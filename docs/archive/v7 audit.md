# V7 publication-readiness audit

- **Repository:** AML Evaluation Harness
- **Audit date:** 2026-09-15 (America/Denver)
- **Audited branch:** `main`
- **Audited commit:** `8e34620c1c8e74790d4f1df92e2dc8be6e7d7132`
- **Observed `origin/main`:** `8e34620c1c8e74790d4f1df92e2dc8be6e7d7132`
- **Initial tracked worktree:** clean
- **Decision:** **not ready to make public or tag as a release**
- **Code/result changes made by this audit:** none; this report is the only intended addition

## Executive verdict

Claude closed most of the mechanical V6 findings correctly. This is now a
serious research repository, not a prototype wearing release documentation:

- the complete local `make release-check` passes;
- 336 tests pass and 17 correctly skip without built HI-Small intermediates;
- source coverage is 78%, with the scientific metric and split modules above
  90%;
- all current GitHub `ci`, `gates`, and linux/amd64 `image` runs are green at
  the audited SHA;
- the tested image is the image that was pushed, and its digest was pulled back
  and checked;
- all nine replay bundles recompute their published budget metrics;
- the six-file dataset contract is still intact and fails closed when the local
  HI-Large CSV is absent;
- 517 decimal claims across 13 current documents pass the existing numeric
  gate; and
- the wheel and sdist build, pass `twine check`, install into an empty Python
  3.12 environment, and run the real demo through the installed console entry
  point.

That evidence is strong. It is also not the same as release readiness. V7 found
four classes of publication blocker and several places where a new guard still
checks something weaker than the claim attached to it.

The blockers are:

1. **the replay bundles' redistribution status is unresolved**, and the public
   wording simultaneously says readers have “no CDLA obligation” and that the
   legal conclusion is unreviewed;
2. **the supposedly withdrawn simulator-attribution claim remains current** in
   README and paper prose, despite no measured denominator or attribution
   design;
3. **the Azure estate is still running and billing**, differs from the Bicep,
   has no shutdown schedule, and has passed its notification-only budget; and
4. **the GitHub launch controls are not in release state**: private repository,
   no ruleset or branch protection, no code scanning, no working private
   disclosure route, private GHCR image, six unresolved Dependabot PRs, no tag,
   no release, and no recorded decisions on token rotation or author emails.

No new error was found in the core metric arithmetic or the canonical
HI-Large/HI-Medium values. The remaining scientific problem is claim scope; the
remaining technical problems are guard semantics, exact environment identity,
prediction identity, supply-chain completeness, and release operations.

## How complete is it?

These percentages are audit judgements, not generated measurements. A hard
blocker is not averaged away by strong engineering elsewhere.

| dimension | completion | judgement |
|---|---:|---|
| Scientific methods and honesty | **84%** | Strong nulls, ceilings, negative controls, seed ranges and retractions; still one unsupported simulator-attribution conclusion, one stale ensemble decision, no external/real-world validation, and n=1 at the generator-run level |
| Core technical implementation | **88%** | Pipeline, storage abstraction, failure semantics, deterministic ordering and behavioural tests are strong; cache/environment and prediction-digest guarantees remain weaker than described |
| Results integrity | **91%** | Canonical values, lineage registry, replay and counterfactual checks are strong; one central ablation remains grandfathered and the publication checker is not semantically typed |
| Reproducibility | **82%** | Excellent replay path and dataset pin; the full raw-data rebuild is not locally available, installed environment is not in cache identity, and one claimed behaviour hash does not hash the stored/evaluated representation |
| Testing | **85%** | 353 collected, 336 pass, 17 expected skips, 78% coverage; several orchestration-heavy modules remain below 65%, and some important regression tests inspect source text/counts rather than behaviour/identity |
| Packaging and container | **82%** | Build/install/demo and tested-image publication work; build isolation resolves an unpinned backend, the image SBOM is Python-only, and there is no image signing or vulnerability gate |
| Cloud engineering | **72%** | A genuine 179.7M-row run and careful failure record are impressive; live state is not reproducible from Bicep and lifecycle/cost closure is unfinished |
| Security and public-release operations | **60%** | Full-history secret scan and SAST are useful; disclosure, branch rules, CodeQL, dependency triage, image visibility/signing/scanning and credential confirmation remain open |
| Documentation and presentation | **82%** | Exceptionally candid and detailed, with a useful figure and pipeline diagram; current contradictions, stale counts and remediation archaeology still obscure the clean story |
| **Overall project completion** | **about 82%** | The research harness is mostly complete; the public release is not |
| **Public GitHub release readiness** | **about 65%** | Four hard launch decisions plus the high-priority technical/claim corrections below remain |

