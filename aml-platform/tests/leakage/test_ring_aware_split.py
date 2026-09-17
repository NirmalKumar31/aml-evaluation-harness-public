"""
Leakage tests -- the load-bearing tests of the whole project.

We build a tiny world with a leak deliberately planted in it, then check the
split removes it. A split that merely *passes* its own assertion proves nothing:
a broken detector also passes. So each test here first shows the leak EXISTS,
then shows the split removes it.

The planted world (cut = 2022-09-10):

  ring 0  starts 09-01, ends 09-12   accounts A,B   <- STRADDLES the cut
  ring 1  starts 09-11               accounts C,D   <- clean test ring
  ring 2  starts 09-12               accounts B,E   <- shares B with ring 0

  correct outcome:
    train        = ring 0
    test kept    = ring 1
    test dropped = ring 2            (account B is in a training ring)
    ring 0's 09-12 transaction must NOT appear in test (straddling tail)
"""
import duckdb
import pandas as pd
import pytest

from aml.splits.ring_aware import LeakageError, build, sweep

CUT = "2022-09-10"

# (ring_id, typology, sender, receiver, day)
RING_TXNS = [
    (0, "FAN-OUT", "A", "B", "2022-09-01"),
    (0, "FAN-OUT", "A", "B", "2022-09-05"),
    (0, "FAN-OUT", "A", "B", "2022-09-12"),   # <- the straddling tail
    (1, "CYCLE",   "C", "D", "2022-09-11"),
    (1, "CYCLE",   "C", "D", "2022-09-13"),
    (2, "STACK",   "B", "E", "2022-09-12"),   # <- B is also in ring 0
    (2, "STACK",   "B", "E", "2022-09-14"),
]


def _world(tmp_path):
    """Write the synthetic patterns + labeled-transaction tables to disk."""
    rt = pd.DataFrame(RING_TXNS, columns=["ring_id", "typology", "s", "r", "day"])
    rt["event_time"] = pd.to_datetime(rt.day)

    rings = rt.groupby(["ring_id", "typology"]).agg(
        start_time=("event_time", "min"), end_time=("event_time", "max"),
        n_txns=("s", "size")).reset_index()
    rings["subtitle"] = ""
    rings["n_accounts"] = 2
    rings["duration_days"] = (rings.end_time - rings.start_time).dt.days

    ra = pd.concat([rt[["ring_id", "s"]].rename(columns={"s": "account_id"}),
                    rt[["ring_id", "r"]].rename(columns={"r": "account_id"})]).drop_duplicates()

    # Laundering rows, plus clean background so account-days exist on both sides.
    rows = [dict(event_time=t.event_time, sender_id=t.s, receiver_id=t.r,
                 is_laundering=1, ring_id=t.ring_id, typology=t.typology)
            for t in rt.itertuples()]
    for d in pd.date_range("2022-09-01", "2022-09-15"):
        for i in range(20):
            rows.append(dict(event_time=d, sender_id=f"N{i}", receiver_id=f"M{i}",
                             is_laundering=0, ring_id=None, typology=None))
    L = pd.DataFrame(rows)
    L["event_date"] = L.event_time.dt.date
    L["amount_paid"] = 100.0

    pat, lab = tmp_path / "patterns", tmp_path / "labeled"
    pat.mkdir()
    lab.mkdir()
    con = duckdb.connect()
    for name, df in [("rings", rings), ("ring_accounts", ra)]:
        con.register("d", df)
        con.execute(f"COPY d TO '{pat}/{name}.parquet' (FORMAT PARQUET)")
    con.register("d", L)
    con.execute(f"COPY d TO '{lab}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date))")
    return str(pat), str(lab)


# ---------------------------------------------------------------- the leak exists

