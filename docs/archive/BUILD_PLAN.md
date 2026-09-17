> # ⚠️ SUPERSEDED — historical record only
>
> This file describes a plan that was **not built**. It is kept because the
> decisions and their reasons are part of the project's history, not because
> any of it is current.
>
> **Current state: [`HANDOFF.md`](../../HANDOFF.md)** (or `HANDOFF.md` at the
> repo root). Architecture actually built: one Azure VM + Bicep, single-node
> DuckDB. Not AWS, not Terraform, not Azure ML, not Synapse.
>
> Anything in this file about status, test counts, cost, services or
> infrastructure is out of date by construction.

# DriftGraph — Build Plan & Workflow Map

**Companion to** `AML_PROJECT_KNOWLEDGE.md` (the source of truth for *decisions*).
**This file is the source of truth for *execution*** — what we build, in what order, and how the pieces connect.

**Written:** 2026-08-11 · **Status:** awaiting owner review before Phase 0 begins.

---

## Part 1 — What this project actually is (plain English)

### The real-world problem

Banks are legally required to watch every transaction for money laundering. A bank the
size of the one in our dataset moves ~180 million transactions in four months. Roughly
**0.076%** of them are criminal — about 1 in every 1,300.

A bank cannot investigate 180 million transactions. It employs a fixed number of
investigators, and each can review a fixed number of cases per day. So the actual job
is **not** "find all the fraud." The job is:

> Given a fixed number of investigation slots per day (say 50), which 50 accounts do we
> hand to the humans so we catch as much laundering as possible?

That reframing is the whole project. It changes what "good" means. A model that is 99.9%
accurate is worthless here — you get 99.9% by calling everything clean. What matters is
**what fraction of the real laundering ends up in the top 50 slots.** That number is
called `recall@budget`.

### Why laundering is hard to detect

Criminals do not launder money in one transaction. They do it in **rings** — a group of
accounts moving money between each other in a shaped pattern over weeks or months:

```
  FAN-OUT                 CYCLE                   SCATTER-GATHER
  one -> many         money goes in a loop      spread out, then collect

     A                      A --> B                A -> B -\
   / | \                    ^      |               A -> C --> Z
  B  C  D                   |      v               A -> D -/
                            D <-- C
```

Our dataset gives us **8 named ring shapes** (typologies). In the big file there are
**16,467 labeled rings** covering **137,936 transactions**. The median ring touches
7 accounts. One ring type (GATHER-SCATTER) runs a median of **56 days**.

That 56-day figure is the single most important number in this project, and Part 3
explains why.

### The three things this project proves to a hiring manager

1. **I can process production-scale data correctly.** The same code runs on 5 million
   rows and 182 million rows, with only a config file changing. We publish the speed
   and cost at both sizes.
2. **I understand evaluation, which is where most ML projects silently lie.** See Part 3.
3. **I know what NOT to build.** We keep a written list of every AWS service we
   considered and rejected, with the reason. This is a deliverable, not an afterthought.

### What we are deliberately NOT claiming

| We will not say | Because |
|---|---|
| "Big data" | 17 GB is *large*, not big. Senior reviewers will call this out. |
| "Real-time streaming" | The dataset is a static historical file. Streaming it is a simulation. |
| "State of the art detection" | 38,000 people downloaded this dataset. The model is not the contribution. |
| "I found concept drift" | We *measured* that IBM's data has none (Cramér's V = 0.075). We **manufacture** the drift, and say so every single time. |
| Any AUC number as the headline | At 0.076% prevalence AUC sits at ~0.99 and hides everything. |

---

## Part 2 — The data (what we are actually holding)

### Two files matter

| File | Size | Rows | Time span | What it is |
|---|---|---|---|---|
| `HI-Small_Trans.csv` | 475 MB | 5,078,345 | 18 days | Every transaction. Our **development** file. |
| `HI-Large_Trans.csv` | 17.05 GB | ~182,060,762 | ~119 days | Same thing, big. Our **scale** file. |
| `HI-Small_Patterns.txt` | ~0.3 MB | 370 rings | 18 days | The answer key — which rings, what shape. |
| `HI-Large_Patterns.txt` | 13.8 MB | 16,467 rings | ~119 days | Same, big. **Small enough to work with locally.** |

