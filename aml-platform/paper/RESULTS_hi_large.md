# Results: HI-Large, 179.7M transactions, on a 31 GB machine

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

**Run:** Azure `Standard_E4ds_v7` — 4 vCPU, 31 GB RAM, 216 GB NVMe + 1 TB managed
disk. Container built on the VM, data in ADLS Gen2, managed identity, no secrets.
**Cut:** 2022-10-07, chosen by `split-sweep`. **Date:** 2026-09-11.

> **This replaces a retracted version**, kept at
> [`archive/RESULTS_hi_large_RETRACTED.md`](archive/RESULTS_hi_large_RETRACTED.md).
> That version reported a single-seed fit at `--sample 0.7`, and the sampling
> thinned by `hash(txn_id)` — selecting transactions independently. It broke the
> ring unit and silently thinned the test set too (`recall_ceiling@50` moved
> 0.0517 → 0.0713 from subsampling alone). Every number in it was withdrawn. <!-- derived: 0.0713 = a withdrawn subsampling figure, quoted as the record of what was retracted -->
>
> The run below uses **no sampling at all** and **three seeds**, so neither
> defect can apply. `_sample_clause` is now ring-aware.

---

## 1. It ran, end to end

| stage | rows | wall clock |
|---|---|---|
| normalize | 179,702,229 | 4m12s |
| parse-patterns | — | 2s |
| reconcile-labels | 179,702,229 | 1m05s |
| build-splits | 125.0M train / 54.6M test | ~1m |
| build-features | 179,702,229 | **2h03m**, 96 GB spilled |
| train (LightGBM, 100%) | **124,992,128** | 25.5m ± 0.2, 30.8 GB peak |

**The full training split, not a sample.** 124,992,128 rows × 32 features on a
machine with 31 GB that cannot be enlarged — a trial subscription cannot raise
its vCPU quota (`az quota update` → `ResourceNotAvailableForOffer`).

---

## 2. The result, three seeds — CANONICAL lineage

`results_archive/gold/large_sorted_lgbm_s{0,1,2}`. Fitted with
`ORDER BY txn_id`, all three sharing one `train_matrix_sha256` over
124,992,128 rows, all three from one commit.

| metric | unit | seed 0 | seed 1 | seed 2 | mean | range |
|---|---|---:|---:|---:|---:|---:|
| average_precision | txn | 0.09229 | 0.07052 | 0.08257 | **0.08179** | 27% |
| precision@50 | acct-day | 0.48530 | 0.35584 | 0.44547 | **0.42887** | 30% |
| recall@50 | acct-day | 0.03238 | 0.02374 | 0.02973 | 0.02862 | 30% |
| recall_ceiling@50 | acct-day | 0.05169 | 0.05169 | 0.05169 | 0.05169 | 0% |
| recall_efficiency@50 | acct-day | 0.62653 | 0.45939 | 0.57510 | **0.55367** | 30% |
| **recall@200** | acct-day | 0.09521 | 0.07851 | 0.08982 | **0.08785** | 19% |
| ring_recall@200 | ring | 0.88772 | 0.84880 | 0.86976 | **0.86876** | 4.5% |

Test set: 54,647,122 rows, 34,952 positives, 27,809,331 account-days, 61,698 of
them positive.

> ### ⛔ These numbers replaced an earlier set, and the difference is not rounding
>
> Until 2026-09-14 this section reported `recall@200 = 0.0918` and  <!-- historical -->
> `ring_recall@200 = 0.8738` from `large_eval3_lgbm_*` — evaluations of fits  <!-- historical -->
> made **before** the training load imposed a row order. Both histogram
> learners bin from a 200,000-row subsample of *positions*, so those fits saw
> different bin thresholds and are different models.
>
> `recall@200` moves 0.0918 → **0.08785**. `precision@50` moves 0.4405 →  <!-- historical -->
> **0.42887**. The superseded lineage is retained in the archive as the
> evidence for the defect and is listed in
> `results_archive/CANONICAL.json`; `make_tables.py --check` now **refuses** a
> current document whose number is supported only by it.

⚠️ **`precision@50` spans 0.356–0.485 across the three seeds — a 30% range.**
The metric most often quoted as a headline is the least stable thing here.
Quote the mean with the range, or do not quote it.

---

## 3. Two numbers that reframe the whole thing

The instrumentation added after the 2026-09-10 audit earned its place immediately.

