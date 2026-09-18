# V3 final pre-publication audit

**Repository:** `NirmalKumar31/aml-evaluation-harness`
**Audited commit:** `bb9550a0c82eee1d461a2cbefa1440e852c9876d`
**Audit date:** 2026-09-13/14 (America/Denver / UTC)
**Scope:** the complete tracked Git repository, its current GitHub configuration,
committed result artifacts and replay bundles, package and container definitions,
CI/CD, documentation, methods, scientific claims, reproducibility controls, and a
read-only comparison with the currently deployed Azure resources.
**Changes made by this audit:** none, other than creating this requested report.

---

## Final verdict

**NO-GO for making the repository public in its present state.**

This is a much stronger project than the V1 and V2 snapshots. The core codebase is
real, unusually well tested for a research repository, thoughtfully documented,
and technically interesting. The end-to-end demo runs, 293 tests pass, all current
CI workflows are green, the package builds, the pinned dependencies audit clean,
the Bicep compiles, the canonical sorted HI-Large fits exist, and the replay
mechanism is genuinely useful.

However, the repository is not yet publication-safe because the reader-facing
story and the evidence are not synchronized. The largest remaining issue is not
cosmetic: the canonical sorted HI-Large artifacts contain different values from
the values still presented as current in the root README and the main HI-Large
results paper. A green numerical checker did not catch this because it accepts a
number found in *any* provenanced artifact, including a superseded lineage. There
are also exact cloud commands that fail as written, an asserted source-tar hash
verification that does not exist, an experimentally demonstrated stale-cache bug,
unsupported cross-architecture bitwise claims, derived analyses whose recorded
commit does not contain the analysis script, and an unresolved data-licensing
judgment for the row-level replay bundles.

The right description is therefore:

> **Engineering release candidate: strong. Scientific/documentary release
> candidate: not internally reconciled. Public release: not ready.**

The blockers below should be closed before changing repository visibility. The
major findings should either be fixed or explicitly placed in a short, honest
known-limitations section. The lower-priority polish can follow, but several items
there materially affect first impressions and reproducibility.

---

## What was independently verified

These are fresh checks, not repetitions of prose already in the repository.

| Area | Fresh result | Assessment |
|---|---|---|
| Git state before the audit | clean; local `HEAD` equals `origin/main` | pass |
| Tracked repository | 393 files, 14,857,209 bytes | healthy GitHub size |
| Unit/integration suite | **293 passed, 17 skipped, 310 collected** in 32.48 s | pass, with coverage caveat below |
| Second run under coverage | **293 passed, 17 skipped** in 41.82 s | pass; no one-run fluke observed |
| Source line coverage | **75%** | reasonable overall, weak in several high-risk paths |
| Ruff | `src`, `tests`, and `scripts` clean locally | pass; CI omits `scripts` |
| `pip check` | no broken requirements | pass |
| Dependency vulnerability audit | no known vulnerabilities in `requirements.lock` | pass at audit time |
| Bandit 1.9.4, `src/` | 0 high, 47 medium, 4 low | matches the triage document |
| End-to-end demo | all six stages completed from a clean Git archive | pass |
| Package build | wheel and sdist built in an isolated environment | pass |
| Twine metadata check | wheel and sdist pass | pass |
| Package contents | both MIT `LICENSE` and `DATA_LICENSE.md` included | pass |
| Package build warning | setuptools `license-files` form is deprecated for removal after 2027-02-18 | fix before it becomes debt |
| Results JSON | 164 files parsed; no malformed committed JSON found | pass |
| Replay bundles | all nine mappings are exercised by the passing test suite | pass, but old/current naming is confusing |
| Bicep | compiles | pass; compile is not deployment equivalence |
| Shell syntax / CI ShellCheck | current gate green | pass |
| Local Markdown links | 83 checked, none broken; 0 malformed table rows | pass within the checker's limited scope |
| External links | current primary sources responded to a real GET | pass at audit time |
| `CITATION.cff` | valid against CFF 1.2.0 | schema pass; content needs correction |
| Markdownlint, current non-archive docs | 308 default-rule findings: 234 line-length, 58 unlabeled fences, 16 others | formatting is not release-clean |
| GitHub CI at audited `HEAD` | `ci`, `gates`, and `image` all successful | pass, with important blind spots below |
| GitHub rulesets | none | fail for a public release |
| GitHub release/tag | none | expected pre-release, but release gate remains open |
| GHCR anonymous pull | denied; package is private | distribution decision unresolved |
| Live Azure VM | running | cost still accruing |

### Test coverage detail

The 75% source coverage is not evenly distributed:

| Module | Coverage |
|---|---:|
| `aml.demo` | 19% |
| `aml.drift.experiment` | 0% |
| `aml.eval.run` | 30% |
| `aml.models.stability` | 31% |
| `aml.models.train` | 41% |
| `aml.leakproof.plant` | 53% |
| `aml.leakproof.sweep` | 58% |

The strong total test count should not be used as a proxy for risk-weighted test
coverage. The lower-coverage modules include the model-fit and experiment paths
that create publication claims.

---

## Release blockers — must fix before public visibility

### P0-1. The main HI-Large result is split across a superseded and a canonical lineage

The canonical lineage is now clearly named in
`aml-platform/docs/RESULT_LINEAGE.md` as
`large_sorted_lgbm_s{0,1,2}`. Those fits use `ORDER BY txn_id`, share the same
124,992,128-row training-matrix hash, record prediction hashes, and are the correct
post-fix evidence.

Their current seed results are:

| Metric | Seed 0 | Seed 1 | Seed 2 | Mean |
|---|---:|---:|---:|---:|
| `recall@200` | 0.09521 | 0.07851 | 0.08982 | **0.08785** |
| `precision@50` | 0.48530 | 0.35584 | 0.44547 | **0.42887** |
| `ring_recall@200` | 0.88772 | 0.84880 | 0.86976 | **0.86876** |
| permutation null | 0.93650 | 0.88893 | 0.91934 | **0.91492** |
| ring lift | 0.948 | 0.955 | 0.946 | **0.9497** |

