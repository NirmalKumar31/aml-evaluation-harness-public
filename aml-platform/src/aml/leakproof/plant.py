"""
plant_leak: deliberately build a LEAKY feature table.

WHY THIS EXISTS
    build_splits asserts the split is leak-free, and every assertion passes.
    But a passing assertion and a BROKEN CHECKER are indistinguishable from the
    outside. If our harness could not detect leakage even when it exists, a
    clean result would mean nothing.

    So we cheat on purpose, and require the harness to notice. That converts
    "my numbers are clean" from a claim into a demonstration.

TWO KINDS OF LEAK, because they fail differently
    reversed_window   The realistic one. Someone writes FOLLOWING where they
                      meant PRECEDING in a window frame. One word. The code
                      runs, the shapes are right, nothing warns -- and the
                      feature now describes the future. This is the mistake
                      that actually happens.

    target            The blatant one. A feature derived from the label itself,
                      aggregated over an account's whole history including the
                      future. Equivalent to target-encoding on the full dataset.
                      Should produce an absurd score.

Neither is ever used in a real run. `plant` writes to its own directory and the
production feature path never reads it.
"""
import sys

from aml import io, schema
from aml.manifest import Run, cached_or_none

LEAK_KINDS = ("reversed_window", "future_counterparty", "target")

# The leak columns each kind adds, appended to the honest FEATURES list.
LEAK_COLUMNS = {
    "reversed_window": ["s_n_next_1d", "s_n_next_7d", "s_max_amt_next_7d",
                        "r_n_next_1d", "r_n_next_7d", "r_max_amt_next_7d"],
    "future_counterparty": ["s_secs_until_next_cp", "s_n_future_with_cp",
                            "r_secs_until_next_cp", "r_n_future_with_cp"],
    "target": ["s_account_ever_laundered", "r_account_ever_laundered",
               "s_account_laundering_rate", "r_account_laundering_rate"],
}


def _reversed_window_sql() -> str:
    """PRECEDING -> FOLLOWING. The one-word typo, made explicit.

    Compare with features/build.py, which uses
        RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 MINUTE PRECEDING
    This is the same frame pointing the other way.
    """
    return """
        SELECT txn_id, side,
            count(*)          OVER wnext1 AS n_next_1d,
            count(*)          OVER wnext7 AS n_next_7d,
            max(amount_paid)  OVER wnext7 AS max_amt_next_7d
        FROM events
        WINDOW
            wnext1 AS (PARTITION BY account_id ORDER BY event_time
                       RANGE BETWEEN INTERVAL 1 MINUTE FOLLOWING
                                 AND INTERVAL 1 DAY FOLLOWING),
            wnext7 AS (PARTITION BY account_id ORDER BY event_time
                       RANGE BETWEEN INTERVAL 1 MINUTE FOLLOWING
                                 AND INTERVAL 7 DAY FOLLOWING)
    """


def _future_counterparty_sql() -> str:
    """The dangerous realistic leak: mirror a STRONG honest feature forwards.

    features/build.py's `secs_since_prev_cp` -- "how long since this account
    last dealt with this exact counterparty" -- is one of the better signals we
    have, because a brand-new counterparty is the FAN-OUT fingerprint.

    Point the same window forward and you get "how long until they deal with
    this counterparty AGAIN". Ring members transact with each other repeatedly
    over days, so this reveals ring membership directly -- while looking like an
    ordinary counterparty feature.

    Contrast reversed_window, which mirrored a WEAK, autocorrelated feature
    (activity counts) forwards and leaked nothing measurable. Severity depends
    on how much the future tells you that the past does not.
    """
    return """
        SELECT txn_id, side,
            epoch(min(event_time) OVER wfwd - event_time) AS secs_until_next_cp,
            count(*)                        OVER wfwd     AS n_future_with_cp
        FROM events
        WINDOW
            wfwd AS (PARTITION BY account_id, cp ORDER BY event_time
                     RANGE BETWEEN INTERVAL 1 MINUTE FOLLOWING
                               AND UNBOUNDED FOLLOWING)
    """


def _target_sql() -> str:
    """A feature computed from the label over an account's ENTIRE history.

    No window bounds at all, so it sees the future by construction. This is
    what "target encoding on the full dataset" looks like underneath.
    """
    return """
        SELECT txn_id, side,
            max(is_laundering) OVER (PARTITION BY account_id) AS account_ever_laundered,
            avg(is_laundering) OVER (PARTITION BY account_id) AS account_laundering_rate
        FROM events
    """


def plant(labeled: str, dest: str, kind: str = "reversed_window",
          manifest_dir: str | None = None, force: bool = False):
    if kind not in LEAK_KINDS:
        raise ValueError(f"kind must be one of {LEAK_KINDS}, got {kind!r}")
    labeled, dest = str(labeled), str(dest)
    # 1.1.0: txn_id read, not regenerated -- the join in prove.py was unsound
    # before this, so every pre-1.1.0 leak proof must be recomputed.
    cfg = {"labeled": labeled, "dest": dest, "kind": kind, "plant_version": "1.1.0"}

    key, hit = cached_or_none(f"plant_leak[{kind}]", cfg, [labeled],
                              (manifest_dir or dest),
                              modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run(f"plant_leak[{kind}]", cfg, manifest_dir or dest, key=key) as run:
        con = io.duckdb_connect((labeled, dest))
        # This used to regenerate txn_id with the same expression as
        # features/build.py, on the theory that identical expressions give
        # identical ids. They did not: the ordering key is not unique and the
        # sort is parallel, so the two tables disagreed about which transaction
        # each id meant, and the join below attached leak columns to the wrong
        # rows while validate="one_to_one" passed. Now it is read, not derived.
        con.execute(f"""
            CREATE VIEW t AS SELECT * FROM read_parquet({io.parquet_arg(labeled)})
        """)
        schema.require_txn_id(con, "t")
        con.execute("""
            CREATE VIEW events AS
                SELECT txn_id, 's' AS side, sender_id AS account_id, event_time,
                       amount_paid, receiver_id AS cp, is_laundering FROM t
                UNION ALL
                SELECT txn_id, 'r',        receiver_id,             event_time,
                       amount_paid, sender_id,         is_laundering FROM t
        """)
        sql = {"reversed_window": _reversed_window_sql,
               "future_counterparty": _future_counterparty_sql,
               "target": _target_sql}[kind]()
        con.execute(f"CREATE VIEW leak AS {sql}")

        cols = [c.split("_", 1)[1] for c in LEAK_COLUMNS[kind] if c.startswith("s_")]
        sel_s = ", ".join(f"ls.{c} AS s_{c}" for c in cols)
        sel_r = ", ".join(f"lr.{c} AS r_{c}" for c in cols)

        io.ensure_dir(dest)
        con.execute(f"""
            COPY (
                SELECT t.txn_id, {sel_s}, {sel_r}
                FROM t
                LEFT JOIN leak ls ON ls.txn_id = t.txn_id AND ls.side = 's'
                LEFT JOIN leak lr ON lr.txn_id = t.txn_id AND lr.side = 'r'
            ) TO '{dest}/leak.parquet' (FORMAT PARQUET)
        """)

        n = con.execute(f"SELECT count(*) FROM '{dest}/leak.parquet'").fetchone()[0]
        run.record(kind=kind, rows=int(n), leak_columns=LEAK_COLUMNS[kind])
        print(io.json_line({"event": "plant_leak_complete", **run.metrics}))
        return run.metrics
