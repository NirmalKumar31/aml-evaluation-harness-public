# Results: replicated leak detection with a negative control

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

**Run:** `data/gold/leaksweep_Small/` · 2026-08-22 · HI-Small, cut `2022-09-05`
**Scale:** 2,284,182 train rows · 2,793,197 test rows · 2,683 test positives · 144 test rings
**Design:** 8 seeds × (1 clean + 3 channels × {real, placebo}) = **56 fits**, GBDT 300 iterations, full sample — the same configuration as the headline model
**Placebo:** the real leak columns with their rows block-permuted. Identical marginals, identical column count, alignment to the label destroyed.

> ## ⚠️ These numbers came from a placebo that has since been corrected — and rerunning it CHANGED THE VERDICTS
>
> The permutation below was **global** — across the whole leak table — so a
> training row could receive a test row's values and a day-1 row a day-28
> row's. That preserves only the global marginal, so the placebo arm differed
> from the real arm in **two** ways at once: alignment, the intended contrast,
> and distribution shift across the split and the calendar, which is not.
>
> `sweep_version` **2.0.0** permutes within `(split side, event_date)` instead,
> and fails on a partial leak join rather than filling NaN. It has been rerun
> (`results_archive/gold/leaksweep2_Small/`), and the result is in §1b. The two
> designs disagree about two of three channels, which is the most useful thing
> either of them produced.

---

## 1b. The rerun under the corrected placebo

| channel | real AP ratio | placebo mean | placebo range | separates? |
|---|---:|---:|---|:--:|
| **1.1.0 — global permutation** | | | | |
| reversed_window | 1.0066 | 0.9400 | [0.854, 0.999] | ❌ <!-- historical --> |
| future_counterparty | 1.2014 | 0.9945 | [0.982, 1.022] | ✅ <!-- historical --> |
| target *(positive control)* | 3.5525 | 0.9931 | [0.882, 1.069] | ✅ <!-- historical --> |
| **2.0.0 — within (side, day)** | | | | |
| reversed_window | 0.9951 | 0.8834 | [0.832, 0.936] | ✅ |
| future_counterparty | 1.1920 | 0.9841 | [0.904, 1.099] | ❌ |
| target *(positive control)* | 3.4508 | 0.7713 | [0.693, 0.834] | ✅ |

```text
noise floor        1.1.0   placebo mean 0.9759   spread 21.97%   <!-- historical -->
                   2.0.0   placebo mean 0.8796   spread 46.10%
```

**Three things follow, and the third is the finding.**

1. **The positive control survives both designs**, and by a wide margin (3.45
   against a 0.77 placebo). The harness can still see a leak it planted, which
   is the only thing the gate asserts.

2. **The corrected placebo has a noise floor twice as wide** — 46.1%, not
   21.97%. The published figure *understated* it. A stratified permutation was <!-- historical -->
   expected to tighten the null; it did the opposite, because preserving day
   and split structure leaves the placebo carrying more of the variation that
   differs between seeds.

3. **Two of three channel verdicts flipped.** `reversed_window` was not
   detected and now is; `future_counterparty` was detected and now is not.
   Neither channel's real arm moved materially (1.0066 → 0.9951, 1.2014 →  <!-- historical -->
   1.1920) — what moved was the null they are compared against.

   **That is the result.** At a 46% noise floor, a single channel's
   detected/not-detected verdict is not a measurement; it is a coin weighted by
   the design of the control. The honest claim is the one about the positive
   control and the noise floor, not a per-channel ladder.

