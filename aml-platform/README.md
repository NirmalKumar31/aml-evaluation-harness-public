# aml-evaluation-harness

The Python package. **Start at the repository README on GitHub**
<https://github.com/NirmalKumar31/aml-evaluation-harness> — it
carries the findings, the claim boundaries and the quick start. This file
exists so the package has metadata of its own and so a reader who lands here
from PyPI-style tooling is not stranded.

## What the distributions contain

The wheel ships **`src/aml/` only**, plus `LICENSE` and `DATA_LICENSE.md` in
`dist-info/licenses/`. The sdist adds this README and `pyproject.toml`.
Neither carries `scripts/`, `tests/`, `paper/`, `docs/`, `infra/` or any
`results_archive/` data — a `pip install` gets the library and the two licence
files, and nothing else.

## What is in the repository

Everything below is the **repository** layout, which is what a clone or the
container image gives you. Only the first block is packaged.

```
src/aml/            the pipeline: ingest -> label -> split -> features -> fit -> evaluate
  eval/metrics.py   the metric suite, including the ring-recall permutation null
  splits/           the ring-participant-disjoint temporal split
  io.py             one module that knows local paths from object-store URIs
scripts/            experiment runners and the publication checker
tests/              leakage, parity, reproducibility, storage, contract, regression
paper/              measured results, each with its claim boundary
docs/LIMITATIONS.md every caveat, in one place
infra/              Bicep: VM, network, storage, identity, spill disk
```

## Run it without the dataset

From an installed wheel — the only entry point the package provides:

```bash
aml demo --dest /tmp/demo   # generates a corpus, runs every stage, ~30s
```

From a clone, where the Makefile and the suite exist:

```bash
make setup
make demo          # the same thing, through the repository tooling
make test
```

The demo's numbers are meaningless by construction and it says so. The
published results need the raw IBM AMLworld files, which this project does not
redistribute — obtain them from Kaggle or IBM under CDLA-Sharing-1.0; see
`make get-data`.

⚠️ **The development archive and the container image contain derived
row-level records; the wheel, the sdist and the PUBLIC SNAPSHOT do
not.** `results_archive/replay/` holds
nine bundles — **526,355 rows** of calendar day, opaque account code, label,
model score, rank and ring linkage — which exist so a reader can recompute
every published budget metric without the dataset. They are not packaged, so
installing from an index does not redistribute them. Whether redistributing
them *from the repository or the image* is permitted under CDLA-Sharing-1.0 is
**unreviewed**; each bundle records `licence_status: UNREVIEWED`.
`DATA_LICENSE.md` — in the wheel's `dist-info/licenses/`, at the root of the
sdist, and beside this file in the repository — is the analysis.

## Licence

MIT for the code (`LICENSE`). The dataset is CDLA-Sharing-1.0 and
is **not** included; see `DATA_LICENSE.md`.
