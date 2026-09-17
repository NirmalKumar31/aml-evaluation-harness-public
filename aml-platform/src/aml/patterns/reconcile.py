"""
reconcile_labels: join the answer key back onto the transaction table.

Two independent files claim to describe the same laundering:
  Trans.csv       flags individual transactions with is_laundering = 1
  Patterns.txt    groups transactions into named rings

They do NOT agree, by design. Roughly 31% of flagged transactions belong to no
named pattern -- real laundering that doesn't fit a textbook shape.

This component measures that disagreement instead of assuming it away, and
attaches ring_id / typology to the transactions where it exists.

GOTCHA 2 enforced here: typology is a NULLABLE ENRICHMENT, never a join key.
"""
import sys

from aml import io
from aml.manifest import Run, cached_or_none

# Ring transactions carry no row id, so we match on business content. Amounts
# are rounded to cents because they are decimal text on both sides.
JOIN_KEYS = "event_time, sender_id, receiver_id, round(amount_paid, 2), payment_format"


def reconcile(txns: str, patterns: str, dest: str, manifest_dir: str | None = None,
              force: bool = False):
    txns, patterns, dest = str(txns), str(patterns), str(dest)
    cfg = {"txns": txns, "patterns": patterns, "dest": dest, "join_keys": JOIN_KEYS}

    key, hit = cached_or_none("reconcile_labels", cfg, [txns, patterns], (manifest_dir or dest),
                             modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run("reconcile_labels", cfg, manifest_dir or dest, key=key) as run:
        io.ensure_dir(dest)
        con = io.duckdb_connect((txns, patterns, dest))
        con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet({io.parquet_arg(txns)})")
        con.execute(f"CREATE VIEW rt AS SELECT * FROM read_parquet('{patterns}/ring_txns.parquet')")

        # One row per (ring transaction) content key -> ring_id. A content key
        # can legitimately appear in more than one ring; keep the lowest id and
        # count how often it happens so we can report it rather than hide it.
        con.execute(f"""
            CREATE VIEW rt_key AS
            SELECT {JOIN_KEYS.replace('round(amount_paid, 2)', 'round(amount_paid, 2) AS amt2')},
                   min(ring_id) AS ring_id,
                   min(typology) AS typology,
                   count(DISTINCT ring_id) AS n_rings_for_key
            FROM rt GROUP BY 1,2,3,4,5
        """)

        # Left join: every transaction survives, ring_id is NULL when unmatched.
        con.execute(f"""
            COPY (
                SELECT t.*, k.ring_id, k.typology
                FROM t
                LEFT JOIN rt_key k
                  ON  t.event_time     = k.event_time
                  AND t.sender_id      = k.sender_id
                  AND t.receiver_id    = k.receiver_id
                  AND round(t.amount_paid, 2) = k.amt2
                  AND t.payment_format = k.payment_format
            ) TO '{dest}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date),
                                        OVERWRITE_OR_IGNORE)
        """)

        con.execute(f"CREATE VIEW L AS SELECT * FROM read_parquet({io.parquet_arg(dest + '/txns_labeled')})")
        s = con.execute("""
            SELECT count(*)                                                    AS rows,
                   sum(is_laundering)                                          AS flagged,
                   sum(CASE WHEN ring_id IS NOT NULL THEN 1 ELSE 0 END)        AS with_ring,
                   sum(CASE WHEN is_laundering=1 AND ring_id IS NOT NULL
                            THEN 1 ELSE 0 END)                                 AS flagged_with_ring,
                   sum(CASE WHEN is_laundering=1 AND ring_id IS NULL
                            THEN 1 ELSE 0 END)                                 AS flagged_no_ring,
                   sum(CASE WHEN is_laundering=0 AND ring_id IS NOT NULL
                            THEN 1 ELSE 0 END)                                 AS unflagged_with_ring
            FROM L
        """).fetchone()

        ring_txns_total = con.execute("SELECT count(*) FROM rt").fetchone()[0]
        ambiguous = con.execute("SELECT count(*) FROM rt_key WHERE n_rings_for_key > 1").fetchone()[0]

        rows, flagged, with_ring, flagged_with_ring, flagged_no_ring, unflagged_with_ring = s
        run.record(
            rows=int(rows),
            flagged_txns=int(flagged),
            ring_txns_in_patterns_file=int(ring_txns_total),
            flagged_with_ring=int(flagged_with_ring),
            flagged_without_ring=int(flagged_no_ring),
            typology_coverage_pct=round(100 * flagged_with_ring / flagged, 2),
            unflagged_but_in_a_ring=int(unflagged_with_ring),
            ring_txns_not_found_in_trans=int(ring_txns_total - with_ring),
            ambiguous_content_keys=int(ambiguous),
        )
        print(io.json_line({"event": "reconcile_complete", **run.metrics}))
        return run.metrics