⚠️ §1 and §2 were produced by **1.1.0** and are kept as the record (§7's limitations are current, and quote the 2.0.0 floor)
of what the earlier design reported. Do not quote its per-channel verdicts.

---

## 1. The noise floor, measured for the first time

> ⛔ **THE NUMBERS IN §1 AND §2 ARE THE 1.1.0 RUN, WHICH §1b SUPERSEDES.**
> They are kept because they are the record of the first measurement and of
> what the correction changed. The canonical lineage is `leaksweep2_Small`
> (`CANONICAL.json`); `leaksweep_Small` is registered superseded. Every figure
> below carries `<!-- historical -->` for that reason, and **two of the three
> channel verdicts in §2 are reversed under the corrected placebo** -- see
> §1b. Do not quote a verdict from §2.

```text
placebo AP ratio        mean 0.976   range [0.854, 1.069]   spread 22.0%   <!-- historical -->
clean AP across seeds   mean 0.194   range [0.182, 0.205]   spread 12.1%   <!-- historical -->
```

**The null is not 1.00.** Adding columns that carry no information by construction moves the AP ratio anywhere from 0.854 to 1.069. Any detection rule that compares a single measured ratio against 1.00 is comparing it against the wrong number.

Separately measured: with row order held fixed, repeated fits are **bit-identical**. The pipeline is reproducible. The variance comes from training row order — an arbitrary implementation detail that changed here merely because `txn_id` moved from a sort key to a file offset.

## 2. The ladder

| channel | real AP ratio | placebo AP ratio | paired diff | sign test | verdict |
|---|---|---|---|---|---|
| `reversed_window` | 1.007 [0.936, 1.107] | 0.940 [0.854, 0.999] | +0.067 | 6/8, p=0.29 | **not detected** <!-- historical --> |
| `future_counterparty` | 1.201 [1.038, 1.322] | 0.995 [0.982, 1.022] | +0.207 | 8/8, **p=0.0078** | **detected** <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact --> <!-- historical --> |
| `target` (positive control) | 3.553 [3.272, 3.918] | 0.993 [0.882, 1.069] | +2.559 | 8/8, **p=0.0078** | **detected** <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact --> <!-- historical --> |

Two independent decision rules — strict non-overlap of the marginal ranges, and an exact paired sign test — agree on all three channels.

## 3. The finding that matters: the old threshold had zero sensitivity to a real leak

The previous harness declared a channel leaky when its AP ratio cleared `MIN_AP_RATIO = 1.50`, from a single fit.

```text
runs clearing 1.50, out of 8
  reversed_window        0/8      range 0.936 - 1.107   <!-- historical -->
  future_counterparty    0/8      range 1.038 - 1.322     <-- a GENUINE leak   <!-- historical -->
  target                 8/8      range 3.272 - 3.918   <!-- historical -->
```

`future_counterparty` is real leakage: 8/8 paired positive on AP (p=0.0078) *and* 8/8 on error-reduction (p=0.0078). **Yet not one of eight runs would have tripped the 1.50 rule.** The threshold's sensitivity to this channel is zero.  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact; 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->

The project believed its harness worked because its positive control was extreme — a label-derived feature scores 3.5×, so it clears any threshold. A validated positive control demonstrates the harness is *not blind*. It does not establish the harness is *sensitive enough for the leaks you actually have*, and here it was not. <!-- derived: 3.5 = the canonical positive-control AP ratio 3.4508, rounded to one decimal in this sentence -->

**No false positives:** 0/8 placebo runs cleared 1.50 in any channel. The threshold errs conservatively — it under-detects.

## 4. `reversed_window`: a leak that reproducibly makes the model worse

On AP it is undetectable. On the budget-constrained metric it is consistently harmful:

```text
paired error_reduction@50 (real minus placebo, same seed)
  reversed_window       mean -0.249    0/8 positive    p = 0.0078  (negative direction)  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
  future_counterparty   mean +0.243    8/8 positive    p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
  target                mean +0.886    8/8 positive    p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
```

All eight seeds show the real forward-looking columns degrading top-of-ranking detection *relative to permuted versions of the same columns*. This is a reproducible effect, not noise, and it is invisible to AP.

🔬 **Hypothesis, not established:** the reversed-window features are forward-looking activity counts, strongly correlated with the honest backward-looking counts but pointing the wrong way. A misaligned near-duplicate of a useful feature can win tree splits away from the correct one and degrade the ranking. **Test:** compare feature importances and split counts between the clean and reversed_window models.

Relationship to failure-log entry F9 ("the realistic leak didn't leak"), which diagnosed *"six redundant columns, no new information, slightly worse model"*:

- **F9's diagnosis is largely vindicated.** The placebo degrades AP by almost exactly as much as the real columns do (0.940 vs 1.007), so most of the observed degradation really is the cost of adding columns, not the leak.
- **F9's account is incomplete in one respect.** "No new information" predicts real ≈ placebo on every metric. On the budget metric they diverge, consistently and in the harmful direction, across all 8 seeds. There is a real residual effect that redundancy alone does not explain.
- F9's stated lesson — leak severity depends on how much the future tells you that the past does not — explains why AP did not rise. It does not explain why `recall_efficiency@50` reliably falls.

## 5. Metric sensitivity differs by channel

```text
                        AP        error_reduction@50
reversed_window          -        detected (negative)
future_counterparty   detected    detected
target                detected    detected
```

`error_reduction@50` catches all three channels; AP catches two. **No single metric detects every channel, and one channel is only visible through a metric that moves in the opposite direction.** A harness reporting one number would miss leakage that is present and reproducible.

## 6. What this does to earlier claims

| earlier claim | status |
|---|---|
| "AP ×2.54 proves the harness detects leakage" | **narrowed.** It proves the harness is not blind to an extreme leak. It says nothing about sensitivity, which is zero for `future_counterparty` at the 1.50 threshold. <!-- derived: 2.54 = the withdrawn positive-control AP ratio from the 1.1.0 sweep, quoted as the claim being narrowed --> |
| "`reversed_window` leaked nothing measurable" | **partly wrong.** Not measurable on AP; consistently harmful on the budget metric, 8/8 seeds. |
| "a real temporal leak degraded AP (×0.835)" | **withdrawn.** That was a single fit through a corrupt join. The placebo shows column-count dilution produces the same effect with no information present. |
| single-run AP ratios in the old ladder | **not interpretable.** The noise floor is 22%; several reported values sit inside it. |

## 7. Limitations

- One dataset rung (HI-Small), one cut point, one model family. The 46.10% noise floor is specific to this configuration and should not be quoted as a general figure. (This line said 22% until an audit noticed it was still quoting the superseded 1.1.0 sweep. <!-- historical -->)
- 8 seeds floors the two-sided sign test at p=0.0078. More seeds would tighten it; 8 was chosen for compute, not for power.  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
- The placebo controls for column count and marginal distribution. It does not control for the *correlation structure between leak columns and honest features*, which the §4 hypothesis suggests may matter.
- HI-Medium confirmation not yet run.
- ⚠️ **There is no honest-but-informative control arm, and the verdict rule
  needs one.** `src/aml/leakproof/sweep.py:198-216` fits exactly three things
  per seed: clean, real and placebo. "Separates from placebo" therefore means
  only "the real arm differs from its permuted twin" — it never asks whether
  the real arm *helped*. `reversed_window` is scored **separates ✅** on a real
  AP ratio of **0.9951**, i.e. below the clean baseline: a channel that made
  the model worse is reported as detected leakage. Section 4 reads that as a
  finding about the channel, and it may be, but the verdict rule cannot tell
  "leaks" from "hurts" at all. A fourth arm — a genuinely predictive column
  that is not leakage — would separate those, and until one exists the
  per-channel verdicts mean "differs from its own permutation", not "leaks".
