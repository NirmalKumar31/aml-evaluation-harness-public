# V6 publication-readiness audit

- **Repository:** AML Evaluation Harness
- **Audit date:** 2026-09-14 (America/Denver)
- **Audited branch:** `main`
- **Audited commit:** `9a84eaeef3bc241d66ebe6ee070aaa8f68846de0`
- **Observed `origin/main`:** `9a84eaeef3bc241d66ebe6ee070aaa8f68846de0`
- **Initial worktree:** clean
- **Decision:** **not ready to make public or tag as a release**

## Executive verdict

Claude fixed a large amount of the V5 surface correctly. The repository is now
technically serious: the current local suite, clean-clone release check, and all
three current GitHub workflows pass; the published container is the same image
that was tested; strict JSON output works; the six-file dataset pin fails closed;
and a full five-seed, 400-draw regeneration of the formerly nondeterministic
split-inflation experiment reproduces the committed scientific payload exactly.

That is not the same as being ready to publish. V6 found eight release blockers:

1. derived-artifact provenance still reports a false clean result when a
   generator depends on another edited script or on edited repository content;
2. the central “largely linear / most of the separability” interpretation is
   stronger than the experiment establishes and contradicts the repository's
   own narrow claim boundary;
3. the current release checklist republishes superseded HI-Medium ring-lift
   values while the numeric gate reports success;
4. current cost statements disagree with each other and with the cost artifact,
   and the live amount is still changing;
5. redistribution of the row-level replay bundles remains legally unreviewed,
   while the container includes those bundles without the data-licence notice;
6. the previously exposed Kaggle token is still recorded as unrotated;
7. the Azure VM and nine other resources remain live, with current spend already
   above the resource group's notification-only budget amount; and
8. the repository, disclosure channel, branch rules, code scanning, package
   visibility, dependency PRs, tag, and GitHub Release are not in release state.

The answer to “is everything done?” is therefore **no**. The core harness is
close. The scientific headline, provenance boundary, public documents, legal
decision, cloud lifecycle, and GitHub launch controls are not.

## Readiness by dimension

Scores are an audit judgement, not a generated metric. A high score does not
override a blocker in another row.

| dimension | state | assessment |
|---|---|---|
| Core pipeline correctness | strong | Current suite and end-to-end demo pass; many past defects now have behavioural regression tests |
| Scientific methods | good with a headline defect | Nulls, ceilings, leakage controls, split caveats, and lineage disclosure are unusually strong; the main linearity inference remains unsupported |
| Results integrity | mixed | Replay recomputation and counterfactual regeneration pass, but a current release document still quotes superseded results |
| Reproducibility | good but incomplete | Data contract, code-tree hashes, locks, replay, deterministic ordering, and source archive are strong; provenance does not cover the full generator dependency graph or installed environment |
| Testing | good | 334 tests collected and 73% source coverage; important orchestration modules remain lightly tested or completely untested |
| Packaging | incomplete | The artifacts themselves build and run, but the documented clean-clone package command is not self-contained and is absent from the release gate |
| Container/cloud | technically capable, operationally open | The tested image is pushed exactly, but security/supply-chain hardening is incomplete and the live estate does not match the Bicep |
| Security | incomplete for public launch | Secret scan and high-severity Bandit gate are green; no working disclosure route, no code scanning, no protected branch, and no image vulnerability scan |
| Data/legal | blocked | Raw CSVs are absent and disclosure is now honest, but the replay-bundle classification still requires a qualified decision |
| Documentation | extensive but inconsistent | Excellent forensic honesty; several current-facing contradictions and too much remediation history in the primary reading path |
| Usefulness | high | The alert-budget framing, replay bundles, nulls, ceilings, and failure catalogue are genuinely useful to AML evaluators |
| Presentation/impressiveness | potentially high | The depth is impressive, but a concise architecture/result visual and a cleaner narrative would communicate it better than hundreds of lines of audit archaeology |

## Audit scope and limitations

This audit covered the tracked tree and its public-facing operational state:

- 368 tracked files, approximately 14.8 MB in the checkout;
- source, tests, scripts, Make targets, locks, package metadata, Dockerfile,
  workflows, Bicep, results papers, current docs, archived result manifests,
  replay bundles, release metadata, licensing, security policy, and Git history;
- local and clean-clone execution;
- exact current GitHub workflow runs and repository settings;
- read-only Azure resource, network, VM, shutdown, and budget queries;
- regeneration of the split-inflation counterfactual from the available local
  intermediates.

