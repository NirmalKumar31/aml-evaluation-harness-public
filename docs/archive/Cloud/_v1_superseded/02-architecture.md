# The Azure architecture
## Every service, what it does, and why it beat the alternatives

**The rule, kept from the original plan:** every service below is followed by *the
requirement that forces it to exist*. If that requirement can't be stated, the service
gets cut.

---

## The picture

```
                   GitHub Actions
                   OIDC → Azure. No stored secrets, ever.
                          │
                          │ terraform apply
                          ▼
        ┌─────────────────────────────────────────────┐
        │           AZURE DATA FACTORY                │
        │           (the conductor)                   │
        │  runs each pipeline stage in order,         │
        │  retries on failure, one visual run history │
        └──┬─────────┬──────────┬──────────┬─────────┘
           │         │          │          │
           ▼         ▼          ▼          ▼
      ┌────────┐ ┌───────┐ ┌─────────┐ ┌──────────┐
      │Container│ │Azure  │ │ Synapse │ │  Azure   │
      │Apps Job │ │  ML   │ │ Spark   │ │Functions │
      │         │ │ jobs  │ │  pool   │ │          │
      │ small   │ │       │ │         │ │ scoring  │
      │ stages  │ │ big   │ │ the     │ │ endpoint │
      │ DuckDB  │ │ runs +│ │ cluster │ │ scales   │
      │ scales  │ │ train │ │ compare │ │ to zero  │
      │ to zero │ │ min 0 │ │         │ │          │
      └────┬────┘ └───┬───┘ └────┬────┘ └────┬─────┘
           └──────────┴──────────┴───────────┘
                          │
                          ▼
        ┌─────────────────────────────────────────────┐
        │   ADLS Gen2  (one storage account)          │
        │                                             │
        │   raw/      the original Kaggle CSVs        │
        │   bronze/   cleaned, day-partitioned        │
        │   silver/   32 features per transaction     │
        │   gold/     splits, models, metrics         │
        └─────────────────────────────────────────────┘
                          │
                          ▼
              Synapse Serverless SQL
              ad-hoc queries over the Parquet.
              No cluster. ~£4 per TB scanned.

        ┌─────────────────────────────────────────────┐
        │ Log Analytics — our JSON logs become        │
        │ queryable metrics with zero code changes    │
        │ Azure Budget — alert at your ceiling        │
        └─────────────────────────────────────────────┘
```

---

## Every service, and the requirement forcing it

### Storage — ADLS Gen2

**What:** Azure's object storage with a real folder hierarchy.
**Requirement:** somewhere cheap to keep 17 GB of raw CSV and ~10 GB of Parquet that
every compute service can read without copying.
**Cost:** ~£0.50/month for 27 GB.

**Why not a database?** Our pipeline reads whole day-partitions with DuckDB. Loading
182M rows into a SQL database first would cost more and buy nothing.

### Query — Synapse Serverless SQL

**What:** run SQL directly over the Parquet files. No server to provision.
**Requirement:** ad-hoc exploration and result aggregation without standing
infrastructure.
**Cost:** ~£4 per TB scanned. Our partitioning means most queries scan a fraction.

**Why not Synapse Dedicated pools?** They're a running cluster you pay for hourly. This
is the Athena equivalent and the right shape.

### Small/medium compute — Azure Container Apps Jobs

**What:** run our Docker image as a job, on demand, then shut down.
**Requirement:** every pipeline stage is already a shell command in a container. This
runs exactly that, and **scales to zero** between runs.
**Cost:** pennies per run.

This is the Fargate equivalent. Used for ingest, patterns, reconcile, splits — the stages
that finish in seconds or minutes.

### Big compute + training — Azure ML jobs

**What:** submit a container to a compute cluster whose minimum size is **0 nodes**.
**Requirement:** the 182M-row feature build needs far more memory than a Container Apps
job allows, and we need automatic artifact capture and run logging.
**Cost:** ~£0.60–1.20/hour while running, **£0 when idle** because min_nodes = 0.

This is the SageMaker Training Job equivalent, and it also runs the big DuckDB stages.

> **Why min_nodes = 0 matters.** A cluster with min_nodes = 1 bills 24/7. This is the
> exact trap that decision D6 worried about, and setting it to 0 avoids it.

### Distributed compute — Synapse Spark pool

**What:** managed Spark, auto-pauses after idle.
**Requirement:** decision D10 — the deliverable is the **crossover measurement**, so both
engines must exist. We run the same workload single-node and distributed and publish
where each wins.
**Cost:** ~£1–3 per run, £0 when paused.

**The honest trade-off:** AWS's EMR Serverless bills per vCPU-second with no floor.
Synapse Spark pools have a minimum node count and a few minutes of spin-up. **Less
granular — and that makes the crossover story better, not worse.** A cluster with a
higher floor loses to a single machine for longer, and saying exactly where is the point.

