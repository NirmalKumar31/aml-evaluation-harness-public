"""
Invariants for the manufactured-drift generator.

The whole value of induced drift is that the ground truth is EXACT. That is
only true if the generator preserves what it claims to preserve. These tests
are what make "exact by construction" a fact rather than a hope.

Five invariants, from AML_PROJECT_KNOWLEDGE.md 7.3:
  1. every emitted ring is internally intact -- same transaction count, same
     relative timing, same typology as its source
  2. no account id appears in two ring instances
  3. rings are assigned to a bucket by START time, and that rule holds
  4. the realised typology mix matches the schedule within tolerance, and the
     resulting Cramer's V is LARGE compared to the 0.075 measured on real data
  5. the same seed reproduces byte-identical output
"""
import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from aml.drift.resample import DriftGenerationError, generate
from aml.drift.schedule import STATIONARY, TYPOLOGIES, make_schedule

# Measured on the real HI-Large pattern file. The number this project exists to
# beat: statistically overwhelming, practically negligible.
REAL_IBM_CRAMERS_V = 0.0747


def _fake_patterns(tmp_path, n_per_typology=14, seed=0):
    """A small pattern set with every typology and varied ring shapes."""
    rng = np.random.default_rng(seed)
    rings, txns, accts = [], [], []
    rid = 0
    for typ in TYPOLOGIES:
        for _k in range(n_per_typology):
            n_txn = int(rng.integers(2, 9))
            start = pd.Timestamp("2022-09-01") + pd.Timedelta(days=float(rng.uniform(0, 20)))
            offsets = np.sort(rng.uniform(0, 4, size=n_txn))
            accounts = set()
            for i, off in enumerate(offsets):
                s, r = f"010_R{rid}A{i}", f"011_R{rid}B{i}"
                accounts |= {s, r}
                txns.append(dict(ring_id=rid, typology=typ,
                                 event_time=start + pd.Timedelta(days=float(off)),
                                 sender_id=s, receiver_id=r,
                                 amount_paid=float(rng.integers(100, 9999)),
                                 amount_received=float(rng.integers(100, 9999)),
                                 payment_format="ACH",
                                 payment_currency="US Dollar",
                                 receiving_currency="US Dollar"))
            rings.append(dict(ring_id=rid, typology=typ, subtitle="", n_txns=n_txn,
                              n_accounts=len(accounts), start_time=start,
                              end_time=start + pd.Timedelta(days=float(offsets[-1])),
                              duration_days=float(offsets[-1])))
            accts.extend(dict(ring_id=rid, account_id=a) for a in sorted(accounts))
            rid += 1

    d = tmp_path / "patterns"
    d.mkdir(exist_ok=True)
    con = duckdb.connect()
    for name, df in [("rings", pd.DataFrame(rings)), ("ring_txns", pd.DataFrame(txns)),
                     ("ring_accounts", pd.DataFrame(accts))]:
        con.register("df", df)
        con.execute(f"COPY df TO '{d}/{name}.parquet' (FORMAT PARQUET)")
    return str(d)


def _load(dest):
    q = lambda n: duckdb.sql(f"SELECT * FROM '{dest}/{n}.parquet'").df()
    return (q("drift_rings"), q("drift_ring_txns"), q("drift_ring_accounts"),
            json.loads((dest / "drift_manifest.json").read_text())
            if hasattr(dest, "read_text") else
            json.loads(open(f"{dest}/drift_manifest.json").read()))


# ---------------------------------------------------------------- the schedule

def test_magnitude_zero_is_stationary():
    """The control. If magnitude 0 drifted, every 'no drift' comparison would
    be meaningless."""
    for bucket in make_schedule(4, magnitude=0.0):
        for t in TYPOLOGIES:
            assert bucket[t] == pytest.approx(STATIONARY[t], abs=1e-12)


def test_magnitude_one_reaches_the_target_regime():
    sched = make_schedule(4, magnitude=1.0)
    assert sched[0]["CYCLE"] == pytest.approx(0.125, abs=1e-12)   # stable early
    assert sched[3]["CYCLE"] == pytest.approx(0.40, abs=0.01)     # taken over late
    assert sched[3]["FAN-OUT"] < 0.05


def test_every_bucket_sums_to_one():
    for m in (0.0, 0.25, 0.5, 0.75, 1.0):
        for bucket in make_schedule(4, magnitude=m):
            assert sum(bucket.values()) == pytest.approx(1.0, abs=1e-9)


def test_magnitude_outside_zero_one_is_rejected():
    with pytest.raises(ValueError):
        make_schedule(4, magnitude=1.5)


# ---------------------------------------------------------------- invariant 1

