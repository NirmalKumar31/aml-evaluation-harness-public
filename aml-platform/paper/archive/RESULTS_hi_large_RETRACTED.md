# Results: HI-Large, 179.7M transactions, on a 31 GB machine

> ## ⚠️ RETRACTION — the numbers in §2 and §3 are withdrawn
>
> A council audit on 2026-09-10 found that `--sample 0.7`, used to fit inside
> the 31 GB ceiling, thinned by `hash(txn_id)` — selecting **transactions**
> independently. Two consequences, both fatal to the comparison below:
>
> **It applied to the TEST set as well as the training set.** The 70% runs were
> scored on 38,252,185 test rows and the 100% run on 54,647,122. Every budget
> metric is defined per-day against a competitor pool, so thinning it changes
> the number mechanically: `recall_ceiling@50` moved **0.0517 → 0.0713** from
> subsampling alone. The 70% and 100% runs were never comparable to each other,
> and the HI-Medium comparison in §2 put a full HI-Medium test set against a
> 70% HI-Large one without saying so.
>
> **It broke the ring unit.** A ring lost ~30% of its transactions, shrinking
> its account-day footprint and its chances at the daily top-k, while a
> one-transaction ring vanished entirely 30% of the time — yet ring_recall's
> denominator came from `test_rings.parquet`, built on unsampled data. Those
> rings were structurally guaranteed misses. **Both 70% runs are void for any
> ring-level claim**, including `ring_recall@200 = 0.9011`.
>
> The two biases oppose each other and are size-dependent, so the net direction
> **cannot even be signed**. These are not "approximately right" numbers.
>
> Fixed in `train._sample_clause`: whole rings are now kept or dropped by
> `hash(ring_id)`, unringed rows thin by `hash(txn_id)`. §1, §4 and §5 —
> runtime, the memory ceiling, and the two correctness findings — are
> unaffected and stand.
>
> **Also withdrawn:** every number here is single-seed, while this project's own
> finding #2 measures a 37.2% worst-case seed range on exactly these metrics.
> Nothing below should be read to more than one significant figure, and the
> comparison should not be read at all until re-run.

**Run:** Azure `Standard_E4ds_v7` (4 vCPU, 31 GB, 216 GB NVMe + 1 TB data disk),
container built on the VM, data in ADLS Gen2, managed identity, no secrets.
**Date:** 2026-09-10 · **Cut:** 2022-10-07 (chosen by `split-sweep`, not by hand)

---

## 1. It ran

| stage | rows | wall clock |
|---|---|---|
| normalize | 179,702,229 | 4m12s |
| parse-patterns | — | 2s |
| reconcile-labels | 179,702,229 | 1m05s |
| build-splits | 125.0M train / 54.6M test | ~1m |
| build-features | 179,702,229 | **2h03m** (96 GB spilled) |
| train (gbdt, 70%) | 87,492,546 | **61m** (29.9 GB peak) |

Feature engineering over all 179.7M rows; the model fitted on 70% of the
training split. The reason for the 70% is §4 — it is a measured ceiling, not a
convenience.

---

## 2. Against HI-Medium ~~[WITHDRAWN — see retraction]~~

**Do not cite this table.** Kept visible rather than deleted so the retraction
has something to point at, and so the error is part of the record.

Same code, same hyperparameters, same seed.

| | HI-Medium | HI-Large |
|---|---:|---:|
| train rows | 19,487,126 | 87,492,546 |
| **train positives** | **15,713** | **88,951** |
| test rows | 12,402,530 | 38,252,185 |
| test positives | 10,935 | 24,487 |
| test prevalence | 0.0882% | 0.0640% |
| test rings kept | 529 | 668 |
| account-days | 6,204,374 | 25,026,707 |
| typology coverage | 49.5% | 12.8% |
| | | |
| average precision | **0.2824** | **0.0871** |
| precision@50 | 0.7940 | 0.5134 |
| recall_ceiling@50 | 0.0473 | 0.0713 |
| recall_efficiency@50 | 0.7995 | 0.6470 |
| **ring_recall@200** | **0.6938** | **0.9011** |
| rings found @200 | 367 / 529 | **602 / 668** |

## 3. The two headline metrics move in opposite directions ~~[WITHDRAWN]~~

> **Ring-level detection improved a lot. Transaction-level ranking got worse.**

`ring_recall@200` rose from 69.4% to 90.1%. `average_precision` fell from 0.2824
to 0.0871 — and still falls, 320× to 136×, after normalising by prevalence.

A plausible reading is that 5.7× more training positives (88,951 vs 15,713)
buys ring-level detection, while a test set with **4× the account-days**
(25.0M vs 6.2M) makes per-transaction ranking harder. That reading is
consistent with the numbers. It is not established by them.

**What would be needed to establish it:** holding the test window fixed and
varying only the training size. This run does neither — the rungs differ in
span, prevalence, account-day density and typology coverage simultaneously.

### ⚠️ These rungs are not a controlled comparison

