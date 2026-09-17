"""Replicated leak detection, with a negative control.

WHY THIS EXISTS -- the measurement that invalidated the old ladder
------------------------------------------------------------------
The single-run leak ladder reported an average-precision ratio per channel and
declared a channel "detected" when that ratio cleared 1.50. On 2026-08-20 the
noise floor was measured for the first time:

    identical data, identical hyperparameters, identical random_state=0,
    only the TRAINING ROW ORDER permuted

    AP = 0.2323, 0.2341, 0.2630, 0.2277        spread 15.5% relative

Repeated fits at a FIXED row order are bit-identical, so the pipeline is
reproducible. But row order is an arbitrary implementation detail -- it changed
merely because txn_id moved from a sort key to a file offset -- and the reported
metric moves 15% with it.

Consequences for the old ladder:
  * a measured ratio of 1.13 cannot be distinguished from 1.00 on one fit
  * the 1.50 threshold was chosen without knowing the noise floor
  * the clean baseline itself moved -9.6% between two runs of the same code,
    which is inside the noise band

So no single-fit ratio supports a detection claim. This module replaces the
point estimate with a distribution, and adds the control the harness never had.

THE NEGATIVE CONTROL, AND WHY IT IS THE RIGHT ONE
--------------------------------------------------
A positive control already exists: a label-derived feature must be detected. The
missing half is a NEGATIVE control -- something that must NOT be detected, so
that "detected" means more than "the number went up".

The placebo here is the real leak columns with their rows PERMUTED. That keeps
every column's marginal distribution exactly, keeps the column count exactly,
and destroys only the row-level correspondence to the label. Anything the model
still extracts from it is not information.

It is also the exact failure mode that corrupted the previous ladder: a
misaligned leak join. So the placebo measures, directly, what a broken join
looks like -- which is why a channel must beat it to count as detected.

VERDICT RULE
------------
A channel is detected only if its paired ratio distribution separates from the
placebo's. Nothing is compared against 1.00, because 1.00 is not where the null
sits once the fit carries noise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aml import io
from aml.eval.metrics import evaluate
from aml.features.build import FEATURES
from aml.leakproof.plant import LEAK_COLUMNS
from aml.manifest import Run
from aml.models import config as model_config

# Budgets kept narrow: this module measures detectability, not the metric suite.
BUDGETS = (10, 50, 200)

# A feature derived from the label MUST be detectable. If it is not, the harness
# is blind and no clean result from this pipeline means anything -- so the sweep
# raises rather than reporting.
POSITIVE_CONTROL = "target"


class LeakNotDetectedError(Exception):
    """The harness failed to notice a deliberately planted leak.

    Never caught. If this fires, no result from this pipeline can be trusted --
    not because a leak exists, but because we cannot tell whether one does.
    """


def _fit_score(Xtr, ytr, Xte, seed: int, iters: int):
    """Fit at the SHIPPED hyperparameters, with only the round count overridable.

    Reading the config from aml.models.config rather than restating it matters
    here: if the leak proof fits a different model from the one the project
    reports, every detection verdict describes a configuration nobody ships, and
    nothing errors. The previous version hardcoded learning_rate=0.1 and
    min_samples_leaf=40 as literals, which would have silently drifted the first
    time the production model was retuned.
    """
    clf = model_config.gbdt(seed, max_iter=iters)
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def _permute(df: pd.DataFrame, cols: list[str], seed: int,
             strata: pd.Series | None = None) -> pd.DataFrame:
    """Shuffle the leak columns as a block, WITHIN STRATA.

    As a block, not column-by-column: shuffling each column independently would
    also destroy the correlations among the leak columns, and the only
    difference from the real leak should be its alignment to the row.

    WITHIN STRATA, and this is the correction. The first version permuted
    globally across the whole leak table, which moves a training row's values
    onto a test row and a day-1 row's values onto a day-28 row. That preserves
    only the GLOBAL marginal, so the placebo arm differs from the real arm in
    two ways at once -- alignment (intended) and distribution shift across the
    split and the calendar (not intended) -- and the gap between them can no
    longer be read as "what misalignment costs".

    The stratum is (side, day): permuting inside it holds the split and the
    temporal marginals fixed, so the ONLY thing broken is which row within a day
    on a given side carries which values. That is the null the comparison is
    supposed to be against.

    Strata with a single row cannot be permuted at all and are left alone; they
    are counted by the caller rather than hidden, because a placebo made mostly
    of fixed points is not a placebo.
    """
    out = df.copy()
    rng = np.random.default_rng(seed)
    values = out[cols].to_numpy()
    if strata is None:
        out[cols] = values[rng.permutation(len(out))]
        return out

    idx = np.arange(len(out))
    order = idx.copy()
    for _, rows in pd.Series(idx).groupby(strata.to_numpy()):
        r = rows.to_numpy()
        if r.size > 1:
            order[r] = r[rng.permutation(r.size)]
    out[cols] = values[order]
    return out


def _leak_strata(tr: pd.DataFrame, te: pd.DataFrame,
                 table: pd.DataFrame) -> pd.Series:
    """(side, day) per leak-table row, in the table's own order."""
    key = pd.concat([
        pd.DataFrame({"txn_id": tr.txn_id.to_numpy(), "_side": "train",
                      "_day": tr.event_date.to_numpy()}),
        pd.DataFrame({"txn_id": te.txn_id.to_numpy(), "_side": "test",
                      "_day": te.event_date.to_numpy()}),
    ], ignore_index=True)
    j = table[["txn_id"]].merge(key, on="txn_id", how="left", validate="one_to_one")
    return j["_side"].astype(str) + "|" + j["_day"].astype(str)


