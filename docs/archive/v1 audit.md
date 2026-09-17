# v1 audit

> Final pre-publication audit of `NirmalKumar31/aml-evaluation-harness` at commit
> `ab68300a8df143f8e7145867b596937d923fce95`, performed 2026-09-11 UTC.
>
> Audit mode: read-only. No existing source, test, documentation, data, configuration,
> infrastructure, cloud, or GitHub setting was changed. This report is the only file added.

## Executive verdict

**Status: not ready to make public yet.**

The repository has a stronger engineering core than most research projects: 241 tests pass,
Ruff is clean, the generated-data pipeline runs end to end, the package builds, the Bicep
template compiles, the current GitHub CI is green, raw benchmark data is not tracked, and the
limitations/retraction history is unusually candid.

The blockers are not cosmetic. The checked-in HI-Large runner defaults to the retracted
sampled configuration rather than the currently reported full-data, three-seed LightGBM run;
the ring-level metric implementation loses many-to-many ring membership at the account-day
aggregation boundary; several central conclusions are stronger than their evidence; multiple
documents declare themselves current sources of truth while describing mutually incompatible
AWS, Azure ML/Terraform, and Azure VM/Bicep systems; the large-run manifests record the code
commit as `unknown`; the NAT gateway is provisioned but not attached to the VM subnet; and the
history/publication-security decision is still explicitly open.

Publishing now would expose a credible project with avoidable contradictions and would invite
reviewers to reproduce the wrong large experiment. Fix the release blockers, rerun the affected
experiments, regenerate every result-bearing document, then perform one clean-clone release
candidate run before changing repository visibility.

## Severity and evidence conventions

- **P0 — release blocker:** fix or explicitly remove the affected claim/surface before public release.
- **P1 — high:** material correctness, reproducibility, safety, or credibility issue.
- **P2 — medium:** important hardening or documentation issue that need not block a clearly labelled preview.
- **P3 — polish:** discoverability, contributor experience, or presentation improvement.
- **Confirmed defect:** directly demonstrated from code, artifacts, commands, repository state, or live read-only state.
- **Methodological risk:** an assumption whose effect has not yet been measured; it must not be presented as a measured failure until sensitivity analysis is run.

## Release blockers

