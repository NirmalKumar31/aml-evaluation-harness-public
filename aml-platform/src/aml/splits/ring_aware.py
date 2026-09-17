"""
build_splits: the ring-participant-disjoint, temporal train/test split.

THIS IS THE LOAD-BEARING COMPONENT. Every downstream number is meaningless if
this is wrong, and a wrong split fails silently -- it just makes results better.

Three things go wrong with a naive "cut the timeline in half" split:

  1. RINGS STRADDLE THE CUT. A ring runs for days or months. Cut through it and
     the model trains on its first half, then "detects" its second half by
     recognising accounts it was already given the answers for.

  2. RINGS SHARE ACCOUNTS. Even with whole rings on each side, a launderer
     reuses mule accounts across operations. Same memorisation, different door.

  3. RING-LEVEL RECALL AMPLIFIES IT. Ring recall asks "was ANY member alerted?"
     So a single leaked account makes an entire ring score as detected.

The fix, in order:
  - assign whole RINGS by their START time            (fixes 1)
  - drop TEST rings sharing any account with train    (fixes 2 and 3)
  - drop straddling train-ring tails out of the test window
  - assert disjointness, and fail the build if violated
"""
import sys

import duckdb
import pandas as pd

from aml import io
from aml.manifest import Run, cached_or_none


class LeakageError(Exception):
    """The split is not leak-free. Never caught -- this must stop the build."""


def _con(patterns: str, labeled: str) -> duckdb.DuckDBPyConnection:
    c = io.duckdb_connect((patterns, labeled))
    c.execute(f"CREATE VIEW R  AS SELECT * FROM '{patterns}/rings.parquet'")
    c.execute(f"CREATE VIEW RA AS SELECT * FROM '{patterns}/ring_accounts.parquet'")
    c.execute(f"CREATE VIEW L  AS SELECT * FROM read_parquet({io.parquet_arg(labeled + '/txns_labeled')})")
    return c


def _split_sets(c, cut: str) -> dict:
    """The four ring sets that define the split, computed once."""
    c.execute(f"""
        CREATE OR REPLACE TEMP VIEW train_rings AS
            SELECT ring_id FROM R WHERE start_time <  TIMESTAMP '{cut}';
        CREATE OR REPLACE TEMP VIEW test_rings_raw AS
            SELECT ring_id FROM R WHERE start_time >= TIMESTAMP '{cut}';
        CREATE OR REPLACE TEMP VIEW train_accounts AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM train_rings);
        CREATE OR REPLACE TEMP VIEW test_accounts_raw AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM test_rings_raw);
        CREATE OR REPLACE TEMP VIEW overlap_accounts AS
            SELECT account_id FROM train_accounts
            INTERSECT SELECT account_id FROM test_accounts_raw;
        -- Drop the WHOLE ring, not just the offending account: amputating a node
        -- changes the ring's shape, and graph features would still carry the
        -- contaminated account's fingerprint to its neighbours.
        CREATE OR REPLACE TEMP VIEW dropped_rings AS
            SELECT DISTINCT ring_id FROM RA
            WHERE ring_id IN (SELECT * FROM test_rings_raw)
              AND account_id IN (SELECT * FROM overlap_accounts);
        CREATE OR REPLACE TEMP VIEW test_rings AS
            SELECT ring_id FROM test_rings_raw
            EXCEPT SELECT ring_id FROM dropped_rings;
        CREATE OR REPLACE TEMP VIEW test_accounts AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM test_rings);
    """)
    return {}


def sweep(patterns: str, labeled: str, fractions=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8)) -> pd.DataFrame:
    """Diagnostic: what does each candidate cut point cost and buy?

    Ring STARTS often span far less than the file does (the generator injects
    rings early and lets them run), so the usable cut window is narrower than
    it looks. This table is how we pick a cut from data instead of guessing.
    """
    c = _con(patterns, labeled)
    lo, hi = c.execute("SELECT min(start_time), max(start_time) FROM R").fetchone()
    span_days = (hi - lo).days
    rows = []
    for f in fractions:
        cut = (lo + pd.Timedelta(days=span_days * f)).strftime("%Y-%m-%d")
        _split_sets(c, cut)
        n = c.execute("""
            SELECT (SELECT count(*) FROM train_rings),
                   (SELECT count(*) FROM test_rings_raw),
                   (SELECT count(*) FROM dropped_rings),
                   (SELECT count(*) FROM test_rings),
                   (SELECT count(*) FROM overlap_accounts)
        """).fetchone()
        straddle = c.execute(f"""SELECT count(*) FROM R
            WHERE start_time < TIMESTAMP '{cut}' AND end_time >= TIMESTAMP '{cut}'""").fetchone()[0]
        n_typ = c.execute("SELECT count(DISTINCT typology) FROM R").fetchone()[0]
        rows.append(dict(frac=f, cut=cut, train_rings=n[0], test_rings_raw=n[1],
                         straddling=straddle, overlap_accounts=n[4], dropped=n[2],
                         test_rings_kept=n[3], per_typology=round(n[3] / max(n_typ, 1))))
    return pd.DataFrame(rows)