## Audit scope and limits

This pass reviewed all 376 tracked files, the source package, tests, scripts,
Make targets, four dependency locks, package metadata, Dockerfile, workflows,
Bicep, current and archived results, replay bundles, generated figures,
licensing, security policy, Git history, current GitHub settings/runs, and live
Azure state.

The audit deliberately reused expensive evidence where the relevant code or
artifact had not changed. It did not repeat the V6 30-minute, five-seed,
400-draw counterfactual regeneration merely to consume compute; the post-V6
changes and current regression suite cover its deterministic ordering, and the
committed artifact still verifies against its generator and package tree. It
also did not refit HI-Medium or HI-Large. `HI-Large_Trans.csv` is not on this
machine, so the full six-file data gate cannot pass here; five available files
were checked with zero mismatches and the sixth is still present in the
six-name contract and pin.

No Azure, GitHub, package, token, repository, branch, or security setting was
changed.

## Verification performed

### Local repository and release path

| check | result |
|---|---|
| HEAD equals `origin/main` | pass, exact SHA above |
| Initial tracked worktree | clean |
| Ruff over `src`, `tests`, `scripts` | pass |
| Full local pytest | **336 passed, 17 skipped**, 4 deprecation warnings |
| Source coverage | **78%**, 2,227 statements / 496 missed |
| `make release-check` | pass end to end |
| Storage abstraction | 10 passed |
| Derived provenance regression subset | 5 passed |
| Replay subset | 11 passed |
| Publication checker | **517 checked**, 174 marker-exempt, 0 reported unsupported/unprovenanced/superseded/retracted/missing |
| Result collection | 56 result sets, 0 malformed |
| Release-facts verification | 353 collected, 17 skipped, stable fields match |
| Local links/table structure | 48 Markdown files, 98 local links, 0 malformed tables |
| Markdown style | 18 current files, 0 errors |
| Figure check | committed SVG agrees with the four archive summary values it checks |
| Package smoke | sdist + wheel built; both pass `twine check`; wheel install, CLI and demo pass |

The four warnings are all the same DuckDB deprecation:
`fetch_record_batch()` should become `to_arrow_reader()`. It is not a current
failure, but it is a small forward-compatibility debt.

Coverage is sensibly concentrated around the scientific core:

- `eval/metrics.py` 95%;
- `splits/ring_aware.py` 92%;
- `features/build.py` 92%;
- `features/online.py` 99%;
- `eval/run.py` 100%; and
- `drift/experiment.py` 99%.

The remaining low modules are `demo.py` 19%, `models/stability.py` 31%,
`leakproof/plant.py` 51%, `leakproof/sweep.py` 57%, `models/train.py` 59%, and
`manifest.py` 63%. The end-to-end demo executes some of these paths, but it
does not turn unasserted execution into behavioural coverage.

### Current GitHub evidence

At the audited SHA:

| workflow | run | result |
|---|---:|---|
| `ci` | 34931720285 | success |
| `gates` | 34931720338 | success; Bicep compile, pinned-action check, full-history Gitleaks, Bandit baseline and Markdown checks pass |
| `image` | 34931720220 | success; **327 passed / 26 skipped** inside linux/amd64 |

