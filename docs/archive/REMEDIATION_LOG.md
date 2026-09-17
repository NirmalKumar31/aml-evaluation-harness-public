# Remediation log — per-round audit histories

> ⛔ **A RECORD, NOT CURRENT STATE.** Moved out of `HANDOFF.md`, which a cold
> reader described as a private diary published in public: six consecutive
> "audit N — where the remediation stands" sections with Closed/Open lists,
> standing ahead of the four decisions a reader actually needs.
>
> Numbers here are stale by definition. Current state is
> [`../../HANDOFF.md`](../../HANDOFF.md); claim boundaries are
> [`../../aml-platform/docs/LIMITATIONS.md`](../../aml-platform/docs/LIMITATIONS.md);
> retractions are [`../../CHANGELOG.md`](../../CHANGELOG.md). This directory is
> excluded from the publication gate.

## V3 audit — where the remediation stands

The report is `docs/archive/v3 audit.md`, against commit `bb9550a`. It found
**12 P0 blockers** and ~16 P1s. Every P0 I have checked was real. Status:

### Closed

| id | what it was | what was done |
|---|---|---|
| **P0-1/2** | README and the HI-Large paper headlined the **superseded unsorted** lineage while the canonical sorted one sat lower in the same file. The gate was green because it only asked whether a token appears in *some* provenanced artifact | `results_archive/CANONICAL.json` names every superseded lineage; `--check` refuses a current doc supported only by one. Found 23 such values. Canonical numbers are now primary everywhere |
| **P0-3** | "bitwise-identical predictions across arm64 and amd64" — the arm64 manifest predates `predictions_sha256`, so what was compared was *printed metrics* | withdrawn; narrowed to bitwise repeatability on **one** architecture <!-- historical --> |
| **P0-6** | metric cache still served stale ranks; the previous fix stamped a random token that an in-place mutation does not change | keyed on a blake2b digest of score/label/day/account/membership; 4 parametrised mutation tests |
| **P0-7** | three derived artifacts recorded a commit that did **not contain** their generator script | `manifest.generator_provenance()` names + hashes the generator; a test resolves `git cat-file -e <sha>:<path>` for every derived artifact |
| **P0-8** | the "every excluded row is a positive" check was a **tautology** — it verified a constant `COALESCE(..., 1)` had just assigned | labels read independently from the naive split and cross-checked; draws 60 → 400 (answer unchanged) |
| **P0-10** | tracked `.coverage` with **64 occurrences of the maintainer's home directory**, plus 32 stale duplicate sources under `build/` | untracked, ignored. Both remain in history |
| **P0-12** (part) | `SECURITY.md` named a private-reporting endpoint that 404s on a private repo | rewritten with a route that works now, and the enable step is a release-checklist row |

### Open after V3 — all closed in the V4 pass below

| id | what it was | where it went |
|---|---|---|
| **P0-4** | the runbook's exact commands failed as written, and it claimed a source-tar hash check that did not exist | V4 P0-8 |
| **P0-5** | the runners skipped a download when a file merely existed non-empty | V4 P0-8 |
| **P0-9** | replay-bundle CDLA classification unreviewed | V4 P0-10 — **still needs a lawyer** |
| **P0-11** | live Azure ≠ Bicep ≠ docs | V4 P0-9 — divergence now documented first-hand; **the decision is the operator's** |
| — | `categorical_ablation_medium.json` lacked a resolvable generator | V4 P0-3 |

---

## V4 audit — where the remediation stands

The report is `docs/archive/v4 audit.md`, against commit `830f118` with a dirty
tree. It found **11 P0 blockers** and 16 P1s. **Two were already stale** when it
was written — the tree was clean and the suite green at `b7419ae` before the
report arrived — and **nine were real**. Status:

### Closed

