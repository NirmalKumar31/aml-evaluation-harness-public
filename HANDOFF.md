# Handoff — state as of 2026-09-17

Written to survive a context reset. Every number on this page is generated or
checked by `scripts/make_tables.py --check` and `scripts/release_facts.py
--check`, both of which run in CI against this file.

> ⚠️ **"Everything here is verified" used to be the second sentence of this
> page, and it was not true when it was written.** A fifth audit found the
> page quoting the superseded HI-Large lineage, a split-inflation share that
> its own section contradicted two paragraphs later, and a test count with the
> wrong semantics — all under a heading asserting verification. The checkers
> named above are now the claim; this prose is not.

---

## Where the project stands

The local pipeline, the cloud run, three internal audit rounds and **six
external audits** are done. Those rounds **retracted five published claims and
one reproducibility claim**, which is the most important thing on this page.
Every technical blocker any of them raised is closed; what is left needs a
person rather than a commit, and is listed at the bottom.

```text
repo      github.com/NirmalKumar31/aml-evaluation-harness   [PRIVATE]
branch    main · ci + gates verified locally at this commit;
          the image job runs only in CI
tests     415 collected · lint clean   (generated: results_archive/derived/release_facts.json)
numbers   every published value traces to an artifact, from a canonical
          lineage, and is not on the retraction registry. The COUNT is not
          restated here -- it moves whenever a document does, and it was
          479 for two rounds after it stopped being 479. Run
          `make release-check`, or read the gate's own output.
spend     STILL ACCRUING. The figure lives in ONE place and is provisional
          until the meter stops: aml-platform/docs/RUNBOOK_cloud.md, the one
          cost table, generated from results_archive/derived/cost.json.
          Restating it here is what made three documents disagree.
          -> aml-platform/docs/RUNBOOK_cloud.md, the ONE cost table
```

### ⛔ The retractions, and one false reproducibility claim

Read these before quoting anything. A second external audit (`v2 audit.md`)
found all of them; each was verified here before being acted on.

1. **The 1.43× ring lift is retracted; measured, it is 0.9497.** <!-- historical --> The null used
   recall pooled over *all* positive account-days, and 87% of HI-Large's carry
   no ring label. Against a within-day permutation null the model covers
   slightly **fewer** distinct rings than chance, p = 1.000 on all three seeds.
   Confirmed on HI-Medium too — the canonical sorted gbdt gives lift
   **0.907**. Two independent generator runs, every lift below 1.
   `paper/RESULTS_hi_large.md` §4.

   ⚠️ This bullet used to add "logistic 0.946" and quote gbdt at 0.920. Both <!-- historical -->
   came from `eval3_Medium`, which the canonical registry lists as superseded —
   it evaluated fits made while the training load did not sort. No canonical
   re-evaluation of the HI-Medium logistic under the permutation null exists,
   so no figure is quoted for it. <!-- historical -->

2. **"Inflated by leakage" — retracted, then PARTLY REINSTATED.** The
   preregistered experiment ran: a naive split reports AP +40%. That was first
   attributed 97% to prevalence, which was wrong — the ratio arithmetic did not
   mean what it was reported as meaning, and the division assumed AP scales
   linearly with prevalence. A counterfactual decomposition gives **47%
   prevalence / 53% detectability**. So the effect is about half, not 3% — but
   "detectability" is what the design establishes, and "caused by leakage" is an
   interpretation on top of it. `paper/RESULTS_split_inflation.md` §3.

3. **"Near-saturated" is withdrawn, and so is "most of the separability".** <!-- historical -->
   The first asserts closeness to a maximum that was never bounded; the second
   is an undefined fraction with no measured denominator. The measured
   statement is: on HI-Medium with this 32-feature representation, a logistic
   fit reaches `precision@50 = 0.57060` and the eight-seed GBDT mean is
   0.82480 with observed range 0.59144–0.89815. The GBDT's worst seed clears
   the logistic fit by 0.02 and its best by 0.33, so the margin the model adds
   is not a single number either.

4. **"Deterministic — same inputs, same predictions" was false above 200,000
   rows.** Both histogram learners build bin thresholds from a 200,000-row
   subsample of *positions*, and the training load had dropped its
   `ORDER BY txn_id` on the strength of a **20,000-row** experiment — below the
   threshold, where order genuinely does not matter. Measured at 210,001 rows:
   the same rows in a different order move sklearn's predictions by about 0.04
   and LightGBM's by about 0.05. `test_the_bin_subsample_makes_row_order_matter_above_200k`
   recomputes both on every run; the line used to quote 0.063/0.064 from a run <!-- historical -->
   that left no artifact.

   The sort is restored and `train_matrix_sha256` is recorded. Two independent
   HI-Medium runs produce identical matrix hashes, prediction hashes and
   metrics; and at HI-Large all three seeds — separate runs, hours apart —
   produced a byte-identical 124,992,128-row training matrix. The sort costs
   26 minutes and peaks at 30 GB of 31. It also explains the two conflicting Medium lineages: the sorted run
   reproduces the *older* one exactly, so the README's number was right and the
   rerun done during the unsorted window was the corrupted one.
   `docs/RESULT_LINEAGE.md`.

