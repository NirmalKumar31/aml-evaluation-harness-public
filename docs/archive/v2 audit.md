# V2 publication-readiness audit

**Repository:** `NirmalKumar31/aml-evaluation-harness`
**Audited revision:** `52632868673d69af46b09b13c6bc654932693850` (`main`)
**Audit snapshot:** 2026-09-13 18:47 UTC
**Decision:** **Not ready to make public or tag as v0.1.0**
**Required re-audit:** yes, after the blockers and high-severity findings are resolved

> This is a read-only audit. No source, result, infrastructure, documentation,
> workflow, or GitHub/Azure setting was changed. This report is the only file
> added by the audit. `aml-platform/results_archive/derived/cost.json` was already
> modified when the audit began and was left untouched.

## 1. Executive verdict

This is a substantially stronger project than the average public ML portfolio
repository. Its central idea—evaluating AML systems at a daily investigator
budget, on an explicitly defined alert unit, against attainable ceilings and
ring-aware nulls—is useful, memorable, and defensible. The repository also has
real scale, thoughtful negative results, extensive tests, locked environments,
replay bundles, structured manifests, and an end-to-end demo.

It nevertheless should **not** be published in its current state. Five release
blockers remain:

1. **The documented deterministic-training claim is false at production scale.**
   Training rows are read without a stable order. Both supported histogram
   learners construct bins from a 200,000-row sample at this scale, so a row
   permutation changes bin boundaries and fitted predictions. The regression
   test that is cited as proof uses only 20,000 rows and never crosses the
   sampling threshold. This affects the current HI-Large LightGBM results and
   the repository's core reproducibility claim.
2. **“97% of the split uplift is prevalence arithmetic” is not established by
   the implemented analysis.** Average precision does not generally scale
   linearly with prevalence, the removed positives are demonstrably non-random,
   and the reported 97% is not even the share of uplift under the code's own
   multiplicative decomposition. This conclusion must be re-analysed or
   retracted.
3. **The replay-bundle licensing description does not match the files.** The
   repository says it publishes only aggregates, with no account identifiers or
   transaction records, while bundles contain row-level scored/labeled
   account-days, encoded account identifiers, ring memberships, and ring
   transaction endpoint mappings. Whether those files are license-defined
   “Results” or redistributed/Enhanced Data requires a proper license review.
4. **There is no single canonical result set.** The README reports the older
   Medium GBDT result (`precision@50 = 0.793981`), while a newer committed
   `models3_Medium` / `eval3_Medium` run reports `0.880787` for nominally the
   same model configuration. The newer AP is `0.300478` versus `0.282400`.
   Publishing both without an explicit lineage and selection rule makes the
   headline result ambiguous.
5. **The live Azure deployment contradicts the documented security and cost
   architecture.** At audit time the VM was running, its NIC had a public IP,
   and its NSG allowed inbound TCP/22 from any source. The checked-in Bicep and
   runbook repeatedly claim no public IP, no inbound rule, and no SSH. There was
   no cost budget; the live-cost snapshot had already risen from the documented
   51.0 hours / $27.90 to 91.81 hours / $50.23 list price. The checked-in Bicep
   is not the deployed state.

These are correctable. Once corrected, the project can be impressive precisely
because it does more than train a model: it demonstrates how seemingly good AML
benchmark results change when the unit, split, budget, null, and provenance are
made explicit. Correctness should be fixed before visual polish or promotion.

## 2. Release gates

| Gate | Status | Publication requirement |
|---|---:|---|
| Scientific claims | **Fail** | Rework the 97% split-inflation conclusion and narrow the typology/null claims |
| Deterministic training | **Fail** | Establish stable training semantics at >200k rows for both sklearn and LightGBM; regenerate affected results |
| Canonical results | **Fail** | Select one current result lineage and explain/archive superseded lineages |
| Data licensing | **Fail** | Review replay bundles against CDLA-Sharing-1.0 and make content/notice/license statements accurate |
| Cloud security and truthfulness | **Fail** | Reconcile or remove the live deployment; validate IaC from a clean deployment; update cost and provenance evidence |
| Tests | Pass with qualification | 277 passed, 17 data-dependent skips; skipped contracts still need a full-data release run |
| Dependency audit | Pass at snapshot | `pip-audit` found no known vulnerabilities in the pinned runtime lock |
| Static Python quality | Pass with qualification | Ruff passes, but scripts are omitted from CI's Ruff target and no SAST gate exists |
| Shell/Bicep syntax | Pass with qualification | Shell syntax and Bicep compilation pass; functional cloud defects remain |
| Reproducibility artifacts | Mixed | Six replay bundles reproduce their source manifests, but training provenance and data acquisition are incomplete |
| Packaging | **Fail** | Built artifacts pass Twine, but omit the root license/data-license context and contain broken parent-relative README links |
| Documentation correctness | **Fail** | Numerous stale counts, contradictory claims, broken Markdown table rows, and false release metadata remain |
| GitHub governance/security | **Fail** | No branch protection, native security features disabled, no PR image gate, no release/tag, and GHCR remains private |

## 3. What was inspected and verified

The audit covered all 311 tracked files, Git history and metadata, the GitHub
repository/workflows/package settings, the live Azure resource group, code,
tests, documentation, paper/results, manifests, replay bundles, package builds,
locks, container/IaC definitions, scripts, and publication presentation.

Fresh checks included:

- `pytest -q -rs -p no:cacheprovider`: **277 passed, 17 skipped**.
- Isolated coverage run: **75% total**.
- `ruff check src tests scripts`: pass. The committed CI checks only `src/` and
  `tests/`.
- `pip check`: pass.
- `pip-audit -r requirements.lock --no-deps`: no known vulnerabilities.
- Bandit over source and scripts: no high-severity findings; 50 medium and 7 low
  findings, dominated by dynamically formatted DuckDB SQL.
