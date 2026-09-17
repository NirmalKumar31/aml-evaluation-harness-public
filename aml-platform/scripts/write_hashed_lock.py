"""Turn a directory of downloaded wheels into a --require-hashes lock.

Used by `make lock-hashes`. Kept as a script rather than a shell one-liner
because it has to FAIL when a wheel is missing or its version disagrees with
requirements.lock: a hashed lock that silently omits a package is worse than no
hashed lock, since `--require-hashes` would then reject the install for a
reason that has nothing to do with the actual problem.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HEADER = """# HASHED lock for the CONTAINER platform: linux/amd64, CPython 3.12.
#
# This is the environment the 179,702,229-row run executed in, identified by
# content rather than by version string. `pip install --require-hashes` refuses
# to install anything whose bytes do not match, which closes the gap between
# "the versions I tested" and "the bytes that ran".
#
# WHY A SEPARATE FILE FROM requirements.lock. Hashes are per artifact, and an
# artifact is per platform. The development machine is arm64 macOS and the
# container is amd64 Linux; one file cannot pin both without listing every
# wheel twice and going stale twice as fast. requirements.lock stays the
# human-readable version pin for local work; this is what the image installs.
#
# Regenerate with: make lock-hashes   (needs network, ~1 minute)
"""


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels", required=True, type=Path)
    ap.add_argument("--lock", default="requirements.lock", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)

    have: dict[str, tuple[str, str]] = {}
    for w in sorted(a.wheels.glob("*.whl")):
        name, version = w.name.split("-")[0], w.name.split("-")[1]
        have[norm(name)] = (version,
                            hashlib.sha256(w.read_bytes()).hexdigest())

    lines, missing = [HEADER], []
    for raw in a.lock.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        name, _, version = raw.partition("==")
        got = have.get(norm(name))
        if got is None:
            missing.append(f"{name}: no wheel downloaded")
        elif got[0] != version:
            missing.append(f"{name}: lock says {version}, wheel is {got[0]}")
        else:
            lines.append(f"{name}=={version} \\\n    --hash=sha256:{got[1]}")

    if missing:
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print(f"{len(missing)} package(s) could not be hashed; not writing "
              f"{a.out}", file=sys.stderr)
        return 1

    a.out.write_text("\n".join(lines) + "\n")
    print(f"{a.out}: {len(lines) - 1} packages pinned by sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
