# V5 publication-readiness audit

**Repository:** AML Evaluation Harness
**Audit date:** 2026-09-14
**Audited branch:** `main`
**Audited commit:** `5f39c227b6d27679ffff60003c1da6e9062224a9`
**Observed `origin/main`:** `5f39c227b6d27679ffff60003c1da6e9062224a9`
**Initial worktree:** clean
**Scope:** all 366 tracked files, source, tests, result artifacts, replay bundles,
methods, claims, documentation, packaging, dependencies, container, CI/CD,
GitHub configuration, Azure infrastructure and live-cloud state.

## Verdict

**No: the repository is not completely done and should not be made public yet.**

V4's largest repository defects were genuinely fixed. This is now a strong,
technically distinctive project with a green exact-commit test suite, unusually
good result traceability, a correctly fail-closed six-file data pin, strict
stored JSON, reproducible replay metrics, and real large-scale cloud evidence.
The present commit is much closer to a release candidate than the V4 snapshot.

It is not, however, the final release. This audit found four new technical
release blockers that the current checks do not detect:

1. derived-artifact provenance still accepts dirty imported package code;
2. the image pushed to GHCR is a second build, not the image that was tested;
3. the current split-inflation headline calls an observational contrast
   leakage/contamination more strongly than its own method permits; and
4. a current feature specification still declares the fixed `txn_id` defect to
   be live and says the leak proof is silently wrong.

Four owner-controlled release blockers also remain exactly where the handoff
says they remain: the VM is still running and billing, replay-bundle licensing
is unreviewed, the Kaggle credential must be rotated, and the repository/image/
security settings are not ready for anonymous public use.

There are also important non-blocking defects: the demo prints non-standard
JSON `NaN`, clean setup/package smoke select whatever `python3` means even
though the project supports only Python 3.12, cross-architecture claims still
overreach the evidence, cache keys omit the dependency environment, run
manifests and replay bundles have incomplete provenance, and several release
documents are already stale or internally contradictory.

### Release decision

| Decision | Status |
|---|---:|
| Publish/tag the current commit | **No** |
| Core implementation is credible | **Yes** |
| Main committed result tables are numerically consistent | **Yes** |
| Tests and current remote checks are green | **Yes** |
| Reproduction and provenance claims are fully proved | **No** |
| Cloud and public-distribution state are safe/complete | **No** |
| Ready after a focused release-hardening pass | **Yes** |

## Corrections to the V4 discussion

The response to V4 was right on two points and partly wrong on one:

- The V4 snapshot/CI finding was stale by the time its report arrived. This V5
  audited a clean tree whose `HEAD` and `origin/main` are the same full SHA.
- V4 misdescribed `categorical_ablation_medium.json`: it did have a generator.
  The real defect was its 12-character commit SHA. It now records the full SHA,
  and its generator bytes match that Git object.
- The demo's **stored manifest** now writes `null`, but the demo's stdout did
  not. A clean Python 3.12 wheel run at this commit emitted `"ci_lo": NaN` and
  `"ci_hi": NaN` in the `train_complete` event. Those are separate output
  paths. The V4 wording should have distinguished them, but the stdout defect
  remains real.

This report supersedes V4 for the exact commit named above.

## What was independently checked

This was not a documentation-only review. The audit used clean or temporary
environments wherever the distinction mattered.