The original HI-Medium and HI-Large feature tables are not all present locally.
Consequently, this audit did not refit those large models or rebuild every
dataset-derived artifact from raw CSV. It instead checked the six-file input
contract, all available hashes and lineage, replayed all committed budget
metrics, and reran the expensive counterfactual for which the gold inputs are
available. The eight older cloud replay bundles cannot be rebuilt on this
machine; their disclosed lineage limitation is itself reviewed below.

No Azure, GitHub, package-visibility, token, branch-protection, or repository
setting was changed. No project code, result, documentation, or artifact was
changed. This audit file is the sole intended repository addition.

## Verification performed

### Repository and code

| check | result |
|---|---|
| HEAD equals `origin/main` | pass, exact 40-character SHA above |
| initial tracked worktree | clean |
| `git diff --check` | pass for the current worktree |
| `git fsck --full` | pass; two harmless dangling commits reported |
| Ruff over `src`, `tests`, and `scripts` | pass |
| Python tests in the working checkout | **317 passed, 17 skipped** |
| Clean-clone `make release-check` | **316 passed, 18 skipped**, then all component checks passed |
| Source-only line coverage | **73%**, 2,166 statements / 590 missed |
| Shell syntax over every tracked shell script | pass |
| Current configured Markdown lint | 18 current documents, zero errors |
| Local Markdown links/table structure | 47 files, 88 local links, zero broken or malformed |
| Strict parse of committed result JSON | 166 JSON files, zero parse failures and zero accepted non-finite constants |

The local checkout runs one additional test because the split-inflation gold
outputs are present. A fresh clone and GitHub CI correctly skip that test, giving
316/18 instead of 317/17. Collection is stable at 334.

### Current GitHub evidence at the audited SHA

| workflow | run | result |
|---|---:|---|
| `ci` | 34917432125 | success; 316 passed / 18 skipped |
| `gates` | 34917432167 | success; actions pinned, Bicep compiled, full-history Gitleaks clean, Bandit high severity 0, Markdown clean |
| `image` | 34917432141 | success; 310 passed / 24 skipped, one pytest-cache permission warning |

The image workflow now does an important thing correctly: it loads and tests one
image, tags that already-tested image, pushes it, pulls the published digest
back, and confirms it is the same image. The run also confirms that
`AML_GIT_SHA` is injected and the DuckDB Azure extension is available without a
runtime fetch. This closes a substantive V5 defect.

### Results, artifacts, and reproducibility

| check | result |
|---|---|
| Publication checker | 479 decimal tokens across 13 current documents; 156 token exemptions; 0 unsupported, unprovenanced, superseded, retracted, or missing reported |
| Artifact collection | 56 result sets, zero malformed |
| Release facts | 334 collected, 17 local skips, 56 result sets; four stable fields match a fresh collection |
| Replay bundles | all nine bundles' file hashes and published budget metrics recompute; replay test set passes |
| Dataset contract | all six required filenames are encoded in code and the pin; five available local files hash correctly; `--require all` exits non-zero and names missing `HI-Large_Trans.csv` |
| Derived generator blobs | all ten named generator files resolve and hash correctly at their recorded commits |
| Newer package-tree provenance | nine newer derived artifacts' package tree hashes match their commits; the one grandfathered Medium ablation openly lacks this field |
| Full split-inflation regeneration | scientific payload exactly equals committed artifact for all five seeds and 400 draws |
| CFF validation | schema 1.2 validation passes |
| Dependency vulnerability audit | no known Python dependency vulnerabilities reported from the current locks |

The full counterfactual run took about 30 minutes and produced, at the current
HEAD, a prevalence-share mean of `0.46700481392675935`, range
`[0.4391384783663008, 0.4996102074578042]`. After removing timestamp,
environment, and provenance fields, the fresh JSON and committed JSON are equal.
The earlier DuckDB scan-order nondeterminism is therefore fixed in the real
400-draw experiment, not only in the small regression test.

### Packaging

An independent build, after explicitly supplying the missing packaging tools,
produced both sdist and wheel. Both passed `twine check`. Installing the wheel
into an empty Python 3.12 environment succeeded; the console command, help, and
demo ran through the installed wheel; all 19 JSON-shaped event lines from the
demo passed a strict JSON parser.

That successful artifact test does not rescue the repository command described
in P1-1 below: a genuinely fresh clone fails before it can build the same wheel.

### Live Azure, read-only

At approximately 2026-09-15 02:00 UTC:

- the resource group exists and contains 10 resources;
- the VM reports **running**;
- one public IP is attached;
- no NAT gateway is attached;
- the inbound TCP/22 custom rule is `Deny` from `*`;
- no auto-shutdown schedule exists; and
- the monthly resource-group budget is `$60`, with an 80% notification and
  current spend reported at approximately **$60.61**.

