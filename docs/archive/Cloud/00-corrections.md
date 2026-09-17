# Corrections to v1
## What the first cloud design got wrong, and what changed

The first version of these documents was reviewed and found to contain factual errors,
internal contradictions, and claims stated with more confidence than the evidence
supported. The v1 files are archived in `_v1_superseded/` rather than deleted, because
the corrections are more instructive than a clean document would be.

**This file is the honesty record.** Every correction, what was wrong, and what replaced it.

---

## The two root causes

Almost every error traces to one of these.

### 1. I ported the AWS design service-for-service instead of designing for the requirement

```
Step Functions  →  Data Factory
Fargate         →  Container Apps Jobs
SageMaker       →  Azure ML
EMR Serverless  →  Synapse Spark
Athena          →  Synapse Serverless SQL
Lambda          →  Azure Functions
```

That produced **eleven services for a one-time historical batch experiment**. A
translation is not a design. Each extra service brings RBAC, networking, monitoring,
retry semantics and debugging surface.

### 2. I wrote hypotheses as facts

```
"that's DuckDB spilling to disk"      unmeasured
"~45 seconds"                          extrapolated, ignores network and startup
"14 GB for the matrix"                 ignores labels, working copies, framework overhead
"$25–50"                               a guess, and the currency flipped between £ and $
"set correctly in the Terraform"       Terraform did not exist
```

**This is the embarrassing one.** The entire codebase exists to separate claims from
evidence — planted-leak controls, contract tests, `recall_ceiling`. That discipline did
not transfer from the code to the prose.

**Every document from v2 onward tags claims:**

```
✅ FACT          measured, with the measurement stated
🔬 HYPOTHESIS    plausible, not yet tested, with the test named
📋 REQUIREMENT   will be configured, and verified after provisioning
🚧 KNOWN WORK    identified, not yet done
```

---

## Correction 1 — Service-principal credentials ⚠️ SERIOUS

**v1 said:** create a service principal with
`az ad sp create-for-rbac --role Contributor --scopes /subscriptions/<id>`, then *"send
me the output."*

**Wrong on three counts:**

1. It directly contradicts the same document's claim of *"OIDC to Azure, no stored
   secrets, ever."*
2. A client secret must never enter a chat, a file, or a repository.
3. `Contributor` at **subscription** scope is far broader than needed.

**Replaced with:**

```
bootstrap      you run `az login` interactively; Terraform runs locally under
               YOUR identity. Nothing is created for me, nothing is sent to me.
CI             GitHub Actions uses workload identity federation (OIDC).
               No secret exists to leak.
services       Azure ML, Synapse and compute use MANAGED IDENTITIES.
               No secret exists to leak.
scope          every role assignment is scoped to the RESOURCE GROUP,
               never the subscription.
```

