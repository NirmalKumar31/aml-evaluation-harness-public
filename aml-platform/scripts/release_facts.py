"""Generate the counts that prose keeps getting wrong, and check prose against them.

Test counts, result-set counts, marker counts and manifest counts were
hand-maintained in README, CONTRIBUTING, HANDOFF and RELEASE_CHECKLIST. They
drifted immediately and repeatedly: at one audit snapshot the documents said
257, 270 and 275 tests while the suite had 277, and claimed the 17 skips were
"without Azure extras" when they are data-dependent HI-Small contract tests.

This is the same defect the metric checker exists for, in a different column of
the same table: a number typed by a human and never re-derived. So it gets the
same treatment -- generated from the artifacts, and verified in CI.

    python scripts/release_facts.py            # write the artifact
    python scripts/release_facts.py --check D  # fail if D disagrees with it
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# "283 tests" / "283 pass" / "283 passing".
#
# Word-boundary-anchored on the LEFT too: `34,952 test positives` matched the
# first version, which reported a 952-test disagreement. A checker that cries
# wolf is a checker that gets switched off.
TEST_COUNT = re.compile(r"(?<![\d,.])(\d{2,4})\s+tests?\b(?!\s+positives)")
# SEPARATE, because they are different numbers and one regex mapped both to
# `tests_collected`. HANDOFF.md said "315 pass, 17 skip" and passed the check:
# 315 is what pytest COLLECTED, of which 298 passed and 17 skipped, so the
# sentence was arithmetically impossible and the gate agreed with it. A checker
# that maps two claims onto one field cannot see the one it is not looking at.
PASS_COUNT = re.compile(r"(?<![\d,.])(\d{2,4})\s+pass(?:ing|es|ed)?\b")
# "327 collected", which is the phrasing the documents were told to use --
# and the one the checker could not see. HANDOFF.md sat at 315 while the suite
# collected 327, through two --fix runs, because every pattern here required
# the word "tests" or "pass" and that line has neither. A checker that only
# recognises the phrasings nobody was asked to use is a checker that reports
# zero disagreements about a stale number.
COLLECTED = re.compile(r"(?<![\d,.])(\d{2,4})\s+collected\b")
# "526,355 rows" / "526,355 total rows". The replay inventory appears in a
# LEGAL notice, which is the last place a hand-typed count belongs.
REPLAY_ROWS = re.compile(r"\b(\d{1,3}(?:,\d{3})+)\s+(?:total\s+)?rows\b")
# "216 values are exempted", "529 values checked". Numbers ABOUT the gate,
# which used to be published in prose and gated by nothing.
EXEMPTED = re.compile(r"\b(\d{1,4})\s+values?\s+(?:are\s+)?exempt")
CHECKED_VALUES = re.compile(r"\b(\d{1,4})\s+(?:published\s+)?values?\s+checked")
# Some counts only mean what they mean IN CONTEXT. "210,001 rows" is the
# row-order threshold experiment, not the replay inventory, and matching it
# turned a checker into a crash. A pattern that needs a cue declares one.
CONTEXT = {"replay_rows": ("replay", "bundle", "parquet")}


def _wanted(key: str, line: str) -> bool:
    cues = CONTEXT.get(key)
    return cues is None or any(c in line.lower() for c in cues)


# A LINE THAT NARRATES THE PAST IS NOT A CLAIM ABOUT THE PRESENT.
#
# `--fix` rewrote "the v2 audit found this list claiming 270 tests" to the
# current collection count, round after round -- so the sentence ended up
# saying v2 objected to a number that did not exist when v2 was written. The
# checker could not tell a record from a claim, and the fixer edited history.
#
# Deliberately tight: these are phrases that can only be about a previous
# state. "Currently" and "now" are absent on purpose -- they describe the
# present and their numbers SHOULD be maintained.
HISTORY_CUES = (
    "used to say", "used to read", "used to be", "an earlier version",
    "previous version", "previously said", "previously claimed",
    "the v1 audit", "the v2 audit", "the v3 audit", "the v4 audit",
    "the v5 audit", "the v6 audit", "the v7 audit",
    "until the", "predates", "was wrong", "had been", "this line said",
    "this bullet said", "at one audit snapshot", "no longer says",
)


def _narrates_history(line: str) -> bool:
    low = line.lower()
    return ("<!-- historical -->" in low
            or any(c in low for c in HISTORY_CUES))


SKIP_COUNT = re.compile(r"\b(\d{1,3})\s+skip")
RESULT_SETS = re.compile(r"\b(\d{1,4})\s+result\s+sets\b")


def _line_index(text: str) -> list[int]:
    """Byte offset at which each 1-indexed line begins."""
    starts, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        starts.append(pos)
    return starts


def _line_of(offset: int, starts: list[int]) -> int:
    return bisect.bisect_right(starts, offset)


_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")


def _sentences(s: str):
    """(start, end) of each sentence in `s`.

    A full stop INSIDE a number does not end a sentence. Splitting on every
    `[.!?]` cut "the v2 audit claimed 0.920" in two and left the half carrying
    the figure unexempted, which is the opposite of what the exemption is for.
    Requiring whitespace or end-of-string after the stop also leaves "e.g."
    alone.
    """
    pos = 0
    for m in _SENTENCE_END.finditer(s):
        stop = m.end()
        while stop < len(s) and s[stop] in " \t":
            stop += 1
        if s[pos:stop].strip():
            yield pos, stop
        pos = stop
    if s[pos:].strip():
        yield pos, len(s)


def _history_spans(text: str) -> list[tuple[int, int]]:
    """CHARACTER RANGES whose sentence narrates a past state.

    Four scoping rules, and three of them are corrections.

    1. A FENCED CODE BLOCK IS NEVER EXEMPTED BY ITS NEIGHBOURS. The status
       block in HANDOFF.md holds `363 collected` and, eight lines later, "it
       was 479 for two rounds after it stopped being 479" -- and a
       paragraph-wide rule exempted the whole block, so the live test count sat
       stale under a green gate. A code block is where current facts live.
    2. PROSE IS EXEMPTED BY SENTENCE, not by paragraph. Per-line matching was
       too narrow -- the cue and the number it governs land on different lines
       of one wrapped sentence -- and per-paragraph was too wide, which is what
       produced the false green.
    3. THE UNIT IS THE SENTENCE, AND THE ANSWER IS A CHARACTER RANGE. This
       returned line numbers, so the sentence scoping was thrown away at the
       last step: "The v7 audit was wrong. Current release has 999 tests." put
       both sentences on one line, the line was marked historical, and the
       current count on it was never checked. Two sentences share a line far
       more often than one sentence spans two.
    4. An explicit `<!-- historical -->` marker exempts its own line anywhere,
       including inside a fence, because that is someone stating intent.
    """
    spans: list[tuple[int, int]] = []
    starts = _line_index(text)
    lines = text.splitlines()
    in_fence = False
    para: list[int] = []                  # 0-based indexes of prose lines

    def whole(i: int) -> tuple[int, int]:
        return (starts[i], starts[i] + len(lines[i]))

    def flush() -> None:
        if not para:
            return
        base = starts[para[0]]            # `para` is always contiguous
        joined = "".join(lines[i] + "\n" for i in para)
        for begin, stop in _sentences(joined):
            if any(c in joined[begin:stop].lower() for c in HISTORY_CUES):
                spans.append((base + begin, base + stop))
        para.clear()

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            if "<!-- historical -->" in line:
                spans.append(whole(i))
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith("|"):
            flush()                       # each table row stands alone
            if _narrates_history(line):
                spans.append(whole(i))
            continue
        if "<!-- historical -->" in line:
            spans.append(whole(i))
        para.append(i)
    flush()
    return spans


def _history_lines(text: str) -> set[int]:
    """1-indexed lines touched by a historical span.

    A convenience for reasoning about whole lines. The matcher does NOT use
    it: a line can hold one historical sentence and one current claim, and
    collapsing the spans onto lines exempts both.
    """
    starts = _line_index(text)
    out: set[int] = set()
    for begin, stop in _history_spans(text):
        for n in range(_line_of(begin, starts),
                       _line_of(max(begin, stop - 1), starts) + 1):
            out.add(n)
    return out


def _retraction_count(plat: Path) -> int | None:
    """How many withdrawn claims the registry holds."""
    f = plat / "results_archive/RETRACTED.json"
    if not f.exists():
        return None
    return len(json.loads(f.read_text()).get("retracted", []))


def collect(root: Path, allow_red: bool = False) -> dict:
    plat = root / "aml-platform"
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                       capture_output=True, text=True, cwd=plat)
    n_tests = len([ln for ln in r.stdout.splitlines() if "::" in ln])

    # Skips are only knowable by running; deriving them from markers would be a
    # second implementation of pytest's own logic.
    run = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                         capture_output=True, text=True, cwd=plat)
    tail = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tail)) else None
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", tail)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", tail)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", tail)) else 0

    sys.path.insert(0, str(plat / "scripts"))
    import make_tables
    make_tables.ARCHIVE = plat / "results_archive"
    rows = make_tables.collect(plat / "results_archive")

    # The publication gate's own counters, so prose quoting them is checkable.
    # FROM THE GATE'S OWN INVENTORY. This used to rebuild the list by hand and
    # got a different answer -- fourteen documents against the gate's thirteen
    # -- so the published count described a gate that had not been run over
    # what it claimed. A number about a gate has to come from the gate.
    gate_docs = make_tables.publication_docs(plat.parent)
    gate_counts = {}
    if all(d.exists() for d in gate_docs):
        import contextlib
        import io as _io
        with contextlib.redirect_stdout(_io.StringIO()):
            make_tables.check(rows, gate_docs)
        gate_counts = dict(getattr(make_tables, "LAST_COUNTS", {}))

    # THREE SCOPES, NAMED. One number called "derived markers" counted every
    # Markdown file in the tree including six archived audit reports, while
    # HANDOFF quoted a different figure for "currently" and the publication
    # gate reported a THIRD number that is not markers at all -- it counts
    # exempted numeric TOKENS. Three quantities, one name, and `--check` never
    # validated the field, so all three could drift independently under a green
    # gate. Whatever is quoted in prose now has to say which one it means.
    def _markers(paths):
        return sum(f.read_text(encoding="utf-8", errors="replace")
                   .count("<!-- derived -->") for f in paths)

    # TRACKED FILES ONLY, and this is the second time a count here has been
    # environment-dependent without saying so.
    #
    # `rglob` walks what is on DISK, which locally includes a gitignored
    # `Learning/` corpus and two council transcripts -- 18 Markdown files that
    # do not exist in a clean checkout. The committed artifact said 67 and CI
    # measured 49, and `--verify-artifact` caught it on the first push, which
    # is what that gate is for. The release is the tracked tree; count that.
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "*.md"],
                             capture_output=True, text=True)
    if tracked.returncode == 0:
        all_md = [root / line for line in tracked.stdout.splitlines() if line]
    else:                       # no git: fall back, and the scope says so
        all_md = [f for f in root.rglob("*.md")
                  if not {".git", ".venv", "node_modules"} & set(f.parts)]
    current_md = [f for f in all_md if "archive" not in f.parts]
    markers_all = _markers(all_md)
    markers_current = _markers(current_md)
    manifests = len(list((plat / "results_archive").rglob("manifest.json")))

    # THE REPLAY INVENTORY, GENERATED. `DATA_LICENSE.md` said 446,466 rows, the
    # package README said "roughly 526,000", and the Parquet metadata says
    # 526,355 -- because the first number was totalled by hand from three of
    # the five file kinds. A legal notice has to inventory the data it
    # describes accurately, and a number typed into a notice is a number that
    # will be wrong. Counted from Parquet footers, so it costs nothing.
    replay = plat / "results_archive" / "replay"
    replay_rows, replay_files, replay_bundles = 0, 0, 0
    replay_by_kind: dict[str, int] = {}
    # AN INVENTORY THAT SHIPS WHEN THE DATA DOES NOT.
    #
    # The public snapshot withholds the row-level bundles while their CDLA
    # status is unreviewed, but the licence notice and the README still have to
    # state accurately what the development archive holds. Counting from
    # Parquet footers gives 0 there and would silently rewrite a legal notice
    # to describe nothing. So the counts fall back to a committed aggregate
    # manifest -- bundle names, file names, row counts and hashes, no rows.
    # BESIDE the directory, not inside it: `alert_unit_coupling.json` records
    # the replay directory's content hash as an input, and a file added within
    # it silently changed that identity.
    inv = replay.parent / "replay_inventory.json"
    if not any(replay.glob("*/*.parquet")) and inv.exists():
        man = json.loads(inv.read_text())
        replay_rows = man["rows"]
        replay_files = man["files"]
        replay_bundles = man["bundles"]
        replay_by_kind = dict(man["by_kind"])
    elif replay.is_dir():
        import pyarrow.parquet as pq
        replay_bundles = len([d for d in replay.iterdir() if d.is_dir()])
        for f in sorted(replay.glob("*/*.parquet")):
            n = pq.ParquetFile(f).metadata.num_rows
            replay_rows += n
            replay_files += 1
            replay_by_kind[f.name] = replay_by_kind.get(f.name, 0) + n

    # An internal check, because the two numbers come from two pytest
    # invocations and a mismatch means one of them saw a different tree.
    if (failed or errors) and not allow_red:
        raise SystemExit(
            f"{failed} failed and {errors} errored; release facts are not "
            f"published from a red suite. Pass --allow-red ONLY to break the "
            f"one bootstrap cycle this creates: the provenance test fails "
            f"because this artifact is stale, and this artifact cannot be "
            f"regenerated while that test fails. Never in CI.")
    ran = (passed or 0) + skipped + failed + errors
    if passed is not None and n_tests != ran:
        raise SystemExit(
            f"collected {n_tests} but ran {ran} "
            f"({passed} passed, {skipped} skipped, {failed} failed, "
            f"{errors} errored); the two pytest invocations disagree, so "
            f"neither count is publishable")

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # PROSE QUOTES `tests_collected`, NOT `tests_passed`.
        #
        # The passing count is environment-dependent -- 288 on the development
        # machine, 289 in CI, 278 inside the container -- because data-dependent
        # contract tests skip where their intermediates are absent. A number
        # that differs by where you stand cannot be written in a document.
        # Collection is stable.
        "tests_collected": n_tests, "tests_passed": passed, "tests_skipped": skipped,
        "skip_reason": "data-dependent HI-Small contract tests whose built "
                       "intermediates are absent from a fresh checkout -- NOT "
                       "'without Azure extras', which is what the docs used to say",
        "result_sets": len(rows),
        # Kept under the old name for compatibility, and now defined: EVERY
        # Markdown file in the tree. `derived_markers_current` excludes the
        # archives, which is the number a reader of the live documents wants.
        "derived_markers": markers_all,
        "derived_markers_scope": "every git-TRACKED .md, archives "
                                 "INCLUDED. Untracked and ignored files are "
                                 "excluded: they differ between a working "
                                 "copy and a clean checkout",
        "derived_markers_current": markers_current,
        "derived_markers_current_scope": "the same, with docs/archive and "
                                         "paper/archive excluded",
        "markdown_files": len(all_md),
        "markdown_files_current": len(current_md),
        "manifests_archived": manifests,
        "replay_bundles": replay_bundles,
        "replay_parquet_files": replay_files,
        "replay_rows": replay_rows,
        "replay_rows_by_kind": dict(sorted(replay_by_kind.items())),
        "published_values_checked": gate_counts.get("checked"),
        "published_values_exempted": gate_counts.get("exempted"),
        "published_documents": gate_counts.get("documents"),
        # THE DENOMINATOR, PUBLISHED BESIDE THE NUMERATOR.
        #
        # This project's retractions are loud and its base rate was withheld,
        # so a reader could not tell "unusually rigorous" from "unusually
        # error-prone" -- and a cold reader reported the second. A retraction
        # count means nothing without the number of claims it is drawn from.
        "retraction_patterns": _retraction_count(plat),
        "pytest_ok": run.returncode == 0,
    }


# One table, used by the checker AND the fixer. They used to carry two copies
# of this list, which is exactly how a field gets checked but never repaired.
PATTERNS = (
    (TEST_COUNT, "tests_collected"),
    (COLLECTED, "tests_collected"),
    (REPLAY_ROWS, "replay_rows"),
    (EXEMPTED, "published_values_exempted"),
    (CHECKED_VALUES, "published_values_checked"),
    # NOT `tests_passed` / `tests_skipped`. The docstring above has said for
    # months that prose quotes the COLLECTED count because passing and
    # skipping depend on where you stand -- 390/17 here, 388/19 in a clean
    # clone -- and then this list enforced both in prose anyway. The result
    # was a bootstrap cycle: the count could only be made correct by a run in
    # which the test policing it was already failing. A rule and the list that
    # enforces it have to agree.
    (RESULT_SETS, "result_sets"),
)


def _hits(text: str, facts: dict):
    r"""Every count claim in `text`, MATCHED ACROSS LINE BREAKS.

    This scanned line by line, and Markdown prose is hard-wrapped, so a claim
    whose number and noun landed on different lines was invisible to both the
    checker and the fixer. README said "156 values are\nexempted by an explicit
    marker" while the gate reported 216 and zero disagreements -- a published
    number going stale under a green tick, which is the precise failure this
    script exists to prevent. Reflowing that one sentence would have fixed the
    symptom and left the next wrap to fail the same way.

    `\s` already matches a newline, so scanning the whole document is all it
    takes. What that buys has to be paid for with a block guard: without one,
    a number ending one paragraph and a noun opening the next would join into
    a claim nobody made.
    """
    starts = _line_index(text)
    history = _history_spans(text)
    lines = text.splitlines()
    for rx, key in PATTERNS:
        # A field the committed artifact predates is not a disagreement -- it
        # is a regeneration that has not happened yet. Crashing on it made
        # `--check` unusable exactly when it was needed, which is while adding
        # a field.
        want = facts.get(key)
        if want is None:
            continue
        for m in rx.finditer(text):
            first = _line_of(m.start(), starts)
            last = _line_of(m.end() - 1, starts)
            # A claim is one block of prose. A blank line, a table edge or a
            # fence delimiter inside the match means the two halves belong to
            # different claims.
            if last != first and re.search(r"\n[ \t]*(?:\n|```|\|)", m.group(0)):
                continue
            span = lines[first - 1:last]
            if any("<!-- derived -->" in ln for ln in span):
                continue
            # Overlap with a historical SENTENCE, not with its line.
            if any(b < m.end() and e > m.start() for b, e in history):
                continue
            # The cue for a context-dependent count may sit on either line of a
            # wrapped sentence, so the whole span is what gets searched.
            if not _wanted(key, "\n".join(span)):
                continue
            yield key, want, int(m.group(1).replace(",", "")), first, last, m


def check(facts: dict, docs: list[Path]) -> int:
    bad = 0
    for d in docs:
        if not d.exists():
            print(f"  MISSING DOCUMENT: {d}")
            bad += 1
            continue
        for key, want, got, first, _last, _m in _hits(d.read_text(), facts):
            if got != want:
                print(f"  {d.name}:{first}  {key} says {got}, actual {want}")
                bad += 1
    return bad


def fix(facts: dict, docs: list[Path]) -> int:
    """Rewrite stale counts in place. The counts are generated; the prose is
    not, so this is the join between them."""
    n = 0
    changed: dict[str, int] = {}
    for d in docs:
        if not d.exists():
            continue
        text = d.read_text()
        starts = _line_index(text)
        edits = []
        for _key, want, got, _first, _last, m in _hits(text, facts):
            if got == want:
                continue
            # Preserve the thousands separators the prose uses.
            shown = f"{want:,}" if "," in m.group(1) else str(want)
            # The lines the DIGITS occupy, not the lines the whole claim
            # spans. A wrapped sentence is matched across two lines but its
            # number sits on one of them, and reporting two would be this
            # tool printing a count that is not true.
            edits.append((m.start(1), m.end(1), shown,
                          _line_of(m.start(1), starts),
                          _line_of(m.end(1) - 1, starts)))

        touched: set[int] = set()
        done: list[tuple[int, int]] = []
        # Right to left, so an applied edit cannot move the offsets of the ones
        # still pending. Two patterns can match the same digits (`TEST_COUNT`
        # and `COLLECTED` both feed `tests_collected`); rewriting one span
        # twice would splice on stale offsets, so overlaps are dropped.
        for begin, stop, shown, first, last in sorted(edits, reverse=True):
            if any(begin < b and stop > a for a, b in done):
                continue
            text = text[:begin] + shown + text[stop:]
            done.append((begin, stop))
            touched.update(range(first, last + 1))

        if not touched:
            continue
        d.write_text(text)
        # COUNT LINES CHANGED, NOT SUBSTITUTIONS ATTEMPTED.
        #
        # This added `subn`'s return value, which counts every match the regex
        # rewrote INCLUDING the ones it rewrote to the same text. So a run that
        # changed four lines reported "rewrote 257 count(s)" -- a false number,
        # printed by the tool whose entire job is stopping false numbers.
        n += len(touched)
        changed[d.name] = len(touched)
    if changed:
        for name, count in sorted(changed.items()):
            print(f"  {name}: {count} line(s)")
    return n


# THE COUNT INVENTORY, DEFINED ONCE.
#
# Enumerated in the Makefile and again in ci.yml, which is how the publication
# inventory drifted, and this list had already lost a document: the PACKAGE
# README publishes "526,355 rows" and appears in neither copy, so the replay
# inventory in the text a package index shows could go stale with both gates
# green. It is the most widely published document in the repository and it was
# the one nothing checked.
#
# Not the same list as `make_tables.PUBLICATION_CORE`: that one gates metric
# VALUES against artifacts, this one gates COUNTS against release_facts.json,
# and the two cover different documents on purpose (CONTRIBUTING carries
# counts and no metrics; paper/ carries metrics and no counts).
COUNT_DOCS = (
    "README.md",
    "HANDOFF.md",
    "CONTRIBUTING.md",
    "DATA_LICENSE.md",
    "aml-platform/README.md",
    "aml-platform/DATA_LICENSE.md",
    "aml-platform/docs/RELEASE_CHECKLIST.md",
)


def count_docs(root: Path | None = None) -> list[Path]:
    """Every document whose counts are maintained from release_facts.json."""
    if root is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import make_tables
        root = make_tables.repo_root()
    return [root / p for p in COUNT_DOCS]


# PROPERTIES OF WHERE YOU STAND, not of the tree. The data-dependent contract
# tests skip wherever their intermediates are absent, so pass and skip counts
# differ between laptop, CI and container, and the timestamp differs always.
VOLATILE_FACTS = frozenset({
    "generated_at", "tests_passed", "tests_skipped", "skip_reason",
    "pytest_ok",
})


def drifted(committed: dict, fresh: dict) -> list[tuple[str, object, object]]:
    """Fields where the COMMITTED artifact disagrees with a fresh collection.

    FAIL CLOSED. This was an allowlist of ten field names, so any field added
    afterwards was unchecked by default -- and three were. The publication
    counters (`published_values_checked`, `published_values_exempted`,
    `published_documents`) were added precisely so prose could quote them under
    a gate, documents started quoting them, and an artifact holding 9999 for
    all three passed `--verify-artifact` and printed that it matched. The
    committed facts and the prose could go stale together while the release
    gate stayed green.

    That is the lineage registry's defect in a second place: a default of
    "assume valid" turns an omission into the vulnerability. So the list is
    inverted. Everything `collect()` produces is compared unless it is named
    above, and adding a field now means adding a checked field.
    """
    return [(k, committed.get(k), fresh.get(k)) for k in sorted(fresh)
            if k not in VOLATILE_FACTS and committed.get(k) != fresh.get(k)]


def facts_path(root: Path, out: str) -> Path:
    """The committed artifact, in the repo layout OR the image's.

    `--root` defaults to two levels above this file -- the repository when the
    script sits in `aml-platform/scripts/`, and `/` when the image puts the
    package at `/app`. Every reader then looked under `<root>/aml-platform/`,
    so `--check` inside the container resolved `/aml-platform/...`, found
    nothing and exited 2. The two tests that drive this script through a
    subprocess guarded against that by skipping, which is how a behavioural
    test quietly stops being one: the image ran the suite and proved nothing
    about the tool.

    The last candidate is the package directory next to this script, which is
    what both `_script()` and `_archive_root()` in the test suite already do.
    """
    for cand in (root / "aml-platform" / out, root / out,
                 Path(__file__).resolve().parents[1] / out):
        if cand.exists():
            return cand
    return root / "aml-platform" / out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=Path(__file__).resolve().parents[2], type=Path)
    ap.add_argument("--out",
                    default="results_archive/derived/release_facts.json")
    ap.add_argument("--check", nargs="*", type=Path, default=None)
    ap.add_argument("--gate", action="store_true",
                    help="check COUNT_DOCS. Callers used to enumerate the "
                         "documents themselves, in two places that had already "
                         "lost the package README.")
    ap.add_argument("--allow-red", action="store_true",
                    help="publish facts even if the suite is red. Exists only "
                         "for the bootstrap cycle described above; CI must not "
                         "use it.")
    ap.add_argument("--verify-artifact", action="store_true",
                    help="recollect the facts and fail if the COMMITTED "
                         "artifact disagrees on any environment-independent "
                         "field. Without this, CI regenerates the artifact in "
                         "its own checkout and then checks documents against "
                         "the fresh copy -- so a stale tracked file survives a "
                         "green job, which is how an artifact generated four "
                         "hours and one test earlier stayed in the tree.")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite the counts in --check documents to match the "
                         "facts. Hand-editing them is what made them stale five "
                         "times; this makes it mechanical.")
    a = ap.parse_args(argv)

    if a.verify_artifact:
        path = facts_path(a.root, a.out)
        if not path.exists():
            print(f"no release facts at {path}", file=sys.stderr)
            return 2
        committed = json.loads(path.read_text())
        fresh = collect(a.root, allow_red=a.allow_red)
        drift = drifted(committed, fresh)
        for k, was, now in drift:
            print(f"  {k}: committed {was}, actual {now}")
        if drift:
            print(f"{path.name} is stale in {len(drift)} field(s); "
                  f"regenerate it and commit the result", file=sys.stderr)
            return 1
        n_stable = len([k for k in fresh if k not in VOLATILE_FACTS])
        print(f"{path.name} matches a fresh collection on {n_stable} "
              f"environment-independent field(s)")
        if a.check is None:
            return 0

    if a.check is not None or a.gate:
        path = facts_path(a.root, a.out)
        if not path.exists():
            print(f"no release facts at {path}; generate them first", file=sys.stderr)
            return 2
        docs = list(a.check or [])
        if a.gate:
            docs = count_docs() + docs
        if not docs:
            print("--check requires at least one document, or --gate",
                  file=sys.stderr)
            return 2
        missing = [d for d in docs if not d.exists()]
        if missing:
            for d in missing:
                print(f"  MISSING COUNTED DOCUMENT  {d}", file=sys.stderr)
            return 2
        facts = json.loads(path.read_text())
        if a.fix:
            n = fix(facts, docs)
            print(f"rewrote {n} count(s) to match {path.name}")
        bad = check(facts, docs)
        print(f"release facts as of {facts['generated_at']}: "
              f"{facts['tests_collected']} collected, "
              f"{facts['tests_skipped']} skipped here, "
              f"{facts['result_sets']} result sets; {bad} disagreement(s)")
        return 1 if bad else 0

    # FAIL FAST, and ONLY WHEN GENERATING. The scope guard also runs when the
    # artifact is written, by which point the suite has been run twice -- but
    # `--check`, `--fix` and `--verify-artifact` write no artifact and must not
    # be blocked by a dirty tree. They are how a dirty tree gets cleaned up.
    from aml.manifest import generator_provenance, require_clean_scope
    require_clean_scope(scope=("",))

    facts = collect(a.root, allow_red=a.allow_red)
    facts.update(generator_provenance(
        __file__,
        # THE WIDEST SCOPE IN THE REPOSITORY, because this artifact has the
        # widest dependency. It runs the whole suite, so every test file
        # changes `tests_collected`; it counts `<!-- derived -->` markers in
        # every Markdown file, so every document changes `derived_markers`; and
        # it imports make_tables to count result sets, so the archive and that
        # sibling script change `result_sets`. Nothing narrower than the
        # repository is honest here.
        scope=("",),
        # Repository-RELATIVE. The committed artifact recorded the maintainer's
        # absolute home path in `parameters.root`, which is not a secret and is
        # not portable either.
        parameters={"root": ".", "allow_red": bool(a.allow_red)}))
    out = facts_path(a.root, a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(facts, indent=1))
    print(json.dumps(facts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
