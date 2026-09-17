"""
Offline/online feature parity.

THE RISK THIS REMOVES
    features/build.py computes features for 31.9M rows in SQL window functions.
    features/online.py computes them one transaction at a time in Python,
    because a serving Lambda has no 31.9M-row table to run a window over.

    Two implementations of one definition always drift. A window bound moves in
    one and not the other; a null becomes a zero on one side; a rounding rule
    differs. The model then trains on one distribution and serves on another,
    and NOTHING FAILS -- predictions just quietly get worse. This is called
    train/serve skew and it is one of the most expensive bugs in production ML.

WHY THIS TEST IS THE DELIVERABLE
    The managed answer is SageMaker Feature Store: one implementation, served
    both ways. It costs money and adds a dependency. This test removes the same
    risk for free, and is the better thing to show someone.

TOLERANCE
    Exact for integer-valued features. 1e-9 relative for floats -- SQL and
    numpy accumulate sums in different orders, and floating-point addition is
    not associative, so bit-identity is not achievable and not required.
"""
import numpy as np
import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from aml.features.build import FEATURES, build
from aml.features.online import compute

RTOL = 1e-9

BASE = dict(receiving_currency="US Dollar", payment_currency="US Dollar",
            payment_format="ACH", is_laundering=0, ring_id=None, typology=None)


def _make_world(n_accounts=12, n_days=14, seed=0):
    """A small but structurally varied world: repeat counterparties, new
    counterparties, self-transfers, cross-bank, same-minute ties, and accounts
    that only ever receive."""
    rng = np.random.default_rng(seed)
    rows = []
    banks = ["010", "011", "0223041"]
    accts = [f"ACC{i:03d}" for i in range(n_accounts)]
    for d in range(1, n_days + 1):
        for _ in range(rng.integers(3, 8)):
            sb, rb = rng.choice(banks, 2)
            sa, ra = rng.choice(accts, 2)
            hh, mm = int(rng.integers(0, 24)), int(rng.integers(0, 60))
            amt = float(rng.choice([9000.0, 8700.0, 123.45, 1000.0,
                                    float(rng.integers(10, 99999))]))
            rows.append({**BASE, "event_time": f"2022-09-{d:02d} {hh:02d}:{mm:02d}",
                         "sender_bank": sb, "sender_account": sa,
                         "receiver_bank": rb, "receiver_account": ra,
                         "amount_paid": amt, "amount_received": amt})
    # Force same-minute ties on one account -- the case the 1-MINUTE-PRECEDING
    # frame exists for.
    for k in range(3):
        rows.append({**BASE, "event_time": "2022-09-07 12:00",
                     "sender_bank": "010", "sender_account": "ACC000",
                     "receiver_bank": "011", "receiver_account": f"ACC{k+1:03d}",
                     "amount_paid": 500.0 + k, "amount_received": 500.0 + k})
    # An account that only ever RECEIVES until the very end.
    for d in range(1, 6):
        rows.append({**BASE, "event_time": f"2022-09-{d:02d} 09:00",
                     "sender_bank": "010", "sender_account": f"ACC{d:03d}",
                     "receiver_bank": "011", "receiver_account": "MULE",
                     "amount_paid": 250.0, "amount_received": 250.0})
    rows.append({**BASE, "event_time": "2022-09-10 09:00",
                 "sender_bank": "011", "sender_account": "MULE",
                 "receiver_bank": "010", "receiver_account": "ACC000",
                 "amount_paid": 1200.0, "amount_received": 1200.0})
    # A self-transfer.
    rows.append({**BASE, "event_time": "2022-09-11 10:00",
                 "sender_bank": "010", "sender_account": "ACC002",
                 "receiver_bank": "010", "receiver_account": "ACC002",
                 "amount_paid": 777.0, "amount_received": 777.0})

    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df.event_time)
    df["event_date"] = df.event_time.dt.date
    df["sender_id"] = df.sender_bank + "_" + df.sender_account
    df["receiver_id"] = df.receiver_bank + "_" + df.receiver_account
    df = df.sort_values(["event_time", "sender_id", "receiver_id"]).reset_index(drop=True)
    # Mirrors ingest: identity assigned once, in row order. Because this frame
    # is sorted first, txn_id - 1 indexes it -- which the parity test asserts
    # rather than assumes, so a change here fails loudly.
    df.insert(0, "txn_id", range(1, len(df) + 1))
    return df


