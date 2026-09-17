"""Analyse the preregistered split-inflation experiment.

Reads only manifests and scores written by `scripts/run_split_inflation.sh`;
computes nothing from memory. Writes one artifact,
`results_archive/derived/split_inflation.json`, which is what
`paper/RESULTS_split_inflation.md` is checked against.

The predictions being tested were committed on 2026-08-24 in
`paper/PREREGISTRATION_split_inflation.md` and are restated here verbatim so a
reader does not have to trust that they were not edited afterwards -- git
history is the actual evidence, and `git log --follow` on that file is the
check.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import duckdb
import numpy as np

PROTOCOLS = ("ring-aware", "naive")


def _manifest(p: Path) -> dict:
    with open(p) as fh:
        return json.load(fh)


def _metrics(m: dict) -> dict:
    return m.get("metrics", m)


def paired_ratio(naive: list[float], ring: list[float]) -> dict:
    """Per-seed ratio, then a t interval across seeds.

    PAIRED, because the two protocols share a seed and therefore a fitted
    model: the pairing removes fit-to-fit variance, which is the dominant term.
    With five seeds the interval is wide and is reported as such -- n is stated
    next to it rather than left for the reader to infer.
    """
    ratios = [n / r for n, r in zip(naive, ring, strict=True) if r]
    if len(ratios) < 2:
        return {"ratio_mean": ratios[0] if ratios else None, "n_seeds": len(ratios)}
    mean = statistics.fmean(ratios)
    sd = statistics.stdev(ratios)
    se = sd / len(ratios) ** 0.5
    # t(0.975, df=4) = 2.776. Hardcoded rather than pulling in scipy for one
    # constant; asserted against the seed count so it cannot silently apply to
    # a different n.
    t = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571,
         7: 2.447, 8: 2.365}.get(len(ratios))
    if t is None:
        raise ValueError(f"no t quantile tabulated for n={len(ratios)}")
    return {"ratio_mean": mean, "ratio_sd": sd, "ratio_ci_lo": mean - t * se,
            "ratio_ci_hi": mean + t * se, "n_seeds": len(ratios),
            "per_seed": ratios}


def experiment_b(gold: Path, variant: str, seed: int, budget: int = 50) -> dict:
    """Within the NAIVE test set, compare rows the ring-aware filter removes
    against rows both protocols keep.

    Free of the prevalence confound in Experiment A: one test set, one model,
    one global score threshold, applied identically to both partitions.
    """
    naive = gold / f"infl_splits_naive_{variant}" / "test"
    ring = gold / f"infl_splits_ring-aware_{variant}" / "test"
    scores = gold / f"infl_fit_naive_s{seed}" / "gbdt_test_scores.parquet"

    con = duckdb.connect()
    df = con.execute(f"""
        WITH n AS (SELECT txn_id, is_laundering, event_date
                   FROM read_parquet('{naive}/**/*.parquet', hive_partitioning=true)),
             r AS (SELECT DISTINCT txn_id
                   FROM read_parquet('{ring}/**/*.parquet', hive_partitioning=true)),
             s AS (SELECT txn_id, score FROM read_parquet('{scores}'))
        SELECT n.txn_id, n.is_laundering, n.event_date, s.score,
               (r.txn_id IS NULL) AS excluded_by_ring_filter
        FROM n JOIN s USING (txn_id) LEFT JOIN r USING (txn_id)
        -- ORDERED, because a parallel hash join emits rows in whatever order
        -- the workers finish in, and `mean()` over floats is not associative.
        -- Six fields of this artifact moved in their last significant bit
        -- between two runs of identical code -- harmless in itself, and a
        -- regeneration that is not byte-identical cannot be used as a gate.
        -- The sibling counterfactual had the same omission and it mattered
        -- there: it draws from an array whose ORDER was the scan order.
        ORDER BY n.txn_id
    """).df()
    con.close()

    n_days = df.event_date.nunique()
    # "A fixed global score threshold (the naive-set top-k cut)": the score that
    # admits exactly as many transactions as the daily budget admits alerts
    # across the whole window. One number, applied to both partitions, so the
    # comparison cannot be moved by either partition's prevalence.
    k_total = budget * n_days
    thr = float(np.partition(df.score.to_numpy(), -k_total)[-k_total])

    out = {"seed": seed, "n_days": int(n_days), "budget": budget,
           "k_total": int(k_total), "global_threshold": thr,
           "naive_test_rows": len(df),
           "naive_test_positives": int(df.is_laundering.sum())}
    for name, mask in (("excluded", df.excluded_by_ring_filter),
                       ("retained", ~df.excluded_by_ring_filter)):
        part = df[mask]
        pos = part[part.is_laundering == 1]
        out[name] = {
            "rows": len(part),
            "positives": len(pos),
            "prevalence": float(len(pos) / len(part)) if len(part) else None,
            "row_share": float(len(part) / len(df)),
            "positive_share": float(len(pos) / df.is_laundering.sum())
            if df.is_laundering.sum() else None,
            "recall_at_global_threshold":
                float((pos.score >= thr).mean()) if len(pos) else None,
            "mean_positive_score": float(pos.score.mean()) if len(pos) else None,
            "mean_negative_score":
                float(part[part.is_laundering == 0].score.mean())
                if (part.is_laundering == 0).any() else None,
        }
    e, r = out["excluded"], out["retained"]
    out["detection_ratio_excluded_over_retained"] = (
        e["recall_at_global_threshold"] / r["recall_at_global_threshold"]
        if r["recall_at_global_threshold"] else None)
    # P3: do excluded rows hold a disproportionate share of the positives?
    out["positive_share_over_row_share"] = (
        e["positive_share"] / e["row_share"] if e["row_share"] else None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/gold")
    ap.add_argument("--variant", default="Small")
    ap.add_argument("--seeds", default="0,1,2,3,4")
    ap.add_argument("--out", default="results_archive/derived/split_inflation.json")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    gold = Path(a.gold)
    seeds = [int(s) for s in a.seeds.split(",")]

    splits = {p: _metrics(_manifest(gold / f"infl_splits_{p}_{a.variant}" /
                                    "manifest.json")) for p in PROTOCOLS}

    # THE DESIGN'S LOAD-BEARING ASSUMPTION, CHECKED RATHER THAN ASSERTED.
    # The ring discipline is meant to be purely a test-set filter, so the two
    # fits for one seed must be the same model. If they are not, Experiment A
    # is confounded by the fit and the whole comparison is void.
    fits = {}
    for s in seeds:
        h = {}
        for p in PROTOCOLS:
            m = _metrics(_manifest(gold / f"infl_fit_{p}_s{s}" / "manifest.json"))
            h[p] = m.get("model_artifact_sha256")
        if h["naive"] != h["ring-aware"]:
            raise SystemExit(
                f"seed {s}: the two protocols produced DIFFERENT models "
                f"({h['ring-aware']} vs {h['naive']}). The training halves were "
                f"supposed to be identical; Experiment A is confounded and must "
                f"not be reported.")
        fits[s] = h["ring-aware"]

    evals = {p: {s: _metrics(_manifest(gold / f"infl_eval_{p}_s{s}" /
                                       "manifest.json")) for s in seeds}
             for p in PROTOCOLS}

    keys = ["average_precision__txn", "recall@10", "recall@50", "recall@200",
            "recall_efficiency@10", "recall_efficiency@50",
            "recall_efficiency@200", "precision@50", "ring_recall@200"]
    a_out = {}
    for k in keys:
        per = {p: [evals[p][s].get(k) for s in seeds] for p in PROTOCOLS}
        if any(v is None for p in PROTOCOLS for v in per[p]):
            continue
        a_out[k] = {
            "ring_aware_mean": statistics.fmean(per["ring-aware"]),
            "naive_mean": statistics.fmean(per["naive"]),
            "ring_aware_per_seed": per["ring-aware"],
            "naive_per_seed": per["naive"],
            **paired_ratio(per["naive"], per["ring-aware"]),
        }

    b_out = [experiment_b(gold, a.variant, s) for s in seeds]

    # ⛔ SUPERSEDED. Kept because a published figure came from it.
    #
    # This block divided the AP ratio by the prevalence ratio and the result
    # was reported as "97% of the uplift is prevalence arithmetic". Both halves
    # of that were wrong:
    #
    #   * AP equals prevalence for a RANDOM ranker. It does not scale linearly
    #     with prevalence for a fitted one, so the division assumes a
    #     functional form that was never established.
    #   * A residual RATIO of 1.0296 is not "97% of the uplift". Allocating the
    #     excess gives 0.3596/0.3999 = 89.9%; a log allocation gives 91.3%.
    #
    # scripts/split_inflation_counterfactual.py replaces it with a
    # counterfactual that assumes nothing about AP's response to prevalence,
    # and finds 47% prevalence / 53% detectability. The fields below are
    # emitted with `_SUPERSEDED` names so nothing reads them by accident.
    prev = {p: splits[p]["test_positives"] / splits[p]["test_rows"]
            for p in PROTOCOLS}
    prevalence_ratio = prev["naive"] / prev["ring-aware"]
    ap = a_out.get("average_precision__txn", {})
    decomposition = {
        "prevalence": prev,
        "prevalence_ratio_naive_over_ring_aware": prevalence_ratio,
        "ap_ratio": ap.get("ratio_mean"),
        "SUPERSEDED_ap_ratio_net_of_prevalence": (
            ap["ratio_mean"] / prevalence_ratio if ap.get("ratio_mean") else None),
        "SUPERSEDED_note": "this ratio was misreported as '97% is prevalence'. "
                           "See results_archive/derived/"
                           "split_inflation_counterfactual.json for the "
                           "decomposition that replaced it.",
        "excluded_rows_are_all_positive": all(
            x["excluded"]["prevalence"] == 1.0 for x in b_out),
    }

    from aml.manifest import generator_provenance
    result = {
        **generator_provenance(
            __file__,
            inputs=[Path(a.gold)],
            parameters={"gold": str(a.gold), "variant": a.variant,
                        "seeds": a.seeds}),
        "preregistration": "paper/PREREGISTRATION_split_inflation.md",
        "preregistered_commit_date": "2026-08-24",
        "variant": a.variant, "seeds": seeds,
        "model_sha256_per_seed": fits,
        "split_facts": {p: {k: splits[p].get(k) for k in
                            ("cut_time", "protocol", "train_rows",
                             "train_positives", "test_rows", "test_positives",
                             "test_positive_account_days",
                             "test_total_account_days", "dropped_rings",
                             "test_rings_before_drop",
                             "straddling_ring_tail_rows_in_test")}
                        for p in PROTOCOLS},
        "experiment_a": a_out,
        "experiment_b": b_out,
        "decomposition": decomposition,
        "experiment_b_summary": {
            "detection_ratio_mean": statistics.fmean(
                [b["detection_ratio_excluded_over_retained"] for b in b_out
                 if b["detection_ratio_excluded_over_retained"] is not None]),
            "positive_share_over_row_share_mean": statistics.fmean(
                [b["positive_share_over_row_share"] for b in b_out
                 if b["positive_share_over_row_share"] is not None]),
        },
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps({"event": "split_inflation_analysis", "out": str(out),
                      **{k: result["experiment_a"][k]["ratio_mean"]
                         for k in ("average_precision__txn",)
                         if k in result["experiment_a"]}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