`HI-Small` is **not** a subset of `HI-Large`. They are two independent simulation runs
with different accounts. You cannot cross-validate one against the other.

### The transaction file looks like this

```
Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering
2022/09/01 00:20,010,8000EBD30,010,8000EBD30,3697.34,US Dollar,3697.34,US Dollar,Reinvestment,0
2022/09/01 00:20,03208,8000F4580,001,8000F5340,0.01,US Dollar,0.01,US Dollar,Cheque,0
```

### The answer-key file looks like this

```
BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/01 04:33,021174,800737690,020,80020C5B0,8630.40,Euro,8630.40,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT
```

One `BEGIN…END` block = one ring, with its shape named on the header line.

### Three landmines in this data

**Landmine 1 — there are two columns literally named `Account`.**
The header is `From Bank, Account, To Bank, Account`. If you load this with default
settings, pandas silently renames the second one to `Account.1` and you will not notice
until a join produces wrong numbers. Spark and Athena will either crash or mangle it.
Iceberg refuses the table outright.

*Fix, in the very first commit:* never let any tool infer the header. Declare the schema
explicitly and rename **by position**:

```
position 0  Timestamp          -> event_time
position 1  From Bank          -> sender_bank
position 2  Account            -> sender_account
position 3  To Bank            -> receiver_bank
position 4  Account            -> receiver_account
position 5  Amount Received    -> amount_received
position 6  Receiving Currency -> receiving_currency
position 7  Amount Paid        -> amount_paid
position 8  Payment Currency   -> payment_currency
position 9  Payment Format     -> payment_format
position 10 Is Laundering      -> is_laundering
```

Then build the real account key: `sender_id = sender_bank + "_" + sender_account`.
**Account IDs are only unique within a bank** — account `8000EBD30` at bank `010` is a
different account from `8000EBD30` at bank `011`.

Also: bank codes are zero-padded strings. `010` ≠ `10`. Never parse them as integers.

**Landmine 2 — only ~62% of laundering transactions have a named ring.**
In HI-Small, `Trans.csv` flags **5,177** transactions as laundering, but the pattern
blocks only account for **3,209** of them. The other **1,968 (38%)** are laundering with
no named shape.

> Measured in Phase 1. The knowledge doc originally said 3,579 / 69%; that count treated
> each block's `BEGIN` header line as a transaction. See §5.6 of the knowledge doc.

This is by design, not a bug — not every crime fits a textbook pattern. Consequences:

- Typology is a **nullable enrichment**. It is never a join key, never a required field.
- Any typology-based metric is reported *only over the labeled subset*, with the
  coverage number (62%) stated next to it.

**Landmine 3 — self-transactions exist.** Row 1 in the sample above sends money from an
account to itself (`Reinvestment` format). Never assume `sender != receiver`.

---

## Part 3 — The one thing that makes this project good (the leakage problem)

This is the section to understand. Everything else is plumbing.

### The naive approach, and why it produces a lie

Standard machine learning practice: train on the past, test on the future. Cut the
timeline at day 90, train on days 1–90, test on days 91–119.

```
  day 1 ........................ day 90 ................. day 119
  |------------- TRAIN -----------|-------- TEST ----------|
```

Now recall that a GATHER-SCATTER ring runs a **median of 56 days**, and rings touch a
median of 7 accounts. So a ring that starts on day 70 looks like this:

```
  day 1 ........................ day 90 ................. day 119
  |------------- TRAIN -----------|-------- TEST ----------|
                        [=== ring #4471, accounts A,B,C,D ===]
                          ^^^^^^^^^ ^^^^^^^^^^^^^^^^^^^^^
                          in TRAIN     in TEST
```

The model trains on the first half of the ring. It memorises that accounts A, B, C, D
behave criminally. Then at test time it sees those exact same accounts again and scores
them highly.