The budget does not stop resources. The `$60.61` Cost Management amount is not
the same estimand as the repository's elapsed-time list-price estimate and should
not be substituted into that table. Both are changing while resources run.

## P0 — blockers before public visibility or a release tag

### P0-1 — Provenance still has an uncovered dependency boundary

`aml.manifest.generator_provenance` verifies exactly two code surfaces:

1. the named generator script; and
2. all Python files under `src/aml`.

It does not verify sibling scripts, tests, documents, registries, or other
repository-owned inputs. That is already enough to create false provenance.
`scripts/release_facts.py:65-68` imports `scripts/make_tables.py` at runtime, but
`generator_provenance` is called only for `release_facts.py` and receives no
inputs at `scripts/release_facts.py:232-235`.

I reproduced the failure in a scratch clone of the audited commit:

```text
edit only scripts/make_tables.py
call generator_provenance("scripts/release_facts.py")

generator_matches_commit=True
code_tree_matches_commit=True
```

The edited sibling can change which result sets are collected while the output
claims clean provenance from a commit that does not contain that edit. The same
artifact also depends on every test, every Markdown file counted for markers,
and the results archive; none is recorded in `inputs`. Adding an uncommitted test
or changing a document can therefore change `release_facts.json` while its code
provenance remains green.

The current mutation test at
`tests/repro/test_audit_regressions.py:2518-2604` mutates only the generator and
one package module. It proves those two boundaries and no more.

**Required change:** define each derived artifact's complete repository-owned
dependency closure. At minimum, verify all imported project scripts and record
the result/test/document/archive inputs that affect the output. A simpler,
safer release rule is to refuse artifact generation from any dirty tracked or
untracked project file within a declared scope. Add mutation tests for a sibling
script, a new/edited test, an edited current document, and an edited result
artifact. Do not label this fixed until each mutation stops generation.

### P0-2 — The headline interpretation still exceeds the evidence

The measured facts are useful and defensible:

- one 32-feature logistic baseline reaches `precision@50 = 0.5706` on
  HI-Medium;
- one GBDT fit on the same feature vector reaches `0.7940`; and
- the eight-seed GBDT distribution is available elsewhere.

The interpretation attached to them is not established:

- `README.md:17-25` says whatever separates the classes is “largely linear” and
  that the baseline is what the benchmark “gave away”;
- `README.md:188-189` repeats that framing;
- `HANDOFF.md:61-64` and `HANDOFF.md:127` say “most of the separability” is
  linearly reachable; and
- `CITATION.cff:29-32` promotes the same inference into citation metadata.

Yet `docs/LIMITATIONS.md:326-332` correctly states the supported boundary:
this particular feature vector is strongly separable by this particular linear
model, while whether the benchmark is “largely linear” is not established. The
same limitations file contradicts itself at lines 33-37 by making the broader
claim again.

A single linear baseline and a single comparator do not define total
“separability,” establish a ceiling, or show what fraction belongs to the data
generator rather than feature engineering. Removing “near-saturated” did not
remove the underlying inference; it replaced it with another undefined fraction.

**Required change:** make the headline purely measured. A defensible form is:
“On HI-Medium, with this 32-feature representation and account-day alert unit,
logistic regression achieves precision@50 of 0.5706; the eight-seed GBDT mean is
0.8248 with observed range 0.5914–0.8981.” If a “share of separability” is to be
claimed, preregister its denominator, ceiling, comparators, and seed aggregation
and then measure it. Synchronize README, HANDOFF, CFF, and LIMITATIONS.

### P0-3 — A current release document republishes superseded ring-lift values

`docs/RELEASE_CHECKLIST.md:214-215` says the completed HI-Medium permutation-null
result agrees at “gbdt 0.920, logistic 0.946.” Those are from the superseded
`eval3_Medium` lineage. The current canonical statement is:

- sorted canonical GBDT lift `0.907`; and
- no canonical HI-Medium logistic re-evaluation under this null.

That correction is already stated accurately in `HANDOFF.md:42-50` and
`docs/LIMITATIONS.md:146-154`. The current checklist contradicts both.

The 479-value publication check still passes. It finds `0.920` and `0.946`
elsewhere under other metrics or lineages and cannot bind a number to the nearby
label, metric, budget, model, seed aggregation, or canonical result set. This is
not a hypothetical weakness; it has now admitted the exact defect it was built
to prevent.

**Required change:** correct the checklist immediately. Then implement the typed
claim-reference change in P1-2 so this class cannot recur.

### P0-4 — Cost statements are internally stale while the meter is live

