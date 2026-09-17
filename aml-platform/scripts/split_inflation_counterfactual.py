"""Decompose the split-inflation AP gap WITHOUT assuming AP scales with prevalence.

The first analysis divided the AP ratio by the prevalence ratio and called the
remainder the non-prevalence part. Two things were wrong with that, and an
external audit caught both:

  1. **AP does not generally scale linearly with prevalence.** It equals
     prevalence for a RANDOM ranker; for a fixed good ranker the relationship is
     not proportional, so the division has no justification.
  2. **The arithmetic did not say what it was reported as saying.** A residual
     ratio of 1.0296 is a 2.96% residual RATIO. It is not "97% of the uplift".
     Allocating the excess directly gives 0.3596/0.3999 = 89.9%; a log-ratio
     allocation gives 91.3%. Neither is 97%.

THE REPLACEMENT IS A COUNTERFACTUAL, NOT AN IDENTITY.

The naive test set is exactly the ring-aware test set plus 966 rows, every one
of them a laundering transaction. So the question "how much of the AP gap is
because there are MORE positives, and how much is because those positives are
EASIER?" has a direct answer that needs no model of how AP responds to
prevalence:

    AP_ring_aware      the smaller set, as published
    AP_naive_actual    the larger set with the real scores
    AP_naive_cf        the larger set, with the 966 added positives given
                       scores RESAMPLED FROM THE RETAINED POSITIVES -- i.e.
                       positives that are typical rather than easy

    prevalence effect    = AP_naive_cf     - AP_ring_aware
    detectability effect = AP_naive_actual - AP_naive_cf

Both effects are measured on the same metric, the same ranker and the same
rows; only the scores of the added rows are counterfactual. The split between
them is then a statement about this data rather than about a functional form.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


def load_seed(gold: Path, variant: str, seed: int) -> pd.DataFrame:
    """(score, y, excluded) for every row of the NAIVE test set, IN TXN ORDER.

    ⚠️ `ORDER BY s.txn_id` is not cosmetic, and its absence was found by trying
    to regenerate this artifact and getting different numbers from identical
    code and an identical seed.

    DuckDB's hash join is parallel and emits rows in whatever order the
    workers finish in. `decompose` then builds its counterfactual pool as
    `s[(~exc) & (y == 1)]` -- an array whose ORDER is that scan order -- and
    draws from it with `rng.choice`. Same RNG state, differently ordered pool,
    different values drawn. Every one of the five seeds moved in the fourth
    significant figure. The headline share is stable to three decimals either
    way -- the canonical artifact reports it, and this comment deliberately
    does not, because a result value hardcoded in a source comment is one more
    place for a number to go stale. An audit caught this comment quoting an
    intermediate regeneration that no artifact ever held.

    That is small. It is also the exact defect this project retracted a
    HI-Medium lineage over: a result that depends on a scan order nothing
    determines. It was in the generator of a published decomposition, and no
    test would have found it, because nothing ever asked the script to produce
    the same answer twice.

    Reconstructed from committed artifacts rather than from a splits directory:
    the naive scores name every naive test row, and the ring-aware split names
    the retained ones. Their difference is the excluded set.
    """
    naive = gold / f"infl_fit_naive_s{seed}" / "gbdt_test_scores.parquet"
    naive_dir = gold / f"infl_splits_naive_{variant}" / "test"
    ring_dir = gold / f"infl_splits_ring-aware_{variant}" / "test"

    # LABELS COME FROM THE NAIVE SPLIT, not from the exclusion itself.
    #
    # The first version read labels from the RING-AWARE split and filled
    # `COALESCE(r.is_laundering, 1)` for rows the ring-aware set does not
    # contain -- then "checked" that every excluded row had y = 1. That check
    # was a tautology: it verified the constant it had just assigned. An audit
    # caught it, and it is the kind of self-confirming assertion this project
    # exists to object to.
    #
    # Both label sources are now read independently and compared.
    con = duckdb.connect()
    df = con.execute(f"""
        WITH s AS (SELECT txn_id, score FROM read_parquet('{naive}')),
             n AS (SELECT txn_id, is_laundering
                   FROM read_parquet('{naive_dir}/**/*.parquet', hive_partitioning=true)),
             r AS (SELECT txn_id, is_laundering AS ring_y
                   FROM read_parquet('{ring_dir}/**/*.parquet', hive_partitioning=true))
        SELECT s.txn_id, s.score, n.is_laundering AS y,
               (r.txn_id IS NULL) AS excluded, r.ring_y
        FROM s JOIN n USING (txn_id) LEFT JOIN r USING (txn_id)
        ORDER BY s.txn_id
    """).df()
    con.close()

    # Where both protocols keep a row, their labels must agree. That is a real
    # check: two independent reads of the same transaction.
    both = df[~df.excluded]
    if not (both.y == both.ring_y).all():
        raise SystemExit(
            f"{int((both.y != both.ring_y).sum())} retained rows have different "
            f"labels in the two splits; the reconstruction is wrong")

    n_excluded_pos = int(df.loc[df.excluded, "y"].sum())
    n_excluded = int(df.excluded.sum())
    # NOT asserted -- measured and reported. That every excluded row happens to
    # be a positive is a finding about this generator's labelling, and a
    # finding is not something to assert into existence.
    df.attrs["excluded_rows"] = n_excluded
    df.attrs["excluded_positives"] = n_excluded_pos
    return df.drop(columns="ring_y")


def decompose(df: pd.DataFrame, draws: int, rng) -> dict:
    y = df.y.to_numpy().astype(np.int8)
    s = df.score.to_numpy()
    exc = df.excluded.to_numpy()

    ap_naive = float(average_precision_score(y, s))
    ap_ring = float(average_precision_score(y[~exc], s[~exc]))

    # The pool the counterfactual draws from: positives that BOTH protocols keep.
    retained_pos = s[(~exc) & (y == 1)]
    cf = np.empty(draws)
    s_cf = s.copy()
    idx = np.flatnonzero(exc)
    for i in range(draws):
        s_cf[idx] = rng.choice(retained_pos, size=idx.size, replace=True)
        cf[i] = average_precision_score(y, s_cf)

    ap_cf = float(cf.mean())
    total = ap_naive - ap_ring
    prevalence = ap_cf - ap_ring
    detect = ap_naive - ap_cf
    return {
        "ap_ring_aware": ap_ring, "ap_naive_actual": ap_naive,
        "ap_naive_counterfactual_mean": ap_cf,
        "ap_naive_counterfactual_lo": float(np.percentile(cf, 2.5)),
        "ap_naive_counterfactual_hi": float(np.percentile(cf, 97.5)),
        "total_gap": total,
        # CONTRASTS, NOT EFFECTS, and the field names used to say otherwise.
        #
        # `prevalence_effect` / `detectability_effect` read as causal
        # quantities in a schema that has no design to identify one. The paper
        # states the exchangeability assumption; the artifact did not, and an
        # audit was right that a machine-readable field carrying the stronger
        # word is the one a downstream reader will copy. The old names are kept
        # as aliases so existing references resolve, and marked.
        "composition_contrast": prevalence,
        "score_distribution_contrast": detect,
        "prevalence_effect": prevalence,
        "detectability_effect": detect,
        "_deprecated_field_names": {
            "prevalence_effect": "composition_contrast",
            "detectability_effect": "score_distribution_contrast",
            "why": "they name causal effects; this design measures contrasts",
        },
        "prevalence_share": prevalence / total if total else None,
        "detectability_share": detect / total if total else None,
        "n_excluded": int(idx.size), "n_retained_positives": int(retained_pos.size),
        "n_excluded_positives": int(df.attrs.get("excluded_positives", -1)),
        "excluded_all_positive": (df.attrs.get("excluded_positives")
                                  == df.attrs.get("excluded_rows")),
        "draws": draws,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="data/gold", type=Path)
    ap.add_argument("--variant", default="Small")
    ap.add_argument("--seeds", default="0,1,2,3,4")
    # 400, not 60. Sixty draws is thin for a headline decomposition; the audit
    # was right that the seed range shown is a spread, not an inferential
    # interval. More draws shrink the Monte Carlo component of that spread so
    # the residual is seed-to-seed variation, which is the thing worth showing.
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--out",
                    default="results_archive/derived/split_inflation_counterfactual.json")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    from aml.manifest import generator_provenance
    rng = np.random.default_rng(0)
    per_seed = {}
    for seed in (int(x) for x in a.seeds.split(",")):
        t0 = time.time()
        d = decompose(load_seed(a.gold, a.variant, seed), a.draws, rng)
        per_seed[seed] = d
        print(f"  seed {seed}: ring {d['ap_ring_aware']:.5f}  naive {d['ap_naive_actual']:.5f}"
              f"  cf {d['ap_naive_counterfactual_mean']:.5f}"
              f"  prevalence share {d['prevalence_share']:.3f}"
              f"  ({time.time()-t0:.0f}s)")

    shares = [d["prevalence_share"] for d in per_seed.values()]
    out = {
        # Generator named and hashed, and the path is relative to the GIT ROOT
        # so `git cat-file -e <sha>:<path>` resolves. Three derived artifacts
        # once recorded a commit that did not contain the script that produced
        # them; a commit is not provenance for code absent from it.
        **generator_provenance(
            __file__,
            inputs=[a.gold],
            parameters={"gold": str(a.gold), "variant": a.variant,
                        "seeds": a.seeds, "draws": a.draws}),
        "method": "counterfactual rescoring of the excluded positives from the "
                  "retained-positive score distribution; no assumption about how "
                  "AP responds to prevalence",
        # THE ESTIMAND, AND WHAT IT RESTS ON, in the artifact rather than only
        # in the paper. The two disagreed: the paper stated the assumption and
        # the artifact's short method note omitted it.
        "estimand": "the share of the observed average-precision CONTRAST "
                    "between the naive and ring-aware test sets that remains "
                    "when the excluded positives are given score-typical "
                    "values. Not a causal effect and not an identification of "
                    "leakage.",
        "assumptions": [
            "Excluded and retained positives are EXCHANGEABLE UNCONDITIONALLY: "
            "the resample conditions on no covariate. This is false by "
            "construction -- a positive is excluded because its ring reuses "
            "accounts, which correlates with day, typology, ring size and "
            "account history -- so read the split as a sensitivity analysis, "
            "not a decomposition.",
            "Average precision is computed on the same ranker and the same "
            "rows in both arms; only the excluded rows' scores are altered.",
            "The seed range is a spread across five optimizer seeds on one "
            "dataset and one split, not an inferential interval.",
        ],
        "does_not_establish": "that the score-distribution component is "
                              "train/test contamination. It is CONSISTENT with "
                              "contamination and does not identify it.",
        "supersedes": "the AP-ratio / prevalence-ratio division in "
                      "analyze_split_inflation.py, and the '97%' figure derived "
                      "from it",
        "per_seed": per_seed,
        "prevalence_share_mean": statistics.fmean(shares),
        "prevalence_share_min": min(shares), "prevalence_share_max": max(shares),
        "detectability_share_mean": 1 - statistics.fmean(shares),
    }
    d = Path(a.out)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    print(f"\nprevalence share of the AP gap: mean {out['prevalence_share_mean']:.4f} "
          f"[{out['prevalence_share_min']:.4f}, {out['prevalence_share_max']:.4f}]")
    print(f"detectability share:            mean {out['detectability_share_mean']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