| id | what it was | what was done |
|---|---|---|
| **P0-1/2** | no clean snapshot; the suite was red | already true at `b7419ae`: clean tree, pushed, `ci`+`gates`+`image` green. The audit measured a working tree mid-edit |
| **P0-3** | **7 of 10** derived artifacts recorded a `generator_sha256` that is not the generator at the recorded commit; an 8th recorded a 12-character SHA | the cause was one line: `git_sha()` returned HEAD regardless of whether the file on disk is what HEAD contains. `generator_provenance` now resolves the generator **at** that commit and raises on a mismatch; the test recomputes the hash from git objects instead of asking whether the path exists |
| **P0-4** | `dataset_pin.json` silently lost `HI-Large_Trans.csv`, after which `--require all` meant "all five that remain" and reported a complete dataset | the six filenames are a CONTRACT in code, `--require all` is measured against it, re-pinning carries forward what disk cannot see, and dropping an entry needs `--drop-missing --allow-incomplete`. Three tests |
| **P0-5** | current documents mixed the superseded unsorted lineage into live claims | every current-facing number is now the canonical sorted lineage. HANDOFF also said the leak sweep and the categorical ablation had not been rerun; **both had** |
| **P0-6** | the gate matched `0.\d{4,5}` — so `0.945` was invisible — and any line carrying `<!-- derived -->` was skipped whole <!-- historical --> | three to six decimals, plus `results_archive/RETRACTED.json`, which names the values that must not appear as a current claim. 43 findings on its first run |
| **P0-7** | the counterfactual artifact and the documents disagreed, and the language was causal | the per-seed table is regenerated from the artifact (its counterfactual column was still the 60-draw values), and "effect" is now "contrast", with the exchangeability assumption stated |
| **P0-8** | the documented cloud commands could not run, and the runbook described a hash check that was never implemented | a test extracts every documented invocation and checks it against the script's own required inputs; provisioning verifies the archive before extracting and replaces `/opt/aml`; both runners hash raw data against the pin |
| **P0-9** (part) | three different project costs published at once | one dated snapshot, the runbook table generated from it, a test binding the two, and `actually_charged_usd` is `null` with the claim recorded as stated-not-measured |
| **P0-10** (part) | bundle metadata asserted a CDLA conclusion the repository calls unreviewed | `licence_status: UNREVIEWED` in every bundle; full SHAs; no `/scratch` paths |
| **P0-11** (part) | `SECURITY.md` named a channel that cannot carry a report | it now says so, and names the two ways to fix it as a blocking checklist row |
| **P1-3** | `train_matrix_sha256` identified X and nothing else | labels, feature order, dtype and byte order now hashed alongside it |
| **P1-7** | the image skipped every archive-dependent test, so "the suite runs in the image" was true and "the image validates the archive" was not | `results_archive` ships in the image and the tests resolve it from either layout |
| **P1-8/9/12/14** | strict-JSON, lint and licence-metadata gaps | strict-JSON tests; `ruff` and `bandit` cover `scripts/`; PEP 639 licence metadata; `make package-smoke` installs the wheel into an empty interpreter and runs the demo through it |
| **P2-3/4** | no Markdown configuration; external links never fetched | `.markdownlint-cli2.jsonc`, scoped to current documents — 3,148 default findings down to **0** real ones — and a weekly, non-blocking anonymous link job |

### Open after V4

| id | what it was | where it went |
|---|---|---|
| **P0-10** | replay-bundle CDLA classification | V5 P0-6 — the opening of `DATA_LICENSE.md` now discloses the derived rows instead of denying them. **The legal question is still open** |
| **P0-9** | the VM running, live state ≠ Bicep | V5 P0-8 — still open, still billing |
| **P0-11** | GitHub settings | V5 P0-9 — still open |
| **P1-1** | conclusions stronger than the evidence | **closed** — "refuted" → "not shown to be stable"; the alert-budget claim says it is an impression, not a survey; the CFF says "an operationally motivated alert-budget operating point" |
| **P1-13** | reproducibility tiers not tabulated | **closed** — the tier table is in `README.md`, and §1b of the release checklist maps every artifact to the command that regenerates it |

---

## V5 audit — where the remediation stands

The report is `docs/archive/v5 audit.md`, against commit `5f39c22` with a clean
tree. It ran the suite, the gates, a fresh `pip-audit`, a clean-wheel install
and read-only Azure and GitHub inspection, and it **confirmed the V4 work**:
10/10 generator blobs matching their recorded SHA, 9/9 package trees matching,
the six-file pin failing closed, 479 published values with nothing unsupported,
superseded or retracted.

It then found **four technical blockers the existing checks could not see**, and
all four were real.