def test_rings_are_internally_intact(tmp_path):
    """Same transaction count, same typology, and the same INTERNAL timing as
    the source ring. If the generator distorted rings, the drift experiment
    would be measuring the distortion rather than the mix."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    inst, txns, _, man = _load(tmp_path / "d")

    src_txns = duckdb.sql(f"SELECT * FROM '{pat}/ring_txns.parquet'").df()
    by_src = {r: g.sort_values("event_time") for r, g in src_txns.groupby("ring_id")}

    for row in inst.itertuples():
        g = txns[txns.instance_id == row.instance_id].sort_values("event_time")
        src = by_src[row.source_ring_id]

        assert len(g) == len(src), "transaction count changed"
        assert row.typology == src.typology.iloc[0], "typology changed"

        # Relative timing: the gaps between consecutive transactions must be
        # identical, even though every absolute time moved.
        got = np.diff(g.event_time.to_numpy()).astype("timedelta64[s]").astype(float)
        want = np.diff(src.event_time.to_numpy()).astype("timedelta64[s]").astype(float)
        np.testing.assert_allclose(got, want, atol=1e-6,
                                   err_msg="internal ring timing was distorted")

        # Amounts travel untouched.
        np.testing.assert_allclose(np.sort(g.amount_paid.to_numpy()),
                                   np.sort(src.amount_paid.to_numpy()))


def test_rings_actually_moved(tmp_path):
    """Control for the test above: if nothing were shifted, timing would be
    trivially preserved and the test would prove nothing."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    inst, _, _, _ = _load(tmp_path / "d")
    assert (inst.time_shift_sec.abs() > 3600).mean() > 0.8, "rings were barely moved"


# ---------------------------------------------------------------- invariant 2

def test_no_account_appears_in_two_instances(tmp_path):
    """The same source ring can be sampled into several buckets. Without a
    per-instance namespace the copies would share accounts, and the split's
    ring-participant-disjointness rule would correctly delete all of them."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    _, _, accts, _ = _load(tmp_path / "d")
    dupes = accts.groupby("account_id").instance_id.nunique()
    assert (dupes > 1).sum() == 0, f"{(dupes > 1).sum()} accounts span two instances"


def test_source_rings_are_reused_within_a_bucket(tmp_path):
    """Control for the account-namespace test: if no source ring were ever
    reused at all, "no account spans two instances" would hold trivially.

    Reuse is now confined to WITHIN a bucket (cross-bucket reuse would leak a
    behavioural signature -- see test_no_source_ring_appears_in_two_buckets),
    so this asserts the remaining, harmless kind still occurs."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    inst, _, _, _ = _load(tmp_path / "d")
    within = inst.groupby(["bucket", "source_ring_id"]).size()
    assert (within > 1).sum() > 0, "no source ring was reused within any bucket"


# ---------------------------------------------------------------- invariant 3