| Check | V5 result |
|---|---|
| Repository state | clean `main`; local and remote SHA identical |
| Local suite | **310 passed, 17 skipped; 327 collected** |
| Source-only coverage | **76%** |
| Ruff | pass across `src`, `tests`, and `scripts` |
| Git integrity | `git fsck` pass; whitespace check pass |
| GitHub CI at exact SHA | success; **309 passed, 18 skipped** in fresh checkout |
| Container CI at exact SHA | success; **304 passed, 23 skipped** |
| Security/gates workflow | success; gitleaks found no leaks; Bandit found no high-severity issue |
| Published-number gate | 13 documents, 479 checked values, zero unsupported/unprovenanced/superseded/retracted |
| Result registry | 56 result sets; zero malformed |
| Derived markers | 156 exemptions; all accepted by the current gate |
| Release-facts gate | 327 collected, 56 result sets, 79 markers, 101 manifests |
| Local Markdown links | 88 local links checked; zero broken/malformed |
| Markdown lint | 19 configured current files; zero errors |
| Strict stored JSON | every committed result JSON parsed with non-finite constants rejected |
| Dataset contract | six exact filenames pinned; five local files verified; missing HI-Large correctly causes exit 1 |
| Derived generator provenance | 10/10 generator blobs match their recorded full Git SHA |
| Derived package-tree provenance | 9/9 artifacts that record a tree hash match the package tree at their Git SHA |
| Replay verification | all committed bundle metric recomputations pass |
| Bicep | build succeeds in the remote gate |
| Shell scripts | Bash syntax pass |
| Python dependencies | `pip check` pass; fresh `pip-audit` found no known vulnerability in `requirements.lock` |
| Package build | sdist and wheel build successfully |
| Package metadata | both artifacts pass `twine check` |
| Wheel smoke, explicit Python 3.12 | clean install, CLI help, and no-data demo succeed |
| Citation metadata | valid CFF 1.2.0 |

The skip-count difference is explainable. Seventeen local skips require the
HI-Small built intermediates. Fresh CI also lacks the split-inflation gold
inputs, producing one more skip. The image adds five root-context checks it
cannot run, for 23 total. The image job now asserts allowed reasons rather than
merely comparing counts.

## P0 release blockers

P0 means that the current state can create a materially false provenance,
scientific, security, legal, billing, or public-reproduction claim. These must
be resolved before the repository becomes public or receives a release tag.

### P0-1 — Artifact provenance still fails for dirty imported code

`generator_provenance()` now performs the missing comparison between the
generator on disk and the generator blob at `code_git_sha`. That is a real and
important fix. It does **not** perform the equivalent comparison for the package
code imported by that generator.

The function records `code_tree_sha256`, but its own comment calls the value
"informational." It hashes the current package tree and never compares that
hash to the tree at the recorded commit.

V5 reproduced the remaining failure in an isolated clean clone:

1. modify only `src/aml/eval/metrics.py`;
2. leave `scripts/cost_table.py` unchanged;
3. call `generator_provenance()` for `cost_table.py`.

The helper returned the clean HEAD SHA, `generator_matches_commit: true`, and a
new hash of the dirty package tree. It therefore remains possible to commit an
artifact that says the generator matches commit X even though the imported
implementation that produced it is absent from X. This is the same class of
false combined assertion as V4, moved one level down the dependency graph.

All ten current derived artifacts also omit `inputs` and `parameters` even
though the helper can accept them. Code identity alone does not identify what
the generator read or which options it used.

**Required change:** compute the package-tree digest from Git objects at the
recorded full SHA and require it to equal the on-disk digest. Alternatively,
fail artifact generation whenever relevant tracked files are dirty. Record and
validate input hashes/IDs and parameters for every derived artifact. Remove or
explicitly scope the dirty-provenance override for committed output.

**Acceptance test:** change an imported module while leaving the generator
unchanged; artifact generation must fail. The regression must compare the
generator blob, package tree, inputs, and parameters—not merely field presence.

### P0-2 — The cloud source recipe can make the same false Git claim

`docs/RUNBOOK_cloud.md` computes `GIT_SHA` from HEAD, warns when the worktree is
dirty, then tars the working tree and builds the image with that clean commit
label. `SRC_SHA256` proves that Azure received the same tarball; it does not
prove that the tarball is the tree identified by `GIT_SHA`.

The warning even states the defect: the image will claim a commit it does not
contain. A documented warning does not make false provenance safe.

**Required change:** fail on a dirty or untracked deployment input, or create
the source bundle with `git archive <full-sha>` plus separately controlled
non-Git inputs. Record both commit identity and source-bundle identity in the
image and result manifests. Verify their relationship before building.

