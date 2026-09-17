# Release checklist

From the external audit's go/no-go list, plus what the remediation added. Every
line is either a command you can run or a decision with a name on it.

**Run from a clean clone**, not from a working tree that has been alive for
weeks. Most of what this catches is the difference between the two.

---

## 1. Automated — all of this runs in CI on every push

```bash
cd aml-platform
make lint                                  # ruff
make test                                  # 415 tests collected (pass/skip
                                           # split varies by environment)
python -m aml.cli demo --dest "$TMPDIR/demo"   # the real pipeline, generated corpus
pytest tests/cloud/ -q                     # every stage through file:// URIs

# Every published figure must trace to an artifact WITH PROVENANCE, from a
# CANONICAL lineage, and must not be a value the project has retracted.
#
# `--gate`, NOT a list. This block enumerated thirteen documents by hand while
# the gate covered twenty-three, so ten published files -- including
# `paper/README.md`, which indexes every result and was selling a withdrawn
# claim -- were absent from the command the release process tells you to run.
# A hand-kept copy of an inventory is the defect this flag exists to remove,
# and it had grown back in three places.
python scripts/make_tables.py --check --gate

# The committed counts artifact must not be stale, and the prose must match it
python scripts/release_facts.py --verify-artifact
python scripts/release_facts.py --check ../README.md ../HANDOFF.md \
    ../CONTRIBUTING.md docs/RELEASE_CHECKLIST.md

python scripts/check_links.py ..           # no broken relative links or anchors

# A published number, recomputed from a few hundred KB and no dataset
python scripts/verify_replay_bundle.py \
  --bundle   results_archive/replay/small_gbdt_s0 \
  --manifest results_archive/gold/infl_eval_ring-aware_s0/manifest.json
```

Plus, in the `gates` workflow: ShellCheck, actionlint, a pinned-action check, a
Bicep build, and a **full-history** gitleaks scan.

Plus, in the `image` workflow: build for linux/amd64 from a `--require-hashes`
lock, assert `AML_GIT_SHA` is not `unknown`, run the whole suite **inside** the
image, and confirm the DuckDB azure extension is baked in rather than fetched.

## 1b. Which command regenerates which result

`make all` does not reproduce everything, and no single page said so. Each row
names what it needs; a reader with only a checkout can do the first two.

| result / artifact | command | needs | ~time | determinism |
|---|---|---|---|---|
| the six pipeline stages compose | `make demo` | nothing | 30 s | exact; corpus is generated, numbers are meaningless by construction |
| every published budget metric | `pytest -q -k replay` | nothing (9 MB of bundles) | 5 s | **exact** — recomputed from the bundle, compared to the manifest |
| all derived artifacts' provenance | `pytest -q -k derived_artifact_names` | nothing | 3 s | exact, from git objects |
| every published number and count | `make release-check` | nothing | ~2 min | exact |
| `dataset_pin.json` | `python scripts/verify_dataset.py --pin` | the CSVs | 1 min | exact (content hashes) |
| `dataset_facts.json` | `python scripts/measure_dataset_facts.py` | HI-Medium CSV | 2 min | exact |
| `split_inflation.json` | `python scripts/analyze_split_inflation.py` | `data/gold` from a Small run | 1 min | **exact** since the `ORDER BY` fix |
| `split_inflation_counterfactual.json` | `python scripts/split_inflation_counterfactual.py` | `data/gold` from a Small run | 13 min | **exact** since the `ORDER BY` fix; was not before |
| `typology_null.json` | `python scripts/typology_null.py` | the two `stability.json` files, `data/bronze/patterns_Medium/rings.parquet` and the `medium_gbdt_s0` bundle | 30 s | exact (seeded); without the parsed patterns it records an error instead of an exposure null |
| `categorical_ablation.json` | `python scripts/categorical_ablation.py --features … --splits …` | a built Small feature table | 2 min | exact (seeded) |
| `categorical_ablation_medium.json` | the same, on HI-Medium features | **the cloud VM** — not reproducible locally | 9 min | not re-run; provenance-repaired only, and the artifact says so |
| `cost.json` | `python scripts/cost_table.py --created …` | network (Azure retail prices) | 5 s | prices and elapsed time both move; timestamped |
| `sbom.cdx.json` | `python scripts/make_sbom.py` | nothing | 2 s | exact |
| `release_facts.json` | `python scripts/release_facts.py` | nothing | 40 s | `tests_collected` exact; `tests_passed`/`skipped` vary by environment |
| HI-Small / HI-Medium lineages | `make all VARIANT=Small` / `VARIANT=Medium` | the CSVs, 16 GB RAM | 30 min / hours | exact given the same lock |
| HI-Large canonical lineage | `docs/RUNBOOK_cloud.md` | Azure, 17 GB download, ~$64 list | 3.5 h | matrix hash identical across three seeds <!-- derived: 3.5 = the HI-Large lineage's wall-clock estimate in RUNBOOK_cloud.md, not a measured artifact field --> |
| the container | the `image` workflow | Docker, amd64 | 6 min | the tested digest is the pushed digest |

