"""Does the 'largely linear' claim survive removing the hashed categoricals?

H7. `payment_format` and `receiving_currency` enter the feature vector as
`DuckDB hash(value) % 1000` -- a NUMBER. A logistic regression then treats
bucket 17 as lying between 16 and 18, which is meaningless as a category but is
not noise: the model can fit real structure in hash order. So part of what the
headline linear baseline exploits may be the ENCODING rather than the data, and
the claim "most of the separability is linear" cannot be evaluated until that
is measured.

Three arms, same split, same seed, same everything else:

    full          the published 32 features
    no-categorical  the 30 features with both hashed codes removed
    onehot        the hashed codes replaced by explicit one-hot indicators
                  over the values present in TRAINING only, with an
                  everything-else column

If `full` and `onehot` agree, the hash encoding is not doing anything a proper
categorical encoding would not. If `full` beats both, the linear model is
exploiting hash order and the claim must be narrowed further.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

CATEGORICAL = ["payment_format_code", "payment_currency_code"]


def segment_metrics(te, scores, budgets, thin_from) -> dict:
    """Per-arm precision@k split by window segment, WITH a random-ranker null.

    WITHOUT THIS A RERUN RE-ANSWERS A RETRACTED QUESTION. The arms were
    compared on POOLED `precision@50`, and a pooled budget level on this window
    beats a uniformly random ranker by only 1.16x-1.26x
    (`docs/LIMITATIONS.md` section 1) -- so three arms agreeing to 1% agreed
    about the window, not about the encoding. The encoding question needs the
    volume segment and a null on that segment.

    ⛔ AND THE FIRST WORKING VERSION ANSWERED IT IN THE WRONG UNIT. It ranked
    TRANSACTION rows -- `te.is_laundering`, ranked within `event_date` --
    while every published budget metric in this repository goes through
    `to_account_days`. The two are not interchangeable: an account-day is
    positive if ANY of that account's transactions was laundering, so
    account-day prevalence is strictly the higher, and this function's head
    segment reported a null of 0.00077 where `budget_null.py` computes
    0.00243 for the same rung and the same segment -- a factor of 3.16. Every
    lift it produced was inflated by about that much; `docs/LIMITATIONS.md`
    published them as a decomposition of an ACCOUNT-DAY headline; and the
    artifact ended up carrying `precision@50` twice, at two different units,
    under one key name. `make_tables.UNITS` held the correct unit for
    `precision@50` the entire time and used it only to format a table column.

    The test written to guard the repaired function could not see it either:
    it built a frame with no account column at all, so transactions and
    account-days coincided by construction -- and its own comment called the
    rows account-days.

    THREE DEFECTS THIS FUNCTION SHIPPED WITH, none of which any test executed:

      1. `m is slice(None)` compared the IDENTITY of two separately
         constructed slice objects, so it was always False and the pooled
         branch fell through to `top & slice(None)` -- a TypeError on the
         first call. The whole `--thin-from` path crashed, which is why the
         segmented numbers were never produced.
      2. The docstring cited `0.95x a random ranker`, a figure withdrawn when
         the null was recomputed on the evaluated split.
      3. It promised "plus the random null" in its own first line and computed
         no null at all.

    The null here is the slot-weighted mean of daily prevalence, restricted to
    the same segment -- the value a uniformly random ranker attains -- so each
    arm's level is reported against what chance gives on that segment rather
    than against 1.0 or against the pooled figure.
    """
    import hashlib

    import pandas as pd

    from aml.eval.metrics import to_account_days

    # THE ALERT UNIT, not the row. This is the same call `evaluate` makes, so
    # these segments decompose the published headline rather than a quantity
    # that merely shares its name.
    ad = to_account_days(te, scores)
    day = pd.to_datetime(ad.day).dt.date.to_numpy()
    y = ad.y.to_numpy()
    scores = ad.score.to_numpy()
    head = day < thin_from
    # `None` as the sentinel for "no mask". A slice object cannot be used here
    # -- see defect 1 above.
    segments = (("", None), ("_head", head), ("_tail", ~head))
    # DECLARED, not inferred. `check_units.py` refuses to compare a budget
    # metric across artifacts that do not agree on what an alert is.
    out: dict = {"alert_unit": "account-day"}
    # ONCE. The within-day rank does not depend on the budget, and this was
    # inside the budget loop -- a full groupby-rank over every account-day per
    # budget, on a frame with 27.8M rows at the largest rung.
    r = (pd.DataFrame({"d": day, "s": scores})
         .groupby("d")["s"].rank(ascending=False, method="first").to_numpy())
    for b in budgets:
        top = r <= b
        for lab, m in segments:
            sel = top if m is None else (top & m)
            n = int(sel.sum())
            if not n:
                continue
            tp = int(y[sel].sum())
            out[f"precision@{b}{lab}"] = round(tp / n, 5)
            out[f"alerts@{b}{lab}"] = n
            # THE SUPPORT, published beside the rate. The withdrawn version of
            # this table reported a "43% relative spread" across encodings
            # whose entire content was three alerts -- 7, 9 and 10 true
            # positives out of 350 -- and no reader could recover that from a
            # precision quoted to five decimals. Fisher two-sided on the
            # extremes was p = 0.62; one arm's binomial sd was 2.96 hits,
            # larger than the whole spread.
            out[f"tp@{b}{lab}"] = tp

            # THE NULL, on the same segment and the same slots.
            #
            # A uniformly random ranker fills each day's k slots from that
            # day's population, so its expected precision is the slot-weighted
            # mean of daily prevalence. Computed per day and weighted by the
            # slots the day actually contributes, which is what makes it
            # comparable to the level above.
            keep = np.ones_like(day, dtype=bool) if m is None else m
            frame = pd.DataFrame({"d": day[keep], "y": y[keep]})
            per_day = frame.groupby("d")["y"].agg(["size", "sum", "mean"])
            slots = np.minimum(per_day["size"].to_numpy(), b)
            if slots.sum():
                null = float((slots * per_day["mean"].to_numpy()).sum()
                             / slots.sum())
                out[f"precision_null@{b}{lab}"] = round(null, 5)
                out[f"precision_lift@{b}{lab}"] = (
                    round(out[f"precision@{b}{lab}"] / null, 4) if null else None)
                # AND THE CEILING THE LIFT IS MEASURED AGAINST. A precision
                # lift cannot exceed `ceiling/null`, and on the head segment
                # every day holds far more positives than slots, so the
                # ceiling is 1.0 and the bound is the reciprocal base rate --
                # a property of the generator, not of the ranker. Published
                # bare, "310.3x" reads as unbounded when 75.7% of it is
                # 1/prevalence. This project invented `recall_ceiling@k` for
                # precisely this reason and then published precision lifts
                # without one.
                best = float(np.minimum(per_day["sum"].to_numpy(), b).sum()
                             / slots.sum())
                out[f"precision_ceiling@{b}{lab}"] = round(best, 5)
                out[f"precision_efficiency@{b}{lab}"] = (
                    round(out[f"precision@{b}{lab}"] / best, 4) if best else None)
                out[f"precision_lift_ceiling@{b}{lab}"] = round(best / null, 4)

    # THE PAIRED STATE, for a paired comparison. See `paired_head_tests`.
    hp = head & (y == 1)
    key = np.stack([day[hp].astype("U10"),
                    ad.acct.to_numpy()[hp].astype("U24")], axis=1)
    state = {"order_sha": hashlib.sha256(key.tobytes()).hexdigest()[:16],
             "n_head_positives": int(hp.sum()),
             # THE DAY, because the day is the independent unit. See
             # `paired_head_tests`.
             "day": day[hp].astype("U10"),
             "caught": {b: (r <= b)[hp] for b in budgets}}
    return out, state


def paired_head_tests(states: dict, budgets) -> dict:
    """Exact McNemar between the arms, on the head segment's positives.

    THE ARMS ARE NOT INDEPENDENT SAMPLES. They rank the same account-days, of
    the same days, under the same split, differing only in how two columns are
    encoded -- so comparing their precisions with Fisher's exact test treats a
    paired design as unpaired. Under pairing the quantities that matter are
    the DISCORDANT counts: `b` positives caught by the first arm and missed by
    the second, `c` the reverse. Exact McNemar is a two-sided binomial test on
    b out of b + c.

    The withdrawn version of this table never computed them, so nothing in the
    artifact could show a reader that the comparison had no power. Recording
    them does not rescue the result -- pairing makes a three-alert difference
    WORSE, because a net of 3 cannot reach p < 0.25 under any pairing, which
    removes the "Fisher is conservative, something may be there" escape. It is
    simply the test this design calls for, and it costs two integers.
    """
    import itertools
    from math import comb

    shas = {st["order_sha"] for st in states.values()}
    if len(shas) != 1:
        return {"status": "the arms are not row-aligned, so no paired test is "
                          "possible", "order_shas": sorted(shas)}
    out = {"order_sha": shas.pop(),
           "test": "exact two-sided McNemar on head-segment positives (unit: "
                   "account-day), AND an exact sign test blocked on the day, "
                   "which is the independent unit. Prefer the blocked test, "
                   "and read `smallest_p_attainable_by_design` before "
                   "reading any p-value here.",
           "n_head_positives":
               next(iter(states.values()))["n_head_positives"]}
    raw_p: dict[str, float] = {}
    raw_perm: dict[str, float] = {}
    for bud in budgets:
        for x, y in itertools.combinations(sorted(states), 2):
            cx, cy = states[x]["caught"][bud], states[y]["caught"][bud]
            b, c = int((cx & ~cy).sum()), int((~cx & cy).sum())
            nd = b + c
            p = 1.0 if not nd else min(
                1.0, 2.0 * sum(comb(nd, i) for i in range(min(b, c) + 1))
                / 2 ** nd)

            # ⚠️ AND THE ALERT IS NOT THE INDEPENDENT UNIT. The head segment
            # is a handful of days -- seven on HI-Medium, six on HI-Small --
            # and within a day all three arms re-rank the SAME population, so
            # the discordant alerts cluster by day and their signs are driven
            # by one per-day score reshuffle. An exact binomial over alerts
            # treats 22 correlated observations as 22 independent ones and is
            # anti-conservative.
            #
            # Blocking on the day gives an honest test and, more usefully, an
            # honest BOUND: with d days a two-sided sign test cannot go below
            # 2 * 0.5**d, so at seven days the floor is 0.0156 and after Holm
            # over six comparisons 0.094. Neither rung can reach 0.05 at the
            # correct blocking unit even with a perfect, unanimous result.
            # That bound is the finding; the alert-level p is a footnote.
            days = states[x]["day"]
            per_day = {}
            for dd in np.unique(days):
                m = days == dd
                per_day[str(dd)] = int((cx & ~cy)[m].sum()) - int((~cx & cy)[m].sum())
            fx = sum(1 for v in per_day.values() if v > 0)
            fy = sum(1 for v in per_day.values() if v < 0)
            nz = fx + fy
            p_day = 1.0 if not nz else min(
                1.0, 2.0 * sum(comb(nz, i) for i in range(min(fx, fy) + 1))
                / 2 ** nz)

            # AND THE SAME BLOCKING, WITHOUT THROWING AWAY THE MAGNITUDE. The
            # sign test uses only the direction of each day's net, so a day
            # that moved by 7 alerts counts the same as one that moved by 1 --
            # on HI-Medium that put the best comparison at p = 1.0 while an
            # exact sign-flip permutation on the day-level nets gives 0.1875.
            # Same randomization set, same floor (2 * 0.5**d, because exactly
            # two of the 2**d assignments are at least as extreme), strictly
            # more power. Exhaustive: d <= 7 here, so 128 assignments.
            nets = list(per_day.values())
            obs = abs(sum(nets))
            total = 0
            for mask in range(2 ** len(nets)):
                flipped = sum(v if mask >> i & 1 else -v
                              for i, v in enumerate(nets))
                total += abs(flipped) >= obs - 1e-12
            p_perm = total / 2 ** len(nets) if nets else 1.0
            out[f"{x}_vs_{y}@{bud}"] = {
                f"caught_by_{x}_only": b, f"caught_by_{y}_only": c,
                "n_discordant": nd, "p_exact_mcnemar": round(p, 5),
                "n_head_days": len(per_day),
                f"days_favouring_{x}": fx, f"days_favouring_{y}": fy,
                "p_sign_test_blocked_by_day": round(p_day, 5),
                "p_permutation_blocked_by_day": round(p_perm, 5),
                # FROM THE DESIGN, NOT THE REALISED DATA. This used `nz`,
                # the number of days that happened to split -- so the "floor"
                # moved between comparisons of one identical design (0.03125,
                # 0.0625, 0.125 across six cells) and was post hoc. The bound
                # a reader needs is the one the design fixes in advance: with
                # d head days, a two-sided sign test cannot go below
                # 2 * 0.5**d whatever the data does.
                "smallest_p_attainable_by_design": round(
                    min(1.0, 2.0 * 0.5 ** len(per_day)) if per_day else 1.0, 5),
                "smallest_p_attainable_given_the_ties_observed": round(
                    min(1.0, 2.0 * 0.5 ** nz) if nz else 1.0, 5),
                "net_by_day": per_day}
            raw_p[f"{x}_vs_{y}@{bud}"] = p
            raw_perm[f"{x}_vs_{y}@{bud}"] = p_perm

    # HOLM, OVER THE WHOLE FAMILY. Three arms at two budgets is six tests,
    # and quoting the smallest uncorrected p from six is how a null result
    # becomes a finding. Computed from the UNROUNDED p-values with a running
    # maximum, which is the part this project has previously got wrong twice.
    # FROM THE UNROUNDED VALUES, which this comment already claimed and the
    # code did not do: it read back `out[...]["p_exact_mcnemar"]`, which had
    # already been rounded to five decimals one block earlier. The same defect
    # the typology null carried, reintroduced here on the day it was fixed
    # there.
    def holm(raw: dict, key: str) -> float | None:
        order = sorted(raw, key=lambda k: raw[k])
        running = 0.0
        for rank, name in enumerate(order):
            running = max(running, min(1.0, raw[name] * (len(order) - rank)))
            out[name][key] = round(float(running), 5)
        return min((out[k][key] for k in order), default=None)

    # BOTH FAMILIES, because this block tells the reader to prefer the blocked
    # test and then corrected only the alert-level one. Holm over a test the
    # artifact says to ignore is an adjusted p-value for the wrong question.
    smallest_alert = holm(raw_p, "p_holm")
    smallest_blocked = holm(raw_perm, "p_holm_blocked")
    out["n_tests_in_family"] = len(raw_p)
    out["smallest_p_holm"] = smallest_alert
    out["smallest_p_holm_blocked"] = smallest_blocked
    out["n_significant_after_holm_at_0.05"] = sum(
        v["p_holm_blocked"] < 0.05 for v in out.values()
        if isinstance(v, dict) and "p_holm_blocked" in v)
    out["n_significant_note"] = (
        "counted on the DAY-BLOCKED permutation test, which is the one this "
        "block says to prefer. `p_holm` adjusts the alert-level McNemar "
        "values and is kept only so the two can be compared.")
    return out


def fit_arm(Xtr, ytr, Xte, te, cols, seed, budgets):
    from aml.eval.metrics import evaluate
    from aml.models.train import MODELS
    clf = MODELS["baseline"](seed)
    clf.fit(Xtr, ytr)
    score = clf.predict_proba(Xte)[:, 1]
    m = evaluate(te, score, budgets=budgets, per_typology=False, n_permutations=0)
    # DECLARED at the arm, because these come from `evaluate` and are
    # account-day metrics. `average_precision__txn` carries its own unit in
    # its name and `ring_recall@200` is counted per ring; check_units.py
    # honours both, and it is the alert unit that has to be stated.
    return {"alert_unit": "account-day",
            **{k: m[k] for k in
               ("average_precision__txn", "precision@50", "recall@50",
                "recall_efficiency@50", "ring_recall@200") if k in m}}, score


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--splits", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--thin-from", default=None,
                    help="the rung's transaction-volume collapse date (see "
                         "results_archive/derived/window_decomposition.json, "
                         "first_thin_day). REQUIRED for the arms to be "
                         "comparable: pooled levels on this window are 0.95x "
                         "a random ranker and cannot settle the encoding.")
    ap.add_argument("--out",
                    default="results_archive/derived/categorical_ablation.json")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    from aml.features.build import FEATURES
    from aml.manifest import generator_provenance
    from aml.models.train import load_test, load_train_xy

    idx = {f: i for i, f in enumerate(FEATURES)}
    keep = [i for f, i in idx.items() if f not in CATEGORICAL]

    t0 = time.time()
    # float32 AND freed between arms.
    #
    # The first HI-Medium attempt was OOM-killed at exit 137. The one-hot arm
    # hstacks a wider matrix while the original is still live -- at 19.5M rows
    # and float64 that is 5 GB plus 8 GB, plus the test side, on a 31 GB
    # machine. A logistic baseline does not need float64, and nothing here
    # compares bitwise against a float64 fit.
    Xtr, ytr = load_train_xy(a.features, a.splits, dtype=np.float32)
    Xte, te = load_test(a.features, a.splits, dtype=np.float32)
    budgets = (50, 200)

    out = {**generator_provenance(
               __file__,
               inputs=[Path(a.features), Path(a.splits)],
               # `thin_from` DECIDES WHETHER THE SEGMENTED RESULT EXISTS, so
               # it belongs in the recorded parameters. It was omitted, so an
               # artifact with `by_segment` and one without were
               # indistinguishable from their provenance alone.
               parameters={"features": a.features, "splits": a.splits,
                           "seed": a.seed, "thin_from": a.thin_from}),
           "estimand": (
               "whether the volume-segment precision@k of a linear model on "
               "these 32 features depends on how the two categorical columns "
               "are encoded. The arms differ ONLY in that encoding; the unit "
               "is the account-day throughout, which is the unit every other "
               "budget metric in this repository uses. An earlier version "
               "ranked transaction rows and reported lifts inflated ~3.16x."),
           "seed": a.seed,
           "n_train": len(ytr), "n_test": len(te),
           "categorical_features": CATEGORICAL, "arms": {}}

    full, s_full = fit_arm(Xtr, ytr, Xte, te, FEATURES, a.seed, budgets)
    out["arms"]["full"] = full

    nocat, s_nocat = fit_arm(Xtr[:, keep], ytr, Xte[:, keep], te,
                             [FEATURES[i] for i in keep], a.seed, budgets)
    out["arms"]["no_categorical"] = nocat

    # One-hot over TRAINING values only, plus an "unseen" column. Fitting the
    # vocabulary on train alone is the point: a vocabulary built on the test set
    # is a leak, which is the class of defect this repository exists to catch.
    oh_blocks_tr, oh_blocks_te, vocab = [], [], {}
    for c in CATEGORICAL:
        col = idx[c]
        vals = np.unique(Xtr[:, col])
        vocab[c] = int(vals.size)
        btr = (Xtr[:, [col]] == vals[None, :]).astype(np.float32)
        oh_blocks_tr.append(np.hstack([btr, np.zeros((len(Xtr), 1), np.float32)]))
        bte = (Xte[:, [col]] == vals[None, :]).astype(np.float32)
        unseen = (~bte.any(axis=1)).astype(np.float32)[:, None]
        oh_blocks_te.append(np.hstack([bte, unseen]))
        del btr, bte, unseen
    Xtr_oh = np.hstack([Xtr[:, keep], *oh_blocks_tr])
    del Xtr, oh_blocks_tr                      # 5 GB back before the test side
    Xte_oh = np.hstack([Xte[:, keep], *oh_blocks_te])
    del Xte, oh_blocks_te
    onehot, s_onehot = fit_arm(Xtr_oh, ytr, Xte_oh, te, None, a.seed, budgets)
    del Xtr_oh, Xte_oh
    out["arms"]["onehot"] = onehot
    out["onehot_vocabulary_sizes"] = vocab

    # SEGMENT METRICS FOR EVERY ARM. Pooled levels cannot settle the encoding
    # question on a two-regime window; see `segment_metrics`.
    if a.thin_from:
        import datetime as _dt
        thin = _dt.date.fromisoformat(a.thin_from)
        states = {}
        for name, sc in (("full", s_full), ("no_categorical", s_nocat),
                         ("onehot", s_onehot)):
            seg, states[name] = segment_metrics(te, sc, budgets, thin)
            out["arms"][name]["by_segment"] = seg
        # THE PAIRED COMPARISON, once, across arms. Per-arm levels cannot say
        # whether the arms differ; only the discordant counts can.
        out["paired_head_tests"] = paired_head_tests(states, budgets)
        out["thin_from"] = a.thin_from
    else:
        out["by_segment_note"] = (
            "NOT COMPUTED: pass --thin-from <YYYY-MM-DD> (the rung's "
            "transaction-volume collapse, from window_decomposition.json). "
            "Without it the arms are only comparable on pooled levels, which "
            "this window does not support.")
    out["wall_clock_sec"] = round(time.time() - t0, 1)

    f = out["arms"]["full"]["average_precision__txn"]
    out["ap_ratio_full_over_no_categorical"] = (
        f / out["arms"]["no_categorical"]["average_precision__txn"])
    out["ap_ratio_full_over_onehot"] = (
        f / out["arms"]["onehot"]["average_precision__txn"])

    d = Path(a.out)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "arms"}, indent=1))
    for name, arm in out["arms"].items():
        # SCALARS ONLY. `by_segment` is a nested dict and this formatted every
        # value with `:.5f`, so the segmented path would have raised a
        # TypeError here even after the crash above was fixed.
        flat = {k: v for k, v in arm.items() if isinstance(v, (int, float))}
        print(f"  {name:16s} " + "  ".join(f"{k}={v:.5f}" for k, v in flat.items()))
        seg = arm.get("by_segment")
        if seg:
            for k in sorted(seg):
                v = seg[k]
                print(f"      {k:26s} {v:.5f}" if isinstance(v, (int, float))
                      else f"      {k:26s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