- `bash -n scripts/*.sh`: pass.
- `az bicep build --file infra/main.bicep`: pass.
- Clean isolated `aml demo`: all six stages completed in about five seconds.
- All 165 tracked JSON files parse strictly.
- All six replay bundles reproduce their referenced source manifests with zero
  metric mismatches.
- Five locally present raw files match the committed SHA-256 pin. The missing
  HI-Large transaction file was not checked and the verifier still exited zero.
- Clean sdist and wheel build: pass; `twine check`: pass.
- `CITATION.cff` schema validation: pass.
- Local Markdown link scan: 76 links, no missing local target. External targets
  are not fetched by that checker.
- Publication-number checker on its eight configured documents: 195 numeric
  tokens, 51 result sets, no reported unsupported values. Its semantic limits
  are discussed below.
- Strict Markdown lint: **2,202 findings across 28 files**.
- GitHub's current `ci`, `gates`, and `image` runs at HEAD: green.
- Full-history Gitleaks in GitHub Actions: green, with no detected leak.
- Read-only Azure inspection and Bicep `what-if` comparison against the live
  resource group.
- Direct >200k-row permutation experiments for sklearn histogram binning and
  LightGBM fitting.

The audit does **not** claim to have rerun the 32M/180M pipelines from raw data;
that is exactly the release evidence that remains necessary after fixing the
determinism and provenance issues.

## 4. Blockers in detail

### B1 — Training is row-order-dependent at the actual scale

**Severity:** blocker
**Affected claims:** reproducibility, deterministic outputs, HI-Large methods,
cloud parity, canonical metrics

``load_train_xy`` deliberately
executes its training query without `ORDER BY`. Its comment says this is safe
because `HistGradientBoostingClassifier` is row-order-independent and cites
``test_gbdt_is_row_order_independent``
as bitwise proof. That test uses `n = 20_000`.

The proof does not exercise the behavior used at Medium or Large scale:

- Scikit-learn's histogram gradient boosting bins continuous features before
  training. In the installed implementation, `_BinMapper` samples row positions
  when the number of rows exceeds 200,000. The public estimator documentation
  confirms that features are binned, while its source contains the subsampling
  implementation.
