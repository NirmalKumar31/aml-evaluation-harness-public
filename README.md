# Alert-Budget-Aware Evaluation for Transaction Monitoring

**On IBM's AMLworld benchmark, most of a reported detection score is handed
over by the data rather than earned by the model.** The generator stops
mid-test-window: daily volume falls from 3,021,866 transactions to 7, and the
laundering share rises from 0.0008 to 0.4286. Pool that window and a uniformly
random ranker already scores `precision@50` between **0.45392 and 0.49147** —
the published logistic model's 0.57060 beats it by only **1.16×–1.26×**. <!-- derived: 0.57060/0.49147; 0.57060/0.45392 -->

Restrict to the seven days the generator was still running and the comparison
starts to mean something:

| ranker, 50 alerts/day | `precision@50` | true positives | vs the null |
|---|---:|---:|---:|
| uniformly random | 0.00243–0.00244 | — | 1× |
| logistic regression, 32 features | 0.04286 | 15 of 350 | **17.6×** <!-- derived: 0.04286/0.00244 --> |

⛔ **The boosted-model row is withdrawn.** It read 0.75714 and 310.3×, from <!-- historical --><!-- derived: 310.3 = a WITHDRAWN value this sentence exists to narrate. It came from the superseded eval3_Medium lineage and is deliberately not restated as current; 0.75714 = the same -->
`replay/medium_gbdt_s0` — a bundle that reproduces `gold/eval3_Medium/gbdt`
bit-identically, and `results_archive/CANONICAL.json` marks that lineage
**superseded**: those fits were made while the training loader did not sort
its rows. The canonical value for that model is **0.793981** pooled against
0.880787, and no canonical volume-segment decomposition exists — rebuilding  <!-- derived: 0.880787 = a WITHDRAWN value this sentence exists to narrate. It came from the superseded eval3_Medium lineage and is deliberately not restated as current -->
one needs a refit, recorded as open rather than approximated. The logistic row
stands: a deterministic fit, identical in both lineages.

⚠️ **And a lift is bounded.** Every head day holds far more positives than the
budget has slots, so a perfect ranker scores 1.0 there and the largest
attainable lift is **409.8×** — the reciprocal of the null, a property of the <!-- derived: 1/0.00244 -->
generator rather than of any ranker. Quoted bare it is the precision restated;
quote the count, or the precision against that bound. The budget binds hard
regardless: at 50 alerts/day no model can exceed **4.73%** recall, because
only 858 of 18,130 positive account-days are reachable.

Verify the machinery in about a minute from a cold clone, with no dataset
and no AMLworld bytes:

```bash
cd aml-platform && make setup && make replay-demo   # 42 metrics, 0 mismatches
# ~70 s cold -- it generates the corpus first -- and ~2 s once the stage cache
# is warm. The metrics it prints are 1.000000 by construction: the corpus is
# synthetic and trivially separable. What is verified is the MECHANISM, that
# every published budget metric recomputes from a 0.03 MB bundle and nothing
# else.
```

AMLworld is synthetic, from a single generator, never validated against real
transactions — **every number here is a claim about a simulator**, and the
contribution is evaluation methodology, not detection performance. What may
and may not be claimed:
[`docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md). What was retracted
along the way: [`CHANGELOG.md`](CHANGELOG.md), and the summary below.

## The headline

**On this benchmark, a pooled budget metric is barely a result.** A uniformly
random ranker scores `precision@50` between **0.45392 and 0.49147** on the
HI-Medium ring-aware test split. The published logistic figure of 0.57060 beats
that by only **1.16×–1.26×**. <!-- derived: 0.57060/0.49147; 0.57060/0.45392 -->

The reason is that AMLworld's generator **winds down**. It emits background
traffic and then stops, leaving its remaining laundering patterns to play out
against almost nothing:

```text
2022-09-16   3,021,866 transactions   prevalence 0.0008
2022-09-17       2,020 transactions   prevalence 0.5936     <- overnight
2022-09-28           7 transactions   prevalence 0.4286
```

A random ranker's expected precision is a slot-weighted mean of daily
prevalence, so a window containing both regimes hands it almost half the
alerts for free. Restrict to the seven volume days and the comparison becomes
informative:

```text
HI-Medium precision@50, random-ranker null = 0.00243-0.00244 on the volume days

  logistic regression, 32 features        0.04286      17.6x null  <!-- derived: 0.04286/0.00244 -->
  gradient-boosted trees, same features   0.75714     310.3x null  <!-- derived: 0.75714/0.00244 -->
```

⛔ **Three days (2022-09-26/27/28) hold fewer account-days than the budget**, so
`precision@50` there equals the day's prevalence for *any* ranker including a
constant. A budget metric presupposes a binding budget.

**What this licenses:** boosting buys roughly **18×** what the linear baseline
does on the days where ranking is a real problem. **What it does not license:**
any pooled level from this window as a model comparison, and any statement
about linear separability — [§1 of
`docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md) retracts this page's
former headline. Measured by `scripts/budget_null.py` on the evaluated split;
values are bracketed because the split's per-day totals are bounded rather than
materialised here. See [`CHANGELOG.md`](CHANGELOG.md).

