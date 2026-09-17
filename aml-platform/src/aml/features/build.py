"""
build_features: labeled transactions -> model-ready feature table.

THE ABSOLUTE RULE
    Every feature must be computable from information strictly BEFORE the
    transaction's own event_time. No global aggregates, no future windows, no
    target encoding over the full dataset.

Why it matters: a feature that peeks at the future makes the model look
brilliant in testing and useless in production. It is leakage wearing a
different hat from the split problem, and it fails just as silently.

HOW WE ENFORCE IT
    Timestamps are minute-resolution, so several transactions routinely share
    the exact same event_time. A window frame of "... AND CURRENT ROW" would
    include those siblings -- information from the same instant, which the
    model would not have at decision time. So every trailing window ends at
    INTERVAL 1 MINUTE PRECEDING, which at minute granularity means "everything
    strictly earlier, nothing from this minute". Tested in
    tests/leakage/test_causal_features.py with a planted future outlier.

ACCOUNT HISTORY IS TWO-SIDED
    A mule account mostly RECEIVES. If we only aggregated rows where it was the
    sender, its history would look empty. So we build a unified event stream
    where each transaction contributes one event to the sender and one to the
    receiver, compute history per account over that, then join back to both
    sides of the transaction.
"""
import sys

from aml import io, schema
from aml.manifest import Run, cached_or_none

WINDOWS = {"1d": "1 DAY", "7d": "7 DAY", "30d": "30 DAY"}

# Everything the model is allowed to see. Keeping this explicit means a new
# column cannot silently become a feature.
TRANSACTION_FEATURES = [
    "log_amount_paid", "log_amount_received", "fx_ratio", "currency_mismatch",
    "amount_roundness", "hour", "dayofweek", "is_weekend", "is_self_transfer",
    "is_cross_bank", "payment_format_code", "payment_currency_code",
]
HISTORY_FEATURES = [
    f"{side}_{f}"
    for side in ("s", "r")
    for f in ("n_1d", "n_7d", "n_30d", "mean_amt_7d", "std_amt_7d", "max_amt_30d",
              "n_out_7d", "secs_since_prev", "secs_since_prev_cp", "amt_vs_hist")
]

