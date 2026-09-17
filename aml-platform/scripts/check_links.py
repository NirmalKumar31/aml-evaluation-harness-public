"""Every relative link and anchor in every tracked Markdown file must resolve.

A release gate, not a nicety. This repository's documentation carries its own
evidence -- "see paper/RESULTS_hi_large.md section 4" is a citation, and a
citation that 404s is the documentation equivalent of an unsupported number.
Files get renamed; `make_tables.py --check` will not notice.

External (http/https) links are NOT fetched: a network call in CI is a flaky
gate, and a gate that fails for reasons unrelated to the commit gets ignored,
which is worse than not having it. They are counted and listed so the number
is visible.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# [text](target) -- skipping image embeds is deliberate: they are rare here and
# a missing image is not a broken claim.
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def anchors(text: str) -> set[str]:
    """GitHub's slug rules: lowercase, drop anything that is not alphanumeric,
    space or hyphen, then map EACH space to a hyphen.

    Each, not each run. `## 4. Record -- what was measured` slugs to
    `4-record--what-was-measured`: the em dash vanishes and the two spaces that
    surrounded it each become a hyphen. Collapsing runs produces a single
    hyphen and then reports every such heading as a broken anchor, which is a
    checker that cries wolf -- and a gate nobody trusts is a gate nobody keeps.
    """
    out = set()
    for h in HEADING.findall(text):
        s = re.sub(r"[^\w\s-]", "", h.lower().replace("`", ""))
        out.add(re.sub(r"\s", "-", s.strip()))
    return out


def tracked_markdown(root: Path) -> list[Path]:
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "*.md"],
                           capture_output=True, text=True, check=True)
        return [root / line for line in r.stdout.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(root.rglob("*.md"))


def malformed_tables(files: list[Path], root: Path) -> list[str]:
    """Table rows whose cell count disagrees with their header, and rows with
    content after the closing pipe.

    The second case is this project's own `<!-- derived -->` convention: 34
    rows carried the marker AFTER the final `|`, where a parser may count it as
    an extra column. The marker now lives inside the last cell. This keeps it
    there.
    """
    bad = []
    for f in files:
        if not f.exists():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        header_cells = None
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped.startswith("|"):
                header_cells = None
                continue
            if not stripped.endswith("|"):
                bad.append(f"{f.relative_to(root)}:{n}: content after the "
                           f"closing pipe -- may parse as an extra column")
                continue
            cells = len(stripped.split("|")) - 2
            if header_cells is None:
                header_cells = cells
            elif re.fullmatch(r"[\s|:-]+", stripped):
                continue                      # the --- separator row
            elif cells != header_cells:
                bad.append(f"{f.relative_to(root)}:{n}: {cells} cells, "
                           f"header has {header_cells}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    files = tracked_markdown(root)
    broken, external, checked = [], 0, 0
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                external += 1
                continue
            checked += 1
            path_part, _, anchor = target.partition("#")
            if not path_part:                       # same-file anchor
                if anchor and anchor not in anchors(text):
                    broken.append(f"{f.relative_to(root)}: #{anchor}")
                continue
            dest = (f.parent / path_part).resolve()
            if not dest.exists():
                broken.append(f"{f.relative_to(root)}: {target} -> missing")
            elif (anchor and dest.suffix == ".md"
                  and anchor not in anchors(
                      dest.read_text(encoding="utf-8", errors="replace"))):
                broken.append(f"{f.relative_to(root)}: {target} -> no such anchor")

    tables = malformed_tables(files, root)
    print(f"{len(files)} markdown files, {checked} LOCAL links checked, "
          f"{external} external links listed but NOT fetched, "
          f"{len(tables)} malformed table row(s)")
    for b in broken:
        print(f"  BROKEN  {b}")
    for t in tables:
        print(f"  TABLE   {t}")
    if broken or tables:
        print(f"\n{len(broken)} broken link(s), {len(tables)} table defect(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
