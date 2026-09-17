"""
Contract tests for the HI-Small answer key and its reconciliation.

MEASURED 2026-08-11 on the real files. Two figures here CORRECT
AML_PROJECT_KNOWLEDGE.md, which counted BEGIN header lines as transactions:
    pattern txns        doc said 3,579  -> actually 3,209
    typology coverage   doc said 69%    -> actually 61.99%
Arithmetic proof: the file has 4,319 lines = 370 BEGIN + 370 END + 370 blank
+ 3,209 transactions. The doc's HI-Large figure (137,936) was already correct.
"""
import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).parents[2]
PAT = ROOT / "data" / "bronze" / "patterns"
# reconcile_Small, not the unsuffixed "reconcile". Every stage became
# rung-suffixed when HI-Medium was added; this path was left pointing at the
# pre-suffix directory, so these eight assertions were silently validating a
# stale August artifact -- and would have SKIPPED, not failed, once it was
# cleaned up. A contract test that quietly stops running is worse than one
# that fails.
REC = ROOT / "data" / "gold" / "reconcile_Small"

pytestmark = pytest.mark.skipif(
    not (PAT.exists() and REC.exists()),
    reason="run `make patterns reconcile VARIANT=Small` first",
)


@pytest.fixture(scope="module")
def pm():
    return json.loads((PAT / "manifest.json").read_text())["metrics"]


@pytest.fixture(scope="module")
def rm():
    return json.loads((REC / "manifest.json").read_text())["metrics"]


def test_ring_and_txn_counts(pm):
    assert pm["rings"] == 370
    assert pm["ring_txns"] == 3_209


def test_all_eight_typologies_present(pm):
    assert pm["typologies"] == 8
    assert sum(pm["typology_counts"].values()) == 370
    # Uniform by design: no typology below 10% or above 15% of rings.
    for n in pm["typology_counts"].values():
        assert 0.10 <= n / 370 <= 0.15


def test_ring_structure(pm):
    assert pm["rings_ge_3_txns"] == 258            # 70% have real graph structure
    assert pm["median_accounts_per_ring"] == 8.0


def test_every_ring_txn_exists_in_the_transaction_file(rm):
    """If the answer key referenced transactions we don't have, the join --
    and every label downstream -- would be silently incomplete."""
    assert rm["ring_txns_not_found_in_trans"] == 0


def test_answer_key_is_a_strict_subset_of_the_flags(rm):
    """Every ring transaction is also flagged is_laundering=1. If this ever
    fails, the two files disagree about what laundering IS."""
    assert rm["unflagged_but_in_a_ring"] == 0
    assert rm["flagged_with_ring"] == 3_209


def test_the_unlabeled_positives(rm):
    """GOTCHA 2: 38% of flagged transactions belong to NO named ring.
    Typology must therefore always be nullable."""
    assert rm["flagged_txns"] == 5_177
    assert rm["flagged_without_ring"] == 1_968
    assert rm["typology_coverage_pct"] == pytest.approx(61.99, abs=0.01)


def test_join_is_unambiguous(rm):
    """No content key maps to two different rings, so ring_id is well-defined."""
    assert rm["ambiguous_content_keys"] == 0


def test_typology_is_nullable_not_a_key():
    con = duckdb.connect()
    n = con.execute(f"""
        SELECT count(*) FROM read_parquet('{REC}/txns_labeled/**/*.parquet')
        WHERE is_laundering = 1 AND typology IS NULL
    """).fetchone()[0]
    assert n == 1_968     # code must never assume a positive has a typology