# GRAPH FEATURES -- the network shape of the money, not the size of it.
#
# Laundering is defined by structure: many accounts into one (FAN-IN), one into
# many (FAN-OUT), closed loops (CYCLE), long chains (STACK). None of the
# features above can see any of that. They describe a transaction and an
# account's own volume; they never describe who it deals with.
#
# WHY THESE, AND NOT DEGREE / TRIANGLES / COMPONENTS
#     The obvious graph features -- exact distinct-counterparty degree, 2-hop
#     neighbourhood size, clustering coefficient, connected-component size --
#     need self-joins or iteration over the edge table. F3 in this project's
#     failure log is a 12.7 GiB out-of-memory caused by exactly that shape
#     (list_distinct(list(cp) OVER w7d)) on only 5M rows. At 182M it would not
#     survive, and the scale run is one-shot.
#
#     The trick that avoids it: `secs_since_prev_cp IS NULL` already means
#     "this account has never dealt with this counterparty before". That makes
#     "new counterparty" a per-event FLAG, and everything below is a windowed
#     SUM of that flag -- the same cost class as the existing features, no
#     self-join, no list materialisation.
#
#     n_distinct_cp_ever is the neat one: a running total of new counterparties
#     IS the account's degree, computed as a cumulative sum.
#
# All frames end at INTERVAL 1 MINUTE PRECEDING, exactly like the features
# above, so none of these can see the present or the future.
#
# ⚠️ EMPTY ON PURPOSE. THE MODEL SHIPS WITHOUT GRAPH FEATURES.
#
# The columns below are still COMPUTED and written to the parquet (see the
# COPY list) so the experiment stays reproducible from the stored data. They
# are simply not handed to the model, because measurement says they cost
# accuracy. Three rounds, HI-Small, 8 paired seeds, identical split/config,
# baseline = these 32 features:
#
#   +10 counts+ratios   AP -17% (ensemble), 0 of 8 seeds better, AP spread
#                       12.1% -> 24.4%
#   +2  counts          ring_recall@200 -5.1%. 0 better, 8 worse, 0 tied.
#                       Exact sign test, n=8, p=0.0078
#   +4  ratios          ring_recall@200 -6.4%. 0 better, 7 worse, 1 EXACTLY
#                       TIED. Sign tests drop ties, so n=7 and p=0.0156.
#                       Writing this arm as "0/8 improved" is true and
#                       misleading -- it hides why the two p-values differ.
#                       Report better/worse/tied, always.
#
# WHY, measured rather than guessed:
#   n_new_cp_7d correlates 0.977 with s_n_7d / s_n_out_7d / s_n_30d and 1.000
#   with r_n_1d. In this data almost every counterparty is new, so "new
#   counterparties this week" IS "transactions this week" -- volume wearing a
#   graph costume. No new information, and a duplicate column still competes
#   for splits.
#
#   The rate features avoid that (max |r| vs any existing feature 0.22-0.52)
#   and did WORSE, because they carry almost no class signal: laundering vs
#   normal separates 1.03x, 1.04x, 0.85x. Against 1,528 training positives --
#   47.8 per feature at 32 -- a near-noise column is a pure variance cost.
#
# The real reason none of this worked: every feature here is computed from ONE
# ACCOUNT'S OWN event stream. That is a time series, not a graph. FAN-IN,
# FAN-OUT, CYCLE and STACK are properties of the SUBGRAPH -- who your
# counterparties deal with, whether money returns to you. No per-account
# trailing count can see that. Doing it properly needs self-joins or iteration
# over the edge table, which is F3 in the failure log: 12.7 GiB OOM on 5M rows.
#
# See paper/RESULTS_graph_features.md. Re-enable only with a paired A/B that
# beats this baseline on ring_recall@200; do not re-enable on intuition.
GRAPH_FEATURES: list[str] = []

FEATURES = TRANSACTION_FEATURES + HISTORY_FEATURES + GRAPH_FEATURES