### `ring_recall` is far above the account-day recall, and needs a null

```text
recall@200         0.08785    what an investigator actually catches
ring_recall@200    0.86876    the same predictions, counted per ring
```

A ring counts as caught if **any** of its account-days reaches the top 200 on
its day, so a ring spanning m account-days gets m chances. HI-Large's mean ring
size is **12.0** (61,698 test positive account-days, ~13% ringed, 668 rings).

The bare ratio of the two, 9.5, is **not** the right way to express this, and an
earlier version of this file headlined it. It has no reference point: 9.5 is not
comparable to HI-Medium's 5.6 because neither is anchored to what chance would
give, and the value is dominated by ring size and window length rather than by
how much the metric flatters.

Against a **within-day permutation null**, computed by `evaluate()` and read
from the manifests (`large_sorted_lgbm_s{0,1,2}` — the canonical lineage, 1,000 draws each):

| | seed 0 | seed 1 | seed 2 | mean |
|---|---:|---:|---:|---:|
| recall@200 | 0.09521 | 0.07851 | 0.08982 | 0.08785 |
| ring_recall@200 | 0.88772 | 0.84880 | 0.86976 | 0.86876 |
| ring_recall_null@200 | 0.93650 | 0.88893 | 0.91934 | 0.91492 |
| **ring_recall_lift@200** | **0.948** | **0.955** | **0.946** | **0.9497** |
| ring_recall_null_p@200 (upper) | 1.000 | 1.000 | 1.000 | 1.000 |
| ring_recall_null_p_lower@200 | 0.001 | 0.001 | 0.001 | 0.001 |

Ring sizes: median **10.0**, p90 **25.0**. 668 rings, 8,616 ring-member
account-days.

> ## ⛔ RETRACTED: the 1.43× lift <!-- historical -->
>
> **An earlier version of this file reported `ring_recall_lift@200 = 1.430` and
> concluded that "the model spreads its hits across distinct rings rather than
> piling them into a few." That conclusion was wrong.** Measured against a null
> that survives its own control, the lift is **0.9497**, the upper-tail
> p-value for *more* rings than chance is **1.000** on every seed, and the
> **lower**-tail p-value — the one that tests the claim actually being made —
> is **0.001**, the smallest 1,000 draws can produce.
>
> The direction reverses. The correct statement is that the model covers
> slightly **fewer** distinct rings than a ring-blind assignment of the very
> same scores would.

The retracted null was `mean(1 - (1-r)^m_i)` with `r = recall@200` — recall
pooled over *all* positive account-days. Two independent errors, in opposite
directions, and the larger one was never considered:

| null | value | lift | what it assumes |
|---|---:|---:|---|
| pooled recall, independent draws | 0.61165 | 1.429 | the retracted one <!-- historical --> |
| ring-eligible rate, independent draws | 0.98886 | 0.884 | population fixed only <!-- historical --> |
| **within-day permutation** | **0.91492** | **0.9497** | **shipped** |

> The first two rows are values from `large_eval3_lgbm_s*`, computed while the
> retracted nulls were being compared against each other. They are kept as the
> record of that comparison. The shipped row is the canonical lineage,
> `large_sorted_lgbm_s{0,1,2}` — the three-seed means, not the unsorted fits.

1. **Wrong population, and this is the big one.** The null asked how often a
   ring-member account-day gets alerted and answered with pooled
   `recall@200`, which averages over every positive account-day — and
   **86.04% of them carry no ring label**. The rate at which *ring-member* account-days are
   actually alerted is `ring_eligible_recall@200 = 0.61989`, **seven times
   higher**.

2. **Wrong independence, in the direction this file already predicted.** Both
   closed forms treat a ring's `m` account-days as `m` independent Bernoulli
   draws. They are not: one transaction produces a sender account-day and a
   receiver account-day carrying the same max score, and same-day account-days
   compete for a fixed budget rather than being drawn independently. The
   previous version of this section named this exact mechanism and correctly
   reasoned that it makes an independence null too generous — it just applied
   that reasoning to a null whose base rate was already wrong by 7×.
   Correcting it brings the null back down from 0.989 to 0.925.

The replacement conditions on what the model actually did and randomises only
the thing under test — see `_permutation_null` in `src/aml/eval/metrics.py` for
the estimand. Each draw reshuffles which ring transaction gets which of that
day's ring-transaction scores, rebuilds the affected account-day maxima, and
re-ranks against that day's untouched account-days. Ring sizes, ring day
composition, the daily budget, and the sender/receiver coupling all survive;
only the link between ring identity and score is broken.