**Acceptance test:** an edited tracked source file must make the documented
deployment command stop before upload. A clean archive reconstructed from the
recorded commit must match the deployed source manifest.

### P0-3 — The published container is not the tested container

`.github/workflows/image.yml` first uses `docker/build-push-action` to build and
load an `:ci` image. It runs provenance, the full suite, skip-reason parity, and
the DuckDB Azure-extension test against that local image. The later `Push` step
invokes the build action a second time and pushes that second build.

The workflow therefore proves one artifact and publishes another. Cache reuse
does not establish bit identity. The Dockerfile also consumes mutable external
state—APT repositories and a fetched DuckDB extension—so a rebuild can differ
even at the same source commit.

**Required change:** build once, test that exact image, then push/promote the
same digest. Record the resulting digest in release evidence. Generate and
attach provenance/SBOM to that digest.

**Acceptance test:** the digest tested before publication must be byte-for-byte
the digest under the commit/release tag in GHCR. The job must fail if they
differ.

### P0-4 — The split-inflation conclusion exceeds its identification argument

The counterfactual work is substantially better after the deterministic
ordering fix. The paper correctly says that its two components are contrasts,
not causal effects, and explicitly states that the score-distribution component
is not proven to be leakage. It also explains that the conclusion requires an
unconditional exchangeability assumption that may fail.

But the final claim table says published AMLworld numbers are "inflated by
leakage," rates this partly supported, and the boxed conclusion calls the
second half "the contamination a ring-aware filter exists to remove." Those
sentences turn a non-causal, assumption-dependent contrast into an identified
mechanism. The artifact's field names `prevalence_effect` and
`detectability_effect`, and its short method note also omit the exchangeability
qualification. This is internally inconsistent, not merely conservative
wording.

The strongest defensible result is:

> Under the implemented mixture counterfactual and its exchangeability
> assumption, approximately 47% of the observed AP contrast is associated with
> prevalence/composition and 53% with the score distribution of the readmitted
> positives. The latter is consistent with—but does not identify—contamination
> or leakage.

**Required change:** use that level of claim consistently in the artifact,
script, preregistration interpretation, results paper, README, and handoff.
Rename causal-sounding `*_effect` fields to `*_contrast` or explain their
non-causal meaning in-schema. Reserve "leakage" for a design-based result or a
sensitivity analysis showing the conclusion under explicit assumptions.

**Acceptance test:** no current document may state that the decomposition
proves leakage/contamination unless the method has been upgraded to identify
that mechanism. An assumptions/estimand block must be attached to the result.

### P0-5 — A current specification says the central leak proof is broken

`aml-platform/docs/FEATURE_SPEC_v1.md` is not archived and presents itself as
the live design. It says `txn_id` is nondeterministic, that cross-engine
reproduction is impossible, that the leak proof is already silently wrong,
and that the code—not the document—is the bug.

The implementation now assigns transaction identity once during normalization
and carries it downstream, with regression coverage. The current specification
therefore makes a severe false statement about the current product. A reviewer
has no principled basis for knowing whether to trust the implementation,
README, tests, or this spec.

**Required change:** either archive the file as a dated pre-fix design record or
rewrite it as the current specification. Preserve the old failure as history,
clearly marked resolved with the fixing commit and regression-test reference.

**Acceptance test:** current-facing specifications and code agree on the source
and lifecycle of `txn_id`; searching current docs must not report the defect as
live.

### P0-6 — Replay-bundle redistribution remains legally unreviewed

The repository now correctly says `UNREVIEWED`; that is better than asserting a
license conclusion. It is not permission. Nine bundles contain row-level
derived records from a CDLA-Sharing source, and the project intends to publish
them.

The opening of `DATA_LICENSE.md` also says "No transaction data is included"
and that a clone contains only code, tests, and result manifests. Later in the
same file it accurately inventories `ring_transactions.parquet` at one row per
ring transaction and multiple account-day/ring-membership Parquets. Even if
these are feature-stripped derived records rather than raw source rows, the
opening categorical statement is misleading and the clone plainly contains
more than manifests.