The root README still presents `recall@200 = 0.0918` and
`ring_recall@200 = 0.8742`, values from the superseded unsorted
`large_eval3_lgbm_s*` lineage. `paper/RESULTS_hi_large.md` makes the same old
lineage its primary tables, narrative, conclusion, and “what may be claimed” row,
then inserts the corrected canonical table later in the same document. It even
retains the sentence that dropping the sort was proven safe by bitwise-identical
predictions—the exact claim the new 210,001-row test disproves.

This is a publication blocker because a reader cannot tell which headline is the
paper's result. The difference is not merely rounding: mean `recall@200` changes
from about 0.0918 to 0.08785, and the seed-specific values and fitted predictions
are different.

**Required change:** make one explicit machine-readable canonical-result registry;
update every current document to use it; mark every unsorted directory and replay
bundle as `superseded_unsorted`; move the old narrative to the retracted archive;
and make CI reject a current document whose supporting artifact is not canonical.

### P0-2. The numerical publication gate can certify the wrong lineage

`scripts/make_tables.py --check` is token-based. It asks whether a decimal token
appears in some eligible artifact. It does not bind the number to a metric, model,
seed, budget, unit, dataset rung, or canonical/superseded status. Integers and
percentages are largely outside its protection.

That limitation is documented, but it is no longer hypothetical: the gate is green
while the root README and main HI-Large paper headline superseded values. The same
design also lets a correct value appear under the wrong label.

**Required change:** replace the token-membership check for current publications
with typed references, for example `(artifact-id, metric-key, aggregation,
format)`. At minimum, add a canonical/superseded allowlist and require each current
table to name its source lineage. Keep the loose checker only as a secondary typo
detector.

### P0-3. The cross-architecture “bitwise-identical predictions” claim is not evidenced

The README, `HANDOFF.md`, and `docs/LIMITATIONS.md` say that the same code produced
bitwise-identical predictions on arm64 macOS and amd64 Linux.

The committed evidence does not prove that:

- The old arm64 manifest with model hash `084dae41...` predates
  `predictions_sha256` and `train_matrix_sha256`.
- The canonical Linux/amd64 manifest records prediction hash `33601dc4...`.
- The canonical replica has the same hash, but it is another Linux/amd64 Azure run,
  not an arm64 run.
- Equal printed metrics or identical score ordering do not establish byte-identical
  prediction arrays.

The repository proves deterministic repeatability twice on Linux at the canonical
commit, and it records an older cross-platform metric agreement. It does **not**
prove the stronger bitwise cross-platform statement.

**Required change:** either rerun the same committed code, data, row order, model
configuration, and score serialization on arm64 and amd64 and compare committed
`predictions_sha256` values, or narrow every claim to the evidence actually held.

### P0-4. The documented cloud commands fail as written

The runbook's “exact” command sequence is no longer executable:

1. `provision_vm.sh` now requires `AML_GIT_SHA`, but the documented invocation
   supplies only `ACCT`; it exits 1.
2. `run_cloud.sh` now requires `IMAGE`, but the documented HI-Medium invocation
   supplies only `ACCT` and `VARIANT`; it exits immediately.
3. `run_hi_large.sh` now requires `TAG`, but the documented HI-Large invocation
   supplies only `ACCT`; it exits immediately.
4. The runbook says the VM verifies the recorded source-tar SHA-256 before
   extraction. `provision_vm.sh` downloads the tarball and immediately runs
   `tar xzf`; it accepts no expected hash and performs no verification.

This is a direct reproducibility failure: a new user following the authoritative
runbook cannot reach stage one.

**Required change:** execute the runbook verbatim from a clean deployment in CI or
a disposable resource group. Pass `AML_GIT_SHA`, `TAG`/`IMAGE`, and the expected
source hash consistently; verify the hash before extraction; and add a no-cloud
contract test that compares required shell parameters with every documented
invocation.

### P0-5. Cloud input integrity remains fail-open on existing files

`run_cloud.sh` downloads raw files only when a path is absent. `run_hi_large.sh`
uses `[ -s file ]` and resumes a download only when the file is empty. Neither
runner verifies the pinned dataset hash before the expensive pipeline begins.

A partial but nonempty file, a stale same-name file, or a corrupted upload is
therefore accepted. `verify_dataset.py --require ...` exists but the runners do not
call it. The Medium upload is also not verified after transfer on the VM.

**Required change:** run the pinned verifier on the VM after every download/upload
and before normalization, delete or quarantine mismatches, and fail closed. Verify
the source archive similarly. A filename and nonzero size are not identities.

### P0-6. The metric cache still returns stale ranks after in-place mutation

The attempted cache fix assigns a UUID `_build_token` once in `to_account_days` and
stores that token with cached ranks/ring structure. In-place changes do not change
the token, so the cache still cannot detect mutation.

Fresh reproduction at audited `HEAD`:

```text
before                         [1.0, 3.0, 2.0, 4.0]
after negating score, cached   [1.0, 3.0, 2.0, 4.0]
after clearing cache, fresh    [3.0, 1.0, 4.0, 2.0]
stale?                         True
```

The comments say the token makes stale reuse impossible; the behavior disproves
that. The pipeline may not currently mutate this frame, but these helpers create
every published budget metric and are reachable from library code. The invariant
must be enforced rather than narrated.

**Required change:** make the evaluation frame immutable by contract, compute the
cache key from the actual relevant columns and membership, or use an explicit
version that every mutation path increments. Add regression tests that mutate
score, day, account, labels, and membership after the first metric call.

### P0-7. Three important derived analyses have invalid commit provenance

The following artifacts record a `code_git_sha` whose commit does not contain the
script that generated the artifact:

| Artifact | Recorded SHA | Missing at that SHA |
|---|---|---|
| `split_inflation_counterfactual.json` | `52632868673d...` | `scripts/split_inflation_counterfactual.py` |
| `categorical_ablation.json` | `111c4c2c99c2...` | `scripts/categorical_ablation.py` |
| `categorical_ablation_medium.json` | `b48ed9ff2b4a...` | `scripts/categorical_ablation.py` |

They were produced while their analysis code was uncommitted, then the code was
committed later. A commit SHA is not valid provenance for code absent from that
commit. These artifacts support the current 47/53 split interpretation and the
defense of the linear-baseline headline, so this is not archival trivia.

