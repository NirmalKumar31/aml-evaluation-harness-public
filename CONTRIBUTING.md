# Contributing

This is a personal research project. Issues and pull requests are welcome, and
so is "your number is wrong" — that one especially.

## The one rule that matters

> **If a number is not emitted by code from an artifact, it is not a number.**

Every figure in every document must be traceable to a manifest under
`aml-platform/results_archive/`. `scripts/make_tables.py --check` enforces it
and runs in CI. It exists because the same defect recurred four times, once in
a table cell *back-solved* from its neighbours — which made that table
internally consistent by construction, so no cross-check on it could ever have
failed.

If you need a value that is legitimately computed in prose (a p-value, a ratio
quoted from another document), the marker has to say what it is derived
FROM. Two forms, and each example below must stay on one line, because the
checker reads line by line:

- arithmetic the gate evaluates and matches against this line:
  `<!-- derived: 0.57060/0.49147 -->`
- a named value with a stated reason:
  `<!-- derived: 3.5 = a runtime estimate, not a measured field -->`

A marker carrying neither is rejected. The bare form used to exempt a whole
line unconditionally, which is how one stale lift survived in seven documents.
Run `python scripts/make_tables.py --markers` to see which markers are
load-bearing.

## Getting set up

```bash
cd aml-platform
make setup          # venv + pinned deps
make test           # 422 tests collected; the pass/skip split depends on
                    # which data-dependent intermediates exist locally
                    # contract tests whose built intermediates are
                    # absent from a fresh checkout (NOT Azure extras)
make lint
make demo           # the whole pipeline on a generated corpus, ~30s
```

No dataset download is needed for any of that.

## Before you open a pull request

```bash
make lint
make test
# --gate, never a hand-listed set of documents. This recipe named four of
# the twenty-three, so three PRs in a row could not have caught a stale value
# in any of the other nineteen -- the same duplicate-inventory defect the gate
# flag was introduced to end.
python scripts/make_tables.py --check --gate
python scripts/make_tables.py --markers        # which markers are load-bearing
python scripts/check_links.py ..
```

CI runs these plus ShellCheck, actionlint, a Bicep build, a full-history secret
scan, the storage-abstraction gate, and the test suite inside the built image.

## What a good change looks like

- **A bug fix comes with a test that fails without it.** `tests/repro/` holds
  one test per defect found in an audit; that file is the strongest single
  artifact in this repository. Add to it.
- **Assert on behaviour, not on source text.** A test that greps for the words
  describing a fix passes because the remediation is *described*. There is a
  test in here that was written that way, caught, and rewritten.
- **Comments explain why, not what.** The surrounding code is dense with
  reasons a decision was made and what broke before it. Match that.
- **Changing a published number means rerunning what produced it**, updating
  the document, and re-running `--check`. Do not hand-edit a figure.

## What will be turned down

- Performance improvements to the model, unless they come with the measurement
  showing the improvement is larger than the seed-to-seed spread. On HI-Medium
  that bar is wide: `recall@50` runs 0.02819 to 0.0428 across eight seeds, a
  relative spread of 37.19%. Most proposals do not clear it.
  (The threshold used to be quoted as "~0.0056 SD on `recall@200`" — a metric <!-- derived: 0.0056 = the withdrawn threshold, quoted as the record of what was corrected -->
  the stability sweep does not compute, in the document that tells you every
  number here is checked against an artifact. It was not, because this file
  was outside the gate until now.)
- New metrics without a null or a ceiling.
- Anything that widens a claim past `docs/LIMITATIONS.md`.