The image run recorded:

- tested local image id
  `sha256:ff81917a6eeabfde1c94a271b4b362775b0384256b876d19239e0cdb40bcd273`;
- published digest
  `sha256:098e21b4a7117f69903956b16f9489a6ad25c53e6683e0cf9c552b75cdab7e39`;
- successful pull-back identity check; and
- `ANONYMOUS PULL: DENIED` for the current GHCR package.

Current repository settings observed read-only:

- repository is **private**;
- no repository rulesets;
- `main` is not protected;
- code scanning is not enabled;
- private vulnerability reporting endpoint is unavailable;
- no tag and no GitHub Release;
- six open Dependabot PRs (#1, #2, #4, #5, #6 and #7); and
- the Docker update PR proposes Python 3.14 even though the package explicitly
  supports only Python 3.12, so the update mechanism needs configuration or
  triage rather than blind merge.

The full-history secret scan is green over the current 130 commits. That does
not prove a credential pasted into an external chat was rotated.

### Live Azure evidence

Read-only queries on 2026-09-15 found:

- resource group `aml-rg` still exists with 10 resources;
- `aml-vm` is **running**;
- a static public IP remains attached (address redacted: it is the live VM's, and this file ships publicly);
- the custom TCP/22 rule is `Deny` from `*`;
- no NAT gateway exists in the live group;
- no `Microsoft.DevTestLab/schedules` shutdown resource exists;
- both managed disks are attached;
- the unused Basic ACR still exists; and
- budget `aml-guard` is `$60`, while Azure Cost Management reported
  `$61.375188826828555` current spend.

The runbook's `$60.61` value is a timestamped earlier reading, not the same
thing as the list-price estimate, and correctly says the snapshot is
provisional. The resource continues to move both numbers.

### Dataset and replay evidence

- Five locally present source files match their six-file pin; zero mismatches.
- `HI-Large_Trans.csv` is absent locally, and `--require all` reports it as the
  one required missing file.
- The contract still names all six files and retains the 17 GB file's recorded
  SHA-256 rather than silently deleting it during a local repin.
- Nine replay bundles contain 45 Parquet files and **526,355 total rows** by
  Parquet metadata:
  - 335,269 top-ranked account-days;
  - 71,604 ring-membership rows;
  - 79,264 ring endpoints;
  - 39,632 ring transactions; and
  - 586 per-day-positive rows.
- All replay tests pass and recompute the published budget metrics.

## P0 — blockers before public visibility or a release tag

### P0-1 — The replay-bundle legal position is unresolved and the public wording contradicts itself

`DATA_LICENSE.md:80-93` correctly says whether the bundles are CDLA “Results”
or redistributed Data is a legal judgement that has not been reviewed. Every
bundle records `licence_status: UNREVIEWED`, and both licence notices now ship
with the image. Those are genuine improvements.

The contradiction remains in `README.md:575`: it says a reader needs “no CDLA
obligation” and, in the same table cell, says whether the row-level bundles may
be redistributed is unreviewed. The first clause is a legal conclusion; the
second says the project is not qualified to make it. A clone and image already
deliver the files to the reader, so the question is not hypothetical.

The inventory is also inconsistent. `DATA_LICENSE.md:6-9` says roughly 446,466
rows, while the actual 45 Parquet files contain 526,355 rows and README/package
copy says roughly 526,000. A legal notice must accurately inventory the data it
describes.

**Required before publication:** obtain a dated qualified determination, or
remove the replay Parquet from public Git and OCI distribution
until one exists. Until then, remove “no CDLA obligation,” use one generated
inventory count, and retain the unreviewed warning everywhere.

### P0-2 — The unmeasured simulator-attribution claim survived its own retraction

The defensible measurement is clear:

- logistic `precision@50 = 0.57060` on this representation and operating point;
- eight-seed GBDT mean `0.82480`, observed range `0.59144-0.89815`.

The repository correctly says this does not measure what share of separability
is linear. It then reintroduces essentially the same attribution:

- `README.md:49-50`: a headline number is “substantially a property of the
  benchmark”; the line is marked `historical` even though the sentence is
  presented as the current defensible reading;
- `paper/RESULTS_hi_large.md:396-398`: a strong score “is substantially a
  property of IBM's simulator”; and
- `docs/LIMITATIONS.md:501-502`: the increment from model complexity “is small
  here.”

The average GBDT-minus-logistic precision difference is approximately 0.254,
with observed seed-specific differences from 0.021 to 0.328. Calling the
increment “small,” or attributing an undefined substantial share to the
simulator, needs a scale, denominator and attribution design that do not exist.
The marker on the README line also makes the phrase gate exempt the current
sentence rather than reject it.

`CITATION.cff:29-34` remains softer but still leads with “the headline result is
about the benchmark rather than about a model.” That is an interpretation, not
a directly measured estimand.

**Required before publication:** make the headline and claim boundary purely
measured. It is valid to say the baseline is strong on this representation and
therefore model-only comparisons need that baseline. Do not assign an
unmeasured fraction of the result to the simulator or call the average model
increment small. Extend the retracted-phrase registry so a renamed version of
the same inference cannot pass.

### P0-3 — Azure lifecycle and final cost are still open

The docs accurately admit the live group differs from Bicep, but disclosure is
not closure. The VM is running, the public IP and unused ACR remain, there is no
NAT gateway or shutdown schedule, and the notification-only budget has been
exceeded. The checked-in Bicep would build a different topology.

This also prevents a final `cost.json`: `snapshot_is_final` is correctly false,
and the list-price table continues to grow. `README.md:577` still says “about
$64 at list price,” while the one current cost table says `$68.92` and the
README itself says cost is stated in exactly one place. The `derived` marker
exempts the stale README line from the numeric gate.

**Required before publication:** decide whether the estate is retained or
deleted. If retained, reconcile it into IaC, remove unnecessary public/registry
resources, add an intentional lifecycle control, and record the reason. If
deleted, verify zero daily spend after the documented window. Then create the
final cost snapshot with an explicit stop time and remove copied totals from
other current documents.

### P0-4 — GitHub/security/release state is not ready

The repository cannot yet meet its own release checklist:

- it is private;
- `main` has no protection and there is no ruleset requiring `ci`, `gates`, and
  `image`;
- code scanning and secret push protection are not enabled;
- there is no working private disclosure route;
- GHCR is not anonymously pullable and README does not state an authenticated
  pull procedure;
- six dependency PRs are open and some are stale/red rather than triaged;
- there is no signed tag or GitHub Release;
- 130 commits are unsigned;
- two author email identities remain in raw history and no accept/rewrite
  decision is recorded; and
- rotation/failure of the previously pasted Kaggle token is not evidenced.

Some settings can only sensibly be enabled at the public transition. That does
not make them complete now; it makes publication a controlled sequence, not a
button click.

**Required before publication:** rotate and verify the old token fails; record
the history/authorship decision; fix the always-on required-check issue in
P1-4; triage dependency PRs; choose GHCR visibility/auth documentation; then
make public, enable the security features and disclosure route, apply a
ruleset, verify from a logged-out account, and create a signed release tag.

## P1 — high-priority technical and scientific corrections

### P1-1 — The cache keys the declared environment, not the installed environment

`manifest.env_id()` is the requirements-lock digest plus Python patch version.
That is useful declared-environment identity, but it does not change if someone
runs with a different installed NumPy, DuckDB or LightGBM while leaving the
lock file untouched.

`installed_matches_lock()` is evaluated only when a new manifest is written at
stage exit. A cache hit occurs earlier in `cached_or_none()` and returns the old
metrics without creating a new manifest. Therefore a mismatched installed stack
can still receive an old cache hit, and the record beside that hit continues to
describe the old run's environment. The new test changes `env_id()` by
monkeypatch; it never simulates an installed/declared mismatch.

There is a second fail-open edge: if one of `NUMERIC_DEPS` is absent from the
lock, `installed_matches_lock()` skips it instead of reporting the lock entry as
missing.

This gap is already admitted in `HANDOFF.md:379`, while README lines 189-195,
`CHANGELOG.md`, and comments in `manifest.py:789-793` contradict one another
about whether dependency identity is in the key.

**Required change:** either fail before cache lookup unless the installed
numeric stack matches a complete lock, or include an identity of the actual
installed numeric distributions/interpreter/platform in the key. Add a
behavioural test where installed identity changes while the lock stays fixed
and prove the cache misses or refuses.

### P1-2 — `predictions_sha256` does not hash the stored or evaluated predictions

`models/train.py` evaluates the raw estimator output and writes that raw
`score` array to Parquet. LightGBM/sklearn probability output is float64, and a
direct probe confirms the resulting Parquet field is `double`.

The manifest instead hashes `np.asarray(score, dtype=np.float32).tobytes()`.
Thus the field intentionally ignores float64 differences, does not hash the
Parquet representation, and does not include `txn_id`. Yet README and
LIMITATIONS call matching hashes “bitwise-identical predictions” and say this
digest would settle cross-architecture identity.

The regression test at `tests/repro/test_audit_regressions.py:356-377` checks
only that the source contains the strings `predictions_sha256` and
`dtype=np.float32`. It does not compute a score file and verify the digest. This
is precisely the weaker-than-the-defect test pattern the contributing guide
warns against.

**Required change:** choose one canonical prediction representation. Either
cast once to float32 and use that same array for evaluation, persistence and
hashing, or retain float64 and hash the ordered `(txn_id, dtype, score)` payload
that is actually stored. Call a quantized hash a tolerance digest, not bitwise
identity. Replace the source-text test with a behavioural mutation test.

### P1-3 — The publication gate remains token membership, and current drift demonstrates the gap

The checker is candid that it cannot bind a number to a nearby metric, model,
unit, seed aggregate or lineage. Widening the regex and adding retractions
helped, but did not make it semantic. Current examples that pass all gates:

- HANDOFF says 479 checked values; the current check reports 517;
- HANDOFF says the full-history scan covered 57 commits; current history has
  130;
- HANDOFF says four Dependabot PRs; GitHub currently has six;
- `DATA_LICENSE.md` says approximately 446,466 replay rows; actual total is
  526,355; and
- README says about $64 at list price while the sole current table says $68.92.

Integers are mostly outside the metric matcher, and 174 decimal tokens are
explicitly exempted by markers. A `historical` marker on the same line as a
current conclusion exempts the whole line.

**Required change:** introduce typed claim references such as
`(artifact, lineage, metric, unit, aggregation, display precision)` and generate
tables/counts from them. Maintain a much smaller reviewed exemption file with a
reason and owner. At minimum generate repository/PR/replay counts rather than
copying them into prose.

### P1-4 — The image check is still not always present on pull requests

`.github/workflows/image.yml:20` says there is no path filter. The
`pull_request` trigger at lines 35-38 still filters to `aml-platform/**` and the
workflow file. A root-only README, licence, security, CFF, or release change
will not get an `image` status. If `image` is then made required as the release
checklist demands, such a PR waits for a status that can never appear.

**Required change:** remove the PR path filter, or make an always-triggered
workflow publish a stable required status while conditionally skipping only the
expensive build job. Test with a root-only PR before enabling the ruleset.

### P1-5 — The release build backend is still resolved outside the release lock

`requirements-release.lock` pins `build` and `twine`, but `python -m build`
uses build isolation. The successful audit log explicitly says:

```text
Creating isolated environment
Installing packages in isolated environment:
  setuptools>=77
Installed build dependency versions:
  setuptools==84.0.0
```

`setuptools==84.0.0` is not in the release lock; `pyproject.toml` asks for
`setuptools>=77`. The target also upgrades pip without a pin. Therefore “the
build tools come from a lock” is only partly true and the same source may build
with a different backend on another date.

**Required change:** pin the backend and wheel tool, preferably with hashes,
and build with a pre-created locked environment plus `--no-isolation`, or use a
locked tool that honours a build-constraint file. Keep the separate clean-wheel
install; that check is valuable.

### P1-6 — The SAST baseline detects count changes, not new findings

`check_sast.py` stores only counts per Bandit rule (`B310: 1`, `B608: 50`). If
one old B608 is fixed and a new B608 is introduced elsewhere, the total remains
50 and the gate passes. The documentation says a new finding fails; this
implementation proves only that the per-rule count did not change.

**Required change:** baseline stable finding identities—rule plus normalized
path and code/context fingerprint—or compare the full Bandit result after
normalizing volatile fields. Add the fix-one/add-one mutation test.

### P1-7 — Canonical provenance enforcement has two sources of truth

`CANONICAL.json` says unlisted lineages default to canonical. The stronger test
for full 40-character SHA plus package-tree equality uses a separate hard-coded
`CANONICAL_LINEAGES` set in the test. `make_tables._provenanced()` itself accepts
any non-`unknown` SHA and status `ok`; it does not verify tree identity.

A new unlisted result can therefore be treated as canonical by the publication
checker without automatically joining the set held to the stronger provenance
standard. The current named canonical lineages pass, but the release mechanism
can regress by omission.

**Required change:** derive the provenance-enforcement set directly from one
typed registry, and require every artifact eligible to support a current claim
to meet the same SHA/tree/input standard.

### P1-8 — The central Medium categorical ablation remains grandfathered evidence

`categorical_ablation_medium.json` supports the defence of the linear-baseline
headline. Its generator blob matches the expanded commit SHA, but it lacks
`code_tree_sha256`, dependency identity, declared inputs, parameters and clean
scope. The metadata note openly says the experiment was not rerun.

That disclosure is honest. It also means there is no evidence that the package
actually imported during the run was the package at the recorded commit. The
live VM may still contain the required features, but this audit did not mutate
or use it.

**Required change:** before treating the ablation as release-grade evidence,
rerun it from the pinned Medium inputs under current provenance/environment
rules, preferably before Azure teardown. If it cannot be rerun, narrow the
claim to “historical result with partial provenance” rather than using it to
close the encoding confound.

### P1-9 — The ensemble-size decision is based on a table the document says is biased

`paper/RESULTS_metric_stability.md:77-105` prints the old prefix-order curve,
labels three seeds “saturated,” then acknowledges that seed 0 was atypical and
the curve is one arbitrary ordering. It says current code averages four
orderings, but the available corrected `typology_Medium/stability.json` artifact
was produced with 12 orderings, and the displayed decision table was not
regenerated from either corrected artifact.

The same section says “Decision: N = 4 for the 182M-row run,” while the released
HI-Large result uses three seeds under a separately documented cost exception.
The science is not invalidated, but the decision trail is internally stale.

**Required change:** generate one canonical ensemble-size artifact using the
current algorithm, display its mean and range across orderings, define the
plateau rule numerically, and reconcile the planned N=4 with the executed N=3.

### P1-10 — Container/software supply-chain coverage is incomplete

The Python wheel lock is hashed and the base image is digest-pinned, which is
good. Remaining gaps:

- the SBOM lists 63 Python components only—not Debian packages, the base image,
  the DuckDB extension, or a complete final-image filesystem inventory;
- no vulnerability scanner gates the final image;
- no signature or provenance attestation is published;
- APT repositories and the DuckDB extension are mutable build-time inputs;
- the image installs the project editable rather than as the release wheel;
- the base is Python 3.12.3 and the automated Docker update currently jumps to
  unsupported Python 3.14 rather than maintaining the 3.12 line; and
- the job grants `packages: write` at job scope even on pull requests, although
  only login/push steps need it on trusted pushes.

**Required change:** create a release image from a pinned wheel in a multi-stage
build, generate an image-level SBOM, scan the exact tested digest, publish an
attestation/signature, constrain Dependabot to the supported runtime line, and
separate PR validation from the package-write job.

### P1-11 — Important orchestration modules still have shallow behavioural coverage

Overall 78% is respectable, and the core metric/split logic is strong. The
remaining low-coverage modules include the expensive experiment orchestrators
where earlier defects repeatedly occurred. `manifest.py` is particularly
important: most of `generator_provenance`, error branches, and remote/cache
edges are not covered by line coverage despite many source-inspection tests.

**Required change:** prioritize behavioural tests for cache/environment refusal,
prediction-file identity, stability orchestration, leak sweep failure paths,
manifest failure/remote paths, and the full CLI parser. Do not chase 100%; close
the mechanisms named in P1-1, P1-2, P1-6 and P1-7.

## P2 — writing, maintenance and presentation issues

### P2-1 — Current prose and comments still contradict the implementation

Examples:

- README lines 189-190 say the cache does not key on the dependency environment;
  lines 192-195 immediately say the run key includes environment identity.
- `CHANGELOG.md` still says it does not key on the dependency environment “at
  all.”
- `manifest.py:789-793` says the run key does not include the lock even though
  `env_id()` includes its digest.
- `_ranks()` says its cache is keyed by length, while it now uses a content
  token.
- `infra/main.bicep:1` says “storage, a registry, and nothing else” before
  defining network, VM and disks.
- `SECURITY.md` says “No inbound rules on the VM”; the live NSG has a custom
  inbound rule whose access is Deny. “No allowed inbound path” is accurate.
- HANDOFF says four Dependabot PRs, 57 commits and 479 checked values; current
  state is six, 130 and 517.

These should be corrected after the substantive decisions so the numbers do
not churn again.

### P2-2 — The figure check is still a token-presence check

`make_figures.py --check` looks for four three-decimal summaries somewhere in
the SVG. It does not compare a normalized regenerated SVG, validate the JSON
companion, bind labels to marks, or verify the eight individual seed positions.
Different seed values with the same min/mean/max could pass.

**Suggested change:** produce a deterministic figure model JSON, validate all
seed/value/label bindings, and render SVG from that model. Compare the model
exactly and the SVG structurally or after removing only volatile provenance
fields.

### P2-3 — The primary narrative is still dominated by remediation history

The candid failure record is one of the repository's strengths, but README,
HANDOFF, LIMITATIONS and result papers repeatedly narrate every previous wrong
version inline. That makes it difficult for a new reader to distinguish the
current method, current result and historical lesson without reading hundreds
of lines.

For a strong GitHub launch:

1. keep README focused on the current question, one figure, one result table,
   quick start, reproducibility tiers and claim boundary;
2. move the detailed correction chronology into CHANGELOG and archived audit
   pages;
3. keep only corrections that materially change interpretation beside current
   results; and
4. add a compact “what is novel/useful” section: alert-unit definition, budget
   ceiling, within-day ring null, split sensitivity, seed instability and replay
   verification.

### P2-4 — Release metadata is correctly withheld but still incomplete

`CITATION.cff` correctly has no version/date until a release exists. Before the
first tag, add the final version/date, release notes, tested image digest,
artifact checksums, and an archival DOI if the project is intended as a
research artifact. A DOI is not necessary for GitHub publication, but it would
materially improve citability.

## Scientific assessment

### What is genuinely strong

- The alert unit, daily budget, ceiling and unit distinctions are explicit.
- `ring_recall` is no longer interpreted without a within-day permutation
  null, two tails and negative-control reasoning.
- The split is accurately called ring-participant-disjoint rather than entity
  disjoint.
- The training row-order failure is understood at the histogram-bin mechanism,
  fixed with a deterministic sort, and evidenced by matrix hashes.
- Seed instability is reported rather than averaged away.
- Split-inflation claims distinguish prevalence composition from score
  distribution and avoid identifying leakage causally.
- Typology results are tested against model-conditional nulls and scoped to the
  available rungs.
- Graph-feature claims are narrowed to the actual one-hop/time-series features
  tested.
- Retractions remain visible, which is unusually good scientific practice.
- Replay bundles make exact metric verification possible without a 20+ GB
  dataset download.

### What the project can claim now

- On this pinned AMLworld HI-Medium run, representation and account-day unit,
  logistic precision@50 is 0.57060 and the eight-seed GBDT mean is 0.82480 with
  range 0.59144-0.89815.
- Budget metrics are far more seed-sensitive than ROC-AUC on this fixed run.
- Ring recall greatly exceeds account-day recall, and under the implemented
  within-day null the canonical Medium/Large models cover slightly fewer rings
  than chance allocation of the same daily score multiset.
- A naive and ring-aware test protocol report materially different quantities;
  the sign and size depend on the metric.
- The implemented counterparty-count features add no useful information on the
  tested Small run and often degrade the paired result.
- The pipeline and current metrics are reproducible through the documented
  checkout/replay paths, subject to the environment and digest qualifications
  in this audit.

### What it still cannot claim

- real-world AML effectiveness or production readiness;
- that a substantial share of performance belongs to the simulator;
- that model complexity adds only a small amount;
- calibration, investigator utility, case/SAR conversion, reason-code quality,
  fairness, governance or regulatory validation;
- generator-run uncertainty or population-level confidence intervals;
- full entity disjointness;
- that any typology is universally easiest/hardest;
- cross-architecture bitwise prediction identity; or
- legal permission for others to redistribute the replay rows.

## Recommended closure order

1. **Immediately rotate the Kaggle token and record verification.**
2. **Resolve the replay-bundle licence decision.** Remove bundles temporarily if
   qualified review will not happen before publication.
3. **Stop or intentionally retain Azure.** If the required Medium ablation is
   still reproducible only there, rerun it under current provenance before
   teardown. Produce the final cost snapshot afterwards.
4. **Remove the unsupported simulator-attribution/small-increment language.**
5. **Fix actual environment identity and prediction identity**, with behavioural
   tests.
6. **Replace the remaining weak gates:** always-on image PR status, typed claim
   references, identity-based SAST baseline, one-source canonical provenance,
   locked build backend.
7. **Regenerate only affected artifacts** and rerun `make release-check` from a
   clean clone plus the linux/amd64 image workflow.
8. **Triage the six Dependabot PRs and add image scan/SBOM/signing.**
9. **Execute the public transition as one checklist:** history/authorship
   decision, visibility, disclosure route, security features, ruleset, GHCR
   access, signed tag, release notes and digest.
10. **Verify anonymously:** clone, links, vulnerability form, image pull, wheel
    install and demo.

## Final answer

**No, everything is not done.** The code and scientific machinery are mostly
complete and substantially above the standard of an ordinary portfolio
repository. The project is useful and technically impressive. Its strongest
idea is not the model score; it is the combination of budget-aware metrics,
explicit ceilings/nulls, reproducible replay, and a documented record of how
apparently reasonable evaluation choices failed.

But it should not be made public or tagged today. The legal distribution
question, unsupported headline attribution, live cloud lifecycle and GitHub
launch controls are hard blockers. The cache/environment and prediction-digest
issues are the most important remaining code corrections. Once those items are
closed, the project is plausibly one disciplined release pass—not another
research cycle—away from publication.