**Required change:** obtain a qualified licensing decision covering these exact
derived fields and redistribution method. If approval is unavailable, remove
the bundles from public history and replace them with synthetic fixtures or a
user-local generation path. Do not translate `UNREVIEWED` into "probably OK."
Rewrite the opening now as "no raw AMLworld CSV or original transaction rows"
and immediately disclose the derived row-level bundles.

**Acceptance test:** `DATA_LICENSE.md` records the decision, scope, reviewer,
and date, or no potentially restricted row-level bundle is present in the
public repository/history/release assets.

### P0-7 — A known Kaggle credential still requires rotation

The handoff says the token must be rotated. Repository scanning did not find a
current secret, but absence from the current tree does not make a previously
exposed credential safe.

**Required change:** revoke/rotate it at Kaggle, update the local/VM secret
store, verify the old token no longer authenticates, and keep the replacement
out of Git and shell history. Record completion without recording the token.

### P0-8 — The live Azure deployment is still running, drifting, and billing

Read-only inspection during V5 confirmed:

- the VM is still `running`;
- a public IP remains attached;
- there is no NAT gateway;
- an NSG deny rule was changed manually and is not represented by Bicep;
- there is no automatic shutdown schedule;
- live resource names/topology differ from the IaC conventions;
- an apparently unused ACR remains;
- current Azure budget spend was approximately **$57.40** against a **$60**
  monthly budget, and the VM was still accruing cost.

The committed cost artifact's $64.32 is a list-price estimate over a past
117.56-hour interval, not a live bill. Neither number can be treated as final
while resources continue to run.

**Required change:** choose deliberately between deallocation, deletion, and
continued retention. Preserve needed `/mnt/scratch` evidence first because
deallocation can lose ephemeral data. Then reconcile the intended topology
into Bicep or declare the deployment disposable and delete it. Export a final
cost view after billing settles and update the evidence/date.

**Acceptance test:** no unintended billable resource remains; the final live
inventory matches IaC or a documented disposable-state decision; the public
cost claim distinguishes estimated list cost from invoiced/actual spend.

### P0-9 — Public GitHub and image-distribution controls are not configured

At V5 inspection the repository was private; the GHCR image rejected anonymous
pulls; there was no release or tag, no branch protection/ruleset, no topics or
homepage, and no working private-reporting route. `SECURITY.md` correctly says
there is currently no disclosure channel, but that condition cannot accompany
a serious public security policy.

Four Dependabot PRs were open. One had fresh green checks; the others displayed
older failures and need refresh/review. Code scanning was unavailable without
the relevant GitHub feature; no CodeQL result existed.

**Required change before visibility changes:** enable a monitored disclosure
channel or private vulnerability reporting; configure branch protection or a
ruleset for required exact-commit checks; decide whether GHCR becomes public or
the README documents authenticated pulls; refresh and adjudicate the four
dependency PRs; add repository description/topics/homepage; disable unused
wiki/features; and create the release/tag only after all P0 acceptance checks
pass.

## P1 important defects

### P1-1 — Demo stdout still emits non-standard JSON

A wheel installed into an empty Python 3.12 environment completed the demo and
wrote strict stored JSON. Its `train_complete` stdout event contained literal
`NaN` for both bootstrap bounds. Python's default `json.dumps` accepts that
extension; strict JSON consumers do not.

`io.write_json` has the right normalization/`allow_nan=False` policy, while
`models/train.py` prints the event through a separate bare `json.dumps` path.

**Fix:** route every structured event through one strict serializer that
normalizes NumPy/Pandas missing and non-finite values to `null`; add a test that
parses every JSON-looking demo event with non-finite constants rejected.

### P1-2 — The advertised clean setup and package smoke choose an unsupported interpreter

The package declares `>=3.12,<3.13`, but Makefile `setup` and `package-smoke`
call unqualified `python3 -m venv`. On the audited machine `python3` is 3.14.7,
so a clean `make package-smoke` fails when pip rejects the wheel. The same wheel
installs and runs correctly when the venv is explicitly created with Python
3.12.