**Re-fitted with a deterministic row order, three seeds.** The numbers in the
table above came from fits whose training rows arrived in whatever order DuckDB
produced — which changes the bin thresholds of both histogram learners above
200,000 rows. The canonical lineage `large_sorted_lgbm_s{0,1,2}` fixes that:

| | seed 0 | seed 1 | seed 2 | mean |
|---|---:|---:|---:|---:|
| ring_recall@200 | 0.88772 | 0.84880 | 0.86976 | 0.86876 |
| ring_recall_null@200 | 0.93650 | 0.88893 | 0.91934 | 0.91492 |
| **ring_recall_lift@200** | **0.948** | **0.955** | **0.946** | **0.9497** |
| ring_recall_null_p_lower@200 | 0.001 | 0.001 | 0.001 | 0.001 |

The conclusion is unchanged and better supported: the **lower**-tail p-value is
the smallest a 1000-draw permutation can give, on all three seeds. See
[`docs/RESULT_LINEAGE.md`](../docs/RESULT_LINEAGE.md).

**Confirmed on a second rung.** HI-Medium was re-run end to end on the cloud VM
from a re-downloaded dataset (sha256 matching the pin) and evaluated under the
same null:

| rung / model | ring_recall@200 | null | lift | p |
|---|---:|---:|---:|---:|
| HI-Large, lgbm (3 seeds, canonical) | 0.86876 | 0.91492 | 0.9497 | 1.000 |
| HI-Medium, gbdt (canonical, sorted) | 0.69376 | 0.76453 | 0.907 | 1.000 |

Two independent generator runs, three model configurations, every lift below 1.
The retraction does not rest on a single rung or a single model.

**Why it is believable where the old one was not:** it has a control. On scores
drawn independently of ring membership it must report no effect, and it does
(`test_ring_null_says_nothing_is_happening_when_nothing_is`). The first
*attempted* replacement — an exchangeable permutation over ring-member
account-days, holding the daily alerted count fixed — returned lift **0.497**
on that control, declaring a strong effect on data built to contain none, and
was discarded. The shipped fast path is additionally pinned draw-for-draw to a
from-scratch recomputation through `to_account_days`
(`test_ring_null_matches_a_from_scratch_recomputation`).

⚠️ **This figure has now been published wrong three times, every time by hand
or by an untested assumption:**

| value | how it was obtained |
|---|---|
| 1.08 | `m=17` — **HI-Medium's** mean ring size, applied to HI-Large <!-- historical --> |
| 1.28 | corrected to a scalar `m=12`, still a hand calculation <!-- historical --> |
| 1.43 | measured from per-ring sizes — but against the wrong reference population <!-- historical --> |
| **0.9497** | **measured against a null with a control that can return "no effect"**, on the canonical sorted lineage |

The first two corrections were about arithmetic. The third was not: 1.43 was
computed correctly, by code, from artifacts, and published under a checker that
verified it traced to a manifest. It was still wrong, because **the estimand
was wrong, and no amount of provenance discipline detects that.** A null needs
a negative control the way a leak detector needs a placebo, and this one did
not have one until now.

Note also that `ring_recall@200` is the **most stable** metric here (1.9% across
seeds) while `precision@50` moves 26%. A metric that barely moves is not being
reassuring — it is saturated.

### The ring discipline covers 13% of positives

```text
pct_positive_acct_days_without_ring = 86.04%
```

**87% of HI-Large positives carry no ring label at all.** They are neither
dropped for account overlap nor counted in `ring_recall`'s denominator.

Combined with the 87.45% of test rings dropped for ring-participant-disjointness, the <!-- derived: 87.45 = gold/large_splits/manifest.json `dropped_pct`. That manifest records code_git_sha "unknown" -- the HI-Large split predates the provenance gate -- and the figure cannot be re-derived without the 179.7M-row dataset. It is published on an unprovenanced artifact and that is a disclosed limitation, not an oversight -->
estimand behind `ring_recall@200 = 0.86876` is:

> the ~13% of rings isolated enough to survive the split, measured over the
> ~13% of positives that carry a ring label at all.

