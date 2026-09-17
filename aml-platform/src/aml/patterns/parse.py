"""
parse_patterns: *_Patterns.txt -> three tables (rings, ring_txns, ring_accounts).

The file is the answer key. Format:

    BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
    2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,...,ACH,1
    2022/09/01 04:33,021174,800737690,020,80020C5B0,8630.40,Euro,...,ACH,1
    END LAUNDERING ATTEMPT - FAN-OUT

One BEGIN..END block = one laundering ring, with its typology named on the
header line and the generator's parameters in the free-text qualifier after
the colon. Transaction lines use the same 11 columns as Trans.csv, no header.
"""
import re
import sys

import pandas as pd

from aml import io, schema
from aml.manifest import Run, cached_or_none, sha256_file

BEGIN_RE = re.compile(r"^BEGIN LAUNDERING ATTEMPT\s*-\s*([A-Z\-]+)\s*:?\s*(.*)$")
END_PREFIX = "END LAUNDERING ATTEMPT"

# The 8 typologies IBM's generator emits. Anything else is a parse failure.
KNOWN_TYPOLOGIES = {
    "FAN-OUT", "FAN-IN", "CYCLE", "BIPARTITE",
    "STACK", "SCATTER-GATHER", "GATHER-SCATTER", "RANDOM",
}


class PatternParseError(Exception):
    """Raised on malformed pattern blocks. Never caught."""


def iter_blocks(path):
    """Yield (typology, subtitle, [raw_line_fields]) per BEGIN..END block."""
    typ = subtitle = None
    rows = []
    open_at = None
    with io.open_text(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            m = BEGIN_RE.match(line)
            if m:
                if typ is not None:
                    raise PatternParseError(f"nested BEGIN at line {lineno} (opened at {open_at})")
                typ, subtitle, rows, open_at = m.group(1).strip(), m.group(2).strip(), [], lineno
                if typ not in KNOWN_TYPOLOGIES:
                    raise PatternParseError(f"unknown typology {typ!r} at line {lineno}")
                continue
            if line.startswith(END_PREFIX):
                if typ is None:
                    raise PatternParseError(f"END without BEGIN at line {lineno}")
                if not rows:
                    raise PatternParseError(f"empty ring block closed at line {lineno}")
                yield typ, subtitle, rows
                typ = subtitle = open_at = None
                rows = []
                continue
            if typ is not None and line.strip():
                fields = line.split(",")
                if len(fields) != len(schema.COLUMNS):
                    raise PatternParseError(
                        f"line {lineno}: expected {len(schema.COLUMNS)} fields, got {len(fields)}"
                    )
                rows.append(fields)
    if typ is not None:
        raise PatternParseError(f"unterminated block opened at line {open_at}")


def parse(src: str, dest: str, manifest_dir: str | None = None, force: bool = False):
    src, dest = str(src), str(dest)
    cfg = {"src": src, "dest": dest, "parser_version": "1.1.0"}

    key, hit = cached_or_none("parse_patterns", cfg, [src], (manifest_dir or dest),
                             modules=(sys.modules[__name__], schema), force=force)
    if hit is not None:
        return hit

    with Run("parse_patterns", cfg, manifest_dir or dest, key=key) as run:
        run.record(input_sha256=sha256_file(src))

        txn_recs, ring_recs, acct_recs = [], [], []
        for ring_id, (typ, subtitle, rows) in enumerate(iter_blocks(src)):
            accounts = set()
            for r in rows:
                sender_id = f"{r[1]}_{r[2]}"
                receiver_id = f"{r[3]}_{r[4]}"
                accounts.update((sender_id, receiver_id))
                txn_recs.append((
                    ring_id, typ, r[0], sender_id, receiver_id,
                    float(r[7]), float(r[5]), r[9], r[8], r[6],
                ))
            ring_recs.append((ring_id, typ, subtitle, len(rows), len(accounts)))
            acct_recs.extend((ring_id, a) for a in sorted(accounts))

        if not ring_recs:
            raise PatternParseError(f"no laundering rings found in {src}")

        ring_txns = pd.DataFrame(txn_recs, columns=[
            "ring_id", "typology", "event_time", "sender_id", "receiver_id",
            "amount_paid", "amount_received", "payment_format",
            "payment_currency", "receiving_currency"])
        ring_txns["event_time"] = pd.to_datetime(
            ring_txns.event_time, format=schema.TIMESTAMP_FORMAT)

        # Ring timing is derived from its transactions, not declared in the file.
        span = ring_txns.groupby("ring_id").event_time.agg(["min", "max"])
        rings = pd.DataFrame(ring_recs, columns=[
            "ring_id", "typology", "subtitle", "n_txns", "n_accounts"]).join(span, on="ring_id")
        rings = rings.rename(columns={"min": "start_time", "max": "end_time"})
        rings["duration_days"] = (
            (rings.end_time - rings.start_time).dt.total_seconds() / 86400).round(4)

        ring_accounts = pd.DataFrame(acct_recs, columns=["ring_id", "account_id"])

        io.ensure_dir(dest)
        con = io.duckdb_connect(dest)
        for name, df in [("rings", rings), ("ring_txns", ring_txns),
                         ("ring_accounts", ring_accounts)]:
            con.register("df", df)
            con.execute(f"COPY df TO '{dest}/{name}.parquet' (FORMAT PARQUET)")

        run.record(
            rings=len(rings),
            ring_txns=len(ring_txns),
            distinct_ring_accounts=int(ring_accounts.account_id.nunique()),
            typologies=int(rings.typology.nunique()),
            start_time=str(rings.start_time.min()),
            end_time=str(rings.end_time.max()),
            median_txns_per_ring=float(rings.n_txns.median()),
            median_accounts_per_ring=float(rings.n_accounts.median()),
            max_duration_days=float(rings.duration_days.max()),
            rings_ge_3_txns=int((rings.n_txns >= 3).sum()),
            typology_counts=rings.typology.value_counts().to_dict(),
        )
        print(io.json_line({"event": "parse_patterns_complete", **run.metrics}))
        return run.metrics
