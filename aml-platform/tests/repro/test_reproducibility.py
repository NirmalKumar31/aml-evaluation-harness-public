"""
Reproducibility: the same reproducibility key must produce the same artifact.

WHY THIS MATTERS MORE THAN IT SOUNDS
    In four months you will have a chart saying recall_efficiency@50 = 89.9%.
    Someone asks how you got it. If re-running the same inputs with the same
    code gives a different number, you cannot answer -- and neither can you
    tell a real regression from ordinary run-to-run noise.

    Non-determinism also HIDES BUGS. F8 in this project (scores matched to the
    wrong rows) was possible precisely because a query returned the same rows in
    a different order each run. A pipeline that is bit-reproducible cannot have
    that class of bug.

WHAT MUST BE STABLE
    row order out of the split      (fixed by ORDER BY txn_id)
    feature values                  (pure functions of the input)
    the fitted model                (fixed random_state)
    the metrics                     (deterministic given scores)
    the cache key                   (or caching silently never hits)
"""
import hashlib
import json

import duckdb
import numpy as np
import pandas as pd

from aml.features.build import FEATURES, build
from aml.manifest import config_hash, run_key

BASE = dict(sender_bank="010", sender_account="A", receiver_bank="011",
            receiver_account="B", amount_received=100.0, receiving_currency="US Dollar",
            payment_currency="US Dollar", payment_format="ACH", is_laundering=0,
            ring_id=None, typology=None)


def _world(tmp_path, name, n=120, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        d = 1 + i % 14
        rows.append({**BASE,
                     "event_time": f"2022-09-{d:02d} {i % 24:02d}:{i % 60:02d}",
                     "sender_account": f"S{i % 9}", "receiver_account": f"R{i % 7}",
                     "amount_paid": float(rng.integers(10, 50000)),
                     "amount_received": float(rng.integers(10, 50000)),
                     "is_laundering": int(i % 17 == 0)})
    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df.event_time)
    df["event_date"] = df.event_time.dt.date
    df["sender_id"] = df.sender_bank + "_" + df.sender_account
    df["receiver_id"] = df.receiver_bank + "_" + df.receiver_account
    # Mirrors ingest: identity assigned once, in row order, 1..N.
    df.insert(0, "txn_id", range(1, len(df) + 1))
    d = tmp_path / name
    d.mkdir()
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{d}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date))")
    return str(d / "txns_labeled")


def _digest(path) -> str:
    """Content hash of a feature table, read in a defined order so the hash
    describes the DATA and not the order the files happened to be scanned in."""
    df = duckdb.sql(f"SELECT * FROM read_parquet('{path}/**/*.parquet') ORDER BY txn_id").df()
    return hashlib.sha256(
        pd.util.hash_pandas_object(df[FEATURES].round(9), index=False).values.tobytes()
    ).hexdigest()


def test_features_are_bit_reproducible(tmp_path):
    """Same input, same code, run twice -> identical feature values."""
    src = _world(tmp_path, "in")
    build(src, tmp_path / "a")
    build(src, tmp_path / "b", force=True)      # force, or we'd just read the cache
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")


def test_the_digest_would_notice_a_change(tmp_path):
    """Control. If _digest returned a constant, the test above would pass while
    checking nothing."""
    a = _world(tmp_path, "in_a", seed=0)
    b = _world(tmp_path, "in_b", seed=1)
    build(a, tmp_path / "fa")
    build(b, tmp_path / "fb")
    assert _digest(tmp_path / "fa") != _digest(tmp_path / "fb")


def test_model_is_deterministic_given_a_seed(tmp_path):
    from sklearn.ensemble import HistGradientBoostingClassifier
    rng = np.random.default_rng(0)
    X = rng.random((4000, 8)).astype(np.float32)
    y = (rng.random(4000) < 0.05).astype(int)

    def fit_and_score():
        m = HistGradientBoostingClassifier(max_iter=30, random_state=0,
                                           class_weight="balanced", early_stopping=False)
        m.fit(X, y)
        return m.predict_proba(X)[:, 1]

    np.testing.assert_array_equal(fit_and_score(), fit_and_score())


def test_a_different_seed_gives_a_different_model(tmp_path):
    """Control for the test above."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    rng = np.random.default_rng(0)
    X = rng.random((4000, 8)).astype(np.float32)
    y = (rng.random(4000) < 0.05).astype(int)

    def fit(seed):
        m = HistGradientBoostingClassifier(max_iter=30, random_state=seed,
                                           class_weight="balanced", early_stopping=False,
                                           max_features=0.5)
        m.fit(X, y)
        return m.predict_proba(X)[:, 1]

    assert not np.array_equal(fit(0), fit(7))


def test_config_hash_ignores_key_order():
    """If it did not, the cache would never hit and every stage would rerun."""
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})


def test_config_hash_notices_a_real_change():
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_run_key_is_stable_across_calls(tmp_path):
    from aml import schema
    cfg = {"src": "x", "dest": "y"}
    f = tmp_path / "f.txt"
    f.write_text("hello")
    keys = {run_key("c", cfg, [str(f)], (schema,)) for _ in range(3)}
    assert len(keys) == 1


def test_run_key_changes_when_the_input_changes(tmp_path):
    from aml import schema
    cfg = {"src": "x", "dest": "y"}
    f = tmp_path / "f.txt"
    f.write_text("hello")
    before = run_key("c", cfg, [str(f)], (schema,))
    f.write_text("goodbye")
    assert run_key("c", cfg, [str(f)], (schema,)) != before


def test_manifest_records_everything_needed_to_reproduce(tmp_path):
    """The reproducibility key must actually be written down, not just computed."""
    src = _world(tmp_path, "in")
    build(src, tmp_path / "out")
    m = json.loads((tmp_path / "out" / "manifest.json").read_text())
    for field in ("run_key", "config", "config_hash", "code_git_sha",
                  "wall_clock_sec", "metrics", "env"):
        assert field in m, f"manifest is missing {field}"
    assert m["status"] == "ok"
    assert m["config"]["feature_spec_version"]