**Your metrics look excellent. Not because the model generalises — because it memorised
the answer.** And the amount of inflation is unknowable, so you cannot even correct for it **[SUPERSEDED 2026-09-12: it was measurable, was measured, and is correctable -- it is a prevalence ratio. See paper/RESULTS_split_inflation.md]**.

This is the single most common silent failure in fraud-detection portfolio projects, and
almost nobody catches it. Catching it is our headline.

### Our fix: ring-aware, entity-disjoint, temporal split

```
STEP 1   Pick a cut time T.

STEP 2   Assign each RING (not each transaction) to train or test,
         by the ring's START time.
             ring starts before T  -> train
             ring starts after  T  -> test

STEP 3   Collect the accounts:
             train_accounts = every account in every train ring
             test_accounts  = every account in every test ring

STEP 4   overlap = train_accounts  ∩  test_accounts
         For every ring on the TEST side that touches an overlapping account:
             DROP THAT ENTIRE RING.
         (We drop from test, not train. Dropping from test shrinks our
          test set — which is honest. Dropping from train would leak.)

STEP 5   Cut transactions by time as well:
             train keeps only transactions before T
             test  keeps only transactions after  T

STEP 6   ASSERT, and fail the build if violated:
             train_accounts ∩ test_accounts == ∅
             no ring_id appears on both sides

STEP 7   Record in the run manifest: how many rings were dropped,
         and how many positives survive in test.
         If test has too few positives -> MOVE T. Never weaken the assertion.
```

### The planted-leak test (the part that makes it provable)

An assertion that passes proves nothing on its own — a broken detector also passes.

So we deliberately break it: we inject a feature computed from future data, run the
pipeline, and **assert that performance jumps implausibly.** If it doesn't jump, our
leak detector is broken and we would never know.

```
   normal run   ->  recall@50 = 0.72     (assertion passes)
   planted leak ->  recall@50 = 0.99     (test asserts this jump HAPPENS)
```

This turns "my numbers are clean" from a claim into a demonstration.

### How we measure: `recall@budget`, unit = (account, day)

Before this project, the spec said `recall@B` without saying what B counted. Fifty
transactions, fifty accounts, and fifty rings are three different projects.

**Decision: one alert = one `(account, calendar day)` pair** — because that is what a
human investigator actually opens and reviews.

```
FOR each calendar day d:
    FOR each account a active on day d:
        score(a, d) = max( model score over a's transactions on day d )
    rank all (a, d) by score, descending
    take the top B

recall@B  =  (# positive (account,day) pairs that landed in any top-B)
             ---------------------------------------------------------
                    (total # positive (account,day) pairs)

A (account, day) is POSITIVE if any transaction touching that account
on that day has is_laundering = 1.
```

Default `B = 50`. We report a sweep over B ∈ {10, 25, 50, 100, 200}, because a single
budget is a hidden assumption.

### The manufactured drift

The original project idea was: "models decay over time, let's measure it and see if
retraining helps." We tested whether IBM's data actually drifts.

**It does not.** Every one of the 8 typologies sits at ~12.5% ± 1.5pp in every week of
the dataset. The chi-square test says p = 1.3e-75 (wildly significant) but
**Cramér's V = 0.075**, which means the effect is negligible. This is the classic
statistics trap: overwhelming significance, meaningless effect size.

So we **build** the drift instead. Because we hold ring-level typology labels, we can
resample which ring shapes appear in which month:

| bucket | FAN-OUT | FAN-IN | CYCLE | BIPARTITE | STACK | SCAT-GAT | GAT-SCAT | RANDOM |
|---|---|---|---|---|---|---|---|---|
| M1 | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% |
| M2 | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% |
| **M3** | 5% | 5% | **30%** | 5% | **30%** | 10% | 10% | 5% |
| **M4** | 2% | 2% | **40%** | 3% | **40%** | 5% | 5% | 3% |

Method: sample **whole rings** (never individual transactions), time-shift each ring so
it lands in the target bucket while preserving its internal timing, rewrite its account
IDs so instances never collide, and log every `(source_ring → instance, shift, account_map)`
into a `drift_manifest.json`.

