"""
Causality tests: prove no feature can see the future.

Method: plant an enormous transaction in the FUTURE, then check that features
on EARLIER rows are unchanged. If any earlier row's history moves, that feature
is reading forward in time and every metric built on it is inflated.

The second test is the subtle one. Timestamps are minute-resolution, so
transactions routinely share an event_time. A window ending at CURRENT ROW
would let a transaction see its own siblings -- information nobody has at
decision time. Our frames end at INTERVAL 1 MINUTE PRECEDING to exclude them.
"""
import duckdb
import pandas as pd

from aml.features.build import FEATURES, build

BASE = dict(sender_bank="010", sender_account="A", receiver_bank="011",
            receiver_account="B", amount_received=100.0, receiving_currency="US Dollar",
            payment_currency="US Dollar", payment_format="ACH", is_laundering=0,
            ring_id=None, typology=None)


def _write(tmp_path, rows, name="labeled"):
    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df.event_time)
    df["event_date"] = df.event_time.dt.date
    df["sender_id"] = df.sender_bank + "_" + df.sender_account
    df["receiver_id"] = df.receiver_bank + "_" + df.receiver_account
    # Mirrors ingest: txn_id is assigned once, in row order, 1..N. build() reads
    # it and refuses to run without it, so fixtures must supply it too.
    df.insert(0, "txn_id", range(1, len(df) + 1))
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{d}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date))")
    return str(d / "txns_labeled")


def _feats(tmp_path, rows, out):
    src = _write(tmp_path, rows, name=f"in_{out}")
    build(src, tmp_path / out)
    return duckdb.sql(
        f"SELECT * FROM read_parquet('{tmp_path}/{out}/**/*.parquet') ORDER BY event_time"
    ).df()


def test_a_planted_future_outlier_does_not_change_the_past(tmp_path):
    """The load-bearing causality test."""
    hist = [{**BASE, "event_time": f"2022-09-0{d} 10:00", "amount_paid": 100.0}
            for d in range(1, 6)]

    without = _feats(tmp_path, hist, "a")
    # Same history, plus a 10-million transaction two days AFTER the last row.
    with_future = _feats(tmp_path, [*hist, {**BASE, "event_time": "2022-09-07 10:00", "amount_paid": 10000000.0}], "b")

    past = with_future[with_future.event_time < pd.Timestamp("2022-09-07")]
    cols = [c for c in FEATURES if c in without.columns]
    pd.testing.assert_frame_equal(
        without[cols].reset_index(drop=True), past[cols].reset_index(drop=True),
        check_dtype=False,
        obj="features on past rows changed when a future row was added -> LEAKAGE")


def test_the_future_row_itself_does_see_the_past(tmp_path):
    """Control: if history never moved at all, the test above would be vacuous
    because the features would simply be broken."""
    rows = [{**BASE, "event_time": f"2022-09-0{d} 10:00", "amount_paid": 100.0}
            for d in range(1, 6)]
    f = _feats(tmp_path, rows, "c")
    assert f.s_n_7d.iloc[0] == 0      # first ever transaction: no history
    assert f.s_n_7d.iloc[-1] == 4     # last one has seen the other four
    assert f.s_max_amt_30d.iloc[-1] == 100.0


def test_same_minute_siblings_are_invisible_to_each_other(tmp_path):
    """Minute-resolution timestamps mean ties are common. A transaction must
    not see another transaction from its own minute."""
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0},
            {**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 999_999.0},
            {**BASE, "event_time": "2022-09-01 10:01", "amount_paid": 100.0}]
    f = _feats(tmp_path, rows, "d")
    same_minute = f[f.event_time == pd.Timestamp("2022-09-01 10:00")]
    assert (same_minute.s_n_1d == 0).all(), "a transaction saw its own minute"
    assert same_minute.s_max_amt_30d.isna().all()
    # The 10:01 row is strictly later, so it sees both.
    later = f[f.event_time == pd.Timestamp("2022-09-01 10:01")].iloc[0]
    assert later.s_n_1d == 2 and later.s_max_amt_30d == 999_999.0


