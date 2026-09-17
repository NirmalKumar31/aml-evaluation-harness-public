# Results: how much does a naive temporal split inflate what you report?

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

**Pre-registered:** [`PREREGISTRATION_split_inflation.md`](PREREGISTRATION_split_inflation.md),
committed **2026-08-24**. **Executed:** 2026-09-12, eighteen days later.
`git log --follow paper/PREREGISTRATION_split_inflation.md` is the evidence that
the predictions below were not written after the numbers — the file's
`Approval: pending` line is left exactly as it was, because back-filling an
approval onto it after seeing results is precisely the thing a preregistration
exists to prevent.

**Run:** `scripts/run_split_inflation.sh`, analysed by
`scripts/analyze_split_inflation.py` into
`results_archive/derived/split_inflation.json`. HI-Small, cut `2022-09-05`
(fixed by `split-sweep` and archived long before this ran), GBDT at 300
iterations, no sampling, seeds 0–4, ring-clustered bootstrap at 500 resamples.

---

## 0. The design assumption, checked rather than asserted

The ring discipline is purely a **test-set filter**, so the training half must
be identical under both protocols and each seed must produce *the same model*.
That is verified, not assumed: the analysis compares `model_artifact_sha256`
across protocols per seed and refuses to report anything if they differ.

```text
5 seeds, 5 distinct model hashes, each shared by both protocols
```

So every difference below is attributable to which rows a protocol admits into
the evaluation set, and to nothing else.

## 1. The two test sets

| | ring-aware | naive |
|---|---:|---:|
| test rows | 2,793,197 | 2,794,163 |
| test positives | 2,683 | 3,649 |
| positive account-days | 4,308 | 5,598 |
| straddling-ring tail rows | 0 | 533 |
| **prevalence** | **0.000961** | **0.001306** |

The naive protocol admits **966 more rows**, and **966 more positives**. That is
not a coincidence: the filter keys on `ring_id`, and `ring_id` is non-null only
on laundering transactions, so **the ring-aware filter removes only positives.**
Every one of the 966 excluded rows is a laundering transaction — measured
prevalence in that partition is exactly **1.000**.

## 2. Experiment A — what each protocol would report

Paired across the five shared models; ratio is naive ÷ ring-aware.

⚠️ **The interval below is a SEED SENSITIVITY interval, not a confidence
interval.** It is a t-interval across five optimizer seeds on one fixed
dataset, one fixed split and one fixed cut. It characterises how much the
answer moves when only the optimizer seed moves. It says nothing about
dataset-generation variability, the choice of cut, entity clustering, or any
population beyond this one. An earlier version labelled it "95% CI", which
invites exactly the inferential reading it cannot support.

| metric | ring-aware | naive | ratio | seed interval (n=5) |
|---|---:|---:|---:|---|
| average_precision__txn | 0.19192 | 0.26846 | **1.400** | [1.363, 1.436] |
| precision@50 | 0.70572 | 0.83974 | 1.190 | [1.152, 1.228] |
| recall_efficiency@200 | 0.56829 | 0.68895 | 1.212 | [1.193, 1.232] |
| recall_efficiency@50 | 0.71065 | 0.83974 | 1.182 | [1.144, 1.220] |
| recall_efficiency@10 | 0.80714 | 0.91571 | 1.137 | [1.059, 1.214] |
| recall@200 | 0.24708 | 0.23937 | 0.969 | [0.953, 0.984] |
| recall@50 | 0.09452 | 0.09060 | 0.959 | [0.928, 0.989] |
| recall@10 | 0.02623 | 0.02290 | 0.875 | [0.815, 0.934] |
| ring_recall@200 | 0.84861 | 0.74222 | 0.875 | [0.857, 0.892] |

**The direction depends on the metric, and that is the first finding.** A naive
split reports average precision **40% higher**, precision@50 **19% higher** —
and `recall@50` **4% lower**. Both moves have the same cause: the naive test set
contains more positives, which raises the numerator of precision-like metrics
and the denominator of recall-like ones. "Naive splits inflate results" is not
a statement that survives contact with a metric suite.

## 3. ⛔ CORRECTED: what drives it is about half prevalence, half detectability

> **An earlier version of this section claimed "about 97% of the apparent 40%
> inflation is prevalence arithmetic". That was wrong twice over, and an
> external audit caught both errors.**
>
> **The arithmetic did not say what it was reported as saying.** Dividing the AP
> ratio by the prevalence ratio gives `1.3999 / 1.3596 = 1.0296` — a 2.96%
> residual *ratio*. That is not "97% of the uplift". Allocating the excess
> directly gives `0.3596 / 0.3999 = 89.9%`; a log-ratio allocation gives  <!-- derived: 1.3596 - 1; 1.3999 - 1 -->
> 91.3%. Neither is 97%.
>
> **And the division had no justification anyway.** Average precision equals
> prevalence for a *random* ranker; it does not scale linearly with prevalence
> for a fixed good one. The decomposition assumed a functional form it never
> established — the same species of error as the retracted ring null, which
> assumed an independence structure the data did not have.

