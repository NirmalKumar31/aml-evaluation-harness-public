"""Phase 0 tests. These encode the three landmines in the raw data."""
from pathlib import Path

import duckdb
import pytest

from aml import schema
from aml.ingest.normalize import normalize

FIX = Path(__file__).parents[1] / "fixtures"


def test_good_header_accepted():
    schema.validate_header(FIX / "mini_trans.csv")


def test_bad_header_rejected_loudly():
    """A file we did not contract for must raise, not silently proceed."""
    with pytest.raises(schema.SchemaContractError):
        schema.validate_header(FIX / "bad_header.csv")


def test_no_duplicate_column_names():
    names = [n for n, _ in schema.COLUMNS]
    assert len(names) == len(set(names)) == 11


def test_normalize_end_to_end(tmp_path):
    out = tmp_path / "bronze"
    m = normalize(FIX / "mini_trans.csv", out)

    assert m["rows"] == 4
    assert m["positives"] == 1
    assert m["days"] == 2                      # partitioned into 2 day folders
    assert len(list(out.glob("event_date=*"))) == 2

    df = duckdb.sql(f"SELECT * FROM read_parquet('{out}/**/*.parquet')").df()

    # LANDMINE 1: both raw 'Account' columns survived, distinctly.
    assert {"sender_account", "receiver_account"} <= set(df.columns)

    # Leading zeros preserved -- '010' must not become 10.
    assert "010" in set(df.sender_bank)

    # Account identity is (bank, account), not account alone. Rows 1 and 4 both
    # receive at account 8000EBD30, but at banks 010 and 011 -- two different
    # real-world accounts. Keying on account alone would collapse them to 3.
    assert df.receiver_id.nunique() == 4
    assert df.receiver_account.nunique() == 3
    assert {"010_8000EBD30", "011_8000EBD30"} <= set(df.receiver_id)

    # LANDMINE 3: self-transactions exist and are not filtered out.
    assert (df.sender_id == df.receiver_id).sum() == 1


def test_manifest_written(tmp_path):
    out = tmp_path / "bronze"
    normalize(FIX / "mini_trans.csv", out)
    assert (out / "manifest.json").exists()