5. **Per-channel leak verdicts are not measurements.** The leak placebo
   permuted globally, carrying a distribution shift on top of the misalignment
   it meant to measure. Rerun within `(side, day)`: the noise floor is
   **46.1%**, not 22%, and **two of three channel verdicts flipped** while
   neither real arm moved. The positive control separates under both designs,
   so the harness is not blind — but the per-channel ladder should not be
   quoted. `paper/RESULTS_leak_detection.md` §1b.

**One claim that was challenged and held.** The hashed categorical encoding was
suspected of flattering the linear baseline. Measured on HI-Medium:
⛔ these are POOLED levels on the two-regime window (1.16x-1.26x a random ranker), so they cannot settle the encoding question — `precision@50` is 0.5706 hashed, 0.5764 without the categoricals, 0.5764
one-hot — a 1% range with the hashed arm *lowest*. The headline does not depend
on the encoding.

**Three lessons that generalise.**

*On numbers:* 1.43 was computed by code, from artifacts, under a checker that
verified it traced to a manifest — and was still wrong, because the **estimand**
was wrong. Provenance discipline cannot detect that. Only a negative control can.

*On controls:* every time a null or a control was rebuilt properly, the number
it produced moved a long way — ring lift 1.43 → 0.9497, split inflation 97% → 47%, <!-- historical -->
leak noise floor 22% → 46%. A weak control does not produce a slightly wrong
answer; it produces a confidently wrong one.

*On tests:* four separate tests in this repository were **written around the
bug they were named for** — the row-order test that ran below the threshold it
was protecting, the stale-partition test that deleted the file by hand first,
the loader test that asserted the training load must *not* sort, and a leak
coverage check that tested nullness when it meant coverage. A test can hold a
defect in place as firmly as it can hold a fix, and a green suite is not
evidence that the assertions are the right ones.

### The claims that hold

| claim | evidence |
|---|---|
| Pipeline processes **179,702,229** rows end to end on one 31 GB VM | `paper/RESULTS_hi_large.md` |
| Model trained on the **full 124,992,128-row** training split, 3 seeds | `results_archive/gold/large_sorted_lgbm_s{0,1,2}/` |
| **sklearn cannot fit** this matrix in 31 GB (33.5 GB, `X_DTYPE=float64`); **LightGBM can** (14.9 GB). Both run | §4 of that file |
| Same code, arm64 macOS → amd64 Linux, **matching metrics** (not proven bitwise — the arm64 manifest predates `predictions_sha256`) | `docs/LIMITATIONS.md` §7 |
| **Bitwise repeatability on one architecture**: two HI-Medium fits and three HI-Large seeds, identical matrix and prediction hashes | `docs/RESULT_LINEAGE.md` |
| **A 32-feature logistic reaches `precision@50 = 0.57060` on HI-Medium**, against an eight-seed GBDT mean of **0.82480** (range 0.59144–0.89815). No claim is made about what *share* of it a linear model reaches: that fraction has no measured denominator | `results_archive/gold/eval_Medium/baseline/` and `eval_Medium/seed{0..7}/` |
| **Every budget metric recomputes from 1.3 MB**, no dataset needed | `results_archive/replay/` + `scripts/verify_replay_bundle.py` |
| A naive split reports **AP +40%**, of which **47% is composition (prevalence) and 53% score distribution** | `paper/RESULTS_split_inflation.md` |
| **No per-structure detection claim is made.** The published 3.05× (p=0.0008) is retracted — its H0 assumed one rate per ring — and the ensemble has never been tested under a like-for-like null. A single-seed diagnostic on `medium_gbdt_s0` gives p = 0.46633 and establishes nothing about the ensemble <!-- historical --> | `results_archive/derived/typology_null.json` |
| `ring_recall` needs a null — and the first null was wrong. Against a within-day permutation: lift **0.9497**, p **1.000** for *more* rings than chance, lower-tail p **< 0.001**, which is the floor 1,000 permutations can express | `large_sorted_lgbm_s{0,1,2}` |

### The rule this project adopted, the hard way

