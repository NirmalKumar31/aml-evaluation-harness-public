# Working agreement and resume point

**Purpose:** if the chat context is lost, this file is enough to pick up exactly where we
stopped. Written at the point where all planning is complete and no code has been written
for the cloud phase.

**Status: Stage 1 COMPLETE, Gate 1 passed. Paused on a decision — see §0.**

---

# 0. Where we actually are (updated 2026-08-20)

```
✅ STAGE 1 DONE   all 6 checklist items · branch `stage-1-storage-layer`
                  2 commits · 172 tests pass · $0 spent · no Azure contact
🚦 GATE 1 PASSED  the original 96 tests pass unchanged
⛔ BLOCKED        one decision needed before Stage 2 — txn_id, below
```

**What was built:** `src/aml/io.py` (local/blob abstraction) + 27 call sites
rewired; cache fingerprint `mtime` → ETag; checkpoints persisted to the stage
output path instead of ephemeral node disk; `src/aml/exits.py` (exit code 1 =
transient/retry, 2 = correctness/never retry); `docs/FEATURE_SPEC_v1.md`.

**Gate 1 evidence** — not just "tests pass":
- fingerprint parity vs the frozen pre-cloud implementation: 18 real targets,
  ~800 files, incl. a 3 GB CSV and a 190-file Parquet tree → **0 mismatches**,
  so cache entries written by the old code are still recognised
- end-to-end HI-Small run: 5,078,345 rows, 370 rings, all four split assertions
  passed, AP 0.302, 6 checkpoints, artifact 1.12 MB
- checkpoint resume works; a failed stage still writes `status=failed`
- real process exit codes verified via `python -m aml.cli` and the `aml` entry point

## ⛔ The decision blocking Stage 2

**`txn_id` is not deterministic.** It is `row_number() OVER (ORDER BY
event_time, sender_id, receiver_id)`, and that key is not unique — 658,850 rows
(2.1%) of HI-Medium share one, in groups of up to 4. DuckDB parallelises the
sort, so three runs gave three different digests, two of them at identical
thread settings.

It is not theoretical: `features/build.py` and `leakproof/plant.py` each
recompute `txn_id` independently, and `prove.py` joins them on it with
`validate="one_to_one"`, which checks cardinality only — never that a `txn_id`
means the same transaction on both sides. Leak columns are therefore attached to
the wrong transactions for tie-group rows, silently. **The affected artifact is
the leak-detection proof.** It also makes Gate 2 unpassable, since row identity
is unstable within a single engine.

**Recommended fix:** assign `txn_id` once in `normalize`, carry it through
bronze, so identity is never re-derived. Ordering on all 14 bronze columns
leaves only 20 fully identical rows out of 31.9M, and those are interchangeable
by construction.

**Cost of the fix:** features and leak tables must be rebuilt. Feature *values*
do not depend on `txn_id` and split membership is by `event_time`/`ring_id`, so
headline metrics are expected to be unchanged — to be verified, not assumed. The
leak-proof numbers may genuinely move, because that join is currently wrong.

Full evidence: `aml-platform/docs/FEATURE_SPEC_v1.md` §8.

## Also still open

**DuckDB's Azure extension is not wired up.** `io.py` covers the Python-side
file operations, but DuckDB still receives raw path strings inside SQL
(`read_parquet('{src}/**/*.parquet')`). For `abfss://` to work there, the
extension must be loaded and its credential provider pointed at
`DefaultAzureCredential`. The storage audit listed this as known work but left
it off the Stage 1 checklist — it belongs there, because nothing runs in the
cloud without it.

---

# 1. The working agreement — Option 1

| | you | me |
|---|---|---|
| decisions | ✅ all of them | recommend only |
| credentials | ✅ **only you, ever** | never touch, never receive |
| running commands | ✅ **you type every one** | write them for you |
| watching it run | ✅ the Azure portal | read logs |
| writing code | review before running | ✅ |
| catching my errors | ✅ (you have, repeatedly) | |

## The rules

```
1. Every command that touches Azure is typed by YOU, in YOUR terminal.
2. No credential is ever pasted into chat, a file, or a repo.
   → you: az login interactive
   → CI: GitHub workload identity federation (OIDC), no secret exists
   → services: managed identities, no secret exists
3. Terraform CREATES infrastructure. The portal is where you WATCH,
   VERIFY and STOP things.
4. I write code; you review it before it runs.
5. Nothing expensive runs until the gate before it passes.
```

## Why Terraform instead of clicking

```
clicking     works, but: can't reproduce · can't prove teardown ·
             nothing to show anyone
declaring    reproducible · `terraform destroy` = provable $0 ·
             the file itself is a portfolio artifact
```