| ID | Severity | Finding | Evidence | Required disposition before publication |
|---|---|---|---|---|
| RB-01 | P0 | **The advertised HI-Large executable path reproduces the retracted run, not the published run.** | `aml-platform/scripts/run_hi_large.sh:12-13,62-64` defaults to `SAMPLE=0.7`, `MODEL=gbdt`, and seed 0. The current result is full-data LightGBM at seeds 0, 1, and 2. The runbook invokes the script without overriding those values. | Make the default command reproduce the current result exactly, use seed-specific output directories, and assert model, sample, seed set, input hashes, and destination. Preserve the old command only under an explicitly retracted/archive name. |
| RB-02 | P0 | **Ring attribution is structurally lossy.** | `aml-platform/src/aml/eval/metrics.py:45-52` reduces each `(day, account)` to one `ring_id` using `max`. An account-day can participate in more than one ring, so all but one membership are discarded; an unrelated high-scored transaction can also make a ring appear detected. | Represent alerts and ring membership separately: one account-day score table plus a many-to-many `(ring_id, day, account)` membership table. Define whether detection requires alerting a ring member-day, a ring transaction, or merely the same account-day. Rerun ring recall, null lift, typology results, and all derived claims. |
| RB-03 | P0 | **The ring-lift null is not yet a defensible baseline for the headline claim.** | `metrics.py:167-172` applies global account-day recall—including predominantly unringed positives—to ring sizes and assumes independent, equal-probability hits. HI-Large reports 87% of positive account-days without ring labels. Day-level budget constraints and score correlation are ignored. | Estimate the null on the ring-eligible population and preserve daily strata/budgets; use a permutation or simulation retaining day, ring size, and ranking structure. Report uncertainty. Until then, label `1.43` descriptive under a simplifying null, not evidence the model exploits ring structure. |
| RB-04 | P0 | **Central public claims overreach the evidence.** | `README.md:12-15` compares synthetic ground-truth precision with real alert-to-SAR filing conversion and concludes the benchmark is “near-saturated” and the number is “mostly” simulator property. The root warns about common benchmark inflation while the preregistered naïve-vs-ring-aware experiment has not run. | Remove the SAR comparison unless supported by authoritative citations and a like-for-like estimand. Reframe high linear separability as evidence that this feature/task setup is easy on one synthetic generator. Do not claim naïve splits inflate results until the preregistered experiment is executed. |
| RB-05 | P0 | **The repository has incompatible “current” sources of truth.** | `BUILD_PLAN.md` describes unbuilt AWS/Terraform. `AML_PROJECT_KNOWLEDGE.md:6,11` says zero lines exist and selects AWS. `Cloud/README.md` describes Azure ML, Synapse, Terraform/OIDC, 96 tests, and $0 spent. Current code uses one Azure VM and Bicep. Root `README.md:340-341` presents the stale files as current. | Choose one canonical current architecture/status document. Remove stale files from public navigation or move them under a clearly dated archive with a banner on every file. Update all test counts, costs, services, IaC, and status statements. |
| RB-06 | P0 | **Published large-run provenance cannot identify code or raw input content.** | All three `results_archive/gold/large_final_lgbm_s*/manifest.json` files record `code_git_sha: "unknown"`. Docker excludes `.git`, and `manifest.py` silently accepts unknown. The archive lacks a complete large-run raw/normalize/reconcile/feature manifest chain and immutable raw-data checksums. | Inject commit SHA and dirty/build identity at build time; fail a publication run if unknown. Record dataset version and SHA-256s, image digest, lock hash, stage code hash, parent run IDs, and output hashes. Archive a complete chain for every published seed. |
| RB-07 | P0 | **The declared Azure outbound design is not implemented.** | `infra/main.bicep:205-217` creates a NAT IP and gateway, but the subnet at lines 185-191 has no NAT association. The resources are billable but unused. Microsoft says NAT operates at subnet level and must be associated with it ([NAT overview](https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview), [management guidance](https://learn.microsoft.com/en-us/azure/nat-gateway/manage-nat-gateway)). | Attach NAT and make the subnet explicitly private, or delete NAT resources and document the actual outbound method. Add Bicep compile/lint and deployment validation/what-if to CI. |
| RB-08 | P0 | **Publication security/history decisions are unfinished.** | `HANDOFF.md:82,94-97` says a Kaggle token was pasted into chat and should be revoked, and ignored `Learning/` files remain in early commits. History contains 21 legacy learning/superseded-cloud paths plus machine-local and personal/academic author emails. No dedicated secret scanner was available. | Revoke/rotate the token regardless of Git findings. Run full-history Gitleaks/TruffleHog. Decide which historical notes and identities are acceptable; if not, rewrite all refs and re-scan the rewritten clone before going public. |
| RB-09 | P0 | **Licence presentation fails GitHub detection.** | GitHub reports `NOASSERTION`/“Other” because `LICENSE` appends a data note after canonical MIT text. The benchmark is separately CDLA-Sharing-1.0 on [Kaggle](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml) and in [IBM AML-Data](https://github.com/IBM/AML-Data). | Restore canonical MIT `LICENSE`; move data terms, attribution, exact source/version/checksums, redistribution boundaries, and citation into `DATA_LICENSE.md` or a data card. Avoid uncited legal conclusions about derived statistics. |
| RB-10 | P0 | **Result documents contain known stale statements.** | `paper/RESULTS_hi_large.md:202` says lift 1.28 although its measured table says 1.43. `paper/RESULTS_metric_stability.md:98` says 12 ordering permutations while code uses 4. `paper/RESULTS_typology.md:24,51` asserts non-replication/easiest typology despite uninformative n=8 uncertainty. `docs/FEATURE_SPEC_v1.md:311` still declares fixed `txn_id` behavior a blocker. | Correct or archive every stale result/spec. Regenerate narrative from final artifacts after metric fixes, using a claim-by-claim review rather than a numeric token scan. |

## Verification performed

All commands were run without changing tracked project files. Cache-writing for tests and lint
was disabled where applicable.

| Check | Result | Interpretation |
|---|---|---|
| Git state before report | Clean; `HEAD == origin/main` at `ab68300a` | Audit covered the remote tip. |
| Git object integrity | `git fsck --full --no-dangling` passed | No object corruption detected. |
| Test suite | **241 passed, 17 skipped** | Green, but not the “243 tests” claimed twice in README. There are 258 collected cases. The 17 real-data contracts skip because built bronze/reconcile inputs are absent. |
| Ruff | `ruff check --no-cache src/ tests/` passed | Current configured lint rules pass. |
| Dependency consistency | `pip check` passed | No declared installed conflicts; this is not a vulnerability audit. |
| Generated demo | Passed all six stages | Composition works; it also exposed a stale row-count disclaimer and non-standard JSON `NaN`. |
| Clean-snapshot wheel | `aml_platform-0.1.0-py3-none-any.whl` built with normal PEP 517 isolation | Buildable when the environment can fetch setuptools. Offline `--no-build-isolation` failed because setuptools was absent. |
| Bicep compile | Passed | Syntax/type compilation passes; semantic design issues remain. |
| Shell syntax | `bash -n scripts/*.sh` passed | Syntax only; ShellCheck was unavailable. |
| Markdown links | 25 tracked files, 0 missing relative targets | External links and heading anchors were not validated. |
| Tracked JSON | 121 files, 0 strict-parse failures | Committed JSON is strict; the generated demo manifest was not. |
| Numeric gate as CI runs it | Passed: 82 values, 3 documents, 15 exemptions, 24 result sets | A narrow allow-list, not a repository-wide guarantee. |
| Numeric gate over all Markdown | **Failed: 26 unsupported values across 25 docs; 58 exemptions** | 17 in `AML_PROJECT_KNOWLEDGE.md`, one in `Cloud/07-working-agreement.md`, one in `HANDOFF.md`, seven in the retracted paper. |
| GitHub Actions | Latest `ci` at `ab68300a` passed; image at prior source commit `ab5b2339` passed | Image did not run at HEAD because the last change was outside its path filter. |
| GitHub settings | Private, unprotected `main`, no tags/releases, licence undetected, no topics | Not configured as a polished public release. |
| Live Azure check | `aml-vm` was **running** on `Standard_E4ds_v7` in `eastus` | Ongoing spend remains; no cloud state was changed. |

### Checks not completed

Docker was unavailable locally, so the image was not rebuilt in this audit; the latest GitHub
image workflow is the evidence used. ShellCheck, Actionlint, Markdownlint, Codespell, Gitleaks,
Trivy, and a Python vulnerability scanner were not installed. There is no coverage report,
static type checker, SBOM, image-signature verification, or cross-version Python matrix. Thus,
“green” does not certify security, coverage, shell portability, or supply-chain integrity.

## Detailed findings

### 1. Evaluation and statistical validity

#### EV-01 — P0, confirmed: account-day aggregation discards ring membership

`to_account_days()` duplicates transactions to sender and receiver, then groups by `(day,
account)` and uses `ring_id=max`. This is invalid when one account-day touches multiple rings. It
can undercount rings, misassign typology, and credit a ring when the account-day's maximum score
came from another transaction. Keep alert scoring and ring membership in separate relations and
join only at the explicitly defined detection event.

#### EV-02 — P1, methodological risk: tied daily scores are resolved by input order

`recall_at_budget()`, `ring_recall()`, bootstrap preparation, and typology evaluation use
`rank(method="first")`. Tree models commonly produce repeated leaf scores; selection at the daily
budget boundary can therefore depend on account-code/group order. Those codes are created by
`row_number() over()` without semantic ordering in `train.py:390-396`. Exact replay on two
architectures does not make this tie policy statistically meaningful.

Add a stable semantic secondary key and publish the policy. Report ties at every budget boundary
and optimistic/pessimistic or randomized tie sensitivity. The current effect is unquantified
because archived predictions are absent.

#### EV-03 — P0, methodological risk: the ring null uses the wrong reference population

The null uses overall account-day recall for all ring-member opportunities. On HI-Large, most
positive account-days lack rings, so overall recall need not be the hit probability for
ring-labelled account-days. It also treats all member-days as independent and exchangeable across
days although ranking occurs separately under a daily budget. Use a stratified permutation or
simulation null, state its estimand, and include uncertainty.

#### EV-04 — P1, confirmed limitation: confidence intervals are conditional and anti-conservative

The bootstrap holds the fitted ranking fixed, resamples only positive outcome clusters, treats
unringed account clusters as independent, and excludes fitting, split, generator, negative-pool,
and ranking uncertainty. The code documents a bootstrap SE about four times smaller than
seed-to-seed SD on one metric. Report these only as conditional outcome-resampling intervals. Do
not treat cross-architecture equality of identical bootstrap draws as additional validity evidence.

#### EV-05 — P1, confirmed: the legacy split loader still samples the test set

The primary `train()` path was corrected to thin training only, but `load_split()` at
`train.py:417-462` appends the same sampling predicate to train and test. `model-stability` and
`leak-sweep` call this loader. Any such experiment with `sample < 1` silently changes the
evaluation population and budget competition—the defect the comments say was fixed. Published
sample-1 experiments are unaffected. Centralize membership logic and test every caller.

#### EV-06 — P1, methodological risk: hashed categories impose arbitrary geometry

Payment format and currency are encoded as `DuckDB hash(value) % 1000` and passed as numeric
features. Logistic regression treats arbitrary codes as ordered/linear; histogram trees split
their arbitrary order; collisions are possible and unchecked. This weakens the interpretation of
the “linear baseline” and model lift. Use fixed vocabularies with an unknown category and one-hot
or native categorical treatment, then rerun comparisons.

Also parameterize `features/online.py:67`; embedding text in `SELECT hash('...')` breaks on quotes
and creates an avoidable SQL-injection surface for serving inputs.

#### EV-07 — P1, methodological risk: alert unit and budget are asserted, not validated

The code says `(account, calendar_day)` is what an investigator “actually opens.” Real systems may
operate on customer, scenario alert, event, or case units, and budget 50 is workflow-specific.
Treat this as a proxy unless cited, and add sensitivity across units, budgets, and case-merging
windows.

#### EV-08 — P1, confirmed wording issue: “entity-disjoint” is narrower than implied

Disjointness is enforced for ring-participating accounts across assigned rings. Pre-cut clean
history for a later test account can be present in training, and unringed positive account-days
bypass ring discipline. The manifest describes “handling A”; headlines should say
“ring-participant-disjoint temporal split” or define scope adjacent to every result.

#### EV-09 — P0, confirmed evidence gap: the split-inflation thesis is preregistered only

`paper/PREREGISTRATION_split_inflation.md` is a draft/pending experiment. Until same-path naïve and
ring-aware protocols run, the project can say leakage is plausible and the harness prevents it;
it cannot say common benchmark results are inflated. Execute the analysis or remove the
warning-level claim.

#### EV-10 — P1, confirmed scope limitation: one generator, one split; seeds are not replicates

Primary claims come from one synthetic generator and one selected temporal cut. Seeds reuse the
same transactions and labels. The limitations acknowledge this, but “mostly a property of the
simulator” and cross-rung typology conclusions outrun it. Add independent datasets/generator draws
or narrow every conclusion to this dataset and configuration.

#### EV-11 — P1, confirmed: typology conclusions contradict their uncertainty

With eight typologies, Spearman rho 0.286 and an approximate interval from about -0.55 to +0.84
are uninformative about ordering. `RESULTS_typology.md` nevertheless says ordering “does not
replicate,” GATHER-SCATTER being easiest “holds,” and a 2–3x spread is genuine. Replace these with
descriptive rung-specific estimates. Do not designate easiest/hardest without an appropriate
repeated-measures test and multiplicity-aware intervals.

#### EV-12 — P1, confirmed design weakness: leak placebo does not preserve conditional marginals

The leak sweep globally permutes the feature, then splits. It preserves only the global marginal,
not train/test, time, entity, or label-conditional structure; this can create placebo distribution
shift. Left merges assert one-to-one cardinality but not complete transaction-ID coverage, so
missing IDs become model-consumable nulls. Use a permutation matched to the null hypothesis and
fail on missing/extra keys. Emit p-values and sign-test results as artifacts instead of manual
prose exemptions.

### 2. Reproducibility, artifacts, and caching

#### RP-01 — P0, confirmed: large manifests record `unknown` code provenance

Docker installs Git because comments say it is required for provenance, but `.dockerignore`
excludes `.git`; the source-tar/VM flow likewise lacks repository metadata. Seven archived
manifests have `code_git_sha=unknown`, including current HI-Large fits and split. Pass immutable
build arguments/OCI labels into every manifest and reject unknown provenance for release results.

#### RP-02 — P1, confirmed: local directory fingerprints can return stale cache hits

Local directories are fingerprinted from relative path, size, and integer-second mtime. A same-size
rewrite within one second can retain identity. Use cached per-file content hashes, suitable Parquet
identities, or immutable run-keyed input directories. The statement that `(size, mtime)` is “fine”
is too strong.

#### RP-03 — P1, confirmed: cache hits do not verify outputs

`load_cached()` checks only manifest `run_key` and `status=ok`; it does not confirm required
Parquet/model/score outputs exist or match hashes. Deleted or corrupted outputs with an intact
manifest produce a successful skip. Store and verify an output inventory with size, hash, and
schema before accepting a hit.

#### RP-04 — P1, confirmed: stage code hashes omit transitive dependencies

Each cache key hashes only explicitly passed modules. Training hashes `train.py` and model config,
not evaluation metrics, manifest, I/O, or feature schema; feature building hashes only its own
module. A shared change can leave stale cached results. Hash a declared dependency set, installed
wheel/image digest, or deterministic source-tree subset, and persist it visibly rather than only
inside a 16-character run key.

#### RP-05 — P1, confirmed: output replacement is neither clean nor atomic

Stages use DuckDB `OVERWRITE_OR_IGNORE` into existing partitioned destinations. If a new run emits
fewer partitions, old files can survive. Manifest and remote JSON writes are direct rather than
atomic commits. Write to fresh run-keyed directories, validate, then atomically publish a pointer;
never mix generations in one prefix.

#### RP-06 — P1, confirmed: remote directory failures are suppressed

`io.ensure_dir()` suppresses every exception from URI `makedirs`, including authentication,
authorization, and invalid-path failures, despite the fail-loud philosophy. Ignore only documented
already-exists/unsupported cases; propagate all others with backend and path context.

#### RP-07 — P2, confirmed wording issue: ETag is not universally content identity

The remote fingerprint docstring promises an ETag changes if and only if content changes. ETag
semantics are provider- and operation-specific and often identify an object version rather than a
content hash. Record provider, version ID, ETag, size, and content MD5/SHA where available; do not
equate a generic ETag with a cryptographic digest.

#### RP-08 — P1, confirmed: dataset acquisition is mutable and unchecked

The large script downloads current Kaggle paths without a pinned dataset version or expected
SHA-256. Upstream changes can silently define a new experiment. Publish the exact dataset version,
update date, and both file hashes; fail before normalization on mismatch.

#### RP-09 — P1, confirmed: manifests alone cannot audit/recompute results

The archive omits predictions and model artifacts while retaining only hashes. Reviewers cannot
check ties, recompute metrics after a fix, or compare metric implementations without rerunning
180M rows. Archive compressed `(txn_id, score)` outputs or publish versioned access under the data
terms, plus schemas/checksums. If redistribution is disallowed, state that and retain a verifiable
access procedure.

#### RP-10 — P2, confirmed: setup and CI do not use one locked environment

`make setup` installs unpinned `.[dev,azure]`; CI first installs `requirements.lock` then ranged
extras, allowing omitted pytest/Ruff to float; the image test installs latest pytest at runtime.
The lock has exact versions but no hashes and comes from `pip list`, including unrelated tooling
while excluding test tools. Use resolver-generated, hashed runtime and dev locks with
`--require-hashes`. Test the advertised Python range or narrow it to supported versions.

### 3. Cloud, operations, and supply chain

#### OP-01 — P0, confirmed: `run_hi_large.sh` points to the wrong experiment

This is RB-01 and should be fixed first. The script explains why 70% sklearn GBDT was once
necessary, but the project switched to full-data LightGBM. A publication runbook must be
executable documentation, not historical narrative.

#### OP-02 — P1, confirmed: multi-seed cloud runs overwrite one another

`run_cloud.sh:54-57` loops seeds into the same `/scratch/out/gold/models` destination. Model,
score, checkpoint, and manifest names are overwritten; only the final manifest remains for upload.
Use a seed/run-key directory per fit and publish an index manifest after all seeds complete.

#### OP-03 — P1, confirmed: registry and execution paths diverge

Bicep provisions ACR and `AcrPull`; GitHub Actions publishes GHCR; VM provisioning builds a local
image from a blob tarball; scripts use local tags (`aml:v5` / `aml:latest`). The paid ACR may be
unused, and no one artifact digest connects CI to the measured cloud run. Select one immutable
registry/digest flow, then remove unused resources and permissions.

#### OP-04 — P0, confirmed safety defect: “idempotent” provisioning can format the wrong disk

`provision_vm.sh:23-27` chooses the first roughly 200 GB block device by size and unconditionally
runs `mkfs.ext4 -F` whenever `/mnt/scratch` is not mounted. A rerun after unmount can destroy data,
and a similarly sized disk can be selected. The 1 TB path checks `blkid` but still identifies by
size. Resolve Azure LUN/resource-disk identity, check filesystem and mount UUID, and require an
explicit empty-device condition before formatting.

#### OP-05 — P1, confirmed supply-chain gaps

Provisioning executes an unpinned `curl | bash` Azure CLI installer and extracts an unsigned,
unchecked source tar from blob. The Docker base is pinned only to a mutable tag, the Ubuntu image
uses `version: latest`, DuckDB downloads an extension during build, and GitHub Actions use mutable
major tags rather than commit SHAs. Pin digests/versions, verify source and extension hashes or
signatures, generate an SBOM, scan dependencies/image, and sign the release image.

#### OP-06 — P1, confirmed cost/governance gap

The VM was running during the audit, and `HANDOFF.md` estimates about $0.40/hour. There is no
automatic shutdown, TTL enforcement, budget resource, or scheduled orphan check. Before release,
decide whether to delete or deliberately retain it, then remove exact account, resource,
subscription, and personal-email details from public handoff material. Keep operational identifiers
in a separate private note if needed.

#### OP-07 — P1, confirmed cost-story contradiction

README says the verified cloud run cost under $5; the current runbook estimates roughly $21 for a
complete sequence; the handoff says roughly $30 spent and live burn continues; old cloud docs say
$0 or give much larger forecasts. These may be different scopes, but no scope is stated. Publish
one dated table separating medium parity, failed attempts, HI-Large final, idle resources, and
total project spend.

#### OP-08 — P2, confirmed: infrastructure validation is outside CI

Bicep compiles manually, but CI does not build/lint it, validate a deployment, or check drift.
Shell scripts receive syntax parsing only. Add Bicep build/lint, safe validation/what-if,
ShellCheck, Actionlint, timeouts, and concurrency cancellation. Declare top-level least-privilege
workflow permissions; only the image job currently does so.

#### OP-09 — P2, confirmed release-operability gap

GHCR packages are private by default even if the repository becomes public, as the workflow notes.
Decide whether a public image is part of the release and test anonymous pull. Publish version and
source-SHA/digest tags, not only floating `latest`.

### 4. Documentation and claim governance

#### DOC-01 — P0, confirmed: global artifact-generation claim is false

`README.md:53-54` says every table cell is emitted by `make_tables.py` and nothing is typed by hand.
The script prints a generic table but does not rewrite README tables. Its checker looks only for
`0.xxxx`/`0.xxxxx` tokens and asks whether each text value occurs anywhere in any JSON artifact.
It cannot bind a value to metric, unit, rung, model, seed, or source; ignores integers,
percentages, scientific notation, most rounded formats, and wrong-label reuse; silently skips
malformed artifacts; and permits manual `<!-- derived -->` exemptions. CI checks only three docs.

Generate document regions directly from a typed results specification, or validate each cell
against an explicit artifact JSONPath plus unit/rung/model/fit identity. Fail on malformed,
failed-status, or unknown-provenance artifacts. Change the README wording until generation is real.

#### DOC-02 — P0, confirmed: status documents contradict one another

Archive or rewrite `BUILD_PLAN.md`, `AML_PROJECT_KNOWLEDGE.md`, and root `Cloud/`. Their “source of
truth/current” labels make them active misinformation, not harmless history. Preserve decision
history only with dates and unmistakable superseded banners.

#### DOC-03 — P1, confirmed: test counts are wrong

`README.md:194,211` says 243 tests. This audit collected 258: 241 passed and 17 skipped. Use a
CI-generated test summary and disclose why real-data contracts skip in public CI.

#### DOC-04 — P1, confirmed: metric-stability document is stale

`RESULTS_metric_stability.md` says the curve averages 12 random orderings; code sets
`N_CURVE_ORDERINGS=4`. It also states an eight-seed reporting rule while HI-Large has three seeds.
Meet the rule or define a separately justified large-rung exception before seeing results.

#### DOC-05 — P1, confirmed: result narrative mixes old and new ring lift

`RESULTS_hi_large.md` correctly tabulates mean lift about 1.43 and explains its correction, then
its claim table says 1.28. The metrics docstring also preserves 1.28 examples. Old values belong
only in a correction history; the current claim needs one value and one artifact path.

#### DOC-06 — P1, confirmed: stale blocker/spec language

`FEATURE_SPEC_v1.md` says `txn_id` is non-deterministic “today” and marks it a blocker, although
normalize now assigns/carries it. A repro-test docstring retains an old “ordering reverses” story
that current docs reject. Separate historical incidents from current specification and assertions.

#### DOC-07 — P1, confirmed: external factual claims lack sources

README contains uncited claims about alert-to-SAR conversion, investigator review units,
cross-bank observability, publication practice, and production transaction monitoring. Add primary
sources and label inference as inference. Add formal IBM paper citation/BibTeX and `CITATION.cff`.

#### DOC-08 — P2, confirmed: project identity is inconsistent

The repository is `aml-evaluation-harness`, package/subdirectory `aml-platform`, root title
“Alert-Budget-Aware Evaluation,” and package description “DriftGraph - AML transaction monitoring
platform.” Pick one name and accurately call it a research/evaluation harness. Complete package
metadata: README, licence expression, authors, URLs, classifiers, and version policy.

#### DOC-09 — P2, confirmed: README is candid but overloaded

The 347-line README foregrounds repeated forensic corrections. The honesty is valuable, but a new
reader traverses a postmortem before architecture, scope, and the supported claim. Keep a concise
overview/results/quick-start README; move incident history to engineering notes; add a small
architecture/dataflow figure and sample artifact/output.

#### DOC-10 — P2, confirmed: no formal public-project governance

There is no `CONTRIBUTING.md`, `SECURITY.md`, code of conduct, issue/PR templates, release notes,
tagged release, changelog, dependency-update configuration, or support boundary. At minimum add
testing/contribution instructions, a security-reporting route, and a tagged release with checksums.

### 5. Code and interface robustness

#### CQ-01 — P1, confirmed: sample values are not validated

`_sample_clause()` treats values `>=1` as full data, converts lower values to an integer threshold,
and does not reject zero, negatives, NaN, or values above one. Validate `0 < sample <= 1` at CLI
and function boundaries and test invalid cases.

#### CQ-02 — P1, confirmed: SQL interpolation is broader than necessary

DuckDB statements interpolate paths, dates, memory limits, temp directories, and online category
text. Quotes can break SQL and untrusted values can alter it. Centralize safe literal/identifier
quoting or use supported parameters/table functions.

#### CQ-03 — P2, confirmed: evaluator input validation is incomplete

`evaluate()` does not explicitly check score length, finite scores, required columns, or both label
classes before sklearn metrics. A one-class slice or malformed score fails indirectly. Validate
once with domain-specific errors and define missing-class behavior.

#### CQ-04 — P1, confirmed: manifest JSON permits non-standard constants

`io.write_json()` uses Python's default `allow_nan=True`. The supported demo with bootstrap 0
produced `ci_lo: NaN` and `ci_hi: NaN`, which strict JSON parsers reject. Use `allow_nan=False`,
normalize non-finite values to `null`, and test strict JSON over every CLI path.

#### CQ-05 — P2, confirmed: demo disclaimer is stale

The demo generated 3,116 rows but printed “This is ~900 rows of uniform noise.” It also said the
model cannot detect anything while the planted construction yielded high scores. Generate the row
count and say only that the demo verifies composition, not scientific performance.

#### CQ-06 — P2, confirmed: malformed artifacts can disappear from publication checks

`make_tables.py::_load()` silently skips malformed/unreadable JSON. That may suit historical
browsing but makes a publication gate fail-open. The release checker must fail on every malformed
artifact in scope, `status != ok`, and missing provenance.

#### CQ-07 — P2, test gap: identified defects lack invariant-level tests

Add tests for multi-ring account-days, unrelated high-score transactions on ring-member days, tied
budget-boundary scores, null population/day stratification, `load_split(sample<1)` test identity,
invalid samples, categorical quotes/collisions, deleted/corrupt cached outputs, transitive code
changes, same-size/same-second rewrites, stale partitions, strict JSON, unknown release SHA, and safe
repeated VM provisioning. Current green tests do not cover these paths.

## Repository and publication hygiene

- The tracked footprint is about 4.6 MB; the benchmark CSV/Parquet corpus is not tracked. This is
  good. The largest reachable blobs are archived drift manifests followed by historical learning
  documents, not raw benchmark/customer data.
- All 25 tracked Markdown files had valid local relative targets. Automate external-link and anchor
  checking as a release gate.
- The repository is private, `main` is unprotected, and there are no tags, releases, or topics.
  Protect `main`, require CI/image/release gates, and create a signed/tagged release candidate.
- `HANDOFF.md` is an internal operational handoff, not a safe public landing document. It includes
  live status, exact cloud resource names, subscription/personal-account description, cost burn,
  and credential/history warnings. Sanitize it or keep it out of the public tree.
- Ignored files remain visible after a repository visibility change when they exist in history. A
  `.gitignore` entry is not a privacy control.
- No high-confidence credential was observed in the targeted regex/history review, but this is not
  equivalent to a dedicated full-history secret scan. The documented pasted token must still be
  rotated.

## What is already strong and should be preserved

- The working tree was clean, compact, and free of tracked benchmark data before this report.
- The tests are broad for a research harness: leakage, parity, reproducibility, storage, drift,
  contract, and regression categories are represented.
- The generated demo exercises real stages rather than a disconnected toy API.
- The project distinguishes transaction, account-day, and ring units in many current outputs;
  preserve this discipline while repairing ring membership.
- Archived manifests contain detailed configuration, row counts, metrics, environment, wall time,
  model hash, and prediction hash. Extend this design rather than replacing it.
- The retracted HI-Large result is retained and explained, and `LIMITATIONS.md` admits many hard
  caveats. Keep the audit trail but separate historical corrections from current claims.
- Managed identity, disabled shared-key access, no inbound VM rules, one-resource-group teardown,
  non-root containers, in-image tests, and cross-architecture prediction hashes are sound choices
  when wired into one coherent release path.
- The normal clean-snapshot wheel build, generated demo, lint, Bicep compile, Git integrity, local
  link scan, and current CI all passed. The foundation is viable.

## Required remediation order

1. **Freeze publication state.** Revoke the Kaggle token; stop/delete or explicitly retain live
   Azure resources; sanitize handoff content; run full-history secret scanning; decide whether to
   rewrite history and author metadata.
2. **Fix estimands first.** Replace lossy ring attribution, define detection precisely, design a
   stratified ring null, specify tie handling, and add invariant tests. Do not regenerate results
   until these definitions are frozen.
3. **Fix executable reproducibility.** Correct HI-Large defaults, isolate every seed, pin raw inputs
   and image/source identity, complete lineage, and make cache/output commits verifiable and atomic.
4. **Repair cloud safety.** Attach or remove NAT, make provisioning non-destructive, converge ACR/
   GHCR/local-image flows, pin supply-chain inputs, and add infra/shell gates.
5. **Rerun affected experiments.** At minimum rerun HI-Medium primary/ensemble, HI-Large three seeds,
   typology, leak sweep, and every result affected by category encoding, ring membership, tie policy,
   or null changes. Execute the preregistered split-inflation experiment or remove that thesis.
6. **Generate claims from artifacts.** Use a typed result specification that writes document regions
   and validates artifact identity, unit, source, status, and provenance. Eliminate manual-value
   exemptions from headline results.
7. **Consolidate documentation.** One architecture, one status, one cost scope, one project name,
   current counts, citations, data card/licence separation, and unmistakably archived old designs.
8. **Cut a release candidate from a clean clone.** Use documented commands; fetch verified data; run
   lint, all non-skipped tests, real-data contracts, demo, full publication checker, wheel,
   container, vulnerability/image scans, Bicep validation, and shell/workflow lint. Confirm a clean
   tree and known commit/image/input identities in every release manifest.
9. **Configure GitHub, then publish.** Canonical MIT detection, topics/description/homepage,
   protected `main`, required checks, security policy, dependency updates, public-image decision,
   signed tag, release notes, checksums, and citation metadata.

## Go/no-go acceptance checklist

The repository is ready to make public only when every item is true:

- [ ] The default HI-Large command reproduces full-data LightGBM seeds 0/1/2 into isolated outputs.
- [ ] Ring membership is many-to-many, detection is defined, and ring/typology results are rerun.
- [ ] Tie counts/sensitivity and a day/population-preserving ring null are published.
- [ ] The split-inflation experiment is complete, or claims of measured inflation are removed.
- [ ] SAR/production comparisons are cited and estimand-compatible, or removed.
- [ ] Current result/spec documents agree with code/artifacts; stale architecture docs are archived.
- [ ] The publication checker validates explicit artifact/metric/unit/rung/model/fit mappings and all current docs.
- [ ] Publication manifests contain known commit, dirty state, image digest, raw hashes, lock hash, lineage, and output checksums.
- [ ] Cache hits verify outputs; outputs are generation-isolated and committed atomically.
- [ ] NAT/outbound design matches Bicep; provisioning cannot format a non-empty or wrong disk.
- [ ] Credential rotation and full-history secret scanning are complete; history exposure is intentional.
- [ ] The live Azure decision is complete; public docs disclose no unnecessary operational identifiers.
- [ ] Canonical MIT is detected; CDLA data card/licence and citation are separate and complete.
- [ ] A clean-clone candidate passes code, real-data, doc, package, container, infra, shell, security, and link gates.
- [ ] Branch protection, required checks, release/tag, security policy, and public-package behavior are configured.

## Final assessment

This is worth publishing after remediation. It demonstrates real engineering judgment, unusually
good failure documentation, and a valuable budget-aware evaluation perspective. Its present
weakness is that its strongest branding—reproducibility, fail-closed provenance, and measurement
discipline—is exactly where the remaining defects land. That makes them visible and fixable, but
also makes them release blockers rather than footnotes.

**Current decision: NO-GO for public visibility.** Resolve RB-01 through RB-10, rerun affected
results, and execute the clean-clone checklist. P2/P3 items may follow a clearly labelled preview,
but statistical estimands, the large-run command, provenance, documentation truthfulness,
history/credential review, licence detection, and cloud safety should not be deferred.