PROTOCOLS = ("ring-aware", "naive")


def build(patterns: str, labeled: str, cut: str, dest: str,
          manifest_dir: str | None = None, min_test_positives: int = 100,
          force: bool = False, protocol: str = "ring-aware"):
    """Build a train/test split under one of two protocols.

    `naive` exists to be MEASURED AGAINST, not used. It is the plain temporal
    cut a practitioner would reach for: train on everything before the cut,
    test on everything after, no ring discipline at all. The preregistered
    split-inflation experiment (paper/PREREGISTRATION_split_inflation.md)
    compares what the two protocols would report.

    It is the SAME CODE PATH with the filter disabled, deliberately. A second
    implementation of "the naive split" would be a second chance for the
    two-independent-derivations bug that the txn_id defect already taught this
    project once.

    The training set is byte-identical under both protocols -- the ring
    discipline is purely a test-set filter -- so any difference is entirely
    attributable to which rows a protocol admits into the evaluation set.
    """
    if protocol not in PROTOCOLS:
        raise ValueError(f"protocol must be one of {PROTOCOLS}, got {protocol!r}")
    patterns, labeled, dest = str(patterns), str(labeled), str(dest)
    cfg = {"patterns": patterns, "labeled": labeled, "cut_time": cut, "dest": dest,
           "split_spec_version": "1.1.0", "min_test_positives": min_test_positives,
           "protocol": protocol}

    key, hit = cached_or_none("build_splits", cfg, [patterns, labeled],
                              (manifest_dir or dest),
                              modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run("build_splits", cfg, manifest_dir or dest, key=key) as run:
        c = _con(patterns, labeled)
        _split_sets(c, cut)
        io.ensure_dir(dest)

        # ---- TRAIN: everything before the cut. Test rings start after the cut,
        # so by construction none of their transactions can be here.
        c.execute(f"""COPY (SELECT * FROM L WHERE event_time < TIMESTAMP '{cut}')
                      TO '{dest}/train' (FORMAT PARQUET, PARTITION_BY (event_date),
                                         OVERWRITE_OR_IGNORE)""")

        # ---- TEST: after the cut, MINUS two things:
        #   (a) transactions of dropped rings (shared an account with train)
        #   (b) the tails of straddling train rings -- their ring is in train,
        #       so the model has already seen it. This is the leak that a plain
        #       temporal split leaves behind even after ring-level assignment.
        #
        # Under `naive` neither filter is applied: the test set is every
        # post-cut row, which is what the comparison exists to price.
        ring_filter = ("" if protocol == "naive" else
                       " AND (ring_id IS NULL OR ring_id IN (SELECT * FROM test_rings))")
        c.execute(f"""COPY (
                SELECT * FROM L
                WHERE event_time >= TIMESTAMP '{cut}'{ring_filter}
            ) TO '{dest}/test' (FORMAT PARQUET, PARTITION_BY (event_date),
                                OVERWRITE_OR_IGNORE)""")

        for v in ("train_rings", "test_rings", "dropped_rings"):
            c.execute(f"COPY (SELECT * FROM {v}) TO '{dest}/{v}.parquet' (FORMAT PARQUET)")

        c.execute(f"CREATE VIEW TR AS SELECT * FROM read_parquet({io.parquet_arg(dest + '/train')})")
        c.execute(f"CREATE VIEW TE AS SELECT * FROM read_parquet({io.parquet_arg(dest + '/test')})")

        # ================= ASSERTIONS =================
        # These are the whole point of this file. Fail loudly, never warn.
        #
        # The three RING assertions are what `naive` is defined by the absence
        # of, so running them there would fail by construction. They are
        # skipped rather than weakened, and the manifest records which set
        # actually ran -- `assertions_passed` must never imply a check that was
        # not performed. The TEMPORAL assertions apply to both protocols and
        # are not skipped: a naive split is still a split.
        ring_checks = protocol != "naive"
        if ring_checks:
            n_shared = c.execute("""SELECT count(*) FROM (
                SELECT account_id FROM train_accounts
                INTERSECT SELECT account_id FROM test_accounts)""").fetchone()[0]
            if n_shared != 0:
                raise LeakageError(
                    f"{n_shared} ring-participating accounts appear on BOTH sides of the "
                    f"split at cut={cut}. The split is leaking.")

            n_both = c.execute("""SELECT count(*) FROM (
                SELECT ring_id FROM train_rings
                INTERSECT SELECT ring_id FROM test_rings)""").fetchone()[0]
            if n_both != 0:
                raise LeakageError(f"{n_both} rings appear on both sides at cut={cut}.")

        n_late = c.execute(f"""SELECT count(*) FROM TR
            WHERE event_time >= TIMESTAMP '{cut}'""").fetchone()[0]
        n_early = c.execute(f"""SELECT count(*) FROM TE
            WHERE event_time < TIMESTAMP '{cut}'""").fetchone()[0]
        if n_late or n_early:
            raise LeakageError(f"temporal bleed: {n_late} train rows after cut, "
                               f"{n_early} test rows before cut")

        n_strad = c.execute("""SELECT count(*) FROM TE
            WHERE ring_id IS NOT NULL AND ring_id IN (SELECT * FROM train_rings)""").fetchone()[0]
        if ring_checks and n_strad != 0:
            raise LeakageError(f"{n_strad} test transactions belong to TRAINING rings "
                               f"(straddling ring tails were not removed)")

        # ---- counts for the manifest
        stats = c.execute("""
            SELECT (SELECT count(*) FROM TR), (SELECT sum(is_laundering) FROM TR),
                   (SELECT count(*) FROM TE), (SELECT sum(is_laundering) FROM TE),
                   (SELECT count(*) FROM train_rings), (SELECT count(*) FROM test_rings_raw),
                   (SELECT count(*) FROM dropped_rings), (SELECT count(*) FROM test_rings),
                   (SELECT count(*) FROM overlap_accounts)
        """).fetchone()

        # Positive (account, day) pairs in test -- the denominator of recall@budget.
        pad = c.execute("""
            WITH ad AS (
                SELECT sender_id AS acct, event_date AS d, max(is_laundering) AS y FROM TE GROUP BY 1,2
                UNION ALL
                SELECT receiver_id, event_date, max(is_laundering) FROM TE GROUP BY 1,2)
            SELECT count(*) FILTER (WHERE y=1), count(*)
            FROM (SELECT acct, d, max(y) AS y FROM ad GROUP BY 1,2)
        """).fetchone()

        # ---- OPTION B sensitivity: the 1,968-style positives that belong to no
        # ring can't be ring-assigned, so Option A leaves them wherever they fall.
        # Measure what a stricter rule WOULD have removed, and report it rather
        # than silently choosing. Documented in the manifest either way.
        opt_b = c.execute("""
            WITH ad AS (
                SELECT sender_id AS acct, event_date AS d, max(is_laundering) AS y,
                       max(CASE WHEN ring_id IS NULL THEN 1 ELSE 0 END) AS unl FROM TE GROUP BY 1,2
                UNION ALL
                SELECT receiver_id, event_date, max(is_laundering),
                       max(CASE WHEN ring_id IS NULL THEN 1 ELSE 0 END) FROM TE GROUP BY 1,2),
            g AS (SELECT acct, d, max(y) AS y, max(unl) AS unl FROM ad GROUP BY 1,2)
            SELECT count(*) FILTER (WHERE y=1 AND unl=1
                     AND acct IN (SELECT account_id FROM train_accounts))
            FROM g
        """).fetchone()[0]

        run.record(
            cut_time=cut,
            train_rows=int(stats[0]), train_positives=int(stats[1] or 0),
            test_rows=int(stats[2]), test_positives=int(stats[3] or 0),
            train_rings=int(stats[4]), test_rings_before_drop=int(stats[5]),
            dropped_rings=int(stats[6]), test_rings_kept=int(stats[7]),
            overlap_accounts=int(stats[8]),
            dropped_pct=round(100 * stats[6] / stats[5], 2) if stats[5] else 0.0,
            test_positive_account_days=int(pad[0] or 0),
            test_total_account_days=int(pad[1]),
            unlabeled_positive_acct_days_touching_train_rings=int(opt_b),
            unlabeled_handling="A: disjointness applies to ring-participating accounts only",
            protocol=protocol,
            # Counted under both protocols, enforced under one. This is the
            # quantity the inflation experiment is about, so it is recorded
            # even -- especially -- when it is allowed to be non-zero.
            straddling_ring_tail_rows_in_test=int(n_strad),
            assertions_passed=(
                ["accounts_disjoint", "rings_disjoint", "no_temporal_bleed",
                 "no_train_ring_tails_in_test"] if ring_checks
                else ["no_temporal_bleed"]),
        )

        if run.metrics["test_positive_account_days"] < min_test_positives:
            raise LeakageError(
                f"only {run.metrics['test_positive_account_days']} positive account-days "
                f"survive at cut={cut} (need >= {min_test_positives}). MOVE THE CUT -- "
                f"never weaken the assertions to keep more data.")

        print(io.json_line({"event": "build_splits_complete", **run.metrics}))
        return run.metrics