You will still be in the portal constantly — verifying `min_nodes = 0` is really set,
watching pipeline runs, checking Cost Analysis before and after each big run, reading
failure logs, and using the emergency stop.

---

# 2. Where the project stands

```
✅ Phase 0   ingest, schema contract, contract tests
✅ Phase 1   answer key, reconciliation, ring-aware split + 4 assertions
✅ Phase 2   32 causal features, logistic + GBDT, full metric suite
✅ Phase 3   planted-leak proof, offline/online parity, reproducibility
🟡 Phase 6   drift GENERATOR complete (26 tests); EXPERIMENT cut on evidence
❌ Phase 4-5 cloud + 182M rows          ← everything below is about this
❌ Phase 8   README, cut list, ADRs

2,895 lines source · 1,553 lines tests · 96 tests · ~8 seconds · 7 commits · $0 spent
```

**Repo:** `Final Projects/AML/aml-platform/` — local git, not yet pushed to GitHub.

---

# 3. Decisions locked

| decision | value | notes |
|---|---|---|
| Cloud | **Azure** | reverses D6; the objection was aimed at managed endpoints we never used |
| Spark | **Synapse Spark**, not Databricks | cheaper; Spark is the skill, not the vendor wrapper |
| Engine strategy | **Option C** — DuckDB pipeline + Spark for ONE stage | less work than porting everything, and a better story |
| Scale experiments | **both** — VM-size scaling *and* the DuckDB↔Spark crossover | |
| Cost ceiling | **$200 total** (the credit), alerts at **$40 / $80 / $150** | budget is an ALERT, not a brake |
| Orchestration | **Azure ML pipelines** | Data Factory cut |
| Serving | **Azure Functions cut** | its only justification was a test that doesn't need it |
| Working mode | **Option 1** — I write, you run | |
| Drift experiment | **CUT** | generator kept; synthetic positives were 3× too easy |
| Project name | **DEFERRED** | repo stays `aml-platform`; not blocking |

## Still open

```
[ ] Azure region          needed at Stage 4
[ ] project name          whenever
[ ] AWS root key deletion whenever — unrelated to Azure, but that account is
                          sitting with permanent unrestricted keys in
                          ~/.aws/credentials
```

---

# 4. The plan — ten stages, four gates

```
STAGE 1  storage layer          ME · local · free      ~1 day
STAGE 2  Spark implementation   ME · local · free
STAGE 3  container + CI         ME · free
   ── GATES 1 & 2 ──
STAGE 4  Azure account          YOU · 15 min · ⚠️ starts the 30-day clock
STAGE 5  Terraform              me writes · YOU run
   ── GATE 3 ──
STAGE 6  cloud smoke test       HI-Small · minutes · cents
   ── GATE 4 ──
STAGE 7  17 GB upload           ~1-2 hrs · ~$1
STAGE 8  the 182M run           🔬 2-8 hrs · the unknown
STAGE 9  both experiments
STAGE 10 publish + teardown     back to $0
```

## Stage 1 — ✅ COMPLETE (2026-08-20)

```
[x] src/aml/io.py — local/blob abstraction        (~380 lines incl. docs)
[x] update the call sites                         27, not 8 — audit undercounted
[x] cache fingerprint: mtime → ETag
[x] checkpoints persist to storage, not ephemeral node disk
[x] exit codes: 1 = transient (retry), 2 = correctness (NEVER retry)
[x] docs/FEATURE_SPEC_v1.md — engine-neutral feature definition
[ ] DuckDB Azure extension + credential chain     ← added; was missing from this list
```

**🚦 GATE 1 PASSED.** The original 96 tests pass unchanged; 172 total.

Two bugs found that the storage audit had missed:
- `Path("abfss://c/x") / "y"` collapses the double slash to `abfss:/c/x/y` — a
  different, nonexistent location, no error raised. Hence `io.join()`.
- `txn_id` non-determinism (§0) — the blocker.

## Stage 2

```
[ ] features/build_spark.py — PySpark, from the spec (~150 lines)
[ ] tests/engine_parity/test_duckdb_vs_spark.py (~100 lines)
[ ] prove both engines agree on HI-Small
```

**🚦 GATE 2: exact for integers, 1e-9 for floats, nulls exact.**
⚠️ **No timing number is quoted until this passes.**

## The other two gates

```
🚦 GATE 3   terraform destroy PROVEN on an EMPTY environment, before any data
🚦 GATE 4   full pipeline on HI-Small in the cloud matches local results
            ⚠️ NO 182M-ROW RUN UNTIL THIS PASSES
```

