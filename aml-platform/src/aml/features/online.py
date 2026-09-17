"""
The ONLINE feature path: compute one transaction's features in pure Python.

WHY A SECOND IMPLEMENTATION EXISTS
    features/build.py computes features for 31.9M rows at once, in SQL, using
    window functions. That is the right tool for batch.

    Serving is a different shape: one transaction arrives, you have milliseconds,
    and there is no 31.9M-row table to run a window function over. So the
    serving path is necessarily written differently -- in our case a Lambda
    function holding a short history buffer.

    Two implementations of the same definition ALWAYS drift. A window bound
    changes in one and not the other; a null is treated as zero on one side;
    a rounding rule differs. The model then trains on one distribution and
    serves on another, and the failure is silent -- predictions just quietly
    get worse.

    So we test them against each other. That CI test is the reason this project
    does not need SageMaker Feature Store: the managed service costs money to
    remove a risk that a test removes for free, and the test is the better
    portfolio artifact.

CONTRACT
    For the same (account, timestamp, history), this module must produce byte-
    identical values to the SQL path. Enforced by tests/parity/.
"""
from datetime import datetime, timedelta

import numpy as np

from aml.features.build import FEATURES

# Mirrors WINDOWS in features/build.py. Kept as timedeltas because the online
# path has no SQL engine to interpret INTERVAL for it.
WINDOW_1D = timedelta(days=1)
WINDOW_7D = timedelta(days=7)
WINDOW_30D = timedelta(days=30)

# The SQL frames end at INTERVAL 1 MINUTE PRECEDING, because minute-resolution
# timestamps mean same-minute rows must not see each other. The Python
# equivalent is a strict cutoff one minute before the current event.
EXCLUDE = timedelta(minutes=1)


def _roundness(amount: float) -> int:
    """Mirror of the SQL CASE expression. Structuring signal."""
    if amount == round(amount, -3):
        return 3
    if amount == round(amount, -2):
        return 2
    if amount == round(amount, 0):
        return 1
    return 0


def _hash_code(text: str) -> int:
    """Mirror of DuckDB's hash(x) % 1000.

    NOTE: Python's built-in hash() is salted per process and would give a
    different answer every run, so it cannot be used here. The SQL side uses
    DuckDB's hash, so the online side asks DuckDB for the same value. The
    parity test pins this; getting it wrong would be a textbook train/serve
    skew bug that no amount of unit testing on either side alone would catch.
    """
    import duckdb
    # PARAMETERISED, not interpolated. `text` is a payment format or a currency
    # code arriving from a serving request: a value with an apostrophe breaks
    # the statement, and a crafted one rewrites it. The batch side reads these
    # from Parquet, so it was never reachable there -- this side is the one
    # that takes untrusted input, and it was the one building SQL by hand.
    return duckdb.sql("SELECT hash($v) % 1000", params={"v": text}).fetchone()[0]


def _history_features(events, now: datetime, prefix: str) -> dict:
    """Trailing-window aggregates for one account.

    `events` is that account's prior activity as a list of dicts with keys
    event_time, amount_paid, counterparty, is_out. It may include rows at or
    after `now`; they are filtered here, exactly as the SQL frame does.
    """
    cutoff = now - EXCLUDE
    prior = [e for e in events if e["event_time"] <= cutoff]

    in_1d = [e for e in prior if e["event_time"] > now - WINDOW_1D - EXCLUDE]
    in_7d = [e for e in prior if e["event_time"] > now - WINDOW_7D - EXCLUDE]
    in_30d = [e for e in prior if e["event_time"] > now - WINDOW_30D - EXCLUDE]

    amt7 = [e["amount_paid"] for e in in_7d]
    amt30 = [e["amount_paid"] for e in in_30d]

    # NULL, not 0, when there is no history. The SQL side returns NULL and the
    # GBDT treats NaN as its own branch; substituting 0 here would be a silent
    # distribution shift between training and serving.
    mean_7d = float(np.mean(amt7)) if amt7 else np.nan
    # stddev_pop, not sample stddev: DuckDB's stddev_pop divides by n, not n-1.
    std_7d = float(np.std(amt7)) if amt7 else np.nan
    max_30d = float(max(amt30)) if amt30 else np.nan

    prev = max((e["event_time"] for e in in_30d), default=None)
    secs_prev = (now - prev).total_seconds() if prev else np.nan

    return {
        f"{prefix}_n_1d": float(len(in_1d)),
        f"{prefix}_n_7d": float(len(in_7d)),
        f"{prefix}_n_30d": float(len(in_30d)),
        f"{prefix}_mean_amt_7d": mean_7d,
        f"{prefix}_std_amt_7d": std_7d,
        f"{prefix}_max_amt_30d": max_30d,
        f"{prefix}_n_out_7d": float(sum(e["is_out"] for e in in_7d)),
        f"{prefix}_secs_since_prev": secs_prev,
    }


