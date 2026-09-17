# Measured results

Each file states what may and may not be claimed from it. Read
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) first — it carries the
retractions, and two of the headline readings below are withdrawn there.

> This index sold a withdrawn claim for three audits. It described the
> typology result as "significant on HI-Medium" — retracted, see that file —
> and nothing caught it: the retraction registry <!-- historical -->
> matched the withdrawn *number*, and an index restates *claims*. The registry
> now carries prose patterns, and this file is inside the publication gate.

| file | what it measures | status |
|---|---|---|
| [`RESULTS_hi_large.md`](RESULTS_hi_large.md) | the 179.7M-row run: `recall@200`, `ring_recall@200` and its within-day permutation null. Contains the **sign reversal** (lift 1.43 → 0.9497) that is this project's central methodological finding | current |
| [`RESULTS_metric_stability.md`](RESULTS_metric_stability.md) | eight-seed spread of the budget metrics, and the mechanism: `random_state`'s only live consumer is a 200,000-row histogram bin subsample | current, with a thread-count caveat in §3c |
| [`RESULTS_leak_detection.md`](RESULTS_leak_detection.md) | the permuted-leak placebo and the 46.1% noise floor; per-channel verdicts are **not** stable across placebo designs | current |
| [`RESULTS_graph_features.md`](RESULTS_graph_features.md) | three paired A/B rounds where adding features made detection worse. ⚠️ The p-values are the **floor** of an n=8 sign test | current, estimand narrowed |
| [`RESULTS_typology.md`](RESULTS_typology.md) | per-structure detection, and the **withdrawal** of the spread published from it: its H0 was false, and the ensemble result has never been tested under a like-for-like null. A single-seed diagnostic is reported as a diagnostic only. **No claim about laundering structure is made from this benchmark** | current, headline withdrawn |
| [`RESULTS_split_inflation.md`](RESULTS_split_inflation.md) | what a naive temporal split reports, decomposed into prevalence and detectability under an exchangeability assumption | current |
| [`PREREGISTRATION_split_inflation.md`](PREREGISTRATION_split_inflation.md) | the above, written before it was run | record |
| [`archive/`](archive/) | superseded versions | ⛔ stale by definition, excluded from the publication gate |

## Two things to know before reading any number here

1. **The test window contains two regimes.** AMLworld's generator winds down —
   HI-Medium goes from 3,021,866 transactions a day at 0.0008 laundering to
   2,020 at 0.5936 — and every pooled budget metric averages both. See
   [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1 and
   `results_archive/derived/window_decomposition.json`.
2. **Every decimal in these files is checked against an artifact** by
   `scripts/make_tables.py --check --gate`, which also fails on any value the
   retraction registry has retired. A line may carry
   `<!-- derived: <arithmetic or value = reason> -->`, which states what a
   computed value comes from and is itself checked — the arithmetic is
   evaluated and must match a value on the line. A bare `<!-- derived -->` is
   rejected. `<!-- historical -->` quotes a withdrawn figure as a record, and
   the value must still exist in an artifact.