**Required change:** commit the analysis first, rerun from a clean checkout, and
record full commit, code-tree/script hash, dirty-tree flag, input artifact hashes,
parameters, environment, output hash, and execution time. CI should reject a
derived artifact if its recorded commit cannot resolve every named generator
script.

### P0-8. The split-inflation decomposition is presented too causally

The counterfactual is an interesting sensitivity analysis, but it does not uniquely
identify “prevalence” versus “leakage” as causal components.

Specific problems:

- `load_seed` sets every row absent from the ring-aware set to `y=1` with
  `COALESCE(..., 1)`, then checks that every excluded `y` equals 1. That check is a
  tautology. It does not independently validate the excluded labels.
- The method resamples excluded-positive scores unconditionally from retained
  positives. It does not condition on day, typology, ring structure, account
  history, or other composition variables.
- “Easier excluded positives” demonstrates a detectability/composition difference.
  It does not by itself prove that train-test leakage caused the difference.
- Sixty draws per seed is thin for a headline decomposition; the displayed
  seed-range is not an inferential interval.
- The preregistered HI-Medium confirmation remains unrun.

The papers acknowledge some of this, but then call the 53% component
“contamination” or “inflated by leakage.” That conclusion is stronger than the
design.

**Required change:** independently join naive labels and verify the set difference;
report excluded-count equality and label counts; call the second component
“detectability/composition under this resampling counterfactual”; add stratified
sensitivity analyses; increase/rejustify Monte Carlo draws; and run the declared
HI-Medium confirmation before using a field-facing leakage headline.

### P0-9. Replay-bundle redistribution remains an unresolved legal release decision

`DATA_LICENSE.md` is now admirably candid: the bundles contain row-level derived
records with labels, days, pseudonymous account codes, scores, ranks, ring
membership, endpoints, and one record per ring transaction. It also says the
assessment that these are CDLA “Results,” rather than a non-de-minimis portion of
Data/Enhanced Data, has not been reviewed by a lawyer.

That means the project itself documents an unresolved release risk while the
release checklist has no legal/licensing gate. The opening sentence “No transaction
data is included or redistributed” is also easy to read more broadly than the
later disclosure of `ring_transactions.parquet` and row-level account-day records.

This audit does not make the legal judgment. It does conclude that an explicitly
unreviewed redistribution classification cannot be called publication-ready.

**Required change:** obtain a competent license review, obtain/record permission,
apply the required CDLA terms to the bundles, or remove the row-level bundles and
publish aggregate/reconstructible alternatives. Make the decision a named manual
release gate and make the opening data statement precise.

### P0-10. Generated local artifacts are tracked, including a privacy-revealing coverage database

The repository tracks:

- `aml-platform/.coverage`, a 52 KB SQLite database containing absolute local
  paths such as `/Users/<user>/Possible Projects/...`;
- 32 files under `aml-platform/build/lib/aml/`, totaling about 308 KB;
- stale duplicate code in that build tree: `io.py`, `leakproof/sweep.py`, and
  `models/train.py` differ from `src/aml`.

These should never be source-controlled. The build tree creates two apparent
implementations and can confuse search, review, packaging, scanners, and future
contributors. The coverage database publishes the maintainer's workstation path
and is not a portable coverage report.

**Required change:** remove both generated artifacts from Git, add `.coverage`,
`coverage.xml`, `htmlcov/`, `build/`, and `dist/` to ignore rules, and publish a
CI-generated text/XML/HTML coverage artifact or badge instead. Verify the sdist and
wheel from a clean source tree after removal.

### P0-11. Live Azure state, IaC, and public documentation describe different systems

Read-only inspection found the VM still **running**. The live deployment uses the
older names and topology: the NIC still has a public-IP reference; an explicit NSG
rule now denies inbound TCP/22 from `*`; the live subnet has neither the new NAT
gateway association nor `defaultOutboundAccess: false`. The current Bicep instead
declares a NAT gateway, no NIC public IP, and disabled default outbound access.

`infra/README.md` now admits that deployed state is not the template, which is good,
but other documents still say “no public IP,” “no inbound rules,” or describe the
template as though it were the observed run. “No allowed inbound traffic” is true
of the inspected NSG; “no public IP” and “no inbound rule” are not true of the live
resources.

The cost story also diverges:

- Root README: **$27.90**.
- Runbook/artifact at 99.99 hours: **$54.71 list-price estimate**.
- Live VM: still running after that snapshot, so both are already stale as current
  totals.
- “$0 actually charged” is inferred from a free-trial spending limit and
  `pretaxCost: null`, not demonstrated by an invoice/payment statement.

**Required change:** decide whether to delete or retain the resource group; reconcile
or explicitly snapshot the deployed topology; stop describing target IaC as live
state; replace the root cost with one dated, scoped artifact-derived value; label
the zero-charge statement as reported/inferred unless billing evidence exists; and
do not publish a “one cost table” claim while another current cost appears in the
README.

### P0-12. The repository's own release gates are visibly incomplete

The current GitHub state is:

- repository private;
- no branch rulesets/protection;
- no tag and no GitHub Release;
- secret scanning unavailable/off;
- code scanning unavailable/off;
- private vulnerability reporting disabled;
- GHCR package private; anonymous pull denied;
- five open Dependabot PRs updating all major JavaScript actions.

`SECURITY.md` instructs users to use GitHub's private vulnerability-reporting path,
but the endpoint is currently disabled. That is a broken disclosure route.

The manual release checklist itself leaves repository-public, security features,
branch protection, image distribution, signed tag/release, cloud resolution, and
history decisions unchecked. Additionally, its dataset release gate fails locally
because `HI-Large_Trans.csv` is absent: five pinned files verify and one required
file is missing. That may be easy to resolve by downloading it, but the declared
gate has not passed.

**Required change:** close the content/method blockers first, then make public in a
controlled release window; immediately enable security features and private
reporting (or provide a working security email first), configure required checks
and force-push/deletion protection, decide GHCR visibility/document authentication,
run the full data verifier, and create a signed tag plus GitHub Release with
immutable artifact/image digests.

---

## Major findings — material quality or credibility issues

### P1-1. `HANDOFF.md` is not trustworthy as the asserted source of truth

It says “Everything here is verified against artifacts or code,” but contains
multiple current false or contradictory statements:

- “310 pass, 17 skip” instead of 310 collected = 293 passed + 17 skipped;
- 9 documents, although the number gate now covers 11;
- 68 derived markers, while the generated artifact says 67;
- the retracted “97% prevalence” claim in the claim table;
- `large_eval3_lgbm_s*` as current HI-Large evidence;
- `large_final_lgbm_s*` as fit evidence even though those three manifests have
  `code_git_sha: unknown`;
- `make_tables.py` “generates every published figure,” when it verifies tokens and
  explicitly does not generate the documents;
- bitwise cross-architecture predictions, not established by artifacts;
- state date 2026-09-12 despite material 2026-09-13 changes.

The `release_facts.py` regex lets “310 pass” succeed because it compares that token
to `tests_collected`, not `tests_passed`. This is another concrete checker false
negative.

**Change needed:** either make HANDOFF generated from typed facts or demote it to an
internal historical note. Correct the regex semantics and add checks for marker,
document, manifest, canonical-lineage, and full/pass/skip counts.

### P1-2. The typology replication conclusion remains stronger than its model

The analysis has only eight structures and uses a plug-in/model-conditional
“perfect replication” calculation. Some text appropriately says “no evidence of
replication,” but the README and results text still say the ordering is “refuted,”
“genuinely does not replicate,” or cannot generalize.

Failure to fall inside a plug-in interval is not proof of nonreplication under a
composite uncertainty model. The result is useful evidence of instability, not a
definitive refutation.

**Change needed:** use “ordering was not stable/demonstrated across these two
rungs under this model-conditional comparison”; retain the concrete reversals and
wide seed ranges; avoid universal deployment claims.

### P1-3. Several broad scientific sentences remain unsupported or overstated

Examples:

- “Published numbers on this dataset rarely state the alert budget” has no survey.
- “Whatever separates positives ... is largely linear and largely there for the
  taking” generalizes from one logistic specification on one synthetic dataset.
- The main HI-Large paper still says “near-saturated,” despite its explicit
  retraction elsewhere.
- `CITATION.cff` says “ring-aware entity-disjoint,” the terminology the limitations
  document rejects as too broad.
- `CITATION.cff` calls precision@50 “the operating point practitioners care about”
  without operational evidence.
- `LIMITATIONS.md` says categorical encoding “has not been ablated,” then later
  reports the completed ablation.

**Change needed:** run a repository-wide claim glossary/search after selecting the
final terminology. Prefer narrow measured statements: “this classifier on this
feature set and dataset,” “under an independence null,” “ring-participant-disjoint,”
and “chosen illustrative budget.”

### P1-4. Archived and current result artifacts are not sufficiently segregated

There are 101 archived manifests. Forty-seven lack a current `run_key`, seven
record `code_git_sha: unknown`, and 69 lack a current output inventory. Historical
evidence is valuable, but it lives beside canonical results under names such as
`large_final_*`, `large_eval3_*`, and replay bundles named simply `large_lgbm_*`.

The three old replay bundles pass against the old manifests and are kept as defect
evidence, but their names do not tell a reader that they are superseded. A consumer
can easily choose the wrong “final” run.

**Change needed:** add a registry with status (`canonical`, `supporting`,
`superseded`, `retracted`, `legacy-unprovenanced`), parent/superseding lineage,
artifact schema version, and claim IDs. Rename or relocate old replay bundles and
prevent current documents from resolving to them.

### P1-5. Manifest identity is still weaker than the README wording

The README says every stage records inputs and their checksums. Current manifests
derive cache keys from input fingerprints, but input directory identity is not
presented as an explicit per-file checksum inventory, and local large-file/directory
fingerprints rely partly on size and modification time. Output files larger than
64 MiB are recorded by size rather than a full SHA-256.

This may be a deliberate performance tradeoff, but “content-addressed” and
“checksums” sound stronger than the implementation.

**Change needed:** document exact identity semantics and thresholds; record the
input fingerprint and method in the manifest; hash final publication artifacts in
full even if routine cache validation uses a faster proxy; distinguish cache
identity from archival provenance.

### P1-6. Training-matrix identity excludes labels and row identity

`train_matrix_sha256` is a strong improvement, but the name suggests a complete
training-input identity while it hashes the feature matrix, not `y` and not the
ordered transaction IDs. Stable SQL ordering and other manifests reduce the risk,
but the evidence would be stronger and less ambiguous with separate hashes for
`txn_id`, `X`, and `y`, or one canonical row-record hash.

**Change needed:** record `train_row_ids_sha256`, `train_features_sha256`, and
`train_labels_sha256` and define byte order/dtype/endian conventions.

### P1-7. The runtime lock and image include unrelated packages

`requirements.lock` contains 63 packages, including Kaggle/Jupyter/document tooling
such as `jupyter_core`, `jupytext`, `nbformat`, `markdown-it-py`, and `bleach`, while
no source or script import was found for them. The lock is generated from
`pip list` in the current environment rather than resolved from a minimal declared
input. This inflates the container, SBOM, vulnerability surface, and update burden.

**Change needed:** generate runtime, cloud, development, and release-tool locks from
minimal input sets using a deterministic resolver. Build the runtime image only
from runtime/cloud dependencies. Do not freeze whatever happened to be installed
in a long-lived environment.

### P1-8. The SBOM is a Python lock inventory, not a complete container SBOM

The committed CycloneDX file lists 63 Python libraries and their selected wheel
hashes. It has no dependency graph, no OS packages, no DuckDB extension component,
no services, and no image digest. Its metadata identifies old commit `5c8d62d...`,
not the release candidate.

Calling it an SBOM is not wrong, but calling it the contents of the published image
is too broad. The image also installs Debian packages and downloads the DuckDB Azure
extension during build.

**Change needed:** generate a standard SBOM from the final image digest (for example
CycloneDX/SPDX via a mature image scanner), retain the lock-derived document as a
Python dependency inventory, attach both to the release, and sign/attest them.

### P1-9. Container and local image builds are not fully reproducible

Good controls: the Python base image is digest-pinned, Linux wheel hashes are
pinned, code is read-only at runtime, and CI injects a Git SHA.

Remaining gaps:

- `apt-get update` installs unpinned Debian packages from mutable repositories;
- the DuckDB Azure extension is fetched at build time without a committed digest;
- `build-essential` and `git` remain in the runtime image;
- `pip install -e .` makes this a development-style install;
- `make docker-build` does not pass `AML_GIT_SHA`, so local images record
  `unknown`;
- `make docker-build` installs unpinned `pytest`, despite the workflow correctly
  using the hashed dev lock;
- the Dockerfile comments still say all three “current” HI-Large fits have unknown
  SHAs, which is stale after the sorted refits.

**Change needed:** use a builder/runtime split; install a wheel non-editably;
snapshot or pin OS packages where feasible; verify the extension artifact; pass a
required SHA in every build path; use the hashed dev lock in local validation; and
remove stale commentary.

### P1-10. The image test skips materially more than the host test

The latest image workflow reports **279 passed, 31 skipped**, versus **293 passed,
17 skipped** on the host. It also emits a `PytestCacheWarning` because the non-root
user cannot create `/app/.pytest_cache`.

The additional skips occur because the image does not include repository-root docs,
release facts, result archives, and replay bundles. Thus “run the full suite inside
the image” is technically collection of the full test tree, but not execution of
the same assertions. The host CI covers them separately, yet the documentation
should not imply equivalence.

**Change needed:** run with `-rs -p no:cacheprovider`, publish skip reasons, define
an expected skip allowlist, and describe the image suite as the runtime-compatible
subset unless the required audit artifacts are mounted or copied in.

### P1-11. CI action dependencies are already obsolete

All major JavaScript actions in current workflows target deprecated Node 20 and are
being forcibly executed on Node 24 by GitHub. The latest successful logs warn for
checkout, setup/build/login/push Docker actions, and Gitleaks. Five Dependabot PRs
are open for their maintained major versions.

Commit-SHA pinning is good, but a stale exact pin is still stale.

**Change needed:** review and merge/update the five actions by verified commit SHA,
run all workflows on a PR, and keep the version comments synchronized. Configure
repository policy to require SHA-pinned actions if available.

### P1-12. Static/release tooling is only partly pinned and partly scoped

- CI Ruff scans `src/` and `tests/`, not `scripts/`, even though scripts generate
  scientific claims. Local Ruff over scripts passes today, but CI would not protect
  that state.
- Bandit scans only `src/`; adding scripts changes the fresh total from 47 to 51
  medium findings and from 4 to 10 low findings.
- `actionlint` is installed by executing a remotely fetched installer script from a
  tag URL without a checked digest.
- `az bicep install` fetches the current Bicep tool, so the gate can change without
  a repository change.
- ShellCheck comes from the mutable `ubuntu-latest` apt repository.
- CI upgrades `pip` to the current release and installs the unhashed host locks;
  only the Linux image lock is hash-enforced.

**Change needed:** include `scripts/` in lint/SAST, pin or verify all gate tools,
record their versions, and distinguish “version-pinned packages” from
“hash-pinned bytes.”

### P1-13. The Azure VM image and provisioning packages are mutable

Bicep uses Ubuntu `version: latest`. `provision_vm.sh` calls `apt-get install` for
Docker, curl, and Azure CLI without package versions. The Microsoft repository is
signed, but the comment calls it “PINNED REPOSITORY” even though neither repository
snapshot nor package version is pinned.

This is acceptable for an operational convenience script only if claims are
narrow. It is not sufficient for a reproducible cloud environment.

**Change needed:** pin the Azure image version, capture OS/package versions in run
manifests, and use a versioned/snapshotted provisioning path. Change the comment to
“signed repository” unless it is actually pinned.

### P1-14. Infrastructure documentation contains an unusable ACR path

`infra/README.md` first says the registry is off by default and ACR Tasks are
blocked on the trial subscription, then presents `az acr build` as the image-build
procedure. With `deployRegistry=false`, the output is empty; on the documented
trial, the task is blocked anyway. The Bicep header also still says “storage, a
registry, and nothing else” even though it provisions networking, VM, disks, and
identities.

**Change needed:** remove the dead ACR procedure from the main path or place it in a
clearly conditional alternative with the exact deployment parameter and
subscription requirement. Make the VM/GHCR path authoritative.

### P1-15. Security posture claims need exact wording

The current target Bicep has no allowed inbound traffic and no NIC public IP. The
live deployment has a public IP and an explicit deny rule. `SECURITY.md` says “No
inbound rules on the VM,” which is false as an inventory statement, though the
security outcome observed is no allowed inbound TCP/22.

Role-scope commentary also says “scoped to the resource group” beside assignments
whose actual scope is the storage account/registry, which is narrower and better
but textually inaccurate.

**Change needed:** consistently separate target template, historical run, and live
state. Describe effective access, not absence of objects. Ensure the vulnerability
reporting route works before publishing it.

### P1-16. The full dataset release verification has not been demonstrated at HEAD

The default verifier found five present files with matching hashes and one absent
file, `HI-Large_Trans.csv`. `--require all` therefore exits nonzero. The cloud
results can still be genuine—the Large file was downloaded on the VM—but the
release checklist explicitly names this command as the gate.

**Change needed:** run the full verifier on a clean release environment, record a
small signed verification artifact with all six filenames, sizes, hashes, source,
and timestamp, and link it without committing the dataset.

---

## Secondary findings and publication polish

These should not distract from the blockers, but they matter to “GitHub standard,”
usefulness, and first impression.

### P2-1. Markdown formatting is not lint-clean

Across current, non-archive Markdown, default markdownlint reports 308 findings:
234 lines over 80 characters, 58 fenced blocks without a language, and 16 structural
or style findings. The structural set includes a PR template without an H1,
multiple blank lines, missing blank lines around lists, emphasis used as headings,
trailing punctuation in a heading, and malformed emphasis spacing.

Line length is a policy choice, not an objective defect, and many wide result tables
should be exempt. Unlabeled fences and the structural findings are worth fixing.

**Change needed:** commit a deliberate `.markdownlint` configuration, exempt tables
and long URLs where appropriate, fix the remaining structural issues, and add the
configured check to CI. Do not chase a default rule blindly.

### P2-2. The link checker has important blind spots