## 2. With the dataset

```bash
make get-data
make verify-data                           # reports on what is present
python scripts/verify_dataset.py --require all   # RELEASE GATE: fails if any
                                           # pinned file is absent or differs
make all VARIANT=Small CUT=2022-09-05
```

## 3. Manual gates — each names its evidence and its pass criterion

A box here may **not** be ticked on the strength of a prose assertion. Each row
says what would count as proof. The v2 audit found the previous version of this
list asserting things that were false — it claimed **270 tests** and blamed the
17 skips on missing Azure extras, said "all six files verified", and required
an image check on a workflow that had no PR trigger — which is what a checklist
without evidence criteria becomes. <!-- historical -->

⚠️ That "270" had been mechanically rewritten to the CURRENT collection count
for several rounds, so this sentence claimed the v2 audit objected to a number
that did not exist when v2 was written. `release_facts.py --fix` was editing a
historical fact because it could not tell a record from a claim. It now leaves
any line that narrates a past state alone, and this one carries the marker as
well. <!-- historical -->

| # | gate | pass criterion | evidence to record | done |
|---|---|---|---|:--:|
| 1 | Kaggle token rotated | the pasted token no longer authenticates | date of rotation; the token was never needed — AMLworld downloads unauthenticated, which the cloud run proves | ☐ |
| 2 | `Cloud/_v1_superseded/` | decide whether these five files should be public | **they already are.** `.gitignore` lists the directory, but the files were committed in `bfaa463` *before* the entry was added, and ignoring a tracked file does not untrack it. Moving the directory to `docs/archive/` made them visible to the link checker, which is how this surfaced. A concrete instance of the rule below | ☐ |
| 3 | History decision made | an explicit accept, or a `git-filter-repo` run | `gitleaks` over all commits reports 0; the 16 `Learning/` files are 437 KB of study notes with no emails, GUIDs or keys. So this is a taste call, not a security one — record which was chosen | ☐ |
| 4 | **Rerun the HI-Medium categorical ablation BEFORE teardown** | a fresh `categorical_ablation_medium.json` with a package-tree hash, declared inputs, parameters and `scope_clean: true` | it is the evidence that the linear-baseline headline does not depend on the hashed encoding, and it is the ONE derived artifact still grandfathered — no package-tree hash, no inputs, no environment. The HI-Medium features live on `/mnt/scratch`, the **ephemeral resource disk**, which Azure wipes **on deallocate** -- not on delete. So the window closes when the VM stops for ANY reason, including automatic deallocation when the trial credit runs out, which at the measured ~$0.49/h is the first constraint to bind. This row previously said "possible until the group is deleted", which overstates the window by however long the VM would have sat deallocated. If it is not rerun, the encoding question stays open and `LIMITATIONS.md` §5b says so | ☐ |
| 5 | Azure resolved | resource group deleted, **or** retained with a budget and no inbound rule | **partly done**: inbound TCP/22 set to **Deny** (it had been Allow from `*` while the docs claimed no public IP), and a `$60` monthly budget `aml-guard` created with an 80% alert. Still to decide: delete the group, and whether to add auto-shutdown | ☐ |
| 6 | HI-Large re-fitted under the sort | three seeds with `train_rows_ordered_by: txn_id` and `train_matrix_sha256` in every fit manifest | **done** — `large_sorted_lgbm_s{0,1,2}`, one commit, all three producing a byte-identical 124,992,128-row training matrix | ☑ |
| 7 | Repository public | — | — | ☐ |
| 8 | GitHub security features on | secret scanning, push protection and CodeQL enabled | these need Advanced Security, **free only once public** — so this is gated on #5. Dependabot alerts and automated fixes are already on | ☐ |
| 9 | `main` protected | `ci`, `gates`, `image` required; force-push and deletion blocked | the ruleset id. `image` gained a `pull_request` trigger, so it can now be required | ☐ |
| 10 | Image distribution decided | either an anonymous `docker pull` succeeds, or the README says the image needs auth | the image workflow's "ANONYMOUS PULL" line from a post-release run | ☐ |
| 11 | Release tagged | a signed tag and a GitHub Release exist | tag name and digest. `CITATION.cff` gets its `version`/`date-released` **only then** — a test enforces that it has neither while no tag exists | ☐ |
| 12 | External audit re-run | the auditor sees the post-remediation state | two headline claims reversed direction since the last review; they reviewed a different project | ☐ |
| 13 | **A disclosure channel that works** | either GitHub private vulnerability reporting loads **for a logged-out visitor**, or `SECURITY.md` names a monitored address in plain text | a screenshot or the URL, taken while signed out. Two previous versions of `SECURITY.md` named a channel that could not carry a report — first a 404 endpoint, then a profile with no address shown. The setting being on is not the evidence; the form loading for someone else is | ☐ |
| 14 | **Replay-bundle redistribution settled** | a written determination that the row-level `day`/`account`/`label`/`score`/ring fields are CDLA "Results" and not redistributed data — or the fields removed until they are | the determination, dated and attributed. `DATA_LICENSE.md` calls this an unreviewed interpretation and the bundles' own notes stated it as settled fact; the notes now match the analysis, but the analysis is still unreviewed. **This is the one item here that needs a lawyer rather than a commit** | ☐ |
| 15 | **Authorship identity decided** | every commit's author email is one you intend to publish | `git log --format=%ae` uniqued shows two: a machine-local hostname address and an institutional one. `.mailmap` unifies the displayed NAME and changes nothing in the objects. The options are (a) accept both, (b) add a mapping line naming a public address, or (c) `git-filter-repo` before the first public push — only (c) removes them. Record which, and set `git config user.email` for future commits | ☐ |
| 16 | **Final cloud cost snapshot** | one dated `cost.json` generated after the last resource is stopped, and every public cost figure derived from it | the artifact plus `git diff --exit-code`. Three different totals were published simultaneously ($27.90, $54.71, $63.62) because each document quoted a different day's snapshot <!-- historical --> | ☐ <!-- derived: 27.90 = a superseded cost snapshot quoted as a record; 54.71 = the same; 63.62 = the same --> |