def _merge_leak(frame: pd.DataFrame, table: pd.DataFrame,
                cols: list[str], arm: str, kind: str) -> pd.DataFrame:
    """Left-join the leak columns, refusing a partial join.

    `validate="one_to_one"` checks CARDINALITY, not COVERAGE: a left merge whose
    right side is missing keys succeeds and fills NaN, and a histogram model
    consumes NaN happily as its own branch. So a leak channel that covered half
    the rows would look like a weaker leak rather than a broken join, which is
    the exact confusion this module exists to prevent.
    """
    n = len(frame)
    out = frame.merge(table, on="txn_id", how="left", validate="one_to_one",
                      indicator="_join")
    if len(out) != n:
        raise ValueError(f"{kind}::{arm} merge changed the row count: "
                         f"{n} -> {len(out)}")

    # COVERAGE, NOT NULLNESS -- and the difference matters.
    #
    # The first version of this check asserted that no leak column was null
    # after the merge. It fired immediately on `reversed_window`, reporting
    # 186,731 of 2,284,182 training rows with "no leak values", and it was
    # wrong: the leak table covers all 5,078,345 transactions with no missing
    # keys. Those nulls are LEGITIMATE. `s_max_amt_next_7d` is a MAX over a
    # forward window and is null when the window is empty -- which is a real
    # property of the planted feature, not a broken join.
    #
    # So the check is the one that was actually wanted: did every row find a
    # partner? The merge indicator answers that exactly, and cannot be confused
    # by a feature that is null on purpose.
    unmatched = int((out["_join"] == "left_only").sum())
    if unmatched:
        raise ValueError(
            f"{kind}::{arm}: {unmatched} of {n} rows matched no leak row. The "
            f"leak table does not cover the split; a partial join reads as a "
            f"weak leak rather than a broken one.")
    return out.drop(columns="_join")