### Closed

| id | what it was | what was done |
|---|---|---|
| **P0-1** | the provenance guard compared the GENERATOR and not the package it imports. Editing `src/aml/eval/metrics.py` while leaving `scripts/cost_table.py` alone still produced `generator_matches_commit: true` against a clean HEAD | `tree_hash_at()` rebuilds the package digest from git objects at the recorded commit and generation raises on a mismatch. Two mutation tests, one per level, each building a scratch repo from the WORKING tree so the test can fail before the fix is pushed. Every generator now records `inputs` and `parameters` |
| **P0-2** | the cloud recipe tarred the working tree, labelled it HEAD, and *printed a warning saying so* | fails on a dirty worktree; builds with `git archive <sha>`, which is byte-reproducible from the commit — two runs here give the identical SHA-256 |
| **P0-3** | the image job built twice and pushed the second build. Everything was tested against the first | tags and pushes the tested image, then pulls the published digest back and asserts it is the same image |
| **P0-4** | §3 of the split paper states the exchangeability assumption and says the second component is not proven to be leakage; its own conclusion box called it "the contamination a ring-aware filter exists to remove" | the box, the claim table, the README and `LIMITATIONS.md` all say *contrast*, and the artifact carries `estimand`, `assumptions` and `does_not_establish`. `*_effect` → `*_contrast`, old names kept as marked aliases |
| **P0-5** | `docs/FEATURE_SPEC_v1.md` declared the `txn_id` defect live and the leak proof silently wrong. **The v1 audit flagged that exact sentence and it survived four rounds** | archived with the resolution and the regression tests named, plus a check that no current document reports it as live |
| **P0-6** | `DATA_LICENSE.md` opened "a clone contains code, tests and result manifests only" and inventoried ~526,355 rows of derived replay data four sections later | the opening says what a clone contains and that the licence question is open |
| **P1-1** | the demo printed `"ci_lo": NaN` on stdout while writing strict JSON to disk — two output paths, one fixed. **My V4 "already closed" was a statement about files** | one strict serializer, twenty call sites routed through it, and a test that parses every demo event with non-finite constants rejected |
| **P1-2** | `make setup` and `package-smoke` created venvs with a bare `python3`, which is 3.14 on a fresh machine; the documented clean setup failed there | `PYTHON ?= python3.12`, version-checked before any venv is created |
| **P1-3** | five CANONICAL manifests carried 12-character SHAs | expanded, after verifying the package tree at each; a test holds canonical lineages to the current standard and grandfathers the rest by name |
| **P1-4** | bundles recompute the metrics exactly and could not say what they were an extract of | schema v3 records generator, dataset-pin and input identity; `small_gbdt_s0` is rebuilt under it and still verifies at 0 mismatches; the eight VM-built bundles now state which claims are unverifiable |
| **P1-5** | "content-addressed" covered code and not data | narrowed: content-addressed on code, **metadata-addressed at the data boundary**, and manifests record the lock digest so a dependency change is at least detectable |
| **P1-6** | the README inferred identical score *ordering* from equal average precision | deleted; only "every metric recorded in both manifests agreed" remains |
| **P1-7** | stale gate descriptions, and a coverage claim that blamed the 17 skips for six under-covered modules | corrected from measurement. **The skip-count alibi was the most misleading sentence in the checklist** and is now called out as false |
| **P1-9** | `run_cloud.sh` looped over `SEEDS` into one destination | one destination per seed, plus a count assertion |
| **P1-10** | "$180 ceiling" and "$200 ceiling" in one file; "Nobody was charged anything" as fact | one ceiling, and four cost quantities kept apart: list estimate, portal spend, credit, invoice (not measured) |
| **P1-11** | no one place said which command regenerates which result | §1b of the release checklist, plus `make release-check` for everything a bare checkout can verify |
| **P2-2/3/6** | CFF said "entity-disjoint"; a source comment quoted an intermediate result; two author identities | exact term; comment no longer quotes a value; `.mailmap` unifies the name and the email decision is a checklist row |

### Open after V5 — all closed in the V6 pass below, except the four owner items

