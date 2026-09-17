# Results: per-structure detection, and what does not replicate

> ⛔ **THE ENSEMBLE RESULT IS WITHDRAWN AND HAS NOT BEEN REPLACED.** It has
> never been tested under a valid like-for-like null, and this document no
> longer claims that it has.
>
> The published 3.05× is an **eight-seed score-averaged ensemble** from
> `gold/typology_Medium/stability.json`. Its null assumed one detection
> probability per ring, which the generator's wind-down falsifies — so the
> claim falls on its own H0. Testing the ensemble properly needs the HI-Medium
> feature table rebuilt and all eight fits rerun under current code; the
> machine available carries no saved per-seed predictions and no Python 3.12
> environment, so that was **not done** and is recorded as an open item rather
> than approximated.
>
> **A single-seed diagnostic, and nothing more.** On one archived replay
> (`medium_gbdt_s0`, `ring_recall@50`, the 529 evaluated rings, current
> many-to-many ring join):
>
> | | |
> |---|---:|
> | observed spread, this seed | 3.46875 |
> | permutation null, median | 3.42745 |
> | permutation null, 95th percentile | 4.60417 |
> | **P(null ≥ observed)** | **0.46633** <!-- source: 0.46633 <- derived/typology_null.json#permutation_spread_Medium.p_value --> |
>
> ⚠️ **This does not establish the ensemble result, and it does not establish
> any conclusion about laundering structure.** It is a different model, a
> different lineage, and a different ring-membership implementation from the
> figure it sits beside: the stability artifact predates the many-to-many
> correction, and this replay holds 5 account-days belonging to two rings each
> that the old collapsed join would have mis-assigned
> (`src/aml/eval/metrics.py:794`). One seed is not eight, and an ordinary
> result on one seed is not evidence about the ensemble.
>
> **And no per-typology ordering survives either.** Each typology's
> `ring_coverage_concentration` — observed ring recall over its own null —
> with a 95% interval from the same draws:
>
> | typology | observed | null | concentration | 95% CI | Holm p |
> |---|---:|---:|---:|---|---:|
> | FAN-IN | 0.2162 | 0.3609 | 0.599 | [0.471, 0.842] | 0.080 |
> | SCATTER-GATHER | 0.4167 | 0.5545 | 0.751 | [0.625, 0.893] | 0.105 |
> | BIPARTITE | 0.2295 | 0.2743 | 0.837 | [0.609, 1.273] | 1.000 |
> | STACK | 0.3818 | 0.4330 | 0.882 | [0.700, 1.167] | 1.000 |
> | GATHER-SCATTER | 0.7500 | 0.8188 | 0.916 | [0.833, 1.000] | 0.599 |
> | RANDOM | 0.2895 | 0.2799 | 1.034 | [0.786, 1.469] | 0.883 |
> | FAN-OUT | 0.3385 | 0.3203 | 1.057 | [0.815, 1.571] | 1.000 |
> | CYCLE | 0.3846 | 0.3043 | 1.264 | [0.968, 1.875] | 0.549 |
>
> **Six of eight intervals span 1, and after Holm across eight tests nothing
> is distinguishable from 1 at all.** An earlier version of this banner read
> the ordering off these ratios and called it an inversion. It is not one:
> P(GATHER-SCATTER lands below CYCLE under H0) is **0.485**, a coin flip. <!-- historical -->
> Publishing an ordering without an interval is the mistake this whole
> document exists to record, and it was made once more in the correction.
>
> ⚠️ **And "concentration below 1" does not mean "worse than chance".** The
> null conditions on the model's **own** per-day multiset of ring-transaction
> scores, so any ring skill already in that multiset is inside H0; what varies
> is which ring each score lands on. A value below 1 means the alerts
> concentrate into **fewer distinct rings** than a ring-blind reassignment of
> the same scores. `src/aml/eval/metrics.py:640` re-exports this quantity as
> `ring_coverage_concentration` for exactly that reason, and the first version
> of this section quoted the fallacy the rename exists to prevent.

