> # ⛔ ARCHIVED — a pre-fix design record, not the current specification
>
> **Archived 2026-09-14. Do not read anything below as a description of the
> current system.**
>
> This document's status block declares that `txn_id` is non-deterministic
> "today", that no cross-engine equality test can therefore pass, and that "one
> join inside the leak proof is already silently wrong". **All three were true
> when it was written and none of them is true now.** Transaction identity is
> assigned once during normalization from the physical file order and carried
> downstream; `aml-platform/tests/repro/test_txn_id_identity.py` pins
> contiguity, tie handling, thread-count independence and run-to-run equality,
> and the leak proof was re-run after the fix.
>
> It is kept because the defect and its specification are part of the record —
> and because this file is itself an exhibit. **The v1 audit flagged exactly
> this sentence** ("`FEATURE_SPEC_v1.md` says `txn_id` is non-deterministic
> 'today' and marks it a blocker"), and it survived four audit rounds sitting
> in `aml-platform/docs/` presenting itself as the live design. A reviewer
> reading it had no way to tell whether to trust the code or the spec. That is
> a worse failure than the original bug, because it is a failure of the thing
> that is supposed to catch bugs.
>
> The engine-neutral feature definitions in §1–§6 are still accurate, and the
> §7 trap list is still useful. The Spark implementation they were written for
> was never built; the DuckDB implementation is the only one.

# Feature specification v1

**Purpose.** Define the 32 features precisely enough that a PySpark
implementation written from this document alone produces output that matches the
DuckDB implementation exactly. That equality test is Gate 2, and no timing
number from the DuckDB↔Spark comparison may be quoted until it passes.

**Engine-neutral means:** this document never says "DuckDB does X". It states
the intended computation, then names the engine-specific traps separately, in
§7. Nine of them have already cost this project a bug.

## Status of this version

```text
✅ §1-§6   the specification. Complete.
⛔ §8      A BLOCKER. txn_id is not deterministic today, so no cross-engine
           equality test can pass -- and one join inside the leak proof is
           already silently wrong. Must be fixed before Stage 2 starts.
```

---

## 1. Inputs and grain

| | |
|---|---|
| input | `gold/reconcile/` — one row per transaction, day-partitioned Parquet |
| output | `silver/features/` — one row per transaction, day-partitioned by `event_date` |
| rows in = rows out | yes, exactly. This is a projection, never a filter |

Input columns relied upon:

```text
event_time  TIMESTAMP (minute resolution)   sender_id / receiver_id  VARCHAR
sender_bank / receiver_bank  VARCHAR        amount_paid / amount_received  DOUBLE
payment_currency / receiving_currency VARCHAR
payment_format VARCHAR    is_laundering TINYINT
ring_id BIGINT NULL       typology VARCHAR NULL      event_date DATE
```

`ring_id` and `typology` are nullable enrichments carried through untouched.
They are **labels, not features** — see §5.

---

## 2. The absolute rule

> Every feature must be computable from information strictly **before** the
> transaction's own `event_time`.

No global aggregates. No forward windows. No target encoding over the full
dataset. A feature that peeks at the future makes the model look excellent in
testing and useless in production, and it fails as silently as a bad split.

### The minute-resolution consequence

Timestamps are minute-resolution, so many transactions share an exact
`event_time`. A window frame ending at `CURRENT ROW` would therefore include
**siblings from the same minute** — information not available at decision time.

Every trailing window must end **one minute before** the current row:

```text
RANGE BETWEEN <span> PRECEDING AND INTERVAL 1 MINUTE PRECEDING
```

At minute granularity this means "everything strictly earlier, nothing from this
minute." Enforced by `tests/leakage/test_causal_features.py`, which plants a
future outlier and requires it not to appear.

**Spark note:** Spark has no interval-based `RANGE` frame. See §7.1 — this is
the single most likely place for a Spark port to be quietly wrong.

---

## 3. The two-sided event stream

A mule account mostly **receives**. Aggregating only rows where it was the
sender would make its history look empty.

So each transaction contributes **two account-events**:

```text
txn  A --($500)--> B
     │
     ├─ event(account=A, side='s', cp=B, amount=500, is_out=1)
     └─ event(account=B, side='r', cp=A, amount=500, is_out=0)
```

```sql
events =
    SELECT txn_id, 's' AS side, sender_id   AS account_id, event_time,
           amount_paid, receiver_id AS cp, 1 AS is_out FROM t
  UNION ALL
    SELECT txn_id, 'r' AS side, receiver_id AS account_id, event_time,
           amount_paid, sender_id  AS cp, 0 AS is_out FROM t
```

At HI-Large this stream is ~364M events for ~182M transactions. **It is never
persisted** — it exists only inside the feature computation. That distinction
matters when reasoning about memory: the 364M figure is a count, not a table.

History is computed **per account over this stream**, then joined back to both
sides of each transaction.

---

## 4. The features

### 4a. Transaction-level (12) — no history, nothing to leak

| feature | definition | type |
|---|---|---|
| `log_amount_paid` | `ln(1 + amount_paid)` | double |
| `log_amount_received` | `ln(1 + amount_received)` | double |
| `fx_ratio` | `amount_received / amount_paid`, **NULL when `amount_paid = 0`** | double |
| `currency_mismatch` | `payment_currency <> receiving_currency` → 1/0 | int8 |
| `amount_roundness` | 3 if `amount_paid` is a whole 1000; else 2 if whole 100; else 1 if whole unit; else 0 | int8 |
| `hour` | hour of `event_time`, 0–23 | int |
| `dayofweek` | **0 = Sunday … 6 = Saturday** | int |
| `is_weekend` | `dayofweek ∈ {0, 6}` → 1/0 | int8 |
| `is_self_transfer` | `sender_id = receiver_id` → 1/0 | int8 |
| `is_cross_bank` | `sender_bank <> receiver_bank` → 1/0 | int8 |
| `payment_format_code` | stable integer code in `[0, 1000)` for the format string | int |
| `payment_currency_code` | stable integer code in `[0, 1000)` for the currency string | int |

`amount_roundness` is a structuring signal: launderers round amounts to sit just
under reporting thresholds.

⚠️ The two `*_code` features are **not portable as currently implemented** —
see §7.3. Cardinality is tiny (7 formats, 15 currencies measured on HI-Medium),
which makes the fix cheap.

### 4b. Account history (20) — 10 per side

Computed over the §3 event stream, per `account_id`, then joined to the sender
side (prefix `s_`) and the receiver side (prefix `r_`).

| feature | window | definition |
|---|---|---|
| `n_1d` | 1 day | count of prior events |
| `n_7d` | 7 days | count of prior events |
| `n_30d` | 30 days | count of prior events |
| `mean_amt_7d` | 7 days | mean `amount_paid` |
| `std_amt_7d` | 7 days | **population** stddev of `amount_paid` |
| `max_amt_30d` | 30 days | max `amount_paid` |
| `n_out_7d` | 7 days | `sum(is_out)`, **coalesced to 0 when the window is empty** |
| `secs_since_prev` | 30 days | `event_time − max(prior event_time)`, in seconds |
| `secs_since_prev_cp` | unbounded, partitioned by `(account_id, cp)` | seconds since this account last dealt with *this counterparty* |
| `amt_vs_hist` | — | `amount_paid / mean_amt_7d`, **NULL when `mean_amt_7d = 0`**. Computed *after* the join, not in the window |

Every window frame is `RANGE BETWEEN <span> PRECEDING AND INTERVAL 1 MINUTE
PRECEDING`. `secs_since_prev_cp` uses `UNBOUNDED PRECEDING` as its lower bound.

**Nulls are meaningful and must be preserved, not filled.**
`secs_since_prev IS NULL` means "this account's first ever transaction" —
legitimately unknown, and the GBDT handles it natively. Measured on HI-Small:
8.59% of rows. Filling it with 0 or -1 would assert something false.

**`n_out_7d` and the empty-window trap.** `sum()` over an empty window returns
NULL, while `count()` over the same empty window returns 0. That made
`n_out_7d` NULL exactly where `n_7d` was 0 — inconsistent inside the batch path
and different from the serving path, which computes Python `sum([]) == 0`. **0
is the correct answer**: we *know* there were no outgoing transactions. Caught
by `tests/parity/`.

### Why `secs_since_prev_cp` and not a distinct-counterparty count

An earlier version computed `len(list_distinct(list(cp) OVER w7d))`. Exact, but
it materialises one list per row and exceeded 12.7 GiB on 5M rows.
`secs_since_prev_cp` costs one extra sort and carries the signal more directly:
NULL means "never dealt with this counterparty before", which is the
FAN-OUT / SCATTER fingerprint the model actually needs.

---

## 5. Passed through, never features

```text
txn_id  event_time  event_date  sender_id  receiver_id
is_laundering   <- the label
ring_id         <- evaluation grouping, nullable
typology        <- reporting only, nullable, ~62-66% coverage
```

Feeding `ring_id` to a model would be the `target` leak from the leak-proof
ladder. The feature list is declared explicitly in code so a new column cannot
silently become a feature.

---

## 6. Output contract

```text
one row per input transaction, no filtering
32 features + 8 passthrough columns
partitioned by event_date
```

**Equality tolerance for Gate 2:**

| column class | tolerance |
|---|---|
| integer and boolean features | **exact** |
| double features | **1e-9 relative** |
| nulls | **exact** — null must equal null, never 0 |
| row count | **exact** |
| row identity | joined on `txn_id`, never on position |

⚠️ "Joined on `txn_id`" is doing a lot of work in that table, and §8 is why.

---

## 7. Engine traps

Each of these has either already caused a bug here or will silently break a
Spark port.

### 7.1 Interval RANGE frames — the big one

Spark's `rangeBetween` takes **numbers, not intervals**. The frame must be
expressed in seconds over a numeric timestamp:

```python
secs = F.col("event_time").cast("timestamp").cast("long")
w7d = (Window.partitionBy("account_id").orderBy(secs)
       .rangeBetween(-7 * 86400, -60))     # -60 == "INTERVAL 1 MINUTE PRECEDING"
```

Getting `-60` wrong — writing `0`, or `Window.currentRow` — reintroduces the
same-minute leakage that §2 exists to prevent, and **every test would still
pass** because the leakage test lives on the DuckDB side. Stage 2 must run the
planted-outlier leakage test against the Spark implementation too.

Also note the boundaries are **inclusive** in both engines: `-7*86400`
includes an event exactly 7 days earlier.

### 7.2 `ln` vs `log`

DuckDB's `log()` is **base 10**; numpy's `np.log` is natural. An earlier version
used `log()`, producing values 2.3× smaller than the serving path computes — so
every threshold the model learned would land on the wrong side in production,
with no error raised anywhere. Caught by `tests/parity/`.

**The spec means natural log.** DuckDB `ln()`, Spark `F.log()` (which is
natural), numpy `np.log`.

### 7.3 Hash-derived codes are not portable ⚠️

Currently `payment_format_code = hash(payment_format) % 1000`, using the
engine's internal hash. Measured: DuckDB gives `hash('ACH') % 1000 = 251`.
**Spark's hash is a different function and will give a different number**, so
these two features can never match across engines.

Options:

| option | preserves current values? | portable? |
|---|---|---|
| **materialise a code map** — emit the ~22-row (string → code) mapping once from DuckDB, have both engines join to it | ✅ yes | ✅ yes |
| switch both engines to `md5(s)` mod 1000 | ❌ no, invalidates Phase 2 | ✅ yes |
| explicit hand-written dictionary | ❌ no | ✅ yes, and most interpretable |

**Recommended: the code map.** Cardinality is 7 and 15, so the artifact is
trivial, existing results stay valid, and it removes a hash dependency from the
feature definition entirely. Cost: one extra small output and a broadcast join.

### 7.4 `dayofweek` numbering differs

```text
DuckDB   0 = Sunday ... 6 = Saturday      (verified)
Spark    1 = Sunday ... 7 = Saturday
```

So Spark must emit `dayofweek(ts) - 1` for the feature, and test
`is_weekend` against `{1, 7}` before shifting. Off by one here silently rotates
a categorical feature by a day.

### 7.5 Population vs sample stddev

`std_amt_7d` is **population** stddev. On `[1,2,3]`: population `0.8165`,  <!-- derived -->
sample `1.0`. DuckDB `stddev_pop`, Spark `F.stddev_pop` — **not** `F.stddev`,
which is the sample version.

### 7.6 Empty-window `sum()` → NULL

See §4b. Both engines return NULL for `sum()` over an empty frame; both need
the explicit coalesce to 0. Do not assume Spark differs here — it does not, and
the coalesce is required in both.

### 7.7 Division by zero

`fx_ratio` and `amt_vs_hist` must yield **NULL**, not infinity and not an error.
DuckDB `nullif(x, 0)`; Spark's `/` already returns null on zero denominator, but
write the `nullif` anyway so the intent survives a refactor.

### 7.8 Negative-precision rounding

`amount_roundness` compares `amount_paid` to `round(amount_paid, -3)` and
`round(amount_paid, -2)`. Verified in DuckDB: `round(1500.0, -3) = 2000`, i.e.
half rounds away from zero. **Spark's rounding mode at negative scale must be
confirmed against this by test, not assumed** — a mismatch would shift the
feature for every amount sitting exactly on a `.5` boundary.

### 7.9 `epoch()` returns seconds as a double

DuckDB `epoch(interval)` → float seconds. Spark: subtract the two long-cast
timestamps. Keep the result a double so nulls stay representable.

---

## 8. ⛔ BLOCKER: `txn_id` is not deterministic

`txn_id` is the join key for every downstream artifact — scores, leak tables,
splits, and the Gate 2 equality test. It is currently derived as:

```sql
row_number() OVER (ORDER BY event_time, sender_id, receiver_id)
```

**That ordering key is not unique.** Measured on HI-Medium:

```text
rows                                              31,898,238
rows sharing an (event_time, sender_id, receiver_id) key  658,850   (2.1%)
largest tie group                                          4 rows
```

Within a tie group the order is unspecified, and DuckDB parallelises the sort.
Measured — the same query, on the same data, three times:

```text
threads=8   digest 69215768756d102f
threads=1   digest f42e5d6aeca3814d
threads=8   digest 31d054694d97e0b3     <- differs from the first run
                                           at IDENTICAL settings
```

**Every run assigns different `txn_id`s to tie-group rows.**

### Why this is not merely theoretical

`features/build.py` and `leakproof/plant.py` **each recompute `txn_id`
independently** with this same unstable expression. `leakproof/prove.py` then
joins them:

```python
tr = tr.merge(lk, on="txn_id", how="left", validate="one_to_one")
```

`validate="one_to_one"` checks **cardinality only** — that each key appears once
per side. It does not and cannot check that a given `txn_id` denotes the same
transaction in both tables. So for rows in tie groups, leak columns are attached
to the wrong transactions, the validation passes, and nothing reports a problem.

The affected artifact is the **leak-detection proof**, which is the project's
central credibility claim.

Three consequences:

1. **Gate 2 cannot pass.** Row identity is unstable within one engine, so a
   cross-engine equality test has nothing stable to join on.
2. **Cross-run joins are unsound.** Rebuild features, keep old scores, join by
   `txn_id` → silently mismatched rows.
3. `test_features_are_bit_reproducible` passes only because the fixtures are
   tiny and tie-free. The test is real; its data does not exercise this.

### The fix

Measured: ordering on **all 14 bronze columns** leaves only **20 fully identical
rows** out of 31.9M — and those are interchangeable by construction (same
amounts, same label, same everything), so which one receives which id cannot
affect any computation.

| option | verdict |
|---|---|
| **assign `txn_id` once in `normalize`, carry it through bronze** | ✅ **recommended.** Identity is assigned at ingest and never re-derived, so the two call sites cannot disagree. Removes the window function from the identity path entirely, which also simplifies the Spark port |
| extend the `ORDER BY` to all columns in both places | ⚠️ works, but keeps two independent derivations that must stay in sync, and sorts on 14 columns |
| content hash of all columns | ⚠️ portable, but collides for genuine duplicates and is more expensive |

Either fix changes `txn_id` values, so features and leak tables must be
rebuilt. **Feature *values* do not depend on `txn_id`**, and train/test
membership is determined by `event_time` and `ring_id`, so the headline model
metrics are expected to be unchanged — but that must be *verified*, not
assumed. The leak-proof numbers may genuinely move, because that join is
currently corrupt for ~2% of rows.

---

## 9. Reference implementation

`src/aml/features/build.py`. Where this document and the code disagree, **the
code is authoritative for v1** and this document is a bug — with the sole
exception of §8, where the code is the bug.