---

# 5. The architecture, in one block

```
CORE (6)      ADLS Gen2 · Container Registry
              Azure ML (pipeline + compute at min_nodes=0 + tracking)
              Terraform + OIDC + managed identities
              Log Analytics · Budget alert

OPTED IN      Synapse Spark — ONE stage only, gated behind the equivalence test

CUT (3)       Data Factory · Container Apps Jobs · Azure Functions
```

**Canonical source of truth:** ADLS `gold/` + `manifest.json`. Azure ML tracking is a
convenience view only.

---

# 6. Numbers worth not losing

```
DATA
  HI-Small     5,078,345 rows · 465 MB · 18 days · 370 rings
  HI-Medium   31,898,238 rows · 2.8 GB · 28 days · 2,756 rings   ← current working set
  HI-Large   ~182,060,762 rows · 17 GB · 119 days · 16,467 rings ← the goal

RESULTS (HI-Medium, GBDT)
  average precision      0.3005   (15× the logistic floor)
  recall_efficiency@50   83.2%    (% of what the budget can physically reach)
  precision@50           83%
  ring recall@200        69%
  95% CI            [.0333,.0460] — does not overlap the baseline's

THE SPLIT
  58% of test rings deleted to stay leak-free (87% projected at HI-Large)
  28% of rings straddle a naive cut
  4.7% hard ceiling on recall@50

THE LEAK PROOF
  target leak: AP ×2.54, 70% of remaining error closed → harness DOES detect leakage

PERFORMANCE  ✅ FACT
  normalize        3.6M → 4.0M rows/sec   from 5M to 32M    FLAT
  build_features   739K →  62K rows/sec   from 5M to 32M    12× WORSE
  🔬 HYPOTHESIS: memory pressure / spilling. NOT YET MEASURED.
  🔬 PREDICTION: DuckDB on a 512 GB VM probably handles 182M fine —
     the local slowdown was a 16 GB limit, not an algorithmic wall.

COST  🔬 HYPOTHESIS
  $32–93 of the $200. To be replaced by Azure Cost Management actuals.
```

---

# 7. Claim convention used in all cloud docs

```
✅ FACT          measured, with the measurement stated
🔬 HYPOTHESIS    plausible, not tested, with the test named
📋 REQUIREMENT   will be configured, and VERIFIED after provisioning
🚧 KNOWN WORK    identified, not done
```

This exists because v1 of the cloud docs stated guesses as facts — in a project whose
entire purpose is separating claims from evidence. See
[00-corrections.md](00-corrections.md).

---

# 8. Where everything lives

```
Final Projects/AML/
├── AML_PROJECT_KNOWLEDGE.md      the original plan (3 figures corrected by us)
├── BUILD_PLAN.md                 the original execution plan
├── aml-platform/                 THE CODE — 2,895 lines, 96 tests
├── Learning/                     12,529 lines of teaching docs
│   ├── Code/       00-map · 01-full-walkthrough · 02-drift-and-leakproof
│   │               03-syntax-dictionary · 04-changes-after-phase-2
│   └── Concepts/   01-domain · 02-how-to-think · 03-phases-0-2 · 04-phase-3
│                   05-drift · 06-failure-log (all 18) · 07-running-and-debugging
│                   08-the-full-story · 09-decision-log · 10-all-the-numbers
└── Cloud/                        the cloud plan, v2 after review
    ├── 00-corrections.md         what v1 got wrong — read first
    ├── 01-architecture.md        lean design · stage-to-service · RBAC · failure model
    ├── 02-azure-explained.md     Azure from zero, with diagrams
    ├── 03-build-order.md         the ten stages and four gates
    ├── 04-storage-compatibility.md  🚧 the real Stage 1 work
    ├── 05-parity-and-benchmark.md   parity contract + Spark protocol
    ├── 06-cost-and-teardown.md   assumptions · budget-is-an-alert · teardown
    ├── 07-working-agreement.md   ← this file
    └── _v1_superseded/           the pre-review versions, kept deliberately
```

---

# 9. To resume

Read §0 above. Stage 1 is done and Gate 1 passed; the next move is a **decision,
not code**:

1. **`txn_id`** — approve the fix (assign once in `normalize`) and accept that
   features and leak tables get rebuilt. Nothing else in Stage 2 can proceed
   until this is settled, because Gate 2 has no stable join key without it.
2. **Azure region** — still unset, needed at Stage 4.
3. **Cost ceiling** — confirm $200 with alerts at $40 / $80 / $150.

Then Stage 2 (the PySpark implementation + engine parity test) can start. Still
local, still free, still no Azure resource.