**Because we constructed it, the ground truth is exact.** We can then dial drift
magnitude up and down and publish *effect size as a function of drift magnitude* — a
sensitivity curve. That is strictly stronger than finding drift in the wild, where you
never know its true size.

**Honesty rule, non-negotiable:** every mention of this result says the drift is
**induced, not observed.**

---

## Part 4 — The pipeline (data flow)

Fourteen components. Every one runs identically as a local command and as a cloud task —
same code, different config. That is what makes "Phase 4: lift to AWS" a config change
rather than a rewrite.

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │  RAW                                                                │
 │  Kaggle CSV  ->  s3://bucket/raw/   (immutable, versioned, sha256)  │
 └─────────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        v                       v                       v
 ┌─────────────┐        ┌──────────────┐        ┌──────────────────┐
 │normalize_   │        │parse_patterns│        │validate_contracts│
 │schema       │        │              │        │                  │
 │             │        │Patterns.txt  │        │row counts, nulls,│
 │fix the dup  │        │ -> (ring_id, │        │ranges, keys.     │
 │Account bug, │        │  typology,   │        │NON-ZERO EXIT on  │
 │build        │        │  txns,       │        │any failure —     │
 │composite    │        │  start, end) │        │never warn-and-   │
 │account keys │        │              │        │continue.         │
 └──────┬──────┘        └───────┬──────┘        └──────────────────┘
        │                       │
        v                       v
 ┌─────────────┐        ┌─────────────────┐
 │  BRONZE     │        │reconcile_labels │
 │  Iceberg    │<-------│                 │
 │  table,     │        │join flagged     │
 │  partitioned│        │positives to     │
 │  by day     │        │rings. Quantify  │
 └──────┬──────┘        │the unlabeled 38%│
        │               └─────────────────┘
        v
 ┌────────────────────────────────────────────────────────┐
 │ build_features                                         │
 │                                                        │
 │ ABSOLUTE RULE: every feature uses ONLY information     │
 │ strictly BEFORE that transaction's own timestamp.      │
 │                                                        │
 │  transaction-level : log amount, currency mismatch,    │
 │                      fx ratio, roundness, hour, dow,   │
 │                      self-transfer, cross-bank         │
 │  account history   : rolling 1/7/30-day counts, distinct│
 │                      counterparties, amount vs history │
 │  graph             : degree, 2-hop size, clustering,   │
 │                      fan-in/out ratio, component size  │
 │                      (computed with SQL, NOT a graph DB)│
 └──────────────────────┬─────────────────────────────────┘
                        v
                 ┌─────────────┐
                 │   SILVER    │
                 │  features,  │
                 │  by day     │
                 └──────┬──────┘
                        │
        ┌───────────────┴────────────────┐
        v                                v
 ┌──────────────────┐          ┌──────────────────────┐
 │make_drift_       │          │ build_splits         │
 │schedule          │          │                      │
 │                  │          │ ring-aware,          │
 │resample rings to │--------->│ entity-disjoint,     │
 │hit a target      │          │ temporal             │
 │typology mix per  │          │ + THE ASSERTION      │
 │month.            │          │ (fails the build)    │
 │emits drift_      │          └──────────┬───────────┘
 │manifest.json     │                     │
 └──────────────────┘                     v
                              ┌────────────────────────┐
                              │ train_model            │
                              │  1. logistic regression│
                              │     (the floor)        │
                              │  2. GBDT  <- primary   │
                              │  3. GraphSAGE (only if │
                              │     justified by data) │
                              └──────────┬─────────────┘
                                         v
                              ┌────────────────────────┐
                              │ score_shard            │
                              │ batch inference per    │
                              │ evaluation bucket      │
                              └──────────┬─────────────┘
                                         v
                              ┌────────────────────────┐
                              │ evaluate               │
                              │  recall@B sweep        │
                              │  average precision     │
                              │  ring-level recall     │
                              │  per-typology recall   │
                              │  calibration           │
                              │  bootstrap CIs at the  │
                              │  RING level            │
                              └──────────┬─────────────┘
                                         v
                              ┌────────────────────────┐
                              │  GOLD                  │
                              │  results, manifests,   │
                              │  throughput+cost table,│
                              │  drift curves, plots   │
                              └────────────────────────┘

                              ┌────────────────────────┐
                              │ teardown               │
                              │ terraform destroy      │
                              │ + orphan sweep         │
                              └────────────────────────┘