The cost artifact and top of the runbook record a snapshot of `$66.73` at list
price over `121.96` hours. Current-facing text disagrees:

- `README.md:441` says `$64.32` over `117.56` hours, then says the runbook is the
  only place cost is stated;
- `docs/RUNBOOK_cloud.md:237-240` repeats `117.56` hours inside the same file that
  reports `121.96` at lines 7-11 and 324-329; and
- `HANDOFF.md:320` says portal spend is about `$57`, while the read-only audit
  query now reports about `$60.61`.

The publication checker ignores two-decimal money and hour values, so it reports
zero disagreements. The underlying design also guarantees continued drift:
`cost.json` has no stop time and the VM remains running.

**Required change:** first resolve the live resources in P0-7. Then regenerate
one final cost artifact with an explicit end time, label list-price estimate and
Cost Management spend as different quantities, and make every current document
derive or link rather than copy. Extend the claim gate to money, hours, resource
counts, and percentages.

### P0-5 — Replay-bundle redistribution is unresolved, and the image omits its notice

The disclosure is much more honest than V5: the nine bundles say
`licence_status: UNREVIEWED`, and `DATA_LICENSE.md` identifies the row-level
fields. This audit counted 526,355 rows across the 45 committed Parquet files.
They include day, opaque account code, label, score, rank, and ring linkage.

Whether these are CDLA “Results” or redistribution of “Data” remains a legal
classification the repository explicitly declines to make. That is a release
blocker, not documentation polish.

There is also a distribution-specific defect. The Dockerfile copies
`results_archive/` into the published image but never copies `DATA_LICENSE.md` or
`LICENSE`. The runbook's source archive path list likewise omits both. Thus a
future public OCI image would contain the disputed row-level bundles without the
notice that explains their source, terms, or unreviewed status.

Several short statements remain too categorical:

- `README.md:545-546` says no transaction data is redistributed;
- `aml-platform/README.md:31-33` calls AMLworld “not redistributable”; and
- the same package README does not alert an image/package reader to the replay
  bundle distinction.

The first is at least ambiguous in a repository that contains derived
transaction-level records; the second overstates what a conditional data licence
means.

**Required change:** obtain a written determination from qualified counsel, or
remove the bundles from every public Git/GHCR artifact until one exists. Include
the applicable notices in every artifact that contains the bundles. Make all
README/CFF/security wording distinguish raw AMLworld data, derived row-level
records, metrics, and code consistently.

### P0-6 — The exposed Kaggle token still needs to be rotated

`HANDOFF.md:334-336` and the release checklist state that a Kaggle credential was
pasted into a chat transcript and rotation has not been verified. A clean current
tree and zero full-history Gitleaks findings do not invalidate a credential that
was exposed outside Git.

**Required change:** expire/rotate it at Kaggle, verify the old credential no
longer authenticates, replace any legitimate local use without recording the new
value in Git or shell history, and record only the completion date.

### P0-7 — Azure is still running, over the notification budget, and not reproducible from Bicep

The live read-only facts are listed above. The checked-in Bicep describes a NAT
gateway and no NIC public IP; the live group has an attached public IP, no NAT
gateway, and a manually flipped Deny rule. The VM is running with no shutdown
schedule. Current spend is already approximately `$60.61` against a `$60`
notification budget. A budget alert is not a kill switch.

This is simultaneously cost leakage, operational residue, and a reproducibility
failure: publishing the Bicep as “the infrastructure” does not reproduce the
estate that produced the results.

**Required change:** preserve anything intentionally retained from the ephemeral
scratch disk, then deallocate or delete the resources. Decide whether the Bicep
is the intended future design or historical documentation; deploy it into a
clean group and verify it, or label/retire it. Generate the final settled cost
snapshot only after the meters stop. This audit deliberately performed no cloud
write.

### P0-8 — GitHub is not in a safe release state

At audit time:

- the repository is private;
- `main` has no branch protection and there are no repository rulesets;
- code scanning is not enabled;
- private vulnerability reporting has no working endpoint;
- `SECURITY.md` openly states that no private disclosure channel works;
- GHCR denies anonymous pulls;
- there are no tags and no GitHub Releases;
- repository topics and homepage metadata are empty; and
- four Dependabot PRs remain open. One is fully green; the other three have at
  least one current or recorded failing workflow that requires triage.

Dependabot vulnerability alerts are enabled and currently report zero open
dependency alerts. That is good, but it does not replace code scanning, branch
rules, or a disclosure channel.

