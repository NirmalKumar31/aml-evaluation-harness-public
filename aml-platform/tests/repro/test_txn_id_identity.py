"""The txn_id identity contract.

WHAT WENT WRONG, so these tests are read in context
    txn_id used to be derived downstream, independently, in two components:

        row_number() OVER (ORDER BY event_time, sender_id, receiver_id)

    Each site carried a comment saying the two expressions must stay identical.
    They were identical. It broke anyway, because that ordering key is not
    unique -- 658,850 rows of HI-Medium (2.1%) share one, in groups up to four
    -- and the sort runs in parallel. Three runs of the same query on the same
    data produced three different assignments, two at identical thread settings.

    The damage was silent. features/build.py and leakproof/plant.py disagreed
    about which transaction each id denoted, and prove.py joined them on it with
    validate="one_to_one" -- a cardinality check that cannot detect this. Leak
    columns landed on the wrong rows and every assertion passed.

WHAT THESE TESTS PIN
    Identity is assigned once, at ingest, and everything downstream reads it.
    "Keep the two copies in sync" is not a control; refusing to run without a
    supplied txn_id is. Both halves are tested: the assignment is deterministic,
    and the refusal actually fires.

The fixture deliberately contains a four-row tie on the old ordering key. Under
the previous scheme these are exactly the rows whose ids shuffled between runs.
"""
import pandas as pd
import pytest

pytest.importorskip("duckdb")
import duckdb

from aml import schema
from aml.features.build import build
from aml.ingest.normalize import normalize
from aml.leakproof.plant import plant

HEADER = schema.EXPECTED_HEADER

# 12 transactions. Rows 3-6 share (Timestamp, From Bank, Account, To Bank,
# Account) and differ only in amount -- the tie group that broke the old scheme.
ROWS = [
    "2022/09/01 00:20,010,ACC1,010,ACC2,100.00,US Dollar,100.00,US Dollar,ACH,0",
    "2022/09/01 00:20,010,ACC3,011,ACC4,250.00,US Dollar,250.00,US Dollar,Cheque,0",
    "2022/09/01 09:00,010,TIE1,010,TIE2,1.00,US Dollar,1.00,US Dollar,ACH,0",
    "2022/09/01 09:00,010,TIE1,010,TIE2,2.00,US Dollar,2.00,US Dollar,ACH,0",
    "2022/09/01 09:00,010,TIE1,010,TIE2,3.00,US Dollar,3.00,US Dollar,ACH,1",
    "2022/09/01 09:00,010,TIE1,010,TIE2,4.00,US Dollar,4.00,US Dollar,ACH,0",
    "2022/09/02 10:00,010,ACC1,011,ACC5,500.00,US Dollar,500.00,US Dollar,Wire,0",
    "2022/09/02 10:01,011,ACC5,010,ACC1,500.00,US Dollar,500.00,US Dollar,Wire,0",
    "2022/09/03 11:00,010,ACC2,010,ACC2,777.00,US Dollar,777.00,US Dollar,ACH,0",
    "2022/09/03 11:30,012,ACC6,010,ACC1,900.00,Euro,850.00,US Dollar,Wire,1",
    "2022/09/04 08:00,010,ACC1,012,ACC6,1200.00,US Dollar,1200.00,US Dollar,ACH,0",
    "2022/09/04 08:00,010,ACC1,012,ACC6,1200.00,US Dollar,1200.00,US Dollar,ACH,0",
]


@pytest.fixture
def raw_csv(tmp_path):
    p = tmp_path / "HI-Test_Trans.csv"
    p.write_text(HEADER + "\n" + "\n".join(ROWS) + "\n")
    return p


def _ingested(path):
    return duckdb.sql(
        f"SELECT * FROM read_parquet('{path}/**/*.parquet') ORDER BY txn_id").df()


# ---------------------------------------------------------------------------
# The assignment
# ---------------------------------------------------------------------------

def test_txn_id_is_contiguous_1_to_n(raw_csv, tmp_path):
    normalize(str(raw_csv), str(tmp_path / "bronze"))
    df = _ingested(tmp_path / "bronze")

    assert len(df) == len(ROWS)
    assert df.txn_id.tolist() == list(range(1, len(ROWS) + 1))


def test_txn_id_follows_physical_file_order(raw_csv, tmp_path):
    """txn_id N means "line N of the source file". That is what makes it
    meaningful as an identity and reproducible from the raw input."""
    normalize(str(raw_csv), str(tmp_path / "bronze"))
    df = _ingested(tmp_path / "bronze")

    expected = [float(line.split(",")[7]) for line in ROWS]   # Amount Paid
    assert df.amount_paid.tolist() == expected


def test_the_tie_group_gets_stable_distinct_ids(raw_csv, tmp_path):
    """The four rows that share the old ordering key must still get four
    distinct, stable ids -- and each must keep its OWN amount and label."""
    normalize(str(raw_csv), str(tmp_path / "bronze"))
    df = _ingested(tmp_path / "bronze")

    tie = df[df.sender_id == "010_TIE1"].sort_values("txn_id")
    assert tie.txn_id.tolist() == [3, 4, 5, 6]
    assert tie.amount_paid.tolist() == [1.0, 2.0, 3.0, 4.0]
    # The label travels with the right row. Under the old scheme this is the
    # association that silently permuted.
    assert tie.is_laundering.tolist() == [0, 0, 1, 0]