```

Every component must emit: explicit input/output URIs, a `manifest.json`, structured JSON
logs, a deterministic config hash, non-zero exit on contract failure, and an idempotency
key of `component + input_hash + config_hash + code_sha` so re-running is free and safe.

---

## Part 5 — Where it runs (AWS architecture)

Rule: every service below is followed by *the requirement that forces it to exist.*
If we cannot state the requirement, the service gets cut.

```
                     ┌──────────────────────────────────────┐
                     │      GitHub Actions (CI/CD)          │
                     │  OIDC federation -> IAM role         │
                     │  NO static AWS keys, anywhere, ever  │
                     └──────────────┬───────────────────────┘
                                    │ terraform apply
                                    v
 ┌─────────────────────────────────────────────────────────────────────┐
 │                      AWS Step Functions                             │
 │                      (the conductor)                                │
 │  Standard workflow for the outer pipeline.                          │
 │  Distributed Map + EXPRESS children for the 182M-row fan-out.       │
 │  Native .sync calls — no glue code between stages.                  │
 │  WHY: MWAA (managed Airflow) is $350+/month minimum. Disqualifying. │
 │       Step Functions: $0.025 per 1,000 transitions, 4,000 free.     │
 │  COST TRAP: in Distributed Map, EVERY child's transitions are       │
 │             billed. Standard children at 182M scale = real money.   │
 └──┬──────────┬───────────┬───────────┬────────────┬─────────────────┘
    │          │           │           │            │
    v          v           v           v            v
 ┌──────┐ ┌─────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
 │DuckDB│ │   EMR   │ │ Athena │ │SageMaker │ │  Lambda  │
 │ on   │ │Serverless│ │        │ │ Training │ │container │
 │Fargate│ │         │ │ SQL on │ │  Jobs    │ │  image   │
 │      │ │  Spark  │ │Iceberg │ │          │ │          │
 │5M rows│ │182M rows│ │        │ │ ephemeral│ │ inference│
 │& all │ │         │ │$5/TB   │ │ artifacts│ │ p99<100ms│
 │dev   │ │per-vCPU-│ │scanned │ │ -> S3    │ │ scales   │
 │      │ │ second  │ │pennies │ │ auto     │ │ to zero  │
 └──┬───┘ └────┬────┘ └───┬────┘ └────┬─────┘ └────┬─────┘
    │          │          │           │            │
    └──────────┴──────────┴─────┬─────┴────────────┘
                                v
 ┌─────────────────────────────────────────────────────────────────────┐
 │              S3 + Apache Iceberg + Glue Data Catalog                │
 │                                                                     │
 │  raw/     immutable Kaggle CSVs, versioning on                     │
 │  bronze/  Iceberg, schema-normalised, partitioned by event_date    │
 │  silver/  features, partitioned by event_date                      │
 │  gold/    training sets, eval results, run manifests               │
 │                                                                     │
 │  WHY ICEBERG, not plain Parquet: we must be able to say            │
 │  "model X was trained on table snapshot Y." Snapshots + time travel│
 │  + ACID appends + schema evolution. Costs the same as plain S3.    │
 └─────────────────────────────────────────────────────────────────────┘

 ┌─────────────────────────────────────────────────────────────────────┐
 │  CloudWatch  — structured JSON logs, 7-day retention (or it creeps) │
 │  custom metrics that matter: recall@budget, rows/sec,               │
 │  cost per million rows, rings dropped by the split                  │
 │  AWS Budgets  — alarm -> SNS -> email. In the Terraform itself.     │
 └─────────────────────────────────────────────────────────────────────┘
