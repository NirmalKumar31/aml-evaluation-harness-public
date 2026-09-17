"""Pin the raw dataset by content hash, and refuse to run against anything else.

RP-08. The acquisition step downloaded whatever the current Kaggle path served,
with no version and no expected digest. If IBM or Kaggle republishes AMLworld --
a regenerated draw, a corrected file, a different compression -- every number in
this repository silently starts describing a different experiment, and nothing
anywhere errors. "The published results come from HI-Medium" is not a
reproducibility claim unless HI-Medium is identified by something stronger than
a filename.

    python scripts/verify_dataset.py --pin       # record what is on disk now
    python scripts/verify_dataset.py             # check disk against the pin

The pin lives in `results_archive/derived/dataset_pin.json` and is committed.
Hashing 3.3 GB takes about a minute, so it is a release gate and a
`make get-data` follow-up, not something the pipeline does on every stage.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
import time
from pathlib import Path

# THE CONTRACT. Not "whatever the pin happens to contain" -- the six files the
# project says it uses, declared here, in code, where a regeneration cannot
# quietly shorten the list.
#
# It could, and did. `--pin` rebuilt the pin from the files present on the
# development machine, and HI-Large_Trans.csv is 17 GB and has never been on
# that machine: it was hashed once on the cloud VM and hand-carried into the
# pin. A later `--pin` dropped it without a word, after which `--require all`
# read "all" as "all five entries that remain" and reported a complete,
# verified dataset. An incomplete download could have done the same thing.
#
# So the contract is separate from the pin, `--require all` is checked against
# the CONTRACT, and dropping an entry is now an explicit act.
CONTRACT = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
            "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
            "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
FILES = CONTRACT                                   # back-compat for importers


def sha256(p: Path, chunk: int = 1 << 22) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(p, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def scan(data: Path) -> dict:
    out = {}
    for name in CONTRACT:
        f = data / name
        if not f.exists():
            continue
        digest, size = sha256(f)
        out[name] = {"sha256": digest, "bytes": size}
        print(f"  {name:26s} {size:>14,} B  {digest}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", type=Path)
    ap.add_argument("--pin-file", default="results_archive/derived/dataset_pin.json",
                    type=Path)
    ap.add_argument("--pin", action="store_true",
                    help="record the files on disk as the pin, carrying "
                         "forward pinned files that are not on this machine")
    ap.add_argument("--drop-missing", action="store_true",
                    help="do NOT carry forward pinned files absent from disk. "
                         "Use when a pinned file is genuinely wrong, never to "
                         "re-pin on a machine that holds a subset.")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="write a pin that does not cover the whole contract. "
                         "Records `complete: false`; --require all still fails "
                         "against it.")
    ap.add_argument("--require", default=None,
                    help="comma-separated variants that MUST be present and "
                         "match, e.g. --require Small,Medium. Use 'all' for "
                         "every pinned file. Without this the command reports "
                         "on what it finds and a missing file is not an error, "
                         "which is right for a laptop with one rung downloaded "
                         "and WRONG for a release gate.")
    a = ap.parse_args(argv)

    found = scan(a.data)
    if not found:
        print(f"no dataset files under {a.data}/ -- see `make get-data`",
              file=sys.stderr)
        return 2

    if a.pin:
        from aml.manifest import generator_provenance
        # CARRY FORWARD WHAT DISK CANNOT SEE.
        #
        # A file that is pinned but absent locally is not evidence that the pin
        # was wrong; on this project it is the 17 GB rung that only ever
        # existed on the VM. Re-pinning keeps it, marked, unless the operator
        # says otherwise in so many words.
        previous = {}
        if a.pin_file.exists():
            with contextlib.suppress(Exception):
                previous = json.loads(a.pin_file.read_text()).get("files", {})
        carried = sorted(set(previous) - set(found))
        if carried and a.drop_missing:
            print(f"  DROPPING {len(carried)} pinned file(s) not on disk "
                  f"(--drop-missing): {', '.join(carried)}")
            carried = []
        for name in carried:
            entry = dict(previous[name])
            entry.setdefault("carried_from", "a previous pin; not present on "
                                             "this machine at re-pin time")
            found[name] = entry
            print(f"  carried forward {name:26s} {entry['bytes']:>14,} B  "
                  f"{entry['sha256']}")
        absent = [n for n in CONTRACT if n not in found]
        if absent and not a.allow_incomplete:
            print(f"\nrefusing to write a pin missing {len(absent)} of the "
                  f"{len(CONTRACT)} contracted file(s): {', '.join(absent)}\n"
                  f"  the pin is the dataset's identity; a short pin makes an "
                  f"incomplete download verifiable.\n"
                  f"  --allow-incomplete records the shortfall deliberately.",
                  file=sys.stderr)
            return 2
        a.pin_file.parent.mkdir(parents=True, exist_ok=True)
        a.pin_file.write_text(json.dumps({
            **generator_provenance(
                __file__,
                inputs=[a.data / n for n in CONTRACT if (a.data / n).exists()],
                parameters={"data": str(a.data), "contract": CONTRACT,
                            "drop_missing": bool(a.drop_missing),
                            "allow_incomplete": bool(a.allow_incomplete)}),
            "contract": CONTRACT,
            "complete": not absent,
            "pinned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dataset": "IBM AMLworld (Altman et al., NeurIPS 2023 D&B)",
            "licence": "CDLA-Sharing-1.0; not redistributed. See DATA_LICENSE.md",
            "source": "https://www.kaggle.com/datasets/ealtman2019/"
                      "ibm-transactions-for-anti-money-laundering-aml",
            "note": "Kaggle exposes no immutable version id for this dataset, "
                    "so the CONTENT HASH is the version. If a future download "
                    "does not match, it is a different dataset and the "
                    "published numbers do not describe it.",
            "files": found,
        }, indent=1))
        print(f"pinned {len(found)} file(s) -> {a.pin_file}")
        return 0

    if not a.pin_file.exists():
        print(f"no pin at {a.pin_file}; run with --pin to create one",
              file=sys.stderr)
        return 2
    pin = json.loads(a.pin_file.read_text())["files"]

    bad = 0
    for name, got in found.items():
        want = pin.get(name)
        if want is None:
            print(f"  UNPINNED  {name} (present on disk, absent from the pin)")
            bad += 1
        # COMPARE THE IDENTITY FIELDS, NOT THE WHOLE RECORD.
        #
        # `got != want` compared dicts, and a pin entry may carry annotation
        # the fresh hash cannot have: HI-Large_Trans.csv records `hashed_on`
        # and `carried_from` because it is 17 GB and lives only on the cloud
        # VM. So verifying it on that VM -- the one machine where it CAN be
        # verified -- reported MISMATCH while printing an identical sha256 and
        # an identical byte count. A verifier whose failure message disproves
        # its own verdict is worse than no verifier.
        elif (got["sha256"], got["bytes"]) != (want["sha256"], want["bytes"]):
            print(f"  MISMATCH  {name}\n"
                  f"            expected {want['sha256']} ({want['bytes']:,} B)\n"
                  f"            found    {got['sha256']} ({got['bytes']:,} B)")
            bad += 1
    missing = [n for n in pin if n not in found]

    # FAIL CLOSED WHEN ASKED TO. `--require` is what a release gate uses; the
    # bare command is a laptop convenience. The distinction matters because
    # RELEASE_CHECKLIST.md said "sha256 all six files" while the command it
    # named would happily verify one and exit 0.
    required = set()
    if a.require:
        if a.require.strip().lower() == "all":
            # AGAINST THE CONTRACT, NOT THE PIN. `set(pin)` made "all" mean
            # "all of whatever survived the last re-pin", which is how a
            # five-file pin reported a complete six-file dataset.
            required = set(CONTRACT)
        else:
            for v in a.require.split(","):
                v = v.strip()
                required |= {n for n in CONTRACT if n.startswith(f"HI-{v}")}
            if not required:
                print(f"--require {a.require!r} matched no contracted file; "
                      f"the contract is: {', '.join(CONTRACT)}", file=sys.stderr)
                return 2

    # A required file that is not even PINNED cannot be verified, and saying
    # "0 mismatches" about it would be the original defect wearing a new hat.
    unpinned_required = sorted(required - set(pin))
    for n in unpinned_required:
        print(f"  UNPINNED  {n} (required by --require, absent from the pin)")

    absent_required = sorted(required & set(missing))
    for n in absent_required:
        print(f"  MISSING   {n} (required by --require)")
    if missing and not a.require:
        print(f"  not present locally (not an error without --require): "
              f"{', '.join(missing)}")

    print(f"{len(found)} file(s) checked against the pin of {len(pin)}; "
          f"the contract names {len(CONTRACT)}; {bad} mismatch(es); "
          f"{len(absent_required)} required file(s) missing; "
          f"{len(unpinned_required)} required file(s) unpinned")
    return 1 if (bad or absent_required or unpinned_required) else 0


if __name__ == "__main__":
    raise SystemExit(main())