**Fix:** introduce one configurable interpreter such as `PYTHON ?= python3.12`,
preflight its exact supported version, and use it for all venv creation. Run
`make package-smoke` in CI from an environment that does not inherit the dev
venv. Keep `twine check` as a release check; both current artifacts pass it.

### P1-3 — Archived run manifests are not held to the new provenance standard

There are 101 archived manifests. Sixty-nine omit `code_tree_sha256`, 69 omit
output hashes, and 47 omit `run_key`. Seven record an unknown SHA and 12 record
an abbreviated SHA. The unknown entries are older/superseded, but abbreviated
SHAs remain in canonical Medium and Large lineages.

The canonical short SHAs inspected by V5 resolve to real commits and the
recorded tree hashes match; the weakness is that the publication gate accepts
any non-`unknown` string rather than proving that relationship for every
canonical manifest.

**Fix:** define a versioned manifest schema. Require full SHAs, code-tree hash,
input identity, configuration, environment/lock identity, and strong output
hashes for canonical current results. Explicitly grandfather only archived
non-canonical evidence, with status and reason. Validate canonical manifests
from Git objects in CI.

### P1-4 — Replay bundles reproduce metrics but do not fully identify lineage

All nine bundles successfully recompute the published budget metrics. Their
metadata now uses full code SHAs and honest legal status. They do not record a
generator script/hash, dataset-pin identity, or a cryptographic identity for
the source score set from which each top-1000 extract was created.

**Fix:** add a versioned bundle schema containing generator provenance,
canonical result-set ID, dataset-pin hash, source score/manifest hash, extraction
parameters, output hashes, and migration history. Rebuild from authoritative
source where possible. If a bundle is metadata-migrated without rebuilding,
state exactly which claims remain unverifiable.

### P1-5 — “Content-addressed” caching omits part of the computation identity

README says every stage is content-addressed. Local directory fingerprints use
path, size, and mtime rather than file content; large outputs may be checked by
size; and run keys omit the Python/dependency environment. A new DuckDB,
Pandas, NumPy, or LightGBM build can change results while the old cache key
still matches. Manifests record Python/platform but not the tested lock digest.

**Fix:** include the relevant lock/container/environment digest in every run
key; content-hash material inputs or qualify the claim as metadata-addressed;
make the integrity level explicit for large files; record dependency and image
digests in manifests.

### P1-6 — Cross-architecture wording still makes an invalid inference

README says matching average precision to 15 significant figures over 12.4M
rows means the score ordering is identical, then says the model behaves
identically. Equal AP and the listed aggregate metrics do not prove full score
ordering or prediction identity. The later paragraph correctly admits there is
no cross-architecture prediction hash.

**Fix:** delete the ordering/identical-behaviour inference and keep only the
supported statement: every metric recorded in both manifests agreed to the
reported precision; model bytes differed; cross-architecture prediction
identity was not measured.

### P1-7 — Release documentation contains stale or false gate descriptions

- README says `make_tables` matches 4–5 decimals and ignores percentages; the
  implementation now considers 3–6 decimals and has a retraction registry.
- `HANDOFF.md` says the zero-unsupported result spans nine documents; the gate
  now scans 13.
- `RELEASE_CHECKLIST.md` says overall source coverage is 75%; V5 measured 76%.
- More importantly, the checklist says the lowest-covered train/eval/stability/
  leakproof paths are "exactly" what the 17 skipped tests cover. They are not.
  The 17 local skips are HI-Small contract/reconciliation prerequisites; fresh
  CI's additional skip is split-inflation determinism. The statement hides real
  untested paths behind an unrelated skip count.

**Fix:** regenerate or directly measure these statements. List skip reasons and
uncovered module risks separately. Do not use skipped tests as evidence that
specific uncovered execution paths would run with data unless the tests
actually invoke those paths.

### P1-8 — The numeric-claim gate remains deliberately untyped