def test_history_is_two_sided(tmp_path):
    """An account that only ever RECEIVES must still accumulate history --
    otherwise every mule account looks brand new forever."""
    # NOTE the banks. Identity is (bank, account), so the MULE that receives at
    # bank 011 must SEND from bank 011 to be the same account. An earlier
    # version of this test had it receiving at 011 and sending from 010, and
    # correctly got zero history -- those are two different real-world accounts.
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0,
             "sender_account": f"S{i}", "receiver_bank": "011",
             "receiver_account": "MULE"} for i in range(4)]
    rows.append({**BASE, "event_time": "2022-09-02 10:00", "amount_paid": 100.0,
                 "sender_bank": "011", "sender_account": "MULE",
                 "receiver_bank": "012", "receiver_account": "OUT"})
    f = _feats(tmp_path, rows, "e")
    mule_sends = f[f.sender_id == "011_MULE"].iloc[0]
    assert mule_sends.s_n_7d == 4, "receiving activity was not counted as history"


def test_same_account_number_at_different_banks_shares_no_history(tmp_path):
    """The composite-key rule, enforced end-to-end through the feature layer."""
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0,
             "sender_bank": "010", "sender_account": "X"},
            {**BASE, "event_time": "2022-09-02 10:00", "amount_paid": 100.0,
             "sender_bank": "011", "sender_account": "X"}]
    f = _feats(tmp_path, rows, "g")
    assert f[f.sender_id == "011_X"].iloc[0].s_n_7d == 0


def test_new_counterparty_is_null_and_repeat_is_not(tmp_path):
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0,
             "receiver_account": "B"},
            {**BASE, "event_time": "2022-09-02 10:00", "amount_paid": 100.0,
             "receiver_account": "C"},
            {**BASE, "event_time": "2022-09-03 10:00", "amount_paid": 100.0,
             "receiver_account": "B"}]
    f = _feats(tmp_path, rows, "f")
    assert pd.isna(f.s_secs_since_prev_cp.iloc[0])       # never seen B
    assert pd.isna(f.s_secs_since_prev_cp.iloc[1])       # never seen C
    assert f.s_secs_since_prev_cp.iloc[2] == 2 * 86400   # seen B two days ago


def test_split_row_order_is_deterministic(tmp_path):
    """Regression guard for a silent correctness bug.

    DuckDB parallelises scans, so the same query returned the same rows in a
    different order on every run. Scores saved positionally against one
    ordering and re-read against another were matched to the WRONG rows, which
    shows up as ROC-AUC 0.49 -- indistinguishable from "the model doesn't work"
    rather than "the harness is broken".
    """
    import hashlib
    import json as _json

    import duckdb as _duck

    from aml.models.train import load_split

    rows = [{**BASE, "event_time": f"2022-09-{d:02d} 10:00", "amount_paid": 100.0,
             "sender_account": f"S{d}"} for d in range(1, 15)]
    src = _write(tmp_path, rows, name="in_det")
    build(src, tmp_path / "feat")

    splits = tmp_path / "splits"
    splits.mkdir()
    (splits / "manifest.json").write_text(_json.dumps({"config": {"cut_time": "2022-09-07"}}))
    _duck.connect().execute(
        f"COPY (SELECT 0 AS ring_id WHERE false) TO '{splits}/test_rings.parquet' (FORMAT PARQUET)")

    sigs = set()
    for _ in range(3):
        _, te = load_split(str(tmp_path / "feat"), str(splits))
        sigs.add(hashlib.sha256(te.txn_id.to_numpy().tobytes()).hexdigest())
    assert len(sigs) == 1, "load_split returned rows in a different order across calls"


# ---------------------------------------------------------------------------
# Graph features: do they mean what the names claim?
#
# The tests above prove these cannot see the future. That is necessary and not
# sufficient -- a feature can be perfectly causal and still count the wrong
# thing. These pin the semantics.
# ---------------------------------------------------------------------------

