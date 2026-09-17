> # ⚠️ SUPERSEDED — historical record only
>
> This file describes a plan that was **not built**. It is kept because the
> decisions and their reasons are part of the project's history, not because
> any of it is current.
>
> **Current state: [`../HANDOFF.md`](../../../HANDOFF.md)** (or `HANDOFF.md` at the
> repo root). Architecture actually built: one Azure VM + Bicep, single-node
> DuckDB. Not AWS, not Terraform, not Azure ML, not Synapse.
>
> Anything in this file about status, test counts, cost, services or
> infrastructure is out of date by construction.

# Cloud — scaling to 182 million rows on Azure

**Version 2.** The first version was reviewed and found to contain factual errors,
internal contradictions and claims stated more confidently than the evidence supported.
It is archived in `_v1_superseded/` rather than deleted, because the corrections are
more instructive than a clean document.

**Start here:** [00-corrections.md](00-corrections.md) — what was wrong and what changed.

---

## The files

```
00-corrections.md            what v1 got wrong — the honesty record
02-azure-explained.md        ⭐ START HERE if you don't know Azure. Diagrams, from zero
01-architecture.md           the lean design · stage-to-service table · RBAC · failure model
03-build-order.md            what you do, what I do, and the three gates
04-storage-compatibility.md  🚧 the real work — every local-filesystem assumption
05-parity-and-benchmark.md   the parity contract and the Spark benchmark protocol
06-cost-and-teardown.md      assumptions table · the budget is an ALERT · teardown
```

---

## The claim convention

Every statement in these documents is tagged. This exists because v1's biggest failure
was writing guesses as facts — in a project whose entire purpose is separating claims
from evidence.

```
✅ FACT          measured, with the measurement stated
🔬 HYPOTHESIS    plausible, not yet tested, with the test named
📋 REQUIREMENT   will be configured, and VERIFIED after provisioning
🚧 KNOWN WORK    identified, not yet done
```

---

## The design in one block

```
CORE (6)      ADLS Gen2 · Container Registry
              Azure ML (pipeline + compute at min_nodes=0 + tracking)
              Terraform + OIDC + managed identities
              Log Analytics · Budget alert

OPTIONAL      Synapse Spark      — we are opting in, gated behind an equivalence test
              Serverless SQL     — cheap, handy, not required

CUT (3)       Data Factory       — Azure ML pipelines already orchestrate
              Container Apps     — Azure ML jobs already run containers
              Azure Functions    — its only justification was a test that doesn't need it
```

---

## Why Azure

Decision D6 originally chose AWS because *"Azure ML managed online endpoints bill hourly
while deployed."* **We don't use managed online endpoints** — decision D15 chose
serverless functions precisely to avoid them. The objection was aimed at a design the
project had already rejected.

The technical reasons for Azure:

1. **$200 of credit** covers the estimated $32–93 spend 🔬
2. **Service fit** — Azure ML compute at `min_nodes = 0` is the right shape for a batch
   experiment that runs a handful of times
3. **No pipeline code changes** — every stage is already a shell command taking paths

⚠️ **Not a technical reason:** *"banks are Microsoft shops."* v1 used that as
justification. It's market positioning, and it's an overgeneralisation.

---

## Why the switch is cheap — the honest version

```
CHANGES        infra/terraform/**          does not exist yet
               one Dockerfile
               CI authentication
               🚧 THE STORAGE LAYER        ~120 lines + 8 call sites
                                           v1 said "one line." Wrong.

UNCHANGED      all 2,895 lines of pipeline LOGIC
               all 96 tests
               every command: aml normalize --src ... --dest ...
```

The pipeline runs as shell commands reading from paths. It does not know whose cloud it
is. **The cloud choice is a Terraform decision, not a pipeline decision** — the payoff for
building CLI-first in Phase 0.

**But** manifests, the cache fingerprint, model artifacts and checkpoints all use
`pathlib` against local paths, and the cache uses `mtime`, which is unreliable on object
storage. That's a day of careful work, detailed in
[04-storage-compatibility.md](04-storage-compatibility.md).

---

## The three gates

Nothing expensive runs until each passes.

```
GATE 1   the storage abstraction ships and all 96 tests still pass LOCALLY
GATE 2   terraform destroy is proven on an EMPTY setup, before any data exists
GATE 3   the full pipeline runs on HI-Small in the cloud and matches local results

         ⚠️ NO 182M-ROW RUN UNTIL GATE 3 PASSES
```

Each gate fails *backwards* into real work rather than forwards into a six-hour job.

---

## ⚠️ The credential rule

v1 instructed you to create a service principal and paste its output into chat. **That was
wrong and is withdrawn.**

```
❌ NEVER    paste a client secret, service-principal JSON or connection string
            into a chat, a file, or a repository

✅ INSTEAD  you       az login, interactive — Terraform runs under YOUR identity
            CI        GitHub workload identity federation — no secret exists
            services  managed identities — no secret exists
            scope     every role assignment scoped to the RESOURCE GROUP
```

The only thing I need from you is a **subscription ID**, which is not a secret.

---

## The clock

⚠️ Azure's credit expires **30 days after activation**, and the amount, currency and
expiry should be **confirmed in your actual subscription** rather than assumed.

Don't activate it until Step 2 of [03-build-order.md](03-build-order.md) is done —
otherwise the clock burns while local work happens.

---

## Current status

```
✅ DECIDED    Azure · Synapse Spark (not Databricks) · both scale experiments
              cost ceiling $200, alerts at $40 / $80 / $150
⏸ DEFERRED   project name
❌ NOT DONE   any Azure resource. Nothing has been created. $0 spent.
```

**Next action is mine:** the storage-compatibility layer, locally, before you touch Azure.