def _graph_features(events, now: datetime, prefix: str) -> dict:
    """Network-shape features for one account. Mirrors the batch CTE exactly.

    THE SUBTLE PART, and the one worth reading twice.

    `is_new_cp` is not a property of the transaction being scored. It is
    computed FOR EACH PRIOR EVENT: at the moment that event happened, had this
    account dealt with that counterparty before? The batch side does this in a
    first window pass (`wcp`, UNBOUNDED PRECEDING .. 1 MINUTE PRECEDING) and
    then sums the flag in a second pass.

    So the loop below is nested on purpose: for every event in the window, look
    back at everything strictly earlier than IT. Flattening that -- for example
    counting distinct counterparties in the window directly -- gives a different
    number, because a counterparty first seen two months ago is not "new" when
    it reappears this week.
    """
    cutoff = now - EXCLUDE
    prior = [e for e in events if e["event_time"] <= cutoff]
    in_7d = [e for e in prior if e["event_time"] > now - WINDOW_7D - EXCLUDE]

    def first_time_with(e) -> bool:
        earlier = e["event_time"] - EXCLUDE
        return not any(o["counterparty"] == e["counterparty"]
                       and o["event_time"] <= earlier
                       for o in events)

    n7 = len(in_7d)
    n_out_7d = sum(e["is_out"] for e in in_7d)
    n_new_7d = sum(1 for e in in_7d if first_time_with(e))
    # Degree: a running total of "first contact" over ALL prior events is the
    # count of distinct counterparties seen so far.
    n_distinct_ever = sum(1 for e in prior if first_time_with(e))

    return {
        # coalesce(...) on the SQL side: an empty window means we KNOW it is
        # zero, so 0 here, not NaN.
        f"{prefix}_n_in_7d": float(n7 - n_out_7d),
        f"{prefix}_n_new_cp_7d": float(n_new_7d),
        f"{prefix}_n_distinct_cp_ever": float(n_distinct_ever),
        # nullif(count, 0) on the SQL side: with no history there is no
        # direction and no rate to report, so NaN rather than 0.
        f"{prefix}_out_share_7d": (n_out_7d / n7) if n7 else np.nan,
        f"{prefix}_new_cp_rate_7d": (n_new_7d / n7) if n7 else np.nan,
    }


def _counterparty_feature(events, now: datetime, counterparty: str, prefix: str) -> dict:
    """secs_since_prev_cp -- UNBOUNDED PRECEDING, so all history, not a window."""
    cutoff = now - EXCLUDE
    seen = [e["event_time"] for e in events
            if e["counterparty"] == counterparty and e["event_time"] <= cutoff]
    return {f"{prefix}_secs_since_prev_cp":
            (now - max(seen)).total_seconds() if seen else np.nan}


def compute(txn: dict, sender_history: list, receiver_history: list) -> dict:
    """Feature vector for a single transaction.

    txn keys: event_time, sender_bank, sender_account, receiver_bank,
              receiver_account, amount_paid, amount_received,
              payment_currency, receiving_currency, payment_format
    """
    now = txn["event_time"]
    amt = txn["amount_paid"]
    sender_id = f"{txn['sender_bank']}_{txn['sender_account']}"
    receiver_id = f"{txn['receiver_bank']}_{txn['receiver_account']}"

    f = {
        "log_amount_paid": float(np.log(1 + amt)),
        "log_amount_received": float(np.log(1 + txn["amount_received"])),
        "fx_ratio": txn["amount_received"] / amt if amt else np.nan,
        "currency_mismatch": float(txn["payment_currency"] != txn["receiving_currency"]),
        "amount_roundness": float(_roundness(amt)),
        "hour": float(now.hour),
        # DuckDB's dayofweek is 0=Sunday; Python's weekday() is 0=Monday.
        # Off-by-one here would shift every weekend flag by two days.
        "dayofweek": float((now.weekday() + 1) % 7),
        "is_weekend": float((now.weekday() + 1) % 7 in (0, 6)),
        "is_self_transfer": float(sender_id == receiver_id),
        "is_cross_bank": float(txn["sender_bank"] != txn["receiver_bank"]),
        "payment_format_code": float(_hash_code(txn["payment_format"])),
        "payment_currency_code": float(_hash_code(txn["payment_currency"])),
    }
    f.update(_history_features(sender_history, now, "s"))
    f.update(_history_features(receiver_history, now, "r"))
    f.update(_counterparty_feature(sender_history, now, receiver_id, "s"))
    f.update(_counterparty_feature(receiver_history, now, sender_id, "r"))
    f.update(_graph_features(sender_history, now, "s"))
    f.update(_graph_features(receiver_history, now, "r"))

    # amt_vs_hist is derived from mean_amt_7d, so it inherits its NaN.
    for p in ("s", "r"):
        m = f[f"{p}_mean_amt_7d"]
        f[f"{p}_amt_vs_hist"] = amt / m if m and not np.isnan(m) else np.nan

    missing = set(FEATURES) - set(f)
    if missing:
        raise KeyError(f"online path is missing features the batch path emits: {sorted(missing)}")
    return {k: f[k] for k in FEATURES}


def compute_vector(txn: dict, sender_history: list, receiver_history: list) -> np.ndarray:
    """Same, ordered as FEATURES -- ready for model.predict_proba."""
    d = compute(txn, sender_history, receiver_history)
    return np.array([d[k] for k in FEATURES], dtype=np.float32)