The widened matcher and `RETRACTED.json` materially reduce the known risk and
did catch 43 retired values on its first run. It remains a token-membership
check, not a semantic claim check. It cannot prove that a supported decimal is
attached to the correct dataset, split, model, metric, budget, unit, or seed.
It does not generically validate most integers, currency, durations, and
percentages, and 156 marked values are exempt.

The decision not to perform the full typed rewrite is understandable, but the
residual risk must not be described as eliminated.

**Fix:** migrate headline/current tables to explicit typed references or
generated blocks. A smaller safe first step is a schema mapping each displayed
claim to `(result_set, field, aggregation, formatting)`, with unknown and
superseded IDs failing closed.

### P1-9 — `run_cloud.sh` silently overwrites multi-seed runs

The script exposes `SEEDS`, loops over it, and writes every seed to the same
`/scratch/out/gold/models` destination. Any value other than the default single
seed overwrites prior seed output.

**Fix:** either remove the multi-seed interface or use seed-specific
destinations and an explicit aggregation step, as the large-runner path does.
Test with at least two seeds and assert both manifests/artifacts remain.

### P1-10 — Cloud cost language contradicts its own evidence

The runbook correctly says authoritative charged cost was not measured and the
derived artifact records `actually_charged_usd: null`. It then states "Nobody
was charged anything" as fact. It also refers to both a $180 and a $200 ceiling.

**Fix:** state this as an inference from credit/subscription context, not an
observed charge; use one defined budget/ceiling; timestamp every cost snapshot;
separate list-price estimate, Azure Cost Management spend, credits, and final
invoice.

### P1-11 — The reproducibility entry point is incomplete

README's quick route and `make all` do not recreate every published analysis.
`make full` adds more stages, while split inflation, typology, categorical
ablation, replay bundles, cost, SBOM, and the HI-Large path use separate
commands. A reader cannot tell from one place which command regenerates each of
the 56 result sets and which require unavailable data/cloud state.

**Fix:** publish a result-to-command matrix with input tier, expected runtime,
hardware, outputs, canonical result ID, and determinism tolerance. Provide one
release verification command that checks all locally verifiable artifacts and
reports explicit external prerequisites for the rest.

### P1-12 — Test quality is strong around past defects but thin in core fit paths

Source coverage is 76%, with especially low coverage in `demo.py` (19%),
`eval/run.py` (30%), `models/stability.py` (31%), `models/train.py` (40%),
`leakproof/plant.py` (53%), and `leakproof/sweep.py` (58%). No coverage floor is
necessarily a defect, but these are high-consequence paths, and the present
release checklist mischaracterizes why they are uncovered.

**Fix:** add small synthetic integration fixtures for training, evaluation,
stability, checkpoint/resume, leak planting/sweep, and event serialization.
Set an initially modest source coverage floor only after meaningful assertions
exist; do not chase line coverage without behavioral oracles.

## P2 polish and hardening

### P2-1 — Container/runtime supply-chain hardening is incomplete

The base image and Python wheels are pinned, and fresh dependency audit is
clean. APT packages are not version/snapshot pinned; the DuckDB Azure extension
is fetched without a recorded digest; compiler/build tools and research tooling
remain in the runtime; the runtime lock includes Kaggle/Jupyter/formatting tools;
and there is no signed image, full-image SBOM, or CodeQL result.

Use a multi-stage build, minimize runtime dependencies, pin or attest external
extension inputs, generate an image-level SBOM, scan the final digest, and sign
or attest releases. These are professional hardening items, not evidence that a
known vulnerability currently exists.

### P2-2 — Citation terminology is broader than the implemented split

`CITATION.cff` says "entity-disjoint temporal split." The implementation and
README more precisely say "ring-participant-disjoint." The broader term can be
read as all accounts being disjoint across train and test.

Use the exact term in the citation abstract. The file is otherwise valid CFF
1.2.0.

### P2-3 — The split script contains a stale regeneration note

The script comment says the deterministic-order fix moved the headline from
0.4677 to 0.4682. The committed artifact and current paper report approximately
0.4670. This appears to record an intermediate regeneration rather than the
current canonical output.