```

### The DuckDB vs Spark question — we measure it, we don't guess

Reflexively reaching for Spark on 17 GB is exactly the over-engineering to avoid — 17 GB
fits comfortably on one machine. So we run **both engines at both data sizes** and publish
where single-node stops winning:

```
  time
   ^
   │                                        ╱ DuckDB (single node)
   │                                      ╱
   │                                   ╱
   │                          ╱─────╳──────  <- THE CROSSOVER
   │                    ╱────╱      │           (this is the deliverable)
   │              ╱────╱            │
   │  ────────────                  │        EMR Serverless (Spark)
   └────────────────────────────────┴───────────> rows
       5M                          ???        182M
```

"I measured where single-node stops being the right answer, here's the plot" is a much
stronger interview answer than either "I used Spark" or "I used DuckDB."

### The cut list — services deliberately rejected

| Rejected | Why |
|---|---|
| MWAA (managed Airflow) | $350+/month minimum. Disqualifying. |
| MSK / Kafka | Streaming is out of v1 entirely. |
| Redshift | Athena over Iceberg answers every question. Redshift adds a cluster to pay for. |
| SageMaker Feature Store | The offline/online parity **test** is the valuable artifact. The managed service adds cost, not signal, at this scale. |
| Neptune / any graph DB | Ring structure = connected components over a table. SQL does this fine. |
| EKS / Kubernetes | Nothing here needs an orchestrator. |
| Multi-region failover | No availability requirement exists for a portfolio artifact. |
| Always-on SageMaker endpoints | Lambda scales to zero. Model is <100 MB, CPU-only. |
| GPU, any type | GBDT is CPU work. |
| Spark as the only engine | 17 GB fits single-node. Not measuring the crossover is the over-engineering. |
| SMOTE / synthetic oversampling | Fabricates transactions belonging to no ring, corrupting every ring-level metric. |
| Kinesis / DynamoDB (v1) | No requirement forces streaming. Cutting it: ~$30–60/mo → ~$5–15/mo. |
| Azure | Azure ML managed endpoints do not scale to zero. |

**Cost target: ~$5–15/month.** Nothing meaningful idles, because there are no standing
endpoints, clusters, or shards.

---

## Part 6 — Build order

Every phase ends with something that runs and is committed. Phases 0–3 are **entirely
on your laptop** — no AWS, no cost, no risk.

```
LOCAL ONLY, NO AWS
├── PHASE 0  Make code exist
│   Repo skeleton, pyproject.toml, CI skeleton.
│   ONE commit: read HI-Small_Trans.csv with an explicit schema that
│   fixes the duplicate-Account bug, write Parquet partitioned by day.
│   DONE WHEN: `make ingest` produces day-partitioned Parquet locally.
│
├── PHASE 1  Labels and the split       <-- LOAD-BEARING
│   Pattern parser (reuse drift-test/ibm_patterns.py).
│   Label reconciliation — quantify the unlabeled 38%.
│   Ring-aware entity-disjoint split WITH the assertion.
│   DONE WHEN: the assertion runs in CI and fails on a deliberately
│              bad cut time.
│   NOTE: every downstream number is wrong if this is wrong.
│
├── PHASE 2  Features and baseline
│   Causal transaction + account-history features.
│   Logistic regression (the floor), then GBDT.
│   recall@budget with the B ∈ {10,25,50,100,200} sweep.
│   DONE WHEN: a numbers table exists for HI-Small.
│
├── PHASE 3  The leak-detection proof   <-- CREDIBILITY GATE
│   Planted-leak test. Offline/online parity test. Repro test.
│   DONE WHEN: all three pass.
│   NOTE: numbers from Phases 0-2 are NOT trustworthy until this passes.
│
AWS BEGINS — money starts moving
├── PHASE 4  AWS lift
│   Terraform: S3, Glue, Iceberg, Athena, IAM, Budgets.
│   Move bronze/silver to S3. Step Functions wraps the existing CLI.
│   NOTHING about the logic changes — this is a path and config change.
│   That payoff is why we built CLI-first.
│   DONE WHEN: `terraform apply` then `terraform destroy` both run clean.
│
├── PHASE 5  Scale to 182M              <-- GOAL #2 CONTENT
│   EMR Serverless on HI-Large. Expect: partition skew, shuffle spill,
│   OOM, read amplification.
│   WRITE DOWN WHAT BROKE AND HOW YOU FIXED IT. Keep a running log.
│   "What broke at 182 million rows?" is the question interviewers most
│   want answered, and it cannot be faked.
│   DONE WHEN: throughput + cost table exists for both rungs.
│
├── PHASE 6  The drift experiment       <-- THE NAME OF THE PROJECT
│   Manufactured-drift generator + schedule + manifest.
│   Four update strategies: frozen / naive retrain / sliding window /
│   typology-aware replay.
│   Sensitivity curve: effect size vs drift magnitude.
│   DONE WHEN: the curve exists with ring-level bootstrap CIs.
│
├── PHASE 7  Graph features — ONLY IF JUSTIFIED
│   Run only if Phase 6 leaves measurable headroom.
│   Report the delta, or skip the phase and say why. Both are fine.
│
├── PHASE 8  Release
│   README with the cut list. One ADR per decision. Figures.
│   Demo script. Reproducibility command. Teardown proof.
│
└── PHASE 9  Optional
    Elliptic appendix figure (one afternoon, already measured).
    Bounded Kinesis replay demo (~$11/month while running).