The replacement is a **counterfactual**, which needs no model of how AP responds
to prevalence. The naive test set is exactly the ring-aware set plus 966 rows,
all of them laundering. So ask directly: what if those 966 added positives had
been *typical* rather than *easy*?

```text
AP_ring_aware      the smaller set, as published
AP_naive_actual    the larger set, real scores
AP_naive_cf        the larger set, with the 966 added positives rescored by
                   resampling from the RETAINED positives' score distribution

composition contrast        = AP_naive_cf     - AP_ring_aware
score-distribution contrast = AP_naive_actual - AP_naive_cf
```

These are **contrasts between two computed quantities, not causal effects.**
The artifact still names its fields `prevalence_effect` and
`detectability_effect`, which is the older and worse vocabulary; the fields are
kept so existing references resolve, and the words here are the ones that
describe what is measured.

**The assumption this rests on, stated plainly.** The counterfactual draws
replacement scores for the 966 excluded positives from the empirical
distribution of the *retained* positives' scores, unconditionally — so it
assumes the excluded positives are exchangeable with the retained ones **given
nothing**. They are not: a positive is excluded precisely because its ring
reuses accounts, which correlates with day, typology, ring size and account
history, none of which the resample conditions on. Under that assumption the
split is a decomposition; without it, it is a sensitivity analysis showing how
much of the gap survives when the added positives are made score-typical. Read
it as the second.

Same metric, same ranker, same rows; only the added rows' scores are
counterfactual. **400 draws per seed**, five seeds
(`scripts/split_inflation_counterfactual.py`). An earlier version used 60,
which an audit called thin for a headline decomposition; at 400 the answer is
unchanged, so the 60-draw figure was not a Monte Carlo artefact.

| seed | AP ring-aware | AP naive | AP counterfactual | prevalence share |
|---|---:|---:|---:|---:|
| 0 | 0.198032 | 0.277298 | 0.235127 | 0.468 |
| 1 | 0.196235 | 0.268598 | 0.232388 | 0.500 |
| 2 | 0.181828 | 0.257374 | 0.215752 | 0.449 |
| 3 | 0.202653 | 0.278620 | 0.239060 | 0.479 |
| 4 | 0.180838 | 0.260387 | 0.215771 | 0.439 |

```text
prevalence share of the AP gap    0.467   [0.439, 0.500]   (400 draws, 5 seeds)
detectability share               0.533
```

⚠️ **That range is a seed SPREAD, not an inferential interval.** It is the
minimum and maximum across five optimizer seeds on one dataset and one split.

⚠️ **And the second component is not proven to be leakage.** What the
counterfactual measures is that the excluded positives are *easier to detect*
than typical retained positives, under an unconditional resample. It does not
condition on day, typology, ring structure or account history, so
"detectability/composition difference" is what it establishes; "caused by
train/test contamination" is an interpretation on top of that. The preregistered
HI-Medium confirmation, which would test whether it replicates, has not run.

**Roughly half the uplift is having more positives; roughly half is that the
readmitted positives are easier to detect under this counterfactual.** Not
97/3. <!-- historical --> Whether that second half is *contamination* specifically, rather than any
other composition difference between the two row sets, is not established by
this design.

## 4. Experiment B — are the excluded rows easier?

Within the **naive** test set only, one model, one global score threshold (the
score admitting `50 × 14 days = 700` transactions), applied identically to both
partitions. Free of the prevalence confound by construction.

| | EXCLUDED | RETAINED |
|---|---:|---:|
| rows | 966 | 2,793,197 |
| positives | 966 | 2,683 |
| prevalence | **1.000** | 0.000961 |
| share of the naive set's rows | 0.035% | 99.965% |
| share of its positives | **26.5%** | 73.5% |
| recall at the global threshold | 0.1470 | 0.1051 |
| mean score of positives | 0.7713 | 0.5597 |

```text
detection ratio (excluded / retained), 5 seeds:  1.326   [1.139, 1.440]
positive-share / row-share, 5 seeds:             765.7x <!-- derived: 765.7 = positive share divided by row share, printed by the counterfactual run and not stored as a field -->
```

Excluded rows **are** easier — the effect is real and consistent across all five
seeds — but by about a third, not by the factor the prediction named.

## 5. The predictions, scored

Written 2026-08-24. Wrong ones stay on the record.

