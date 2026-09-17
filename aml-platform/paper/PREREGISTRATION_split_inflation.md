# Pre-registration: how much does a naive temporal split inflate reported performance?

**Status: DRAFT, awaiting approval. Not yet binding.**
**Once approved, this file is committed BEFORE the experiment runs and is not edited afterwards.** Results go in a separate file. If a finding contradicts a prediction below, the prediction stays on the record.

**Why pre-register at all.** The paper's claim is that AML evaluation harnesses fail silently and must be validated with controls. A paper making that argument cannot also be the kind of paper that tuned its headline experiment until it looked good. The cost of writing this down is twenty minutes. The cost of not being able to say we wrote it down is the paper's credibility.

---

## 1. The question

Practitioners evaluating on IBM AMLworld typically use a plain temporal split: train on everything before a cut date, test on everything after. This project instead uses a ring-aware, entity-disjoint split.

**How different is the number you would report?**

Our own planning documents assert this is unanswerable — `BUILD_PLAN.md:186` says *"the amount of inflation is unknowable, so you cannot even correct for it."* We now think that is wrong, and this experiment is the test.

## 2. The structural fact that shapes the design

Read from `src/aml/splits/ring_aware.py`:

```text
TRAIN  SELECT * FROM L WHERE event_time < cut          ← IDENTICAL under both protocols
TEST   post-cut rows, MINUS (a) transactions of rings sharing an account with
       train rings, MINUS (b) tails of straddling rings that began before the cut
```

**The ring-aware discipline is purely a test-set filter.** The training set is byte-identical either way.

Two consequences:

1. There is **no training-contamination component to isolate**. Any inflation is entirely attributable to which rows a protocol admits into the evaluation set. An earlier draft of this design proposed comparing models trained on contaminated vs clean training sets; that comparison does not exist here.
2. The comparison is therefore unusually clean: **one model, trained once, scored on two test sets.** No confound from differing model fits, seeds, or feature values.

## 3. Experiments

### Experiment A — the headline: what each protocol would report

```text
train        one model, one fit, the shared pre-cut training set
evaluate on  (i)  NAIVE test set      = all post-cut rows
             (ii) RING-AWARE test set = (i) minus the two filters above
report       AP, recall@{10,50,200}, recall_efficiency@{10,50,200},
             precision@50, ring_recall@200, and for each test set its
             row count and positive prevalence
```

**Known confound, stated up front:** the two test sets differ in size and in positive prevalence, and average precision depends on prevalence. So A alone cannot attribute the gap to leakage. A is the *practitioner-relevant* number — "the figure you would publish" — and B is what makes it interpretable.

### Experiment B — the mechanism, confound-free

Within the **naive** test set only, partition rows by whether the ring-aware protocol would have excluded them:

```text
EXCLUDED   rows the ring-aware filter removes (dropped-ring rows,
           straddling-ring tails) -- the putatively contaminated rows
RETAINED   rows both protocols keep
```

Same model, same test set, same prevalence computation applied to each part. Compare detection difficulty between the two partitions:

```text
recall at a FIXED global score threshold (the naive-set top-k cut)
mean predicted score for positives
per-partition average precision
share of the naive set's true positives that sit in EXCLUDED
```

This is a **within-test-set** comparison, so it is free of the prevalence confound in A. If excluded rows are much easier to detect than retained rows, that is the leakage, measured directly.

### Protocol implementation constraint

The naive split must be produced by the **same code path** with the filter disabled — `build-splits --protocol {naive,ring-aware}` — not a second implementation. Two implementations would be a second chance for the two-independent-derivations bug that `txn_id` just taught us about.

## 4. Fixed analysis parameters

Committed now, so they cannot be chosen after seeing results.

| | |
|---|---|
| primary dataset | **HI-Small** (5,078,345 rows) |
| confirmation | **HI-Medium** (31,898,238 rows), headline metrics only |
| cut | `2022-09-10` for HI-Medium; for HI-Small, chosen by the existing `split-sweep` diagnostic **before** any inflation number is computed |
| seeds | **5** (0–4), full model config: GBDT, 300 iterations, no sampling |
| headline metric | **average precision** |
| budget metric | **recall_efficiency@50** |
| uncertainty | existing ring-clustered bootstrap, 500 resamples, 95% CI |
| comparison | paired across seeds; report the ratio and its CI |
| identity | schema ≥ 1.1.0 only (post-`txn_id` fix) |

Reported to three significant figures. Prevalence and row counts reported alongside every metric, always.

## 5. Predictions

Committed before running. Wrong predictions stay in this file.

**P1.** Experiment A: the naive protocol reports a **higher** average precision than the ring-aware protocol, with a ratio between **1.2× and 3.0×**.

**P2.** Experiment B: rows the ring-aware filter excludes are detected **at least 2× more easily** than retained rows, on recall at a fixed threshold.

**P3.** The dominant driver of A is **test-set composition** (B), not the prevalence difference. Operationally: excluded rows will hold a **disproportionate share** of the naive test set's true positives relative to their share of its rows.

**P4.** `recall_efficiency@50` will show a **smaller** proportional gap than average precision, because it is bounded by the review-budget ceiling and cannot inflate without limit.

## 6. What would refute the paper's framing

Stated explicitly so it cannot be quietly discovered and dropped:

- **If AP_naive ≈ AP_ring-aware** (ratio CI contains 1.0), then the ring-aware split costs 45–58% of test rings for **no measurable metric benefit** on this benchmark. That is a strong negative result about our own central design decision, and **we commit to publishing it as the headline** rather than relegating it. It would also mean the "published AMLworld numbers are inflated" framing must be dropped.
- **If the naive protocol scores *lower***, the straddling-tail rows are harder rather than easier, and the leakage intuition is wrong for this generator. Also publishable, also as the headline.
- **If P2 holds but P3 fails**, the gap in A is mostly a prevalence artifact and the honest claim shrinks to "protocols are not comparable" rather than "naive protocols inflate."

## 7. What we will not do

- No adding, removing or reweighting metrics after seeing results.
- No changing the cut point to improve a contrast. The HI-Small cut is fixed by `split-sweep` before any inflation number is computed.
- No dropping seeds, and no switching from the mean across seeds to a best-of.
- No re-running with a different model configuration and reporting only the more favourable one.
- If we later decide a different analysis is better, it is reported as **exploratory**, separately, and labelled as such.

---

**Approval:** *pending*
**Committed before results exist:** *pending*