def test_the_planted_leak_is_really_there(tmp_path):
    """Sanity check on the fixture: a NAIVE temporal split genuinely leaks.
    If this ever fails, every test below is vacuous."""
    pat, lab = _world(tmp_path)
    con = duckdb.connect()
    ra = con.execute(f"SELECT * FROM '{pat}/ring_accounts.parquet'").df()
    rings = con.execute(f"SELECT * FROM '{pat}/rings.parquet'").df()

    train_ids = set(rings[rings.start_time < CUT].ring_id)
    test_ids = set(rings[rings.start_time >= CUT].ring_id)
    train_acc = set(ra[ra.ring_id.isin(train_ids)].account_id)
    test_acc = set(ra[ra.ring_id.isin(test_ids)].account_id)

    assert train_acc & test_acc == {"B"}       # account B is on both sides
    # ...and ring 0 straddles, so a plain time cut also splits it in half
    r0 = rings[rings.ring_id == 0].iloc[0]
    assert r0.start_time < pd.Timestamp(CUT) <= r0.end_time


# ---------------------------------------------------------------- the split removes it

@pytest.fixture
def result(tmp_path):
    pat, lab = _world(tmp_path)
    m = build(pat, lab, CUT, tmp_path / "split", min_test_positives=1)
    return m, tmp_path


def test_shared_account_ring_is_dropped(result):
    m, _ = result
    assert m["train_rings"] == 1
    assert m["test_rings_before_drop"] == 2
    assert m["dropped_rings"] == 1          # ring 2, for sharing account B
    assert m["test_rings_kept"] == 1        # ring 1 survives
    assert m["overlap_accounts"] == 1


def test_straddling_ring_tail_is_removed_from_test(result):
    """Ring 0 is a TRAINING ring with a transaction on 09-12. That transaction
    sits in the test window but must not be in the test set -- the model has
    already been trained on that ring."""
    m, tmp = result
    n = duckdb.sql(f"""SELECT count(*) FROM read_parquet('{tmp}/split/test/**/*.parquet')
                       WHERE ring_id = 0""").fetchone()[0]
    assert n == 0


def test_no_account_appears_on_both_sides(result):
    m, tmp = result
    tr = duckdb.sql(f"""SELECT DISTINCT sender_id a FROM read_parquet('{tmp}/split/train/**/*.parquet')
                        WHERE ring_id IS NOT NULL
                        UNION SELECT DISTINCT receiver_id FROM read_parquet('{tmp}/split/train/**/*.parquet')
                        WHERE ring_id IS NOT NULL""").df().a
    te = duckdb.sql(f"""SELECT DISTINCT sender_id a FROM read_parquet('{tmp}/split/test/**/*.parquet')
                        WHERE ring_id IS NOT NULL
                        UNION SELECT DISTINCT receiver_id FROM read_parquet('{tmp}/split/test/**/*.parquet')
                        WHERE ring_id IS NOT NULL""").df().a
    assert set(tr) & set(te) == set()
    assert set(tr) == {"A", "B"} and set(te) == {"C", "D"}


def test_no_transaction_crosses_the_cut(result):
    m, tmp = result
    late = duckdb.sql(f"""SELECT count(*) FROM read_parquet('{tmp}/split/train/**/*.parquet')
                          WHERE event_time >= TIMESTAMP '{CUT}'""").fetchone()[0]
    early = duckdb.sql(f"""SELECT count(*) FROM read_parquet('{tmp}/split/test/**/*.parquet')
                           WHERE event_time < TIMESTAMP '{CUT}'""").fetchone()[0]
    assert late == 0 and early == 0


def test_all_four_assertions_are_recorded(result):
    m, _ = result
    assert m["assertions_passed"] == ["accounts_disjoint", "rings_disjoint",
                                      "no_temporal_bleed", "no_train_ring_tails_in_test"]


# ---------------------------------------------------------------- it refuses bad cuts

def test_refuses_a_cut_that_leaves_too_few_positives(tmp_path):
    """The rule is: move the cut, never weaken the assertion. So an
    under-powered test set must stop the build, not silently pass."""
    pat, lab = _world(tmp_path)
    with pytest.raises(LeakageError, match="MOVE THE CUT"):
        build(pat, lab, CUT, tmp_path / "s2", min_test_positives=10_000)


def test_sweep_reports_every_candidate_cut(tmp_path):
    pat, lab = _world(tmp_path)
    df = sweep(pat, lab, fractions=(0.3, 0.5, 0.7))
    assert list(df.columns[:2]) == ["frac", "cut"]
    assert len(df) == 3
    assert (df.test_rings_kept <= df.test_rings_raw).all()