> **If a number is not emitted by code from an artifact, it is not a number.**

`scripts/make_tables.py` generates every published figure with
`(rung, model, seed|ensemble, unit, source)`. `--check` fails on any value in a
document that no artifact supports, and runs in CI. It **fails closed** on a
missing or empty document list.

This exists because the same defect recurred four times: the four README cells
(one *back-solved* from its neighbours, so no consistency check could ever have
caught it), and the ring lift published as 1.08 → hand-corrected to 1.28 →
**measured 1.43** → **retracted entirely at 0.9497**. <!-- historical --> A quantity defined over a
distribution of ring sizes is not recoverable from any summary of it, so no
scalar was ever going to be right.

And then a harder lesson: **1.43 was computed by code, from artifacts, under a
checker that verified it traced to a manifest — and was still wrong**, because
the estimand was wrong. Provenance discipline cannot detect that. Only a
negative control can: a null must return "no effect" on data built to contain
none. See `docs/LIMITATIONS.md` §2.

`` marks values legitimately computed in prose (p-values, a
correlation quoted from another doc). Per-seed **means are computed**, not
exempted; each marker is an auditable choice rather than a silent one.

⚠️ **Three different numbers were being called "markers".** This line said 68
"currently"; `release_facts.json` reported a larger figure because it counted
every Markdown file including six archived audits; and the publication gate
reports a third number that is not markers at all — it counts exempted numeric
*tokens*, several of which can sit on one marked line. All three could drift
independently because `release_facts --check` never validated the field. The
counts are now generated with their scope attached —
`derived_markers`, `derived_markers_current`, `markdown_files`,
`markdown_files_current` — and verified against a fresh collection. Read them
there rather than from a sentence.

---

## Azure — READ THIS BEFORE TOUCHING IT

> **Identifiers are deliberately generic here.** This file is in a repository
> that may be public. Subscription description, storage-account and registry
> names carry no secret — an account name is discoverable and a name is not a
> credential — but a public document has no reason to publish an inventory of
> someone's cloud estate, and `az resource list -g <rg>` reproduces it in one
> command for anyone who is supposed to have it.

```text
subscription   an Azure free trial ($200 credit, spending limit ON)
resource group <rg>                 one group, so teardown is one command
region         eastus
VM             Standard_E4ds_v7 · 4 vCPU · 31 GB · RUNNING
storage        ADLS Gen2, allowSharedKeyAccess=false, managed identity only
registry       Basic, provisioned and ultimately unused
                 (ACR Tasks are blocked on trial subscriptions)
spill disk     1 TB StandardSSD · persistent
burn rate      $0.416/hr VM + $0.125/hr disks & IP, at list price
               -> aml-platform/docs/RUNBOOK_cloud.md for the one cost table
```

```bash
# The group name is whatever `infra/main.bicep` was deployed with.
az group list --query "[?starts_with(name,'aml')].name" -o tsv
```

**The VM is still running.** Tear down with:

```bash
az group delete -n <rg> --yes --no-wait
az group delete -n cloud-shell-storage-eastus --yes --no-wait   # if it exists
```

> ⚠️ **`/mnt/scratch` is the ephemeral resource disk. Azure wipes it on
> deallocate.** Stopping the VM to save money already destroyed 91 GB of work
> once. It currently holds the 15.9 GB HI-Large CSV, the 23 GB feature table and
> all intermediates. `/mnt/spill` is a managed disk and survives.
>
> ⚠️ **Never click "Upgrade to pay-as-you-go."** It is the only thing that
> removes the free-account spending limit, and it is irreversible.

**Credentials:** `az login` interactively, in the user's own terminal. No
service principal, no client secret, no connection string — ever. Services use
managed identity. A Kaggle token was pasted into chat once and should be
revoked; it turned out to be unnecessary (AMLworld downloads unauthenticated).

**Reproduce the cloud run:** `aml-platform/docs/RUNBOOK_cloud.md` has the exact
sequence, including a failure table that is the most useful part of it.

---

## Audit history

Each round's Closed/Open remediation log lives in
[`docs/archive/REMEDIATION_LOG.md`](docs/archive/REMEDIATION_LOG.md) — a
record, not current state. What matters here is the pattern it shows:

- **Provenance discipline converged; estimands did not.** Every round tightened
  the machinery that verifies *a number came from this code*, and nothing
  verified *this code computes the intended quantity*. Errors of the second
  kind were produced at roughly the rate they were fixed.
- **One quantity — how many distinct transactions an alert budget covers — took
  three definitions, two of them retracted**, each inferring the answer from a
  saved aggregate instead of recomputing it from the primitive the code already
  had.