## 3a. Host and container parity, defined rather than assumed

The image job runs the whole suite inside the built artifact. That used to
report **283 passed / 31 skipped** against the host's 297 / 17, and the <!-- historical -->
difference was not incidental: `results_archive/` was excluded from the image,
so every test that recomputes a published metric from a replay bundle, checks a
derived artifact's provenance, or asserts the dataset-pin contract found
nothing and skipped. "The suite runs inside the image" was true. "The image
validates the released archive" was not, and only the second one is evidence.

`results_archive/` and `docs/` now ship in the image. The intended parity is:

| | host | image | why |
|---|---:|---:|---|
| collected | same | same | one suite, one tree |
| reproducibility tests | run | **run** | the archive is in the image |
| extra skips in the image | — | by REASON, not by count | see below |

⚠️ **This table used to assert a fixed count of five**, and the Dockerfile
comment said four root documents plus the Dockerfile. The sixth audit counted
**six** additional reasons in the actual runs. A hard-coded count is wrong the
day a test is added and tells a reader nothing about *which* checks did not
run, so it is gone: the image job asserts by REASON, and the property that has
to hold is that the only things skipped in there are the ones that cannot run
in there. The permitted reasons are:

- four repository-**root** documents (`README.md`, `HANDOFF.md`,
  `CONTRIBUTING.md`, `CHANGELOG.md`), outside the `aml-platform/` build
  context by construction;
- the `Dockerfile`, which is the recipe rather than an input;
- the data-dependent contract tests and the split-inflation determinism check,
  which need built intermediates and skip on the host too.

**Any other skip inside the image fails the build.** That list is in
`.github/workflows/image.yml`, and extending it is a deliberate act.

## 3b. Coverage, stated rather than chased — twice corrected, then acted on

Source-only line coverage is **78%**, measured with

```bash
pytest -q --cov=src/aml --cov-report=term
```

Every module below 65%, complete — not "the lowest", which is what this table
used to say while omitting the one at zero:

| module | coverage | what is uncovered |
|---|---:|---|
| `demo.py` | 19% | the generated-corpus writer below the CLI entry |
| `models/stability.py` | 31% | multi-config, multi-seed fitting |
| `leakproof/plant.py` | 51% | leak injection into a labelled corpus |
| `leakproof/sweep.py` | 57% | the sweep ladder and placebo arms |
| `models/train.py` | 59% | the checkpoint/resume and large-matrix paths |
| `manifest.py` | 62% | cache-rejection and output-verification branches |

**Two orchestrators left this table**, because `tests/repro/test_orchestrators.py`
now exercises them against synthetic corpora with real oracles rather than line
counts:

| module | was | now | the oracle |
|---|---:|---:|---|
| `eval/run.py` | 27% | **100%** | the metrics it recomputes from saved scores must equal, to 1e-9, the ones the training stage recorded from the same fit — and it must refuse a score file of the wrong length or with the wrong `txn_id`s <!-- derived: 0.000000001 = the comparison tolerance this row states, not a measurement --> |
| `drift/experiment.py` | **0%** | **99%** | four strategies × two evaluation buckets, with `train_rows` asserted against the construction: frozen sees the stable buckets, sliding-window sees exactly the previous one |

Writing the drift fixture found a defect immediately: `run()` reads five
manifest fields at the top and a **sixth**, `cramers_v`, a hundred lines later
when it records its metrics. The stage fitted eight models and then died with a
`KeyError` on its last statement. That is what zero coverage on an orchestrator
buys — the failure was reachable from the CLI the whole time.

⚠️ **Two corrections before that, both found by audits rather than by this
project.** The first version of this section ended *"These are exactly the paths
the 17 skipped tests cover."* False: the 17 skips are HI-Small **contract and
reconciliation** prerequisites and never enter a fit loop. The second version
fixed that sentence and still called its table "the lowest modules" while
**omitting `drift/experiment.py` at 0%** and quoting `eval/run.py` at 30% when
it was 27%. A table of the worst modules that leaves out the worst module is the
same error wearing different clothes. This one is complete by construction:
every module under 65%, with the total above it.

**Still no floor.** The six above are real gaps, and a floor met by executing
lines without asserting anything is worse than no floor. Set one when they have
oracles too.

## 4. Known-open, and deliberately shipped that way

Stating these is the release condition, not fixing them. Items struck through
were on this list earlier today and have since been measured.

- **No between-generator-run variance, and it cannot be estimated here.** Every
  interval in this repository is a *within-run* component. IBM publishes six
  fixed files, not a seeded generator, so HI-Small cannot be drawn again; LI-*
  differs in illicit ratio and would confound run-to-run variance with a
  configuration change. A limitation of the benchmark, not a skipped step.
  `docs/LIMITATIONS.md` §6.
- **A per-channel leak verdict is not a measurement.** The corrected placebo has
  a 46.1% noise floor, and two of three channel verdicts flipped between the two
  placebo designs while neither real arm moved. The positive control separates
  under both. Quote the control and the floor, not the ladder.
- **`precision@50` spans 0.356–0.485 across the three HI-Large seeds** — a 36%
  spread on the metric most often quoted as a headline. Quote the mean with the
  range or not at all.
- **Categorical collisions are unchecked.** The encoding no longer threatens the
  headline (see below), but nothing verifies that two payment formats do not
  share a hash bucket.
- **The split-inflation experiment is HI-Small only.** The preregistered
  HI-Medium confirmation has not been run. (The *ring null* has been confirmed
  on HI-Medium; the split-inflation experiment has not.)
- **The publication checker is syntactic.** It binds each value to the set of
  artifacts containing it and rejects values supported only by unprovenanced
  manifests — but it does not bind a value to its metric name, unit or budget. A
  typed result schema is the right end state and is not built.
- **The image is an editable install with tests inside it.** A wheel built in a
  builder stage and installed non-editably would be stricter, and would trade
  away running the suite inside the artifact that produced the results.

### Closed today

- ~~HI-Medium not re-evaluated under the permutation null~~ — done. The
  canonical sorted GBDT gives lift **0.907**; no canonical HI-Medium logistic
  re-evaluation under this null exists, so no figure is quoted for one.

  ⚠️ This line said "gbdt 0.920, logistic 0.946" until the sixth audit found <!-- historical -->
  it. Both are `eval3_Medium` — the lineage the canonical registry marks
  superseded — and **the 479-value publication gate reported success anyway**,
  because it finds those tokens elsewhere under other metrics and cannot bind a
  number to the label beside it. The gate admitted the exact defect it was built
  to prevent, in the document that certifies the release. Both values are in
  `results_archive/RETRACTED.json` now. <!-- historical -->
- ~~HI-Large not re-fitted under a deterministic row order~~ — done, three
  seeds, byte-identical training matrices.
- ~~The leak sweep predates its own placebo fix~~ — rerun; see above.
- ~~The categorical encoding may be carrying the linear claim~~ — measured on
  HI-Medium, ⛔ POOLED and therefore not a comparison: `precision@50` 0.5706 hashed, 0.5764 without, 0.5764 one-hot. A 1%
  range, hashed lowest. It is not carrying the claim.