Update or remove executable-code comments that quote result values; preferably
derive such notes from the canonical artifact.

### P2-4 — Dataset-version metadata should be checked again

Content hashes remain the strongest identity and are now correctly protected by
the six-file contract. The documentation's suggestion that Kaggle exposes no
immutable dataset version identifier should be verified against the current
Kaggle dataset/version API and recorded metadata. If a version ID exists, store
it in addition to—not instead of—the file hashes.

### P2-5 — Archive and lint boundaries need a release sanity check

The configured lint run checks all 19 current-facing Markdown files and passes.
It deliberately excludes the tracked `docs/archive/**` and paper archive, which
is reasonable for preserved records. Local council transcripts and `Learning/`
are ignored and untracked, so they will not be published from a clean clone.

Keep that boundary explicit in the release process: build the release from a
clean clone, verify the tracked-file inventory, and ensure every document that
is current-facing remains within the lint/link/number gates. No history rewrite
is needed for the ignored local material because it is not in Git.

### P2-6 — Git history contains personal/local author identities

Many historical commits use machine-local hostname addresses, and a smaller
set uses an institutional address. This is not a secret-scanning failure, but it
is a privacy and professional-presentation decision that becomes permanent once
the repository is public.

Review authorship before publication. Rewrite history only if the owner accepts
the coordination consequences; otherwise add `.mailmap` and ensure future Git
configuration uses the intended public identity.

### P2-7 — Repository metadata and release artifacts are incomplete

There is no public release/tag yet, and no version/date in CFF because the
project is pre-release. That is internally reasonable. Before launch, create a
versioned tag, populate CFF version/date, produce release notes, attach checksums
and SBOMs, add topics/homepage, and verify every README link and pull/install
command anonymously after visibility changes.

### P2-8 — Dependabot updates need deliberate review

Four dependency-action PRs were open during V5. Do not merge solely because
they are automated. Refresh each on current `main`, require the same CI/gate/
image checks, review major-version behavior, then merge or close with a recorded
reason.

## Results and method assessment

### What is strong

- The project asks a useful operational question: performance under finite
  alert budgets, not merely ROC-AUC.
- It distinguishes transaction, account-day, and ring units and reports
  ceilings, tie sensitivity, null expectations, and ring coverage.
- The ring-participant split and explicit naive-split counterfactual expose how
  evaluation design changes conclusions.
- The HI-Large run is meaningful evidence of engineering scale: approximately
  179.7 million rows on a documented single Azure VM.
- Historical retractions and registries show real scientific self-correction.
- Nine compact replay bundles let a reviewer independently recompute key budget
  metrics without redistributing the full dataset—subject to the unresolved
  legal question.
- Current result documents are internally far more consistent than V4: the
  479-token gate found no unsupported, superseded, or retracted decimal.
- The newly deterministic split loader addresses a subtle, real source of
  nondeterminism that ordinary fixed-seed testing missed.

### What remains scientifically limited

- The principal evidence comes from one synthetic benchmark family; external
  validity to real investigator queues remains unestablished.
- HI-Medium confirmation of the split-inflation analysis has not been rerun in
  the current environment.
- The categorical-ablation Medium artifact was provenance-repaired without a
  fresh data rerun because its features are unavailable locally. That fact is
  now disclosed and should remain visible.
- The split decomposition is assumption-dependent and not a causal
  identification of leakage.
- Cross-architecture evidence establishes matching recorded metrics, not
  identical predictions or score order.
- Seed/run variability and confidence intervals do not substitute for dataset
  diversity.

These are acceptable research limitations when stated precisely. The problem
is not having limitations; it is allowing a headline to outrun them.

## Reproducibility ladder

