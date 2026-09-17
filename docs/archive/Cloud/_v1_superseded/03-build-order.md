# Build order
## What you do, what I do, and what we're waiting on

**The honest timing model:** writing code is fast. Waiting is not. Every long bar below
is a machine working, not me typing.

```
me writing code        minutes
you clicking in Azure  ~30 minutes total, twice
machines running       most of the elapsed time
```

Realistic wall clock: **one to two days**, of which perhaps an hour is active work.

---

# STEP 0 — Decide (you, 2 minutes)

- [ ] **Cost ceiling.** A number. Goes straight into the Azure Budget alert.
- [ ] **New project name.** "DriftGraph" no longer fits — the drift experiment is cut.
- [ ] **Confirm Azure.** Reversing decision D6, reason recorded in
      [README.md](../README.md).

**Do NOT activate the £200 credit yet.** The 30-day clock starts the moment you do.

---

# STEP 1 — Close the AWS hole (you, 15 minutes)

This happens regardless of which cloud we use. That account exists and is exposed.

- [ ] Sign in to AWS → IAM → Security credentials
- [ ] **Delete the root access keys**
- [ ] Enable MFA on the root account

Right now `~/.aws/credentials` holds permanent, unrestricted root keys in plaintext. If
they leak, the entire account goes — billing included, with no recovery path.

---

# STEP 2 — Azure account (you, 15 minutes)

- [ ] Create the Azure free account → **£200 credit activates here**, 30-day clock starts
- [ ] `brew install azure-cli terraform`
- [ ] `az login`
- [ ] `az account show` → send me the subscription ID
- [ ] Create a service principal for Terraform:
      `az ad sp create-for-rbac --name driftgraph-tf --role Contributor --scopes /subscriptions/<id>`