It intentionally does not fetch external links, skips image embeds, and recognizes
Markdown inline links but not all autolinks/bare URLs. This means the most important
dataset and license links in angle brackets are outside its external count.

**Change needed:** keep network checks out of mandatory CI if flakiness is a concern,
but add a scheduled external-link job and parse autolinks and image targets. Print
the actual external URLs, not just a count.

### P2-3. Structured stdout is not always valid JSON

The demo's `train_complete` log prints `NaN` for bootstrap bounds when bootstrap is
disabled. Python's permissive encoder emits this, but strict JSON parsers reject
it. The written manifest correctly converts those values to `null`; stdout does
not.

**Change needed:** route all structured logs through the same strict JSON
normalization used by `io.write_json` and test every emitted line with a parser that
rejects nonfinite constants.

### P2-4. Git history/release identity needs a conscious decision

All 102 commits are unsigned. Ninety-one use the local hostname email
`nirmalkumar@Nirmals-MacBook-Air.local`; eleven use the Northeastern address. This
can impair GitHub attribution and exposes a local machine identity. Rewriting is a
tradeoff because commit SHAs are embedded throughout provenance.

**Change needed:** do not rewrite casually. Decide and document whether to accept
history as-is; use a verified/noreply address going forward; sign the release tag
and preferably future commits. Preserve an old-to-new map if a history rewrite is
chosen.

### P2-5. Repository metadata under-sells and misdescribes the project

The GitHub description still says “32M rows, DuckDB, one laptop,” despite the
179.7M-row cloud work and the project's central methodological contribution. No
topics or homepage are set. The root README has no build/status/license/Python
badges and no compact architecture/result visual.

**Change needed:** update the description, add accurate topics, add only meaningful
badges, and consider one small architecture/result-lineage diagram. Lead with the
evaluation methodology and reproducible evidence, not just scale.

### P2-6. Community files are good but incomplete

Strong: MIT license, contributing guide, security policy, citation file, changelog,
PR template, and a focused “number dispute” issue template.

Missing or narrow: no Code of Conduct, no general bug/feature templates, no support
route, and currently no working private vulnerability channel.

**Change needed:** add a concise Code of Conduct and general issue templates if
external contributions are desired. A functioning security route is mandatory;
the others are optional for a solo research project.

### P2-7. `CITATION.cff` is valid but not release-complete

It correctly omits `version` and `date-released` because no release exists. Its
schema validates. Its abstract, however, contains the stale split terminology and
unsupported practitioner-operating-point phrase described above.

**Change needed:** correct the abstract now; populate version, date, release URL,
and preferably DOI only when the signed release exists. Consider Zenodo after the
public release if archival citation matters.

### P2-8. Package versioning and release tooling are only halfway defined

`pyproject.toml` declares `0.1.0` while the changelog remains Unreleased and no tag
exists. That is acceptable during development but requires one final synchronization.
The package can build only after installing release tooling separately; `make setup`
does not install `build`/`twine` or expose a release-check target.

**Change needed:** add a reproducible `make dist-check` or equivalent, align
`0.1.0`, changelog, CFF, tag, and GitHub Release in one release commit, and migrate
setuptools license-file configuration away from the deprecated field.

### P2-9. Comments are too historical and sometimes contradict current code

The repository's candid audit trail is a strength, but production files contain
long narratives about multiple former failures. Several are stale. This increases
review burden and makes it harder to distinguish the current contract from history.

Examples include old fit provenance in the Dockerfile, old environment test counts
in `release_facts.py`, and obsolete infrastructure descriptions in Bicep.

**Change needed:** keep durable “why” comments near code, move incident chronology
to `CHANGELOG.md`/decision records, and verify every present-tense comment in the
release pass.

### P2-10. The root README is compelling but too defensive and internally repetitive

The repeated warning/retraction blocks demonstrate integrity, but they dominate the
first-time reader experience. Some retractions recur in README, HANDOFF,
LIMITATIONS, results papers, changelog, source comments, and archived audits—while
still disagreeing in places.

**Change needed:** make the root README a concise entry point: problem, method,
canonical results, quick start, reproducibility tiers, limitations, cloud evidence,
and links. Put detailed correction history in the changelog/result lineage. One
authoritative statement is more impressive than six inconsistent disclaimers.

---

## Methods and scientific assessment

### What is genuinely strong

- The alert-budget framing is useful and more operationally meaningful than using
  ROC-AUC as the headline in an extreme-imbalance setting.
- Units are distinguished: transaction AP, account-day budget metrics, and
  ring-level recall.
- Recall ceilings and recall efficiency make the budget constraint explicit.
- The ring-participant-disjoint temporal split is much more carefully described
  than in earlier versions.
- Tie sensitivity, permutation nulls, both p-value tails, and many-to-many ring
  membership are thoughtful additions.
- The 210,001-row boundary test directly targets the histogram learners' actual
  subsampling threshold and found a real defect.
- The canonical sorted fits and matrix hashes materially improve determinism.
- The negative-control philosophy is excellent. The project correctly demonstrates
  that provenance cannot rescue a wrong estimand.
- Replay bundles make otherwise enormous result calculations independently
  inspectable with small committed artifacts.
- The limitations documents are unusually candid about synthetic data, the FIU/
  network feature perspective, partial ring labels, dropped connected rings, seed
  instability, and non-transferability.

### What the project may safely claim after reconciliation

- It provides an end-to-end, tested harness for alert-budget-aware evaluation on
  the specified AMLworld files.
- On the pinned HI-Medium dataset and stated 32-feature representation, the chosen
  logistic baseline reaches `precision@50 = 0.5706`, and the chosen boosted model
  reaches about 0.794 on the canonical sorted run.
- Account-day recall is sharply constrained by a daily review budget, so it must be
  interpreted beside its ceiling.
- Raw `ring_recall` and account-day recall answer different questions; ring recall
  must be interpreted with a null that respects day, budget competition, and ring
  structure.
- Under the implemented within-day permutation null, these fitted models do not
  cover more distinct rings than the ring-blind score assignment; observed values
  are lower on the evaluated rungs/configurations.
- Model-seed variability is large relative to several claimed effect sizes on these
  fixed datasets.
- Per-typology ordering is unstable across the evaluated rungs and seeds and should
  not be assumed transferable.