```

---

## Part 7 — Current state of your machine

| Thing | Status | Action needed |
|---|---|---|
| Python 3.12.3 (pyenv) | ✅ present | none |
| AWS CLI, region us-east-1 | ✅ present | **credentials are a problem — see C1** |
| Docker | ✅ present | none |
| git | ✅ present | none |
| Homebrew | ✅ present | none |
| Terraform | ❌ missing | `brew install terraform` |
| DuckDB CLI | ❌ missing | `brew install duckdb` (Python lib via pip too) |
| Kaggle API token | ❌ `~/.kaggle` is empty | need a fresh token |
| IBM dataset | ❌ not downloaded | Phase 0 blocker |
| Free disk | ⚠️ **45 GB** | **see C2** |
| Prior analysis scripts | ✅ `drift-test/` — 7 scripts, reusable | `ibm_patterns.py` and `drift_test2.py::recall_at_budget` go straight into Phases 1 and 2 |
| Existing project code | ❌ zero lines | that is what we are here to fix |

---

## Part 8 — Concerns

Ordered by how much they can hurt.

### C1 — You are using AWS ROOT access keys. Fix before Phase 4. ⚠️ SECURITY

`aws sts get-caller-identity` returns:

```
"Arn": "arn:aws:iam::867492128345:root"
```

Those are static, permanent, unrestricted root credentials sitting in a plaintext file
at `~/.aws/credentials`. If they leak, the entire account is gone — billing included,
with no recovery path. AWS's own guidance is to have **zero** root access keys in
existence.

**Fix (30 minutes, before any AWS work):**
1. Create an IAM user `driftgraph-dev` with a scoped policy.
2. Enable MFA on the root account.
3. Move the new keys into a named profile: `aws configure --profile driftgraph`.
4. **Delete the root access keys** in IAM → Security credentials.
5. Every command and every Terraform run uses `--profile driftgraph`.

This is also a portfolio asset. "No static keys, OIDC federation from CI, root keys
deleted" is a real answer to a real interview question.

This does **not** block Phases 0–3, which are entirely local.

### C2 — 45 GB free disk. HI-Large should never touch your laptop.

The math:

```
  free disk                      45 GB
  HI-Large_Trans.csv            -17 GB
  Kaggle zip (deleted after)     -5 GB   (peak, transient)
  bronze Parquet                 -3 GB
  silver features               -5 to 15 GB   <- features multiply columns
  ------------------------------------------
  remaining                     ~5 to 15 GB, and macOS gets unhappy below ~10 GB