def test_bucket_assignment_follows_start_time(tmp_path):
    """Documented rule: a ring belongs to the bucket its START falls in, even
    if it runs on into the next one. Truncating instead would change ring
    shape, which is the thing being measured.

    Tolerance is one day because shifts are quantised to whole days (to preserve
    time-of-day -- see resample.py), while bucket edges fall at fractional days.
    A ring placed on the last day of a bucket can therefore start up to a day
    past the nominal edge."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    inst, _, _, man = _load(tmp_path / "d")
    t0 = pd.Timestamp(man["window"][0])
    blen = pd.Timedelta(days=man["bucket_length_days"])
    for row in inst.itertuples():
        lo = t0 + row.bucket * blen
        hi = lo + blen
        assert lo - pd.Timedelta(days=1) <= pd.Timestamp(row.start_time) \
               <= hi + pd.Timedelta(days=1)


# ---------------------------------------------------------------- invariant 4

def test_realised_mix_matches_the_schedule(tmp_path):
    pat = _fake_patterns(tmp_path)
    m = generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    assert m["max_schedule_deviation"] < 0.03


def test_induced_drift_dwarfs_the_natural_drift(tmp_path):
    """The headline claim of Phase 6: real IBM data has Cramer's V = 0.075
    (negligible). Ours must be far larger, or we have not induced anything."""
    pat = _fake_patterns(tmp_path)
    m = generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    assert m["cramers_v"] > 3 * REAL_IBM_CRAMERS_V


def test_the_control_produces_no_drift(tmp_path):
    """magnitude=0 must be statistically indistinguishable from stationary.
    Without this, a measured 'decay' could be an artefact of resampling itself
    rather than of the mix changing."""
    pat = _fake_patterns(tmp_path)
    m = generate(pat, tmp_path / "d0", n_buckets=4, magnitude=0.0, seed=0)
    assert m["cramers_v"] < REAL_IBM_CRAMERS_V, \
        f"the magnitude=0 control drifted (V={m['cramers_v']})"


def test_cramers_v_rises_with_magnitude(tmp_path):
    """The knob has to actually turn, or the sensitivity curve is meaningless."""
    pat = _fake_patterns(tmp_path)
    vs = [generate(pat, tmp_path / f"m{i}", n_buckets=4, magnitude=m, seed=0)["cramers_v"]
          for i, m in enumerate((0.0, 0.5, 1.0))]
    assert vs[0] < vs[1] < vs[2], f"Cramer's V not monotone in magnitude: {vs}"


# ---------------------------------------------------------------- invariant 5

def test_same_seed_is_byte_identical(tmp_path):
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "a", n_buckets=4, magnitude=1.0, seed=7)
    generate(pat, tmp_path / "b", n_buckets=4, magnitude=1.0, seed=7)
    a, b = (tmp_path / "a" / "drift_ring_txns.parquet").read_bytes(), \
           (tmp_path / "b" / "drift_ring_txns.parquet").read_bytes()
    assert a == b, "same seed produced different output"


def test_a_different_seed_gives_different_output(tmp_path):
    """Control for the test above."""
    pat = _fake_patterns(tmp_path)
    generate(pat, tmp_path / "a", n_buckets=4, magnitude=1.0, seed=7)
    generate(pat, tmp_path / "c", n_buckets=4, magnitude=1.0, seed=8)
    assert (tmp_path / "a" / "drift_ring_txns.parquet").read_bytes() != \
           (tmp_path / "c" / "drift_ring_txns.parquet").read_bytes()


# ---------------------------------------------------------------- failure modes

def test_a_missing_typology_is_rejected(tmp_path):
    """If the source pool lacks a typology the schedule asks for, we cannot
    honour the schedule -- so we stop rather than silently emit a different mix."""
    pat = _fake_patterns(tmp_path)
    con = duckdb.connect()
    r = con.execute(f"SELECT * FROM '{pat}/rings.parquet'").df()
    r = r[r.typology != "CYCLE"]
    con.register("d", r)
    con.execute(f"COPY d TO '{pat}/rings.parquet' (FORMAT PARQUET)")
    with pytest.raises(DriftGenerationError, match="no source rings"):
        generate(pat, tmp_path / "bad", n_buckets=4, magnitude=1.0, seed=0, force=True)


def test_manifest_records_every_instance(tmp_path):
    """Exact ground truth means the mapping is written down, not just computed."""
    pat = _fake_patterns(tmp_path)
    m = generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    man = json.loads((tmp_path / "d" / "drift_manifest.json").read_text())
    assert len(man["instances"]) == m["instances"]
    one = man["instances"][0]
    for field in ("instance_id", "source_ring_id", "typology", "bucket",
                  "time_shift_sec", "account_suffix"):
        assert field in one
    assert man["seed"] == 0 and man["magnitude"] == 1.0


def test_no_source_ring_appears_in_two_buckets(tmp_path):
    """Stronger than the account-namespace rule. Two instances of one source
    ring have different accounts but IDENTICAL amounts and internal timing, so
    a model trained on bucket 2 would recognise the signature in bucket 3.
    The retraining strategies train on one bucket to predict the next, so the
    slices must be disjoint bucket-to-bucket, not merely train-vs-test."""
    pat = _fake_patterns(tmp_path, n_per_typology=24)
    generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    inst, _, _, _ = _load(tmp_path / "d")
    crossers = (inst.groupby("source_ring_id").bucket.nunique() > 1).sum()
    assert crossers == 0, f"{crossers} source rings span two buckets"


def test_too_few_source_rings_for_the_bucket_count_is_rejected(tmp_path):
    """Disjoint slices are impossible below n_buckets rings per typology, so we
    stop rather than silently reusing rings across buckets."""
    pat = _fake_patterns(tmp_path, n_per_typology=3)
    with pytest.raises(DriftGenerationError, match="disjoint slices"):
        generate(pat, tmp_path / "bad", n_buckets=4, magnitude=1.0, seed=0)


def test_within_bucket_reuse_is_reported(tmp_path):
    """Reuse inside a bucket is allowed -- it costs effective sample size, not
    correctness -- but it must be visible in the manifest, not hidden."""
    pat = _fake_patterns(tmp_path, n_per_typology=24)
    m = generate(pat, tmp_path / "d", n_buckets=4, magnitude=1.0, seed=0)
    assert "max_within_bucket_reuse" in m and m["max_within_bucket_reuse"] >= 1.0
