# Changelog

Dates are when the work landed on `main`. Three releases exist, all from the
public snapshot at <https://github.com/NirmalKumar31/aml-evaluation-harness-public/releases>:
**v0.1.0** and **v0.1.1** (2026-09-17) and **v0.1.2** (2026-09-18). Remaining
release items are in
[`aml-platform/docs/RELEASE_CHECKLIST.md`](aml-platform/docs/RELEASE_CHECKLIST.md).

⚠️ This file carried exactly one heading -- `## Unreleased` -- while three
releases were published, and named only v0.1.0 in its own preamble. A changelog
that does not name the releases is the same defect as a metric that does not
name its unit, and an audit found all four of `pyproject.toml`, `CITATION.cff`,
`HANDOFF.md` and this file disagreeing about which version is current.

Corrections and retractions are listed **first** in each entry, because they are
the part a reader most needs and the part a changelog most often buries.

## v0.1.3 — 2026-09-18

**The volume-segment headline is withdrawn.** `replay/medium_gbdt_s0`
reproduces `gold/eval3_Medium/gbdt` bit-identically (761/864 = 0.880787)  <!-- derived: 0.880787 = the SUPERSEDED value this entry names -->
against the canonical 0.793981, and `CANONICAL.json` marks that lineage
superseded — those fits predate the restored row sort in `load_train_xy`.
Withdrawn with it: the pooled 0.88079 and its 1.79x-1.94x lift, the  <!-- derived: 1.94 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current; 1.79 = the same; 0.88079 = the same -->
volume-segment 0.75714 and 310.3x, the 265-of-350 counts, and the  <!-- derived: 310.3 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current; 0.75714 = the same -->
per-typology block including FAN-IN (the method stands; the result must not be
quoted). The logistic survives untouched — a deterministic fit reads 0.570602
in both lineages, which is why five audit sittings missed this.

The publication gate could not see it: it resolves lineage only for paths
under `gold/`, so a superseded value laundered through `replay/` or `derived/`
returned "derived" and passed. A test now catches exactly that condition.

Also: the lead finding's "volume falls 637,998x" was a whole-dataset ratio  <!-- derived: 637998 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current -->
attributed to the test window (correct: 431,695x), and "prevalence rises to  <!-- derived: 3021866/7 -->
1.0" mixed transaction with account-day units (correct: 0.627119). The
"of the attainable" column was vacuous — with the budget binding, precision's
ceiling is 1, so the normalised lift is the precision restated. `replay-demo`
was documented at "about eight seconds" and takes 69 s from a cold clone. Four
files disagreed about the version, and nothing checked; a test now binds them
to the newest tag.

## v0.1.2 — 2026-09-18

The segmented encoding result, recomputed on the account-day alert unit: the
version v0.1.1 shipped ranked transactions, so its head-segment null read
0.00077 against the 0.00243 `budget_null.py` computes for the same rung and  <!-- derived: 0.00077 = a WITHDRAWN transaction-unit null this entry narrates. Deliberately in no artifact -->
segment, and every lift was inflated about 3.16x. <!-- derived: 3.16 = 0.00243/0.00077, the inflation factor of the withdrawn unit --> `LIMITATIONS.md` section 8
regained its missing `**Not claimable:**` header. HI-Large gained non-binding-day
accounting. The per-typology null moved to 50000 draws. `make replay-demo`
demonstrates no-data replay in any clone. Derived artifacts record
content-addressed provenance, taking the public clone from 0 of 13 artifacts
verifiable to 12 of 13.

## v0.1.1 — 2026-09-17

The segmented categorical experiment, which had never executed (`m is
slice(None)` compared two distinct slice objects); the typology report's use of
a single-seed diagnostic to speak about the withdrawn ensemble; two wrong Holm
cells; and this snapshot's claim to offer replay verification it withholds.

## v0.1.0 — 2026-09-17

First public snapshot.

## Unreleased

### Retracted or reversed