> **The mechanism.** Of the 529 evaluated rings, 14 end on a day where the
> budget exceeds the entire population (2022-09-26, -27, -28), so every ranker
> including a constant one catches them. **All 14 are GATHER-SCATTER** — 23.3%
> of that typology, and GATHER-SCATTER is the numerator of the spread. This
> repository has documented that exact defect for `precision@k`
> (`nonbinding_days@k`) since the §1 retraction and never once applied it to
> `ring_recall`.
>
> **Three nulls were tried here and the first three were all wrong**, each
> registered in `results_archive/RETRACTED.json`:
>
> 1. `p = 0.0008` — one detection probability per ring, retracted: falsified
>    by exposure. <!-- historical -->
> 2. `p = 0.11–0.44` — retracted. It measured exposure on 1,908 rings while
>    the detection <!-- historical -->
>    rates came from 529, and *assumed* after-cliff rates of 0.80/0.90/0.95
>    that cannot reproduce the observed pooled rate at any head rate in [0, 1].
> 3. `p = 0.0026` — measured rates at last, but at **budget 200** while the <!-- derived: 0.0026 = a withdrawn p-value, quoted as the record of what was retracted -->
>    3.05× spread is `ring_recall@50`, on a model outside the ensemble, and
>    with a per-day process flattened into two strata. It published a measured
>    tail rate of 0.78348 beside its own feasibility cap of 0.56125, in one <!-- derived: 0.78348 = the withdrawn budget-200 tail rate, quoted as the record of what was retracted -->
>    file. A generator now refuses to write that.
>
> Exposure itself is real and is still reported: after-cliff share runs
> **0.2131 (BIPARTITE) to 1.0 (GATHER-SCATTER)** and correlates with the raw
> per-typology rate at `rho = 0.7857`, exact permutation `p = 0.02793` over <!-- source: 0.02793 <- derived/typology_null.json#exposure_vs_detection.p_exact_permutation --> all
> 40,320 orderings. Dropping GATHER-SCATTER leaves `rho = 0.6786`, exact
> permutation `p = 0.10952` over 5,040 orderings. <!-- source: 0.10952 <- derived/typology_null.json#exposure_vs_detection.p_without_GATHER_SCATTER_exact -->
>
> **What may be said:** per-typology detection rates on this benchmark measure
> when a typology's rings happen to complete relative to the generator's
> shutdown. Nothing here shows detection varies *by structure*, and the one
> ordering the project did publish points the wrong way.

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

**Runs:** `data/gold/typology_Medium/`, `data/gold/typology_Small/` · 2026-08-24
**Setup:** 8 seeds each, production config, full sample, `ring_recall@50`. Reported value is the 8-seed prediction ensemble.

---

## 1. The measurement

A laundering *ring* counts as detected if any of its account-days reaches the top 50 on its day.

| structure | HI-Medium ensemble | per-seed range | HI-Small ensemble | per-seed range |
|---|---|---|---|---|
| GATHER-SCATTER | **0.700** | [0.683, 0.783] | **0.833** | [0.778, 0.889] |
| STACK | 0.564 | [0.273, 0.545] | 0.412 | — |
| SCATTER-GATHER | 0.367 | [0.233, 0.450] | 0.750 | — |
| CYCLE | 0.346 | [0.205, 0.423] | 0.455 | — |
| BIPARTITE | 0.311 | [0.098, 0.328] | 0.571 | — |
| FAN-OUT | 0.308 | [0.185, 0.323] | 0.588 | — |
| RANDOM | 0.250 | [0.105, 0.303] | 0.364 | — |
| FAN-IN | **0.230** | [0.108, 0.243] | 0.667 | — |
| **spread (easiest ÷ hardest)** | **3.05×** | | **2.29×** | |

## 1b. Both headline claims, against their nulls

Added after an external audit pointed out that neither claim below was tested
against anything. Computed by `scripts/typology_null.py` from the actual
per-structure ring counts; artifact `results_archive/derived/typology_null.json`.

