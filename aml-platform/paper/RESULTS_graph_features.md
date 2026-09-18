# Results: adding network-shaped features made detection worse

> ⛔ **READ THIS FIRST — every pooled budget metric below averages two
> regimes.** AMLworld's generator winds down: HI-Medium goes from 3,021,866
> transactions a day at 0.0008 laundering to 2,020 at 0.5936 overnight, and
> HI-Small does the same at 2022-09-11. A uniformly random ranker therefore
> scores `precision@50` = 0.45392-0.49147 on the HI-Medium ring-aware test
> split, so a pooled level near that is near chance. On three of the nineteen
> days the budget exceeds the population entirely and no ranking is being
> tested.
>
> Read pooled levels here as descriptions of a window, never as model
> comparisons. The decomposition and the null are in
> [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1,
> `results_archive/derived/window_decomposition.json` and
> `results_archive/derived/budget_null.json`.

**Runs:** `data/gold/graph_ab0_Small` (baseline), `graph_ab3_Small` (counts),
`graph_ratio_Small` (ratios) · 2026-08-28
**Setup:** HI-Small, 8 seeds, paired within seed, identical split, identical
model config, `sample=1.0`, same feature parquet for all three arms.

---

## 1. What was tested, and what it is NOT

⚠️ **These are not graph features, and the honest claim is narrower than
"graph features do not help AML."**

Every feature tested here is computed from **one account's own event stream**.
That is a time series. FAN-IN, FAN-OUT, CYCLE and STACK are properties of the
**subgraph** — who your counterparties deal with, whether money returns to you.
No per-account trailing count can observe that. A real test of graph structure
would need 2-hop neighbourhoods, triangles or cycle detection, none of which
were built here.

| arm | features | what it measures |
|---|---|---|
| baseline | 32 | transaction + per-account history |
| counts | 34 | `+ s/r_n_new_cp_7d` — first contacts in the trailing week |
| ratios | 36 | `+ s/r_new_cp_rate_7d`, `s/r_out_share_7d` — volume-normalised |

## 2. The measurement

Paired within seed. The reported test is an **exact two-sided sign test** over
the 8 per-seed differences; ties are dropped, which is why *n* differs between
arms.

| metric | baseline | +2 counts | +4 ratios |
|---|---|---|---|
| average_precision (mean) | 0.19379 | 0.17869 (−7.8%) | 0.16458 (−15.1%) |
| ring_recall@200 (mean) | 0.83156 | 0.78901 (−5.1%) | 0.77837 (−6.4%) |
| recall_efficiency@50 (mean) | 0.71335 | 0.71859 (+0.7%) | 0.68281 (−4.3%) |
| ensemble average_precision | 0.21147 | 0.19026 | 0.17740 |
| ensemble ring_recall@200 | 0.85816 | 0.80142 | 0.78014 |

**ring_recall@200, per seed:**

```text
+2 counts   0 better, 8 worse, 0 tied   n=8   p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact and cannot be -->
+4 ratios   0 better, 7 worse, 1 TIED   n=7   p = 0.0156  <!-- derived: 0.0156 = the smallest two-sided sign-test p-value attainable on 7 paired observations, 2/2**7. A property of the DESIGN, not a measurement, so it is in no artifact -->
```

The tie matters. Writing the ratio arm as "0 of 8 improved" is true and
misleading: it hides why the two p-values differ despite both showing zero
improvements. Report better/worse/tied.

`recall_efficiency@50` is unchanged for the counts arm (5 of 8 better,
p=0.7266) — this is a null, not a gain.

## 3. Why the count features failed: they are volume in disguise

| feature | strongest correlation with an existing feature |
|---|---|
| `s_n_new_cp_7d` | **0.977** with `s_n_7d`, `s_n_out_7d`, `s_n_30d` |
| `r_n_new_cp_7d` | **1.000** with `r_n_1d` |

In this data almost every counterparty is new, so "count of new counterparties
this week" **is** "count of transactions this week". The model already had that
column. A near-duplicate carries no information and still competes for splits.

## 4. Why the ratio features failed differently: no signal

Dividing volume out works — the ratio features are genuinely not redundant
(max |r| against any existing feature is 0.22–0.52). They failed anyway,
because they barely separate the classes:

```text
s_new_cp_rate_7d   positives / negatives = 1.034 <!-- derived: 1.034 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived. It passed the gate until now only because an unrelated typology concentration happened to round to it -->
r_new_cp_rate_7d                           1.044 <!-- derived: 1.044 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived -->
r_out_share_7d                             1.026 <!-- derived: 1.026 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived -->
s_out_share_7d                             0.852   <- the only real one
```

Compare `s_n_new_cp_7d` at 2.273. Against **1,528 training positives** — 47.8 <!-- derived: 2.273 = the feature's positives/negatives mean ratio from the separation diagnostic, which is not archived -->
per feature at 32 features — a near-noise column is a pure variance cost, and
four of them cost more than two.

## 5. Reconciling this with the 46.10% placebo noise floor

`RESULTS_leak_detection.md` measures a placebo AP-ratio spread of **46.10%**,
which is nearly ten times the −5.1% effect claimed here. These are not in
conflict — but the reason this section used to give was wrong twice over, and
both errors are worth keeping on the record:

> ⚠️ It cited the floor as **22%** and explained the gap by calling the placebo
> floor "unpaired". The 22% figure is the **superseded 1.1.0** sweep
> (`leaksweep_Small`); the corrected stratified placebo is 46.10%, i.e. the
> gap it was explaining is twice as wide as it said. And "unpaired" is
> contradicted by the code: `src/aml/leakproof/sweep.py:188` shares one clean
> fit per seed precisely so that "the ratio is then a PAIRED comparison
> against the same denominator". Both designs are paired. <!-- historical -->

The actual reconciliation is that the two numbers are different *kinds* of
statistic:

- the **noise floor is an across-seed dispersion** — (max − min) / mean over
  eight independently seeded placebo ratios. It answers "how far apart can two
  runs land?"
- the **A/B test is a within-seed paired sign test** — each seed contributes
  one signed difference between its own with-features and without-features
  arms. It answers "does the difference have a consistent direction?"

A quantity can move a lot between seeds and still move the *same way* within
every seed. That is exactly what happens here: 0 of 8 seeds improved, which is
significant at the design's floor (p = 0.0078) while each individual arm sits <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
well inside a 46.10% band. The pairing is what buys the sensitivity, and the
floor is not the relevant yardstick for a paired contrast — comparing them
directly is the category error this section originally made.

## 6. What may and may not be claimed

| claim | status |
|---|---|
| "Adding near-collinear redundant features degraded ring-level recall" | ✅ **holds.** 0 better / 8 worse, p=0.0078, with a measured r=0.977–1.000 mechanism <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact --> |
| "Volume-normalised variants did not rescue it" | ✅ **holds.** 0 better / 7 worse / 1 tied, p=0.0156 <!-- derived: 0.0156 = the smallest two-sided sign-test p-value attainable on 7 paired observations, 2/2**7. A property of the DESIGN, not a measurement, so it is in no artifact --> |
| "The failure is explained, not just observed" | ✅ **holds.** Redundancy for one arm, near-zero class separation for the other |
| "Graph features do not help AML detection" | ❌ **not tested.** No subgraph feature was ever computed |
| "Graph features do not help at larger scale" | ❌ **not tested.** Only HI-Small. Redundancy is scale-invariant, but that is an argument, not a measurement |
| "This transfers to other AML data" | ❌ **no evidence.** One generator. Whether new-counterparty rate tracks volume is a property of AMLworld |

## 7. Limitations

- **One rung.** HI-Small only. HI-Medium has 6.8× the positives (35,230 vs  <!-- derived: 35230/5177 -->
  5,177) and would test whether the harm shrinks with more data, as the
  variance explanation predicts. Not run.
- **One generator**, and §3's collinearity is specifically a property of it.
- n=8 seeds. The sign test is exact, so the p-values are valid, but the
  smallest two-sided p reachable at n=8 is 0.0078 — that is the floor, not a  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
  strong-evidence threshold.
- The 36-feature arm changes two things at once (non-redundancy *and* feature
  count). A cleaner design would add the ratio features one at a time.

## 8. How this nearly shipped wrong

Two rounds of this experiment were run against the same feature set and
recorded **identical `config_hash` values**, because the run key did not
include the feature list. Three runs, one hash, different numbers. The A/B was
therefore not distinguishable from its own provenance record, in a project
whose thesis is that provenance should be checkable.

Worse: after measuring the harm, `GRAPH_FEATURES` was left **active** in
`features/build.py`. The shipped model was the one the measurement had already
rejected. Both are fixed — the run key now carries `feature_set`, and
`GRAPH_FEATURES` is `[]` — but the sequence is the finding: measuring
correctly is not the same as acting on the measurement.