def _history_for(df, account_id, upto):
    """Every prior event for one account, in the shape online.compute expects.
    Two-sided: an account accumulates history from receiving as well as sending."""
    out = []
    s = df[(df.sender_id == account_id) & (df.event_time <= upto)]
    for r in s.itertuples():
        out.append({"event_time": r.event_time, "amount_paid": r.amount_paid,
                    "counterparty": r.receiver_id, "is_out": 1})
    r_ = df[(df.receiver_id == account_id) & (df.event_time <= upto)]
    for r in r_.itertuples():
        out.append({"event_time": r.event_time, "amount_paid": r.amount_paid,
                    "counterparty": r.sender_id, "is_out": 0})
    return out


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("parity")
    df = _make_world()
    src = tmp / "labeled"
    src.mkdir()
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{src}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date))")
    build(str(src / "txns_labeled"), tmp / "feat")
    offline = duckdb.sql(
        f"SELECT * FROM read_parquet('{tmp}/feat/**/*.parquet') ORDER BY txn_id").df()
    return df, offline


def test_the_fixture_actually_exercises_the_edge_cases(world):
    """If the fixture had no ties, no mule and no self-transfer, parity would
    hold trivially and prove nothing."""
    df, off = world
    assert (df.event_time.duplicated().sum()) > 0, "no same-minute ties in fixture"
    assert (df.sender_id == df.receiver_id).sum() > 0, "no self-transfer"
    assert off.s_n_7d.isna().sum() + (off.s_n_7d == 0).sum() > 0, "no cold-start rows"
    assert off.s_secs_since_prev_cp.isna().sum() > 0, "no new-counterparty rows"


def test_offline_and_online_agree_on_every_row(world):
    """The load-bearing parity assertion, over every transaction in the world."""
    df, off = world
    mismatches = []

    # txn_id is row_number() over (event_time, sender_id, receiver_id) and df is
    # sorted identically, so txn_id-1 indexes df. Asserted, not assumed.
    for row in off.itertuples():
        src = df.iloc[row.txn_id - 1]
        assert src.sender_id == row.sender_id and src.event_time == row.event_time, \
            "txn_id does not line up with the source frame"
        txn = {
            "event_time": row.event_time,
            "sender_bank": src.sender_bank, "sender_account": src.sender_account,
            "receiver_bank": src.receiver_bank, "receiver_account": src.receiver_account,
            "amount_paid": float(src.amount_paid),
            "amount_received": float(src.amount_received),
            "payment_currency": src.payment_currency,
            "receiving_currency": src.receiving_currency,
            "payment_format": src.payment_format,
        }
        sh = _history_for(df, row.sender_id, row.event_time)
        rh = _history_for(df, row.receiver_id, row.event_time)
        online = compute(txn, sh, rh)

        for f in FEATURES:
            a, b = getattr(row, f), online[f]
            a = np.nan if a is None else float(a)
            b = np.nan if b is None else float(b)
            if np.isnan(a) and np.isnan(b):
                continue
            if np.isnan(a) != np.isnan(b):
                mismatches.append((row.txn_id, f, a, b, "null mismatch"))
            elif not np.isclose(a, b, rtol=RTOL, atol=1e-6):
                mismatches.append((row.txn_id, f, a, b, "value mismatch"))

    assert not mismatches, (
        f"{len(mismatches)} offline/online mismatches (showing 10):\n" +
        "\n".join(f"  txn {t} {f}: batch={a!r} serving={b!r} ({why})"
                  for t, f, a, b, why in mismatches[:10]))


def test_online_vector_is_ordered_like_the_model_expects(world):
    """compute_vector must emit features in FEATURES order. If serving reordered
    them, every prediction would be garbage and nothing would raise."""
    from aml.features.online import compute_vector
    df, off = world
    row = off.iloc[5]
    src = df.iloc[row.txn_id - 1]
    txn = {"event_time": row.event_time,
           "sender_bank": src.sender_bank, "sender_account": src.sender_account,
           "receiver_bank": src.receiver_bank, "receiver_account": src.receiver_account,
           "amount_paid": float(src.amount_paid),
           "amount_received": float(src.amount_received),
           "payment_currency": src.payment_currency,
           "receiving_currency": src.receiving_currency,
           "payment_format": src.payment_format}
    v = compute_vector(txn, _history_for(df, row.sender_id, row.event_time),
                       _history_for(df, row.receiver_id, row.event_time))
    assert v.shape == (len(FEATURES),)
    assert v.dtype == np.float32