| id | what it was | where it went |
|---|---|---|
| **P0-6/7/8/9** | licence review, Kaggle rotation, Azure, GitHub settings | still open. **These are the four, and none of them is a commit** |
| **P1-8** | the numeric gate is token-membership | V6 P0-4 — extended to money and hours, which immediately caught three stale cost figures. Still not typed; see below |
| **P1-12** | seven modules under 60% coverage | V6 P1-5 — two orchestrators now have behavioural tests; total 72% → 78% |
| **P2-1** | container hardening | V6 P1-9 — partly: the notices now ship with the image. SBOM/signing/base refresh remain |

---

## V6 audit — where the remediation stands

The report is `docs/archive/v6 audit.md`, against commit `9a84eae` with a clean
tree. It confirmed the V5 work — tested-image-equals-pushed-image, the six-file
pin, strict stdout JSON, and a full 30-minute five-seed regeneration of the
counterfactual reproducing the committed payload exactly — and then found
**eight blockers**, four of them technical.

### Closed

| id | what it was | what was done |
|---|---|---|
| **P0-1** | provenance covered the generator script and the `aml` package, and nothing else. Editing `scripts/make_tables.py` — which `release_facts.py` imports at runtime — left BOTH `generator_matches_commit` and `code_tree_matches_commit` true while the collection logic was absent from the recorded commit | a **declared scope**: nothing inside it may be modified or untracked when an artifact is written, and a generator that depends on more declares more. `release_facts` declares the whole repository. Four mutation tests: sibling script, untracked file, edited document, edited result artifact |
| **P0-2** | "largely linear", "most of the separability", "what the benchmark gave away" — an undefined fraction with no denominator, no ceiling and no preregistered estimand, in README, HANDOFF, CFF and LIMITATIONS, which contradicted itself | replaced by the measurement: logistic **0.57060** against an eight-seed GBDT mean of **0.82480**, range 0.59144–0.89815. All four documents say the same thing, and the phrases are in `RETRACTED.json` <!-- historical --> |
| **P0-3** | the **release checklist** — the document that certifies the release — quoted `gbdt 0.920, logistic 0.946` from the superseded `eval3_Medium`, **and the 479-value gate reported success**, because it finds those tokens elsewhere and cannot bind a number to the label beside it | corrected to the canonical 0.907, with no logistic figure quoted because no canonical one exists. Both values registered as retracted <!-- historical --> |
| **P0-4** | three cost figures live at once. The gate ignored two-decimal money and hours, so it saw none of them | the matcher covers `$x.yy` and `N.NN hours`; it found all three on its first run. The README copy is deleted rather than updated, and `cost.json` now records `snapshot_is_final: false` while the meter runs |
| **P0-5** | the image COPYs `results_archive/` — 526,355 rows of derived row-level records — and copied neither `LICENSE` nor `DATA_LICENSE.md` | both ship, in the image and the deployment archive, with a test. Four licence terms are now used consistently |
| **P1-1** | `make setup && make package-smoke` is the documented pair; the second failed in a clean clone with "No module named build" | `requirements-release.lock`, `twine check`, and the target now runs in both `release-check` and CI |
| **P1-5** | `eval/run.py` 27%, `drift/experiment.py` **0%**, and the published table omitted the module at zero while calling itself "the lowest modules" | 100% and 99%, with oracles. Writing the drift fixture found a latent `KeyError` on the stage's last statement — it read a sixth manifest field a hundred lines after the other five, and nothing had ever executed it |
| **P1-6** | the reporting rule forbade a single-run `precision@50` one screen before the README compared two single fits | scoped, with named exceptions and their reasons |
| **P1-7** | image parity documented as four in one place and five in another; the runs showed six | counts removed; the workflow asserts permitted REASONS, and the `paths` filter is gone so the status always exists |
| **P1-8** | `infra/README.md` instructed a build through a registry that is off by default, on a subscription that rejects the command — twelve lines after saying so | the section names the two flows that work |
| **P1-10** | `SAST_TRIAGE.md` and the workflow both said new findings fail; the blocking command was `bandit -lll` (HIGH only) and the medium run was `--exit-zero` | `scripts/check_sast.py` enforces a triaged per-rule baseline. Adding one untriaged f-string query makes it fail |
| **P1-11** | three quantities were all called "markers", and `--check` validated none of them | each count carries its scope, and all are verified against a fresh collection. `parameters.root` is relative, not a home directory |
| **P2-1/3** | prose residue, and no figures | a sentence that had lost half of itself, an audit count, a retraction count and the gate numbering are fixed; there is a Mermaid pipeline diagram and an SVG result figure generated from the archive, `--check`ed in CI. **Drawing the figure caught an error in the README** I had introduced two hours earlier |