**Required change:** before flipping visibility, publish a monitored security
address or arrange and verify private vulnerability reporting, fix the image
workflow trigger issue in P1-7, configure required checks and protection against
force-push/deletion, enable available scanning and push protection, decide GHCR
visibility/authentication, resolve or close the four dependency PRs with reasons,
then create a signed tag and GitHub Release. Add CFF release metadata only for
the release that actually exists.

## P1 — important defects to close for a credible first release

### P1-1 — The documented clean-clone package smoke command is broken

In a new clone of the audited commit, I ran:

```text
make setup
make package-smoke
```

`make setup` succeeded. `make package-smoke` then failed at its first substantive
line:

```text
.venv/bin/python: No module named build
make: *** [package-smoke] Error 1
```

`Makefile:77-85` invokes `python -m build`, but neither dev lock contains
`build`. `twine` is also absent, and the target does not validate package
metadata. `make release-check` calls neither `package-smoke` nor an equivalent;
it passed in this same clean clone, despite describing itself as the command for
everything locally verifiable.

**Required change:** pin `build` and `twine` in the appropriate dev locks and
hashed Linux lock, make `package-smoke` run `twine check`, and execute that target
in CI and from `release-check`. Keep the clean installed-wheel demo and strict
stdout parse as acceptance tests.

### P1-2 — The publication gate needs typed claim references

P0-3 and P0-4 demonstrate both remaining blind spots:

- token membership accepts a value supported by the wrong metric/model/lineage;
  and
- the 3–6 decimal matcher ignores common two-decimal money and hours.

The 156 exempted numeric tokens are also too large a manual escape surface. An
HTML marker says only “someone exempted this,” not what artifact, formula,
metric, unit, or parameters support it.

**Required change:** represent a current claim as a typed reference containing at
least result-set ID, canonical status, dataset/rung, model, seed or aggregation,
metric, alert budget, unit, and transformation. Generate tables and prose values
from those references. Make exemptions name a formula and source fields. Extend
coverage to integer counts, percentages, money, durations, memory, and resource
facts.

### P1-3 — Cache identity excludes the environment that can change results

`manifest.run_key` uses component, config, package code tree, and input
fingerprints. It does not include the dependency lock, actual installed package
set, Python patch version, container digest, or DuckDB extension identity.
`env_lock_sha256` is recorded after execution, but it is the declared lock and
does not prove the installed environment matches it. A dependency change can
therefore hit a prior cache and only be noticed later by manual comparison.

**Required change:** include an environment identity in every cache key. For
locked environments, verify installed distributions against the lock and record
that verified identity. For container runs, include the immutable image digest
and DuckDB extension identity. Define how deliberate cache compatibility across
environment changes is approved rather than silently assumed.

### P1-4 — Artifact and replay provenance remains partial

The current state is improved but heterogeneous:

- `categorical_ablation_medium.json` is a metadata migration, not a rerun. Its
  full generator SHA is verified, but it has no package-tree hash, input
  identities, parameters, or environment lock;
- `cost.json` records no input identity for the external Azure retail response;
- `release_facts.json` records no tests/docs/archive inputs;
- most directory inputs are explicitly only path-and-size metadata identities,
  not content hashes;
- inputs over 64 MB can have hashing skipped;
- only `small_gbdt_s0` is replay schema v3 with generator/package/input
  provenance and dataset pin; and
- the eight older schema-v2 replay bundles disclose that they lack generator,
  dataset-pin, and source-score identities. They prove metric recomputation from
  their own rows, but not that those rows came from the score parquet named by
  the associated manifest.

The runbook's source tarball is deterministically built from a commit and its
hash is verified before extraction, which is strong. However, the archive hash
is supplied only to provisioning; it is not recorded in the image or result
manifests, and nothing proves inside a later artifact that the separately passed
commit SHA and source archive belonged together.

**Required change:** version the provenance schema, require the strong form for
new canonical artifacts, record external response bodies or immutable request
and response hashes, migrate/rerun what can be rerun, preserve explicit
grandfathering only where raw inputs no longer exist, and carry the verified
source-archive hash into the image and every cloud manifest.

### P1-5 — Coverage is 73%, and the published coverage table is itself wrong

The fresh source-only report is:

| module | coverage |
|---|---:|
| `drift/experiment.py` | **0%** |
| `demo.py` | 19% |
| `eval/run.py` | 27% |
| `models/stability.py` | 31% |
| `models/train.py` | 40% |
| `leakproof/plant.py` | 51% |
| `leakproof/sweep.py` | 57% |
| `manifest.py` | 64% |

`docs/RELEASE_CHECKLIST.md:146-158` calls its table “the lowest modules” but
omits the 0%-covered drift orchestrator and says `eval/run.py` is 30%, not 27%.
`HANDOFF.md:323` says six modules are under 60%; the report has seven. There is no
coverage floor.

