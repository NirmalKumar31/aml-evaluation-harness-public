"""Does each published budget metric measure what its name says it measures?

`make_tables.py` answers "did this number come from that artifact?". It cannot
answer "is this number the quantity the sentence claims", and it says so. This
script is the missing half, and it exists because the gap was not theoretical:

    categorical_ablation_medium.json  arms.full.precision@50            = 0.57060
    categorical_ablation_medium.json  arms.full.by_segment.precision@50 = 0.48858

One artifact, one arm, one key name, two alert units -- the first an
account-day, the second a transaction. `segment_metrics` ranked transaction
rows while every published budget metric in this repository goes through
`to_account_days`, so the segmented head null came out at 0.00077 against the
0.00243 `budget_null.py` computes for the same rung and segment. A factor of
3.16 on every lift in a table that `docs/LIMITATIONS.md` published as a
decomposition of an account-day headline, and the publication gate reported
"1269 values checked, 0 findings" because each number did trace to a real
field. `make_tables.UNITS` held the correct unit for `precision@50` the whole
time and referenced it exactly once, in an f-string that prints a column.

Three rules, all of which that defect breaks:

  1. DECLARE. An artifact publishing a budget-shaped key (`...@<k>`, with an
     optional `_head`/`_tail` segment) must carry `alert_unit`. A metric whose
     denominator is unstated cannot be compared to anything.
  2. AGREE. Two artifacts that publish the same quantity for the same rung,
     budget and segment must agree -- and a random-ranker null is the same
     quantity no matter who computed it.
  3. DO NOT COLLIDE. A key that `make_tables.UNITS` binds to one unit must not
     be published by a block declaring another. The project already invented
     the `__txn` suffix for this; the rule makes it mandatory rather than
     remembered.

    python scripts/check_units.py [--archive results_archive]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ANY segment suffix, not a whitelist. This was `_head|_tail`, so a key named
# `precision@50_mid`, `_hi`, `_binding` or `_k50` matched nothing and rules 1
# to 3 never looked at it -- ten of eleven renamings walked straight through
# with `0 unit finding(s)`. A closed list of the segments that happen to exist
# today is not a gate.
BUDGET_KEY = re.compile(
    r"^(?P<base>.+?)@(?P<k>\d+)(?P<seg>_[a-z0-9]+)?(?:__(?P<unit>txn|acctday))?$")
KNOWN_UNITS = {"account-day", "transaction", "ring", "ratio", "day"}
SUFFIX_UNIT = {"txn": "transaction", "acctday": "account-day"}

# The granularities at which an ALERT can exist. `UNITS` records the unit of
# each metric, which for most budget metrics IS the alert unit -- but not for
# all of them: `ring_recall@200` counts RINGS caught by an account-day budget,
# so its denominator is the ring while its alert unit is still the account-day.
# Rule 3 therefore only speaks where UNITS is making a claim about alerting
# granularity; elsewhere `alert_unit` and UNITS describe different things and
# comparing them would be a category error (and a false failure).
ALERTING = {"account-day", "transaction"}

# The rung a file speaks about, when the file does not say so itself.
RUNG_FROM_INPUT = re.compile(r"features_(?P<rung>Small|Medium|Large)")


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def walk(node, path=""):
    """Every (dotted path, key, value) in a nested document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}.{i}")


def declared_unit(doc: dict, path: str) -> str | None:
    """The nearest `alert_unit` at or above `path`, if any."""
    parts = path.split(".") if path else []
    for depth in range(len(parts), -1, -1):
        cur = doc
        ok = True
        for part in parts[:depth]:
            if isinstance(cur, list):
                try:
                    cur = cur[int(part)]
                except (ValueError, IndexError):
                    ok = False
                    break
            elif isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and isinstance(cur, dict) and isinstance(cur.get("alert_unit"), str):
            return cur["alert_unit"]
    return None


def rung_of(doc: dict, name: str) -> str | None:
    """Which rung this artifact speaks about.

    ⛔ THIS REGEXED THE WHOLE `parameters` BLOB, so a note reading "compared
    against features_Large" in a file about HI-Medium returned Large, and a
    file named `smallest_day.json` returned Small. Worse, renaming
    `features_Small` to `Small_features` returned None -- and a None rung is
    SKIPPED, so the original wrong-unit defect passed. Read the two fields
    that actually name the inputs.
    """
    params = doc.get("parameters") or {}
    for key in ("features", "splits"):
        v = params.get(key)
        if isinstance(v, str):
            m = RUNG_FROM_INPUT.search(v) or re.search(
                r"(?:^|[_/])(?P<rung>Small|Medium|Large)(?:$|[_/.])", v)
            if m:
                return m["rung"]
    for src in (json.dumps(params), name):
        m = RUNG_FROM_INPUT.search(src)
        if m:
            return m["rung"]
    for rung in ("Large", "Medium", "Small"):
        if rung.lower() in name.lower():
            return rung
    return None


def numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def rule_declare_and_collide(archive: Path, units_map: dict) -> list[str]:
    """Rules 1 and 3, over every derived artifact."""
    bad = []
    for f in sorted((archive / "derived").glob("*.json")):
        doc = load(f)
        if not isinstance(doc, dict):
            continue
        undeclared = {}
        for path, key, val in walk(doc):
            if not (numeric(val) and BUDGET_KEY.match(str(key))):
                continue
            m = BUDGET_KEY.match(str(key))
            unit = declared_unit(doc, path)
            if unit is None:
                undeclared.setdefault(str(key), path)
                continue
            if unit not in KNOWN_UNITS:
                bad.append(f"{f.name}: alert_unit {unit!r} at {path or '<root>'} "
                           f"is not one of {sorted(KNOWN_UNITS)}")
            canon = units_map.get(str(key))
            # `UNITS` writes account-days as "acct-day"; one vocabulary.
            canon = {"acct-day": "account-day", "txn": "transaction"}.get(canon, canon)
            # AN EXPLICIT SUFFIX OVERRIDES THE BLOCK. `__txn` is the
            # convention this project already invented for exactly this, so a
            # key is allowed to declare a unit its block does not.
            effective = SUFFIX_UNIT.get(m["unit"] or "", unit)
            if canon in ALERTING and canon != effective:
                bad.append(
                    f"{f.name}: {path}.{key} is published as {effective!r} but "
                    f"make_tables.UNITS binds {key!r} to {canon!r} -- rename "
                    f"the key (the project's own convention is a `__txn` "
                    f"suffix) rather than reusing a name at two units")
        if undeclared:
            shown = ", ".join(sorted(undeclared)[:4])
            bad.append(f"{f.name}: publishes budget metrics ({shown}"
                       f"{', ...' if len(undeclared) > 4 else ''}) with no "
                       f"`alert_unit` declared anywhere at or above them")
    return bad


def rule_nulls_agree(archive: Path, tol: float = 5e-5) -> list[str]:
    """Rule 2, for the one quantity two generators both compute.

    A uniformly random ranker's expected precision at a budget depends on the
    population and the budget and on nothing else, so `budget_null.py` and
    any other generator must land in the same place. `budget_null.py` reports
    a bracket because a truncated day bounds the day's size rather than fixing
    it; a point estimate has to fall inside it.
    """
    bad = []
    bn = load(archive / "derived" / "budget_null.json")
    if not isinstance(bn, dict):
        return ["budget_null.json is missing or unreadable, so no "
                "cross-artifact null agreement can be checked"]
    for f in sorted((archive / "derived").glob("*.json")):
        if f.name == "budget_null.json":
            continue
        doc = load(f)
        if not isinstance(doc, dict):
            continue
        rung = rung_of(doc, f.name)
        ref = (bn.get("rungs") or {}).get(rung or "")
        if not isinstance(ref, dict):
            continue
        for path, key, val in walk(doc):
            if not numeric(val):
                continue
            m = BUDGET_KEY.match(str(key))
            if not m or m["base"] not in ("precision_null", "null_precision"):
                continue
            seg, k = m["seg"] or "", m["k"]
            lo = ref.get(f"null_precision_low@{k}{seg}")
            hi = ref.get(f"null_precision_high@{k}{seg}")
            if lo is None or hi is None:
                # ⛔ A SILENT SKIP IS AN ESCAPE HATCH. A null published for a
                # segment the reference does not compute cannot be
                # cross-checked -- and renaming `_head` to `_mid` was
                # therefore enough to carry the original wrong-unit value
                # straight through this rule with `0 unit finding(s)`. Say so
                # instead of passing.
                bad.append(
                    f"{f.name}: {path}.{key} = {val:g} publishes a "
                    f"random-ranker null for a segment budget_null.json does "
                    f"not compute on {rung} (no "
                    f"null_precision_low@{k}{seg}), so nothing can check it. "
                    f"Compute the reference for that segment, or do not "
                    f"publish the null")
                continue
            if not (lo - tol <= val <= hi + tol):
                bad.append(
                    f"{f.name}: {path}.{key} = {val:g} is outside the "
                    f"{rung} random-ranker null [{lo:g}, {hi:g}] that "
                    f"budget_null.json computes for budget {k}"
                    f"{' segment ' + seg.lstrip('_') if seg else ''} -- one "
                    f"of the two is measuring a different population or a "
                    f"different alert unit (ratio "
                    f"{val / ((lo + hi) / 2):.3g}x)")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="results_archive", type=Path)
    a = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from make_tables import UNITS

    findings = rule_declare_and_collide(a.archive, UNITS)
    findings += rule_nulls_agree(a.archive)
    for line in findings:
        print(f"  {line}")

    # AND WHAT WAS ACTUALLY LOOKED AT. "0 unit finding(s)" over an archive
    # this rule barely reaches is a measurement of the corpus, not of the
    # artifacts: rule 3 can only speak for keys that appear in
    # `make_tables.UNITS`, and rule 2 only for artifacts whose rung resolves
    # and whose segment budget_null.json also computes. Printing the
    # denominators stops the green line from implying more than it checked.
    seen = declared = in_units = 0
    rungs = {}
    for f in sorted((a.archive / "derived").glob("*.json")):
        doc = load(f)
        if not isinstance(doc, dict):
            continue
        keys = [(pth, k) for pth, k, v in walk(doc)
                if numeric(v) and BUDGET_KEY.match(str(k))]
        if keys:
            rungs[f.name] = rung_of(doc, f.name)
        for pth, k in keys:
            seen += 1
            declared += declared_unit(doc, pth) is not None
            in_units += str(k) in UNITS
    resolved = sum(1 for v in rungs.values() if v)
    print(f"  coverage: {seen} budget-shaped value(s) in {len(rungs)} "
          f"artifact(s); {declared} declare an alert unit; {in_units} have a "
          f"canonical unit in make_tables.UNITS and so can be cross-checked "
          f"by rule 3; {resolved} of {len(rungs)} artifact(s) resolve to a "
          f"rung and so can be cross-checked by rule 2.")
    print(f"{len(findings)} unit finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