### Is a 3.05x spread large?

A max/min ratio over eight noisy estimates is biased upward **by
construction** — the largest of eight binomial draws exceeds the smallest even
when every structure is equally detectable. So the question is not whether the
ratio beats 1, it is whether it beats the null.

| rung | observed | null median | null p95 | p |
|---|---:|---:|---:|---:|
| HI-Medium (55–78 rings/structure) | 3.05× | 1.58× | 2.08× | 0.0008 — RETRACTED |
| HI-Small (14–22 rings/structure) | 2.29× | 1.83× | 2.82× | **0.170** |

**Neither cell is a finding, and the HI-Medium one is retracted.** Against this
H0 the HI-Medium spread clears the null — but the H0 is false, because
after-cliff exposure differs by typology and the H0 gives every ring one rate
(see the banner). At 14–22 rings per structure chance alone produces a median
spread of 1.83×, so HI-Small's 2.29× is unremarkable under an H0 that is *also*
false there; a test that cannot reject under a wrong null establishes nothing
either way.

### Would a replicating ordering have looked like this?

`rho = 0.286, p = 0.49` tests against **zero** correlation, so it establishes
*no evidence of correlation* — which is not evidence of no correlation, and the
document treated the two as the same thing. The claim being made is about
whether the ordering REPLICATES, so the null to reject is perfect replication,
not independence.

Simulating both rungs from one shared true ordering, with each rung's own ring
counts and overall detection level:

```text
if the ordering replicated perfectly:  median rho 0.762,  95% [0.347, 0.976]
observed:                              rho 0.286
only 1.38% of perfect-replication draws fall this low
```

**The published test was the wrong one; the replacement is better but still
model-conditional.** The observed rho sits below the 95% interval that *one
assumed* perfectly-replicating profile would produce (p ≈ 0.014). That is
evidence against replication under that profile, not a test of the composite
hypothesis. The original test — rho against zero, p = 0.49 — failed to reject
independence, which is weaker still and happened to point the same way.

### ⚠️ Both p-values are MODEL-CONDITIONAL, and that is not a footnote

Neither number below is model-free evidence, and an external audit was right
that the wording invited reading them as if they were.

**The spread null** (`p = 0.0008 — RETRACTED`) treated rings as independent
binomial draws with a shared rate. Two things are wrong with that and they are
different sizes. The smaller one: rings are not independent — they compete for
the same daily budget and can share accounts. The fatal one: the shared rate
is false by construction, because a ring on a day where the budget exceeds the
population is caught by *every* ranker.

`permutation_spread_Medium` in `results_archive/derived/typology_null.json`
replaces it with the within-day permutation — the same construction
`aml.eval.metrics` already uses for `ring_recall`, and the same one that
produced this project's central sign reversal. It holds the ranking mechanism
fixed and permutes only the scores inside each day. Under it the observed
spread is the 53.5th percentile of chance. **No binomial null belongs on a
budget-constrained metric**, and three were published here before anyone ran
the one the repository already owned.

**The replication null** (`p ≈ 0.014`) is a **plug-in power calculation**, not a
test of the composite hypothesis "the ordering is the same". It takes
HI-Medium's *observed* per-structure profile as the truth, rescales it to
HI-Small's level, and asks how often that specific profile reproduces its own
ordering. If the true per-structure gaps are smaller than the observed ones —
which regression to the mean makes likely — a low rank correlation is more
probable under replication than this simulation says, and the p-value is
optimistic.

So: read both as *"under this model of how the data were generated"*. Of the
two qualitative readings, only one survives. **The spread reading does not**:
against the within-day permutation null it is the 53.5th percentile of chance,
and this sentence asserted the opposite for three rounds after the p-value that
refutes it was computed. The between-rung ordering instability does survive,
though "refuted" and "significant" are stronger words than a model-conditional
simulation earns. A third independently generated dataset would settle the
replication question; this benchmark does not provide one.

## 2. ⚠️ The ordering does not replicate