These are orchestration and artifact-writing paths where a failure can produce a
plausible wrong artifact. The existing contract skips do not cover them, as the
documentation correctly acknowledges elsewhere.

**Required change:** correct the current documents, add small synthetic
behavioural integration tests for each orchestrator, and set a modest ratcheting
floor only after meaningful assertions exist. Do not chase line execution
without output or invariant checks.

### P1-6 — The reporting rule conflicts with the headline and costly runs

`paper/RESULTS_metric_stability.md:49` says a single-run `precision@50` is not a
result, and lines 107-109 require every budget metric to be a mean over at least
eight seeds with observed range. The README headline compares logistic with one
GBDT fit. HI-Large is necessarily presented with only three costly seeds.

The point estimates are labelled, so this is transparent, but the categorical
rule is false as written and the headline uses exactly the presentation it
forbids.

**Required change:** use the eight-seed mean/range in the HI-Medium headline and
scope the rule precisely—for example, stochastic HI-Medium claims where eight
runs exist—while naming an explicit cost-based exception for HI-Large. Keep the
logistic result separate if its ranking is demonstrably seed invariant.

### P1-7 — Image parity documentation and trigger semantics are wrong

The current exact GitHub runs show fresh CI at 316/18 and image at 310/24: the
image has **six** additional skips. `docs/RELEASE_CHECKLIST.md:123-140` says five,
and the Dockerfile comment says four root-document skips plus the Dockerfile.
The actual additional reasons comprise five root/repository-document-dependent
tests and one Dockerfile-dependent test.

The workflow's reason allowlist passes, which is useful, but it does not assert
the documented count or a complete expected mapping. The image workflow also
has `paths` filters limited to `aml-platform/**` and its own workflow file. A
root-only PR can therefore have no image check even if repository rules later
require it.

**Required change:** update the documented parity map from actual test IDs or
avoid a fixed count entirely; assert that every expected host test either runs
or maps to a named image limitation. Make the workflow always produce a required
status, using a cheap no-op decision job if an image rebuild is unnecessary.

### P1-8 — The infrastructure README contains an impossible primary build path

`infra/README.md:3-14` correctly says the registry is off by default and ACR
Tasks are blocked on the trial subscription. Lines 63-72 then instruct the user
to read the registry output and run `az acr build`. With the default deployment,
that output is empty; on the described subscription, the task is known to be
rejected.

**Required change:** remove or clearly archive that section. Make the verified
GitHub-to-GHCR flow or the VM's sha256-verified source-archive flow the only
current instructions. Test every command path from a clean deployment output.

### P1-9 — Container security and supply-chain evidence are incomplete

The image is reproducible in some important ways: base digest, hashed Python
wheel lock, non-root user, immutable tested/pushed digest, and build-time DuckDB
extension test. Remaining gaps are material for a public downloadable image:

- the base is Python `3.12.3` while the 3.12 line is much newer; there is no
  Docker Dependabot entry or image vulnerability scan to establish whether the
  old base remains acceptable;
- APT packages are resolved from mutable repositories without captured package
  versions or snapshot;
- the DuckDB Azure extension is downloaded at build time without a recorded
  digest/version in the repository's SBOM;
- `sbom.cdx.json` describes the 63 Python lock components, not the full image,
  base OS, APT packages, Python runtime, application files, or DuckDB extension;
- build tools and `git` remain in the runtime image even though `.git` is absent
  and `AML_GIT_SHA` supplies provenance;
- the application is installed editable and tests/docs/archive are in the
  runtime artifact; and
- there is no signing or published attestation.

The image test emits a pytest-cache permission warning because the non-root user
cannot write under `/app`. It does not invalidate the suite but is avoidable
release noise.

**Required change:** add Docker dependency updates and vulnerability scanning,
refresh or justify the base, produce a full-image SBOM, record/verify the DuckDB
extension, and publish an attestation/signature. Prefer a multi-stage production
image plus a separately identified test image, or document a deliberate single-
image design with its size and attack-surface trade-off. Disable pytest cache or
write it to a permitted temporary directory during the image gate.

### P1-10 — The SAST gate does not enforce the baseline its prose claims

The gates workflow and `docs/SAST_TRIAGE.md` say known findings are triaged and
new findings fail. The actual blocking command is `bandit -lll`, which fails only
high-severity findings. The medium-and-above run is informational and
`--exit-zero`; it does not compare the count or identities against a baseline.
Current output is 51 medium findings and 0 high. A new medium SQL-construction
finding would therefore pass without triage.

