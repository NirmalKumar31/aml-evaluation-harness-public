"""
make_drift: resample whole rings to hit a target typology mix per time bucket.

THE METHOD, and the constraints that shape it

  1. RESAMPLE WHOLE RINGS, never individual transactions.
     A ring is one crime. Sampling transactions out of it would produce
     fragments that belong to no ring, corrupting every ring-level metric and
     the bootstrap clustering -- the same reason SMOTE is banned here.

  2. TIME-SHIFT THE WHOLE RING BY A WHOLE NUMBER OF DAYS.
     One delta for the entire ring, so internal inter-transaction timing is
     preserved exactly -- a FAN-OUT that fired 16 times over 3 days still fires
     16 times over 3 days.

     The shift must be a whole number of DAYS. An earlier version drew a
     fractional offset, which moved a 09:00 transaction to 17:53 and flattened
     the positives' time-of-day distribution:

         hour-of-day spread (max-min %)   negatives 6.70   positives 0.46
         the same figure on real data     negatives 6.70   positives 3.99

     Background traffic has a strong diurnal pattern; uniformly-shifted rings
     did not, so `hour` alone started separating the classes.

  3. REWRITE ACCOUNT IDS PER INSTANCE.
     The same source ring can be sampled into more than one bucket. Without a
     per-instance namespace, two copies would share accounts and the split's
     ring-participant-disjointness assertion would (correctly) drop both. The suffix is
     deterministic, so the output is reproducible.

  4. ASSIGN BY START TIME.
     A ring shifted into bucket 2 may still be running during bucket 3. We
     assign it to the bucket its START falls in and document that, rather than
     truncating rings -- truncation would change their shape, which is the one
     thing we are measuring.

  5. THE SOURCE POOL IS PARTITIONED PER BUCKET.
     Namespacing account ids stops two INSTANCES sharing accounts, but it does
     not stop the same SOURCE ring appearing in two buckets. Different accounts,
     identical amounts, identical internal timing -- the model would recognise a
     behavioural signature it was trained on. That is the Phase 1 leak wearing
     yet another hat.

     Splitting the pool in half (train buckets vs eval buckets) is not enough:
     the retraining strategies train on bucket 2 to predict bucket 3, so those
     two must be disjoint from each other as well. So each typology's pool is
     cut into n_buckets slices and bucket b draws only from slice b. No source
     ring ever appears in two buckets, whatever the strategy does.

     Rings ARE reused WITHIN a bucket when the schedule demands more of a
     typology than its slice holds. That costs effective sample size, not
     correctness, and the reuse factor is reported so it can be accounted for.

  6. THE NEGATIVE BACKGROUND IS UNTOUCHED.
     Only the laundering side is resampled. Normal traffic keeps its real
     distribution, so any measured decay is attributable to the typology mix
     and not to some artefact of regenerating the whole world.

GROUND TRUTH IS EXACT BY CONSTRUCTION. drift_manifest.json records the
schedule, the seed, and every (source_ring -> instance, shift, account_map).
"""
import sys

import numpy as np
import pandas as pd

from aml import io
from aml.drift.schedule import TYPOLOGIES, cramers_v, make_schedule
from aml.manifest import Run, cached_or_none


class DriftGenerationError(Exception):
    """The generated set does not match the requested schedule. Never caught."""


