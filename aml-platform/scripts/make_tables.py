#!/usr/bin/env python
"""Emit every published results table from manifests. Nothing typed by hand.

WHY THIS EXISTS

    The README table written specifically to fix a unit-mixing problem
    contained four numerical errors:

      * recall@50 reported as 0.0473, which is the CEILING. True value 0.04319.
      * recall_ceiling@50 reported as 0.0518, a number in no artifact.
      * an 8-seed ENSEMBLE compared against a SINGLE-FIT logistic.
      * ring_recall@200 from the ensemble in the table, with seed 0's value in
        the callout below it -- two models in one comparison.

    The second is the instructive one. 0.0473 / 0.0518 = 0.9131, and the true
    efficiency is 0.91259 -- so the missing cell had been BACK-SOLVED from
    recall divided by efficiency. That makes internal consistency necessary by
    construction, so no cross-check on that table could ever have failed. A
    typo is a bad coincidence; a back-solve is a self-sealing one.

    All four share one cause: cells transcribed by hand with no provenance. So
    the fix is not proofreading. It is that no number reaches a document except
    through this script, and every row carries the five things needed to
    identify it: RUNG, MODEL, SEED-OR-ENSEMBLE, UNIT, and the artifact it came
    from.

USAGE
    python scripts/make_tables.py --archive results_archive [--check FILE ...]

    Default prints the tables. `--check` re-reads the given documents and exits
    non-zero if any number in them disagrees with the artifacts, so CI can fail
    on a stale published figure rather than waiting for an audit.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# The unit belongs to the metric, permanently. Without this map a reader cannot
# tell that average_precision and precision@50 have different denominators,
# which is the defect the __txn suffix was introduced to fix.
UNITS = {
    "average_precision__txn": "txn",
    "average_precision": "txn",            # pre-rename artifacts
    "roc_auc_footnote_only__txn": "txn",
    "precision@50": "acct-day",
    "recall@50": "acct-day",
    "recall_ceiling@50": "acct-day",
    "recall_efficiency@50": "acct-day",
    "recall@200": "acct-day",
    "ring_recall@200": "ring",
    "ring_recall_null@200": "ring",
    "ring_recall_lift@200": "ratio",
}
ORDER = ["average_precision__txn", "precision@50", "recall@50", "recall_ceiling@50",
         "recall_efficiency@50", "recall@200", "ring_recall@200"]


def _norm(val: str) -> str:
    """Trailing-zero normalisation, ONLY for values carrying a decimal point.

    `val.rstrip("0")` applied to an integer is destructive: 350 became "35",
    100 became "1", 18130 became "1813". On the source side that made an
    honest `350 <- ...#alerts@50_head` binding impossible to state -- the gate
    reported `3 is bound to ..., which holds 350`. On the derived side it was
    worse than useless, because `<!-- derived: 35 = anything at all -->` then
    exempted a prose 350x. `document_tokens` already guarded this with
    `if "." in tok`; the two marker parsers did not.
    """
    return val.rstrip("0").rstrip(".") if "." in val else val


def _operand_forms(tok: str) -> set[str]:
    """The string forms a marker operand may legitimately take in the index.

    ⛔ NO /100 IMAGE. This used to add it, which let the number being CLAIMED
    legitimise the operand claiming it: `_operand_forms("199")` contained
    "1.99", "1.99" is somewhere in a 21,000-value index, so
    `<!-- derived: 199/100 -->` supported a prose 1.99x. The percent
    candidates belong to the PROSE presence test, where "2.571%" and 0.02571
    really are the same claim; an operand is a measured quantity and must be
    found as itself.
    """
    out = {tok, _norm(tok)}
    try:
        f = float(tok)
    except ValueError:
        return out
    for cand in (f"{f:.4f}", f"{f:.6f}"):
        out.add(cand)
        out.add(_norm(cand))
    return out


def _divides_by_power_of_ten(expr: str) -> float | None:
    """The divisor of any `/` in `expr` that evaluates to 10**k, or None.

    Spelling-independent on purpose. The rule was a regex over the literal
    text and an audit walked through it three times in one line: `/ 100.0`,
    `/(50*2)` and `/1e2` are the same divisor as the `/100` it caught.
    """
    import ast

    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            v = _safe_eval(ast.unparse(node.right))
            if v and v > 0:
                k = math.log10(v)
                if abs(k - round(k)) < 1e-12 and round(k) != 0:
                    return v
    return None


def arithmetic_objection(item: str, known: dict) -> str | None:
    """Why this marker arithmetic is not support, or None if it is.

    Arithmetic can be perfectly valid and still prove nothing. Two ways, both
    found by audit against this gate after three rounds of hardening:

    NO-OP. `<!-- derived: 1.99/1 -->` evaluates to 1.99 and therefore
    "accounts for" a prose `1.99x`. Dividing by one was a universal
    exemption -- four fabricated claims, including a stale headline this gate
    exists to prevent, passed with `checked 0 value(s); 7 exempted`. An
    expression whose result is one of its own literals did no work.

    UNBOUND OPERANDS. The operands were never compared to anything, so
    `812.44/1` cited a value present in no artifact. Small integers stay
    exempt because day counts and arities are legitimately literal: the live
    corpus uses 1, 2, 3, 7 and 8, and nothing larger.
    """
    v = _safe_eval(item)
    if v is None:
        return None
    toks = re.findall(r"\d+(?:\.\d+)?", item)
    if any(abs(v - float(t)) <= 1e-12 for t in toks):
        return (f"the arithmetic `{item}` returns one of its own operands, so "
                f"it supports nothing -- dividing by one is not a derivation")
    small = [t for t in toks if "." not in t and int(t) <= 100]
    loose = [t for t in toks
             if t not in small and not (_operand_forms(t) & set(known))]
    if loose:
        return (f"the operand(s) {', '.join(loose)} in `{item}` appear in no "
                f"artifact -- a derivation must start from measured values")
    # ⛔ SMALL INTEGERS ARE A FREE ALPHABET, and exempting them unconditionally
    # made any value expressible as p/q with p,q <= 100 free: `37/2` supported
    # a fabricated 18.5x, `81/5` a fabricated 16.2x. Day counts and arities
    # legitimately ARE literal, so they stay allowed -- but an expression made
    # of nothing but small integers is not checkable against anything, and the
    # gate has to say so instead of blessing it.
    # ⛔ AND SMALL INTEGERS IN QUANTITY ARE A FREE ALPHABET. Allowing any
    # number of them let ONE bound operand reach almost any value:
    # `0.00243*25*75/14` produced a fabricated 0.3254 and `0.00243*79*81` a
    # fabricated 15.55x, both exempted with zero findings. Measured, one bound
    # operand plus unbounded small integers hit 180 of 200 randomly chosen
    # four-decimal values in (0,1) -- which is the entire range this gate
    # exists to protect. Day counts and arities are legitimately literal, and
    # every live marker uses at most ONE of them; more than one is a knob.
    if len(small) > 1:
        return (f"`{item}` uses {len(small)} free small-integer literals "
                f"({', '.join(small)}). One is a day count or an arity; "
                f"several are a dial that reaches any value from one measured "
                f"operand. State the source with "
                f"`<!-- source: V <- path#key -->` instead")
    # A POWER OF TEN IS A UNIT CONVERSION, NOT A DERIVATION, and the regex
    # that used to say so was evaded three ways: `/ 100.0` (the `(?![\d.])`
    # lookahead killed it), `/(50*2)` (a parenthesised product it could not
    # see), and `/1e2`. Evaluate the divisor instead of matching its spelling.
    div = _divides_by_power_of_ten(item)
    if div:
        return (f"`{item}` divides by {div:g}, a power of ten, which rescales "
                f"a count rather than comparing it to anything. A lift divides "
                f"by its null; a share divides by its total. If this is a unit "
                f"change, state the source with "
                f"`<!-- source: V <- path#key -->`")
    if not [t for t in toks if t not in small]:
        return (f"`{item}` is built entirely from small integer literals, so "
                f"nothing in it is bound to a measurement and any value in "
                f"its range could be produced. State the source instead, with "
                f"`<!-- source: V <- path#key -->`, or give the reason with "
                f"`<!-- derived: V = <why> -->`")
    return None


# `$64.32`, `$0.41600/hr`. Captured without the symbol so the value can be
# looked up in the artifacts the same way a bare decimal is.
MONEY = re.compile(r"\$\s?(\d+\.\d{2,5})\b")
# `117.56 resource-hours`, `121.96 h`, `99.99 hours`.
HOURS = re.compile(r"\b(\d+\.\d{1,2})\s*(?:resource-)?h(?:ours?|rs?)?\b")

# ---------------------------------------------------------------------------
# WHAT THE GATE CAN SEE AT ALL.
#
# This is the defect that produced every headline error in this project, and
# it took nine audits to look at. The extractor was `\b0\.\d{3,6}\b` plus
# money and hours -- so it could not see a value of 1 or more, a percentage,
# or an `Nx` lift written with a multiplication sign. Every headline here is
# in exactly those forms: "1.16x-1.26x", "3.05x", "17.6x", "310.3x",
# "637,998x", "47%/53%", "46.10%".
#
# The consequence was not that such claims failed the gate. They were never
# CANDIDATES: appending `ring recall is 91.234% and the lift is 7.4142x
# chance, mean 12.3456, p = 3.21e-07` to a gated document produced
# "checked 0 value(s) ... 0 finding(s)". The counter did not move. So the
# reassuring "checked 565 values, 0 findings" described only the subset the
# regex happened to match, and the stale "1.15x-1.22x" that survived in seven
# documents was never once looked at -- the `<!-- derived -->` marker on those
# lines was not even the reason.
#
# ONE implementation, exported, because a checker and a test that each keep
# their own copy of the rules drift -- which is how the marker-necessity test
# ended up with a narrower regex than the gate it polices.
# ---------------------------------------------------------------------------

# "3.05x", with either an ASCII x or U+00D7. Not `x` as a letter:
# `(?![\w.])` keeps `0.5x_foo` out.
# ONE decimal counts. `310.3x` and `17.6x` are two of the six examples the
# comment above lists as newly visible, and `\d{2,6}` could not see either.
LIFT = re.compile("(?<![\\d.,])(\\d+\\.\\d{1,6})\\s*(?:\u00d7|x)(?![\\w.])")
# `3.2e-07`. A p-value in scientific notation is a published claim too.
SCI = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?[eE][-+]?\d+)(?![\w.])")
# `1,234.56`. Without this the DEC lookbehind matched at the comma and
# silently yielded `234.56` -- not a miss but a DIFFERENT NUMBER, which is
# worse: the gate would have checked a value the document does not contain.
# A DECIMAL part is required. Bare comma-grouped integers are COUNTS, and
# counts are `release_facts.py`'s job -- pulling 200,000 and 179,702,229 in
# here would duplicate that gate and bury this one in noise.
GROUPED = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+\.\d{1,6})(?![\d])")
# "46.10%", "47%". Checked against both the raw value and value/100, because
# an artifact may store either.
PCT = re.compile(r"(?<![\d.])(\d+(?:\.\d{1,4})?)\s*%")
# Any decimal of 1.00 or more. The leading `[1-9]` is not an exclusion of
# small values -- `0.xxx` is the ORIGINAL pattern below and still applies.
# `(?!\d|\.\d)`, NOT `(?![\d.])`. The point of the lookahead is to reject a
# semver (`1.2.3`), and `(?![\d.])` also rejected any value ending a sentence:
# "...is actually 1.624-1.950." hid 1.950 from the gate entirely. A whole
# class of published values -- every one that ends a sentence -- was invisible.
DEC = re.compile(r"(?<![\d.,])([1-9]\d*\.\d{2,6})(?!\d|\.\d)")
BARE = re.compile(r"\b0\.\d{3,6}\b")
# `637,998x`, `669x`. An INTEGER ratio is still a ratio, and the volume ratio
# is one of the most-quoted figures here. Scoped to the multiplication form so
# that bare integers -- budgets, seed counts, row counts -- stay the counts
# gate's job (`release_facts.py`) rather than flooding this one.
LIFT_INT = re.compile("(?<![\\d.,])(\\d[\\d,]*)\\s*(?:\u00d7|x)(?![\\w.])")

# Things shaped like a measurement that are not one. Stripped BEFORE matching
# rather than filtered after, so a token can never be half-recognised.
_NOISE = (
    re.compile(r"<?https?://\S+>?"),                  # arXiv ids, dashboards
    re.compile(r"\b(?:Python|python|v|version)\s*\d+\.\d+(?:\.\d+)*"),
    re.compile(r"\b\d+\.\d+\.\d+\b"),               # semver, §1.2.3
    re.compile(r"`[^`]*@\d[^`]*`"),                    # pinned `tool@0.14.0`
)


# Values COMPUTED in prose -- p-values, ratios between two published
# numbers, percentages -- are legitimately absent from any artifact. The
# line says what each one is derived from and the gate checks the
# arithmetic; see `DERIVED` and `derived_reasons` at module level. The
# old blanket form, `SKIP = "<!-- derived -->"`, exempted the whole line.
# A number quoted as a RECORD of a superseded run, not as a current claim:
# the retraction tables, the before/after comparisons. It must still exist
# in an artifact -- so it cannot be invented -- but it is excused from the
# provenance requirement, because the run that produced it predates the
# provenance fix and back-filling a commit onto it would be a lie.
# Strictly weaker than `derived`, and deliberately a different word.
HISTORICAL = "<!-- historical -->"
# A HISTORICAL MARKER MUST ACTUALLY NARRATE A RETRACTION.
#
# The marker excuses a line from the retraction registry, on the
# understanding that the line is quoting a withdrawn figure as a record.
# Nothing checked that. An audit found it on a line that stated the
# withdrawn attribution as the CURRENT defensible reading -- so the marker
# exempted the claim instead of labelling it. A line claiming to be history
# has to read like history.
RETRACTION_CUES = ("used to", "earlier version", "previously", "until the",
                   "was withdrawn", "is withdrawn", "retracted", "no longer",
                   "this line said", "this bullet said", "had been",
                   "superseded", "was wrong", "stopped", "is gone",
                   "historical", "before the", "old ", "former")
# ---------------------------------------------------------------------------
# A BYPASS WITH A REASON IS A CHECK. A BYPASS WITHOUT ONE IS A HOLE.
#
# `<!-- derived -->` used to switch the gate off for a whole line,
# unconditionally and permanently. Proven by injection: a fabricated 0.654321
# under that marker is accepted in silence, while the same fabrication under
# `<!-- historical -->` is caught. 87 markers carried 203 values that way.
#
# It is also how a stale number survives its own inputs changing: the lift
# `1.15x-1.22x` was marked `derived`, so when the null it divides by was
# recomputed, nothing could notice -- and the same stale figure was then found
# by hand in seven documents.
#
# So the marker now has to say WHAT the value is derived FROM, per value:
#
#   <!-- derived: 1 + 956/1006 -->        an expression; evaluated and matched
#   <!-- derived: 0.57060/0.49147 -->     a lift; recomputed on every run
#   <!-- derived: 1.034 = positives/negatives from the feature diagnostic,
#                 not archived -->        a named value with a stated reason
#
# Items are separated by `;`. An arithmetic item is EVALUATED and excuses any
# token on the line equal to its value. A `<number> = <prose>` item excuses
# that number only. A bare `<!-- derived -->` excuses nothing, so every value
# it used to hide now has to be accounted for individually.
# ---------------------------------------------------------------------------

DERIVED = re.compile(r"<!--\s*derived\s*(?::\s*(?P<body>.*?))?\s*-->")
_ARITH = re.compile(r"^[\d\s.+\-*/()]+$")
_NAMED = re.compile(r"^(?P<val>\d+(?:\.\d+)?)\s*=\s*(?P<why>\S.*)$", re.S)


def _safe_eval(expr: str) -> float | None:
    """Arithmetic only, walked explicitly.

    Deliberately NOT `eval` on a validated AST. That is defensible and bandit
    flags it anyway (B307), and a reader then has to reason about whether the
    whitelist is airtight. Ten lines of recursion has nothing to reason about:
    there is no code path here that can call anything.
    """
    import ast
    import operator

    binop = {ast.Add: operator.add, ast.Sub: operator.sub,
             ast.Mult: operator.mul, ast.Div: operator.truediv,
             ast.Pow: operator.pow}
    unop = {ast.USub: operator.neg, ast.UAdd: operator.pos}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in binop:
            return binop[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in unop:
            return unop[type(node.op)](ev(node.operand))
        raise ValueError("not arithmetic")

    try:
        return float(ev(ast.parse(expr.strip(), mode="eval")))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError,
            OverflowError, RecursionError):
        return None


def derived_reasons(body: str | None) -> tuple[list[float], dict[str, str], list[str]]:
    """(evaluated values, {named value: reason}, unparseable items)."""
    values: list[float] = []
    named: dict[str, str] = {}
    junk: list[str] = []
    # A `;` SEPARATES ITEMS ONLY WHEN WHAT FOLLOWS LOOKS LIKE ONE. Splitting
    # blindly meant a prose reason could not contain a semicolon: the tail was
    # reported as a malformed item while the value stayed exempt, which is the
    # worst of both. Fragments that do not begin a new item are rejoined.
    raw, items = (body or "").split(";"), []
    for frag in raw:
        starts_item = bool(_ARITH.fullmatch(frag.strip())
                           or _NAMED.match(frag.strip()))
        if items and not starts_item:
            items[-1] = items[-1] + ";" + frag
        else:
            items.append(frag)
    for item in items:
        item = item.strip()
        if not item:
            continue
        if _ARITH.fullmatch(item):
            v = _safe_eval(item)
            (values.append(v) if v is not None else junk.append(item))
            continue
        m = _NAMED.match(item)
        if m:
            named[_norm(m["val"])] = m["why"].strip()
        else:
            junk.append(item)
    return values, named, junk


SOURCED = re.compile(r"<!--\s*source:\s*(?P<body>.+?)\s*-->")


def sourced_claims(body: str | None) -> dict:
    """`<value> <- <artifact path>#<json key>` items, one per `;`.

    TOKEN MEMBERSHIP CANNOT BIND A NUMBER TO ITS METRIC, and that is not a
    theoretical weakness. A published `p = 0.0938` -- an exact permutation
    p-value that had since become 0.10952 -- passed this gate because an
    unrelated `recall@50` in another lineage rounds to 0.0938. The number
    existed somewhere, so the checker was satisfied.

    A line may now say where a value actually comes from:

        <!-- source: 0.10952 <- derived/typology_null.json#exposure_vs_detection.p_without_GATHER_SCATTER_exact -->

    and the gate resolves that exact path and key. It is opt-in because
    retrofitting every value would be a week of work; it exists so the claims
    that matter most can be bound, and so the mechanism is there when a
    number is corrected and its neighbours are not.
    """
    out = {}
    for item in (body or "").split(";"):
        item = item.strip()
        if not item or "<-" not in item:
            continue
        val, ref = (x.strip() for x in item.split("<-", 1))
        out[_norm(val)] = ref
    return out


def resolve_source(ref: str, archive: Path) -> float | None:
    """`path/to.json#a.b.c` -> the value at that key, or None.

    THE PATH MUST STAY INSIDE THE ARCHIVE. An absolute path resolved happily,
    so a binding could cite a file that no clone of this repository contains
    and the gate would certify the chain -- a green tick on a provenance
    claim that nobody else can follow. The value still has to exist in the
    archive to pass the membership test, so this was never a way to inject an
    arbitrary number; it was a way to manufacture its pedigree.
    """
    if "#" not in ref:
        return None
    rel, key = ref.split("#", 1)
    rel = rel.strip()
    target = (archive / rel).resolve()
    if Path(rel).is_absolute() or not target.is_relative_to(archive.resolve()):
        return None
    doc = _load(target)
    if doc is None:
        return None
    cur = doc
    for part in key.strip().split("."):
        if isinstance(cur, list):
            try:
                i = int(part)
            except ValueError:
                return None
            # A NEGATIVE INDEX IS NOT A CITATION. `per_day.-1.n_positive`
            # names whichever row happens to be last, so the binding follows
            # the data instead of pinning a claim to it -- append a day and
            # the "cited" value changes with no edit to the prose.
            if i < 0 or i >= len(cur):
                return None
            cur = cur[i]
            continue
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return float(cur) if isinstance(cur, (int, float)) and not isinstance(cur, bool) else None


def derived_accounts_for(tok: str, values: list[float], named: dict) -> bool:
    """Does the marker account for this specific token?"""
    if _norm(tok) in named:
        return True
    try:
        t = float(tok)
    except ValueError:
        return False
    # Tolerance follows the token's own precision: a value written to four
    # decimals is claimed to four decimals, not to fifteen.
    dec = len(tok.split(".")[1]) if "." in tok else 0
    tol = 0.5 * 10 ** -dec + 1e-12
    return any(abs(t - v) <= tol or abs(t - v * 100) <= tol for v in values)


def document_tokens(line: str) -> list[tuple[str, set[str]]]:
    """Every numeric claim on one line, as (token, candidate artifact keys).

    A percentage yields three candidates -- itself, /100 at four and six
    decimals -- because `46.10%` may be stored as 46.1 or as 0.461 and both
    are the same claim.
    """
    for rx in _NOISE:
        line = rx.sub(" ", line)
    # KEYED BY SPAN, not by value. `LIFT` and `DEC` both match "3.05x", and
    # counting it twice would inflate the "checked N value(s)" line the gate
    # reports -- the same coverage-overstatement this extractor exists to end.
    # Two genuinely separate occurrences of one value keep separate spans.
    found: dict[tuple[int, int], tuple[str, set[str]]] = {}

    def add(span, tok: str, pct: bool = False):
        cands = {tok.rstrip("0").rstrip(".") if "." in tok else tok}
        if pct:
            for prec in (4, 6):
                cands.add(f"{float(tok) / 100:.{prec}f}".rstrip("0").rstrip("."))
        found.setdefault(span, (tok, set()))[1].update(cands)

    for m in BARE.finditer(line):
        add(m.span(), m.group(0))
    for rx in (MONEY, HOURS, LIFT, DEC):
        for m in rx.finditer(line):
            add(m.span(1), m.group(1))
    for m in LIFT_INT.finditer(line):
        add(m.span(1), m.group(1).replace(",", ""))
    for m in GROUPED.finditer(line):
        add(m.span(1), m.group(1).replace(",", ""))
    for m in SCI.finditer(line):
        # Normalised to a plain decimal so it can be looked up like any other.
        add(m.span(1), f"{float(m.group(1)):.10f}".rstrip("0").rstrip("."))
    for m in PCT.finditer(line):
        add(m.span(1), m.group(1), pct=True)
    return [found[k] for k in sorted(found)]

MALFORMED: list[str] = []


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        # Skipped for BROWSING, recorded for RELEASE.
        #
        # This used to return None silently, which is right for generating a
        # table from a decade of stage outputs and wrong for a gate: a
        # truncated artifact simply left its numbers unsupported, and if no
        # OTHER artifact happened to contain them the check would fail with a
        # confusing message, while if one did it would pass for the wrong
        # reason. Either way the corrupt file was invisible. `--check` now
        # fails on it by name.
        MALFORMED.append(f"{path}: {type(e).__name__}: {e}")
        return None


def collect(archive: Path) -> list[dict]:
    """Every (rung, model, fit) result found, with its source file."""
    rows = []

    for f in sorted(archive.glob("gold/eval_*/*/*metrics*.json")):
        m = _load(f)
        if not m:
            continue
        rung = f.parts[-3].replace("eval_", "")
        fit = f.parts[-2]                       # seed0..seed7 | baseline | gbdt
        model = "logistic" if fit == "baseline" else "gbdt"
        rows.append({"rung": rung, "model": model,
                     "fit": "1 fit" if fit in ("baseline", "gbdt") else fit,
                     "metrics": m, "source": str(f.relative_to(archive))})

    # Train-stage manifests: HI-Large lives here, because no eval_* stage was
    # run for it. Without this branch every HI-Large figure was unverifiable
    # locally -- the same defect as the retracted version of that file, which
    # was prose with no artifact behind it.
    for f in sorted(archive.glob("gold/*/manifest.json")):
        m = _load(f)
        comp = m.get("component", "").split("[")[0] if m else ""
        # Both stages that produce metrics. `evaluate` matters as much as
        # `train_model`: HI-Large's ring metrics were recomputed from saved
        # scores by the evaluate stage, and without this branch their means
        # were unverifiable -- the same gap that made every HI-Large figure
        # unsupported before the train branch was added.
        if comp not in ("train_model", "evaluate"):
            continue
        name = f.parts[-2]
        rung = "Large" if name.startswith("large_") else "Medium"
        cfg = m.get("config", {})
        seed = cfg.get("seed")
        if comp == "evaluate":
            hit = re.search(r"_s(\d+)$", name)
            seed = int(hit.group(1)) if hit else seed
        # LINEAGE IS PART OF THE GROUP KEY.
        #
        # Per-seed means are derived by grouping (rung, model). Adding a
        # re-fitted HI-Large seed under a NEW lineage put it in the same group
        # as the three older unsorted runs, so the derived mean became a mean
        # ACROSS TWO LINEAGES and every published 3-seed figure stopped being
        # reproducible. The checker caught it, which is the good news; the
        # cause is the same competing-lineage problem the audit raised, showing
        # up inside the tool meant to police it.
        #
        # The lineage is the directory name with its _s<seed> suffix removed:
        # large_eval3_lgbm_s0 -> large_eval3_lgbm.
        lineage = re.sub(r"_s\d+$", "", name)
        rows.append({"rung": rung, "model": cfg.get("model", "?"),
                     "lineage": lineage,
                     "fit": f"seed{seed if seed is not None else '?'}"
                            + ("" if cfg.get("sample", 1.0) >= 1.0
                               else f" sample={cfg['sample']}"),
                     "metrics": m.get("metrics", {}),
                     "source": str(f.relative_to(archive))})

    for f in sorted(archive.glob("gold/stability_*/stability.json")):
        j = _load(f)
        if not j:
            continue
        rung = f.parts[-2].replace("stability_", "")
        for cfg, body in j.items():
            if not isinstance(body, dict) or "ensemble" not in body:
                continue
            n = len(body.get("per_seed", []))
            rows.append({"rung": rung, "model": f"gbdt[{cfg}]",
                         "fit": f"{n}-seed ensemble", "metrics": body["ensemble"],
                         "source": str(f.relative_to(archive))})
    return rows


def table(rows: list[dict]) -> str:
    out = ["| rung | model | fit | metric | unit | value | source |",
           "|---|---|---|---|---|---:|---|"]
    for r in rows:
        for k in ORDER:
            if k not in r["metrics"]:
                continue
            v = r["metrics"][k]
            if not isinstance(v, (int, float)):
                continue
            out.append(f"| {r['rung']} | {r['model']} | {r['fit']} | `{k}` | "
                       f"{UNITS.get(k, '?')} | {v:.5f} | `{r['source']}` |")
    return "\n".join(out)


ARCHIVE = Path('results_archive')


# THE PUBLICATION INVENTORY, DEFINED ONCE.
#
# This list existed three times -- in the Makefile, in ci.yml, and hand-rolled
# a fourth time inside release_facts.py to count what the gate covers -- and
# they had already diverged. The gate checked thirteen documents while the
# counter reported fourteen, because only the counter included the root licence
# notice. The two totals agreed by luck: DATA_LICENSE.md happens to contain no
# value the matcher recognises, and one decimal added to it would have split
# them, with the published figure describing a gate that was never run over it.
#
# A gate and the number describing that gate have to read the same list. The
# licence notice is IN, because the argument for excluding it was that it had
# nothing to check -- which is a fact about today's text, not a rule.
PUBLICATION_CORE = (
    "README.md",
    "HANDOFF.md",
    "CHANGELOG.md",
    "DATA_LICENSE.md",
    # THE PACKAGE README IS PUBLISHED FURTHEST. pyproject points `readme` at
    # it, so it becomes the package-index description -- the one document here
    # that reaches a reader who never sees the repository -- and it was outside
    # every gate.
    "aml-platform/README.md",
    "aml-platform/docs/LIMITATIONS.md",
    "aml-platform/docs/RELATED_WORK.md",
    "aml-platform/docs/RELEASE_CHECKLIST.md",
    "aml-platform/docs/RESULT_LINEAGE.md",
    "aml-platform/docs/RUNBOOK_cloud.md",
    # THE INDEX THAT ROUTES READERS TO THE RESULTS WAS OUTSIDE THE GATE.
    #
    # `paper/README.md` is the table of contents for every results document,
    # and it carried "per-structure detection ... significant on HI-Medium"
    # -- the exact claim the file it links to retracts. The retraction
    # registry could not catch it either, because the registry matches the
    # withdrawn NUMBER and the index restated the claim in words.
    "aml-platform/paper/README.md",
    # The contribution policy publishes a threshold ("~0.0056 SD on
    # recall@200") and tells contributors every number here is checked.
    "CONTRIBUTING.md",
    "SECURITY.md",
    "aml-platform/docs/ENGINEERING_NOTES.md",
    "aml-platform/docs/SAST_TRIAGE.md",
    "aml-platform/infra/README.md",
    "aml-platform/paper/PREREGISTRATION_split_inflation.md",
)

# GLOBBED, not enumerated. A new paper/RESULTS_*.md is a published document
# from the moment it exists; requiring someone to remember to add it to a list
# is how the list goes stale.
PUBLICATION_GLOB = "aml-platform/paper/RESULTS_*.md"


def repo_root() -> Path:
    """The repository root: the tree that holds `aml-platform/`.

    Deliberately NOT the image's `/app`. The publication inventory names
    documents the container does not ship -- HANDOFF.md, CHANGELOG.md and
    `paper/` are not COPYed into it -- so resolving it against /app produced
    eight paths of which six did not exist, and a gate that quietly covers
    less than it names is worse than one that fails. `--gate` runs from a
    checkout; outside one it resolves to paths that do not exist and the
    missing-document check stops it.
    """
    here = Path(__file__).resolve()
    for base in here.parents:
        if (base / "aml-platform" / "README.md").exists():
            return base
    return here.parents[2]


def publication_docs(root: Path | None = None) -> list[Path]:
    """Every document the publication gate covers, resolved against `root`."""
    root = repo_root() if root is None else root
    return ([root / p for p in PUBLICATION_CORE]
            + sorted(root.glob(PUBLICATION_GLOB)))


def _labels(docs: list[Path]) -> dict:
    """Distinguishing names. `d.name` collides -- README.md exists at the root
    AND in the package -- so reporting both as "README.md:27" sends a reader
    to the wrong file."""
    names = [x.name for x in docs]
    return {d: (d.name if names.count(d.name) == 1
                else "/".join(d.parts[-2:])) for d in docs}


def marker_report(rows: list[dict], docs: list[Path]) -> int:
    """For every `<!-- derived -->` line, say whether the marker is needed.

    The migration tool for the reasoned-marker change, and afterwards the way
    to see at a glance which published values are not artifact-backed. Run it
    instead of guessing: 52 of the 87 original markers turned out to sit on
    lines whose values the gate can verify on its own.
    """
    known = _known_values(rows)
    label = _labels(docs)
    removable, needs = [], []
    for d in docs:
        if not d.exists():
            continue
        for n, line in enumerate(d.read_text().splitlines(), 1):
            # A BACKTICKED MENTION IS NOT A USE. CONTRIBUTING.md explains
            # the marker syntax, in code spans; parsing that as a marker made
            # the document that documents the rule fail the rule.
            mk = DERIVED.search(re.sub(r"`[^`]*`", " ", line))
            if not mk:
                continue
            # FROM THE PROSE, like the gate. This read the whole line, so a
            # marker's own reason text supplied tokens the marker was then
            # judged against -- `3.16 = 0.00243/0.00077, ...` reported that
            # the line needed a reason for 0.00077, a number that appears
            # nowhere in its prose. The report and `check()` have to agree
            # about what a claim on a line IS, or one of them is lying.
            toks = document_tokens(re.sub(r"<!--.*?-->", " ", line))
            dvals, dnamed, _ = derived_reasons(mk.group("body"))
            # WITHOUT the marker's own accounting. Asking "is this value
            # supported, counting the marker that exempts it?" makes every
            # named reason self-justifying, and this classed 31 load-bearing
            # markers as removable -- then removing them exposed 30 values the
            # markers were the only thing standing behind.
            unsupported = [t for t, c in toks if not (set(c) & set(known))]
            covered = [t for t in unsupported
                       if derived_accounts_for(t, dvals, dnamed)]
            unsupported = [t for t in unsupported if t not in covered]
            if unsupported:
                needs.append((d, n, unsupported, line))
            elif dvals or dnamed:
                # A MARKER THAT STATES A REASON IS LOAD-BEARING BY DECLARATION.
                # This heuristic only knows about membership -- it cannot see
                # that a value is unprovenanced or on a superseded lineage, and
                # a marker is what exempts those too. It twice told me to
                # delete markers that were the only thing standing behind a
                # published value. If someone wrote down why, respect it; the
                # thing genuinely worth failing on is a marker that says
                # NOTHING, and check() already rejects those.
                # A MARKER CARRYING ARITHMETIC IS NEVER REMOVABLE, even when
                # every value on the line also passes the membership test.
                # Membership is weak -- a two-decimal value matches almost any
                # artifact -- while the expression is recomputed on every run
                # and fails when the value it divides moves. Deleting it to
                # satisfy a "necessity" rule would trade the strong check for
                # the weak one.
                continue
            else:
                removable.append((d, n, line))
    print(f"REMOVABLE -- every value on the line is artifact-backed "
          f"({len(removable)}):")
    for d, n, _ in removable:
        print(f"  {label[d]}:{n}")
    print(f"\nNEEDS A REASON ({len(needs)}):")
    for d, n, u, line in needs:
        print(f"  {label[d]}:{n}  {u}")
        print(f"      {line.strip()[:120]}")
    # BOTH HALVES. This returned `len(needs)` only, so the test that calls it
    # -- `test_derived_markers_are_necessary` -- was green with 67 markers
    # sitting on fully artifact-backed lines, which is exactly the free
    # weakening its own docstring forbids.
    return len(needs) + len(removable)


def _known_values(rows: list[dict]) -> dict[str, set[str]]:
    """Every value any artifact supports -> the artifacts supporting it.

    ONE implementation. `check()` built this inline and the marker
    report needed the same index; two copies of an index is how a
    checker and the tool that repairs it end up disagreeing.
    """

    def walk(o):
        """Every number anywhere in an artifact, at any nesting depth."""
        if isinstance(o, dict):
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            yield o

    # Scan EVERY json in the archive, not just the metric sets: leak-sweep
    # ratios, split counts and dataset statistics are published too, and a
    # checker that only knows about model metrics cries wolf on all of them.
    # value -> the artifacts that support it. A SET OF SOURCES, not a flag:
    # "this number appears somewhere in some JSON" cannot distinguish a figure
    # backed by a provenanced release run from one backed only by a manifest
    # that records code_git_sha "unknown".
    known: dict[str, set] = {}

    def _remember(v, src):
        # Money and hours are published to two decimals; the artifacts hold
        # them at full precision, so both roundings have to be known.
        for prec in (2, 3, 4, 5, 6):
            known.setdefault(f"{v:.{prec}f}".rstrip("0").rstrip("."),
                             set()).add(src)

    for f in ARCHIVE.rglob("*.json"):
        j = _load(f)
        if j is None:
            continue
        src = str(f.relative_to(ARCHIVE))
        for v in walk(j):
            _remember(v, src)

    # MEANS AND RATIOS ARE COMPUTED, NOT EXEMPTED. Every per-seed mean of a
    # published metric is added to the known set, so documents can state it
    # without switching the check off. `recall@200 = 0.0918` was hand-typed in
    # five places with the marker on each -- a number this script can derive.
    import statistics as st
    from collections import defaultdict

    groups = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["fit"].startswith("seed"):
            key = (r["rung"], r["model"], r.get("lineage"))
            for k, v in r["metrics"].items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    groups[key][k].append(v)
    for key, per_metric in groups.items():
        srcs = {r["source"] for r in rows
                if (r["rung"], r["model"], r.get("lineage")) == key}
        for vals in per_metric.values():
            if len(vals) > 1:
                for src in srcs:
                    _remember(st.mean(vals), src)

    return known


def check(rows: list[dict], docs: list[Path]) -> int:
    """Fail if a document states a value no artifact supports.

    Deliberately crude: it looks for 4-5 decimal numbers and asks whether each
    appears in SOME artifact. That cannot catch a right number attached to the
    wrong label, but it does catch a number that exists nowhere -- which is how
    0.0518 got published.
    """
    known = _known_values(rows)

    # CANONICAL vs SUPERSEDED.
    #
    # The token-membership check was green while the README headlined values
    # from `large_eval3_lgbm_*` -- fits made before the training row order was
    # deterministic. A number appearing in SOME provenanced artifact is not the
    # same as a number appearing in the artifact it claims to come from, and
    # the gate could not tell those apart.
    #
    # Unlisted lineages default to canonical, so the registry cannot hide a
    # result by omission -- only by a deliberate entry.
    reg_path = ARCHIVE / "CANONICAL.json"
    reg = _load(reg_path) or {} if reg_path.exists() else {}
    superseded = set(reg.get("superseded", {}))
    canonical = set(reg.get("canonical", {}))
    supporting = set(reg.get("supporting", {}))

    def _lineage_status(src: str) -> str:
        """canonical | supporting | superseded | unlisted | derived.

        UNLISTED IS A FAILURE NOW, and it used to be the default.

        "Unlisted defaults to canonical" existed so the registry could not hide
        a result by omission. A cross-check found the other edge of that: 28
        unlisted lineages, 58 of whose manifests do not meet the
        full-SHA-plus-tree standard, and a NEW unlisted lineage could back a
        published value while bypassing the test that enforces the standard.
        Omission was the hole, not the guard.

        `derived` is for the ten artifacts under `derived/`, whose provenance
        is gated directly and per-artifact rather than by lineage.
        """
        parts = Path(src).parts
        if not parts or parts[0] != "gold":
            return "derived"
        lineage = re.sub(r"_s\d+$", "", parts[1]) if len(parts) > 1 else ""
        for name, group in (("canonical", canonical), ("supporting", supporting),
                            ("superseded", superseded)):
            if lineage in group:
                return name
        return "unlisted"

    def _superseded(src: str) -> bool:
        return _lineage_status(src) == "superseded"

    # Provenance of an artifact: its own commit, or its sibling manifest's.
    # The `{model}_metrics.json` side files carry no provenance of their own --
    # the manifest next to them does.
    prov_cache: dict[str, bool] = {}

    def _provenanced(src: str) -> bool:
        if src in prov_cache:
            return prov_cache[src]
        f = ARCHIVE / src
        j = _load(f)
        j = j if isinstance(j, dict) else {}     # some artifacts are JSON arrays
        sha = j.get("code_git_sha")
        status = j.get("status")
        if sha is None:
            sib = _load(f.parent / "manifest.json")
            sib = sib if isinstance(sib, dict) else {}
            sha, status = sib.get("code_git_sha"), sib.get("status", status)
        # A FULL SHA. This accepted any non-"unknown" string, so a
        # twelve-character abbreviation counted as provenance -- and an
        # abbreviation cannot be resolved in a clone that does not already hold
        # the object, which is the situation of every reader. Five canonical
        # manifests were in exactly that state until an audit found them.
        ok = (bool(sha) and sha != "unknown" and status in (None, "ok")
              and re.fullmatch(r"[0-9a-f]{40}", sha) is not None)
        prov_cache[src] = ok
        return ok

    # RETRACTED VALUES. The provenance checker asks whether a token appears in
    # SOME artifact, and with 101 archived manifests nearly every number does.
    # It has no way to express "this is the OLD answer", so 0.945 sat in five
    # current-facing lines as the HI-Large lift while the canonical lineage
    # said 0.9497, and the gate was green the whole time. This is the part
    # nothing can derive: it has to be written down.
    ret_path = ARCHIVE / "RETRACTED.json"
    retracted = []
    if ret_path.exists():
        for e in (_load(ret_path) or {}).get("retracted", []):
            retracted.append((re.compile(e["pattern"]), e))

    bad = missing = unprovenanced = stale_lineage = revived = unlisted = 0
    seen = exempt = named_exempt = 0
    label = _labels(docs)
    for d in docs:
        if not d.exists():
            # FAIL CLOSED. This used to `continue`, so a typo in the CI
            # invocation silently disabled the gate and still exited 0.
            print(f"  MISSING DOCUMENT: {d}")
            missing += 1
            continue
        for n, line in enumerate(d.read_text().splitlines(), 1):
            # CHECKED BEFORE THE MARKERS, and `<!-- derived -->` does NOT
            # excuse it. A retracted figure recomputed from other retracted
            # figures is still retracted, and `derived` was carrying three of
            # them.
            narrates = (HISTORICAL in line
                        and any(c in line.lower() for c in RETRACTION_CUES))
            if not narrates:
                for rx, entry in retracted:
                    if rx.search(line):
                        if HISTORICAL in line:
                            print(f"  {label[d]}:{n}  MARKED historical but does "
                                  f"not narrate a retraction -- the marker "
                                  f"exempts the claim instead of labelling it")
                        print(f"  {label[d]}:{n}  RETRACTED: {entry['was']} "
                              f"-> now {entry['now']}\n"
                              f"      {entry['why']}\n"
                              f"      {line.strip()[:110]}")
                        revived += 1
            # THREE FAMILIES, not one.
            #
            # The matcher saw `0.xxx` only, so `$64.32` and `117.56 hours` were
            # invisible -- and that is exactly where the next defect landed: a
            # cost snapshot copied into three documents, two of which went stale
            # the moment the meter ticked, under a gate reporting zero
            # disagreements. Money and durations are published claims like any
            # other.
            # FROM THE PROSE, NOT THE WHOLE LINE. The source gate strips
            # comments before its presence test; this one did not, so
            # `<!-- derived: 43.90/1 -->` satisfied its own
            # appears-on-this-line requirement out of the digits inside the
            # comment. The fix for "a claim cannot be its own evidence" had
            # landed in exactly one of the two checks.
            prose_only = re.sub(r"<!--.*?-->", " ", line)
            pairs = document_tokens(prose_only)
            # A BOUND CLAIM IS CHECKED AGAINST ITS OWN SOURCE, not against
            # whether the number happens to exist somewhere in 101 manifests.
            sm = SOURCED.search(line)
            for val, ref in sourced_claims(sm.group("body") if sm else None).items():
                got = resolve_source(ref, ARCHIVE)
                if got is None:
                    print(f"  {label[d]}:{n}  source claim does not resolve: {ref}")
                    bad += 1
                    continue
                dec = len(val.split(".")[1]) if "." in val else 0
                tol = 0.5 * 10 ** -dec + 1e-12
                if abs(got - float(val)) > tol:
                    print(f"  {label[d]}:{n}  {val} is bound to {ref}, which "
                          f"holds {got:.6g}")
                    bad += 1
                    continue
                # AND THE BOUND VALUE MUST BE ON THE LINE. Checking only that
                # the artifact holds it lets the prose drift away from its own
                # citation: reinstating the stale 0.0938 beside a marker still
                # naming 0.10952 passed, because the marker was self-consistent
                # with the artifact and nothing compared either to the text.
                # FROM THE PROSE, NOT FROM THE MARKER. `document_tokens`
                # reads the whole line, so the citation's own digits satisfied
                # the presence test and the check passed while the prose said
                # something else entirely. A claim cannot be its own evidence.
                # A PLAIN NUMERIC SCAN, not the publication extractor.
                # `document_tokens` exists to FIND CLAIMS WORTH CHECKING, so
                # it deliberately ignores bare integers -- which meant a
                # source binding naming one ("350 <- ...#alerts@50_head")
                # could never satisfy its own presence test, and the only
                # reason no shipped binding hit it was that none named an
                # integer. Asking "does this number appear in this sentence"
                # is a different and simpler question.
                shown = [float(t.replace(",", ""))
                         for t in re.findall(r"-?\d[\d,]*(?:\.\d+)?",
                                             prose_only)]
                # A PERCENT FORM IS THE SAME CLAIM. Prose `2.571%` against a
                # stored 0.02571 was a false failure: document_tokens already
                # computes the /100 candidates and the presence test threw
                # them away, so an honest citation had to be written in the
                # artifact's units to pass.
                if not any(abs(f - got) <= tol or abs(f / 100 - got) <= tol
                           or abs(f * 100 - got) <= tol for f in shown):
                    print(f"  {label[d]}:{n}  {val} is bound to {ref} and the "
                          f"artifact agrees, but no value on this line is "
                          f"{val} -- the prose moved away from its citation")
                    bad += 1
            # PER VALUE, not per line. The marker used to `continue` here, so
            # one comment disabled every check on every number beside it.
            # A BACKTICKED MENTION IS NOT A USE. CONTRIBUTING.md explains
            # the marker syntax, in code spans; parsing that as a marker made
            # the document that documents the rule fail the rule.
            mk = DERIVED.search(re.sub(r"`[^`]*`", " ", line))
            dvals, dnamed, djunk = derived_reasons(mk.group("body")) if mk \
                else ([], {}, [])
            for bad_item in djunk:
                print(f"  {label[d]}:{n}  derived marker item is neither "
                      f"arithmetic nor `<value> = <reason>`: {bad_item!r}")
                bad += 1
            # ARITHMETIC THAT DOES NO WORK IS NOT A DERIVATION.
            #
            # `mk.group("body")` is OPTIONAL in `DERIVED`, so a bare
            # `<!-- derived -->` made this raise AttributeError and abandon
            # every remaining document -- 30 lines above the branch that
            # prints a polite finding for exactly that case. Introduced by the
            # commit that added this block, and no test covered it.
            if mk and mk.group("body"):
                for item in mk.group("body").split(";"):
                    item = item.strip()
                    if not _ARITH.fullmatch(item):
                        continue
                    objection = arithmetic_objection(item, known)
                    if objection:
                        print(f"  {label[d]}:{n}  {objection}")
                        bad += 1
            # THE ARITHMETIC IS A CLAIM ABOUT THIS LINE, so check it against
            # the line. Without this the marker was decoration: changing the
            # headline from 1.16x-1.26x to 1.99x-2.26x while leaving the
            # marker at `0.57060/0.49147` produced ZERO findings, because the
            # unaccounted tokens simply fell through to the membership test
            # and two-decimal values pass that almost always. The stale lift
            # this whole mechanism exists to prevent went straight through it.
            if mk and dvals:
                shown = [t for t, _c in pairs]
                for v in dvals:
                    if not any(derived_accounts_for(t, [v], {}) for t in shown):
                        print(f"  {label[d]}:{n}  the derived marker computes "
                              f"{v:.6g}, which appears nowhere on this line -- "
                              f"the value moved and the marker did not, or the "
                              f"marker is wrong")
                        bad += 1
            if mk and not (dvals or dnamed):
                # A bare marker. It no longer excuses anything, so say so once
                # rather than letting every token on the line fail separately.
                print(f"  {label[d]}:{n}  bare `<!-- derived -->` no longer "
                      f"exempts anything -- state what the value is derived "
                      f"from, e.g. `<!-- derived: 0.57060/0.49147 -->`")
                bad += 1
            for tok, cands in pairs:
                if mk and derived_accounts_for(tok, dvals, dnamed):
                    exempt += 1
                    # A NAMED exemption rests on a prose reason no machine
                    # reads. Counted separately so the summary can say how
                    # much of the green tick is human assertion.
                    named_exempt += _norm(tok) in dnamed
                    continue
                seen += 1
                # THE UNION ACROSS CANDIDATE FORMS, not whichever one a set
                # happened to yield first. A percentage has three forms
                # ("46.1", "0.461", ...) and picking one arbitrarily attributed
                # the leak noise floor to three SUPERSEDED HI-Large manifests
                # that merely contain 0.461, while the canonical artifact that
                # actually publishes `placebo_spread_pct: 46.1` was never
                # consulted. A value is supported if ANY of its forms is, and
                # the lineage question must then be asked of every source that
                # supports it.
                srcs = set()
                for c in cands:
                    srcs |= known.get(c, set())
                if not srcs:
                    print(f"  {label[d]}:{n}  {tok}  <- in no artifact")
                    bad += 1
                elif HISTORICAL in line:
                    pass                         # quoted as a record, see above
                elif not any(_provenanced(x) for x in srcs):
                    # Supported, but only by runs that cannot say which commit
                    # produced them. For a release that is not support.
                    print(f"  {label[d]}:{n}  {tok}  <- supported only by "
                          f"artifacts with no provenance: {sorted(srcs)[:3]}")
                    unprovenanced += 1
                elif all(_superseded(x) for x in srcs
                         if _provenanced(x)):
                    print(f"  {label[d]}:{n}  {tok}  <- supported ONLY by a "
                          f"SUPERSEDED lineage: {sorted(srcs)[:3]}")
                    stale_lineage += 1
                elif not any(_lineage_status(x) in
                             ("canonical", "supporting", "derived")
                             for x in srcs if _provenanced(x)):
                    # FAIL CLOSED ON OMISSION. Every lineage that backs a
                    # current value must be named in CANONICAL.json, so adding
                    # one is a decision rather than a silence.
                    print(f"  {label[d]}:{n}  {tok}  <- supported only by "
                          f"lineages that are NOT IN CANONICAL.json: "
                          f"{sorted(srcs)[:3]}. Add them with a status and a "
                          f"reason, or cite a listed lineage")
                    unlisted += 1

    # THE COUNTERS, MACHINE-READABLE.
    #
    # README quoted "156 values are exempted" and the real figure had moved to
    # 216 -- a number about the GATE, published in prose, outside every gate,
    # so nothing could notice. A counter a document quotes has to be a fact
    # something checks.
    globals()["LAST_COUNTS"] = {
        "documents": len(docs), "checked": seen, "exempted": exempt,
        "unsupported": bad, "unprovenanced": unprovenanced,
        "superseded": stale_lineage, "unregistered": unlisted,
        "retracted": revived, "missing": missing,
    }

    # Report what was actually verified. "0 unsupported numbers" asserted a
    # global property from a ~10% sample, which is manufactured confidence.
    print(f"  checked {seen} value(s) across {len(docs)} document(s); "
          f"{exempt} exempted by marker; {bad} unsupported; "
          f"{unprovenanced} without provenance; {stale_lineage} from a "
          f"superseded lineage; {unlisted} from an unregistered lineage; "
          f"{revived} retracted; {missing} missing")
    # AND SAY WHAT THIS CANNOT SEE. A whole table of numbers computed on the
    # wrong alert unit -- transaction instead of account-day, every value
    # inflated 3.2x -- passed this gate cleanly at "1269 values, 0 findings",
    # because each one traced correctly to a real field in a real artifact.
    # Provenance discipline cannot detect a wrong estimand, and a confident
    # green summary that does not say so supplies false assurance at the exact
    # moment scepticism is called for.
    print("  NOT checked here: that a value measures what its sentence says "
          "it measures (unit/estimand -- see check_units.py), that a named "
          f"marker's stated reason is true ({named_exempt} named exemption(s) "
          "rest on prose alone), or that a comparison has the power to "
          "support the word it is used with.")
    return bad + missing + unprovenanced + stale_lineage + revived + unlisted


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="results_archive", type=Path)
    ap.add_argument("--check", nargs="*", type=Path, default=None)
    ap.add_argument("--gate", action="store_true",
                    help="check the publication inventory (PUBLICATION_CORE "
                         "plus paper/RESULTS_*.md). Callers used to enumerate "
                         "the documents themselves, in three places that "
                         "disagreed.")
    ap.add_argument("--root", default=None, type=Path,
                    help="repository root for --gate; defaults to the tree "
                         "this script lives in.")
    ap.add_argument("--markers", action="store_true",
                    help="report which `<!-- derived -->` markers are needed "
                         "and which sit on values the gate can verify itself.")
    a = ap.parse_args(argv)

    rows = collect(a.archive)
    if not rows:
        print(f"no artifacts under {a.archive}", file=sys.stderr)
        return 2

    globals()['ARCHIVE'] = a.archive
    if a.markers:
        return 0 if marker_report(rows, publication_docs(a.root)) == 0 else 1
    if a.check is not None or a.gate:
        docs = list(a.check or [])
        if a.gate:
            docs = publication_docs(a.root) + docs
        if not docs:
            print("--check requires at least one document, or --gate",
                  file=sys.stderr)
            return 2
        missing = [d for d in docs if not d.exists()]
        if missing:
            # A gate that silently covers fewer documents than it names is
            # worse than one that fails.
            for d in missing:
                print(f"  MISSING PUBLISHED DOCUMENT  {d}", file=sys.stderr)
            return 2
        bad = check(rows, docs)
        # A release gate may not pass over an artifact it could not read.
        for entry in MALFORMED:
            print(f"  MALFORMED ARTIFACT  {entry}", file=sys.stderr)
        print(f"{len(rows)} result sets; {bad} finding(s); "
              f"{len(MALFORMED)} malformed artifact(s)")
        return 1 if (bad or MALFORMED) else 0

    print(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