def _history_sql() -> str:
    """Trailing-window account history over the unified event stream."""
    frames = ",\n            ".join(
        f"w{k} AS (PARTITION BY account_id ORDER BY event_time "
        f"RANGE BETWEEN INTERVAL {v} PRECEDING AND INTERVAL 1 MINUTE PRECEDING)"
        for k, v in WINDOWS.items()
    )
    # NOTE: an earlier version computed distinct counterparties as
    # len(list_distinct(list(cp) OVER w7d)). It is exact but materialises one
    # list per row and blew past 12.7 GiB on 5M rows. `secs_since_prev_cp`
    # below costs one extra sort and carries the same signal more directly:
    # NULL means "this account has never dealt with this counterparty before",
    # which is the FAN-OUT / SCATTER fingerprint we actually want.
    return f"""
        WITH flagged AS (
            -- Pass 1: per event, when did this account last deal with THIS
            -- counterparty? NULL means never -- which makes "new counterparty"
            -- a flag we can sum in pass 2, instead of a list we would have to
            -- materialise. See the GRAPH_FEATURES note for why that matters.
            SELECT *,
                max(event_time) OVER wcp AS prev_cp_time,
                CASE WHEN max(event_time) OVER wcp IS NULL THEN 1 ELSE 0 END
                    AS is_new_cp
            FROM events
            WINDOW wcp AS (PARTITION BY account_id, cp ORDER BY event_time
                           RANGE BETWEEN UNBOUNDED PRECEDING
                                     AND INTERVAL 1 MINUTE PRECEDING)
        )
        SELECT
            txn_id, side,
            count(*)                     OVER w1d  AS n_1d,
            count(*)                     OVER w7d  AS n_7d,
            count(*)                     OVER w30d AS n_30d,
            avg(amount_paid)             OVER w7d  AS mean_amt_7d,
            stddev_pop(amount_paid)      OVER w7d  AS std_amt_7d,
            max(amount_paid)             OVER w30d AS max_amt_30d,
            -- coalesce because SQL sum() over an EMPTY window returns NULL,
            -- while count() over the same empty window returns 0. That made
            -- n_out_7d NULL exactly where n_7d was 0 -- inconsistent inside the
            -- batch path, and different from the serving path, which computes
            -- Python sum([]) = 0. Caught by tests/parity. 0 is the correct
            -- answer: we KNOW there were no outgoing transactions.
            coalesce(sum(is_out) OVER w7d, 0)         AS n_out_7d,
            epoch(event_time - max(event_time) OVER w30d) AS secs_since_prev,
            epoch(event_time - prev_cp_time)              AS secs_since_prev_cp,

            -- ---- graph shape, all from windowed sums of the pass-1 flag ----
            -- Same coalesce reasoning as n_out_7d: an empty window means we
            -- KNOW the count is 0, not that it is unknown.
            coalesce(count(*) OVER w7d - sum(is_out) OVER w7d, 0) AS n_in_7d,
            -- Direction of flow. 1.0 = only ever sent this week (FAN-OUT side),
            -- 0.0 = only ever received (FAN-IN side). NULL on a cold start,
            -- because with no history there is no direction to report.
            sum(is_out) OVER w7d / nullif(count(*) OVER w7d, 0) AS out_share_7d,
            coalesce(sum(is_new_cp) OVER w7d, 0)      AS n_new_cp_7d,
            -- How much of this week's activity is with parties never seen
            -- before. High = spraying outward; low = cycling among the same
            -- few accounts.
            sum(is_new_cp) OVER w7d / nullif(count(*) OVER w7d, 0)
                                                      AS new_cp_rate_7d,
            -- Degree: a running total of "first time with this counterparty"
            -- IS the number of distinct counterparties seen so far.
            coalesce(sum(is_new_cp) OVER wall, 0)     AS n_distinct_cp_ever
        FROM flagged
        WINDOW
            {frames},
            wall AS (PARTITION BY account_id ORDER BY event_time
                     RANGE BETWEEN UNBOUNDED PRECEDING
                               AND INTERVAL 1 MINUTE PRECEDING)
    """