### Open after V6 — where each went

| id | what it was | now |
|---|---|---|
| **P0-5..P0-8** | licence review, Kaggle rotation, Azure, GitHub settings | **still open. These four are the release.** V7 numbers them P0-1, P0-4, P0-3, P0-4 |
| **P1-2** | the numeric gate is token-membership | V7 P1-3 — money, hours and the replay inventory are covered now; still not typed |
| **P1-3** | cache keys the declared environment | V7 P1-1 — **closed**: the installed stack is checked before the cache hit |
| **P1-9** | image SBOM, signing, scanning | V7 P1-10 — still open |
| **P1-12** | six modules under 65% | V7 P1-11 — two more orchestration paths covered; four modules still thin |

---

## V7 audit — where the remediation stands

The report is `docs/archive/v7 audit.md`, against commit `8e34620` with a clean
tree. It scored the project at **about 82% complete overall and about 65% ready
for a public release**, and the gap between those two numbers is the whole
point: the harness is nearly done and the *release* is not.

It confirmed the V6 work — `make release-check` passing end to end, the tested
image being the pushed image, the six-file contract failing closed, all nine
replay bundles recomputing — and then found that **three new guards checked
something weaker than the claim attached to them.**

### Closed

| id | what it was | what was done |
|---|---|---|
| **P0-1** (part) | README told a reader they had "no CDLA obligation" and, in the same cell, that redistribution is unreviewed. The inventory said 526,355 rows; the Parquet footers say **526,355** — the first number was totalled by hand from three of the five file kinds | the legal conclusion is gone, and the count is generated as `replay_rows`, published in `release_facts.json` and checked in prose. **The legal question itself is still open** |
| **P0-2** | the simulator attribution survived its own retraction by being renamed: "substantially a property of the benchmark", "substantially a property of IBM's simulator", "the increment from model complexity is small" | all three withdrawn and registered. The GBDT-minus-logistic difference is **0.254 on average, 0.021 to 0.328 across seeds** — no adjective covers that. A `<!-- historical -->` marker must now actually narrate a retraction, because one was found sitting on a line that stated the withdrawn claim as current |
| **P1-1** | the cache keyed the DECLARED lock; `installed_matches_lock()` ran at stage exit and a cache hit returns before any manifest exists | the check moved in front of the lookup, and a dependency missing from the lock is reported rather than skipped |
| **P1-2** | `predictions_sha256` hashed a float32 cast of scores that are stored as `double` and evaluated as `double` — a representation that exists nowhere — while README called matching values bitwise identity. Its test read the source for two strings | it hashes the ordered `(txn_id, dtype, score)` payload as written, verified by recomputing from the committed file; the float32 form is `predictions_tolerance_sha256`, named for what it is. Archived manifests hold the old definition and are not comparable — said where they are cited |
| **P1-4** | the image workflow had a `pull_request` path filter **under a comment saying it did not**, so a root-only PR got no run — fatal once the check is required | removed |
| **P1-5** | `python -m build` resolved setuptools inside an isolated environment, so the backend that produces the wheel was unpinned | pinned in the release lock; the build runs `--no-isolation` |
| **P1-6** | the SAST baseline stored counts, so fixing one finding and adding another netted to zero | identities: rule, path and a code fingerprint, deliberately without the line number |
| **P1-7** | two sources of truth for "canonical": the registry listed three lineages, a hard-coded set in the test listed four | the test reads the registry; `_provenanced` requires a full 40-character SHA |
| **P1-8** | the HI-Medium categorical ablation was closing the encoding confound on partial provenance | relabelled historical evidence, with the claim scoped to "in this run", and **rerunning it before Azure teardown is a checklist row** |
| **P1-9** | the ensemble decision cited a table the same section calls biased, and said N=4 while the run used 3 | the corrected 12-ordering artifact — which already existed and had never been displayed — with min/max per n, a numeric plateau rule, and the discrepancy reconciled |
| **P2-1** | five places where a comment or document described the opposite of the code | corrected, including `_ranks` "keyed by length", the Bicep's "storage, a registry, and nothing else", and SECURITY.md's "no inbound rules" |
| **P2-2** | the figure check looked for four substrings, so different seeds with the same min/mean/max would pass | the model is compared exactly and every seed mark is verified at its rendered position |
| — | four DuckDB deprecation warnings | `to_arrow_reader`, behind a `getattr` so an older DuckDB still works |