| | prediction | outcome |
|---|---|---|
| **P1** | naive reports higher AP, ratio between 1.2× and 3.0× | ✅ **confirmed.** 1.400, CI [1.363, 1.436] <!-- derived: 1.400 = the observed AP ratio, measured; it coincidentally equals 1 + 1.2/3.0, the two preregistered bounds on this same line, which is why the identity gate flags it --> |
| **P2** | excluded rows detected **at least 2×** more easily | ❌ **refuted.** 1.326, CI across seeds [1.139, 1.440]. The effect exists and is nowhere near 2× |
| **P3** | excluded rows hold a disproportionate share of positives | ✅ **confirmed**, and by more than anticipated: 0.035% of rows, 26.5% of positives, a 766× ratio |
| **P4** | `recall_efficiency@50` shows a smaller proportional gap than AP | ✅ **confirmed.** 1.182 vs 1.400 |

Three of four. **P2 failed as stated** — at a fixed global threshold the excluded
rows are 1.33× easier, not 2×. But note what P2 measured: a transaction-count
recall at one threshold. The AP-level decomposition in §3 shows detectability
accounting for **53%** of the uplift, so "the effect is real but smaller than
predicted" is the accurate reading, not "there is no leakage-like effect". An
earlier version of this file drew the second conclusion from the first
measurement, and that was too strong.

## 6. What may and may not be claimed

§6 of the preregistration committed in advance to what each outcome would mean.
Applying it:

| claim | status |
|---|---|
| "A naive temporal split reports a materially different number on this benchmark" | ✅ **holds.** AP +40%, precision@50 +19%, recall@50 −4% |
| "The two protocols are not comparable" | ✅ **holds**, and is the honest headline. Which one looks better depends on the metric |
| "Published AMLworld numbers are **inflated by leakage**" | ⚠️ **not established, and not refuted.** The contrast is *consistent with* contamination and does not identify it. ~53% of the AP gap is associated with the readmitted positives' score distribution and ~47% with prevalence, under the exchangeability assumption in §3. Calling the second half "leakage" requires a design this experiment does not have. It is also not ~3%, which is what this row used to say |
| "The ring-aware split costs test data for no measurable benefit" | ❌ **not supported.** The filter removes rows that are genuinely easier, and that accounts for about half the AP gap |
| any of this on HI-Medium or HI-Large | ❌ **not run.** The preregistration named HI-Medium as confirmation; it has not been executed |

**The claim, after two corrections.** This project originally carried a
warning-level statement that AMLworld results are inflated by leakage. It was
then **retracted** on the strength of a "97% is prevalence" figure. That figure <!-- historical -->
was wrong, so the retraction was wrong too, and the current position is the
third:

> Under the implemented mixture counterfactual and its exchangeability
> assumption, a naive temporal split reports a materially higher AP on this
> benchmark (+40%); about **47%** of that contrast is associated with
> evaluating on a higher-prevalence population and about **53%** with the score
> distribution of the readmitted positives. The second component is
> **consistent with — but does not identify —** contamination or leakage.
> Neither "it is all prevalence" nor "it is all leakage" is supported, and the
> sign depends on which metric is quoted: `recall@50` goes *down* under the
> naive protocol.

⚠️ **This box previously ended "The second half is the contamination a
ring-aware filter exists to remove."** That sentence named a mechanism the
design cannot identify, two paragraphs after §3 states that the resample
conditions on nothing and that "caused by train/test contamination" is an
interpretation laid on top. A paper cannot hold both. The caveat was correct
and the headline was not, so the headline moved. <!-- historical -->

Getting this wrong in both directions, twice, is the reason the decomposition is
now a counterfactual computed from artifacts rather than a ratio computed in
prose.

`docs/archive/BUILD_PLAN.md:186` claimed the amount of inflation was "unknowable, so you
cannot even correct for it." It is measurable and it was measured — but it is
not a single prevalence ratio, which is what an earlier version of this line
said.

## 7. Limitations

- **HI-Small only.** One rung, one cut, one generator run. The preregistered
  HI-Medium confirmation has not been run.
- **`ring_id` implies positive**, so the filter can only ever remove positives.
  A benchmark whose contamination labels were not perfectly confounded with the
  target would not decompose this cleanly, and the split above is specific to
  this generator's labelling.
- **The counterfactual resamples excluded scores i.i.d. from the retained
  positives.** That defines "a typical positive" as a draw from the retained
  positive score distribution, unconditional on day, ring or account. A
  day-matched or ring-matched resample would be tighter and is not done.
- **n = 5 seeds**, sharing one dataset and one split. The intervals are
  within-run; see `docs/LIMITATIONS.md` on between-generator-run variance.
- **The global-threshold statistic in Experiment B** is a transaction-level
  count, not an account-day budget metric. It is the confound-free comparison
  the preregistration specified, not the operational one.