The triage also records a real robustness issue: operator-supplied paths
containing apostrophes can break f-string-built DuckDB SQL, even if this is not a
remote privilege boundary.

**Required change:** either enforce a reviewed finding baseline/allowlist so new
medium findings fail, or state accurately that only high severity gates. Add
central tested quoting/parameter helpers for paths and identifiers, including
apostrophes and unusual Unicode.

### P1-11 — Release-facts scope, marker counts, and privacy are inconsistent

`release_facts.json` reports 80 derived markers because it counts every Markdown
file, including archived audits. The current tree contains 74 outside archives,
and the 13 publication-checked documents contain 73. `HANDOFF.md:155-157` says
68 “currently.” `release_facts.py --check` does not check this field, so all of
these can coexist under a green release-facts gate. The 156 “exempted” count from
`make_tables` is a count of numeric tokens, not markers, and must not be mixed
with these quantities.

The committed `release_facts.json` also records the maintainer's absolute local
workspace path in `parameters.root`. It is not a secret, but it is unnecessary
personal/system metadata and makes an otherwise portable artifact
machine-specific.

**Required change:** define marker scope once, store separate all/current/checked
counts if each is useful, validate every claimed field, and use repository-
relative normalized parameters. Remove the absolute path on regeneration after
fixing P0-1.

### P1-12 — Public-facing licence language and artifact boundaries need one vocabulary

The detailed data-licence document now distinguishes raw data from derived
records correctly. Short summaries still alternate among “not redistributed,”
“not redistributable,” “no licence,” “Results,” and “unreviewed.” Those are not
synonyms. The root quick-reproduction table even says the replay tier needs “no
licence” immediately before warning that redistribution is unreviewed.

**Required change:** adopt four exact terms everywhere: raw source data, derived
row-level bundle, aggregate metric/manifest, and code. State acquisition terms,
repository inclusion, and redistribution status separately for each. Have the
legal review in P0-5 approve the final wording.

## P2 — quality, clarity, and maintainability

### P2-1 — Current prose still contains visible editing residue

- `README.md:513-517` contains the malformed phrase “the benchmark is a linear
  baseline is already strong.”
- `README.md:535-537` says “both external audit reports,” although five audit
  files now exist under `docs/archive/`.
- `HANDOFF.md:18-20` describes three internal rounds and a fourth external audit,
  then later contains V5 material.
- `HANDOFF.md:33` announces “Three retractions and one false reproducibility
  claim” but the numbered section contains five distinct claim corrections.
- The release-checklist manual-gate numbering is out of order (`1`, `2b`, `2`,
  then `14` before `13`).
- The archived V2–V5 audit Markdown contains 24 trailing-whitespace lines. It is
  intentionally excluded from lint, but this remains visible source hygiene.

**Required change:** perform one human prose pass after the scientific and legal
wording is final. Avoid adding another layer of historical corrections to the
primary README; move the incident record to CHANGELOG/HANDOFF/archive.

### P2-2 — The primary narrative is too dominated by remediation history

The repository's honesty is a strength, but the README, HANDOFF, source comments,
Dockerfile, and workflows repeatedly explain every prior failed fix. A new user
must process the forensic record before understanding architecture, inputs,
outputs, and the smallest useful experiment. This makes the project feel less
finished despite the underlying depth.

**Recommended change:** keep the retractions prominent, then move detailed
failure chronology into a short “engineering postmortem” or ADR series. Give the
README a compact path: problem, method, one measured result table, architecture,
quick start, reproduction tiers, limitations, citation. Keep operational handoff
content out of the permanent project overview once Azure is closed.

### P2-3 — Visual communication is missing

The project would benefit from two generated-from-source figures:

1. a small pipeline/lineage diagram from raw CSV through account-day evaluation,
   manifest, replay bundle, and publication gate; and
2. one result figure showing logistic versus the eight-seed GBDT distribution
   at the daily alert budget, with the recall ceiling and units visible.

These would make the methodology materially easier to understand and reduce the
need for repeated prose explanations. Store the plotting source and input
artifact references; do not add hand-edited screenshots.

### P2-4 — Repository presentation and governance are not finished

The repository has strong LICENSE, CONTRIBUTING, SECURITY, CHANGELOG, CFF, and
release-checklist files. Optional but useful public-project polish remains:

- GitHub topics and a homepage/archival DOI after release;
- issue and pull-request templates;
- a code of conduct if outside contributions are genuinely invited;
- a clear support/non-production-use statement; and
- a concise release badge set only after required checks and a real release
  exist.

The wiki is enabled despite the repository already treating versioned Markdown
as its system of record. Disable it or define its purpose to avoid a second,
unversioned documentation surface.