def generate(patterns: str, dest: str, n_buckets: int = 4, magnitude: float = 1.0,
             seed: int = 0, rings_per_bucket: int | None = None,
             train_buckets: int = 2, manifest_dir: str | None = None,
             force: bool = False, tolerance: float = 0.03):
    patterns, dest = str(patterns), str(dest)
    cfg = {"patterns": patterns, "dest": dest, "n_buckets": n_buckets,
           "magnitude": magnitude, "seed": seed,
           "rings_per_bucket": rings_per_bucket, "tolerance": tolerance,
           "train_buckets": train_buckets, "drift_spec_version": "2.0.0"}

    key, hit = cached_or_none("make_drift", cfg, [patterns], (manifest_dir or dest),
                              modules=(sys.modules[__name__],), force=force)
    if hit is not None:
        return hit

    with Run("make_drift", cfg, manifest_dir or dest, key=key) as run:
        con = io.duckdb_connect((patterns, dest))
        rings = con.execute(f"SELECT * FROM '{patterns}/rings.parquet'").df()
        rtxns = con.execute(f"SELECT * FROM '{patterns}/ring_txns.parquet'").df()

        # The window we redistribute rings across is the real ring-start window.
        t0, t1 = rings.start_time.min(), rings.start_time.max()
        bucket_len = (t1 - t0) / n_buckets
        schedule = make_schedule(n_buckets, magnitude)

        if rings_per_bucket is None:
            rings_per_bucket = len(rings) // n_buckets

        # Partition each typology's source pool. Early (training) buckets draw
        # from half A, later (evaluation) buckets from half B, so no source ring
        # can appear on both sides of the eventual train/test boundary.
        split_rng = np.random.default_rng(seed)
        pools = {}          # pools[bucket][typology] -> disjoint source ring ids
        for t in TYPOLOGIES:
            ids = rings[rings.typology == t].ring_id.to_numpy()
            if len(ids) == 0:
                raise DriftGenerationError(
                    f"no source rings for typology {t!r}. The schedule asks for it, "
                    f"so we cannot honour the requested mix.")
            if len(ids) < n_buckets:
                raise DriftGenerationError(
                    f"typology {t!r} has {len(ids)} source ring(s) but {n_buckets} "
                    f"buckets need disjoint slices. Reduce --buckets or use a "
                    f"pattern file with more rings.")
            for b, slice_ids in enumerate(np.array_split(split_rng.permutation(ids),
                                                         n_buckets)):
                pools.setdefault(b, {})[t] = slice_ids

        # NOT dict(rtxns.groupby(...)): a pandas GroupBy exposes a `.keys`
        # ATTRIBUTE holding the grouping column name, so dict() treats it as a
        # mapping and raises "'str' object is not callable". Ruff's C416 unsafe
        # fix makes exactly this substitution -- caught by the drift tests.
        txns_by_ring = {rid: g for rid, g in rtxns.groupby("ring_id")}  # noqa: C416 - see above
        rng = np.random.default_rng(seed)

        inst_rows, txn_rows, acct_rows, mapping = [], [], [], []
        instance_id = 0

        for b in range(n_buckets):
            b_start = t0 + b * bucket_len
            want = schedule[b]
            # Largest-remainder allocation so the counts sum exactly to
            # rings_per_bucket. Naive rounding would drift the total.
            raw = {t: want[t] * rings_per_bucket for t in TYPOLOGIES}
            counts = {t: int(np.floor(v)) for t, v in raw.items()}
            short = rings_per_bucket - sum(counts.values())
            for t in sorted(TYPOLOGIES, key=lambda x: -(raw[x] - counts[x]))[:short]:
                counts[t] += 1

            for typ in TYPOLOGIES:
                n = counts[typ]
                if n == 0:
                    continue
                pool = pools[b][typ]
                # Without replacement inside a bucket (so one bucket never
                # contains two copies of one ring); with replacement across
                # buckets, which is what the per-instance namespace handles.
                pick = rng.choice(pool, size=min(n, len(pool)), replace=False)
                if n > len(pool):
                    pick = np.concatenate([pick, rng.choice(pool, size=n - len(pool),
                                                            replace=True)])
                for source_ring in pick:
                    g = txns_by_ring[source_ring]
                    old_start = g.event_time.min()
                    duration = g.event_time.max() - old_start
                    # Whole-day shift only: pick a target DAY inside the bucket
                    # and move the ring by (target_day - its original day). The
                    # time-of-day of every transaction is therefore unchanged.
                    days_in_bucket = max(int(bucket_len.total_seconds() // 86400), 1)
                    target_day = (b_start.normalize()
                                  + pd.Timedelta(days=int(rng.integers(0, days_in_bucket))))
                    shift = target_day - old_start.normalize()
                    new_start = old_start + shift

                    suffix = f"#{instance_id}"
                    s_ids = g.sender_id.to_numpy() + suffix
                    r_ids = g.receiver_id.to_numpy() + suffix
                    times = g.event_time + shift

                    txn_rows.append(pd.DataFrame({
                        "instance_id": instance_id, "typology": typ, "bucket": b,
                        "event_time": times, "sender_id": s_ids, "receiver_id": r_ids,
                        "amount_paid": g.amount_paid.to_numpy(),
                        "amount_received": g.amount_received.to_numpy(),
                        "payment_format": g.payment_format.to_numpy(),
                        "payment_currency": g.payment_currency.to_numpy(),
                        "receiving_currency": g.receiving_currency.to_numpy(),
                    }))
                    accounts = sorted(set(s_ids) | set(r_ids))
                    acct_rows.extend((instance_id, a) for a in accounts)
                    inst_rows.append(dict(
                        instance_id=instance_id, source_ring_id=int(source_ring),
                        side="train" if b < train_buckets else "test",
                        typology=typ, bucket=b, start_time=new_start,
                        end_time=new_start + duration, n_txns=len(g),
                        n_accounts=len(accounts),
                        duration_days=round(duration.total_seconds() / 86400, 4),
                        time_shift_sec=round(shift.total_seconds(), 3)))
                    mapping.append(dict(instance_id=instance_id,
                                        source_ring_id=int(source_ring),
                                        typology=typ, bucket=b,
                                        time_shift_sec=round(shift.total_seconds(), 3),
                                        account_suffix=suffix,
                                        n_accounts=len(accounts),
                                        side="train" if b < train_buckets else "test"))
                    instance_id += 1

        instances = pd.DataFrame(inst_rows)
        drift_txns = pd.concat(txn_rows, ignore_index=True)
        # A stable per-row sequence, assigned HERE and never re-derived.
        # splice.py needs an identity for these rows -- they are transactions
        # that exist nowhere upstream, so there is no txn_id to carry forward --
        # and the tempting way to mint one is row_number() in SQL. That is the
        # exact shape of the txn_id defect: an identity that depends on scan
        # order, which DuckDB parallelises. `txn_rows` is built in a
        # deterministic Python loop, so its concatenation order is already
        # fixed; recording it as a column makes it a fact rather than a scan
        # artifact. splice.py offsets this above the background's max txn_id.
        drift_txns["drift_txn_seq"] = range(len(drift_txns))
        drift_accounts = pd.DataFrame(acct_rows, columns=["instance_id", "account_id"])

        # ---- verify the realised mix actually matches what we asked for ----
        ct = pd.crosstab(instances.bucket, instances.typology)
        for t in TYPOLOGIES:
            if t not in ct.columns:
                ct[t] = 0
        ct = ct[TYPOLOGIES]
        realised = (ct.T / ct.sum(axis=1)).T
        worst, worst_at = 0.0, None
        for b in range(n_buckets):
            for t in TYPOLOGIES:
                d = abs(float(realised.loc[b, t]) - schedule[b][t])
                if d > worst:
                    worst, worst_at = d, (b, t)
        if worst > tolerance:
            raise DriftGenerationError(
                f"realised mix deviates from the schedule by {worst:.4f} at "
                f"bucket {worst_at[0]} / {worst_at[1]} (tolerance {tolerance}). "
                f"The generated drift is not the drift that was requested.")

        # Assert the partition held. Cheap, and it is the whole reason for it.
        crossers = int((instances.groupby("source_ring_id").bucket.nunique() > 1).sum())
        if crossers:
            raise DriftGenerationError(
                f"{crossers} source rings appear in more than one bucket. Same "
                f"amounts, same internal timing, different accounts -- a model "
                f"trained on one bucket would recognise a signature in another.")
        # Within-bucket reuse is allowed but must be visible.
        per_bucket = instances.groupby("bucket").agg(
            n=("instance_id", "size"), uniq=("source_ring_id", "nunique"))
        reuse = float((per_bucket.n / per_bucket.uniq).max())

        chi2, p, v = cramers_v(ct.to_numpy())

        io.ensure_dir(dest)
        for name, df in [("drift_rings", instances), ("drift_ring_txns", drift_txns),
                         ("drift_ring_accounts", drift_accounts)]:
            con.register("d", df)
            con.execute(f"COPY d TO '{dest}/{name}.parquet' (FORMAT PARQUET)")

        io.write_json(io.join(dest, "drift_manifest.json"), {
            "seed": seed, "magnitude": magnitude, "n_buckets": n_buckets,
            "train_buckets": train_buckets,
            "bucket_length_days": round(bucket_len.total_seconds() / 86400, 4),
            "window": [str(t0), str(t1)],
            "requested_schedule": schedule,
            "realised_mix": realised.to_dict(orient="index"),
            "max_deviation": worst,
            "chi2": chi2, "p_value": p, "cramers_v": v,
            "instances": mapping,
        }, default=str)

        run.record(
            instances=len(instances), drift_txns=len(drift_txns),
            distinct_accounts=int(drift_accounts.account_id.nunique()),
            n_buckets=n_buckets, magnitude=magnitude, train_buckets=train_buckets,
            train_instances=int((instances.side == "train").sum()),
            test_instances=int((instances.side == "test").sum()),
            source_rings_in_two_buckets=0,
            max_within_bucket_reuse=round(reuse, 2),
            distinct_source_rings=int(instances.source_ring_id.nunique()),
            bucket_length_days=round(bucket_len.total_seconds() / 86400, 4),
            max_schedule_deviation=round(worst, 5),
            chi2=round(chi2, 2), p_value=p, cramers_v=round(v, 4),
            # The whole point: the natural data measures V = 0.075.
            baseline_cramers_v_on_real_ibm_data=0.0747,
            drift_is="INDUCED, not observed",
        )
        print(io.json_line({"event": "make_drift_complete",
                          **dict(run.metrics.items())}, default=str))
        return run.metrics
