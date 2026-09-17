"""
The data contract for IBM AMLworld transaction files.

Why this file exists: the raw CSV header contains the column name "Account"
TWICE (positions 2 and 4). Every tool handles that differently and most handle
it silently and wrongly. So we never let any tool infer this header. We declare
the schema by POSITION and rename it ourselves.
"""

from aml import io

# The raw header, byte-for-byte, as IBM ships it. If a file does not match this
# exactly, we refuse to read it rather than guess.
EXPECTED_HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account,"
    "Amount Received,Receiving Currency,Amount Paid,Payment Currency,"
    "Payment Format,Is Laundering"
)

# Our canonical names, in file order. Position is the source of truth here,
# not the name in the file.
#   (canonical_name, duckdb_type)
COLUMNS = [
    ("event_time",         "TIMESTAMP"),
    ("sender_bank",        "VARCHAR"),   # zero-padded! '010' != '10'. never int.
    ("sender_account",     "VARCHAR"),
    ("receiver_bank",      "VARCHAR"),
    ("receiver_account",   "VARCHAR"),
    ("amount_received",    "DOUBLE"),
    ("receiving_currency", "VARCHAR"),
    ("amount_paid",        "DOUBLE"),
    ("payment_currency",   "VARCHAR"),
    ("payment_format",     "VARCHAR"),
    ("is_laundering",      "TINYINT"),
]

TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"   # minute resolution, no seconds

# Columns we derive on ingest, not present in the raw file.
#
# txn_id is the transaction's IDENTITY and is assigned exactly once, here, at
# ingest. It is never re-derived downstream. See normalize.py for why, and
# require_txn_id() below for how that invariant is enforced rather than trusted.
DERIVED = ["txn_id", "sender_id", "receiver_id", "event_date"]


class SchemaContractError(Exception):
    """Raised when a file does not match the declared contract. Never caught."""


def require_txn_id(con, relation: str) -> None:
    """Refuse to proceed if a relation has no txn_id column.

    This exists because the previous design had two components recomputing
    txn_id independently, with a comment in each saying the expressions must
    stay identical. They were identical, and it still broke -- the shared
    expression was itself non-deterministic. "Keep the two copies in sync" is
    not a control. Assigning identity once and refusing to run without it is.
    """
    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()}
    if "txn_id" not in cols:
        raise SchemaContractError(
            f"{relation} has no txn_id column. txn_id is assigned once, at ingest, "
            f"by `aml normalize`, and carried through every downstream table. "
            f"A table without it was either produced by a pre-1.1.0 ingest or "
            f"dropped the column -- re-run normalize rather than regenerating "
            f"txn_id here, which is the bug this check exists to prevent.\n"
            f"  columns present: {sorted(cols)}"
        )


def read_header(path) -> str:
    """Read ONE line. At HI-Large the file behind `path` is 17 GB, so this
    streams rather than reading the object -- io.open_text keeps that true for
    blob paths as well as local ones."""
    with io.open_text(path) as f:
        return f.readline().strip().lstrip("﻿")


def validate_header(path) -> None:
    """Fail loudly and immediately if the file is not what we contracted for."""
    actual = read_header(path)
    if actual != EXPECTED_HEADER:
        raise SchemaContractError(
            f"Header contract violation in {path}\n"
            f"  expected: {EXPECTED_HEADER}\n"
            f"  actual  : {actual}"
        )


def duckdb_columns() -> dict:
    """Positional schema for duckdb read_csv. Keys are OUR names, so the
    duplicate 'Account' problem cannot occur -- we never read their names."""
    return dict(COLUMNS)
