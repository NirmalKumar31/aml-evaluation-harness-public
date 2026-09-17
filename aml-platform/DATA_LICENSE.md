# Data terms and attribution

**No raw AMLworld CSV, and no original transaction row, is included or
redistributed in this repository.** `aml-platform/data/` is gitignored.

**A clone does, however, contain derived ROW-LEVEL records.** The nine replay
bundles under `aml-platform/results_archive/replay/` hold **526,355 rows**
across 45 Parquet files: top-ranked account-days with an opaque account code, a
calendar day, a label, a model score and a rank, plus ring membership, ring
endpoints, ring transactions and per-day positive counts. No amounts, no
counterparties, no timestamps finer than the day, and no identifier that
resolves outside its own bundle. ⚠️ **The public snapshot does not redistribute them.** While the CDLA determination is outstanding the row-level Parquet files are withheld; `results_archive/replay_inventory.json` records exactly what they are (bundle names, file names, row counts, sha256) and `scripts/make_replay_bundle.py` regenerates them from AMLworld obtained at source. Tests that need them SKIP, explicitly.

> **Format change, not yet in the archive.** `make_replay_bundle.py` now also records `argmax_txn_id`, a positional index naming which transaction supplied each account-day's score. It identifies nothing outside the bundle and exists so the number of distinct transactions a budget covers can be counted exactly rather than approximated by score ties. **No bundle currently in this repository carries it**; the columns listed above are what ships today.
> ⚠️ **That count was 446,466 until the seventh audit.** It had been totalled
> by hand from three of the five file kinds, omitting ring endpoints and
> per-day positives. A legal notice has to inventory the data it describes, so
> it is counted from the Parquet footers now and published in
> `results_archive/derived/release_facts.json` as `replay_rows`, with
> `release_facts.py --check` failing on any document that disagrees. <!-- historical -->

> ⚠️ **This paragraph used to read "a clone contains code, tests and result
> manifests only", which was not true** — the same file inventories those
> bundles four sections further down. Whether they are CDLA **Results** or a
> redistribution of **Data** is the unresolved question below, and an opening
> sentence that answered it by omission made the rest of the analysis harder
> to find. Every bundle now carries `licence_status: UNREVIEWED` in its own
> metadata.

## The dataset

Experiments run against IBM's **AMLworld** synthetic anti-money-laundering
dataset, published by IBM under **CDLA-Sharing-1.0**:

- Kaggle: <https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>
- IBM: <https://github.com/IBM/AML-Data>

Obtain it from its own source. `make get-data` prints the instructions.

## Files used

| file | size | rows |
|---|---|---|
| `HI-Medium_Trans.csv` | 2.82 GB | 31,898,238 |
| `HI-Large_Trans.csv` | 15.9 GB | 179,702,229 |
| `HI-Small_Trans.csv` | 0.44 GB | 5,078,345 |
| `HI-*_Patterns.txt` | — | laundering-attempt blocks |

**The dataset is pinned by content.** Kaggle exposes no immutable version id,
so the SHA-256 of each file *is* the version. All six are recorded in
`aml-platform/results_archive/derived/dataset_pin.json` and checked by
`make verify-data`. An independent re-download of `HI-Medium_Trans.csv` on a
different machine reproduced its pinned hash exactly.

*(An earlier version of this section said the files were "not pinned and not
checksummed". That was true when written and stale by the time it was read.)*

## What this repository publishes — precisely

Two kinds of thing, and the second one is **not** aggregate-only.

**1. Metrics and manifests.** Scalar metrics, run configuration, code and data
hashes, row counts. Aggregate by construction.

**2. Replay bundles** (`aml-platform/results_archive/replay/`). These are
**row-level derived records**, and an earlier version of this file described
them incorrectly as "aggregate counts… no account identifiers, no
reconstructable subset". What they actually contain, per bundle:

| file | rows | columns |
|---|---|---|
| `account_days_topk.parquet` | ≤1000 per day, plus every ring-member account-day | `day`, `acct`, `score`, `other_max`, `y`, `rank` |
| `per_day_positives.parquet` | one per day | `day`, `positive_account_days` |
| `ring_membership.parquet` | one per (account-day, ring) | `day`, `acct`, `ring_id` |
| `ring_endpoints.parquet` | two per ring transaction | `day`, `acct`, `ring_id`, `rt` |
| `ring_transactions.parquet` | one per ring transaction | `rt`, `day`, `score` |

So a bundle **does** contain per-account-day rows carrying a **label** (`y`), a
**calendar day**, a **pseudonymous account code**, and ring membership.

What it does **not** contain: amounts, currencies, banks, counterparties,
payment formats, timestamps finer than the calendar day, the original account
numbers, or any row outside the per-day top-1000 and the ring members. The
`acct` values are dense integers assigned at load time by `row_number()`; they
do not correspond to anything outside the bundle and are not stable between
bundles. The underlying dataset is **synthetic** — no real person, account or
transaction exists in it.

### The licence question, stated rather than pre-empted

CDLA-Sharing-1.0 distinguishes **Results** from **Data** and **Enhanced Data**,
and permits publishing Results while attaching conditions to publishing Data.
Whether these bundles are Results or a de-minimis-exceeding portion of Data is a
legal judgement. **This file does not make it, and no longer makes the
categorical factual statements that would have pre-empted it.**

If you intend to redistribute them or anything like them: read
<https://cdla.dev/sharing-1-0/> and take your own advice. The bundles are
published here under the assessment that rank-selected, feature-stripped,
pseudonymised derived records from a synthetic dataset are Results — an
assessment that has **not** been reviewed by a lawyer, which is exactly why it
is written down.

### Attribution

IBM AMLworld, © IBM, licensed under CDLA-Sharing-1.0. Altman, Blanuša, von
Niederhäusern, Egressy, Anghel and Atasu, *Realistic Synthetic Financial
Transactions for Anti-Money Laundering Models*, NeurIPS 2023 Datasets and
Benchmarks. <https://arxiv.org/abs/2306.16424>. Files here are derived, not
copies; nothing in `aml-platform/data/` is redistributed.

## Citing

Cite IBM's dataset per the terms at the links above. This repository is MIT
(see `LICENSE`) and may be cited by URL and commit SHA.
