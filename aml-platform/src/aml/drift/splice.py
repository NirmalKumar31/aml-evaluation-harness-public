"""
splice_drift: real negative background + manufactured laundering -> a drifted
labeled transaction table the rest of the pipeline can consume unchanged.

WHAT IS REAL AND WHAT IS NOT, precisely -- this matters for how results are
reported:

    REAL      every non-laundering transaction, untouched. 31.8M rows of
              genuine IBM traffic with its real amounts, timing, currencies,
              payment formats and account population.

    REAL      every laundering transaction's CONTENT -- amounts, internal
              timing, ring shape. Each is a verbatim copy of an IBM ring.

    INDUCED   only WHICH ring shapes appear WHEN, and which real account each
              ring member is mapped onto.

ACCOUNT MAPPING, AND THE BUG IT FIXES
    resample.py namespaces account ids per instance ("010_ABC#7") so two
    instances of one source ring never collide. Correct, but if those ids are
    spliced in verbatim they exist NOWHERE ELSE in the 31.8M-row background.
    Measured on the first attempt:

        overlap between laundering and background accounts : 0
        negatives with no 7-day history                    : 6.9%
        positives with no 7-day history                    : 43.0%
        mean prior 7-day transactions, negatives           : 17,973
        mean prior 7-day transactions, positives           : 1.78

    The model then scores a perfect recall_efficiency of 100% because it is not
    detecting laundering at all -- it is detecting "an account I have never
    seen before". The magnitude=0 control is what surfaced this: no drift
    should give no decay, but it also should not give a PERFECT model.

    So every synthetic account is mapped onto a REAL background account,
    sampled without replacement across instances. Each ring member then has
    genuine prior history, appears in ordinary traffic too (which is what a
    mule account does), and no two instances share an account -- so the split's
    ring-participant-disjointness rule still holds.

    THE MAPPING IS ACTIVITY-MATCHED, not uniform. Sampling accounts uniformly
    picks QUIET accounts, because most accounts in a 2M-account population
    barely transact -- while the negative rows, being weighted by transaction,
    come from BUSY ones. That mismatch made every history feature a giveaway:

        single-feature AUC        real data   uniform mapping
        r_secs_since_prev_cp        0.667         0.868
        s_n_out_7d                  0.630         0.827
        s_n_1d                      0.621         0.814

    and lifted average precision from 0.30 on real data to 0.88. So background
    accounts are binned by activity and drawn to match the activity
    distribution of the REAL ring accounts.

So the drift is a re-weighting of real laundering over time, not synthesised
laundering. That is a narrower and more defensible claim than "I generated
laundering data", and it is the claim to make.

The output has exactly the schema reconcile_labels produces, so build_features,
build_splits, train and evaluate all run against it with no changes.
"""
import sys

import pandas as pd

from aml import io, schema
from aml.manifest import Run, cached_or_none