def test_distinct_counterparty_degree_counts_distinct_not_total(tmp_path):
    """Send to B, C, then B again. Degree is 2, not 3."""
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0,
             "receiver_account": "B"},
            {**BASE, "event_time": "2022-09-02 10:00", "amount_paid": 100.0,
             "receiver_account": "C"},
            {**BASE, "event_time": "2022-09-03 10:00", "amount_paid": 100.0,
             "receiver_account": "B"},
            {**BASE, "event_time": "2022-09-04 10:00", "amount_paid": 100.0,
             "receiver_account": "D"}]
    f = _feats(tmp_path, rows, "gdeg")

    # Degree BEFORE each transaction: 0 seen, then B, then B+C, then B+C.
    assert f.s_n_distinct_cp_ever.tolist() == [0, 1, 2, 2]


def test_a_returning_counterparty_is_not_new(tmp_path):
    """The subtle one. `n_new_cp_7d` counts FIRST CONTACTS inside the window,
    not distinct counterparties in the window. A party first seen long ago and
    reappearing this week is not new -- which is the whole point of the
    feature, and the thing a flattened implementation gets wrong."""
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0,
             "receiver_account": "OLD"}]
    # ...30 days later, OLD comes back, and NEW appears for the first time.
    rows += [{**BASE, "event_time": "2022-10-01 10:00", "amount_paid": 100.0,
              "receiver_account": "OLD"},
             {**BASE, "event_time": "2022-10-02 10:00", "amount_paid": 100.0,
              "receiver_account": "NEW"},
             {**BASE, "event_time": "2022-10-03 10:00", "amount_paid": 100.0,
              "receiver_account": "X"}]
    f = _feats(tmp_path, rows, "gnew").reset_index(drop=True)

    last = f.iloc[-1]
    # In the 7d window before 10-03: the OLD revisit (not new) and NEW (new).
    assert last.s_n_7d == 2
    assert last.s_n_new_cp_7d == 1, "a returning counterparty was counted as new"
    assert last.s_new_cp_rate_7d == 0.5
    # But degree over ALL history counts OLD and NEW: 2 distinct so far.
    assert last.s_n_distinct_cp_ever == 2


def test_out_share_separates_a_pure_sender_from_a_pure_receiver(tmp_path):
    """out_share_7d is the FAN-IN / FAN-OUT direction signal: 1.0 = only sent,
    0.0 = only received."""
    rows = [{**BASE, "event_time": f"2022-09-0{d} 10:00", "amount_paid": 100.0,
             "sender_bank": "010", "sender_account": "HUB",
             "receiver_bank": "011", "receiver_account": f"OUT{d}"}
            for d in range(1, 5)]
    rows += [{**BASE, "event_time": f"2022-09-0{d} 11:00", "amount_paid": 100.0,
              "sender_bank": "012", "sender_account": f"IN{d}",
              "receiver_bank": "013", "receiver_account": "SINK"}
             for d in range(1, 5)]
    f = _feats(tmp_path, rows, "gdir")

    hub = f[f.sender_id == "010_HUB"].iloc[-1]      # only ever sends
    sink = f[f.receiver_id == "013_SINK"].iloc[-1]  # only ever receives
    assert hub.s_out_share_7d == 1.0
    assert sink.r_out_share_7d == 0.0
    assert hub.s_n_in_7d == 0
    assert sink.r_n_in_7d > 0


def test_cold_start_gives_zero_counts_but_null_rates(tmp_path):
    """An account's first ever transaction has no history. Counts are KNOWN to
    be zero; rates are genuinely undefined and must stay NULL so the GBDT gets
    its own branch rather than a fabricated 0.0."""
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": 100.0}]
    f = _feats(tmp_path, rows, "gcold").iloc[0]

    assert f.s_n_in_7d == 0
    assert f.s_n_new_cp_7d == 0
    assert f.s_n_distinct_cp_ever == 0
    assert pd.isna(f.s_out_share_7d)
    assert pd.isna(f.s_new_cp_rate_7d)
