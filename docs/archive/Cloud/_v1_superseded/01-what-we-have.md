# What we have, and whether it was worth it

A straight answer before spending any money.

---

## ✅ What is finished

```
Phase 0   INGEST
          [x] read the raw CSV without corrupting it
          [x] fixed the duplicate "Account" column trap
          [x] composite account keys (bank + account)
          [x] 465 MB CSV -> 195 MB Parquet, partitioned by day
          [x] contract tests pin the exact row count and file fingerprint

Phase 1   LABELS AND THE SPLIT
          [x] parse the answer key into rings / transactions / accounts
          [x] join it back onto 31.9M transactions — 0 misses, 0 ambiguity
          [x] found and corrected 3 wrong figures in the project's own docs
          [x] ring-aware entity-disjoint temporal split
          [x] 4 assertions that STOP the build, not warn

Phase 2   FEATURES AND MODELS
          [x] 32 features, every one provably causal
          [x] logistic baseline + gradient-boosted trees
          [x] recall@budget with the alert unit defined as (account, day)
          [x] discovered and fixed the "recall ceiling" problem
          [x] ring-level bootstrap confidence intervals

Phase 3   PROVING THE NUMBERS
          [x] planted 3 leaks; proved the harness detects them
          [x] wrote the serving path separately and tested it against the batch
              path — found 2 real bugs
          [x] reproducibility: 9 tests, each with a control

Phase 6   MANUFACTURED DRIFT
          [x] generator built and tested (26 invariants)
          [ ] experiment CUT — measured that synthetic positives were 3x too easy

TOTALS    2,895 lines of source · 1,553 lines of tests · 96 tests · 8 seconds
          7 commits · £0 spent
```

## ❌ What is not

```
[ ] 182 million rows        <- the gap this folder closes
[ ] throughput + cost table
[ ] single-node vs cluster crossover
[ ] cloud infrastructure
[ ] README, cut list, ADRs
```

---

## Is the project complete?

**No — but the hard part is.**

Think of it as two claims:

| claim | status |
|---|---|
| *"My results are trustworthy"* | ✅ **done and proven** |
| *"I can handle production volume"* | ❌ 32M rows, not 182M |

The first is the difficult one and it's finished. The second is mostly a matter of
running the same code on a bigger machine.

---

## Did it produce anything valuable?

Yes. Five things, each with a number behind it.

### 1. A working detector

```
                        logistic   GBDT
average precision         0.020    0.300      15x better than the floor
recall_efficiency@50      57.5%    83.2%      % of what the budget can reach
precision@50               57%      83%       5 in 6 alerts are real
ring recall@200            44%      69%
confidence intervals          don't overlap   -> genuinely better, not lucky
```

**83% of attainable** means: given 50 investigation slots a day, the model finds 83% of
all the laundering those 50 slots could physically reach. That's a real result.

### 2. Proof the evaluation isn't lying

```
planted a label-derived leak  ->  average precision x2.54, 70% of error closed
                              ->  the harness SEES leakage when leakage exists
```

Most fraud projects can say "my split is clean." Almost none can say **"and here's proof
I'd have caught it if it weren't."**

### 3. Two production bugs caught before production

The serving-path parity test found both on its first run:

```
DuckDB log() is BASE 10; numpy np.log is NATURAL LOG
   -> every learned threshold would land on the wrong side in production
   -> nothing would ever error

SQL sum() over an empty window is NULL; count() is 0
   -> 6.88% of rows disagreed between training and serving
```

This is why the project doesn't need a managed feature store — a test removes the same
risk for free.

### 4. Findings nobody else publishes

```
28%       of laundering rings straddle a naive train/test cut
58%       of test rings must be DELETED to stay leak-free (32M rows)
87%       at 182M rows — being honest gets MORE expensive as data grows
4.7%      the hard ceiling on recall@50; reporting recall without it looks like failure
0.075     Cramér's V of IBM's "drift" — overwhelming p-value, negligible effect
```

### 5. A cut with evidence behind it

The drift experiment was built, tested, and **cut** — because it was measured that the
synthetic positives were 3× easier to detect than real ones (average precision 0.88 vs
0.30), so the model saturated and no decay could be observed.

Cutting your own favourite idea on evidence you generated yourself is a stronger signal
than any drift curve would have been.

---

## What the cloud adds

Exactly one thing, and it's the missing half of your stated goals:

> *"showcases that I can process and handle production level data volume"*

```
                      NOW              AFTER
rows                  31,898,238       182,060,762     5.7x
data                  2.8 GB           17 GB
compute               your laptop      Azure
cost/throughput table none             all three sizes
crossover point       unmeasured       measured and plotted
"what broke at 182M"  no answer        the answer            <- most-asked question
```

We already know where to look. Measured on your machine:

```
stage             5.08M rows    31.9M rows    throughput change
────────────────────────────────────────────────────────────────
normalize            1.4s          8.0s       3.6M -> 4.0M rows/s   flat
reconcile            1.1s          4.6s       4.6M -> 6.9M rows/s   flat
build_features       6.9s        515.7s       739K ->  62K rows/s   12x WORSE
```

Feature building is **12× slower per row** at 6× the data. That's DuckDB spilling to
disk. **That is the crossover, and finding exactly where it happens is the deliverable.**

---

## The honest summary

> You have a finished, defensible project that proves something most people can't.
> What it lacks is scale. The cloud work adds scale to work that is already correct —
> which is the right order to do it in, and the opposite of how most projects go.