```text
Spearman rank correlation between the two rungs:  rho = 0.286,  p = 0.49  (n = 8)
```

Against perfect replication, p ≈ 0.014 (§1b) — that is the test that supports
the heading. The most concrete example:

```text
FAN-IN     HI-Medium 0.230  (rank 8, HARDEST)
           HI-Small  0.667  (rank 3, third EASIEST)
```

`STACK` reverses too — rank 2 on HI-Medium, rank 7 on HI-Small.

**Only GATHER-SCATTER is stable**: rank 1 on both, 0.700 and 0.833.

HI-Small and HI-Medium are **independent simulation runs** of the generator, not
subsets of one another, covering different time spans with different rings. So
this is a statement about how much the generator's per-structure difficulty
varies between runs — and it varies enough to invert the ranking.

## 3. What may and may not be claimed

| claim | status |
|---|---|
| "Detection varies substantially across laundering structures" | ❌ **withdrawn.** Against the within-day permutation null the observed spread of 3.46875 is the 53.5th percentile of chance (p = 0.46633). Per typology, six of eight concentration intervals span 1 and none survives Holm, so no ordering is established either. On HI-Small the spread was never distinguishable from chance (p = 0.170) |
| "GATHER-SCATTER is the easiest to detect" | ⚠️ **suggestive, not established.** Rank 1 on both runs, but rank 1 twice by chance among 8 structures is p ≈ 1/64 before multiplicity, ≈ 0.13 after — and it was chosen *because* it topped both lists |
| "FAN-IN is the blind spot" | ❌ **withdrawn.** Hardest on HI-Medium, third easiest on HI-Small |
| "The per-structure profile is a property of the typology" | ❌ **no evidence.** rho = 0.286, p = 0.49 |
| any single-seed per-structure number | ❌ **not a measurement.** BIPARTITE spans [0.098, 0.328] across seeds — a 3.3× range *within one structure* <!-- derived: 0.328/0.098 --> |

## 4. The finding that survives, and it is the more useful one

> Aggregate recall hides a spread across laundering structures — and how much
> of that spread is *structure* is not identified on this benchmark, because
> when each typology's rings complete relative to the generator's wind-down
> varies from 0.2131 to 1.0 and rank-correlates with the raw rate at
> rho 0.7857 (exact permutation p = 0.02793).
> Separately, **which structure is hardest does not appear to transfer between
> datasets** (rho 0.286 against a perfect-replication interval of
> [0.347, 0.976]). Both comparisons are model-conditional. A per-typology
> breakdown published on one benchmark cannot be assumed to describe another —
> the blind spot has to be measured on the data you actually deploy against.

That is more actionable than "watch out for FAN-IN". It says a compliance team
cannot inherit someone else's weakness profile, and it says a benchmark paper
reporting one cannot generalise it.

It is also the same lesson as the rest of this project arriving in a new place:
the aggregate looked informative, the breakdown looked more informative, and
only replication showed which parts of it were real.

## 5. Limitations

- **Typology coverage is partial**: 49.5% of HI-Medium test positives and 57.0%
  of HI-Small's carry a ring/typology label. This describes about half the
  laundering in each test set; the unlabelled half may behave differently.
- **n = 8 structures** makes the rank test underpowered. This shows *no evidence
  of* replication, which is not the same as proving independence. The FAN-IN and
  STACK reversals are large and concrete regardless.
- Two rungs only. A third would strengthen the conclusion either way.
- 55–78 rings per structure on HI-Medium; fewer on HI-Small. The per-seed ranges
  in §1 are the honest picture of that thinness.

## 6. How this was almost published wrong

The first version of this number was **single-seed** and gave a 4.6× spread with
FAN-IN at 14.9% as the headline blind spot. Both parts were wrong: the spread
was inflated by taking extremes from one noisy run, and the blind spot was an
artifact of one dataset rung.

It survived long enough to be written into a summary and said out loud once. The
only reason it did not go further is that the cross-rung check was cheap and
somebody ran it.