Full matrix in [01-architecture.md](01-architecture.md#4-identity-and-rbac).

---

## Correction 2 — "The same Docker image runs everywhere"

**v1 said:** *"one Docker image feeds every compute service — that's what makes 'same
code runs everywhere' literally true."*

**Wrong for Synapse Spark.** Container Apps and Azure ML can run our ACR image. Synapse
Spark uses Microsoft's **managed Spark runtime**; dependencies are supplied through pool
configuration, `requirements.txt`, Conda environment files, JARs or custom Python wheels
— not by running an arbitrary container.

**Replaced with:** DuckDB and Spark implement the **same versioned feature
specification**, and an equivalence test proves they produce identical output. That is a
stronger claim than sharing an image, because it is *tested* rather than assumed.

See [05-parity-and-benchmark.md](05-parity-and-benchmark.md).

---

## Correction 3 — "Only one line changes"

**v1 said:** loading DuckDB's Azure extension is *"the entire code change for the cloud
move."*

**Badly wrong.** DuckDB reading `abfss://` is the easy part. Here is what our own code
actually does:

```python
# manifest.py
Path(dest).mkdir(parents=True, exist_ok=True)
for f in sorted(p.rglob("*")):
    st = f.stat();  h.update(f"...|{st.st_size}|{int(st.st_mtime)}".encode())
(self.out_dir / "manifest.json").write_text(...)

# models/train.py
joblib.dump(clf, ckpt)
```

Manifests, the **cache fingerprint**, model artifacts and **GBDT checkpoints** all use
`pathlib` against local paths. The cache fingerprint uses **`mtime`**, which is not a
stable concept on object storage. Checkpoints written to Azure ML compute live on
ephemeral node disk and vanish when the node deallocates.

**Replaced with:** an explicit audit — [04-storage-compatibility.md](04-storage-compatibility.md)
— listing every local-filesystem assumption and the test that must pass before any
scale run.

**Honest claim:** CLI-first *minimises* cloud-specific change, subject to an end-to-end
storage-compatibility test that does not yet exist.

---

## Correction 4 — "13 stages force Data Factory"

**v1 said:** the pipeline has 13 dependent stages, so it needs Data Factory.

**Wrong.** Dependencies force *an orchestrator*, not that specific one. **Azure ML
pipelines** already sequence jobs with inputs, outputs and dependencies — and the
workspace is needed anyway for compute and tracking.

**Replaced with:** Azure ML pipelines are the orchestrator. Data Factory is **cut**.

Keeping it would have meant a second service that must be granted permission to invoke
the first, with its own retry semantics, its own identity, and its own failure surface —
for zero additional capability.

---

## Correction 5 — Azure Functions had no requirement

**v1 said:** the Function exists as the "online half" of the offline/online parity test.

**Wrong, and this is the sharpest error.** Look at the signature:

```python
def compute(txn, sender_history, receiver_history):
```

**It receives history as an argument. It does not fetch it.** The parity test hands both
implementations the same history and checks they agree — it is a test between **two
Python functions**, running in CI in under a second. A deployed endpoint adds nothing.

**Replaced with:** the Function is **cut**. If it returns, it needs a genuinely different
justification — demonstrating serverless deployment with a measured p99 latency — stated
as such, not disguised as a test requirement.

The deeper design gap is documented in
[05-parity-and-benchmark.md](05-parity-and-benchmark.md#what-a-real-serving-endpoint-would-need).

---

## Correction 6 — "The parity test removes the same risk as a feature store, for free"

**Too broad.** The parity test reduces **training/serving skew**. A feature store also
provides versioned feature reuse, point-in-time historical retrieval, online state,
freshness controls and serving latency guarantees.

**Replaced with:** the parity test removes *the train/serve skew risk*, which is the one
that matters for a batch project. It does not replace a feature store, and we don't need
the rest of what a feature store does.

---

## Correction 7 — "All compute scales to zero"

**Imprecise — three different mechanisms.**

```
Azure ML compute      deallocates nodes when min_nodes = 0        → $0 compute
Synapse Spark pool    auto-pauses after an idle timeout           → $0 compute
storage / ACR /
workspace / logs      keep existing and KEEP COSTING              → not zero
```

**Replaced with:** per-service behaviour stated explicitly in
[06-cost-and-teardown.md](06-cost-and-teardown.md).

---

## Correction 8 — "The Budget is a ceiling"

**v1 implied** the Azure Budget enforced a spending limit.

**It does not.** An Azure Budget is **an alert**. It emails you. It stops nothing. Billing
data also lags by hours, so an alert can arrive after the spend.

**Replaced with:** the Budget is described as an alert. If a real kill switch is wanted,
it is separate automation (an action group triggering a runbook that cancels jobs), with
the lag acknowledged. **The actual control is human: check Cost Analysis before and after
each large run.**

---

## Correction 9 — "Log Analytics, zero code changes"

**Incomplete.** The *application* needs no changes — it already prints structured JSON.
But diagnostic settings, workspace routing, permissions, retention and queries all need
configuring, and logs from different services do not automatically become one coherent
run timeline.

**Replaced with:** correlation IDs are added to the log lines, diagnostic settings are
listed as Terraform work, and building the run timeline is stated as configuration.

---

## Correction 10 — "That's DuckDB spilling to disk"

**Stated as fact. It is a hypothesis.**

```
✅ FACT        feature building throughput fell 739K → 62K rows/sec from 5M to 32M rows
               (12× worse per row, vs ~8× predicted by n log n for sorting alone)
🔬 HYPOTHESIS  the cause is memory pressure and spilling to temporary storage
📋 TEST        DuckDB `EXPLAIN ANALYZE` profiles, peak RSS telemetry, temp-directory
               growth during the run, and disk I/O counters
```

Until that test runs, "spilling" is a plausible explanation, not a finding.

---

## Correction 11 — Extrapolated timings and memory

**"~45 seconds to normalize 182M rows"** was extrapolated from local throughput and
ignores remote ADLS reads over the network, parsing a 17 GB CSV, container startup and
write behaviour.

**"14 GB for the training matrix"** counted 32 float32 values per row and ignored labels,
indices, histogram bin structures, duplicated working memory, train/validation copies and
framework overhead. **Real headroom needs to be several times the raw arithmetic.**

Both are now labelled 🔬 HYPOTHESIS with the measurement that will replace them.

---

## Correction 12 — Cost estimate

**v1 gave "£20–40" in one file and "$25–50" in another** — inconsistent figures *and*
inconsistent currency.

**Replaced with:** a single assumptions table in
[06-cost-and-teardown.md](06-cost-and-teardown.md) stating region, VM SKU, assumed
runtime and assumed rerun count, all in **USD**, labelled as a pre-run hypothesis to be
replaced by Azure Cost Management actuals.

**Also:** the credit amount, currency and expiry must be confirmed **in your actual
subscription**, not assumed from marketing pages.

---

## Correction 13 — Workload placement contradicted itself

**v1's architecture diagram** said Container Apps runs ingest/patterns/reconcile/splits
while Azure ML runs the big stages. **v1's sequence diagram** showed Azure ML running
`normalize` and never showed Container Apps at all.

**Replaced with:** Container Apps is **cut**, and every stage has an explicit row in the
[stage-to-service table](01-architecture.md#2-stage-to-service-mapping) with compute size,
inputs, outputs, retry policy and estimated duration.

---

## Correction 14 — "Delete the resource group and everything dies"

**A useful emergency simplification, but not exact.** Role assignments outside the group,
soft-deleted services, Terraform state, diagnostic settings and resource locks can
survive.

**Replaced with:** stated as the *emergency stop* (correct) with an explicit orphan-sweep
checklist afterwards.

**Also newly designed:** Terraform **remote state backend with locking**, which v1 did
not mention at all. If CI ever runs Terraform, shared state is mandatory.

---

## Correction 15 — "If the free credit is exhausted, everything stops"

**Not reliable.** Subscription behaviour on credit exhaustion varies with account type
and whether pay-as-you-go is enabled.

**Replaced with:** confirm the behaviour in your subscription before relying on it, and
treat the budget alert plus manual checks as the real control.

---

## Correction 16 — "Banks are Microsoft shops"

**An overgeneralisation used as a technical justification.** It's a market-positioning
observation, not an architecture argument.

**Replaced with:** the technical justifications are available credit, service fit for a
batch experiment, scale-to-zero compute, and the fact that the switch requires no
pipeline code changes.

---

## Correction 17 — Data model grain was ambiguous

**v1 called silver "32 features per transaction" in one place and referenced 364 million
"account-events" in another**, while evaluation uses `(account, day)`.

**Replaced with:** an explicit grain table in
[01-architecture.md](01-architecture.md#3-data-model-and-grain).

---

## Correction 18 — Dual source of truth

**v1 had both ADLS `gold/` and Azure ML tracking holding models and metrics** with no
statement of which is canonical.

**Replaced with:** ADLS `gold/` + `manifest.json` is **canonical**. Azure ML tracking is
a convenience view. Stated explicitly, with the linking identifier defined.

---

## Correction 19 — "If a stage fails, it retries"

**Not automatic.** Retry is configuration, and more importantly **not everything should
be retried**:

```
transient   node preemption, storage throttling, network       → retry
correctness assertion failures (leakage, contract, schema)     → STOP IMMEDIATELY
```

Retrying a leakage assertion failure would be actively harmful. Now specified per stage.

---

## Correction 20 — Kaggle transfer was underspecified

**v1 said** *"spin up a small VM and download it."* Not a secure transfer design.

**Replaced with:** token supplied via environment variable only, never written to disk;
sha256 verified against the recorded fingerprint; VM, its disk and its NIC deleted after;
and the CDLA-Sharing-1.0 licence checked against the intended storage and publication.

---

## Correction 21 — Document contradictions

```
README said credit activation is Step 1        build-order said Step 2
one diagram hardcoded $40/$80/$150             another said "your chosen ceiling"
build-order said "Terraform does not exist"    cost doc said "set correctly in Terraform"
```

All resolved. Thresholds are defined once, in
[06-cost-and-teardown.md](06-cost-and-teardown.md), and referenced elsewhere.

---

## What v1 got right, and is preserved unchanged

The review was clear that the underlying project is strong. None of the following
changed:

```
✅ raw-data contract checks and the explicit schema
✅ ring-aware, entity-disjoint temporal split
✅ four blocking assertions
✅ causal feature definitions and the 1-minute window boundary
✅ alert-budget evaluation with ceiling and efficiency
✅ planted-leak tests with a positive control
✅ offline/online feature parity
✅ reproducibility controls
✅ teardown-first Terraform discipline
✅ measuring the DuckDB↔Spark crossover rather than assuming
```

**The corrections are all about the cloud layer and the documentation's confidence — not
about the pipeline, which stands.**

---

## Scorecard

```
24 points raised
22 accepted substantially
 2 accepted with nuance   (cost estimate is still useful for sizing;
                           Serverless SQL is cheap enough to keep optional)
 2 places I went further  (cut the Function entirely;
                           questioned whether the Spark comparison was worth it
                           — then reinstated it, properly gated)
```