- [ ] Send me the output (I'll put it in env vars, never a file)

**Then tell me, and everything below is mine.**

---

# STEP 3 — Infrastructure (me, ~30 min of writing)

```
infra/terraform/
  main.tf         providers, resource group, tags
  storage.tf      ADLS Gen2 + raw/bronze/silver/gold containers
  registry.tf     Azure Container Registry
  compute.tf      Container Apps environment + Azure ML workspace + cluster (min_nodes 0)
  synapse.tf      Serverless SQL endpoint + Spark pool (auto-pause 15 min)
  functions.tf    the scoring function
  datafactory.tf  the orchestration pipeline
  monitor.tf      Log Analytics workspace
  budget.tf       the alert at YOUR ceiling
  variables.tf    everything parameterised
```

- [ ] `terraform apply` — provisions everything
- [ ] `terraform destroy` — **proven to work before we put any data in**

> Destroy gets tested on an empty environment first. Finding out teardown is broken
> *after* filling the account with data is a bad day.

---

# STEP 4 — Package the pipeline (me, ~15 min)

```dockerfile
FROM python:3.12-slim
COPY . /app
RUN pip install -e /app
ENTRYPOINT ["python", "-m", "aml.cli"]
```

- [ ] Build the image, push to ACR
- [ ] Verify: `aml normalize --src abfss://raw/... --dest abfss://bronze/...`

**One line changes in the pipeline**: DuckDB needs its Azure extension loaded so
`abfss://` paths work like local ones. That is the entire code change for the cloud move.

---

# STEP 5 — Get 17 GB into storage (me, ~1–2 hours wall clock)

**HI-Large never touches your laptop.** You have ~50 GB free; the file plus its Parquet
would not fit.

- [ ] Spin up a small VM in the same region
- [ ] Download HI-Large from Kaggle onto it (17 GB)
- [ ] `azcopy` into `raw/`
- [ ] Verify sha256
- [ ] **Delete the VM**

Cost: about £0.20. It's a script in `scripts/`, run once.

---

# STEP 6 — The scale run (me to launch, hours to run)

This is the phase the whole cloud move exists for.

- [ ] `normalize` on 182M rows
- [ ] `parse-patterns` on 16,467 rings
- [ ] `reconcile-labels`
- [ ] `split-sweep` → **pick the cut from data**, expect ~40%
- [ ] `build-splits` + the 4 assertions
- [ ] `build-features` ← **the one that will hurt**
- [ ] `train`
- [ ] `evaluate`

### What we expect to break, and what we do about it

```
normalize        linear, ~45 sec           should just work
reconcile        linear, ~30 sec           should just work
build_features   1–6 HOURS, may run out    <- the real work of this phase
train            110M rows x 32 features
                 = 14 GB just for the matrix
```

**Feature building is the known risk.** From your own machine:

```
             5.08M rows    31.9M rows    throughput
normalize       1.4s          8.0s       flat
build_features  6.9s        515.7s       12x WORSE per row
```

That degradation is DuckDB spilling to disk. At 182M rows (364M account-events) it may
not finish on one machine at all.

**That is not a failure — it is the finding.** Options, in order:

1. More memory (Azure ML lets us pick the VM size)
2. Process day-by-day and concatenate — the features are already causal and windowed
3. Move that one stage to Spark, and **that boundary is the crossover**

- [ ] **Keep a running log of everything that breaks.** *"What broke at 182 million
      rows?"* is the question interviewers most want answered, and it cannot be faked.

---

# STEP 7 — The crossover measurement (me)

Decision D10's deliverable.

- [ ] Run the same feature build on Synapse Spark
- [ ] Run both engines at 5M, 32M and 182M
- [ ] Plot time and cost against rows
- [ ] Mark where the lines cross

```
time
 ^                                    ╱ DuckDB (single node)
 │                                  ╱
 │                       ╱─────╳──────   <- THE CROSSOVER
 │                 ╱────╱      │            (this is the artifact)
 │  ────────────────             Spark
 └──────────────────────────────┴────────> rows
     5M          32M                182M
```

We already know roughly where to look. That's worth saying out loud: *"I predicted the
crossover from the 5M→32M curve before running 182M, and here's how close I was."*

---

# STEP 8 — Serving + parity in the cloud (me)

- [ ] Deploy the model to an Azure Function
- [ ] Run the offline/online parity test **against the deployed function**
- [ ] Confirm it still passes in the cloud

This is what makes the Function's existence honest — it's the online half of a CI test,
not a pretend production endpoint.

---

# STEP 9 — Publish (me)

- [ ] Throughput + cost table for all three sizes
- [ ] The crossover plot
- [ ] README with the cut list
- [ ] One ADR per decision, including **D6 reversed** and **D11 cut**
- [ ] `terraform destroy` + orphan sweep
- [ ] Verify £0 accruing for 48 hours

---

# The dependency chain

```
STEP 0  decide            you    2 min
STEP 1  delete AWS keys   you   15 min
STEP 2  Azure account     you   15 min      <- credit clock starts
   │
   ▼  everything below is mine
STEP 3  terraform         30 min writing  + 10 min applying
STEP 4  docker image      15 min writing  + 10 min pushing
STEP 5  17 GB upload      script          + 1-2 HOURS transfer
STEP 6  the scale run     launch          + 2-8 HOURS running     <- the unknown
STEP 7  crossover         launch          + 1-2 HOURS running
STEP 8  parity in cloud   20 min
STEP 9  writeup           30 min
```

**You are blocking on Steps 0, 1 and 2.** About 30 minutes of clicking. Then I run.

---

# What I need from you, in one list

```
[ ] a cost ceiling (a number)
[ ] a new project name
[ ] AWS root keys deleted
[ ] Azure subscription ID
[ ] service principal credentials (paste them; I'll use env vars only)
```

---

# The rule for this phase

**Nothing gets provisioned until `terraform destroy` has been proven on an empty
environment.** Teardown is tested before build-up, not after. That's how you guarantee
you can get back to £0 — and how "teardown proof" becomes a deliverable rather than a
hope.