def _one_seed(tr, te, leak_tables: dict, seed: int, iters: int) -> dict:
    """One clean fit, then every (channel, placebo) fit paired against it.

    The clean fit is shared within a seed on purpose: the ratio is then a PAIRED
    comparison against the same denominator, which removes the clean baseline's
    own run-to-run variance from the contrast.
    """
    ytr = tr.is_laundering.to_numpy()
    honest_tr = tr[FEATURES].to_numpy(dtype=np.float32)
    honest_te = te[FEATURES].to_numpy(dtype=np.float32)

    clean = evaluate(te, _fit_score(honest_tr, ytr, honest_te, seed, iters),
                     budgets=BUDGETS, per_typology=False)
    out = {"seed": seed, "clean": _slim(clean), "channels": {}}

    for kind, lk in leak_tables.items():
        cols = LEAK_COLUMNS[kind]
        strata = _leak_strata(tr, te, lk)
        for arm in ("real", "placebo"):
            table = (lk if arm == "real"
                     else _permute(lk, cols, seed=1000 + seed, strata=strata))
            a = _merge_leak(tr, table, cols, arm, kind)
            b = _merge_leak(te, table, cols, arm, kind)
            cheat = FEATURES + cols
            leaky = evaluate(
                b, _fit_score(a[cheat].to_numpy(dtype=np.float32),
                              a.is_laundering.to_numpy(),
                              b[cheat].to_numpy(dtype=np.float32), seed, iters),
                budgets=BUDGETS, per_typology=False)
            out["channels"][f"{kind}::{arm}"] = {
                **_slim(leaky),
                "average_precision_ratio": _ratio(leaky, clean),
                "error_reduction@50": _err_red(clean, leaky),
                "n_leak_columns": len(cols),
            }
            print(io.json_line({"event": "sweep_fit", "seed": seed, "kind": kind,
                              "arm": arm,
                              "ap_ratio": round(_ratio(leaky, clean), 4)}), flush=True)
    return out


def _slim(m: dict) -> dict:
    keep = ["average_precision__txn", "recall_efficiency@50", "recall@50", "precision@50"]
    return {k: m[k] for k in keep if k in m}


def _ratio(leaky: dict, clean: dict) -> float:
    c = clean["average_precision__txn"]
    return leaky["average_precision__txn"] / c if c else float("inf")


def _err_red(clean: dict, leaky: dict) -> float:
    base, leak = clean["recall_efficiency@50"], leaky["recall_efficiency@50"]
    return (leak - base) / (1 - base) if base < 1 else 0.0


def run(features: str, splits: str, leak_root: str, dest: str,
        kinds=("reversed_window", "future_counterparty", "target"),
        seeds=(0, 1, 2, 3, 4), iters: int = 300, sample: float = 1.0):
    """Fit every (seed, channel, arm) combination and write the distributions."""
    from aml.models.train import load_split

    features, splits, dest = str(features), str(splits), str(dest)
    cfg = {"features": features, "splits": splits, "leak_root": str(leak_root),
           "kinds": list(kinds), "seeds": list(seeds), "iters": iters,
           "sample": sample, "sweep_version": "2.0.0",
           # The clean arm's feature set decides what a leak is being measured
           # against, so it belongs in the identity of the run. See the note in
           # models/stability.py for the run that proved this the hard way.
           "feature_set": list(FEATURES), "n_features": len(FEATURES),
           "design": "paired within seed; placebo = leak columns permuted "
                     "WITHIN (split side, day)",
           "placebo_strata": "side|event_date", "sweep_version_note":
               "2.0.0 changed the placebo from a global permutation to a "
               "stratified one; numbers are not comparable to 1.1.0"}

    with Run("leak_sweep", cfg, dest) as run_:
        tr, te = load_split(features, splits, sample=sample)
        leak_tables = {
            k: pd.read_parquet(io.join(leak_root, k, "leak.parquet")) for k in kinds
        }
        per_seed = [_one_seed(tr, te, leak_tables, s, iters) for s in seeds]
        io.ensure_dir(dest)
        io.write_json(io.join(dest, "sweep_raw.json"), per_seed, default=str)

        summary = summarise(per_seed, kinds)
        io.write_json(io.join(dest, "sweep_summary.json"), summary, default=str)
        run_.record(n_seeds=len(seeds), n_fits=len(seeds) * (1 + 2 * len(kinds)),
                    train_rows=len(tr), test_rows=len(te), **summary["headline"])
        print(io.json_line({"event": "leak_sweep_complete", **summary["headline"]}))

        # THE GATE. Results are written first, deliberately: if this raises, the
        # numbers that justify the failure are already on disk, and Run.__exit__
        # still records status=failed.
        #
        # Gated on the positive control ONLY. Whether a given temporal bug is
        # detectable is an empirical question -- `reversed_window` is not, and
        # forcing every planted channel to trip would mean tuning leaks until
        # they did, which proves nothing.
        if POSITIVE_CONTROL in kinds and not summary["headline"][
                "positive_control_separates"]:
            row = next(r for r in summary["ladder"] if r["kind"] == POSITIVE_CONTROL)
            raise LeakNotDetectedError(
                f"POSITIVE CONTROL FAILED. A label-derived feature did not "
                f"separate from its own row-permuted placebo: real AP ratio "
                f"{row['ap_ratio_real_mean']} {row['ap_ratio_real_range']} vs "
                f"placebo {row['ap_ratio_placebo_mean']} "
                f"{row['ap_ratio_placebo_range']}. The harness cannot see "
                f"leakage it was handed on a plate, so no clean result from this "
                f"pipeline is verified."
            )
        return summary