def splice(labeled: str, drift: str, dest: str, seed: int = 0,
           manifest_dir: str | None = None, force: bool = False):
    labeled, drift, dest = str(labeled), str(drift), str(dest)
    cfg = {"labeled": labeled, "drift": drift, "dest": dest, "seed": seed,
           "splice_spec_version": "3.0.0"}

    key, hit = cached_or_none("splice_drift", cfg, [labeled, drift],
                              (manifest_dir or dest),
                              modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run("splice_drift", cfg, manifest_dir or dest, key=key) as run:
        io.ensure_dir(dest)
        con = io.duckdb_connect((labeled, drift, dest))
        con.execute(f"CREATE VIEW L AS SELECT * FROM read_parquet({io.parquet_arg(labeled)})")
        con.execute(f"CREATE VIEW D0 AS SELECT * FROM '{drift}/drift_ring_txns.parquet'")

        # ---- map every synthetic account onto a real background account ----
        con.execute("""
            CREATE VIEW synth_accts AS
                SELECT DISTINCT sender_id AS a FROM D0
                UNION SELECT DISTINCT receiver_id FROM D0;
            CREATE VIEW real_accts AS
                SELECT DISTINCT sender_id AS a FROM L WHERE is_laundering = 0
                UNION SELECT DISTINCT receiver_id FROM L WHERE is_laundering = 0;
        """)
        n_synth, n_real = con.execute(
            "SELECT (SELECT count(*) FROM synth_accts), (SELECT count(*) FROM real_accts)"
        ).fetchone()
        if n_real < n_synth:
            raise ValueError(
                f"need {n_synth:,} real accounts to map onto but the background only "
                f"has {n_real:,}. Reduce rings_per_bucket or use a larger variant.")

        # Activity of every background account, and of the REAL ring accounts
        # whose distribution we want to reproduce.
        act = con.execute("""
            SELECT a, count(*) AS n FROM (
                SELECT sender_id AS a FROM L WHERE is_laundering = 0
                UNION ALL SELECT receiver_id FROM L WHERE is_laundering = 0)
            GROUP BY a
        """).df()
        real_ring = con.execute("""
            SELECT DISTINCT a FROM (
                SELECT sender_id AS a FROM L WHERE ring_id IS NOT NULL
                UNION ALL SELECT receiver_id FROM L WHERE ring_id IS NOT NULL)
        """).df()

        import numpy as _np
        N_BINS = 10
        # Sort by (n, a), never by n alone: DuckDB does not guarantee row order,
        # so ties would bin differently on every run and the mapping would not be
        # reproducible. Same lesson as the ORDER BY in models/train.py.
        act = act.sort_values(["n", "a"], kind="mergesort").reset_index(drop=True)
        act["bin"] = _np.minimum((_np.arange(len(act)) * N_BINS) // len(act), N_BINS - 1)
        target = act.merge(real_ring, on="a", how="inner")
        # Fall back to the background's own shape if the real data has no rings
        # to imitate (only happens on synthetic fixtures).
        share = (target.bin.value_counts(normalize=True).reindex(range(N_BINS), fill_value=0)
                 if len(target) else
                 act.bin.value_counts(normalize=True).reindex(range(N_BINS), fill_value=0))
        if share.sum() == 0:
            share[:] = 1.0 / N_BINS
        share = share / share.sum()

        rng_ = _np.random.default_rng(seed)
        by_bin = {b: g.a.to_numpy() for b, g in act.groupby("bin")}
        want = _np.floor(share.to_numpy() * n_synth).astype(int)
        want[want.argmax()] += n_synth - want.sum()

        chosen = []
        deficit = 0
        for b in range(N_BINS):
            pool = by_bin.get(b, _np.array([]))
            k = min(want[b] + deficit, len(pool))
            deficit = want[b] + deficit - k
            if k:
                chosen.append(rng_.choice(pool, size=k, replace=False))
        if deficit:      # spill anywhere still free
            taken = set(_np.concatenate(chosen).tolist()) if chosen else set()
            spare = act.a.to_numpy()[~_np.isin(act.a.to_numpy(), list(taken))]
            chosen.append(rng_.choice(spare, size=deficit, replace=False))
        real_ids = rng_.permutation(_np.concatenate(chosen))

        synth_ids = _np.sort(con.execute("SELECT a FROM synth_accts").df().a.to_numpy())
        amap_df = pd.DataFrame({"synth": synth_ids, "real_id": real_ids[:len(synth_ids)]})
        con.register("amap_df", amap_df)
        con.execute("CREATE VIEW amap AS SELECT * FROM amap_df")
        con.execute("""
            CREATE VIEW D AS
            SELECT d.* EXCLUDE (sender_id, receiver_id),
                   ms.real_id AS sender_id, mr.real_id AS receiver_id
            FROM D0 d
            JOIN amap ms ON ms.synth = d.sender_id
            JOIN amap mr ON mr.synth = d.receiver_id
        """)

        # Only real laundering is discarded; the negative background stays.
        # ring_id becomes the drift instance_id -- one instance is one crime,
        # which is exactly what ring_id means downstream (metrics cluster the
        # bootstrap on it, and the split keeps it whole).
        # txn_id MUST survive this stage. It is the join key every downstream
        # component uses, and build_features refuses input without it. The
        # first version of this COPY listed columns explicitly and simply left
        # it out, which made the whole drift pipeline unreachable from the CLI:
        # splice succeeded, then build-features died on require_txn_id.
        #
        # Background rows keep their real id. Synthetic rows are transactions
        # that exist nowhere upstream, so they get fresh ids offset above the
        # background's maximum. The offset is applied to `drift_txn_seq`, which
        # resample.py assigned in Python -- NOT to a row_number() over the scan.
        # Deriving identity from scan order is what broke txn_id the first time.
        max_id = con.execute("SELECT coalesce(max(txn_id), 0) FROM L").fetchone()[0]
        con.execute(f"""
            COPY (
                SELECT txn_id,
                       event_time, sender_bank, sender_account, receiver_bank,
                       receiver_account, amount_received, receiving_currency,
                       amount_paid, payment_currency, payment_format,
                       is_laundering, sender_id, receiver_id, event_date,
                       ring_id, typology
                FROM L WHERE is_laundering = 0

                UNION ALL

                SELECT {int(max_id)} + 1 + drift_txn_seq             AS txn_id,
                       event_time,
                       split_part(sender_id,   '_', 1)             AS sender_bank,
                       substr(sender_id,   position('_' IN sender_id) + 1)
                                                                    AS sender_account,
                       split_part(receiver_id, '_', 1)             AS receiver_bank,
                       substr(receiver_id, position('_' IN receiver_id) + 1)
                                                                    AS receiver_account,
                       amount_received, receiving_currency,
                       amount_paid, payment_currency, payment_format,
                       CAST(1 AS TINYINT)                          AS is_laundering,
                       sender_id, receiver_id,
                       CAST(event_time AS DATE)                    AS event_date,
                       instance_id                                 AS ring_id,
                       typology
                FROM D
            ) TO '{dest}/txns_labeled'
              (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
        """)
        rows, distinct_ids = con.execute(
            f"SELECT count(*), count(DISTINCT txn_id) "
            f"FROM read_parquet({io.parquet_arg(dest + '/txns_labeled')})").fetchone()
        if rows != distinct_ids:
            raise schema.SchemaContractError(
                f"spliced output has {rows:,} rows but only {distinct_ids:,} distinct "
                f"txn_id. Background and synthetic ids collided, so every downstream "
                f"join is wrong. The offset is max(L.txn_id)={max_id:,}.")

        con.execute(f"CREATE VIEW O AS SELECT * FROM read_parquet({io.parquet_arg(dest + '/txns_labeled')})")
        s = con.execute("""
            SELECT count(*), sum(is_laundering),
                   count(DISTINCT ring_id) FILTER (WHERE ring_id IS NOT NULL),
                   min(event_time), max(event_time), count(DISTINCT event_date)
            FROM O
        """).fetchone()
        orig = con.execute("SELECT count(*), sum(is_laundering) FROM L").fetchone()

        # Every spliced positive belongs to a ring by construction -- unlike the
        # real data, where 38% of positives have no named typology. State it,
        # because it makes the drifted set EASIER than reality in one specific
        # way and that must not be quietly claimed as a result.
        unlabeled = con.execute(
            "SELECT count(*) FROM O WHERE is_laundering = 1 AND ring_id IS NULL").fetchone()[0]

        # The check that would have caught the ghost-account bug. Laundering
        # accounts MUST also appear in ordinary traffic, or the positives are
        # separable by identity rather than by behaviour.
        overlap = con.execute("""
            WITH pos AS (SELECT DISTINCT sender_id a FROM O WHERE is_laundering = 1
                         UNION SELECT DISTINCT receiver_id FROM O WHERE is_laundering = 1),
                 neg AS (SELECT DISTINCT sender_id a FROM O WHERE is_laundering = 0
                         UNION SELECT DISTINCT receiver_id FROM O WHERE is_laundering = 0)
            SELECT (SELECT count(*) FROM pos),
                   (SELECT count(*) FROM (SELECT a FROM pos INTERSECT SELECT a FROM neg))
        """).fetchone()
        if overlap[1] == 0:
            raise ValueError(
                "not one laundering account appears in the negative background. The "
                "positives are separable by identity, not behaviour, and any model "
                "will score ~100%. The account mapping did not apply.")

        # Instances must still be account-disjoint or the split will drop them.
        shared = con.execute("""
            SELECT count(*) FROM (
                SELECT a FROM (
                    SELECT sender_id a, ring_id FROM O WHERE ring_id IS NOT NULL
                    UNION ALL SELECT receiver_id, ring_id FROM O WHERE ring_id IS NOT NULL)
                GROUP BY a HAVING count(DISTINCT ring_id) > 1)
        """).fetchone()[0]
        if shared:
            raise ValueError(f"{shared} accounts belong to two ring instances")

        run.record(
            rows=int(s[0]), positives=int(s[1] or 0),
            ring_instances=int(s[2]),
            prevalence_pct=round(100 * s[1] / s[0], 4),
            min_event_time=str(s[3]), max_event_time=str(s[4]), days=int(s[5]),
            original_rows=int(orig[0]), original_positives=int(orig[1]),
            negatives_kept=int(orig[0] - orig[1]),
            positives_with_no_ring=int(unlabeled),
            laundering_accounts=int(overlap[0]),
            laundering_accounts_also_in_background=int(overlap[1]),
            accounts_shared_between_instances=0,
            synthetic_accounts_mapped=int(n_synth),
            real_accounts_available=int(n_real),
            note=("negatives are REAL and untouched; laundering content is REAL "
                  "(verbatim IBM rings); ring members are mapped onto REAL "
                  "background accounts; only WHICH shape appears WHEN is induced"),
        )
        print(io.json_line({"event": "splice_drift_complete", **run.metrics}))
        return run.metrics