That slice is narrow and **not randomly chosen** — rings die *because* they
reuse accounts, so the ones removed are exactly the connected hub-and-mule
networks. `ring_recall@200 = 0.86876` should not be quoted without that sentence.

**`recall@200 = 0.08785` is the number that describes all 34,952 test positives.**

---

## 4. The memory ceiling was the library, not the data

The cleanest result of the HI-Large work.

```text
                              125M x 32 training matrix
sklearn HistGradientBoosting        33.5 GB    X  X_DTYPE = float64, upcasts always
LightGBM                            14.9 GB    OK consumes float32, bins to uint8
                                    -------
available                             31 GB
```

sklearn **cannot** fit this data on this machine, at any setting. LightGBM fits
it in 25 minutes. Both were run; this is measured, not inferred.

Four OOM kills established it, and the first three fixes were each real and each
insufficient:

| # | cause | outcome |
|---|---|---|
| 1 | DuckDB's `memory_limit` defaults to 80% of **system** RAM and ignores arrays in the same process | died at 61s |
| 2 | the connection's buffer pool stayed alive into the fit | died at 2m09s |
| 3 | `ORDER BY txn_id` materialised 125M sorted rows, then drained spill **back into** RAM while the array filled | died at 2m00s |
| 4 | **sklearn upcasts float32 → float64**, so float32 was a hidden doubling | fixed |

Docker reports exit 137 and nothing else. A 20-second memory sampler is the only
reason these are causes rather than guesses: the trace showed a steady climb to
15.8 GB with spill flat, then past 31 GB within 16 seconds of the fit starting —
a cliff at the fit boundary, not a leak during the load. Three attempts had been
spent tuning the load.

⚠️ LightGBM is **not** like-for-like. Binning thresholds differ, so identical
predictions are not expected — only comparable metrics. And `min_child_weight`
had to be left at LightGBM's default: 0, chosen to mirror sklearn (which has no
such parameter), crashed at 125M rows with `best_split_info.left_count > 0`, and
does not reproduce below ~100M rows.

---

## 4b. Ring membership is many-to-many, and the numbers survived it

An external audit found that `to_account_days` collapsed each account-day to
one ring with `max`. It is a real defect and it is not a corner case —
measured on HI-Large's reconciled labels:

```text
ringed account-days       243,295
MULTI-RING account-days    10,432   (4.288%)
max rings on one acct-day       12
```

Up to eleven of twelve memberships were being discarded on 4.3% of ringed
account-days. Each one is a detection opportunity the affected ring loses, so
the bias was **downward**, and `per_typology` assigned whichever typology
`max` happened to pick.

Membership is now a separate `(day, acct, ring_id)` relation that `ring_recall`
and `per_typology` join. Everything was re-evaluated from the saved scores.

**The effect on the published numbers is negligible:**

| metric | collapsed `max()` | many-to-many | Δ |
|---|---:|---:|---:|
| n_rings@200 | 668 | 668 | 0 |
| ring_recall@200 | 0.87375 | 0.87425 | +0.00050 <!-- historical --> |
| ring_recall_null@200 | 0.61148 | 0.61165 | +0.00018 <!-- historical --> <!-- derived: 0.00018 = the difference of the two unrounded values in this row, which the four-decimal figures printed here cannot reproduce exactly --> |
| ring_recall_lift@200 | 1.42933 | 1.42967 | +0.00033 <!-- historical --> <!-- derived: 0.00033 = the difference of the two unrounded values in this row --> |

> Both lift columns above are computed against the **retracted** closed-form
> null, because that is what this comparison was run under. They are kept as a
> record of that step, not as a current figure, and every number in the table
> above comes from `large_eval3_lgbm_s*` — the superseded unsorted lineage.
> The current lift is **0.9497** on `large_sorted_lgbm_s{0,1,2}`; see the
> retraction notice in section 4. <!-- historical -->

About **0.3 of 668 rings** changed status. In `per_typology`, exactly one ring
moved, in RANDOM (0.3246 → 0.3333 over 114 rings).  <!-- historical -->

Why so small: no ring vanished from the denominator, because each has a median
of 10 account-days and `max` surfaced it somewhere; and losing a few of ten
opportunities rarely flips "did **any** reach the top 200".

**Both halves of that matter.** The code was wrong and had to be fixed — an
audit that accepted "the number barely moves" would be accepting an incorrect
implementation. But the conclusions drawn from these numbers do not change,
and saying so is more useful than implying a retraction.