- The sorted training pipeline repeats bitwise on the two committed Linux/amd64
  canonical Medium runs and produces the same Large training-matrix hash across
  three seed fits.
- The full pipeline has been executed on Azure over the 179.7M-row HI-Large file on
  a 31 GB VM, subject to the documented lineage and cost scope.

### Claims that should not appear without new evidence

- bitwise-identical predictions across arm64 and amd64;
- a field-wide assertion that AMLworld papers rarely state alert budgets;
- “near-saturated,” “benchmark solved,” or “mostly a property of the simulator”;
- “97% prevalence” in any current summary;
- a causal 53% leakage decomposition;
- definitive refutation of typology replication;
- that 0.945 is the current canonical HI-Large lift without saying the corrected
  sorted mean is 0.9497;
- that the current exact cloud runbook has been reproduced;
- that every input/output is fully content-hashed;
- that the committed Python component list is a complete image SBOM;
- that no public IP or inbound rule exists in the deployed resources;
- that $54.71 is a final project cost while resources remain running;
- that $0 was definitely charged without authoritative billing evidence.

---

## Reproducibility ladder

| Reproduction level | Current state | Verdict |
|---|---|---|
| Clone and install on Python 3.12 | locked setup exists and CI proves it | pass |
| Run without external data | clean-archive demo completes | pass |
| Run unit/integration checks | 293 pass, 17 data-dependent skips | pass with coverage caveat |
| Build distributable package | isolated wheel/sdist and Twine check pass | pass |
| Build/test Linux image in CI | succeeds, but 31 tests skip | partial pass |
| Pull advertised image anonymously | denied | fail until documented/changed |
| Verify a committed metric without dataset | replay mechanism works | pass |
| Identify one canonical result per claim | current/old lineages mixed | fail |
| Reproduce published Small result from raw data | commands and pin exist | plausible; fresh full run not repeated here |
| Reproduce all six pinned inputs locally | one required Large file absent | fail at audited workstation |
| Reproduce exact cloud run from runbook | required parameters missing; hash claim false | fail |
| Prove cross-architecture bitwise prediction parity | arm64 prediction hash absent | fail |
| Reproduce derived 47/53 and categorical analyses from recorded commit | scripts absent at recorded SHAs | fail |
| Reproduce final release from immutable tag/image digest | no tag/release; GHCR private | fail |

---

## File-by-file change map

### Root `README.md`

1. Replace old unsorted HI-Large values with canonical sorted values and ranges.
2. Remove or qualify cross-architecture bitwise prediction claims.
3. Replace `$27.90` with one dated, scoped cost reference; do not assert a final
   total while resources run.
4. Remove the unsupported field-wide publication-practice claim.
5. Narrow the linearity language to this classifier/feature set/dataset.
6. Distinguish cache fingerprints from full content hashes.
7. Shorten repeated retraction history and link to the lineage/changelog.
8. Add a reproducibility-tier table and the actual image access status.
9. Add accurate CI/license/Python badges only after branch/security setup.

### `HANDOFF.md`

Either remove from the public root or comprehensively regenerate it. Correct the
test arithmetic, document count, marker count, split decomposition, canonical
lineages, make-tables description, dates, cloud state, and parity evidence.

### `CHANGELOG.md`

Add the canonical sorted result correction, cloud-command issues when fixed, and
this final reconciliation. Cut `0.1.0` only with the tag. Ensure present-tense
numbers are canonical.

### `CITATION.cff`

Use `ring-participant-disjoint`; remove the practitioner-operating-point claim;
then add version/date only as part of the tagged release.

### `DATA_LICENSE.md` and `aml-platform/DATA_LICENSE.md`

Resolve the bundle classification, state applicable terms, clarify the opening
“no transaction data” sentence, add the decision to the release checklist, and
avoid telling downstream users to seek advice while the repository itself already
redistributes the same artifacts without reviewed classification.

### `SECURITY.md`

Provide a functioning private report route; distinguish live and target cloud
state; say “no allowed inbound traffic” only when verified; explain support scope.

### `docs/RESULT_LINEAGE.md`

Use it as input to a machine-readable registry rather than the sole source of
canonical status. Add explicit supersession edges for every old Large fit/eval and
bundle. Include exact full SHAs and artifact schema versions.

### `docs/RUNBOOK_cloud.md`

Repair and execute every command verbatim. Add `AML_GIT_SHA`, expected source SHA,
`TAG`/`IMAGE`, dataset verification, post-upload verification, cleanup, observed
deployment snapshot, and immutable image digest. Remove “VM verifies” until true.

### `docs/RELEASE_CHECKLIST.md`

Add legal review, generated-artifact cleanup, canonical-result reconciliation,
derived-script provenance, exact-runbook smoke test, cross-architecture claim
decision, and working vulnerability-report route. Correct the checked/open state
using actual evidence. Do not treat “stated” as equivalent to “acceptable.”

### `docs/LIMITATIONS.md`

Remove the stale “categoricals not ablated” sentence, unsupported cross-arch claim,
remaining definitive typology language, and any old 0.945 value presented as the
post-sort canonical mean without lineage qualification.

### `paper/RESULTS_hi_large.md`

Rebuild around `large_sorted_lgbm_s{0,1,2}`. Move the unsorted tables and sort-safe
claim to the retracted archive. Update abstract/summary, main tables, narrative,
claim-status table, limitations, and conclusion. Keep the old lineage only as
evidence of why ordering matters.

### `paper/RESULTS_split_inflation.md`

After rerunning from committed code, relabel 47/53 as a resampling-counterfactual
composition decomposition; remove causal leakage language; document independent
excluded-label validation, sensitivity choices, Monte Carlo uncertainty, and the
unrun Medium confirmation.

### `paper/RESULTS_typology.md`

Use “not demonstrated/stable across these rungs” consistently. Separate the
independence-null spread result from the plug-in replication comparison.

### `scripts/make_tables.py` and `scripts/release_facts.py`

Introduce typed claim references and canonical status. Make `passed`, `collected`,
and `skipped` distinct facts. Count only tracked/publication-scoped documents.
Fail if facts were generated by a stale/dirty tree when used for release.

### Derived-analysis scripts

