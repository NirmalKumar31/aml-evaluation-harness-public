"""Enforce the Bandit baseline the SAST prose already claims exists.

WHY

    `docs/SAST_TRIAGE.md` and the gates workflow both say that known findings
    are triaged and new findings fail the build. The blocking command was
    `bandit -lll`, which fails on HIGH severity only; the medium-and-above run
    was informational and `--exit-zero`. So a NEW medium SQL-construction
    finding -- the exact class the triage document is about -- would have
    passed silently, and the policy statement was aspirational rather than
    enforced.

    This compares medium-and-above findings against a recorded per-test-id
    baseline. A new rule, or more findings under an existing rule, fails. Fewer
    findings also fails, with a different message: the baseline is now wrong and
    should be lowered deliberately rather than left as slack.

    HIGH severity is still a hard fail on its own, in the workflow.

    python scripts/check_sast.py            # check against the baseline
    python scripts/check_sast.py --update   # after triaging, record the new one
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

BASELINE = Path(__file__).resolve().parents[1] / "docs" / "sast_baseline.json"
TARGETS = ("src", "scripts")


def _flagged_line(result: dict) -> str:
    """Just the flagged statement, normalised.

    Bandit's `code` field carries the surrounding CONTEXT -- typically the line
    before and after, each prefixed with its line number. Fingerprinting the
    whole block made the identity move whenever anything nearby changed: adding
    a helper to `models/train.py` re-fingerprinted every finding in the file,
    and CI reported nine new defects for a change that introduced none.

    So: take the one line whose number matches the finding, drop the number,
    and collapse whitespace. An identity that changes when an unrelated line
    moves is a count with extra steps.
    """
    want = str(result.get("line_number", ""))
    for raw in (result.get("code") or "").splitlines():
        num, _, text = raw.partition("\t" if "\t" in raw else " ")
        if num.strip() == want:
            return " ".join(text.split())
    # No match: fall back to the whole block rather than an empty fingerprint,
    # and say so in the identity so it is visibly weaker.
    return "CONTEXT:" + " ".join((result.get("code") or "").split())


def scan(root: Path) -> dict[str, str]:
    """Stable identities for every medium-and-above finding.

    COUNTS WERE NOT ENOUGH, and an audit said so precisely: with `B608: 50` in
    the baseline, fixing one f-string query and introducing another somewhere
    else leaves the total at 50 and the gate green. The documentation promised
    that a new finding fails; the implementation proved only that the number
    did not move.

    The identity is rule + file + a normalised fingerprint of the flagged code,
    with the line number deliberately excluded -- adding an import above a
    finding shifts every line below it and must not look like a new defect.
    """
    out = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", *[str(root / t) for t in TARGETS],
         "-ll", "-q", "-f", "json"],
        capture_output=True, text=True)
    if not out.stdout.strip():
        raise SystemExit(f"bandit produced no output:\n{out.stderr[-500:]}")

    found = {}
    for r in json.loads(out.stdout)["results"]:
        rel = str(Path(r["filename"]).resolve().relative_to(root))
        fp = hashlib.sha256(_flagged_line(r).encode()).hexdigest()[:12]
        ident = f"{r['test_id']}:{rel}:{fp}"
        # Two identical statements in one file are two findings, so number the
        # duplicates rather than collapsing them.
        n = 1
        while f"{ident}#{n}" in found:
            n += 1
        found[f"{ident}#{n}"] = r["issue_severity"]
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="record the current counts as the baseline. Only "
                         "after each new finding has a triage entry.")
    a = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    found = scan(root)

    if a.update:
        BASELINE.write_text(json.dumps({
            "_comment": "Medium-and-above Bandit findings by stable IDENTITY "
                        "-- rule, path and a fingerprint of the flagged code, "
                        "without the line number. All triaged in "
                        "SAST_TRIAGE.md. scripts/check_sast.py fails on any "
                        "identity that appears or disappears, so fixing one "
                        "finding and adding another no longer nets out. "
                        "Regenerate with --update, and only after triaging.",
            "targets": list(TARGETS),
            "findings": dict(sorted(found.items())),
            "total": len(found),
        }, indent=2) + "\n")
        print(f"baseline updated: {len(found)} finding(s) across "
              f"{len({k.split(':')[0] for k in found})} rule(s)")
        return 0

    if not BASELINE.is_file():
        print(f"no baseline at {BASELINE}; create one with --update",
              file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text())
    want = baseline.get("findings")
    if want is None:
        print("the baseline predates identity tracking; regenerate it with "
              "--update after reviewing docs/SAST_TRIAGE.md", file=sys.stderr)
        return 2

    appeared = sorted(set(found) - set(want))
    vanished = sorted(set(want) - set(found))

    for k in appeared:
        print(f"  NEW        {k}\n             not in the baseline and not "
              f"triaged in docs/SAST_TRIAGE.md")
    for k in vanished:
        print(f"  GONE       {k}\n             fixed or moved. Good -- rerun "
              f"with --update so the slack does not hide the next one.")

    print(f"{len(found)} medium-and-above finding(s) across "
          f"{len({k.split(':')[0] for k in found})} rule(s); "
          f"baseline {len(want)}")
    return 1 if (appeared or vanished) else 0


if __name__ == "__main__":
    raise SystemExit(main())