HI-Small, HI-Medium and HI-Large are **independent simulation runs** of IBM's
generator, not nested subsets. They differ in time span (165 days here versus
roughly 18), in labelling density (12.8% typology coverage versus 49.5%), and
in whatever generator settings produced them.

This project has already been bitten by treating rungs as comparable: the
per-typology difficulty ordering did **not** transfer between HI-Small and
HI-Medium (Spearman ρ = 0.286, p = 0.49). The same caution applies here, and
harder, because the gap is larger.

So: the table above is **descriptive**. Read it as "what the same pipeline
produced on a different, larger dataset", not as "what more data does".

---

## 4. The 31 GB ceiling, and what it actually was

The fit could not use 100% of the training split. That is a measured limit with
a specific cause, not a resource complaint.

**The machine could not be enlarged.** `az quota update --limit value=8` returns
`ResourceNotAvailableForOffer` — a trial subscription cannot raise its vCPU
quota, so 4 vCPU / 31 GB is a ceiling rather than a setting.

**Four OOM kills, and the first three fixes were each real and each
insufficient:**

| # | cause | fix | outcome |
|---|---|---|---|
| 1 | DuckDB's `memory_limit` defaults to 80% of **system** RAM and knows nothing about the array the same process holds | compute the budget from the row count | died at 61s |
| 2 | the connection's buffer pool stayed alive into the fit | close it before returning | died at 2m09s |
| 3 | `ORDER BY txn_id` materialised all 125M sorted rows, spilling and then draining **back into memory** while the array filled | drop it — measured bitwise-identical (§5) | died at 2m00s |
| 4 | **sklearn upcasts to float64.** `X_DTYPE = np.float64`, so a float32 array is duplicated at double width inside `fit` | allocate float64 up front | **fitted** |

The fourth is the real ceiling:

```
                        float32 + sklearn's copy      direct float64
HI-Large 100%                     44.7 GB                 33.5 GB
HI-Large  70%                     31.3 GB                 23.5 GB  ✅
```

**float32 was not a saving. It was a hidden doubling.** 100% remains out of
reach at 33.5 GB; 70% fits with room.

The trace is what made this findable. Docker reports exit 137 and nothing else;
a 20-second memory sampler showed the shape — a steady climb to 15.8 GB as the
array filled, with spill flat, then past 31 GB within 16 seconds of the fit
starting. A cliff at the fit boundary, not a leak during the load. Three
attempts had been spent tuning the load.

---

## 5. Two correctness findings that only appeared at this scale

### The account-id hash collided

`load_test` compresses account ids to integers — 71M rows across two string
columns costs more than the feature matrix. The first implementation used
DuckDB's `hash()`, with a collision check written on the assumption it would
never fire.

It fired. **Two collisions across 1,919,521 accounts.** Birthday arithmetic puts
64-bit collisions here at ~1e-7, so `hash()` is evidently not uniform over 64
bits — seven orders of magnitude from the assumption.

Two pairs of distinct accounts would have been merged into single account-days,
**corrupting `ring_recall` with no error and no warning**. Replaced with a
`DISTINCT` + `row_number()` dimension table: exact by construction.

This is the failure mode the whole project is about. It would not have produced
a crash — it would have produced a number.

### Dropping the sort had to be proven, not assumed

Removing `ORDER BY txn_id` from the training load is only safe if the fitted
model does not depend on row order. Rather than assume it, fitting on `X` and on
a row-permuted `X` was checked directly: **bitwise identical `predict_proba`
output**. Asserted in `tests/repro/test_audit_regressions.py`.

`load_test` still sorts, and must — its features and its metadata come from two
separate queries and have to correspond row for row.

---

## 6. What may and may not be claimed

| claim | status |
|---|---|
| "The pipeline processes 179.7M transactions end to end on one 31 GB machine" | ✅ **holds** |
| "Ring-level detection is higher on HI-Large than HI-Medium" | ❌ **withdrawn.** Measured under ring-breaking sampling; see the retraction |
| "Transaction-level AP is lower on HI-Large" | ❌ **withdrawn.** Measured on a 70% test set against a full HI-Medium one |
| "sklearn cannot fit 125M x 32 in 31 GB, LightGBM can" | ✅ **holds.** 33.5 GB vs 14.9 GB, and LightGBM completed at 100% |
| "More training data improves ring detection" | ⚠️ **plausible, not shown.** Four things vary at once |
| "The model got worse" | ❌ **no.** Different test window, prevalence and account-day density |
| "HI-Large results are comparable to HI-Medium" | ❌ **no.** Independent generator runs; the typology ordering already failed to transfer between rungs |
| "sklearn cannot train 125M × 32 in 31 GB" | ✅ **measured** — 33.5 GB minimum, float64 is not optional |

## 7. Limitations

- **One seed.** Every HI-Medium headline number is a multi-seed ensemble with a
  measured 37% spread on budget metrics. This is a single fit, so no HI-Large
  number here should be read to more than one significant figure.
- **70% of the training split**, for the reason in §4.
- **12.8% typology coverage** makes a per-structure breakdown meaningless here;
  it is not attempted.
- Synthetic data from one generator, as everywhere else in this project.