| Level | Current status | Remaining work |
|---|---|---|
| No-data demo | Runs from clean Python 3.12 wheel | strict stdout JSON; interpreter selection |
| Unit/property tests | Green locally and remotely | cover core fit/stability/leak paths |
| Published-number consistency | Green for configured decimals | typed claim binding and broader formats |
| Replay metric recomputation | Green for nine bundles | legal review and full lineage |
| Dataset identity | Correct six-file fail-closed contract | record upstream version metadata if available |
| Derived artifact code identity | generator 10/10; tree 9/9 | enforce dirty imported code; inputs/parameters |
| Full Medium rerun | Not currently possible locally | reacquire verified features/raw data and execute matrix |
| Full Large rerun | Requires live cloud/data | clean source archive, reconciled IaC, final command matrix |
| Container reproduction | Tested image succeeds | publish that exact tested digest |

## Recommended fix order

Do not perform another broad rewrite. Close the release in this order:

1. **Contain external risk now:** rotate the Kaggle token; preserve any needed
   ephemeral Azure evidence; deallocate/delete or explicitly retain the VM;
   capture the final inventory and cost.
2. **Resolve redistribution:** obtain the replay-bundle legal decision or
   remove/replace the bundles before any public push.
3. **Repair provenance once:** make package-tree cleanliness, inputs,
   parameters, lock/image identity, and cloud source-to-commit identity fail
   closed. Add mutation tests at the imported-module and input levels.
4. **Make the image release atomic:** build once, test once, push the same
   digest; attach SBOM/provenance and verify anonymous pull policy.
5. **Correct current truth:** archive/rewrite `FEATURE_SPEC_v1.md`; narrow the
   split claim; remove cross-architecture inference; correct coverage, gate,
   cost, and document-count statements.
6. **Fix user-facing workflows:** strict event JSON; explicit Python 3.12;
   multi-seed output isolation; one result-to-command reproduction matrix.
7. **Harden canonical evidence:** full-SHA/schema checks for current manifests
   and complete replay lineage; leave old non-canonical evidence clearly
   grandfathered rather than pretending it was regenerated.
8. **Prepare public GitHub:** resolve Dependabot PRs, configure security and
   branch rules, set metadata, decide GHCR visibility, cut a clean versioned
   tag, and run an anonymous-reader smoke test.

## Final release checklist

The repository is publishable only when every item below is true on one clean,
pushed, tagged SHA:

- [ ] All P0 items above are closed with their acceptance tests.
- [ ] Worktree is clean and `HEAD == origin/main == release tag`.
- [ ] Local/CI/image suites pass and skip reasons are reviewed.
- [ ] Artifact generation fails for dirty generator **or imported package**
  code and records inputs, parameters, and environment identity.
- [ ] The deployed source archive is proven to correspond to its claimed Git
  commit.
- [ ] The tested image digest is exactly the pushed release digest.
- [ ] Stored files and structured stdout contain no non-standard JSON values.
- [ ] Setup/package-smoke use a verified supported interpreter and run in CI.
- [ ] Current documents contain no live `txn_id` blocker, causal leakage
  overclaim, cross-architecture identity claim, stale counts, or contradictory
  cost ceiling.
- [ ] Replay-bundle redistribution is approved or the bundles are removed.
- [ ] Kaggle credential rotation is completed and verified.
- [ ] Azure state is intentionally stopped/deleted or fully reconciled and the
  final cost statement is timestamped and correctly qualified.
- [ ] GitHub has a disclosure channel, branch protection/ruleset, reviewed
  dependency PRs, intended repository features, and a working anonymous install/
  pull path.
- [ ] Release tag, CFF version/date, release notes, checksums, SBOM/provenance,
  and public links all point to the same release.

## Bottom line

Claude's V4 remediation closed most of the defects it targeted, including the
worst dataset-pin failure and the derived-generator/Git-object mismatch. It
also uncovered and fixed a genuine nondeterminism issue that the earlier audits
missed. That is substantial progress.

The project is still **not finished**. Its numerical archive is presently in
good shape; the remaining highest risk is at the boundaries between claims and
evidence: imported-code provenance, deployed-source provenance, tested-versus-
pushed image identity, causal wording, a contradictory current specification,
and owner-controlled legal/security/cloud decisions. Close those boundaries,
then do one exact-SHA release verification. Another general rewrite is not
needed; a disciplined release-hardening pass is.
