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

# AML Transaction Monitoring Platform — Complete Project Knowledge

**Project codename:** DriftGraph
**Cloud:** AWS
**Dataset:** IBM AMLworld
**Status:** decided, not yet built (zero lines of code as of 2026-08-11)
**Owner:** Nirmalkumar Kesavan
**Document version:** 1.0 — 2026-08-11
**Supersedes:** `Guides-documents/Final projects/03_driftgraph_aml_aws_knowledge_transfer.md` and `04_driftgraph_aml_azure_knowledge_transfer.md`

> **This file is the single source of truth.** Where it disagrees with the older `03_`/`04_` manuals, this file wins. The older manuals were written before any dataset was measured; several of their core assumptions were tested and falsified on 2026-08-11 (see §4).

---

## Table of contents

1. [Project identity](#1-project-identity)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Decision log](#3-decision-log)
4. [Empirical record — what was actually measured](#4-empirical-record--what-was-actually-measured)
5. [The dataset — complete reference](#5-the-dataset--complete-reference)
6. [Claims the project will and will not make](#6-claims-the-project-will-and-will-not-make)
7. [The manufactured-drift design](#7-the-manufactured-drift-design)
8. [Evaluation design](#8-evaluation-design)
9. [Feature engineering](#9-feature-engineering)
10. [Models](#10-models)
11. [AWS architecture](#11-aws-architecture)
12. [The cut list](#12-the-cut-list)
13. [Pipeline components](#13-pipeline-components)
14. [MLOps — versioning, lineage, manifests](#14-mlops--versioning-lineage-manifests)
15. [Testing strategy](#15-testing-strategy)
16. [IaC and CI/CD](#16-iac-and-cicd)
17. [Cost engineering](#17-cost-engineering)
18. [Repository structure](#18-repository-structure)
19. [Build sequence](#19-build-sequence)
20. [Definition of done](#20-definition-of-done)
21. [Interview defense](#21-interview-defense)
22. [Risks and anti-patterns](#22-risks-and-anti-patterns)
23. [Open questions](#23-open-questions)
24. [References](#24-references)
25. [Appendix A — exact commands](#appendix-a--exact-commands)
26. [Appendix B — session artifacts on disk](#appendix-b--session-artifacts-on-disk)

---

## 1. Project identity

### One-sentence definition

**A batch AML transaction-monitoring platform that processes 182 million transactions on AWS, ranks accounts for investigator review under a fixed daily budget, and measures how much detection performance decays over time — with a leak-free, ring-aware evaluation that proves the numbers are real.**

### The 30-second pitch

> I built an anti-money-laundering detection platform on AWS that processes 182 million transactions. The interesting part isn't the model — it's the evaluation. Money laundering rings span dozens of accounts and months of time, so the obvious train/test split leaks: the same ring lands on both sides and your metrics look great for no reason. I built an entity-disjoint temporal split that provably prevents it, then measured how a frozen model decays over time and how much retraining actually recovers. The answer was less than you'd expect.

### Why this project exists

Three things it demonstrates, in the order a hiring manager cares:

1. **Large-volume data engineering that is correct, not just big.** 182M rows, 17 GB, same codebase from 5M to 182M, with a measured cost and throughput curve.
2. **Evaluation discipline under extreme class imbalance.** 0.076% positives, ring-structured labels, a review budget, and a split design that can be proven leak-free by assertion.
3. **Engineering judgment about what NOT to build.** A documented cut list with reasons is a first-class deliverable.

---

## 2. Goals and non-goals

### The two stated goals (verbatim from the owner)

1. "good portfolio project with complex stuff and good architecture and tech stack"
2. "showcases that i can process and handle production level data volume and stuff and concepts"

### Derived engineering success criteria

A v1 release must:

- run the identical pipeline on HI-Small (5M rows) and HI-Large (182M rows) with no code change, only config;
- produce a throughput + cost table for both rungs;
- enforce a ring-aware, entity-disjoint, temporal train/test split with a hard assertion that no laundering ring straddles the boundary;
- report `recall@budget` with the alert unit explicitly defined as `(account, day)`;
- demonstrate a measurable performance decay over event time, and quantify how much retraining recovers;
- reproduce any run from a manifest (data version, code SHA, config hash, model artifact hash);
- tear down to $0 recurring with a single command;
- state, in the README, every AWS service considered and rejected, with the reason.

### Non-goals

- **No streaming in v1.** IBM AMLworld is a static historical file. Streaming it is a *simulation* of a stream, not a stream. See §11.9.
- **No graph database.** Ring structure is connected components over the transaction table. DuckDB and Spark compute this fine.
- **No GPU.** Gradient-boosted trees and GraphSAGE at this node count are CPU work.
- **No claim of "big data."** 17 GB is *large*, not *big*. Claiming otherwise damages credibility with senior reviewers.
- **No real-time SLA claim** without a stated requirement that forces one.
- **No production deployment.** This is a portfolio artifact with a teardown script, not a service.
- **No attempt to beat published AMLworld benchmarks.** The contribution is the platform and the evaluation rigour, not a leaderboard score.

---

## 3. Decision log

Every decision, with the reason and the date. Reversing one of these requires a reason at least as strong.

| # | Decision | Reason | Date |
|---|---|---|---|
| D1 | **Dataset: IBM AMLworld** | Only candidate with 182M rows, named typology labels, and 5+ months of event time. Schema identical across size variants. | 2026-08-11 |
| D2 | **Build on HI-Small, run on HI-Large. Skip HI-Medium.** | Iterating on 17 GB is slow and costs money; 475 MB iterates in seconds. Two rungs is enough — small to build, large to prove. A third rung was overkill. | 2026-08-11 |
| D3 | **Reject TransXion** | 3.03M rows is a laptop file. No typology column. 78% of positive components are a single transaction — almost no graph. | 2026-08-11 |
| D4 | **Reject AMLGentex** | It is a generator, not a dataset — a project before the project. It also vendors AMLSim internally, so it is not an independent second tool. | 2026-08-11 |
| D5 | **Demote Elliptic to one optional appendix figure** | It has 165 anonymized features, no account IDs, no amounts, no usable timestamps. It cannot traverse the IBM pipeline. It is a second *system*, not a second feed. | 2026-08-11 |
| D6 | **Cloud: AWS** | SageMaker Serverless and Lambda scale to zero; Azure ML managed online endpoints bill hourly while deployed. S3 + Athena over Parquet costs pennies. Broader hiring surface. | 2026-08-11 |
| D7 | **Batch only. No Kinesis, no DynamoDB in v1.** | No requirement forces streaming to exist. Cutting it drops the bill from ~$30–60/mo to ~$5–15/mo. | 2026-08-11 |
| D8 | **Orchestration: Step Functions** | MWAA is ~$350+/month minimum, which is disqualifying. Step Functions Standard is $0.025/1,000 state transitions with 4,000/month free. Native `.sync` integrations to Glue, EMR Serverless, Athena and SageMaker remove all glue code. | 2026-08-11 |
| D9 | **Table format: Apache Iceberg on S3** | Reproducible point-in-time training sets need snapshots and time travel; schema evolution and ACID appends are real requirements. Cost is effectively S3 alone. Best AWS-native support (Athena, Glue, EMR). | 2026-08-11 |
| D10 | **Compute: measure the DuckDB↔EMR-Serverless crossover rather than pick one** | 17 GB genuinely fits DuckDB single-node, so reaching for Spark by reflex is the over-engineering to avoid. Publishing *where* single-node stops winning is a stronger artifact than either tool. | 2026-08-11 |
| D11 | **Manufacture the drift from IBM's own pattern blocks** | IBM's typology mix is uniform and stationary by design (Cramér's V = 0.075), so the original drift claim is unmeasurable as-is. But ring-level typology labels allow resampling and time-shifting to *induce* a non-stationary mix with exact ground truth. Surfaced by 3 of 5 council reviewers independently. | 2026-08-11 |
| D12 | **Alert unit = `(account, day)`** | The original spec's `recall@B` had no defined unit — alerts are entities/day, labels attach to transactions, typologies to rings. 50 transactions, 50 accounts and 50 rings are three different projects. Investigators review accounts per day, so that is the unit. | 2026-08-11 |
| D13 | **No SageMaker Feature Store** | Build the offline/online parity CI test by hand instead. The *test* is the impressive artifact; the managed service is a cost with no added signal at this scale. | 2026-08-11 |
| D14 | **No Neptune** | Ring structure = connected components over the transaction table. DuckDB/Spark compute it fine. Cutting a graph DB deliberately, with a stated reason, reads better than adding one. | 2026-08-11 |
| D15 | **Inference: Lambda container image, not SageMaker endpoint** | Model is a GBDT under 100 MB, CPU-only, p99 <100ms is achievable. Lambda scales to zero and is cheaper. | 2026-08-11 |
| D16 | **IaC: Terraform, CI: GitHub Actions with OIDC federation** | No static AWS keys anywhere. More portable and more commonly requested in job postings than CDK. | 2026-08-11 |

---

## 4. Empirical record — what was actually measured

**Everything in this section was produced by running code on 2026-08-11, not read from documentation.** It is the justification for §3, and it is the part of this project that cannot be recovered from any paper or README. Scripts and outputs live in `drift-test/` at the workspace root.

### 4.1 TransXion — the original planned dataset

Loaded the full `tx.csv` (245,159,741 bytes, pulled via GitHub's LFS media endpoint because `git-lfs` was not installed).

**Shape:** 3,029,170 transactions · 365 days (2025-01-01 00:00:29 → 2025-12-31 22:59:18) · 47,526 unique accounts · 4,641 positives (0.1532%).

**Real drift exists — the fear that it wouldn't was wrong.** Monthly prevalence in basis points:

| month | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bps | 7.89 | 18.84 | 18.94 | 19.80 | **26.96** | 14.53 | 10.31 | 14.11 | 12.51 | 14.12 | 15.03 | 13.54 |

- χ² (month × is_laundering) = 454.52, dof 11, **p = 1.574e-90**. Range 7.89 → 26.96 bps = **3.42×**.
- Kendall τ on daily prevalence = −0.0658, p = 0.060 → **no monotone trend**. The pattern is episodic bursts, not drift in one direction.
- Positive-class `Payment Format` mix: χ² = 49.0, dof 33, p = 0.036, **Cramér's V = 0.0593** → statistically detectable, practically negligible.
- Positive `Amount Paid`, first half vs second half: KS = 0.1145, p = 1.60e-13, median 45.27 → 60.85. Negative-class control: KS = 0.0526, p = 1.64e-60 (significant only because n = 100,000).

**A frozen detector decays, and it is not an artifact.** Trained on months 1–6, evaluated monthly on 7–12, `recall@50 account-days/day`:

| | Jul | Aug | Sep | Oct | Nov | Dec | slope | p |
|---|---|---|---|---|---|---|---|---|
| frozen | 0.774 | 0.757 | 0.654 | 0.636 | 0.567 | 0.578 | −0.0448/mo | 0.0028 |
| retrained | 0.774 | 0.749 | 0.685 | 0.677 | 0.593 | 0.622 | −0.0353/mo | 0.0046 |

Average precision fell 0.2384 → 0.1081. AUC 0.9930 → 0.9840.

**Critical robustness check.** The account-history features (`s_prior_n`, `r_prior_n`) grow mechanically because the dataset starts 2025-01-01 with empty history — a cold-start artifact, not drift. Removing them and substituting within-month counts:

| | Jul | Dec | change | slope | p |
|---|---|---|---|---|---|
| frozen | 0.829 | 0.636 | **−0.193** | −0.0359/mo | **0.0006** |
| retrained | 0.829 | 0.702 | −0.128 | −0.0219/mo | 0.0102 |

**The decay survived.** It is real drift. And the retraining benefit got *larger and significant*: mean gain +0.0359, paired t p = 0.0217, bootstrap 95% CI [+0.0166, +0.0546], excludes zero.

**But retraining recovers only 19% of the decay.** 81% is not fixable by training on more data. This is the most interesting result of the entire investigation and it appears in none of the original manuals.

**Why TransXion was still rejected:**
- No typology column. `Is Laundering` is binary 0/1 only.
- 4,641 positives form 1,804 connected components, of which **1,405 (78%) are a single transaction**. Median ring = 2 accounts. Two giant components (242 and 191 accounts) carry nearly all structure. Only 171 rings have ≥3 transactions.
- 3.03M rows does not support a volume claim.

### 4.2 IBM AMLworld — the chosen dataset

**The typology mix is uniform and stationary by design.** Parsed `HI-Large_Patterns.txt` (13,807,473 bytes) → 16,467 labeled rings, 137,936 laundering transactions, ring starts spanning 2022-08-01 → 2022-11-27.

Weekly typology share, 14 consecutive weeks (2022-08-01 → 2022-11-06): every one of the 8 typologies sits at **~12.5% ± 1.5pp**. χ² = 643.8, dof 112, p = 1.267e-75 — but **Cramér's V = 0.0747**, which is negligible. The entire "significance" comes from the final 3 weeks, where the generator stops injecting 6 of the 8 typologies (115, 31, then 3 rings per week versus ~1,150/week normally). That is an end-of-simulation tail-off, not drift.

**Conclusion: IBM hands you the typology label TransXion lacks, and simultaneously proves there is no natural typology drift to find.** Hence D11 — manufacture it.

### 4.3 Elliptic — the real drift, verified

203,769 nodes · 234,355 edges · 165 features · 49 time steps (~2 weeks each ≈ 2 years) · 46,564 labeled (4,545 illicit = 9.8%) · 157,205 unknown · 306 MB.

Trained a RandomForest on steps 1–34 (n = 29,894, illicit = 3,462) rather than trust the folklore:

| step | 35 | 36 | 37 | 38 | 39 | 40 | 41 | 42 | **43** | 44 | 45 | 46 | 47 | 48 | 49 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | .975 | .881 | .750 | .933 | .934 | .742 | .906 | .860 | **.000** | .069 | .000 | .500 | .000 | .000 | .035 |

Mean F1 steps 35–42: **0.776**. Mean F1 steps 44–49: **0.101**. A **−87% collapse**, with F1 exactly 0.000 at steps 43, 45, 47 and 48 — the model goes completely blind. Illicit rate drops 11.1% (step 42) → 1.8% → 1.5% → 0.4% → 0.3%.

This is a genuine real-world distribution shift (widely attributed to a dark-market shutdown) and it is far more violent than anything in either synthetic dataset. Retained as **one optional appendix figure**, not a second pipeline leg.

---

## 5. The dataset — complete reference

### 5.1 Provenance

- **Paper:** Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu — *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models*, NeurIPS 2023 Datasets & Benchmarks. arXiv:2306.16424
- **Generator name:** AMLworld (agent-based, IBM Research + ETH Zurich)
- **Kaggle:** `ealtman2019/ibm-transactions-for-anti-money-laundering-aml` — 8,176,169,418 bytes total, 38,171 downloads, 263 votes
- **GitHub:** `IBM/AML-Data`
- **License:** Community Data License Agreement – Sharing – Version 1.0 (**CDLA-Sharing-1.0**). Permissive for a public portfolio; share-alike applies to redistributed data.

### 5.2 Variant inventory — exact figures

Row counts: HI-Small **measured exactly**. Others extrapolated at 93.7 bytes/row, which reproduces the paper's stated 175–180M for the large variants.

| variant | rows | bytes | span (ring starts) | days | pattern rings | pattern txns | flagged txns | prevalence |
|---|---|---|---|---|---|---|---|---|
| HI-Small | **5,078,345** | 475,664,283 | 2022-09-01 → 2022-09-18 | 18 | 370 | **3,209** | 5,177 | 0.1019% |
| HI-Medium | ~32,368,296 | 3,031,783,420 | 2022-09-01 → 2022-09-28 | 28 | 2,756 | 25,499 | — | ~0.08% |
| **HI-Large** | **~182,060,762** | 17,052,760,651 | 2022-08-01 → 2022-11-27 | ~119 | 16,467 | 137,936 | — | ~0.076% |
| LI-Large | ~178,748,467 | 16,742,513,790 | 2022-08-01 → 2022-11-27 | ~119 | 2,218 | 21,679 | — | ~0.012% |

Also on Kaggle but unused: `LI-Small`, `LI-Medium`, plus `*_accounts.csv` (34–148 MB each).

**HI-Large's last ring *ends* 2023-01-12** — a few long-running rings extend past the last ring *start*. Ring start span and transaction-file span are not the same number.

### 5.3 Transaction schema

`HI-Small_Trans.csv` header, verbatim:

```
Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering
```

Example rows:

```
2022/09/01 00:20,010,8000EBD30,010,8000EBD30,3697.34,US Dollar,3697.34,US Dollar,Reinvestment,0
2022/09/01 00:20,03208,8000F4580,001,8000F5340,0.01,US Dollar,0.01,US Dollar,Cheque,0
```

| column | type | notes |
|---|---|---|
| `Timestamp` | datetime | format `%Y/%m/%d %H:%M`. Minute resolution, no seconds. |
| `From Bank` | string | zero-padded numeric string. **Keep as string** — leading zeros are significant (`010` ≠ `10`). |
| `Account` (1st) | string | hex-like sender account ID, e.g. `8000EBD30` |
| `To Bank` | string | as above |
| `Account` (2nd) | string | receiver account ID |
| `Amount Received` | float | in receiving currency |
| `Receiving Currency` | categorical | e.g. `US Dollar`, `Euro`, `Yuan`, `Swiss Franc`, `Shekel`, `Canadian Dollar`, `Rupee`, `Yen`, `Australian Dollar`, `Saudi Riyal` |
| `Amount Paid` | float | in payment currency |
| `Payment Currency` | categorical | as above |
| `Payment Format` | categorical | `ACH`, `Cheque`, `Cash`, `Credit Card`, `Wire`, `Reinvestment`, `Bitcoin` |
| `Is Laundering` | int8 | 1 = laundering, 0 = normal |

**Account identity is `(Bank, Account)`, not `Account` alone.** Account IDs are only unique within a bank. Build a composite key.

**Self-transactions exist.** Row 1 above has identical sender and receiver — `Reinvestment` format. Do not assume `from != to`.

### 5.4 GOTCHA 1 — two columns are both literally named `Account`

The header has `From Bank,Account,To Bank,Account`. Consequences:

- **pandas** silently renames the second to `Account.1`. Silent, so you will not notice until a join is wrong.
- **Spark / Athena / Glue** will either fail or mangle it.
- **Iceberg** rejects duplicate column names outright.

**Mandatory fix, in the very first ingest commit:** never read this file with header inference. Declare an explicit schema and rename positionally:

```
Timestamp        -> event_time
From Bank        -> sender_bank
Account   (pos 3)-> sender_account
To Bank          -> receiver_bank
Account   (pos 5)-> receiver_account
Amount Received  -> amount_received
Receiving Currency -> receiving_currency
Amount Paid      -> amount_paid
Payment Currency -> payment_currency
Payment Format   -> payment_format
Is Laundering    -> is_laundering
```

Then derive `sender_id = sender_bank || '_' || sender_account` and likewise for receiver.

This is also a genuine portfolio asset: make the schema validator fail loudly on unexpected headers and write it up as a data-contract story.

### 5.5 The typology labels — `*_Patterns.txt`

A separate plain-text file per variant. Format:

```
BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/01 04:33,021174,800737690,020,80020C5B0,8630.40,Euro,8630.40,Euro,ACH,1
...
END LAUNDERING ATTEMPT - FAN-OUT
```

- One `BEGIN … END` block = **one laundering ring** with a named typology.
- The header line carries a free-text qualifier after the colon (`Max 16-degree Fan-Out`, `Max 10 hops`, `Max 3-degree Fan-In`) — parse and keep it; it encodes the generator's parameters.
- Transaction lines use the **same 11-column schema** as `Trans.csv`, no header.
- The 8 typologies: `FAN-OUT`, `FAN-IN`, `CYCLE`, `BIPARTITE`, `STACK`, `SCATTER-GATHER`, `GATHER-SCATTER`, `RANDOM`.

**HI-Large typology inventory (measured):**

| typology | rings | txns | median txns/ring | median accts/ring | median duration (days) | ring share |
|---|---|---|---|---|---|---|
| BIPARTITE | 2,109 | 12,174 | 4 | 8 | 10.43 | 12.8% |
| STACK | 2,096 | 23,624 | 8 | 12 | 26.51 | 12.7% |
| CYCLE | 2,086 | 12,340 | 5 | 5 | 29.18 | 12.7% |
| SCATTER-GATHER | 2,067 | 26,978 | 10 | 7 | 32.44 | 12.6% |
| GATHER-SCATTER | 2,054 | 26,361 | 13 | 14 | 55.76 | 12.5% |
| FAN-OUT | 2,040 | 13,554 | 6 | 7 | 29.13 | 12.4% |
| FAN-IN | 2,014 | 13,287 | 6 | 7 | 28.81 | 12.2% |
| RANDOM | 2,001 | 9,618 | 4 | 5 | 20.52 | 12.2% |

**Ring structure, HI-Large:** 11,329 rings (69%) have ≥3 transactions; 9,367 (57%) have ≥5. Median 7 accounts per ring, max 45.
**Ring structure, HI-Small:** 258 rings (70%) ≥3 txns; 216 (58%) ≥5. Median 8 accounts, max 45. Per-typology counts range 40 (FAN-IN) to 54 (CYCLE).

**Note the durations.** GATHER-SCATTER rings run a median of **55.76 days**. This is exactly why the split must be entity-disjoint as well as temporal — see §8.3.

### 5.6 GOTCHA 2 — typology labels cover only ~62% of positives

> **CORRECTED 2026-08-11 (Phase 1).** This section originally said 3,579 pattern
> transactions and 69% coverage. Both were wrong: the original count included each
> block's `BEGIN` header line as if it were a transaction. `HI-Small_Patterns.txt` has
> 4,319 lines = 370 BEGIN + 370 END + 370 blank + **3,209 transactions**. The HI-Large
> figure (137,936) was already correct. Verified by the reconciliation join, which
> matched all 3,209 with zero misses and zero ambiguity. Pinned in
> `tests/contract/test_hi_small_patterns.py`.

HI-Small: `Trans.csv` flags **5,177** transactions as laundering, but the pattern blocks contain only **3,209**. So **1,968 flagged transactions (38%)** belong to **no named pattern**.

This is by design, not a defect — not every laundering transaction is part of a canonical typology. But it has hard consequences:

- **Never write code that assumes a positive has a typology.** Typology is a *nullable enrichment*, never a join key or a required field.
- Any typology-conditioned model must handle the null class explicitly, or it silently trains on 31% of positives as noise.
- Report typology-conditioned metrics only over the labeled subset, and state the coverage figure.
- This is a legitimate positive-unlabeled learning angle if you want one.

### 5.7 GOTCHA 3 — the variants are independent runs with different spans

**HI-Small is not a subset of HI-Large.** They are separate simulation runs with different account populations. You cannot validate against Large by assuming Small is contained in it.

And they cover different time spans (18 / 28 / 119 days), so **volume and time span are confounded** across rungs. A naive "throughput vs rows" chart mixes two variables, and anything time-dependent is not comparable.

**Fix, only needed if the scale chart is published as a claim:** define the benchmark on a **fixed 18-day window** present in all variants, so only row count varies. Then run a second sweep on HI-Large alone across increasing spans to isolate the time dimension. Two clean charts.

---

## 6. Claims the project will and will not make

### Will claim

1. **Same pipeline, 5M → 182M rows, no code change.** With measured wall-clock, cost per million rows, and a written account of what broke at the top rung and how it was fixed.
2. **A provably leak-free evaluation.** Ring-aware entity-disjoint temporal split with an assertion in CI.
3. **`recall@budget` with a defined unit** — `(account, day)`, at a stated budget.
4. **Measured performance decay over event time**, and the fraction of it that retraining recovers.
5. **Typology-conditioned detection** over the ~62% labeled subset, with coverage stated.
6. **A documented cut list** — every AWS service considered and rejected, with reasons.
7. **Where single-node beats distributed**, measured, with the crossover point.

### Will NOT claim

- ❌ "Big data." 17 GB is large, not big.
- ❌ "Real-time streaming." It is batch, with an optional honest replay demo.
- ❌ "Production deployment." It is a portfolio artifact with a teardown script.
- ❌ "State of the art detection." AMLworld has hundreds of public notebooks; the contribution is the platform, not the AUC.
- ❌ "Natural concept drift on IBM." Measured Cramér's V = 0.075. The drift is *induced*, and that must be said plainly every time it is mentioned.
- ❌ Any AUC figure as the headline. At 0.076% prevalence AUC is near-saturated and misleading. Lead with `recall@budget` and average precision.

---

## 7. The manufactured-drift design

**Origin:** surfaced independently by 3 of 5 council reviewers on 2026-08-11; proposed by no advisor. It is the highest-value idea produced by that session.

### 7.1 The problem it solves

IBM's typology mix is uniform and stationary (§4.2), so "does typology-aware retraining beat naive retraining under drift?" cannot be answered — there is no drift. But you hold **ring-level typology labels**, which means you can *construct* the drift instead of hoping for it.

### 7.2 Method

1. Parse `HI-Large_Patterns.txt` into `(ring_id, typology, [transactions], start_time, end_time)`. Already implemented — see `drift-test/ibm_patterns.py`.
2. Choose a **drift schedule**: a target typology mix per time bucket. Example over 4 months, with a deliberate regime change at month 3:

   | bucket | FAN-OUT | FAN-IN | CYCLE | BIPARTITE | STACK | SCAT-GAT | GAT-SCAT | RANDOM |
   |---|---|---|---|---|---|---|---|---|
   | M1 | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% |
   | M2 | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% | 12.5% |
   | **M3** | 5% | 5% | 30% | 5% | 30% | 10% | 10% | 5% |
   | **M4** | 2% | 2% | 40% | 3% | 40% | 5% | 5% | 3% |

3. **Resample rings, do not duplicate transactions.** For each bucket, sample whole rings without replacement from the pool of that typology, then time-shift the entire ring so its start lands in the bucket, preserving internal inter-transaction deltas.
4. Rewrite account IDs per sampled ring instance with a deterministic namespace suffix so two instances of the same source ring never collide.
5. Keep the negative background unchanged, sampled from the same window.
6. Emit a `drift_manifest.json` recording the schedule, the seed, and every `(source_ring_id → instance_id, time_shift, account_map)`. **The ground truth is exact by construction.**

### 7.3 Invariants that must hold — enforce as tests

- Every emitted ring is internally intact: same transaction count, same relative timing, same typology.
- No account ID appears in two ring instances.
- No ring instance spans a bucket boundary (or if it does, it is assigned by *start* time and that rule is documented).
- The realised typology mix per bucket matches the schedule within sampling tolerance — assert it and report the χ² and Cramér's V, which should now be *large*, in contrast to the 0.075 baseline.
- Re-running with the same seed reproduces byte-identical output.

### 7.4 What it buys

- The original claim becomes measurable, with exact ground truth — better than TransXion's unlabeled drift and cheaper than AMLGentex's generator tax.
- The four update strategies (frozen / naive retrain / full retrain / typology-aware replay) can be separated, because you control the drift magnitude. Report a **sensitivity curve**: effect size versus drift magnitude.
- It justifies the project name.

### 7.5 The honesty requirement

Every mention of this result must say the drift is **induced, not observed**. The framing that works: *"IBM's typology mix is stationary by construction — I measured Cramér's V = 0.075 — so I built a controlled drift generator on top of its ring-level labels, which gives exact ground truth and lets me report effect size as a function of drift magnitude."* That is a stronger statement than pretending the drift was found.

---

## 8. Evaluation design

**This is the most important section in the document.** At 0.076% prevalence the credibility risk is not volume, it is leakage.

### 8.1 The alert unit — `(account, day)`

The original spec's `recall@B` had no unit. Alerts are entities per day, labels attach to transactions, typologies attach to rings. Fifty transactions, fifty accounts and fifty rings are three different projects.

**Decision: an alert is one `(account, calendar_day)` pair.** That is what a human investigator actually reviews.

### 8.2 `recall@budget` — exact definition

```
For each calendar day d:
    score every (account, d) pair by max(model score over that account's transactions on d)
    rank descending
    take the top B
recall@B = (# positive (account, day) pairs in any top-B) / (total positive (account, day) pairs)
```

A positive `(account, day)` is one where any transaction involving that account on that day has `is_laundering = 1`.

Default `B = 50` accounts/day. Report a **sweep** over B ∈ {10, 25, 50, 100, 200}, because a single budget is a hidden assumption.

Reference implementation exists — `drift-test/drift_test2.py`, function `recall_at_budget`.

### 8.3 The split — ring-aware, entity-disjoint, temporal

**Why a plain temporal split is wrong.** GATHER-SCATTER rings run a median of 55.76 days and up to the full span. A cut at day 90 puts the first half of a ring in train and the second half in test. The model has already seen the ring's accounts and its behavioural signature. Metrics inflate, and the amount of inflation is unknowable.

**Algorithm:**

1. Choose cut time `T`.
2. Assign every ring to train or test by its **start** time relative to `T`.
3. Collect `train_accounts` = all accounts in all train rings; `test_accounts` likewise.
4. Compute `overlap = train_accounts ∩ test_accounts`. **Drop every ring touching an overlapping account** from the test side (dropping from test, not train, is the conservative choice — it shrinks the test set rather than leaking into it).
5. Drop all transactions after `T` from train, and all before `T` from test.
6. **Assert:** `train_accounts ∩ test_accounts == ∅`, and no ring appears on both sides. Fail the build if violated.
7. Record dropped-ring count and the resulting positive count in the run manifest. If the test set has too few positives after dropping, move `T` — do not weaken the assertion.

Note that negative-class accounts will also overlap heavily; the assertion applies to **ring-participating accounts**. Document that choice explicitly.

### 8.4 Metric suite

**Primary**
- `recall@budget` at B ∈ {10, 25, 50, 100, 200}, unit `(account, day)`
- Average precision (PR-AUC)

**Secondary**
- Precision@B, and alerts-per-true-positive (the investigator workload number)
- Ring-level recall — fraction of rings with at least one member alerted. This is closer to what an AML team actually cares about than transaction recall.
- Per-typology recall over the labeled subset, with the 62% coverage stated
- Calibration: Brier score and ECE

**Deliberately de-emphasised**
- ROC-AUC. It sat at 0.984–0.993 across all TransXion conditions while `recall@budget` moved 0.83 → 0.64. At this prevalence AUC hides everything that matters. Report it once, in a footnote, and explain why it is not the headline.

**System**
- rows/sec, wall clock, peak memory, cost per million rows, per stage and per rung

### 8.5 Statistical discipline

- Bootstrap 95% CIs on every headline number, resampling at the **ring** level, not the transaction level (transactions within a ring are not independent).
- For paired comparisons across time buckets, report both the paired t-test and Wilcoxon, and be explicit about n. On TransXion with n = 6 months the paired t gave p = 0.056 while the bootstrap CI excluded zero — report both and do not cherry-pick.
- State effect sizes, not just p-values. Cramér's V of 0.075 with p = 1.3e-75 is the canonical trap: overwhelming significance, negligible effect.

---

## 9. Feature engineering

**Absolute rule: every feature must be computable from information strictly before the transaction's own `event_time`.** No target encoding on the full dataset, no global aggregates, no future windows.

### 9.1 Transaction-level

| feature | definition |
|---|---|
| `log_amount_paid` | `log1p(amount_paid)` |
| `currency_mismatch` | `payment_currency != receiving_currency` |
| `fx_ratio` | `amount_received / amount_paid` |
| `amount_round_ness` | is amount a round number (structuring signal) |
| `hour`, `dayofweek`, `is_weekend` | from `event_time` |
| `payment_format` | categorical |
| `is_self_transfer` | `sender_id == receiver_id` |
| `is_cross_bank` | `sender_bank != receiver_bank` |

### 9.2 Account-history — causal only

For both sender and receiver, over trailing windows of 1, 7 and 30 days, strictly before the current transaction:

- transaction count
- distinct counterparties
- mean and stddev of amount
- distinct currencies, distinct payment formats
- ratio of current amount to trailing mean (`amount_vs_history`)
- in-degree / out-degree ratio
- time since that account's previous transaction

**Prefer bounded rolling windows over cumulative expanding counts.** Cumulative counts trend upward simply because the dataset starts with empty history — a cold-start artifact that a model trained on early data will misread as signal. This was measured on TransXion: removing cumulative counts changed frozen recall from 0.774→0.578 to 0.829→0.636 and *improved* the measured retraining benefit from +2.2pp to +3.6pp. Bounded windows are the correct default.

### 9.3 Graph features — computed, not queried

Over a trailing window only, no future edges:

- account degree, in/out split
- 2-hop neighbourhood size
- clustering coefficient
- whether the account sits on a cycle of length ≤ k
- fan-in / fan-out ratio (the direct FAN-IN/FAN-OUT typology signal)
- connected-component size of the trailing-window subgraph
- counterparty concentration (Herfindahl index over counterparties)

All of this is `GROUP BY` and self-join work in DuckDB or Spark. **No graph database.**

### 9.4 Offline/online parity

A CI test that fails the build if the batch feature path and the serving feature path produce different vectors for the same `(account, timestamp)`. Fixture: 100 known accounts at 10 timestamps each. Tolerance: exact for integers, 1e-9 relative for floats.

This test is worth more than adopting a managed feature store.

---

## 10. Models

Deliberately boring. The model is not the contribution.

| stage | model | reason |
|---|---|---|
| Baseline | Logistic regression on transaction features | Establishes the floor. Anything that can't beat it is broken. |
| **Primary** | **Gradient-boosted trees** (LightGBM or `HistGradientBoostingClassifier`) | Best accuracy-per-effort on tabular. Handles NaN natively — important given nullable history features. CPU-only. Sub-100 MB artifact, so Lambda inference works. |
| Optional | GraphSAGE on the trailing-window subgraph | Only if GBDT + graph features leaves measurable headroom. Justify with numbers or skip. |

Class imbalance: use `class_weight='balanced'` or `scale_pos_weight`. Do **not** SMOTE — synthetic minority oversampling on ring-structured data fabricates transactions that belong to no ring and corrupts the ring-level metrics.

Four update strategies for the drift experiment:
1. **Frozen** — trained once, never updated
2. **Naive retrain** — retrain on all data up to each evaluation bucket (expanding window)
3. **Sliding-window retrain** — retrain on the last N days only
4. **Typology-aware replay** — retrain with rings resampled to rebalance under-represented typologies

Strategy 4 is the one the manufactured drift exists to test.

---

## 11. AWS architecture

Every component below is followed by **the requirement that forces it to exist**. If you cannot state that requirement, cut the component.

### 11.1 Storage — S3 + Apache Iceberg

- `s3://<bucket>/raw/` — original Kaggle CSVs, immutable, versioning on
- `s3://<bucket>/bronze/` — Iceberg table, schema-normalized, partitioned by `event_date`
- `s3://<bucket>/silver/` — features, partitioned by `event_date`
- `s3://<bucket>/gold/` — training sets, eval results, run manifests
- Glue Data Catalog as the metastore

**Requirement forcing Iceberg:** reproducible point-in-time training sets need snapshots and time travel; you must be able to say "training run X used table snapshot Y." Also gives schema evolution and ACID appends. Cost ≈ S3 alone.

### 11.2 Query — Athena

**Requirement:** ad-hoc exploration and eval aggregation without standing infrastructure. 17 GB CSV → roughly 2–3 GB as Parquet with dictionary encoding; Athena at $5/TB scanned means pennies per query, and partition pruning cuts most scans to a fraction.

### 11.3 Compute — DuckDB on Fargate, and EMR Serverless

- **DuckDB in a Fargate task** for HI-Small and all development.
- **EMR Serverless** for HI-Large runs.

**Requirement:** D10 — the deliverable is the *crossover measurement*, so both must exist. Run both at both rungs and publish where single-node stops winning. EMR Serverless bills per vCPU-second with no cluster to leave running; Glue's 1-minute minimum billing and DPU granularity make it slightly worse for bursty work.

### 11.4 Orchestration — Step Functions

- **Standard** workflow for the outer pipeline (full execution history is a portfolio screenshot).
- **Distributed Map** with **Express child workflows** for the HI-Large fan-out.
- Native `.sync` integrations: `glue:startJobRun.sync`, `emrserverless:startJobRun.sync`, `athena:startQueryExecution.sync`, `sagemaker:createTrainingJob.sync`.
- Retry/Catch on every state.

**Cost gotcha:** in Distributed Map, each child execution's state transitions are billed. Use Express children for wide fan-out; Standard children will make the transition count material.

### 11.5 Training — SageMaker Training Jobs

**Requirement:** ephemeral compute with automatic artifact capture to S3 and clean MLflow/metadata integration. Scales to zero by definition — the job ends.

### 11.6 Inference — Lambda container image

**Requirement:** GBDT under 100 MB, CPU-only, p99 <100ms achievable, scales to zero. A SageMaker real-time endpoint would bill continuously for no added capability.

### 11.7 Experiment tracking — SageMaker Experiments, or self-hosted MLflow on Fargate

Prefer SageMaker Experiments in v1 (no server to run). If MLflow is wanted for portability, run it on Fargate with an S3 artifact store and scale to zero when idle.

### 11.8 Observability — CloudWatch + OpenTelemetry

Structured JSON logs, one log group per pipeline stage, and custom metrics that actually matter: `recall@budget`, rows/sec, cost per million rows, ring-drop count from the split. X-Ray only if a multi-hop trace exists worth showing — in batch-only v1, it likely does not. Cut it until then.

### 11.9 Streaming — Phase 2 only, and framed honestly

**Not in v1.** IBM AMLworld is a static historical file; streaming it is a simulation of a stream.

If added later, scope it as a **bounded demo**: Kinesis Data Streams at **1 provisioned shard** (~$11/month, versus ~$58/month for On-Demand idling; 1 shard = 1,000 records/sec which is exactly the benchmark ceiling) → Lambda via event source mapping → DynamoDB on-demand for online state. Replay a slice of HI-Large at compressed wall-clock, capture p99 and induce failure modes, then tear it down.

The one thing streaming genuinely buys that batch cannot: event-time vs processing-time handling, at-least-once delivery with idempotency keys, poison-message and partial-batch-failure handling (`bisect_batch_on_function_error`, `maximum_retry_attempts`, on-failure destinations — all configuration, not code), and p99 under load.

Describe it as *"I replayed a historical dataset through Kinesis to exercise event-time correctness and failure handling under retries."* Never imply a live feed.

---

## 12. The cut list

**Write this into the README with the reasons.** Being able to say no, in writing, is one of the highest-signal things in the project.

| Rejected | Why |
|---|---|
| **MWAA (Managed Airflow)** | ~$350+/month minimum. Disqualifying. Step Functions does the job for cents. |
| **MSK / Kafka** | Kinesis suffices at 1,000 events/sec, and MSK Serverless has a high floor. Also streaming itself is out of v1. |
| **Redshift** | Athena over Iceberg answers every question here. Redshift adds a cluster to pay for. |
| **SageMaker Feature Store** | The offline/online parity *test* is the valuable artifact; the managed service adds cost without adding signal at this scale. |
| **Neptune / any graph DB** | Ring structure is connected components over the transaction table. DuckDB/Spark compute it fine. Deliberately cutting this reads better than adding it. |
| **EKS / Kubernetes** | Nothing here needs an orchestrator. Fargate + Lambda cover every workload. |
| **Multi-region / multi-AZ failover** | No availability requirement exists for a portfolio artifact. |
| **Always-on SageMaker endpoints** | Lambda scales to zero and is sufficient for a sub-100 MB CPU model. |
| **GPU (any instance type)** | GBDT is CPU work; GraphSAGE at this node count is minutes on CPU. |
| **Spark as the only engine** | 17 GB fits DuckDB single-node. Using Spark without measuring the crossover is the exact over-engineering to avoid. |
| **SMOTE / synthetic oversampling** | Fabricates transactions belonging to no ring, corrupting ring-level metrics. |
| **Azure** | Azure ML managed online endpoints do not scale to zero. See D6. |

---

## 13. Pipeline components

Every component runs identically as a local CLI and as a cloud task. Same code path, different config.

```
ingest_raw            # Kaggle -> s3://raw/ , verify sha256
normalize_schema      # explicit schema, fix duplicate Account, -> bronze Iceberg
parse_patterns        # *_Patterns.txt -> (ring_id, typology, txns) table
reconcile_labels      # join flagged positives to rings; quantify unlabeled 38%
validate_contracts    # schema, null, range, referential checks; non-zero exit on failure
build_features        # causal rolling-window + graph features -> silver
make_drift_schedule   # optional: manufactured-drift resampling -> gold
build_splits          # ring-aware entity-disjoint temporal split + assertion
train_model           # GBDT; emits model artifact + metrics
score_shard           # batch inference over an eval bucket
evaluate              # recall@B sweep, AP, ring recall, per-typology, calibration
aggregate_report      # cross-rung throughput/cost table, drift curves, plots
teardown              # terraform destroy + orphan sweep
```

Each component must have:
- explicit input and output URIs, no implicit paths
- a written `manifest.json`
- structured JSON logs to stdout
- a deterministic config hash
- **non-zero exit on any contract failure** — never warn and continue
- an idempotency key = `component + input_hash + config_hash + code_sha`, so re-runs are free and safe

---

## 14. MLOps — versioning, lineage, manifests

### The reproducibility key

Any run must be reproducible from:

```
dataset_variant      HI-Small | HI-Large
iceberg_snapshot_id  <snapshot>
code_git_sha         <sha>
config_hash          <sha256 of resolved config>
feature_spec_version 1.x.y
split_spec           {cut_time, seed, dropped_rings}
drift_manifest_id    <id or null>
model_artifact_sha   <sha256>
container_digest     <image@sha256>
```

### Run manifest

Every component writes `manifest.json` containing the reproducibility key, input and output URIs with hashes, row counts in and out, wall clock, peak memory, estimated cost, and the full resolved config. Store under `s3://<bucket>/gold/runs/run_id=<id>/`.

### Lineage

Iceberg snapshots plus Step Functions execution ARNs give a complete chain from raw CSV to eval number. Record the execution ARN in the manifest.

---

## 15. Testing strategy

### Unit
- Schema normalizer rejects a header with duplicate names, and renames positionally when given the known-good header.
- Pattern parser round-trips a synthetic `BEGIN/END` block.
- `recall_at_budget` returns 1.0 when all positives rank first, 0.0 when they rank last, and handles a day with zero positives (must return NaN, not 0).
- Causal feature functions never read a row at or after the target timestamp — assert on a fixture with a planted future outlier.

### Contract
- Row counts match expected per variant (HI-Small exactly 5,078,345).
- No null in required columns.
- `amount_paid > 0`; `event_time` inside the declared variant span.
- `sender_id`/`receiver_id` composite keys are non-null.

### Leakage — the load-bearing tests
- **Split assertion:** `train_accounts ∩ test_accounts == ∅` over ring-participating accounts. Fails the build.
- **No ring on both sides** of the cut.
- **Planted-leak test:** deliberately inject a feature computed from future data and assert that model performance jumps implausibly. This proves the harness can *detect* leakage rather than merely not having any. Without it, a clean result is indistinguishable from a broken detector.

### Parity
- Offline/online feature parity on 100 accounts × 10 timestamps, exact for ints, 1e-9 relative for floats.

### Reproducibility
- Same reproducibility key → byte-identical model artifact and identical metrics.
- Manufactured-drift generator with a fixed seed → byte-identical output.

### Integration
- End-to-end on HI-Small in CI on every PR. Must complete in under 10 minutes or it will be skipped and rot.

---

## 16. IaC and CI/CD

**Terraform** for everything. No console clicks. Remote state in S3 with DynamoDB locking (this is the one justified DynamoDB use in v1 — state locking, not online features).

**GitHub Actions with OIDC federation to an IAM role.** No static access keys anywhere, ever.

Pipeline:

```
PR:     lint -> unit tests -> contract tests -> leakage tests
        -> terraform plan -> end-to-end on HI-Small
merge:  terraform apply (dev) -> integration -> tag artifacts
manual: HI-Large run (gated, because it costs money)
```

Environments: `dev` only, normally. `prod` exists in the Terraform as a named workspace but is not provisioned — this demonstrates environment discipline without paying for it.

**Cost guardrails in the IaC itself:** an AWS Budget with an alarm at a stated threshold, and S3 lifecycle rules moving `raw/` to Glacier Instant Retrieval (or deleting it) after Iceberg conversion is verified.

---

## 17. Cost engineering

### Target

- **~$5–15/month batch-only** (the v1 default)
- ~$30–60/month if the Phase 2 stream is left running — which is why it is not left running

### Where the money actually goes

| item | estimate | note |
|---|---|---|
| S3 storage, 17 GB raw + ~3 GB Parquet | ~$0.50/mo | trivial |
| Athena | pennies | $5/TB, partition-pruned |
| EMR Serverless, HI-Large run | ~$1–3/run | per vCPU-second, no idle cluster |
| Fargate DuckDB runs | cents | |
| SageMaker training jobs | cents–$1 | short CPU jobs |
| Lambda inference | ~$0 | free tier covers a demo |
| Step Functions | ~$0 | 4,000 transitions/month free |
| CloudWatch logs | <$1 | set retention to 7 days, or it creeps |

**The dominant cost is repeated HI-Large runs.** Gate them behind a manual CI approval. Never put a 182M-row run in a PR pipeline.

### Cost-stop procedure

1. Budget alarm fires at threshold → SNS → email.
2. Check Cost Explorer filtered by the project tag (tag **everything**).
3. Kill any running EMR Serverless application and Step Functions executions.
4. Run `terraform destroy`.
5. Sweep for orphans that Terraform does not own: S3 incomplete multipart uploads, CloudWatch log groups, ECR images, Glue catalog entries.

### Teardown checklist

- [ ] Step Functions executions stopped
- [ ] EMR Serverless applications stopped and deleted
- [ ] Fargate tasks stopped
- [ ] Lambda functions deleted
- [ ] `terraform destroy` clean exit
- [ ] S3 buckets emptied (including versions and delete markers) then deleted
- [ ] ECR images deleted
- [ ] CloudWatch log groups deleted
- [ ] Glue catalog databases/tables deleted
- [ ] Budget and SNS topic deleted
- [ ] Cost Explorer shows $0 accruing for 48 hours

---

## 18. Repository structure

```
aml-platform/
  README.md                 # incl. the cut list with reasons
  pyproject.toml
  Makefile                  # make ingest / features / train / eval / all
  .github/workflows/
    pr.yml
    main.yml
    hi-large.yml            # manual approval gate
  infra/
    terraform/
      main.tf  s3.tf  glue.tf  stepfunctions.tf  emr.tf
      lambda.tf  iam.tf  budgets.tf  variables.tf
  src/aml/
    cli.py                  # one entrypoint per pipeline component
    schema.py               # explicit schemas, the duplicate-Account fix
    ingest/
    patterns/               # *_Patterns.txt parser
    features/
      transaction.py  account_history.py  graph.py
    drift/
      schedule.py  resample.py            # manufactured drift
    splits/
      ring_aware.py                       # + the assertion
    models/
      baseline.py  gbdt.py  graphsage.py
    eval/
      recall_at_budget.py  metrics.py  bootstrap.py
    manifest.py
  tests/
    unit/  contract/  leakage/  parity/  repro/  integration/
  notebooks/                # exploration ONLY, no production logic
  docs/
    ADRs/                   # one per decision in §3
    figures/
  scripts/
    download_data.sh  teardown.sh
```

**No production logic may live only in a notebook.**

---

## 19. Build sequence

Each phase ends with something that runs and is committed.

**Phase 0 — make code exist (target: this week)**
Repo, `pyproject.toml`, CI skeleton. One commit: read `HI-Small_Trans.csv` with an explicit schema that fixes the duplicate `Account`, write Parquet partitioned by day. Locally, no AWS.

**Phase 1 — labels and the split**
Pattern parser. Label reconciliation (quantify the unlabeled 38%). Ring-aware entity-disjoint split **with the assertion**. This is commit #2 and it is the load-bearing correctness work — every downstream number is wrong if it is wrong.

**Phase 2 — features and baseline**
Causal transaction + account-history features. Logistic regression, then GBDT. `recall@budget` with the B sweep. All on HI-Small, all local.

**Phase 3 — the leak-detection proof**
Planted-leak test. Offline/online parity test. Reproducibility test. Only now are your numbers trustworthy.

**Phase 4 — AWS lift**
Terraform: S3, Glue, Iceberg, Athena. Move bronze/silver to S3. Step Functions wrapping the existing CLI components. Nothing about the logic changes — this is a path and config change, which is the payoff for building CLI-first.

**Phase 5 — scale**
EMR Serverless on HI-Large. Fix what breaks (expect partition skew, shuffle spill, OOM, and the 93.7-bytes-per-row read amplification). **Write down what broke** — that is the goal-2 content. Produce the throughput and cost table for both rungs.

**Phase 6 — the drift experiment**
Manufactured-drift generator with schedule and manifest. Four update strategies. Sensitivity curve of effect size versus drift magnitude. Calibration.

**Phase 7 — graph features, if justified**
Only if Phase 6 leaves measurable headroom. Report the delta or skip the phase.

**Phase 8 — release**
README with the cut list, ADRs, figures, demo script, reproducibility command, teardown proof.

**Phase 9 — optional**
Elliptic appendix figure. Bounded Kinesis replay demo.

---

## 20. Definition of done

- [ ] Same pipeline runs on HI-Small and HI-Large with only config differing
- [ ] Throughput + cost table published for both rungs, with the confound (§5.7) either controlled or explicitly disclosed
- [ ] DuckDB↔EMR-Serverless crossover point measured and plotted
- [ ] Ring-aware entity-disjoint split with a passing CI assertion
- [ ] Planted-leak test passes — the harness demonstrably detects leakage
- [ ] Offline/online parity test passes
- [ ] `recall@budget` reported with the unit stated and B swept
- [ ] Ring-level recall and per-typology recall reported, with the 62% coverage stated
- [ ] Manufactured-drift experiment with a sensitivity curve, labelled as induced drift
- [ ] Four update strategies compared with ring-level bootstrap CIs
- [ ] Any run reproducible from its manifest
- [ ] Terraform up and down cleanly; teardown checklist verified at $0 for 48h
- [ ] README contains the cut list with reasons
- [ ] One ADR per decision in §3
- [ ] No production logic in a notebook

---

## 21. Interview defense

Be ready for all of these, with numbers.

1. **"Is 182 million rows really big data?"** — No, and I don't claim it is. 17 GB is large, not big. What matters is that the pipeline is correct at both 5M and 182M with the same code, and that I measured where single-node stops being the right answer.
2. **"Why not Spark for everything?"** — Because 17 GB fits DuckDB single-node. I measured the crossover instead of assuming. Here's the plot.
3. **"How do you know your evaluation isn't leaking?"** — Rings run a median 55.76 days and up to 45 accounts, so a plain temporal cut splits rings. I use an entity-disjoint temporal split with a CI assertion, and I have a planted-leak test proving the harness detects leakage when it exists.
4. **"What is `recall@50`? Fifty what?"** — Fifty `(account, day)` pairs, because that's what an investigator reviews. The spec I started from didn't define the unit; I fixed it.
5. **"Why not AUC?"** — At 0.076% prevalence AUC stayed between 0.984 and 0.993 while `recall@budget` moved 0.83 to 0.64. It hides everything that matters.
6. **"Is the drift real?"** — No, it's induced, and I say so every time. IBM's natural typology mix is stationary — I measured Cramér's V = 0.075. So I built a controlled drift generator on the ring labels, which gives exact ground truth and lets me report effect size against drift magnitude.
7. **"Why did you cut streaming?"** — No requirement forced it. The dataset is a static historical file, so streaming it would be a simulation. I scoped it as an optional bounded replay demo and said so honestly.
8. **"Why Iceberg and not just Parquet?"** — Reproducible training sets need snapshot identity. I can name the exact table snapshot behind every model.
9. **"What's the unlabeled 38%?"** — 1,968 of 5,177 HI-Small positives sit in no named pattern block. Typology is a nullable enrichment in my schema, never a key. Typology metrics are reported over the labeled subset with coverage stated.
10. **"What broke at 182M rows?"** — [fill in from Phase 5 — this is the answer they most want, so keep notes.]
11. **"What does this cost, and what costs money while idle?"** — ~$5–15/month; nothing meaningful idles because there are no standing endpoints, clusters, or shards. Here's the teardown proof.
12. **"What would you do differently with a real budget?"** — Real streaming ingest, a managed feature store once multiple teams consume features, and the LI-Large variant for a prevalence-robustness result at 0.012%.

---

## 22. Risks and anti-patterns

| Risk | Mitigation |
|---|---|
| **Analysis paralysis.** Three councils identified ~14,800 lines of planning docs and zero code as the top finding. | Phase 0 is one commit. Do it before any further design. |
| Silent duplicate-`Account` mangling | Explicit schema in the first commit; validator fails on unexpected headers |
| Leaky split inflating every metric | Entity-disjoint split + CI assertion + planted-leak test |
| Overclaiming "big data" or "real-time" | §6 lists the forbidden claims. Reread before writing the README. |
| Cost blowout from repeated HI-Large runs | Manual approval gate; budget alarm; teardown script |
| Cold-start features misread as drift | Bounded rolling windows, not cumulative counts (§9.2) |
| AUC theatre | Lead with `recall@budget`; AUC in a footnote only |
| Notebook rot | No production logic in notebooks; CI runs the CLI |
| Looking like the other 38,171 downloaders | The differentiators are the split correctness, the induced-drift design, the crossover measurement and the cut list — not the model |
| Typology treated as a required key | Nullable enrichment, enforced in the schema |

---

## 23. Open questions

1. **Hard monthly cost ceiling for this project?** Not yet stated. Current design assumes ~$15/month is acceptable.
2. **Is the Phase 2 Kinesis replay demo wanted at all?** It buys four skills batch cannot show, at ~$11/month while running.
3. **Is the Elliptic appendix figure wanted?** One afternoon, already measured, but it is a separate system.
4. **GraphSAGE — in or out?** Decide from Phase 6 headroom, not in advance.
5. **LI-Large prevalence-robustness run?** Same volume, 6× rarer positives (0.012%). Good result, another 17 GB.

---

## 24. References

- **IBM AMLworld:** https://arxiv.org/abs/2306.16424 · https://github.com/IBM/AML-Data · Kaggle `ealtman2019/ibm-transactions-for-anti-money-laundering-aml`
- **Elliptic:** Kaggle `ellipticco/elliptic-data-set` (306 MB) · `ellipticco/elliptic2-data-set` (25.8 GB) · CC BY-NC-ND 4.0
- **TransXion** (rejected): https://arxiv.org/abs/2604.17420 · https://github.com/chaos-max/TransXion
- **AMLGentex** (rejected): https://arxiv.org/abs/2506.13989 · https://github.com/aidotse/AMLGentex
- **SAML-D** (not used): https://github.com/BOztasUK/Anti_Money_Laundering_Transaction_Data_SAML-D
- Apache Iceberg on AWS: https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/
- Step Functions Distributed Map: https://docs.aws.amazon.com/step-functions/latest/dg/use-dist-map-orchestrate-large-scale-parallel-workloads.html
- EMR Serverless: https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/
- GitHub OIDC to AWS: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services

### Council sessions

Two council sessions bear on this project. Both are at the workspace root.

- `council-report-driftgraph-2026-08-11.html` / `.md` — councilled the DriftGraph project itself. Verdict: don't switch to it from TimeLock without first testing whether the drift is measurable. All 5 reviewers named the Contrarian strongest, all 5 named the Expansionist the biggest blind spot.
- `council-report-ibm-dataset-2026-08-11.html` / `.md` — councilled the IBM dataset choice. Verdict: take IBM, effectively 5–0. All 5 reviewers named the Executor strongest. Produced D11 (manufactured drift) and the correction that "two datasets, one pipeline" is impossible.

---

## Appendix A — exact commands

### Kaggle setup

The current Kaggle CLI wants a standalone `KAGGLE_API_TOKEN` (matching the `KGAT_` prefix), **not** `KAGGLE_KEY` + `KAGGLE_USERNAME`.

```bash
python3 -m venv kagenv && ./kagenv/bin/pip install kaggle
export KAGGLE_API_TOKEN="KGAT_..."      # never commit this
```

> **Security:** the token used during the 2026-08-11 session was pasted in plaintext into the chat. **Rotate it** at Kaggle → Settings → Expire API Token. Never write a token into a file, repo or committed artifact — pass it as an ephemeral environment variable only.

### Downloads

```bash
# list files and sizes without downloading
kaggle datasets files ealtman2019/ibm-transactions-for-anti-money-laundering-aml

# the label files are small - get all four first
for f in HI-Small_Patterns.txt HI-Medium_Patterns.txt HI-Large_Patterns.txt LI-Large_Patterns.txt; do
  kaggle datasets download ealtman2019/ibm-transactions-for-anti-money-laundering-aml -f $f -p ibm --unzip -q
done

# development rung (475 MB)
kaggle datasets download ealtman2019/ibm-transactions-for-anti-money-laundering-aml \
  -f HI-Small_Trans.csv -p ibm --unzip

# scale rung (17 GB) - only when Phase 5 is ready
kaggle datasets download ealtman2019/ibm-transactions-for-anti-money-laundering-aml \
  -f HI-Large_Trans.csv -p ibm --unzip

# Elliptic, if the appendix figure is wanted (306 MB)
kaggle datasets download ellipticco/elliptic-data-set -p ell --unzip -q
```

### Verifications worth running once

```bash
wc -l ibm/HI-Small_Trans.csv                      # expect 5078346 (incl. header)
head -1 ibm/HI-Small_Trans.csv                    # confirm the duplicate Account
grep -c 'BEGIN LAUNDERING' ibm/HI-Large_Patterns.txt   # expect 16467
```

### Git LFS note (TransXion only, if ever revisited)

`git-lfs` was not installed during the session. GitHub serves LFS blobs directly:

```bash
curl -sL -o tx.csv "https://media.githubusercontent.com/media/chaos-max/TransXion/main/data/tx.csv"
```

---

## Appendix B — session artifacts on disk

Produced 2026-08-11. Located at `<workspace>/drift-test/`.

| file | contents |
|---|---|
| `drift_test.py` | TransXion L1/L2 — prevalence and covariate stationarity |
| `drift_test2.py` | TransXion L3/L4 — proxy typologies, frozen vs retrained. **Contains the reference `recall_at_budget` implementation.** |
| `drift_test3.py` | Cold-start ablation and the 9-panel figure |
| `plot_fix.py` | Figure regeneration from saved CSVs |
| `ibm_patterns.py` | **`*_Patterns.txt` parser + typology stationarity test. Reuse this directly for Phase 1.** |
| `elliptic_test.py` | Elliptic frozen-model collapse verification |
| `transxion_drift.png` | 9-panel TransXion figure |
| `elliptic_drift.png` | 2-panel Elliptic figure |
| `monthly_prevalence.csv`, `daily_prevalence.csv` | TransXion prevalence series |
| `rings.csv`, `rings_typologies.csv`, `typology_shares.csv` | TransXion ring/proxy-typology analysis |
| `frozen_vs_retrained*.csv` | The three L4 result tables |
| `ibm_rings.csv`, `ibm_typology_shares.csv` | IBM HI-Large ring inventory and weekly shares |
| `elliptic_per_step.csv` | Per-time-step Elliptic performance |

Scratch Python environment: `<scratchpad>/dgenv` — pandas 3.0.5, sklearn 1.9.0, networkx 3.6.1, scipy, matplotlib, pyarrow.

---

*End of document. This file supersedes `03_driftgraph_aml_aws_knowledge_transfer.md` and `04_driftgraph_aml_azure_knowledge_transfer.md`.*