def summarise(per_seed: list, kinds) -> dict:
    """Per-channel distributions, and a verdict that beats the placebo or fails."""
    def col(key, field):
        return np.array([s["channels"][key][field] for s in per_seed], dtype=float)

    clean_ap = np.array([s["clean"]["average_precision__txn"] for s in per_seed])
    rows, verdicts = [], {}
    for kind in kinds:
        real = col(f"{kind}::real", "average_precision_ratio")
        plac = col(f"{kind}::placebo", "average_precision_ratio")
        # Paired within seed: same clean denominator, same row order, so the
        # difference isolates alignment.
        diff = real - plac
        detected = bool(diff.min() > 0 and real.min() > plac.max())
        rows.append({
            "kind": kind,
            "ap_ratio_real_mean": round(float(real.mean()), 4),
            "ap_ratio_real_range": [round(float(real.min()), 4), round(float(real.max()), 4)],
            "ap_ratio_placebo_mean": round(float(plac.mean()), 4),
            "ap_ratio_placebo_range": [round(float(plac.min()), 4), round(float(plac.max()), 4)],
            "paired_diff_mean": round(float(diff.mean()), 4),
            "paired_diff_range": [round(float(diff.min()), 4), round(float(diff.max()), 4)],
            "separates_from_placebo": detected,
            "error_reduction_real_mean": round(float(col(f"{kind}::real",
                                                         "error_reduction@50").mean()), 4),
            "error_reduction_placebo_mean": round(float(col(f"{kind}::placebo",
                                                            "error_reduction@50").mean()), 4),
        })
        verdicts[kind] = detected

    # The noise floor, stated as a number rather than assumed: how far the
    # placebo -- which carries no information by construction -- wanders from 1.
    plac_all = np.concatenate([col(f"{k}::placebo", "average_precision_ratio")
                               for k in kinds])
    return {
        "ladder": rows,
        "noise_floor": {
            "placebo_ap_ratio_mean": round(float(plac_all.mean()), 4),
            "placebo_ap_ratio_min": round(float(plac_all.min()), 4),
            "placebo_ap_ratio_max": round(float(plac_all.max()), 4),
            "placebo_spread_pct": round(float(100 * (plac_all.max() - plac_all.min())
                                              / plac_all.mean()), 2),
            "clean_ap_mean": round(float(clean_ap.mean()), 5),
            "clean_ap_range": [round(float(clean_ap.min()), 5),
                               round(float(clean_ap.max()), 5)],
            "clean_ap_spread_pct": round(float(100 * (clean_ap.max() - clean_ap.min())
                                               / clean_ap.mean()), 2),
        },
        "headline": {
            "channels_separating_from_placebo": sum(verdicts.values()),
            "channels_tested": len(verdicts),
            "positive_control_separates": verdicts.get("target", False),
        },
    }