### Cross-check after V7 — two of those "closed" rows were half-fixes

An independent pass re-ran the V7 fixes and reproduced two of them failing.
Both were the same shape: **I guarded one direction and left the other open.**

| what I claimed closed | what was still wrong | now |
|---|---|---|
| **P1-1** the cache checks the installed stack | it refused to SERVE a mismatched hit and then let the recomputed result be **written under the same key**, so correcting the environment served it back. Four-step reproduction | the installed digest is in the key, so a mismatched environment cannot occupy the locked one; and `load_cached` refuses any manifest that records a mismatch |
| **P1-7** one registry defines canonical | `make_tables` still treated every **unlisted** lineage as canonical — 28 of them, 58 manifests below the standard — so a new unlisted lineage could back a claim and skip the stronger test | three statuses, and `unlisted` is a publication failure. The 28 are registered as `supporting`, each with a reason |
| — | `LIMITATIONS.md` said the encoding concern "is answered" four paragraphs above the note saying it must not be closed | evidence against, not a closure |
| — | README said the prediction digest settles "the same bytes" | it settles **logical payload identity**; compression and writer version change the file, not the predictions |
| — | `SAST_TRIAGE.md` quoted the combined total under a `src/`-only command, and still described count-based behaviour | scope and mechanism corrected |

**The pattern worth carrying:** a fix that closes the read path and leaves the
write path is not a fix, and a default of "assume canonical" turns omission
into the vulnerability. Both passed their own tests because the tests exercised
the direction I had thought about.

### Open — and every one needs a person, not a commit

| id | what it is |
|---|---|
| **P0-1** | the replay bundles' CDLA classification. Disclosure is accurate and the notices ship with the image; the question is unanswered. **A lawyer** |
| **P0-3** | Azure: still running, past its notification budget, live topology ≠ Bicep, no shutdown schedule. **No final cost exists until the meter stops** — `cost.json` says `snapshot_is_final: false`. And the Medium ablation can only be rerun while the VM exists |
| **P0-4** | rotate the Kaggle token; then GitHub: disclosure route, branch protection, code scanning, GHCR visibility, the open Dependabot PRs, the authorship decision, signed tag and release |
| **P1-3** | the numeric gate is still token-membership. It covers decimals, money, hours and the replay inventory, refuses retracted values and superseded lineages, and **still cannot bind a value to the metric beside it** — which is how the checklist published a superseded ring lift. Typed claim references are the real fix |
| **P1-10** | image SBOM is Python-only; no vulnerability scan, no signature, editable install in the runtime image |
| **P1-11** | `demo.py`, `models/stability.py`, `leakproof/plant.py` and `leakproof/sweep.py` still have no behavioural tests |
| **P2-3** | the narrative is still dominated by remediation history. Everything above this line is evidence for that |

---

## Council audit (2026-09-15) — the first one that ran the code

Eight prior audits read the documents. This one executed them, and found more
than the previous two combined. Everything below is closed unless marked.

**Corrected claims.** Three prose statements contradicted the code:

1. *"Seeds measure optimizer sensitivity"* (LIMITATIONS) and *`class_weight`
   is the leading cause of the 37% spread* (config.py). Neither is true. With
   `early_stopping: False` the only live consumer of `random_state` is
   `_BinMapper`'s 200,000-row subsample; `balanced` is a deterministic function
   of `y` and cannot vary anything between runs. Verified by tracing sklearn's
   call sites and by observing byte-identical predictions across seeds below
   200k rows.
