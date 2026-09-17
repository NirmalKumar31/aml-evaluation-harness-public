# Which result is canonical, and why the others are not

An external audit found two committed HI-Medium lineages reporting different
numbers for nominally the same model, with the README quoting one and neither
labelled. A reader could not tell which was authoritative. This file is the
answer, and the mechanism turned out to be a defect rather than a preference.

---

## The canonical HI-Medium GBDT result

```text
results_archive/gold/canonical_Medium_gbdt/         seed 0, sample 1.0
  code_git_sha          c542cc99c12d
  train_rows_ordered_by txn_id
  train_matrix_sha256   40b2f48824c85ca730ad55936905ba7e...
  predictions_sha256    33601dc4f5b055c1842f6ff141c19f6d...
```

**Replicated.** `canonical_Medium_gbdt_replica/` is an independent rerun of the
same command on the same machine. Training matrix hash, prediction hash and
every metric are identical. That is the evidence that the result is
reproducible, not an assertion that it is.

## The three lineages, and what separates them

| | training row order | average_precision | precision@50 | ring_recall@200 |
|---|---|---:|---:|---:|
| `models_Medium` (2026-08, README's number) | sorted | 0.282400339715 | 0.793981481481 | 0.693761814745 |
| `models3_Medium` (2026-09-12) | **unsorted** | 0.300477946178 | 0.880787037037 | 0.712665406427 |
| **`canonical_Medium_gbdt`** (2026-09-13) | sorted | **0.282400339715** | **0.793981481481** | **0.693761814745** |

The canonical run reproduces the older lineage **to the last digit**, and
`models3_Medium` matches neither.

**The cause is the row-order defect.** Both histogram learners build their bin
thresholds from a 200,000-row subsample of *positions*, so above that threshold
the physical scan order decides which observations define the bins.
`load_train_xy` had its `ORDER BY txn_id` removed on the strength of a
20,000-row experiment — below the threshold, where order genuinely does not
matter. `models3_Medium` was produced in that window. Restoring the sort
restores the earlier numbers exactly.

So `models3_Medium` is **superseded, and the reason is known**: it was fitted on
rows in an order nothing determined. It is retained rather than deleted because
it is the evidence for the defect.

## Rule

- A result is publishable only if its manifest records `train_rows_ordered_by`
  and `train_matrix_sha256`.
- A superseded lineage stays in the archive with the reason recorded here.
- `scripts/make_tables.py --check` binds every published figure to an artifact
  and rejects any supported only by manifests without provenance.

## ⚠️ One metric key means two different things across generations

`ring_recall_lift@200` is **not comparable between lineages**, and nothing in
the archive warns a reader who opens two manifests side by side:

| lineage | `ring_recall_lift@200` | what the number actually is |
|---|---:|---|
| `large_eval2_lgbm_s0` (superseded) | 1.431 | observed / a **closed-form pooled independence** null <!-- historical --> |
| `large_sorted_lgbm_s0` (canonical) | 0.948 | observed / a **within-day permutation** null |

The old definition survives under a new name — `ring_recall_lift_analytic_pooled@200`
= 1.425 on the canonical run — so the two are reconcilable. But the *old* key
was never renamed in the manifests that already carried it, so the same string
denotes two estimands depending on when the file was written.

This is the `predictions_sha256` defect a second time. There, a field's meaning
changed and the fix was to split it into two names and say in the README which
manifests hold which. Here the split happened for the new value and not for the
old one.

**Read the rule as:** a `ring_recall_lift@k` from a lineage listed under
`superseded` in `results_archive/CANONICAL.json` is a pooled-null lift; from a
`canonical` lineage it is a permutation lift. The retraction registry catches
the prose form (`\b1\.43\s*[x×]`), so no published sentence can quote the old
number — but the archive itself is not self-describing on this point.

## HI-Large: the sort works at 125M rows

Dropping the sort was originally a genuine OOM fix, so whether it could be
restored at the top rung was the open question. It can.

```text
sorted_lgbm_s0    124,992,128 training rows, LightGBM
  wall clock      1550 s  (~26 min)
  peak memory     30 GB of 31        <- tight, and it held
  ordered by      txn_id
  train_matrix_sha256 / predictions_sha256  both recorded
```

The memory trace shows the same signature that killed the original attempt —
spill climbing to 7 GB and then draining back into memory as the sort finished —
but it completes now, because the DuckDB budget subtracts the destination array
and the connection is closed before the fit. Three fixes that each looked
sufficient at the time turn out to be jointly sufficient.

**And the retraction strengthens.** Under the sorted fit:

```text
ring_recall@200              0.8877
ring_recall_null@200         0.9365
ring_recall_lift@200         0.948
ring_recall_null_p@200       1.000      <- upper tail: not MORE rings than chance
ring_recall_null_p_lower@200 0.000999   <- lower tail: FEWER, and significant
```

The lower-tail p-value is the smallest a 1000-draw permutation can produce. The
claim "the model covers fewer distinct rings than a ring-blind assignment of the
same scores" is now supported by the tail that actually tests it — which is the
correction the audit asked for, arriving at the same conclusion by a valid route.

### All three seeds, and a determinism proof that came free

```text
                              seed 0    seed 1    seed 2      mean
recall@200                   0.09521   0.07851   0.08982   0.08785
ring_recall@200              0.88772   0.84880   0.86976   0.86876
ring_recall_null@200         0.93650   0.88893   0.91934   0.91492
ring_recall_lift@200           0.948     0.955     0.946    0.9497
ring_recall_null_p_lower@200   0.001     0.001     0.001     0.001
precision@50                 0.48530   0.35584   0.44547   0.42887
```

**`large_sorted_lgbm_s{0,1,2}` is the canonical HI-Large lineage.** All three
record `train_rows_ordered_by: txn_id` and a `train_matrix_sha256`, and all
three were fitted by the same commit.

**All three matrix hashes are identical**, which is correct — the training
matrix does not depend on the model seed, only the fit does. Three separate
loads of 124,992,128 rows, run hours apart, produced byte-identical matrices.
That is the determinism claim demonstrated at the top rung, obtained as a
by-product of running the seeds rather than as a special experiment.

The lower-tail p-value is **0.001 on every seed** — the smallest a 1000-draw
permutation can produce. "The model covers fewer distinct rings than a
ring-blind assignment of the same scores" is now supported on three seeds by
the tail that tests it.

⚠️ **`precision@50` spans 0.356 to 0.485 across seeds** — a 36% spread on the
metric most often quoted as a headline. That is the instability this project
documents elsewhere, showing up in its own canonical result. Quote the mean
with the range, or do not quote it.

**Replay bundles ship for the canonical lineage too** —
`results_archive/replay/large_sorted_lgbm_s{0,1,2}`, 1.3 MB each, each verified
against its own manifest at 0 mismatches. Nine bundles are now committed and the
test suite recomputes every one on each push, so a reader can check any
published budget metric without the dataset.

**Superseded by this lineage:** `large_eval_lgbm_s*`, `large_eval2_lgbm_s*` and
`large_eval3_lgbm_s*`, all of which evaluated scores from fits made with an
undetermined row order. Their evaluation code was sound and their manifests
carry provenance; the scores underneath them do not.