- **"Substantially a property of the benchmark / of IBM's simulator" is
  withdrawn**, and so is "the increment from model complexity is small". These <!-- historical -->
  are the same unmeasured attribution the "most of the separability" <!-- historical -->
  retraction removed, in three new wordings — one of them on a line marked
  historical, which made the gate exempt the claim instead of rejecting it.
  The measurement: logistic `precision@50` 0.57060, eight-seed GBDT mean
  0.82480, and a difference that averages 0.254 and spans 0.021 to 0.328.
- **`predictions_sha256` changed meaning.** It hashed a float32 cast of scores
  that are stored and evaluated as `double` — a representation that exists
  nowhere — while the documents called matching values bitwise identity. It
  now hashes the ordered `(txn_id, dtype, score)` payload actually written to
  Parquet. **Manifests written before this change hold the old definition and
  are not comparable with values computed today.**
- **The replay inventory was wrong.** `DATA_LICENSE.md` said 446,466 rows;
  the Parquet footers say **526,355**. The first figure was totalled by hand
  from three of the five file kinds. It is generated now.
- **"N = 4 for the 182M-row run" is reconciled to the 3 that ran**, and the
  ensemble table is regenerated from the corrected 12-ordering artifact that
  already existed and had never been displayed.

- **"Most of the separability is linear" is withdrawn**, along with "largely <!-- historical -->
  there for the taking" and "what the benchmark gave away". One baseline and <!-- historical -->
  one comparator cannot apportion separability: there is no denominator, no
  ceiling and no preregistered estimand. The measurement replaces it — on
  HI-Medium, logistic `precision@50` **0.57060** against an eight-seed GBDT
  mean of **0.82480**, range 0.59144–0.89815. The GBDT's worst seed clears the
  linear fit by 0.02 and its best by 0.33.
- **The release checklist's "gbdt 0.920, logistic 0.946" is retracted.** Both <!-- historical -->
  came from `eval3_Medium`, which the canonical registry marks superseded. The
  canonical figure is **0.907**, and there is no canonical HI-Medium logistic
  re-evaluation under that null, so none is quoted. The publication gate
  reported success on that sentence — it finds those tokens elsewhere and
  cannot bind a number to the label beside it.
- **The metric-stability reporting rule is scoped.** It said every budget
  metric must be a mean over ≥8 seeds, one screen after "a single-run
  precision@50 is not a result" — and the README headline then compared two
  single fits, while HI-Large has three seeds because each costs 26 minutes.
  The exceptions are named now rather than taken silently.
- **The coverage table was wrong twice.** It first blamed the 17 skipped tests
  for six under-covered modules, which they do not cover; corrected, it still
  omitted `drift/experiment.py` at 0% while calling itself "the lowest
  modules".

- **"The second half is the contamination a ring-aware filter exists to
  remove" is withdrawn.** The split-inflation counterfactual measures a
  contrast under an unconditional exchangeability assumption that is false by
  construction — a positive is excluded *because* its ring reuses accounts.
  The two components are now stated as composition and score-distribution
  contrasts, and the second is described as consistent with contamination and
  not an identification of it. §3 of the paper had said this for a while; its
  own conclusion box had not.
- **"Content-addressed" is narrowed.** The cache is content-addressed on code
  and **metadata-addressed at the data boundary**: local directory inputs are
  fingerprinted by path, size and mtime, and outputs over 64 MB by size. It
  did not key on the dependency environment at all. **That is now fixed**:
  the run key includes the declared lock digest and interpreter version, and a
  cache lookup refuses to serve a hit when the *installed* numeric stack
  disagrees with the lock. <!-- historical -->
- **The cross-architecture ordering inference is withdrawn.** Equal average
  precision over 12.4M rows does not imply identical score ordering, and the
  README said it did. Prediction identity across architectures was never
  measured.
- **"These are exactly the paths the 17 skipped tests cover" was false.** The
  17 skips are HI-Small contract prerequisites; they do not invoke the fit,
  stability or leak-sweep paths that the coverage table lists. The sentence
  used a skip count as an alibi for a real coverage gap.

