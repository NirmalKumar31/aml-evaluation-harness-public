"""Pattern parser unit tests. Run on synthetic blocks, not the real file."""
import duckdb
import pytest

from aml.patterns.parse import PatternParseError, iter_blocks, parse

GOOD = """BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/03 04:33,021174,800737690,020,80020C5B0,8630.40,Euro,8630.40,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 3 hops
2022/09/02 01:00,010,AAA,011,BBB,100.00,US Dollar,100.00,US Dollar,Wire,1
END LAUNDERING ATTEMPT - CYCLE
"""


def _write(tmp_path, text):
    p = tmp_path / "P.txt"
    p.write_text(text)
    return p


def test_round_trip(tmp_path):
    blocks = list(iter_blocks(_write(tmp_path, GOOD)))
    assert [b[0] for b in blocks] == ["FAN-OUT", "CYCLE"]
    assert blocks[0][1] == "Max 16-degree Fan-Out"   # qualifier kept, not discarded
    assert [len(b[2]) for b in blocks] == [2, 1]


def test_begin_line_is_not_a_transaction(tmp_path):
    """The bug that produced the wrong 3,579 figure: counting header lines."""
    total = sum(len(b[2]) for b in iter_blocks(_write(tmp_path, GOOD)))
    assert total == 3          # not 5


@pytest.mark.parametrize("bad,why", [
    ("BEGIN LAUNDERING ATTEMPT - FAN-OUT: x\n2022/09/01 00:06,a,b\nEND LAUNDERING ATTEMPT\n",
     "wrong field count"),
    ("BEGIN LAUNDERING ATTEMPT - WOMBAT: x\nEND LAUNDERING ATTEMPT\n", "unknown typology"),
    ("BEGIN LAUNDERING ATTEMPT - CYCLE: x\n", "unterminated block"),
    ("END LAUNDERING ATTEMPT - CYCLE\n", "END without BEGIN"),
    ("BEGIN LAUNDERING ATTEMPT - CYCLE: x\nEND LAUNDERING ATTEMPT\n", "empty block"),
])
def test_malformed_blocks_raise(tmp_path, bad, why):
    with pytest.raises(PatternParseError):
        list(iter_blocks(_write(tmp_path, bad)))


def test_parse_derives_ring_timing_and_accounts(tmp_path):
    m = parse(_write(tmp_path, GOOD), tmp_path / "out")
    assert m["rings"] == 2 and m["ring_txns"] == 3

    rings = duckdb.sql(f"SELECT * FROM '{tmp_path}/out/rings.parquet' ORDER BY ring_id").df()
    # Ring 0 spans 09/01 -> 09/03 = 2 days. Timing is derived, not declared.
    assert rings.duration_days.iloc[0] == pytest.approx(2 + (4 * 60 + 33 - 6) / 1440, abs=1e-3)
    assert rings.n_accounts.iloc[0] == 3      # one sender, two receivers
    assert rings.n_accounts.iloc[1] == 2

    accts = duckdb.sql(f"SELECT * FROM '{tmp_path}/out/ring_accounts.parquet'").df()
    assert set(accts[accts.ring_id == 1].account_id) == {"010_AAA", "011_BBB"}