def test_two_ingests_of_the_same_file_agree_row_for_row(raw_csv, tmp_path):
    """Reproducibility: rebuild bronze from the raw CSV and every txn_id must
    denote the same transaction. This is the property the old scheme lacked."""
    normalize(str(raw_csv), str(tmp_path / "a"))
    normalize(str(raw_csv), str(tmp_path / "b"))

    a, b = _ingested(tmp_path / "a"), _ingested(tmp_path / "b")
    cols = ["txn_id", "event_time", "sender_id", "receiver_id",
            "amount_paid", "is_laundering"]
    pd.testing.assert_frame_equal(a[cols], b[cols])


@pytest.mark.parametrize("threads", [1, 2, 4])
def test_assignment_is_independent_of_thread_count(raw_csv, tmp_path, threads):
    """The old scheme's ids changed with the degree of parallelism, because a
    parallel sort broke ties in whatever order it finished."""
    duckdb.default_connection().execute(f"SET threads={threads}")
    normalize(str(raw_csv), str(tmp_path / f"t{threads}"))
    df = _ingested(tmp_path / f"t{threads}")

    assert df.txn_id.tolist() == list(range(1, len(ROWS) + 1))
    assert df.amount_paid.tolist() == [float(x.split(",")[7]) for x in ROWS]


def test_fully_duplicate_rows_still_get_distinct_ids(raw_csv, tmp_path):
    """The last two fixture rows are byte-identical. They are interchangeable in
    every computation, but they are still two transactions and must get two
    ids -- otherwise row counts and joins break."""
    normalize(str(raw_csv), str(tmp_path / "bronze"))
    df = _ingested(tmp_path / "bronze")

    dup = df[df.amount_paid == 1200.0]
    assert len(dup) == 2
    assert dup.txn_id.nunique() == 2


def test_ingest_records_the_contract_in_its_manifest(raw_csv, tmp_path):
    m = normalize(str(raw_csv), str(tmp_path / "bronze"))
    assert m["txn_id_contiguous"] is True
    assert m["rows"] == len(ROWS)


# ---------------------------------------------------------------------------
# The refusal -- the half that makes the fix structural
# ---------------------------------------------------------------------------

def _labeled_without_txn_id(tmp_path):
    df = pd.DataFrame({
        "event_time": pd.to_datetime(["2022-09-01 10:00", "2022-09-02 10:00"]),
        "sender_bank": ["010", "010"], "sender_account": ["A", "A"],
        "receiver_bank": ["011", "011"], "receiver_account": ["B", "B"],
        "sender_id": ["010_A", "010_A"], "receiver_id": ["011_B", "011_B"],
        "amount_paid": [100.0, 200.0], "amount_received": [100.0, 200.0],
        "payment_currency": ["US Dollar"] * 2, "receiving_currency": ["US Dollar"] * 2,
        "payment_format": ["ACH"] * 2, "is_laundering": [0, 1],
        "ring_id": [None, None], "typology": [None, None],
    })
    df["event_date"] = df.event_time.dt.date
    d = tmp_path / "nolabel"
    d.mkdir()
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{d}/txns' (FORMAT PARQUET, PARTITION_BY (event_date))")
    return str(d / "txns")


def test_build_features_refuses_input_without_txn_id(tmp_path):
    """It must NOT helpfully regenerate the column. Regenerating it is the bug."""
    src = _labeled_without_txn_id(tmp_path)

    with pytest.raises(schema.SchemaContractError, match="no txn_id column"):
        build(src, str(tmp_path / "feat"))


def test_plant_leak_refuses_input_without_txn_id(tmp_path):
    src = _labeled_without_txn_id(tmp_path)

    with pytest.raises(schema.SchemaContractError, match="no txn_id column"):
        plant(src, str(tmp_path / "leak"), kind="target")


def test_the_refusal_names_the_right_remedy(tmp_path):
    """A control that fires but leaves you guessing costs an afternoon."""
    src = _labeled_without_txn_id(tmp_path)

    with pytest.raises(schema.SchemaContractError) as e:
        build(src, str(tmp_path / "feat"))

    msg = str(e.value)
    assert "re-run normalize" in msg
    assert "columns present" in msg


def test_no_component_derives_txn_id_any_more():
    """A grep-style guard. If someone reintroduces a row_number()-based txn_id
    in a component, the two-independent-derivations bug is back, and no
    behavioural test would necessarily catch it on tie-free fixture data.

    COMMENTS ARE STRIPPED FIRST. The guard used to match raw file text, so a
    comment explaining *why* a module avoids row_number() tripped it -- the
    rule's own documentation registering as a violation of the rule. A guard
    that punishes writing down the reason gets deleted eventually, so it reads
    code only.
    """
    from pathlib import Path

    import aml

    offenders = []
    for path in Path(aml.__file__).parent.rglob("*.py"):
        code = "\n".join(ln.split("#", 1)[0] for ln in path.read_text().splitlines())
        if "row_number()" in code and "AS txn_id" in code and path.name != "normalize.py":
            offenders.append(path.name)

    assert not offenders, (
        f"{offenders} derive txn_id from row_number(). Identity is assigned once "
        f"in ingest/normalize.py and read everywhere else -- see that module's "
        f"docstring for what independent re-derivation silently broke."
    )