![HI-Medium precision@50: a single logistic fit against the eight-seed GBDT
spread, at an alert budget of 50 account-days per
day](aml-platform/paper/figures/precision_at_budget_medium.svg)

## What this project found

Full write-ups, with an index, in [`aml-platform/paper/`](aml-platform/paper/README.md); what may and may
not be claimed in [`docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md).

**1. The review budget binds before model quality does.** `recall@50` caps at
**4.73%** of positives on HI-Medium regardless of the model, because the
attainable count is `sum_d min(P_d, 50) = 858` against 18,130 positive
account-days. Reporting recall without its ceiling is uninterpretable. This is
arithmetic on a generator artifact, not a discovery — the contribution is
emitting `recall_ceiling@k` and `recall_efficiency@k` beside every number.

**2. The most stable metrics are the least useful — and the instability has a
name.** Across 8 seeds: ROC-AUC range 0.1%, average precision 16.9%,
`precision@50` 37.2%. The mechanism is not "optimizer noise": in this
configuration `random_state` has exactly one live consumer, the **200,000-row
subsample used to estimate histogram bin edges**. A second library reproduces
it — the canonical HI-Large LightGBM lineage, with `deterministic=True` and no
bagging, spreads **30.2%** on `recall@50`, `precision@50` and <!-- derived: (0.03238-0.02374)/((0.03238+0.02374+0.02973)/3) -->
`recall_efficiency@50` alike. So: at 0.11% prevalence, bin-edge estimation
alone moves the operationally meaningful metric by about a third, and since
these seeds never vary row order, threads or platform, that is a **lower
bound**.

**3. Leak detection is uninterpretable without a negative control.** A
permuted-leak placebo puts the noise floor at a **46.1% spread**, so any
single-run AP-ratio threshold below about 1.10 is reading noise. Of three
injected channels, *which two separate from placebo is not stable* across
placebo designs — only the positive control survives the change.

**4. Adding features made detection measurably worse.** Paired A/B over 8
seeds: +2 counterparty counts → −5.1% `ring_recall@200`, 0/8 seeds better;
+4 volume-normalised ratios → −6.4%, 0/7/1. Diagnosed, not just observed: the
count features correlate **0.977–1.000** with volume features already present.
⚠️ The sign test's p-values sit at the **floor** an n=8 design can express, so
the multiplicity family is a design decision — see LIMITATIONS §6.

**5. ⛔ RETRACTED — no per-structure detection claim is made from this
benchmark.** The published spread of 3.05× against a null median of 1.58×,
p = 0.0008, is retracted: it assumed one detection probability per ring, which
the generator's wind-down falsifies. <!-- historical --> Two replacements were then withdrawn as well — the first
measured exposure on the wrong ring population with arithmetically impossible
rates, the second at the wrong budget on a model outside the ensemble.

**The ensemble result has never been tested under a valid like-for-like null**,
and is withdrawn for that reason rather than replaced. A single-seed
diagnostic on one archived replay (`medium_gbdt_s0`, `ring_recall@50`) gives an
observed spread of 3.46875 at the 54.3rd percentile of its own within-day
permutation null, p = 0.45661, over 50000 draws. <!-- source: 0.45661 <- derived/typology_null.json#permutation_spread_Medium.p_value -->
**That is a diagnostic on one seed, and it establishes neither the ensemble
result nor any general conclusion about laundering structure.** One
per-typology deviation does survive Holm at that draw count — FAN-IN is
covered at 0.594 of its own null, p_holm = 0.04048 — and the previous 400-draw
run could not have found it. See
[`paper/RESULTS_typology.md`](aml-platform/paper/RESULTS_typology.md).

**6. A metric can be right, traceable, and still measure the wrong thing.**
This project published `ring_recall@200 = 0.874` on HI-Large with a **retracted** <!-- historical -->
"lift 1.43× over a size-matched independence null" and the **retracted** claim <!-- historical -->
that the model spreads its hits across distinct rings. Both were withdrawn when
the null was replaced. Re-measured against a **within-day permutation null**:
`ring_recall@200` **0.86876**, null **0.91492**, lift **0.9497** — below 1.
HI-Medium re-run end to end gives lift **0.907**. **The direction reverses**,
by about 5%.

> The uncomfortable part: 1.43 was computed by code, from artifacts, under a
> checker that verified it traced to a manifest. **Provenance discipline cannot
> detect a wrong estimand.** What caught it was a negative control — a null must
> report "no effect" on scores drawn independently of ring membership, and the
> first replacement returned 0.497 on exactly that.

**7. A naive split reports +40% average precision** — decomposed as **46.7%**
prevalence and **53.3%** detectability by a counterfactual that rescores the
excluded positives from the retained ones. These are contrasts under an
exchangeability assumption, not causal effects.

## Quick start

```bash
cd aml-platform
make setup          # venv + locked dependencies
make demo           # generates a corpus, runs every stage, ~30 seconds
make test           # 422 tests collected; pass and skip counts vary by
                    # environment (data-dependent contract tests)
```

`make demo` needs **no data download**. Its numbers are meaningless by
construction and it says so. The published results need the real dataset:

```bash
make get-data       # instructions for IBM AMLworld (CDLA-Sharing-1.0)
make verify-data    # sha256 the files you have against the pin (5 of 6
                    # locally; --require all makes absence an error)
make all VARIANT=Small CUT=2022-09-05
```

## Checking a published number yourself

⚠️ **Read this first if you are on the public snapshot.** The nine **replay
bundles** — about 9 MB, 526,355 rows, enough to recompute every published
budget metric with no dataset download — live in the **private development
archive** and are **NOT redistributed here**. Their CDLA status is unreviewed
(see [`DATA_LICENSE.md`](DATA_LICENSE.md)), so they are withheld rather than
published on an assumption.

What ships in their place is
`aml-platform/results_archive/replay_inventory.json`: the bundle names, file
names, row counts and per-file sha256, so you can see exactly what is missing
and verify a regenerated copy against it.

**The MECHANISM is verifiable here; the archived rows are not.** Only the
AMLworld-derived rows are withheld, so no-data replay itself runs anywhere:

```bash
cd aml-platform && make replay-demo    # ~8 s, no dataset, no AMLworld bytes
```

It generates a synthetic corpus, cuts a bundle from it, and recomputes every
published budget metric from that bundle alone — **42 metrics, 0 mismatches**,
about 0.03 MB. That is the whole differentiator, demonstrated without anything
licensed. An earlier version of this paragraph said no-data replay
verification "is not available" in the snapshot, which was false about the
mechanism and true only of the rows. <!-- historical -->

The commands below, which replay the **archived** bundles, do need them;
without them they **skip** and name the missing input (`replay bundle not
archived in this checkout`, `no replay bundles in this checkout`). Those are
documented skips, not passes. Pass and skip totals move whenever a test is
added, so this page does not pin them — run `make test` and compare against
`results_archive/derived/release_facts.json`, which is generated and gated.

To get them, obtain AMLworld from its official source and regenerate:

```bash
# once the dataset is in place and `make verify-data` agrees with the pin
python scripts/make_replay_bundle.py --features … --splits … --scores … --dest …
```

With the bundles present, this is the check:

```bash
pytest -q -k replay
python scripts/verify_replay_bundle.py \
  --bundle   results_archive/replay/small_gbdt_s0 \
  --manifest results_archive/gold/infl_eval_ring-aware_s0/manifest.json
```

They recompute `recall@k`, `precision@k`, the ceilings and `ring_recall@k`.
⚠️ **The permutation null, the lift and the tail p-values are not recomputed**,
so finding #6 is the one headline this cannot check. The bundles ship the
ingredients, but a permutation moves scores across the top-1000 cut-off, so the
sufficiency argument that justifies the truncation has not been shown to extend
to the null.

| tier | what you need | validates |
|---|---|---|
| **1. No-data demo** | a checkout, Python 3.12, ~1 min | that the six stages **compose** and every manifest is written. **No** detection claim |
| **2. Replay verification** | a checkout, ~5 s per bundle | that the published budget metrics **recompute exactly**, minus the null |
| **3. HI-Small / HI-Medium** | Kaggle account, 3.5 GB, 16 GB RAM | the canonical lineage, leak sweep, split-inflation counterfactual, typology null |
| **4. HI-Large cloud run** | Azure, 4-vCPU quota, 17 GB file | the 179.7M-row result and that LightGBM fits 125M × 32 in 31 GB where sklearn cannot |

## The engineering, and why it matters here

Finding #4 is the reason this repository exists. The experiment said the new
features hurt — and an audit then found the pipeline was **still shipping
them**, while a separate bug meant retuning the model silently reported the
*previous* model's metrics under a `status: ok` manifest. Those are one bug
wearing two hats: **the system let its author lie to himself.** Twelve defects
of that family are listed below; each is covered by a regression test. (This
said "sixteen" over a table of twelve, and the gap widened when the table was
shortened in a rewrite. The count now matches the rows.)

| defect | what it would have cost |
|---|---|
| Shipping a model the measurement had already rejected | wrong results, reported as correct |
| Training cache key omitted the hyperparameters | a retune returns stale metrics, silently |
| No stage hashed its own source | editing SQL did not invalidate the cache |
| DuckDB had no Azure credential | `401` — the cloud run dies in stage 1, minute 1 |
| `ensure_dir` was a no-op on URIs | writes fail on ADLS Gen2's real directories |
| Retry classifier treated auth failure as transient | three full-price retries of a six-hour stage |
| A stage dropped the primary join key | an entire sub-pipeline unreachable |
| Container image built for arm64 | fails to start *after* the cluster is billed |
| TLS failed inside the container | reads as an auth failure and is not one |
| `**/*.parquet` illegal on `abfss://` | the cloud run dies in stage 1 of 7 |
| Token fetched per file open, never cached | dies mid-read on a *different* file each attempt |
| Reproducibility measured on the artifact hash | "different machine" and "different model" were indistinguishable |

Supporting machinery: manifest-based stage caching keyed on code, config and
environment identity; a canonical/superseded **lineage registry**; a
**retraction registry** that fails CI on any retired value; a **publication
gate** that rejects any published decimal no artifact supports; an exit-code
taxonomy; batch-vs-online feature parity tests; a storage layer where local
paths and `abfss://` URIs are the same code path. Detail in
[`docs/ENGINEERING_NOTES.md`](aml-platform/docs/ENGINEERING_NOTES.md).

**Cloud:** the pipeline ran end to end on Azure — containerised, ADLS Gen2,
managed identity, no secret anywhere — and **every one of the 15 metrics
recorded in both manifests matched the laptop run to full float precision**,
including a 500-resample bootstrap. The sixteenth compared quantity is not a
metric at all: it is the serialized model file's hash, and it differs because
joblib embeds platform detail. Saying "15 of 16 metrics" counted a file as a
metric. What that does and does not establish is in
[`docs/ENGINEERING_NOTES.md`](aml-platform/docs/ENGINEERING_NOTES.md) §2.

**Scale:** HI-Large, 179.7M transactions, full training split, three seeds —
124,992,128 training rows × 32 features, LightGBM, 25.5 min, 30.8 GB peak.
`recall@200` **0.08785**, `ring_recall@200` **0.86876**. The memory ceiling was
the library, not the data: sklearn's `HistGradientBoosting` needs 33.5 GB and
cannot fit in 31; LightGBM needs 14.9 GB.

## What this is not

- **Not a bank model.** 40% of transactions are cross-bank and 9 of the 10
  per-side history features are unobservable to a single institution. This is
  the shape of an **FIU / network** model.
- **Not a novel evaluation concept.** Budget-constrained top-k evaluation is
  standard in information retrieval, screening and fraud operations. An earlier
  framing here presented it as a gap in the literature; that rested on an
  impression from reading rather than a survey, and is withdrawn. See
  [`docs/RELATED_WORK.md`](aml-platform/docs/RELATED_WORK.md).
- **Not a validated alert unit.** `(account, day)` is asserted, not validated,
  and AMLworld has no customer identifier so the unit cannot be varied. One
  transaction also emits *two* account-days, so a 50-account-day budget buys
  **at most** 50 distinct reviews and probably fewer. Where identity and score
  are both recorded — ring transactions that caused an alert — the measured
  factor is **1.624 to 1.950** account-days per transaction. For the full <!-- derived: 1 + 156/250; 1 + 956/1006 -->
  alerted set the bundles record no transaction, so the factor is bounded
  rather than known, and **no transaction-level precision, recall or ceiling is
  derivable**; two earlier attempts to state one are retracted. LIMITATIONS
  §3c.

## Where to go next

| | |
|---|---|
| what may and may not be claimed | [`docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md) |
| what was retracted, and why | [`CHANGELOG.md`](CHANGELOG.md) — every withdrawn claim with the mechanism that produced it and the control that caught it. The count and its denominator are generated into `results_archive/derived/release_facts.json` (`retraction_patterns`, `published_values_checked`) rather than typed here, because a hand-typed base rate is the defect this project exists to catch |
| what is new here and what is not | [`docs/RELATED_WORK.md`](aml-platform/docs/RELATED_WORK.md) |
| current state and open decisions | [`HANDOFF.md`](HANDOFF.md) |
| which run backs which number | [`docs/RESULT_LINEAGE.md`](aml-platform/docs/RESULT_LINEAGE.md) |
| the cloud runbook and its costs | [`docs/RUNBOOK_cloud.md`](aml-platform/docs/RUNBOOK_cloud.md) |

## How this project got things wrong

1. **This benchmark's published test window is not an evaluation set.** Its
   second half is a generator shutdown: within the test window volume falls <!-- historical -->
   **431,695×**, from 3,021,866 transactions to 7, while transaction <!-- derived: 3021866/7 -->
   prevalence rises from 0.0008 to 0.627119. (This read "637,998× ...  <!-- derived: 637998 = a WITHDRAWN ratio this sentence narrates: the whole-dataset max over min, wrongly attributed to the test window. Deliberately not restated as current -->
   prevalence rises to 1.0". That ratio spanned the WHOLE dataset — 4,465,985
   is 2022-09-01, a *training* day, against a cut of 2022-09-10 — and 1.0 is
   the maximum ACCOUNT-DAY prevalence, a different unit. Both operands were
   real artifact values, so the gate passed it: provenance verified, scope did
   not.) A uniformly random ranker scores `precision@50` between
   **0.45392 and 0.49147**, and on three of nineteen days the budget exceeds
   the entire population — there, every ranker scores identically by
   construction.
2. **A null must be computed on the evaluated population, and conditioned on
   the right thing.** Getting that wrong reversed one published conclusion's
   sign, and left a second claim resting on an H0 the data falsifies.
3. **A non-binding day biases a *lift* toward 1 and a *spread* upward.** Same
   defect, opposite directions — it understated this project's headline, and
   inflates any spread statistic whose maximum sits on the affected group.
4. **A metric can be traceable, reproducible and still measure the wrong
   thing.** The per-structure "difficulty" result published here was withdrawn
   after its null was shown to be false — and the replacement was withdrawn
   too, twice, for measuring a different model, a different budget and a
   different ring population. Nothing about laundering structure is claimed
   from this benchmark now; see `paper/RESULTS_typology.md`.
5. **Provenance discipline caught none of these.** Every one was caught by a
   control or by a gate that executes something. Hashes prove what was run,
   never that it measured the right quantity.

Each is a link away in [`aml-platform/paper/`](aml-platform/paper/README.md),
with what may and may not be claimed in
[`docs/LIMITATIONS.md`](aml-platform/docs/LIMITATIONS.md). The corrections
behind them are in [`CHANGELOG.md`](CHANGELOG.md), deliberately not here.

## Glossary

The terms the rest of this page assumes.

| term | meaning |
|---|---|
| **rung** | one of the three AMLworld sizes: HI-Small (5.1M transactions), HI-Medium (31.9M), HI-Large (179.7M). They are **independent generator runs, not nested subsets** |
| **ring** | a labelled laundering pattern from the generator — a group of transactions forming one scheme. Roughly 17 account-days each on HI-Medium |
| **account-day** | the alert unit: one `(account, calendar-day)` pair. What an investigator is assumed to open |
| **alert budget** | how many account-days a team can review per day. Renews daily |
| **recall ceiling** | the highest recall a budget permits, whatever the model does. `sum_d min(positives_that_day, budget) / total_positives` |
| **manifest** | the JSON every stage writes: its config, inputs, code hashes, outputs and their checksums |
| **lineage** | a named run whose manifests back a published number. `results_archive/CANONICAL.json` marks each one canonical, supporting or superseded, and an unlisted lineage is **refused** |
| **estimand** | the quantity a metric is meant to estimate — as opposed to the number it computes. The distinction is this project's main finding |
| **permutation null** | what a metric would read if the thing being tested were shuffled. Here: ring-transaction scores permuted *within a day* |
| **replay bundle** | ~9 MB of per-day top-k rows that recompute a published budget metric with no dataset download |
| **prevalence** | the share of a day's account-days that involve laundering. Runs 0.001926 to 1.0 across the evaluated test split, which is the whole problem <!-- derived: 0.001926 = the minimum daily account-day prevalence in the evaluated window, read off the per-day table in budget_null.json rather than stored as a field --> |
| **`recall_efficiency@k`** | `recall@k` divided by its ceiling — what fraction of the attainable you got |
| **`ring_recall@k`** | the share of laundering *rings* with at least one member alerted. Not `recall` — a ring gets one draw per member-day |
| **lift** | an observed value divided by what a stated null would give. Levels mean little here; lift is the number to read |
| **sign test** | counts how many paired arms moved the same way. On 8 pairs its smallest possible p-value is 0.0078 <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact and cannot be --> |
| **FIU** | Financial Intelligence Unit — a national agency that sees cross-bank flows a single bank cannot |

## Layout

```text
README.md           you are here
HANDOFF.md          current state of the project
CHANGELOG.md        retractions first, because that is what a reader needs
aml-platform/
  src/aml/          ingest · patterns · splits · features · models · eval
  tests/            unit · contract · leakage · parity · repro · drift · cloud
  scripts/          experiment runners, and every gate that is not pytest
  paper/            measured results, with what may and may not be claimed
  docs/             LIMITATIONS · RELATED_WORK · RESULT_LINEAGE · RUNBOOK_cloud
                    ENGINEERING_NOTES · RELEASE_CHECKLIST · SAST_TRIAGE
  docs/archive/     ⚠️ SUPERSEDED and segregated on purpose; excluded from the
                    publication check
  results_archive/  manifests, derived artifacts, and replay_inventory.json.
                    The replay bundles themselves are in the private
                    development archive only -- withheld here, see above
  infra/            Bicep: VM, disks, network, storage, identity
```

## Licence

Code: [MIT](LICENSE). **No raw AMLworld file and no original transaction row is
redistributed here** — AMLworld is CDLA-Sharing-1.0 and must be obtained from
its own source. A clone *does* contain derived row-level records whose
redistribution status is unreviewed.

| | in a clone? | in the image? | may you redistribute it? |
|---|---|---|---|
| **raw source data** — the six AMLworld CSV/TXT files | **no** | no | obtain from Kaggle/IBM under CDLA-Sharing-1.0. Not ours to relicense |
| **derived row-level bundles** (withheld from the public snapshot) — `results_archive/replay/`, **526,355 rows** of day, opaque account code, label, score, rank and ring linkage | **yes** | **yes** | ⚠️ **UNREVIEWED.** The project's position is that these are CDLA *Results*; no lawyer has confirmed it. Do not treat their presence as permission |
| **aggregate metrics and manifests** — `results_archive/gold/`, `derived/` | yes | yes | yes, MIT, as project output |
| **code** — everything under `src/`, `scripts/`, `tests/` | yes | yes | yes, [MIT](LICENSE) |

Full analysis: [`DATA_LICENSE.md`](DATA_LICENSE.md).