- **The largest error was found by asking for a denominator nobody had
  recorded**: transactions per day. See
  [`aml-platform/docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md) §1.

Two gates now target that failure mode rather than its instances: no published
ratio may be an exact affine function of two published counts, and a
constructed-answer fixture discriminates the alert-unit definitions. Both are
in `aml-platform/tests/repro/test_audit_regressions.py`.

## What is left

Full list with commands: `aml-platform/docs/RELEASE_CHECKLIST.md`.

### Decisions only the user can make

1. **Rotate the Kaggle token.** One was pasted into a chat transcript. It was
   never needed — AMLworld downloads unauthenticated, which the cloud run
   proves — and it was shredded from the VM, but pasted is pasted.
2. **Make the repo public?** The `gates` workflow runs gitleaks over the
   **full history** on every push and reports 0 findings; the commit count is
   deliberately not written here, because it was 57 in this sentence for three
   audits after it stopped being 57. The 16 `Learning/` files still reachable
   in early commits are 437 KB of study notes with no emails, GUIDs or keys.
   So the choice is *accept* or *rewrite with git-filter-repo*, and it is a
   taste question rather than a security one.
3. **Tear down Azure?** Nothing needs the VM. $0.54/hr at list price for the
   whole resource group while it runs.
4. **GHCR package visibility**, branch protection, and a signed tag.

### Open methodological items — documented, not fixed

All in `aml-platform/docs/LIMITATIONS.md`, which every auditor has called the
best thing in the repo.

1. **There is no manuscript.** The stated goal is an arXiv preprint and the
   repository contains no `.tex`, no `.bib`, no abstract; `CITATION.cff` says
   `type: software`. `paper/` holds results documents written for this
   repository's readers, not a paper. Every framing recommendation an auditor
   has made — reorder the argument, lead with the admissibility result, cut
   the correction history — is advice about a document that does not exist
   yet. Writing it is the next substantive piece of work, and the material
   for a short one is already here: the wind-down profile, `nonbinding_days@k`
   as an estimand-existence precondition, the lift/spread bias asymmetry, and
   the replay bundles as licence-safe verification.

2. **The typology null and the withdrawn 3.05× are not the same basis.** The
   withdrawn figure is an eight-seed score-averaged ensemble from
   `gold/typology_Medium/stability.json`; the null that retired it runs on one
   archived replay from the `models` lineage, and the stability artifact
   predates the many-to-many ring-membership correction (the Medium replay
   holds 5 account-days belonging to two rings each, which the old collapsed
   join would have mis-assigned — `src/aml/eval/metrics.py:794`). So the
   published H0 is demonstrably false and the nearest measurable basis gives
   an ordinary result, but **"3.05× is at chance" has not been demonstrated**
   and no current document claims it.

   The test that would settle it: rebuild the HI-Medium feature table under
   current HEAD, rerun the eight-seed typology sweep, cut a replay bundle for
   the **ensemble** scores, and run `permutation_spread_null` against it —
   asserting that the null's per-typology observed rates equal the source
   artifact's, ring for ring. It needs hours of compute and more free disk
   than the machine this was corrected on had (10 GB). `typology_null.json`
   records the mismatch under `permutation_spread_Medium.basis` so no
   downstream reader can treat the two as interchangeable.

3. **The leak sweep has no honest-but-informative control arm**, so its
   per-channel verdicts mean "differs from its own permutation", not "leaks" —
   `reversed_window` is scored as detected on a real AP ratio of 0.9951, below
   the clean baseline. See `paper/RESULTS_leak_detection.md` §7.

4. **Between-generator-run variance cannot be estimated from this benchmark.**
   IBM publishes six fixed files, not a seeded generator, so HI-Small cannot be
   drawn again; LI-* differs in illicit ratio, so it confounds run-to-run
   variance with a configuration change. An earlier version of this file called
   the fix "cheap" and named both of those — it was wrong on both counts. This
   is a limitation *of the benchmark*.
5. **The leak sweep was rerun under a fixed placebo, and the per-channel
   verdicts moved.** The old placebo permuted globally, carrying a distribution
   shift across the split and the calendar on top of the misalignment it meant
   to measure. `sweep_version 2.0.0` permutes within `(side, day)`
   (`leaksweep2_Small`). The noise floor went from a 21.97% spread to <!-- historical -->
   **46.1%**, and while two of three channels separate
   from placebo under both, **they are not the same two**: `reversed_window`
   failed under the old placebo and separates under the new one;
   `future_counterparty` did the reverse. Only the positive control (`target`,
   real AP ratio 3.4508 vs placebo 0.7713) is robust to the change. Treat the
   individual channel verdicts as unstable.
6. **Categoricals are hashed into 1000 buckets** and fed to a linear model as
   numbers. This has been ablated on HI-Medium, but the artifact carries
   **partial provenance only** — `categorical_ablation_medium.json` records a
   commit and nothing else: no `code_tree_sha256`, no `scope_clean`, no
   `inputs`, no `env_lock_sha256`. It ran on the cloud VM against a feature
   table that exists nowhere else, so it cannot be regenerated while that VM
   is gone. Read the result as indicative, not as settled, in a repository
   whose one rule is provenance
   (`results_archive/derived/categorical_ablation_medium.json`): `precision@50`
   is 0.57060 hashed, 0.57639 with the categoricals dropped, and 0.57639
   one-hot. The linear-baseline headline does not depend on the encoding.
   One seed, one rung — collision counts are still not measured, so this
   bounds the concern rather than closing it.
7. **Split inflation is HI-Small only.** The preregistered HI-Medium
   confirmation has not been run. (The *ring null* has been confirmed on
   HI-Medium; the *split-inflation* experiment has not.)

### Explicitly not claimable

- Anything about detecting money laundering in the real world
- That the model exploits ring structure — **measured, and it does not**
  (lift 0.9497, upper-tail p = 1.000, lower-tail p < 0.001 — the resolution
  floor of 1,000 draws, not a measured magnitude)
- That naive splits inflate results *through leakage*. The decomposition
  attributes **47%** of the AP gap to composition (which positives survive the
  split) and **53%** to the score distribution, and "score distribution" is not
  the same claim as "leakage" — see the exchangeability caveat in
  `paper/RESULTS_split_inflation.md`
- That graph features do not help AML (every feature tested was a per-account
  time series; no subgraph, motif or flow-tracing feature was ever computed)
- That detection is structure-dependent **at all** — retracted, and not
  replaced: the ensemble result has never been tested under a like-for-like
  null, and the single-seed diagnostic is a diagnostic. Against the within-day
  permutation null the spread is the 53.5th percentile of chance
  (p = 0.46633), and no per-typology ordering is established either: six of
  eight concentration intervals span 1 and none survives Holm. The raw rates
  track exposure to the wind-down. The ordering also does not replicate
  between rungs (p ≈ 0.014 against perfect replication)
- That more training data improves detection (four confounds vary at once)
- **Any HI-Large ↔ HI-Medium comparison.** An earlier version of
  `RESULTS_hi_large.md` built its narrative on one and was retracted; it is kept
  at `paper/archive/RESULTS_hi_large_RETRACTED.md` so the error stays on record.
- Anything under a budget metric as a forecast of review load under a
  **different alert unit** — AMLworld has no customer or case structure, so the
  `(account, day)` unit cannot be varied

---

## Gotchas that cost hours

| symptom | cause |
|---|---|
| exit **137**, no message | OOM-killed. Docker reports nothing else — sample memory during long runs or you are guessing |
| `Problem with the SSL CA cert` on every blob read | **not** auth. Needs `azure_transport_option_type='curl'`; `ca_cert_file`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE` all do nothing |
| `abfss do not manage recursive lookup patterns` | `**/*.parquet` is illegal on abfss, and `/**` is no substitute (each stage writes `manifest.json` into its own output dir). See `io.parquet_arg` |
| `Failed to get token from ChainedTokenCredential`, **different file each run** | concurrency, not permissions. DuckDB fetches a token per file open and never caches; IMDS cannot serve them in parallel. Azure paths default to `threads=1` |
| `TasksOperationsNotAllowed` from `az acr build` | trial subscriptions cannot use ACR Tasks. Build on the VM |
| run-command returns truncated JSON | manifests exceed its output limit. Publish to blob and download from there |
| run-command returns `Conflict` | a previous invocation is still running. Only one at a time |
| CI `no artifacts under results_archive` | a bare `gold/` in `.gitignore` matches at **any** depth. Anchor it to `data/` |

## Layout

```text
README.md                           leads with the linear-baseline finding
HANDOFF.md                          this file
aml-platform/
  src/aml/                          pipeline
  scripts/make_tables.py            emits + verifies every published number
  scripts/measure_dataset_facts.py  the payment-format evidence, as an artifact
  scripts/run_hi_large.sh           the cloud run, end to end
  results_archive/                  101+ manifests — the provenance for everything
  paper/                            measured results, with claim boundaries
  docs/LIMITATIONS.md               every caveat, one place
  docs/RUNBOOK_cloud.md             the cloud sequence as executed
  infra/main.bicep                  VM, network, storage, identity, spill disk
```