def build(src: str, dest: str, manifest_dir: str | None = None,
          threads: int | None = None, memory_limit: str | None = None,
          temp_directory: str | None = None, force: bool = False):
    src, dest = str(src), str(dest)
    # 1.2.0 writes the graph columns to the parquet. 1.1.0 read txn_id from the
    # input rather than regenerating it here.
    #
    # n_features is deliberately NOT here. The written table is decided by the
    # hardcoded column lists below, not by FEATURES, so including it would
    # invalidate the cache and force a 182M-row rebuild that produces a
    # byte-identical table -- which is exactly what cutting GRAPH_FEATURES to
    # [] would otherwise have triggered. What DOES decide the output is the SQL
    # in this module, and `modules=(sys.modules[__name__],)` now covers that.
    cfg = {"src": src, "dest": dest, "feature_spec_version": "1.2.0",
           "windows": WINDOWS}

    key, hit = cached_or_none("build_features", cfg, [src], (manifest_dir or dest),
                             modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run("build_features", cfg, manifest_dir or dest, key=key) as run:
        con = io.duckdb_connect((src, dest), threads=threads,
                                memory_limit=memory_limit, temp_directory=temp_directory)
        if threads:
            con.execute(f"SET threads={threads}")
        if memory_limit:
            con.execute(f"SET memory_limit='{memory_limit}'")

        # txn_id is READ, never regenerated. It was assigned once at ingest --
        # see ingest/normalize.py for the silent corruption that regenerating it
        # here used to cause.
        con.execute(f"""
            CREATE VIEW t AS SELECT * FROM read_parquet({io.parquet_arg(src)})
        """)
        schema.require_txn_id(con, "t")
        # One transaction -> two account events. 's' = the sending account's
        # view of it, 'r' = the receiving account's view.
        con.execute("""
            CREATE VIEW events AS
                SELECT txn_id, 's' AS side, sender_id   AS account_id, event_time,
                       amount_paid, receiver_id AS cp, 1 AS is_out FROM t
                UNION ALL
                SELECT txn_id, 'r',        receiver_id,               event_time,
                       amount_paid, sender_id,          0            FROM t
        """)
        con.execute(f"CREATE VIEW hist AS {_history_sql()}")

        hist_cols = ["n_1d", "n_7d", "n_30d", "mean_amt_7d", "std_amt_7d",
                     "max_amt_30d", "n_out_7d", "secs_since_prev", "secs_since_prev_cp",
                     # graph shape -- see GRAPH_FEATURES
                     "n_in_7d", "out_share_7d", "n_new_cp_7d", "new_cp_rate_7d",
                     "n_distinct_cp_ever"]
        sel_s = ",\n                ".join(f"hs.{c} AS s_{c}" for c in hist_cols)
        sel_r = ",\n                ".join(f"hr.{c} AS r_{c}" for c in hist_cols)

        io.ensure_dir(dest)
        con.execute(f"""
            COPY (
              SELECT
                t.txn_id, t.event_time, t.event_date, t.sender_id, t.receiver_id,
                t.is_laundering, t.ring_id, t.typology,

                -- transaction-level: no history needed, nothing to leak
                -- ln(), NOT log(). DuckDB's log() is base 10; numpy's np.log is
                -- natural. The serving path uses np.log, so log() here produced
                -- values 2.3x smaller than serving would -- every threshold the
                -- model learned would land on the wrong side in production, with
                -- no error raised anywhere. Caught by tests/parity.
                ln(1 + t.amount_paid)                          AS log_amount_paid,
                ln(1 + t.amount_received)                      AS log_amount_received,
                t.amount_received / nullif(t.amount_paid, 0)   AS fx_ratio,
                CAST(t.payment_currency <> t.receiving_currency AS TINYINT)
                                                               AS currency_mismatch,
                -- structuring signal: launderers round to just under a threshold
                CASE WHEN t.amount_paid = round(t.amount_paid, -3) THEN 3
                     WHEN t.amount_paid = round(t.amount_paid, -2) THEN 2
                     WHEN t.amount_paid = round(t.amount_paid, 0)  THEN 1
                     ELSE 0 END                                AS amount_roundness,
                hour(t.event_time)                             AS hour,
                dayofweek(t.event_time)                        AS dayofweek,
                CAST(dayofweek(t.event_time) IN (0, 6) AS TINYINT) AS is_weekend,
                CAST(t.sender_id = t.receiver_id AS TINYINT)   AS is_self_transfer,
                CAST(t.sender_bank <> t.receiver_bank AS TINYINT) AS is_cross_bank,
                hash(t.payment_format)   % 1000                AS payment_format_code,
                hash(t.payment_currency) % 1000                AS payment_currency_code,

                {sel_s},
                {sel_r},
                t.amount_paid / nullif(hs.mean_amt_7d, 0)      AS s_amt_vs_hist,
                t.amount_paid / nullif(hr.mean_amt_7d, 0)      AS r_amt_vs_hist

              FROM t
              LEFT JOIN hist hs ON hs.txn_id = t.txn_id AND hs.side = 's'
              LEFT JOIN hist hr ON hr.txn_id = t.txn_id AND hr.side = 'r'
            ) TO '{dest}' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
        """)

        s = con.execute(f"""
            SELECT count(*), sum(is_laundering),
                   avg(CASE WHEN s_n_7d = 0 THEN 1 ELSE 0 END),
                   avg(CASE WHEN s_secs_since_prev IS NULL THEN 1 ELSE 0 END)
            FROM read_parquet({io.parquet_arg(dest)})
        """).fetchone()
        run.record(rows=int(s[0]), positives=int(s[1] or 0), n_features=len(FEATURES),
                   features=FEATURES,
                   pct_sender_no_7d_history=round(100 * s[2], 2),
                   pct_sender_first_ever_txn=round(100 * s[3], 2))
        print(io.json_line({"event": "build_features_complete",
                          **{k: v for k, v in run.metrics.items() if k != "features"}}))
        return run.metrics
