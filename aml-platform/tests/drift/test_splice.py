"""
Splice invariants.

These exist because of a bug the magnitude=0 control caught: ring accounts were
spliced in with their synthetic ids, so they appeared NOWHERE in the 31.8M-row
background. The model then scored a perfect 100% recall_efficiency -- not by
detecting laundering, but by detecting "an account I have never seen before".

Measured at the time:
    overlap between laundering and background accounts : 0
    positives with no 7-day history                    : 43.0%  (negatives: 6.9%)
    mean prior 7-day transactions, positives           : 1.78   (negatives: 17,973)
"""
import duckdb
import numpy as np
import pandas as pd
import pytest

from aml.drift.resample import generate
from aml.drift.splice import splice
from tests.drift.test_drift_generator import _fake_patterns


def _background(tmp_path, n_accounts=1500, n_days=20, seed=1):
    """Real-ish negative traffic, with far more accounts than the rings need.

    txn_id IS PART OF THE FIXTURE ON PURPOSE. reconcile_labels always emits it,
    so a background without one is not a realistic input -- and that omission
    is exactly why nothing caught splice() dropping txn_id from its output,
    which left the drift pipeline unreachable: splice succeeded and the next
    stage died on require_txn_id.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(1, n_days + 1):
        for _ in range(900):
            s, r = rng.integers(0, n_accounts, 2)
            rows.append(dict(
                event_time=pd.Timestamp("2022-09-01") + pd.Timedelta(
                    days=d - 1, minutes=int(rng.integers(0, 1440))),
                sender_bank="010", sender_account=f"BG{s:04d}",
                receiver_bank="011", receiver_account=f"BG{r:04d}",
                amount_received=float(rng.integers(10, 9999)),
                receiving_currency="US Dollar",
                amount_paid=float(rng.integers(10, 9999)),
                payment_currency="US Dollar", payment_format="ACH",
                is_laundering=0, ring_id=None, typology=None))
    df = pd.DataFrame(rows)
    df.insert(0, "txn_id", range(1, len(df) + 1))
    df["sender_id"] = df.sender_bank + "_" + df.sender_account
    df["receiver_id"] = df.receiver_bank + "_" + df.receiver_account
    df["event_date"] = df.event_time.dt.date
    d = tmp_path / "labeled"
    d.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{d}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date))")
    return str(d / "txns_labeled")


@pytest.fixture(scope="module")
def spliced(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("splice")
    pat = _fake_patterns(tmp, n_per_typology=24)
    generate(pat, tmp / "drift", n_buckets=4, magnitude=1.0, seed=0)
    lab = _background(tmp)
    m = splice(lab, tmp / "drift", tmp / "out", seed=0)
    df = duckdb.sql(
        f"SELECT * FROM read_parquet('{tmp}/out/txns_labeled/**/*.parquet')").df()
    return m, df


def test_laundering_accounts_exist_in_the_background(spliced):
    """THE regression guard. Zero overlap means positives are separable by
    identity rather than behaviour, and any model scores ~100%."""
    m, df = spliced
    pos = set(df[df.is_laundering == 1].sender_id) | set(df[df.is_laundering == 1].receiver_id)
    neg = set(df[df.is_laundering == 0].sender_id) | set(df[df.is_laundering == 0].receiver_id)
    assert len(pos & neg) / len(pos) > 0.95, \
        "laundering accounts do not appear in ordinary traffic"


def test_no_account_belongs_to_two_ring_instances(spliced):
    """Mapping onto real accounts must not undo the disjointness the
    per-instance namespace provided, or the split will drop every ring."""
    m, df = spliced
    r = df[df.ring_id.notna()]
    both = pd.concat([r[["sender_id", "ring_id"]].rename(columns={"sender_id": "a"}),
                      r[["receiver_id", "ring_id"]].rename(columns={"receiver_id": "a"})])
    assert (both.groupby("a").ring_id.nunique() > 1).sum() == 0


def test_negatives_are_untouched(spliced):
    m, df = spliced
    assert m["negatives_kept"] == int((df.is_laundering == 0).sum())


def test_every_positive_has_a_ring(spliced):
    """Unlike the real data (38% unlabeled), the drifted set is fully labeled.
    That makes it EASIER than reality in one specific way, so it is recorded
    rather than quietly assumed."""
    m, df = spliced
    assert m["positives_with_no_ring"] == 0


def test_splice_is_deterministic(tmp_path):
    pat = _fake_patterns(tmp_path, n_per_typology=24)
    generate(pat, tmp_path / "drift", n_buckets=4, magnitude=1.0, seed=0)
    lab = _background(tmp_path)
    a = splice(lab, tmp_path / "drift", tmp_path / "o1", seed=0)
    b = splice(lab, tmp_path / "drift", tmp_path / "o2", seed=0, force=True)
    assert a["positives"] == b["positives"]
    q = lambda d: duckdb.sql(
        f"SELECT sender_id FROM read_parquet('{d}/txns_labeled/**/*.parquet') "
        f"WHERE is_laundering=1 ORDER BY event_time, sender_id").df().sender_id.tolist()
    assert q(tmp_path / "o1") == q(tmp_path / "o2")


def test_too_few_real_accounts_is_rejected(tmp_path):
    """If the background cannot supply a distinct real account per ring member,
    we stop rather than silently reusing one and breaking disjointness."""
    pat = _fake_patterns(tmp_path, n_per_typology=24)
    generate(pat, tmp_path / "drift", n_buckets=4, magnitude=1.0, seed=0)
    lab = _background(tmp_path, n_accounts=12)
    with pytest.raises(ValueError, match="real accounts"):
        splice(lab, tmp_path / "drift", tmp_path / "tiny", seed=0)
