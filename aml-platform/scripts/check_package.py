"""Assert what the wheel and the sdist actually contain.

The package README is what `pyproject.readme` points at, so it becomes the
description a package index shows -- the one document here that reaches a
reader who never sees the repository. It said "this package and the container
image do contain derived row-level records", and listed `scripts/`, `tests/`,
`paper/`, `docs/` and `infra/` under "what is in here". None of that is in
either distribution: the wheel holds `aml/` and its dist-info, the sdist adds
this README and `pyproject.toml`. The claim was false in the direction that
matters, since it asserted redistribution of data whose licence status this
project openly records as UNREVIEWED.

Proofreading does not catch that, and neither does `twine check`, which
validates metadata and never looks inside. This does, on the real artifacts,
in the target that already builds them.

    python scripts/check_package.py dist/*.whl dist/*.tar.gz
"""
from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

# Present in the wheel, or the licence is not being shipped at all.
WHEEL_REQUIRED = (
    "aml/__init__.py",
    "aml/cli.py",
    ".dist-info/licenses/LICENSE",
    ".dist-info/licenses/DATA_LICENSE.md",
)

# Absent from BOTH. `results_archive` is the load-bearing one -- it holds the
# 526,355 replay rows -- and the rest are directories the README used to claim
# were shipped.
FORBIDDEN = ("results_archive", "scripts/", "tests/", "paper/",
             "docs/", "infra/", "data/", ".venv")


def _members(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as z:
            return z.namelist()
    with tarfile.open(path) as t:
        # Strip the leading `name-version/` so the paths read like the wheel's.
        return [n.split("/", 1)[1] for n in t.getnames() if "/" in n]


def check(paths: list[Path]) -> int:
    bad = 0
    for path in paths:
        if not path.exists():
            print(f"  MISSING DISTRIBUTION  {path}", file=sys.stderr)
            bad += 1
            continue
        names = _members(path)
        for banned in FORBIDDEN:
            hit = [n for n in names if banned in n]
            if hit:
                print(f"  {path.name}: contains {banned!r} "
                      f"({len(hit)} member(s), e.g. {hit[0]})", file=sys.stderr)
                bad += 1
        if path.suffix == ".whl":
            for want in WHEEL_REQUIRED:
                if not any(n.endswith(want) or n == want for n in names):
                    print(f"  {path.name}: missing {want}", file=sys.stderr)
                    bad += 1
        print(f"{path.name}: {len(names)} member(s)")
    return bad


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: check_package.py <dist file> [...]", file=sys.stderr)
        return 2
    bad = check([Path(a) for a in args])
    if bad:
        print(f"{bad} packaging contract violation(s); the package README "
              f"describes what is in the distributions", file=sys.stderr)
        return 1
    print("the distributions contain the library and the licences, and no "
          "repository data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