- **The 1.43× ring lift is retracted.** <!-- historical --> Measured against a
  within-day permutation null on the canonical sorted lineage it is **0.9497**,
  the upper-tail p-value is **1.000** and the lower-tail p-value is **0.001** —
  the model covers slightly *fewer* distinct rings than a ring-blind assignment
  of the same scores. Confirmed on HI-Medium: the canonical sorted gbdt gives
  **0.907**. The old null applied recall pooled over all positive account-days
  to a population 87% of which carries no ring label.
- **The numbers in the bullet above were themselves restated.** It quoted
  0.945 and HI-Medium at 0.920/0.946, all from lineages the canonical registry <!-- historical -->
  lists as superseded — fits made while the training load did not sort. A
  changelog entry announcing a retraction, carrying figures from the run the
  retraction superseded, is the defect it was written about. <!-- historical -->
- **"97% of the split uplift is prevalence" is retracted**, and with it the
  earlier retraction of "inflated by leakage". A counterfactual decomposition
  that assumes nothing about how AP responds to prevalence gives **47%
  prevalence / 53% detectability**. The original figure was wrong twice: the
  ratio arithmetic did not mean what it was reported as meaning, and the
  division assumed a functional form that holds only for a random ranker.
- **"Near-saturated" removed.** It asserts closeness to a maximum that was never
  bounded. What is measured is that a 32-feature logistic reaches
  pooled `precision@50 = 0.5706`, later retracted as a comparison. The
  correction itself was then corrected: the first null was computed on the raw
  window rather than the evaluated ring-aware split, which put the figure below
  chance at 0.95x. On the evaluated split it is **1.16x-1.26x** a random
  ranker — still barely a comparison, but above chance, not below.
- **"The benchmark everyone measures on" removed** — a claim about publication
  practice with no survey behind it.
- **`models3_Medium` superseded**, with the cause identified: it was fitted with
  the training rows in an undetermined order. See
  [`docs/RESULT_LINEAGE.md`](aml-platform/docs/RESULT_LINEAGE.md).

### Fixed

- **Training was row-order-dependent at every published scale.** Both histogram
  learners bin from a 200,000-row subsample of *positions*; the sort had been
  dropped on the strength of a 20,000-row experiment. `ORDER BY txn_id` is
  restored and `train_matrix_sha256` is recorded. Two independent HI-Medium runs
  now produce identical matrix hashes, prediction hashes and metrics.
- The bootstrap clustered on the collapsed `ring_id`, re-introducing the
  many-to-many defect inside the interval calculation. Now clusters by connected
  components of the account-day/ring graph.
- The ring-null p-value tested only the upper tail while being quoted for a
  lower-tail claim. Both tails and a two-sided value are emitted.
- The stale-output cleanup never ran — it inventoried the directory after the
  stage wrote, when stale files still look current. Its test had been written
  around the bug.
- A manifest with no output inventory could satisfy a cache hit while verifying
  nothing.
- `provision_vm.sh` mounted `/dev/$D` where `$D` was already absolute; the
  runbook's source archive omitted three lock files the Dockerfile copies.
- Live SSH exposure: the VM's NSG allowed inbound TCP/22 from `*` while the
  Bicep and runbook claimed no public IP and no inbound rule. Set to Deny.

### Added

- Replay bundles: 1.3 MB reproduces every budget metric of a 179.7M-row run.
- Preregistered split-inflation experiment, executed.
- Permutation nulls for ring recall and for the per-typology spread.
- Dataset pinned by SHA-256; an independent re-download reproduced the pin.
- `release_facts.py` generates the counts that five documents kept getting wrong.
- Hashed, platform-resolved dependency locks installed with `--require-hashes`.
- `gates` workflow: ShellCheck, actionlint, Bicep build, full-history Gitleaks,
  Bandit against a triaged baseline, link and table-structure checks.