## 5. Two correctness findings only reachable at this scale

**The account-id hash collided.** Account ids are compressed to integers because
71M rows across two string columns costs more than the feature matrix. The first
implementation used DuckDB's `hash()`, guarded by a collision check written on
the assumption it would never fire. It fired: **two collisions across 1,919,521
accounts**, where birthday arithmetic predicts ~1e-7. Two pairs of distinct
accounts would have merged into single account-days and **corrupted `ring_recall`
with no error and no warning**. Replaced with a `DISTINCT` + `row_number()`
dimension table, exact by construction.

> ⛔ **This paragraph claimed the opposite of the truth and is retracted.** It
> read: "Dropping the sort had to be proven, not assumed… fitting on `X` and on
> a row-permuted `X` gives **bitwise identical** `predict_proba` output."
>
> That was measured at **20,000 rows**. Both histogram learners bin from a
> 200,000-row subsample of *positions*, so above that threshold a row
> permutation changes the bin thresholds and the fitted model. At 210,001 rows:
> the same rows in a different order move sklearn's predictions by about
> **0.04** and LightGBM's by about **0.05** at the top of the range.
>
> ⚠️ This line used to say **0.063 and 0.064**, from an ad-hoc run that left no <!-- historical -->
> artifact — so the published-numbers gate could only confirm that the token
> `0.063` appeared *somewhere* in the archive, which it did, as an unrelated <!-- historical -->
> metric of a superseded lineage.
> `test_the_bin_subsample_makes_row_order_matter_above_200k` now recomputes
> both deltas on every run and asserts they stay well above zero; the figures
> above are what it currently measures. They are a property of the fixture and
> the library version, not a pipeline result, which is why they are quoted to
> two decimals. <!-- historical -->
>
> `ORDER BY txn_id` is back in the training load, and the canonical results in
> §2 come from fits that use it. `load_test` sorts for a second, independent
> reason: its features and metadata come from two queries and must correspond
> row for row.

---

## 6. What may and may not be claimed

| claim | status |
|---|---|
| "The pipeline processes 179.7M transactions end to end on one 31 GB machine" | ✅ **holds** |
| "LightGBM trains all 125M × 32 on 31 GB; sklearn cannot" | ✅ **measured** — 14.9 vs 33.5 GB, both run |
| "recall@200 = 0.08785 on HI-Large" | ✅ **holds** — mean of 3 seeds, range 0.07851–0.09521 (19%) |
| "ring_recall@200 = 0.86876" | ⚠️ **only with its estimand.** lift **0.9497** against a within-day permutation null (p=1.000 for *more* rings than chance); covers ~13% of positives, and the least-connected rings |
| "the model exploits ring structure" | ⛔ **retracted.** It covers slightly fewer distinct rings than a ring-blind assignment of the same scores |
| "HI-Large detection is better or worse than HI-Medium" | ❌ **not claimable.** Independent generator runs; 165-day vs ~18-day span; 87% vs 38% unringed positives; 87% vs 58% ring drop |
| "More training data improves detection" | ❌ **not shown.** Four things vary at once; no controlled arm exists |

## 7. Limitations

- Three seeds, not eight. Enough for a range, not for a distribution.
- **No cross-rung comparison is offered.** The retracted version built its
  narrative on one, and that was the error.
- 12.8% typology coverage makes a per-structure breakdown meaningless here; not
  attempted.
- LightGBM, not the sklearn model the other rungs use — because sklearn
  physically cannot fit this data here. That is simultaneously the finding and a
  caveat on every comparison.
- Synthetic data from one generator. See [docs/LIMITATIONS.md](../docs/LIMITATIONS.md),
  particularly that a 32-feature logistic regression reaches
  pooled `precision@50 = 0.5706` on HI-Medium — retracted as a comparison — against an eight-seed GBDT mean of
  0.82480. A linear model doing that well at the top of the ranking is a reason
  to report the baseline beside any model score from this benchmark; it is not
  a measurement of how much of the score belongs to IBM's simulator, and this
  line claimed it was until the seventh audit. No such attribution was
  designed, and none is available from one baseline and one comparator.
  An earlier
  version of this line called the benchmark "near-saturated"; that word was  <!-- historical -->
  withdrawn, because `precision@50` on the canonical HI-Large lineage spans
  0.35584 to 0.48530 across three seeds, which is not what saturation looks
  like.