Add a common artifact writer recording full SHA, code-tree/script hashes, dirty
state, CLI parameters, inputs, outputs, environment, RNG details, and timestamps.
Rerun the counterfactual and categorical artifacts after committing their code.

### `src/aml/eval/metrics.py`

Fix cache invalidation and test mutation. Route JSON logs through strict
serialization. Review stale docstrings such as “keyed by length.”

### `src/aml/manifest.py` and I/O fingerprinting

Record input fingerprint values and algorithms explicitly. Separate fast cache
fingerprints from full publication checksums. Consider full hashes for archived
outputs regardless of size.

### `Makefile`

Make `docker-build` inject a non-unknown SHA and install pytest from the hashed dev
lock. Add `dist-check`, Markdown, typed-result, strict-JSON, and full release-audit
targets. Ensure setup/release tools are explicitly declared.

### `pyproject.toml`

Migrate the deprecated license-file configuration, add release-tool configuration,
and keep package/changelog/CFF versions synchronized.

### `Dockerfile`

Use a builder/runtime split and non-editable wheel, remove build tools from runtime,
verify the DuckDB extension, capture package inventory, and remove stale comments.

### `infra/main.bicep` and `infra/README.md`

Pin the VM image, correct the header, remove/condition the dead ACR path, distinguish
NAT public egress from an attached VM public IP, and document incremental-deployment
drift. Consider putting the budget/auto-shutdown or deployment-stack lifecycle into
IaC rather than relying on manual state.

### Cloud shell scripts

Verify source and data hashes, align required parameters, quote paths consistently,
record OS/tool/image versions, and add a safe preflight that fails before resource-
intensive work.

### GitHub workflows/settings

Update all five JavaScript actions; include scripts in quality gates; pin tool
installers; show/allowlist image skips; remove cache warning; add artifact
attestation/SBOM at tag time; configure rulesets, security features, and working
private reporting; choose GHCR visibility; require `ci`, `gates`, and `image`.

### Repository tree

Remove `.coverage` and `build/`; ignore all generated build/coverage outputs; keep
the archive clearly labeled; make a conscious history decision without breaking
embedded provenance.

---

## Recommended closure order

1. **Resolve live spend immediately outside this audit:** decide whether to
   deallocate/delete or intentionally retain the Azure resources. This audit made
   no cloud changes.
2. **Freeze canonical science:** declare the sorted Large lineage canonical and
   update every current number, table, conclusion, and claim.
3. **Fix the result gate:** make superseded artifacts ineligible for current claims.
4. **Fix the stale metric cache** and add mutation regression tests.
5. **Repair and execute the cloud runbook verbatim**, including source/data hashes
   and required image identity.
6. **Rerun derived analyses from committed clean code** and correct the causal
   language.
7. **Resolve replay-bundle licensing** with a named decision and evidence.
8. **Remove tracked generated artifacts**, especially the coverage database and
   stale build tree.
9. **Reconcile HANDOFF, CFF, LIMITATIONS, SECURITY, changelog, and infrastructure
   documentation** against the same facts.
10. **Update dependencies/actions and harden release tooling**, then regenerate the
    image SBOM and vulnerability report from the final image.
11. **Run a clean-clone release rehearsal:** setup, lint all Python, tests with
    reasons, coverage, demo, nine replay checks, strict JSON, typed publication
    checks, links, Markdown, package/Twine, Bicep, ShellCheck/actionlint, full
    dataset pins, image build, anonymous/authenticated pull as chosen.
12. **Only then make the repository public**, enable security features/private
    reporting and branch rules, verify all required PR checks, sign `v0.1.0`, create
    the GitHub Release, attach immutable checksums/SBOM, and update CFF metadata.

---

## Publication acceptance criteria

The repository is ready when all of the following are true:

- [ ] Every current HI-Large number comes from the sorted canonical lineage.
- [ ] No current paper retains the disproved “sort-safe/bitwise” experiment.
- [ ] Every published number is bound to metric, unit, model, seed/aggregation,
      dataset, and canonical artifact.
- [ ] Cross-architecture claims either have two prediction hashes at the same
      committed code/data/config or are narrowed.
- [ ] All documented cloud commands run as written from a clean deployment.
- [ ] Source archive and every raw data file are verified by SHA-256 before use.
- [ ] In-place mutation cannot produce stale metric caches.
- [ ] Counterfactual and categorical artifacts were generated by code present at
      their recorded clean commit.
- [ ] Split-inflation wording matches what the counterfactual actually identifies.
- [ ] Replay-bundle licensing/permission is resolved and recorded.
- [ ] `.coverage` and `build/` are absent from Git and ignored.
- [ ] Root README, HANDOFF, CFF, SECURITY, limitations, papers, changelog, and
      runbook agree on results, test counts, terminology, cloud state, and cost.
- [ ] The live-resource decision is complete and the final cost is dated/scoped.
- [ ] Full six-file dataset verification has passed in the release rehearsal.
- [ ] Current non-archive Markdown passes the project's chosen lint policy.
- [ ] The final wheel, sdist, image, and full image SBOM are generated at the tag.
- [ ] Dependabot action updates are resolved; no forced deprecated runtime remains.
- [ ] GHCR access behavior matches the README.
- [ ] Private vulnerability reporting works.
- [ ] Branch rules require `ci`, `gates`, and `image` and block force-push/deletion.
- [ ] Secret scanning, push protection, dependency alerts, and code scanning are on
      as available after publication.
- [ ] A signed tag and GitHub Release exist with immutable digests.

---

## Bottom line

The V1/V2 remediation did not merely add polish; it found and corrected substantive
methodological and engineering defects. That is impressive. The project now has a
credible core and a compelling story about why evaluation controls matter.

But the final public artifact must embody that lesson. At this snapshot, a reader
can still be directed to superseded Large numbers by the main README, reproduce no
cloud run from the exact runbook, read a false source-integrity claim, invoke a
stale cache after mutation, and accept derived scientific evidence whose recorded
commit cannot contain its generator. Green CI currently certifies all of that.

**Do not publish this exact commit.** Close the P0 items, rerun the release rehearsal
from a clean clone, and audit the single final release commit—not the intent behind
it. Once those items are closed, the project will be genuinely strong enough to
publish rather than merely elaborate enough to look ready.