```

Too tight, and a full disk mid-run corrupts state.

**Recommendation:** HI-Large is **cloud-only**. Bootstrap it into S3 from a throwaway EC2
instance (t3.medium, 40 GB EBS, download → `aws s3 cp` → terminate; ~$0.20 total, one
script in `scripts/`). Your laptop only ever holds HI-Small (475 MB) plus both
`Patterns.txt` files (14 MB).

This costs nothing architecturally — EMR Serverless reads from S3 anyway. It just makes
explicit what the design already implies.

### C3 — HI-Small is 18 days. The drift experiment needs months.

`AML_PROJECT_KNOWLEDGE.md` §D2 says "build on HI-Small, run on HI-Large." That is right
for everything *except* Phase 6. The drift schedule uses **four monthly buckets**, and
HI-Small spans **18 days total**. You physically cannot build a 4-month drift schedule
on it.

**Not a blocker — the fix is clean.** `HI-Large_Patterns.txt` is only 13.8 MB and spans
the full ~119 days. We develop the whole drift generator locally against that file (it
runs in seconds), and only join it to the 182M-row transaction file in the cloud.

Flagging it now so it isn't discovered as a surprise in Phase 6.

### C4 — HI-Small may be thin for stable evaluation numbers.

HI-Small has 370 rings across 18 days. After a temporal cut and dropping every overlapping
test ring, we might be left with very few test rings, and `recall@50` computed on a handful
of positive account-days will be extremely noisy.

**Not a design flaw, but a thing to check early.** Phase 1 must report the surviving
positive count. If it is too small, options in order of preference:
1. Move the cut time.
2. Accept that HI-Small is a *correctness* rung (does the code run, do the assertions
   fire) and HI-Large is the *numbers* rung. This is a legitimate and honest position.
3. Add HI-Medium (3 GB, 28 days) as a middle rung — reverses D2, needs a real reason.

I would plan for option 2 and confirm it with Phase 1's actual numbers.

### C5 — What is the Lambda inference endpoint actually serving?

In a batch-only v1 there is no live traffic. §11.6 says "GBDT under 100 MB, p99 <100ms" —
but nothing is calling it.

Its real justification is that it is the **"online" half of the offline/online parity
test**: the CI test that proves the batch feature path and the serving feature path
produce identical vectors. That is a genuinely strong artifact.

We should say that explicitly in the README rather than implying a serving requirement
that does not exist. Otherwise a sharp interviewer will ask "who calls this?" and there
is no answer.

### C6 — Cost ceiling is undefined.

§23 open question #1. The design assumes ~$15/month is acceptable, but you never said a
number. The dominant cost is **repeated HI-Large runs** (~$1–3 each). Without a stated
ceiling I cannot size the guardrails.

I need a number before Phase 4. Whatever it is, the AWS Budget alarm gets set to it in
the Terraform.

### C7 — Timeline is undefined, and scope needs a floor.

Nine phases is a lot. Phases 0–3 are days of work; Phases 4–6 are the bulk. If there is
a deadline (job applications, semester end), we should decide now which phases are the
**must-ship floor** versus stretch.

My recommendation for a minimum credible release: **Phases 0–5 plus 8.** That gives the
volume claim, the leak-free evaluation, the crossover measurement, and the cut list —
which is already a strong project. Phase 6 (the drift experiment) is what makes it
*distinctive* and justifies the project's name, so it should be the first stretch item,
not the last.

Phase 7 (GraphSAGE) and Phase 9 (Elliptic, Kinesis) are genuinely optional and should
stay optional.

---

## Part 9 — Decisions needed from you

Before Phase 0 (local, no cost):

1. **Where does the repo live?** Proposal: `Final Projects/AML/aml-platform/`, its own
   git repo, pushed to GitHub as a public portfolio repo (needed for GitHub Actions +
   OIDC in Phase 4).
2. **Confirm the build order** in Part 6, or tell me what to change.

Before Phase 4 (AWS begins):

3. **Fix the root keys** (C1).
4. **Monthly cost ceiling** (C6).
5. **Scope floor** — which phases must ship (C7).
6. **Fresh Kaggle API token.** The one from the 2026-08-11 session was pasted in
   plaintext and must be rotated at Kaggle → Settings → Expire API Token. Pass the new
   one as an ephemeral environment variable only — never into a file or a commit.

---

*End of build plan. Decisions live in `AML_PROJECT_KNOWLEDGE.md`; execution lives here.*