### Orchestration — Azure Data Factory

**What:** runs the stages in order, with retries, and a visual run history.
**Requirement:** the pipeline is 13 stages with dependencies. Something has to sequence
them and show what happened.
**Cost:** ~£0.80 per 1,000 activity runs. Effectively free at our volume.

**Why not Airflow?** Managed Airflow on any cloud starts around £250/month. Disqualifying,
same as it was on AWS.

### Inference — Azure Functions (Consumption plan)

**What:** the model in a function that wakes on request and sleeps otherwise.
**Requirement:** honestly — the **offline/online parity test**. In a batch pipeline
nothing calls this endpoint in anger. Its real job is to be the "online" half of the CI
test that proves the serving feature path matches the batch one.
**Cost:** ~£0 — the free grant covers a demo.

Say that plainly in the README. A sharp interviewer will ask "who calls this?" and the
honest answer is stronger than pretending there's live traffic.

### Registry — Azure Container Registry

**What:** stores our Docker image so every compute service can pull it.
**Requirement:** Container Apps, Azure ML and Synapse all run *the same image*. That's
what guarantees "same code everywhere" is literally true.
**Cost:** ~£4/month Basic tier. Delete at teardown.

### IaC — Terraform

**What:** the infrastructure described in text files. One command up, one command down.
**Requirement:** you must be able to prove you got back to £0. A console click-through
can't be proven or repeated.
**Cost:** free.

### CI — GitHub Actions with OIDC federation

**What:** GitHub proves its identity to Azure directly. No secrets stored anywhere.
**Requirement:** no long-lived credentials in the repo, ever.
**Cost:** free for public repos.

### Monitoring — Log Analytics

**What:** collects our structured JSON logs and makes them queryable.
**Requirement:** we already print `{"event": "...", "rows": ..., "wall_clock_sec": ...}`
from every stage. Log Analytics parses that into metrics with **zero code changes**.
**Cost:** free tier covers this comfortably; set 7-day retention or it creeps.

### Cost guard — Azure Budget

**What:** an alert when spend crosses your ceiling.
**Requirement:** you have a fixed £200 and no desire to discover a runaway job on day 29.
**Cost:** free.

---

## The cut list — what we deliberately do NOT use

Write this into the README. Being able to say no, in writing, is high-signal.

| rejected | why |
|---|---|
| **Managed Airflow** | ~£250/month floor. Data Factory does the job for pennies. |
| **Synapse Dedicated SQL pool** | A cluster billing hourly. Serverless answers every question we have. |
| **Azure ML managed online endpoints** | Bill continuously while deployed. Functions scale to zero and the model is small. This is the original D6 objection, and we avoid it. |
| **Azure Databricks** | Excellent, and more than we need. Synapse Spark is enough to measure a crossover. |
| **Cosmos DB** | No online feature store in v1. The parity *test* is the artifact. |
| **AKS / Kubernetes** | Nothing here needs an orchestrator. Container Apps + Functions cover every workload. |
| **Event Hubs / streaming** | The dataset is a static historical file. Streaming it would be a simulation, not a stream. |
| **Multi-region** | No availability requirement exists for a portfolio artifact. |
| **GPU of any kind** | Gradient-boosted trees are CPU work. |
| **A graph database** | Ring structure is connected components over a table. SQL computes it fine. |

**The pattern:** anything that bills while sitting idle got cut. That's a real
engineering-judgment story, not a cost story.

---

## AWS ↔ Azure quick reference

Useful in interviews — it shows you understand the *shapes*, not just one vendor's names.

| shape | AWS | Azure |
|---|---|---|
| object storage | S3 | ADLS Gen2 |
| SQL over files | Athena | Synapse Serverless SQL |
| container job, scale to zero | Fargate | Container Apps Jobs |
| training job, scale to zero | SageMaker Training | Azure ML jobs (min_nodes 0) |
| managed Spark | EMR Serverless | Synapse Spark pool |
| orchestration | Step Functions | Data Factory |
| serverless function | Lambda | Azure Functions |
| container registry | ECR | ACR |
| logs + metrics | CloudWatch | Log Analytics |
| identity for CI | IAM + OIDC | Entra ID + OIDC |

---

## Estimated total

```
storage 27 GB                    ~£0.50/month
Synapse Serverless queries       pennies
Container Apps Jobs              pennies
Azure ML compute (the big runs)  ~£1/hour, only while running
Synapse Spark (crossover)        ~£1–3 per run
Container Registry               ~£4/month
Functions, Data Factory, logs    ~£0

realistic total for the whole project:  £20–40 of your £200
```

Details and the teardown checklist: [04-cost-and-teardown.md](04-cost-and-teardown.md).