### P2-5 — Author identity remains an explicit publication choice

Raw history contains 109 commits with a machine-local author address, 11 with an
institutional address, and four Dependabot commits. `.mailmap` unifies display
names but does not remove object metadata. This is not a secret-scanning failure.

**Required decision:** accept the history as-is, map to an intended public
address, or rewrite before the first public push. Configure the future author
email deliberately. Rewriting after publication is far more disruptive.

### P2-6 — External-link monitoring has not yet accumulated evidence

All local links pass. Manual spot checks of the current IBM, Kaggle, CDLA, paper,
and Azure-pricing references found four ordinary successes and one expected
bot-blocked 403. The weekly external-link workflow is active but has no completed
scheduled run yet. The repository's own URL and image are intentionally
unavailable anonymously while private.

**Recommended change:** manually dispatch the link workflow after publication,
review its first report, and make broken links create a tracked issue or other
visible notification while remaining non-blocking for transient failures.

## What V5 remediation genuinely closed

The following should not be reopened without new evidence:

- the current tested container is the container actually pushed;
- baked-in `AML_GIT_SHA` no longer makes the provenance mutation test vacuous in
  the image fixture;
- generator blobs and the package code tree are compared with Git objects;
- the six dataset filenames are a code-level contract, and re-pinning cannot
  silently discard the unavailable HI-Large entry;
- strict stdout JSON no longer emits bare `NaN`;
- the split-inflation SQL order fix reproduces exactly at the full published
  draw/seed setting;
- the split-inflation artifact and paper now distinguish composition and score-
  distribution contrasts from a causal leakage effect;
- the feature spec that contradicted the implementation is archived and guarded;
- the runbook refuses a dirty tree and builds a deterministic Git archive;
- cloud runners verify pinned raw inputs and keep seed destinations separate;
- the package CFF no longer declares a release that does not exist;
- the replay-bundle legal status is disclosed rather than falsely settled; and
- the canonical result registry, retraction registry, replay checks, strict JSON
  checks, and current image tests are all substantive improvements.

## Recommended order of work

### 1. Stop external risk now

1. Preserve any intentionally retained `/mnt/scratch` evidence.
2. Deallocate or delete Azure resources and verify the meter stops.
3. Rotate the Kaggle token and verify the old one fails.
4. Decide replay-bundle legal status; remove bundles from prospective public
   artifacts until a positive determination exists.

### 2. Correct the scientific/public record

1. Replace “most/largely linear” with the measured baseline and seeded GBDT
   distribution.
2. Correct the checklist's superseded `0.920/0.946` sentence.
3. Generate one settled cost artifact and remove all copied stale cost values.
4. Correct the coverage table, marker counts, licence summaries, and visible
   prose errors.

### 3. Close the mechanisms that allowed recurrence

1. Make artifact provenance cover sibling scripts and declared repository inputs.
2. Replace numeric token membership with typed claim references.
3. Put verified environment identity into cache keys and manifests.
4. Make clean-clone package smoke part of locks, CI, and `release-check`.
5. Add behavioural integration tests for the seven sub-60% orchestration modules.

### 4. Finish distribution and security

1. Fix image workflow required-check semantics.
2. Refresh/scan/sign the image and publish a full-image SBOM and licence notice.
3. Make SAST policy match enforcement.
4. Resolve dependency PRs.
5. Configure disclosure, rules, scanning, package visibility, topics, and release
   metadata.

### 5. Perform a short release acceptance pass

Do not commission another open-ended prose audit. Run a finite acceptance list:

- clean clone: setup, lint, test, release-check, package-smoke;
- exact current CI/gates/image SHA green;
- all typed claims and release facts green;
- replay legal decision recorded or bundles absent;
- Azure stopped and final cost immutable;
- old token invalid;
- anonymous repository/link/image behaviour matches the README;
- protected branch and disclosure route verified from a non-owner account;
- signed tag, release notes, CFF version/date, wheel, image digest, SBOM, and
  checksums agree.

## Final release decision

**NO-GO for public GitHub visibility or a tagged release at this commit.**

This is no longer because the basic pipeline is weak. The implementation,
regression suite, replay mechanism, and audit history are unusually substantial.
It is because the repository still contains three kinds of failure that a public
research release cannot carry:

1. a central inference broader than its evidence;
2. current-facing false values under green provenance/publication gates; and
3. unresolved external obligations and live state.

Close every P0, then the P1 items that affect provenance, packaging, claims,
coverage, and distribution. At that point this can be a useful and impressive
public project. At `9a84eae`, it is a strong release candidate, not a release.
