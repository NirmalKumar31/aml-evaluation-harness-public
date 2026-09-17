# Static analysis: what Bandit reports and what was done about it

`bandit -r src/ scripts/ -ll` reports **53** medium-and-above findings — the
combined scope, not `src/` alone, which is what this line said while quoting
the combined total. They are not ignored and they are not all fixed; this is
the triage, and `docs/sast_baseline.json` records each finding's **identity**
so the gate fails on anything new rather than on a change in the total.

## B608 — "possible SQL injection vector through string-based query construction" (47)

Every one is an f-string building a DuckDB statement. What gets interpolated:

| interpolated value | source | assessment |
|---|---|---|
| file and directory paths | the operator's command line | trusted input to an offline research CLI. A path containing an apostrophe **will** break the query — a robustness defect, not a privilege boundary |
| the split cut timestamp | the split manifest, written by this pipeline | trusted |
| memory limit / temp directory | computed, or the operator's flag | trusted |
| feature and column names | `FEATURES`, a module constant | not user input at all |
| sample fraction | validated numerically before use | `_sample_clause` rejects NaN, ≤0 and >1 |

**The one place that took untrusted input has been fixed.**
`features/online.py` built `SELECT hash('{text}')` from a payment format or
currency arriving in a serving request. It is now parameterised
(`params={"v": text}`). That was a genuine injection surface; the remainder are
paths supplied by the person running the command on their own data.

**What is still owed, and is not done:** a central, tested quoting helper for
paths and identifiers, plus tests with quotes and unusual Unicode in directory
names. Until then the honest statement is that a hostile *path* can break a
query in this CLI, and that nothing here parses input from an untrusted party.

## The four low-severity findings

| id | what | assessment |
|---|---|---|
| B311 | `random` used for non-cryptographic purposes | correct use — it seeds an experiment, not a key |
| B404/B603/B607 | `subprocess` invoking `git` | fixed argument vector, no shell, used to read the commit SHA for provenance |

## `scripts/` — brought into scope, and what it added

The scan covered `src/` only. That is half the tree, and the wrong half to
leave out: `scripts/` provisions cloud resources, formats disks, downloads
datasets and generates every published artifact. "No high-severity findings"
over a scope that excludes the code with root on a VM reads stronger than it
is. `scripts/` is now scanned with `src/`, and the count moved from 47 medium
to **53**, with **0 high**. The six:

| id | where | assessment |
|---|---|---|
| B608 ×3 | `analyze_split_inflation.py:74`, `measure_dataset_facts.py:38`, `split_inflation_counterfactual.py:72` | the same triaged class as `src/`: an f-string DuckDB query over a path the operator supplied on their own command line. No untrusted input reaches it |
| B608 | `budget_null.py` — the per-day account-day count | same class: the only interpolations are the operator's CSV path and the column list from `aml.schema.COLUMNS`, a module constant |
| B608 | `window_volume.py` — the volume profile | same class again, and narrower. The only interpolations are the CSV path the operator named and the column list built from `aml.schema.COLUMNS`, which is a module constant. Reusing the project's own schema rather than re-deriving the parse is deliberate — re-deriving it is the pattern that produced three retracted definitions of the alert unit — and it means nothing here is caller-controlled except a local file path |
| B310 | `cost_table.py:69` | `urlopen` against a **literal** `https://prices.azure.com/...` constant with a query string built from fixed filters. The finding is that `urlopen` *can* open `file:` — this call site cannot, because the scheme is not variable |

The three LOW `subprocess` findings in `check_links.py` and `release_facts.py`
are fixed argument vectors invoking `git` and `pytest` with no shell, the same
assessment as the existing B404/B603/B607 row.

## The gate

CI runs a **pinned** `bandit==1.9.4` over `src/` **and** `scripts/`, and fails
on two things:

1. **any HIGH-severity finding**, outright; and
2. **any change to the medium-and-above set** — a new rule, or more findings
   under an existing rule — measured against `docs/sast_baseline.json` by
   `scripts/check_sast.py`.

⚠️ **Until the sixth audit, (2) did not exist.** This section said new findings
fail; the blocking command was `bandit -lll`, which fails on HIGH only, and the
medium run was `--exit-zero` with its output piped to `tail`. A new medium
SQL-construction finding — *the exact class this document is about* — would
have passed the gate that this page describes as catching it. The policy was a
statement of intent that nothing executed.

The baseline is 53 findings across 2 rules, every one of them in the classes
triaged above. Regenerate it with `python scripts/check_sast.py --update`, and
only after the new finding has an entry here. A *decrease* also fails, with a
different message: it means the baseline carries slack that would hide the next
regression.

A frozen baseline was tried first and abandoned: with bandit unpinned, CI
resolved a different version, scored the same code differently (42 medium and
4 high, against 47 medium and 0 high locally) and the baseline stopped matching.
A gate whose verdict depends on which day it runs is not a gate — and
installing an unpinned tool inside a supply-chain gate is the habit that gate
exists to catch.

**If a HIGH appears, it fails the build.** And if any medium-and-above finding
**appears or disappears by identity** — rule, file and a fingerprint of the
flagged statement — the build fails too, with the identity named.

⚠️ This paragraph said "if the medium count moves away from 51", and the figure above said 51 while the enforced baseline held 53 — the document that exists to keep a count honest disagreed with the count. A count was
the wrong thing to watch, and a cross-check said so: fix one f-string query,
introduce another elsewhere, and the total stays 53 while an untriaged finding
of exactly this class has been added. The fingerprint deliberately excludes the
line number, so inserting a line above a finding is not a new finding — that
mistake was made once and CI reported nine phantom defects for it.