2. *`recall@50` cannot exceed 5.2%, and 0.027 is 52% of attainable*
   (metrics.py). The shipped numbers are 4.73% and 57.1%. `B*D` over-counts
   because the window is non-stationary — 81.3% of positives in the first 7 of
   19 days. Both wrong figures were 2-decimal tokens, below the publication
   gate's 3-decimal threshold.
3. *lower-tail `p = 0.001`*. That is `1/(b+1)` at b=1000 — the resolution
   floor, not a magnitude. Now `< 0.001`, with
   `ring_recall_null_p_resolution@k` publishing the floor.

**And the finding got stronger.** The obvious objection — that this makes
finding 2 a scikit-learn bug report — is refuted by the canonical HI-Large
LightGBM lineage, which has `deterministic=True`, no bagging and no feature
fraction, and spreads **30.2%** on `recall@50`, `precision@50` and
`recall_efficiency@50`. Two implementations, two rungs, same mechanism. And
because these seeds never vary row order, threads or platform, 30–37% is a
**lower bound**.

**New measurement, corrected twice.** `scripts/alert_unit_coupling.py`
measures the sender/receiver coupling under the headline metrics, which the
`ring_recall` permutation null was built for and which was never checked for
`precision@k`. Both earlier answers were wrong:

1. A score-tie proxy that treated each `(day, score)` group as one <!-- historical -->
   transaction. Unrelated transactions can share a score, so the group count
   bounds transactions from below, not above.
2. Its replacement joined `ring_endpoints` to the alerted account-days on <!-- historical -->
   `(day, acct)` with **no score filter**, attaching an account-day to every
   ring transaction touching the account instead of the one that supplied its
   maximum. `ring_transactions.parquet` carries that score and the script never
   opened it. The 14-48% "evidence" produced this way measured whether an
   account-day touches several ring transactions — a different quantity.
   Corrected, the figure is **0% on all nine bundles**.

What is measured now: a ring transaction is the SCORE SOURCE of an alerted
account-day iff its own score equals that account-day's score, and on that
definition the factor is **1.624 to 1.950** account-days per alert-causing ring
transaction at k=50. No account-day in any bundle has its maximum tied by two
ring transactions, so the ambiguous case is empty here rather than resolved by
fiat. Between 153 and 382 endpoints per bundle attach to alerted account-days
whose maximum came from something else; those are not attributable and are
excluded.

Ring transactions are the only ones whose identity AND score the bundles
record, so none of this covers the full alerted set, and a transaction-level
precision, recall or ceiling is still not derivable. `make_replay_bundle.py`
emits a transaction-level table for that; every archived bundle predates it.

**Scholarship.** The repository cited exactly one external work.
`docs/RELATED_WORK.md` names the prior art and **withdraws** the claim that
budget-aware evaluation is a gap in the literature.

**Presentation.** README 5,858 → 2,113 words, 19 warning blocks → 4. The
correction narrative moved to CHANGELOG; the long technical passages moved
verbatim to `docs/ENGINEERING_NOTES.md`. A glossary now defines ring, rung,
account-day, alert budget and recall ceiling before first use.

**Intervals.** `bootstrap_ci` ran at `budget=50` only; it now emits `ci_lo@k` /
`ci_hi@k` at every requested budget. Archived manifests predate this.

### Still open after the council — needs compute or a decision

- **16 seeds.** The exact two-sided sign test on 8 paired observations has a
  floor of 0.0078125, so the two reported p-values are the smallest the design
  can produce, not effect sizes. <!-- derived -->
  Declare the multiplicity family honestly and finding 4 cannot reach
  significance at all; 16 seeds lowers the floor by two orders of magnitude.
  Numbers in `docs/LIMITATIONS.md` §6. **Needs the dataset and a rerun.**
- **A null for `precision@k` and `recall@k`**, the way one exists for
  `ring_recall`. The consistent next step; not taken.
- **Endpoint pairs in the bootstrap clusters.** Deliberately not patched:
  doing it properly needs a transaction → endpoint map for every transaction,
  which `to_account_days` avoids because it costs a multi-gigabyte column at
  HI-Large, and the same-score proxy would put a heuristic inside a published
  interval.
- **The permutation null is not replayable.** The bundles ship the
  ingredients, but a permutation moves scores across the top-1000 cut-off, so
  the sufficiency argument has not been shown to extend.