- LightGBM documents `bin_construct_sample_cnt` / `subsample_for_bin` with a
  default of **200,000**, and a seed for sampling the data used to construct
  those bins. See the official [LightGBM parameter documentation](https://lightgbm.readthedocs.io/en/stable/Parameters.html#bin_construct_sample_cnt).
- An audit experiment with 210,001 rows found different sklearn bin thresholds
  after a row permutation for every tested feature; maximum threshold deltas
  were approximately `0.0588`, `0.0243`, and `0.0143`.
- A matching 210,001-row LightGBM experiment, with identical values, labels,
  parameters, and random seed but permuted training-row order, changed all
  10,000 checked predictions; maximum absolute prediction change was about
  `0.29135`.

The seed fixes random *positions*, not which observations occupy those positions.
An unordered DuckDB scan can therefore alter the sampled observations, feature
bins, model, predictions, and budget metrics. The result directly contradicts
the README claim “Deterministic — same inputs, same predictions” and the
assertion in `RESULTS_hi_large.md` that dropping the sort was proven bitwise
safe. The project's own metric-stability report already observes that training
row order can materially change AP, which is incompatible with the stronger
claim elsewhere.

The committed Medium evidence is consistent with this risk. The older
`gold/models_Medium/manifest.json` reports AP `0.282400`, precision@50
`0.793981`, recall@50 `0.037838`, and ring recall@200 `0.693762`; the newer
`gold/models3_Medium/manifest.json` reports AP `0.300478`, precision@50
`0.880787`, recall@50 `0.041975`, and ring recall@200 `0.712665` for the same
headline GBDT/seed. Other code or environment changes may also contribute, so
this comparison is not causal proof by itself, but the discrepancy must be
explained before either run is called canonical.

**Required change:**

1. Define a stable training-row identity/order or a deterministic bin-sampling
   method that is invariant to physical scan order. If a full global sort is too
   expensive, use deterministic materialization/partition ordering or construct
   the bin sample from a stable row key before fitting.
2. Add regression tests above the 200,000 threshold for **both** sklearn and
   LightGBM. Compare model-relevant binning and predictions after a physical row
   permutation.
3. Run the test on the Linux/amd64 locked environment used for cloud results.
4. Regenerate every affected Medium and HI-Large fit/evaluation artifact after
   the fix, with known commit SHA and environment provenance.
5. Until then, remove all bitwise/deterministic and cross-machine parity claims.

### B2 — The “97% prevalence arithmetic” conclusion is unsupported

**Severity:** blocker
**Affected claims:** README finding 7, `LIMITATIONS.md`, split-inflation paper,
handoff, project thesis

``analyze_split_inflation.py``
assumes that average precision scales with prevalence for a ranker of fixed
quality. It divides the AP ratio by the prevalence ratio, obtains a residual
ratio of about 1.03, and turns that into the statement that 97% of the AP uplift
is prevalence arithmetic.

That inference does not follow:

- Average precision is prevalence-sensitive, but it does not generally scale
  linearly with prevalence for a fixed score distribution/ranker.
- The excluded observations are not a random sample of positives. Experiment B
  says the excluded positives are easier, so removing them changes the positive
  score distribution as well as prevalence.
- Even if the code's multiplicative ratio decomposition were accepted,
  `1.3999 / 1.3596 = 1.0296` means a 2.96% residual *ratio*. It does not mean
  97% of the 39.99% AP uplift. A direct excess-ratio allocation assigns about
  `0.3596 / 0.3999 = 89.9%`, while a log-ratio allocation is about 91%; neither
  is 97%.
- Experiment B is transaction-level/global-threshold evidence about the removed
  observations. It is not an AP decomposition on a common evaluation
  population.

**Required change:** compare the protocols at a common prevalence using a
pre-registered reweighting/downsampling design, or compute a prevalence-adjusted
precision-recall analysis while preserving score distributions. Resample at the
data-generation or appropriate clustered unit. Report uncertainty. Until that
analysis exists, replace “97%” with the narrower supported statement: the naive
split has higher prevalence and excludes a non-random, easier subset, so its AP
increase cannot be interpreted as model improvement or leakage alone.

### B3 — Replay-bundle contents and licensing statements disagree

**Severity:** blocker pending license review
**Affected files:** ``DATA_LICENSE.md``, replay bundle metadata,
release package/data policy

`DATA_LICENSE.md` says the repository publishes “Derived statistics—metrics,
manifests, aggregate counts” and contains “No transaction records, no account
identifiers, no reconstructable subset.” That description is not accurate for
the committed replay bundles. Depending on bundle, the files include:

- row-level scored and labeled account-days (`day`, `acct`, `score`, `y`, rank,
  and non-ring maximum score);
- encoded/pseudonymous account identifiers;
- many-to-many `(day, acct, ring_id)` membership rows; and
- ring endpoint rows linking a ring, account, day, and ring-transaction index.

The account codes are opaque, and the bundles do not contain the full original
transaction attributes, but that does not make them aggregate-only or justify
the categorical claim that they redistribute no part of the dataset.

The official [CDLA-Sharing-1.0 text](https://cdla.dev/sharing-1-0/) distinguishes
“Results” from “Data” and “Enhanced Data.” A Result may not include more than a
de minimis portion of the source Data; publishing Data or Enhanced Data triggers
conditions including the same license, notices for changed files, and preserved
attribution. The report cannot make the legal classification. The current file
also appropriately says a lawyer should decide—but then makes categorical
factual statements that pre-empt that decision.

**Required change:** obtain a real license review of each bundle schema and its
derivation. Then either (a) redesign the bundles to contain only clearly
aggregate/non-reconstructive outputs, or (b) distribute them under the required
data terms with attribution, notices, and an included license copy. In either
case, describe the files precisely and remove “no account identifiers,” “only
aggregate counts,” and “redistributes no part” unless those claims are verified.

Also correct lines 26–30 of `DATA_LICENSE.md`: the repository now has a
six-file SHA-256 content pin, so “not pinned and not checksummed” is stale.

### B4 — Competing result lineages make the headline non-canonical

**Severity:** blocker
**Affected claims:** README result table, cloud parity, CFF abstract, papers

There are at least two committed Medium model/evaluation lineages that present
different values for the nominal headline model. The README uses the older
lineage. The newer lineage is not labeled as a failed experiment, sensitivity
run, or replacement. A reader cannot determine which numbers are authoritative
or why.

The documented local/cloud parity evidence is also incomplete:

- README lists model hashes beginning `084dae…` and `c9c380…`, says 15/16 metrics
  are identical, and says predictions are identical.
- The `c9c380…` hash appears in prose/test commentary but not in a committed
  source manifest that independently records a prediction digest.
- The old local manifest predates `predictions_sha256`; equal printed metrics do
  not establish bitwise-identical predictions.
- The newer cloud/current lineage has a different model hash and metrics, but no
  corresponding local rerun tied to the same code/data/order.

**Required change:** create a result registry or explicit canonical manifest
that names the selected lineage, code SHA, data hashes, lock/image digest,
configuration, model hash, prediction hash, evaluation hash, and superseded
lineages with reasons. Re-run local/cloud parity after B1 is fixed. The README,
papers, CFF, and tables must all source the same canonical artifacts.

### B5 — Live Azure state contradicts the repository

**Severity:** blocker for the cloud/security/cost claims; immediate operational
risk
**Snapshot:** read-only inspection at 2026-09-13 18:47 UTC

The live `aml-rg` state did not match `infra/main.bicep` or the runbook:

- `aml-vm` was **running**.
- Its NIC had a public IP attached.
- Its NSG allowed inbound TCP/22 from `*`.
- The current documentation and Bicep comments state there is no public IP, no
  inbound port, no SSH access, and no key.
- The live subnet had no NAT gateway, while current Bicep declares a private
  subnet plus NAT.
- Bicep `what-if` proposed creating a new NAT, VNet, NIC, NSG, outbound public
  IP, and related resources rather than reconciling the deployed objects. It did
  not establish that the current template created the reported experiment.
- An ACR remained live even though `deployRegistry=false`. This is expected for
  an incremental deployment that omits an existing resource, but contradicts
  the impression that the parameter describes the complete current state.
- No Azure budget was configured.
- The uncommitted cost snapshot had advanced to 91.81 resource-hours and $50.23
  list price, versus 51.00 hours and $27.90 throughout the published docs.

Azure documents that resources omitted in incremental deployments remain in the
resource group; deleting omitted resources requires an explicit lifecycle
mechanism such as deployment stacks. See [ARM deployment modes](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes).
Azure also recommends explicit outbound connectivity/private subnets and
documents VM auto-shutdown/budgets for cost control: [default outbound access](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/default-outbound-access),
[auto-shutdown](https://learn.microsoft.com/en-us/azure/virtual-machines/auto-shutdown-vm),
and [VM cost monitoring](https://learn.microsoft.com/en-us/azure/virtual-machines/cost-optimization-monitor-costs).

**Required change:** immediately decide whether the live resources are still
needed. If not, deallocate/delete them through a reviewed command. If retained,
restrict/remove public SSH, set a budget and auto-shutdown/TTL, and document the
approved access model. Reproduce the infrastructure from an empty resource
group using the exact checked-in Bicep, capture deployment/what-if evidence, and
either import/manage or explicitly retire legacy resources. Do not publish the
current “no public IP/no inbound” architecture or cost totals as facts until
live evidence matches them.

The repository should not state “$0 actually charged” based only on trial-credit
or consumption API behavior. A credit can offset a real charge, and incomplete
billing data is not an invoice. Use “estimated list cost” and, if needed,
separately say “covered by promotional credit according to [specific billing
record/date].” Cost is time-sensitive; include an as-of timestamp and stop the
clock before publication.

## 5. High-severity scientific and conceptual findings

### H1 — Seed intervals are sensitivity summaries, not external confidence intervals

The five “95% CI” values are calculated from optimizer seeds on one fixed
synthetic dataset and one fixed split. They characterize within-run optimization
sensitivity. They do not capture dataset-generation variability, temporal
sampling, entity/ring clustering, benchmark choice, or production-domain
uncertainty. Some documents acknowledge this, but labels and conclusions still
invite inferential interpretation.

**Change needed:** call them “seed sensitivity intervals” or “t-interval across
five optimizer seeds on a fixed dataset,” not generic confidence intervals.
Reserve external uncertainty language for repeated datasets/splits or a justified
hierarchical/cluster resampling design.

### H2 — Typology “perfect replication refuted” is too strong

The typology null simulation uses Medium's observed effect-size profile as the
truth, rescales it, then asks how often Large reproduces the ordering. That is a
plug-in power calculation for one assumed profile, not a test of the composite
null “the ordering is the same.” If true gaps are smaller, a low rank
correlation is more likely. The reported `p = 0.014` is therefore conditional on
the chosen profile and assumptions.

**Change needed:** present the result as a model-conditional sensitivity
analysis, run a sensitivity grid over plausible effect sizes/noise, or fit a
hierarchical model. A third independently generated dataset would materially
strengthen the generalization claim.

### H3 — The ring-null p-value answers only the upper-tail question

The permutation p-value counts null ring recall values greater than or equal to
the observed value. A reported value near 1 therefore says the model is not
unusually *better* than this null; it is not a calibrated p-value for the claim
that the model detects fewer rings than chance. The observed value being below
the 95% null interval is descriptive evidence for the lower direction, but the
stored p-value does not test it.

**Change needed:** emit and label upper-tail, lower-tail, and/or two-sided values
according to pre-specified hypotheses. Describe the null narrowly: it conditions
on the observed daily ring-transaction score multiset and non-ring scores. It
does not test every possible meaning of “graph exploitation.”

### H4 — Ring and spread nulls depend on independence assumptions

The spread calculation's binomial null treats rings as independent, although
fixed daily budgets and shared accounts create dependence. This limitation is
acknowledged, but `p = 0.0008` can still be read as model-free evidence.

**Change needed:** call it a model-conditional p-value, preserve day/account
dependence in a blocked permutation or simulation where feasible, and avoid
“definitive/refuted” language.

### H5 — Bootstrap clustering still collapses multi-ring membership

The main ring metrics correctly carry a many-to-many membership table and note
that 10,432 of 243,295 ringed account-days (4.288%) belong to multiple rings.
However, ``ring_cluster_bootstrap``
calls `to_account_days`, then clusters by the scalar `ad.ring_id`. That scalar is
created with `ring_id = max`, so the bootstrap discards all but one membership
for multi-ring account-days—the exact representation the surrounding code says
is invalid.

**Change needed:** cluster by connected components in the overlapping
ring/account-day incidence graph, use a multi-membership resampling method, or
justify another dependency-preserving unit. Regenerate affected intervals. Keep
the existing warning that unringed positives are treated too independently; the
multi-ring issue is additional.

### H6 — The unit-of-work claim is a proxy, not an observed operational fact

The metric module says an account-day is what an investigator is told to look
at. The limitations correctly state that no operational queue or analyst study
supports that assertion. A useful proposed alert unit should not be presented as
empirical workflow fact.

**Change needed:** consistently call `(account, calendar-day)` an explicit
evaluation proxy. Explain when it approximates a case/alert and where deduping,
case expansion, household/entity resolution, and multi-day queues would differ.

### H7 — Categorical hash features weaken the “largely linear” conclusion

Categorical values are reduced with DuckDB `hash(...) % 1000` and passed to the
logistic baseline as continuous numeric variables. This introduces collisions
and arbitrary ordinal geometry. A linear classifier can exploit numeric hash
order in ways that are not meaningful categorical effects.

**Change needed:** run ablations with categorical features removed, one-hot or
proper categorical encodings, collision diagnostics, and stable train-only
encoding. Narrow the current claim to: “the chosen transformed 32-feature vector
is strongly separable by this particular linear baseline.” Do not generalize to
the benchmark's intrinsic linearity until the encoding artifact is ruled out.

### H8 — “Near-saturated” and “benchmark everyone measures on” overclaim

The README partly retracts the prior near-saturation comparison, but
`LIMITATIONS.md`, `HANDOFF.md`, `CITATION.cff`, README summaries, and keywords
still use “near-saturated” or “benchmark saturation.” Precision@50 of 0.571 is
strong, but without a justified ceiling or relevant comparator it does not prove
saturation. “The benchmark everyone measures on” and claims that published
numbers rarely state a budget require a literature survey and citations.

**Change needed:** remove saturation language or define and substantiate a
saturation criterion. Replace broad field claims with cited, bounded statements
such as “a widely used synthetic AML benchmark” if supported. The strongest
honest headline is that evaluation choices materially change conclusions, not
that the entire benchmark is solved.

## 6. Reproducibility, provenance, and result-integrity findings

### H9 — HI-Large training provenance is incomplete

Seven successful manifests record `code_git_sha: "unknown"`; all three current
HI-Large fit manifests are among them. Later evaluation manifests may identify
evaluation code, but they do not establish the exact code that created the
models/scores. `provision_vm.sh` defaults `AML_GIT_SHA` to `unknown`, and the
runbook invokes it without supplying a SHA. The run scripts do not enable
`AML_REQUIRE_PROVENANCE=1`.

**Change needed:** make an unknown SHA fatal for publication runs, pass the full
40-character SHA from the runbook/deployment, persist source-bundle and image
digests, and rerun all canonical fits. If rerunning is impossible, explicitly
label current HI-Large training artifacts as incompletely provenance-bound.

### H10 — Dataset verification is not fail-closed

`dataset_pin.json` usefully pins six files. However,
``verify_dataset.py`` checks only
files that happen to be present and calls missing pinned files “not an error.” In
this audit, five files matched and the absent HI-Large transaction file did not
fail the command. The release checklist says all six are verified. Neither
`run_hi_large.sh` nor `run_cloud.sh` invokes this verifier.

The cloud download logic also accepts any existing non-empty file. A partial
non-empty download is skipped on the next run; no expected size/hash is checked
before a costly pipeline begins.

**Change needed:** add `--require-all`/variant-specific required sets, verify
size and SHA-256 after every acquisition, and make each production runner fail
before normalization if either raw input is missing or mismatched. Record the
verified content identities in every downstream manifest.

### H11 — Manifests do not deliver every documented guarantee

1. `verify_outputs()` treats an empty output inventory as valid. A legacy
   manifest with a matching key but no `outputs` can therefore cache-hit without
   verifying any artifact. Sixty-nine committed manifests lack an output
   inventory.
2. Files above 64 MB are checked by size only. Same-size corruption is not
   detected, despite broad checksum language in the README.
3. Forty-six committed manifests have no `run_key`. Several evaluation and
   experiment stages use `Run` without `cached_or_none`, so “every stage is
   content-addressed and unchanged work is skipped” is false.
4. Input identities are folded into a run key but are not explicitly written as
   an auditable input inventory. The claim that a manifest records inputs and
   their checksums is stronger than the schema.
5. The stale-output cleanup in `Run.__exit__` inventories the directory *after*
   the stage writes into it. Old partitions are still present at that point, so
   they appear current and cannot be identified as stale. The regression test
   named for stale partition removal actually treats a surviving ghost file as
   an output.

**Change needed:** fail closed when an inventory is absent; hash or strongly
fingerprint all publication artifacts; make every cacheable stage keyed; persist
an explicit input inventory; and write outputs to a fresh staging directory
followed by validation and atomic replacement. Add a test where a rerun emits
fewer partitions and prove the removed partition is absent.

### H12 — The publication-number checker is syntactic, not semantic

The configured eight-document check passes, which is valuable, but it matches
numeric tokens to values found somewhere in selected artifacts. It does not
bind a value to its metric name, model, variant, budget, seed, unit, or result
lineage. A wrong number can pass if the same number appears in another context.
Integers and percentages receive incomplete coverage. Running it across all 31
Markdown files found 19 unprovenanced numeric tokens, mostly in explicitly
superseded/retracted documents but also a current CONTRIBUTING value.

`HANDOFF.md` says `make_tables.py` generates every figure, while the README more
accurately says it verifies values. It does not generate the prose/tables.

**Change needed:** generate canonical tables from a typed result schema or use
explicit source annotations that bind each cell to artifact path + JSON key.
Keep archived/retracted docs out of current gates only if they are clearly
segregated and immutable.

### H13 — Internal caches can return stale ranks/structures

`_ranks` and `_ring_structure` memoize only by frame length. If scores,
membership, days, or accounts change in place without changing length, stale
values are reused. The current pipeline may not mutate those frames, but the
helpers are public enough to be reused incorrectly and their validity invariant
is not enforced.

**Change needed:** make frames immutable by construction, key caches by relevant
array identity/content/version, or remove the hidden cache and pass a computed
evaluation context explicitly. Add same-length mutation tests.

## 7. Cloud and operational implementation findings

### H14 — The documented Medium cloud run uses an image tag that provisioning does not build

`provision_vm.sh` defaults to `aml:latest`; `run_cloud.sh` defaults to `aml:v5`.
Following the runbook exactly can therefore fail because `aml:v5` was never
built. HI-Large defaults to `aml:latest`, so the two runners also have different
implicit image identities.

**Change needed:** pass one immutable image digest/tag explicitly through
provision and run commands. Record it in manifests. Do not use `latest` or a
manually advanced `v5` for publication reproduction.

### H15 — The runbook's source archive cannot build the Dockerfile

The tar command includes `requirements.lock` but omits
`requirements.linux-amd64.lock`, `requirements-dev.lock`, and
`requirements-dev.linux-amd64.lock`. The Dockerfile copies all of them. A clean
execution of the documented upload/provision path will fail at Docker build.

**Change needed:** construct the source artifact from `git archive` plus only
documented generated inputs, include all required files, emit a SHA-256, upload
that digest, and verify it on the VM before extraction. Add a CI test that builds
from the exact archive recipe in the runbook.

### H16 — Managed-disk mounting has an incorrect device path

In `provision_vm.sh`, `D` is already set to an absolute `/dev/...` path, but line
69 mounts `"/dev/$D"`. This becomes `/dev//dev/...` and will fail when the disk
is not already mounted.

**Change needed:** mount `"$D"`; validate the resolved block-device path, file
system UUID, expected LUN, and mount result before changing permissions. Add a
ShellSpec/Bats-style test or a dry-run function test; shell syntax checking
cannot detect this defect.

### H17 — Bootstrap and acquisition trust mutable/unverified network content

- The provisioning script pipes the current Azure CLI install script into Bash.
- `az bicep install` installs the current CLI component in the gate.
- actionlint is downloaded by a remote shell script without verifying a digest.
- Ubuntu VM image version is `latest`.
- The Docker base is pinned to a mutable patch tag, not a digest.
- The DuckDB Azure extension is downloaded at image-build time without a
  committed digest/attestation.
- Apt packages are unpinned.

**Change needed:** pin and verify downloads or use trusted package repositories;
record the Bicep/Azure CLI versions; pin the base image by digest with a planned
update cadence; create an SBOM; scan and sign/attest the released image. GitHub
supports [artifact attestations](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds)
for public repositories.

### H18 — Container construction is reproducible enough for CI, not yet release-grade

The image uses an editable install and then changes ownership of all `/app` to
the runtime user, making application code mutable at runtime. Tests and scripts
are included in the production image. Dockerfile comments still refer to Azure
ML and Synapse even though the current execution path is a plain VM/container.
The installed Git binary is largely unnecessary once `AML_GIT_SHA` is injected.

**Change needed:** build a wheel in a builder stage, install it non-editably in
a smaller non-root runtime stage, keep application files root-owned/read-only,
copy only required runtime assets, and publish a separate test image if desired.
Update the architecture comments to the actual deployment.

### H19 — Infrastructure documentation is stale and internally contradictory

`infra/README.md` says the stack is storage, registry, and identity with nothing
else billable; the current template includes VM, disks, network, NAT, and public
outbound resources. It recommends an ACR build even though ACR deployment
defaults off and the runbook says ACR Tasks were unavailable. `RUNBOOK_cloud.md`
says sklearn is the model and LightGBM only a comparison, while the published
HI-Large result uses LightGBM.

**Change needed:** rewrite the cloud docs from the validated clean deployment.
One architecture diagram, one resource inventory, one cost scope, one image
flow, and one tested run command should be authoritative. Archive the abandoned
design rather than interleaving it with the current one.

## 8. Security and software-supply-chain findings

### H20 — Native GitHub security controls are not configured

At audit time, Dependabot alerts, code scanning, and secret scanning were not
enabled; there was no branch protection/ruleset. GitHub recommends Dependabot
alerts, secret scanning/push protection, and code scanning for public
repositories. These features are available free for public repositories; see
[GitHub's security settings guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository).

The custom full-history Gitleaks gate is a real strength, but it does not replace
push protection, dependency graph alerts, CodeQL/SAST, or protected review
rules.

**Change needed before public launch:** enable the dependency graph, Dependabot
alerts/security updates, secret scanning, push protection, CodeQL/default code
scanning, private vulnerability reporting, and a default-branch ruleset that
requires current CI/gates/image checks and blocks force pushes/deletion.

### H21 — The image workflow is not a pull-request gate

`image.yml` has only `push` and `workflow_dispatch` triggers. It therefore cannot
be required as a pre-merge pull-request check, despite the release checklist
saying the image check should be required. Any PR-specific condition inside that
workflow is unreachable.

**Change needed:** add a safe `pull_request` build/test path without package
write, and reserve authenticated push for protected main/tags. Make the build
job required. Test the exact release image, then promote by digest rather than
rebuilding.

### H22 — CI action/runtime maintenance is already due

The latest GitHub logs warn that several actions use deprecated Node.js 20 and
are being forced onto Node.js 24. Actions are commendably pinned to exact SHAs,
but no Dependabot/Renovate configuration updates those pins. The repository
setting requiring SHA pinning is also off, so the current practice is not
enforced.

**Change needed:** upgrade affected action versions to Node 24-capable releases,
enable automated action updates, and enforce SHA pinning through a ruleset or
policy. Pin ShellCheck/actionlint/Azure tooling versions and checksums.

### H23 — Dynamic SQL/path interpolation is unnecessarily fragile

Bandit reported 50 medium findings, mostly f-string SQL. Several paths, cut
values, and settings are interpolated into DuckDB SQL. The intended CLI is a
trusted offline research tool, which lowers exploitability, but a path containing
an apostrophe can break a query and untrusted values can become SQL injection.

**Change needed:** use DuckDB parameters where supported and central,
well-tested identifier/path quoting where not. Validate date cuts and resource
settings. Add tests with quotes and unusual Unicode in file paths. Add Bandit or
equivalent SAST as a non-noisy gate after triage.

### H24 — Package/image release visibility and attestations are incomplete

The GHCR image exists, but anonymous pull is denied because the package is
private. There is no signed tag, GitHub Release, SBOM, checksum file, signature,
or provenance attestation. All 76 commits are unsigned.

**Change needed:** decide the distribution promise. If the README offers a
public image, make GHCR public at release and verify an anonymous pull. Publish
an immutable digest, SBOM, signature/attestation, source/wheel checksums, and a
signed release tag. Commit signing is not mandatory for research quality, but a
signed release tag materially improves artifact authenticity.

## 9. Packaging and installability findings

### H25 — The distribution omits essential license/context files

The clean wheel/sdist builds and pass `twine check`, but the distribution does
not include the root `LICENSE`. The package README contains links such as
`../README.md`, `../DATA_LICENSE.md`, and `../LICENSE`; those parent-relative
targets do not exist when the subproject is rendered on PyPI or unpacked from
the sdist.

**Change needed:** include the MIT license in package metadata/artifacts, include
or embed the applicable data-license notice, and make README links valid in both
GitHub and package contexts. Inspect the rendered PyPI description before
publishing.

### H26 — Python compatibility is broader than the test evidence

`requires-python = ">=3.12"` claims compatibility with every future Python 3.x
release, while CI and the image test only Python 3.12.3.

**Change needed:** either test a supported matrix and update dependencies, or
bound the claim (for example `>=3.12,<3.13`) until newer versions are verified.
Add operating-system/architecture support language; current production proof is
Linux amd64 and local development includes arm64.

### H27 — Coverage is uneven in the modules that support conclusions

Overall coverage is 75%, but several high-judgment modules are lightly tested:

| Module | Audit coverage |
|---|---:|
| `drift/experiment.py` | 0% |
| `demo.py` | 19% |
| `eval/run.py` | 30% |
| `models/stability.py` | 31% |
| `models/train.py` | 42% |
| `leakproof/plant.py` | 53% |
| `leakproof/sweep.py` | 58% |
| `cli.py` | 78% |

The green suite is meaningful, but the row-order regression demonstrates why a
test count is not enough: a test can assert the right property below the
behavioral threshold.

**Change needed:** prioritize property/scale-boundary tests for methods that
create publication claims. Set a coverage floor only after adding meaningful
tests; do not optimize for line coverage alone.

## 10. Documentation, writing, and presentation findings

### H28 — Release metadata says a release exists when it does not

`CITATION.cff` declares version `0.1.0` and release date `2026-09-11`, but the
repository is private and has no Git tag or GitHub Release. Its abstract uses the
old phrase “ring-aware entity-disjoint,” calls the benchmark close to saturated,
and says this is the operating point practitioners care about without evidence.

**Change needed:** do not populate `date-released` until the tag/release exists.
Use “ring-participant-disjoint temporal split,” remove unsupported saturation
and practitioner claims, and create the release/tag only after all gates pass.

### H29 — Test, artifact, and marker counts are stale

Current measured counts are 277 passing tests, 17 skips, 51 publication result
sets, 58 `<!-- derived -->` markers, and 95 result manifests. Documentation
variously says 257, 270, or 275 tests; 50 result sets; 68 markers; and 101+
manifests. The skip explanation “without Azure extras” is wrong: the 17 skips
are data-dependent HI-Small contract tests whose built intermediates are absent.

**Change needed:** stop hand-maintaining these counts in multiple prose files.
Generate a release facts block from CI/artifacts and include a timestamp/commit.
Correct README, CONTRIBUTING, HANDOFF, and RELEASE_CHECKLIST together.

### H30 — Markdown renders, but table annotations are malformed

Strict Markdown lint found 2,202 issues across 28 files:

| Rule class | Count | Impact |
|---|---:|---|
| Long lines (`MD013`) | 1,102 | Mostly maintainability/style |
| Table column style (`MD060`) | 723 | Style and noisy diffs |
| Unlabeled code fences (`MD040`) | 157 | Accessibility/rendering |
| Multiple H1 headings (`MD025`) | 59 | Document structure |
| Table pipe/column errors (`MD055`/`MD056`) | 68 | **Actual malformed rows** |
| Heading/list spacing and others | 93 | Consistency/rendering |

The important defects are the 34 table rows that append `<!-- derived -->`
after a closing pipe. Markdown parsers can treat the comment as an extra cell,
causing a column-count mismatch. This affects the root README result table and
multiple result/cost tables.

**Change needed:** choose a Markdown style config, fix structural errors first,
put provenance comments outside table rows or inside the final cell consistently,
label every fence, and add markdownlint to CI. Long lines can be selectively
disabled for wide tables/URLs rather than generating churn.

### H31 — Link checking is local-only despite broader wording

The checker confirms that local paths/anchors resolve but does not fetch five
external targets. “Markdown links resolve” can therefore be misunderstood as an
external link health check.

**Change needed:** rename the current gate “local Markdown links resolve” and
add a scheduled/allowlisted external link checker with retry and rate-limit
handling.

### H32 — Current and historical narratives are interleaved

The repository admirably preserves retractions and failed approaches, but root
`Cloud/`, `AML_PROJECT_KNOWLEDGE/`, and older result documents remain prominent
and searchable. Superseded banners help, yet they still inflate the repository,
conflict with current numbers, and make first-time readers distinguish current
truth from forensic history themselves.

**Change needed:** keep the history, but move it under a clearly named
`docs/archive/` or a tagged historical release. Create one short
`RETRACTIONS_AND_CORRECTIONS.md` index linking old claims, why they changed, and
their replacement. Exclude archived prose from current-number checks only after
that separation is unambiguous.

### H33 — The README is strong but too long and internally self-correcting

At roughly 450 lines, the README repeatedly explains former mistakes inline.
That honesty is valuable for a methods paper, but it dilutes the first-page
message and makes current claims harder to identify. It also contains the
contradiction where the opening narrows/removes “near-saturated,” while the final
limitations summary sends readers to a document that still asserts it.

**Change needed:** after scientific reconciliation, restructure the README:

1. one-sentence contribution and scope;
2. canonical result table sourced from one manifest;
3. what a reviewer can run in 5 minutes / with raw data / in Azure;
4. evaluation design diagram;
5. bounded conclusions and limitations;
6. links to methods, corrections, and full result reports.

Move detailed debugging narratives into architecture decisions or the
corrections log. Avoid promotional claims that require a literature survey.

### H34 — Smaller writing and metadata issues

- `aml-platform/src/aml/io.py` contains “therefor” where “therefore” is intended.
- Many fences lack language labels.
- The GitHub repository has no topics and no homepage metadata; its description
  mentions 32M rows/one laptop but not the 180M-row/cloud evaluation.
- There is no changelog/release-notes document, Code of Conduct, issue template,
  or pull-request template. These are not scientific blockers but affect public
  project completeness.
- Git history contains two author email identities, including a local-hostname
  address and an institutional address. Decide intentionally which personal
  metadata is acceptable before making the history public.

## 11. Release checklist defects

The existing checklist is not reliable enough to be the final gate:

- it says 270 tests and 17 skips due to Azure extras;
- it says all six raw files are verified, while the verifier allows missing
  pinned files;
- it treats the image workflow as a required PR check although the workflow has
  no PR trigger;
- it still lists the Medium cross-machine null as open although a later run is
  committed;
- it does not catch the `latest`/`v5` mismatch, missing source-archive locks,
  unknown HI-Large training SHA, or live Azure drift;
- final decisions remain unchecked for credential rotation, history/privacy,
  public repository/package visibility, branch protection, Azure teardown, and
  the release tag.

**Change needed:** replace it with executable gates where possible. Every manual
gate should name the evidence, responsible person, date, and exact pass
criterion. A box should never be checked based on a prose assertion alone.

## 12. Strengths worth preserving

These are not courtesy notes; they are the parts that make the project worth
finishing.

1. **A genuinely useful evaluation frame.** Daily alert budgets, an explicit
   alert unit, attainable recall ceilings, alerts-per-true-positive, tie
   sensitivity, and ring-level detection answer operationally relevant questions
   that ROC AUC alone does not.
2. **Honest corrections and negative results.** The project retains retractions,
   challenges its graph-feature and ring-lift stories, and distinguishes what a
   null does and does not show. Keep that intellectual honesty, but organize it.
3. **Serious scale.** The work spans roughly 32M and 180M transaction variants
   and records the memory/spill consequences of running them. That is more
   convincing than a toy notebook once the provenance is repaired.
4. **Good automated baseline.** 277 tests, an end-to-end generated-data demo,
   local/file-URI parity tests, linting, ShellCheck, actionlint, Bicep compilation,
   full-history secret scanning, and in-image testing are strong foundations.
5. **Dependency discipline.** Platform-specific hashed locks and current clean
   `pip-audit`/`pip check` results are better than the usual unpinned research
   environment.
6. **Replayability.** All six committed replay bundles exactly reproduced their
   source metrics in this audit. The mechanism is useful; only the legal/content
   boundary needs resolution.
7. **Repository hygiene.** Git is small (about 10.4 MiB tracked; `.git` about
   7.3 MiB), raw datasets are absent from current history, and 165 JSON artifacts
   parse strictly.
8. **Foundational community files exist.** MIT license, SECURITY, CONTRIBUTING,
   and a schema-valid CFF are present; they need consistency rather than creation
   from scratch.

## 13. Recommended remediation order

### Phase 0 — immediate containment

1. Review/deallocate the running Azure VM; remove or restrict public SSH; add a
   budget/TTL. Do this before more cost accrues.
2. Revoke any Kaggle/API credential that was pasted outside the repository. A
   clean Git history cannot prove an externally shared token is safe.
3. Keep the repository and GHCR package private until licensing and result
   blockers are resolved.

### Phase 1 — scientific/reproducibility reset

4. Fix deterministic training semantics and >200k tests for both learners.
5. Rework/retract the 97% split-inflation decomposition.
6. Fix bootstrap multi-ring clustering and p-value labels; narrow typology and
   saturation claims.
7. Make data verification and provenance fail closed.
8. Rerun canonical Medium and HI-Large fits/evaluations with full SHA, data,
   environment, image, model, and prediction identities.
9. Select one canonical result lineage and generate all publication tables from
   it.

### Phase 2 — licensing and cloud proof

10. Complete replay-bundle CDLA review; modify artifacts or notices/license as
    advised.
11. Fix the runbook archive, image tag, disk mount, source checksum, and dataset
    checks.
12. Deploy current Bicep into an empty resource group, run the documented path,
    capture `what-if`/deployment evidence, then tear it down.
13. Publish only final, timestamped cost evidence with an explicit scope.

### Phase 3 — release engineering and presentation

14. Repair manifest guarantees, package license/readme, CI PR image trigger,
    action versions, native GitHub security, and branch rules.
15. Reconcile every current document, CFF, checklist, count, and derived table.
16. Separate archives/retractions from the current narrative and perform
    Markdown/style cleanup.
17. Build and verify public artifacts from the release commit; publish immutable
    hashes/digests, SBOM, attestation/signature, signed tag, and GitHub Release.
18. Verify from a clean unauthenticated machine: clone, install, demo, replay,
    documentation links, and anonymous image pull.

## 14. Definition of publication-ready

The repository is ready only when all of the following are true:

- >200k row-permutation tests pass for sklearn and LightGBM in the release image.
- Canonical Medium and Large artifacts were produced after that fix and have no
  unknown SHA or ambiguous lineage.
- README/paper/CFF numbers are generated or semantically bound to those artifacts.
- The 97% claim is replaced by a statistically justified analysis or removed.
- Replay bundles have a reviewed legal classification and accurate notices.
- A clean Azure deployment matches the stated no-inbound architecture, the
  documented commands complete, cost controls exist, and the resources are
  stopped/deleted after validation.
- Dataset acquisition verifies all required hashes before compute.
- Package and image include correct license/provenance material and are
  reproducible from the tagged commit.
- Required PR checks include code, static gates, and the actual image test;
  branch protection and GitHub security features are enabled.
- All current docs agree on claims, terminology, counts, costs, version, and
  release date; archived claims are unmistakably archival.
- A clean-room reviewer can execute the quick demo and all six permitted replay
  checks without author-only state.
- No checklist item is waived silently. Any accepted limitation is stated in the
  README and release notes with its effect on interpretation.

## 15. Final assessment by dimension

| Dimension | Current assessment | After required fixes |
|---|---|---|
| Writing | Thoughtful and candid, but long, contradictory, and stale in places | Potentially excellent |
| Content | Rich and unusually substantive | Excellent if canonicalized |
| Methods | Several strong ideas; one headline decomposition and some inferential language fail review | Strong and publishable after correction |
| Results | Extensive, but two current lineages and affected determinism/provenance | Convincing after rerun |
| Reproducibility | Strong scaffolding; production-scale training and acquisition are not deterministic/fail-closed | Could become a standout feature |
| Engineering | Broad, tested architecture with specific manifest/cloud defects | Strong |
| Security | Good custom secret scan and least-privilege workflow intent; weak GitHub settings and dangerous live drift | Good after configuration and evidence |
| Cloud | Real, impressive scale work; checked-in IaC/runbook do not reproduce or describe live state | Impressive after clean redeployment |
| Packaging | Builds cleanly, but release context/license links are incomplete | Straightforward to fix |
| Usefulness | High for AML evaluation and imbalanced ranking work | High |
| Impressiveness | High technical ambition, currently reduced by contradictions | Very high once claims are tightened |
| GitHub readiness | **No** | Yes after all blocker/high gates pass |

## Bottom line

Do **not** make this repository public or call `0.1.0` released yet. The project
does not need more breadth. It needs one controlled correction cycle: make
training truly deterministic at the scale claimed, repair the split-inflation
analysis, resolve the replay-data license boundary, choose and regenerate a
single provenance-complete result lineage, and prove the cloud path from clean
infrastructure. Then simplify the story around that evidence.

If those changes are completed, this can be a genuinely impressive public
project: not because it claims the best AML model, but because it shows—with
auditable evidence—how to measure an AML model without confusing benchmark
prevalence, leakage, alert budgets, ring structure, or infrastructure accidents
for real operational performance.
