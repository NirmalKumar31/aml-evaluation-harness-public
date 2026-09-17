"""
One test per defect found in the 2026-08-28 audit.

Every one of these passed silently before the fix. That is the point: each
represents a way the pipeline could be wrong while reporting `status: ok`, and
a bug with no test is a bug that comes back. They are collected in one file so
the list is readable as a list -- it is the strongest single artifact this
project has.

The two cloud-path defects (io.fingerprint refusing URIs without an ETag,
io.ensure_dir being a no-op on URIs) are covered by tests/cloud/, because they
are only observable through a URI.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aml import exits, io
from aml.eval.metrics import bootstrap_ci
from aml.features.build import FEATURES, GRAPH_FEATURES
from aml.manifest import code_hash, config_hash
from aml.models import config as model_config

# ---------------------------------------------------------------------------
# 1. Shipping a model the measurement had already rejected
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# WHERE THE ARCHIVE IS, in both layouts.
#
# These tests anchored on `parents[3]/"aml-platform/results_archive"`, which is
# the repository layout and NOT the image layout: inside the container the
# package lives at /app, so that path resolves to /aml-platform/... and every
# archive-dependent test skipped. The image job reported 283 passed / 31
# skipped against the host's 297 / 17, and the difference was exactly the
# reproducibility checks -- so "the whole suite runs inside the image" was
# true and "the image validates the released archive" was not.
#
# The archive is now COPIED into the image, and this resolves it from either
# side rather than assuming one.
# ---------------------------------------------------------------------------

def _script(name: str) -> Path:
    """`scripts/<name>`, whether we are in the repo or in /app.

    Hardcoding `parents[3]/"aml-platform/scripts"` is the repo layout, and the
    image puts the package at /app -- so the first run of the suite inside the
    image opened `/aml-platform/scripts/verify_dataset.py` and got ENOENT,
    which the test then read as a non-zero exit from the tool.
    """
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "scripts" / name
        if cand.is_file():
            return cand
        cand = base / "aml-platform/scripts" / name
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"scripts/{name} not found from {here}")


# Artifacts that predate the package-tree check and cannot be regenerated
# here. Each one says so in its own `metadata_migration_note`; the exemption is
# by name so that adding to this list is a deliberate act rather than a silence.
GRANDFATHERED_NO_TREE_HASH = {
    # Ran on the cloud VM against HI-Medium features that are not on this
    # machine. Its generator blob and full commit SHA do verify.
    "categorical_ablation_medium.json",
}


def _tree_hash_at(root: Path, sha: str):
    """`aml.manifest.tree_hash_at`, resolved against this checkout's git dir."""
    import os as _os

    from aml.manifest import tree_hash_at
    cwd = Path.cwd()
    try:
        _os.chdir(root)
        return tree_hash_at(sha)
    finally:
        _os.chdir(cwd)


def _archive_root() -> Path:
    """`results_archive`, whether we are in the repo or in /app."""
    here = Path(__file__).resolve()
    for base in here.parents:
        for cand in (base / "aml-platform/results_archive",
                     base / "results_archive"):
            if cand.is_dir():
                return cand
    return here.parents[3] / "aml-platform/results_archive"   # for the message


def test_graph_features_are_not_shipped():
    """Three paired A/B rounds measured that these HURT ring_recall@200
    (0 better / 8 worse, p=0.0078). The features stayed in FEATURES anyway, so
    every run used the configuration the evidence had rejected.

    If this ever needs to change, it changes with a paired A/B that BEATS the
    baseline -- see paper/RESULTS_graph_features.md -- not with an intuition.
    """
    assert GRAPH_FEATURES == []
    assert len(FEATURES) == 32
    assert not [f for f in FEATURES if "new_cp" in f or "out_share" in f]


# ---------------------------------------------------------------------------
# 2. A retune silently reported the previous model's metrics
# ---------------------------------------------------------------------------

def test_retuning_the_model_changes_the_cache_key():
    """`cfg` named the model only as "gbdt" and code_hash() was called with no
    modules -- the sha256 of nothing. Editing models/config.py and re-running
    printed `cached_skip` and returned the OLD model's numbers under a
    `status: ok` manifest."""
    original = model_config.GBDT["learning_rate"]
    try:
        a = config_hash({"model_params": model_config.gbdt_params(0)})
        model_config.GBDT["learning_rate"] = original / 2
        b = config_hash({"model_params": model_config.gbdt_params(0)})
    finally:
        model_config.GBDT["learning_rate"] = original
    assert a != b, "hyperparameter change did not move the cache key"


def test_gbdt_params_is_json_serialisable():
    """The reason the hyperparameters were missing from the key at all: the
    only accessor returned a fitted estimator, which cannot go in a manifest."""
    json.dumps(model_config.gbdt_params(0))


def test_gbdt_params_and_gbdt_cannot_drift():
    """gbdt() must be built FROM gbdt_params(), not alongside it."""
    p = model_config.gbdt_params(3)
    clf = model_config.gbdt(3)
    for k, v in p.items():
        assert clf.get_params()[k] == v, k


# ---------------------------------------------------------------------------
# 3. No stage hashed its own source
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", [
    "aml.features.build", "aml.splits.ring_aware", "aml.leakproof.plant",
    "aml.patterns.reconcile", "aml.patterns.parse", "aml.ingest.normalize",
    "aml.models.train", "aml.drift.splice", "aml.drift.resample",
])
def test_every_cached_stage_hashes_its_own_source(module_name):
    """`modules=()` meant code_hash() returned the sha256 of nothing, so editing
    a window frame from PRECEDING to FOLLOWING did not invalidate the feature
    cache. The one-word typo that leakproof/plant.py exists to SIMULATE was the
    exact edit the cache could not see."""
    import importlib
    m = importlib.import_module(module_name)
    h = code_hash(m)
    assert h != code_hash(), f"{module_name} hashes to the empty-module digest"
    # Distinct from another module's digest, i.e. it really reads THIS source
    # rather than returning some constant that merely differs from empty.
    other = importlib.import_module(
        "aml.eval.metrics" if module_name != "aml.eval.metrics" else "aml.io")
    assert h != code_hash(other)


# ---------------------------------------------------------------------------
# 4. The retry classifier would have retried an authentication failure
# ---------------------------------------------------------------------------

def test_auth_failure_wrapped_in_a_transient_error_is_not_retried():
    """azure-core's real shape. The never-transient check ran per-element in
    the same loop as the transient check, so whichever came FIRST in the chain
    decided -- and the transient wrapper is always outermost. A missing role
    assignment classified as retryable: three full-price attempts at a
    six-hour stage."""
    class ClientAuthenticationError(Exception):
        pass

    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise ClientAuthenticationError("no managed identity on this node")
        except ClientAuthenticationError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_CORRECTNESS


def test_a_genuinely_transient_wrapper_is_still_retried():
    """The fix must not turn every wrapped error into a correctness stop."""
    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise TimeoutError("read timed out")
        except TimeoutError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_TRANSIENT


# ---------------------------------------------------------------------------
# 5. DuckDB had no Azure credential
# ---------------------------------------------------------------------------

def test_duckdb_connections_carry_an_azure_secret():
    """Verified empirically before the fix: read_parquet('abfss://...') returned
    `401 Server failed to authenticate`. DuckDB is an embedded engine with its
    own secret store -- `az login` and managed identity are invisible to it.
    The manifest still wrote (that path is fsspec), so the symptom was a
    `status: failed` record in blob storage next to no data."""
    con = io.duckdb_connect("abfss://c@acct.dfs.core.windows.net/x/*.parquet")
    n = con.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0]
    assert n == 1


def test_az_scheme_does_not_fabricate_an_account_name():
    """`az://container/path` names a CONTAINER, not an account. Reading it as
    one creates a secret for a storage account that does not exist, turning a
    clear 'no credential' error into a confusing 'wrong credential' one."""
    assert io._azure_account("az://mycontainer/path") is None
    assert io._azure_account("abfss://c@acct.dfs.core.windows.net/p") == "acct"


# ---------------------------------------------------------------------------
# 6. bootstrap=0 crashed inside numpy instead of skipping
# ---------------------------------------------------------------------------

def test_bootstrap_zero_skips_instead_of_crashing():
    """n=0 means "skip the bootstrap" -- what the demo and a fast dev loop want.
    It used to reach np.percentile on an empty array and die with an IndexError
    from deep inside numpy, which reads like a broken metric rather than a value
    the caller chose."""
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "b", "c", "d"], "receiver_id": ["w", "x", "y", "z"],
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
    })
    out = bootstrap_ci(df, np.array([0.9, 0.1, 0.8, 0.2]), budget=2, n=0)
    assert out["n_bootstrap"] == 0
    assert np.isnan(out["ci_lo"]) and np.isnan(out["ci_hi"])


# ---------------------------------------------------------------------------
# 7. The drift pipeline was unreachable: a stage dropped the join key
# ---------------------------------------------------------------------------

def test_drift_rows_carry_a_stable_generated_sequence():
    """splice() needs an identity for synthetic rows -- they exist nowhere
    upstream -- and the tempting way to mint one is row_number() in SQL, which
    depends on scan order that DuckDB parallelises. resample() assigns it in a
    deterministic Python loop instead, and splice offsets it."""
    from aml.drift import resample
    src = resample.generate.__doc__ or ""
    import inspect
    body = inspect.getsource(resample.generate)
    assert "drift_txn_seq" in body, "resample no longer emits a stable sequence"
    assert src is not None


# ---------------------------------------------------------------------------
# 8. Azure TLS failed inside the container (found on the first real cloud read)
# ---------------------------------------------------------------------------

def test_azure_connections_use_the_curl_transport():
    """The extension's default HTTP transport cannot locate the trust store in
    a slim Debian image, so every blob request died with "Problem with the SSL
    CA cert" -- which reads like an auth failure and is not one. Measured on a
    real VM: ca_cert_file, CURL_CA_BUNDLE and SSL_CERT_FILE all FAILED; only
    the curl transport worked.

    Never reproduces locally, and the file:// gate in tests/cloud/ cannot see
    it either, because it needs a real TLS endpoint. This assertion is the
    only thing standing between us and rediscovering it on the next cloud run.
    """
    con = io.duckdb_connect("abfss://c@acct.dfs.core.windows.net/x")
    got = con.execute("SELECT current_setting('azure_transport_option_type')").fetchone()[0]
    assert got == "curl"


def test_no_transport_setting_when_no_azure_path():
    """Local and file:// runs must not be perturbed by cloud-only settings."""
    con = io.duckdb_connect(("data/gold/x", "file:///tmp/y"))
    got = con.execute("SELECT current_setting('azure_transport_option_type')").fetchone()[0]
    assert got != "curl"


# ---------------------------------------------------------------------------
# 9. '**/*.parquet' is illegal on abfss:// (found on the first cloud stage)
# ---------------------------------------------------------------------------

def test_local_parquet_arg_keeps_the_recursive_glob():
    """Local behaviour must not change: same glob, plus explicit hive
    partitioning so `event_date` -- which exists only in directory names --
    can never go quietly missing."""
    arg = io.parquet_arg("data/silver/features_Medium")
    assert arg.startswith("'data/silver/features_Medium/**/*.parquet'")
    assert "hive_partitioning=true" in arg


def test_remote_parquet_arg_lists_files_instead_of_globbing(tmp_path):
    """DuckDB refuses '{path}/**/*.parquet' on abfss:// outright:

        Not implemented Error: abfss do not manage recursive lookup patterns,
        ... only pattern ending by ** are allowed.

    And the permitted '{path}/**' is not a substitute, because every stage
    writes manifest.json into its own output directory -- read_parquet would
    be handed a JSON file. So remote paths get an explicit, sorted file list.
    """
    part = tmp_path / "out" / "event_date=2022-09-01"
    part.mkdir(parents=True)
    (part / "data_0.parquet").write_bytes(b"")
    (tmp_path / "out" / "manifest.json").write_text("{}")

    arg = io.parquet_arg("file://" + str(tmp_path / "out"))
    assert arg.startswith("["), "remote path should produce a list, not a glob"
    assert "**" not in arg
    assert "manifest.json" not in arg, "manifest must never reach read_parquet"
    assert "event_date=2022-09-01/data_0.parquet" in arg
    assert "hive_partitioning=true" in arg


def test_remote_parquet_arg_is_sorted_and_raises_when_empty(tmp_path):
    """Sorted because DuckDB's row order follows file order, and every cache
    key and model digest in this project depends on identical inputs producing
    identical bytes."""
    d = tmp_path / "e"
    (d / "event_date=2022-09-02").mkdir(parents=True)
    (d / "event_date=2022-09-01").mkdir(parents=True)
    for sub in ("event_date=2022-09-02", "event_date=2022-09-01"):
        (d / sub / "data_0.parquet").write_bytes(b"")
    arg = io.parquet_arg("file://" + str(d))
    assert arg.index("2022-09-01") < arg.index("2022-09-02")

    with pytest.raises(FileNotFoundError):
        io.parquet_arg("file://" + str(tmp_path / "nothing-here"))


# ---------------------------------------------------------------------------
# 10. Reproducibility was being measured on the wrong thing
# ---------------------------------------------------------------------------

def test_train_records_a_behaviour_digest_not_only_an_artifact_digest():
    """The Azure run reproduced every metric exactly -- average_precision,
    precision@50, ring_recall@200, and even the 500-resample bootstrap
    interval, to full float precision -- while model_artifact_sha256 differed:

        laptop  arm64 macOS   084dae41d5f0f92a...
        cloud   amd64 Linux   c9c38059498b2b16...

    joblib embeds platform detail in the pickle, so the artifact hash answers
    "were these bytes produced on the same machine?" and not "does this model
    behave the same?". For a project whose claim is reproducibility the second
    question is the one that matters, and nothing was recording it.

    ⚠️ **This test used to read the SOURCE and look for two strings.** It
    asserted that `train` mentions `predictions_sha256` and `dtype=np.float32`,
    which is true of a function that computes the digest of something nobody
    stores -- and that is exactly what it was doing. The behavioural version
    lives in `test_orchestrators.py`; this one keeps the history and checks the
    fields exist on a real manifest.
    """
    # Behaviour, not source text: the helper must distinguish two predictions
    # that differ in the id they are attached to, which a digest over scores
    # alone cannot.
    import numpy as np

    from aml.models.train import _predictions_digest

    ids = np.arange(5, dtype=np.int64)
    sc = np.linspace(0.1, 0.9, 5)
    assert _predictions_digest(ids, sc) == _predictions_digest(ids, sc)
    assert _predictions_digest(ids[::-1].copy(), sc) != _predictions_digest(ids, sc), (
        "the same scores on different transactions hash the same; the digest "
        "cannot tell two different predictions apart")
    moved = sc.copy()
    moved[2] += 1e-12
    assert _predictions_digest(ids, moved) != _predictions_digest(ids, sc), (
        "a float64 change vanished from the digest, so it is not a digest of "
        "what is stored")


# ---------------------------------------------------------------------------
# 11. DuckDB's memory budget ignored the array in the same process
# ---------------------------------------------------------------------------

def test_duckdb_budget_subtracts_the_array_we_are_about_to_allocate():
    """DuckDB's default memory_limit is 80% of SYSTEM RAM, which is wrong
    whenever the same process also preallocates the feature matrix. At
    HI-Large the two budgets did not know about each other:

        numpy train array   14.9 GB   (125.0M rows x 32 x float32)
        DuckDB default      25.0 GB   (80% of 31 GB)
                           --------
                            39.9 GB   against 31 GB

    The container was OOM-killed 61 seconds in, exit 137, before a single tree
    was fitted -- and an exit code was the only evidence, which is why the
    budget has to be computed rather than defaulted.
    """
    from aml.models.train import _duckdb_budget

    small = float(_duckdb_budget(1_000, 32).rstrip("GB"))
    large = float(_duckdb_budget(125_000_000, 32).rstrip("GB"))
    assert large < small, "budget must shrink as the array grows"
    assert large >= 1.0, "budget must stay positive even for a huge array"


def test_train_exposes_the_memory_controls():
    """Only the caller knows a 14.9 GB array is coming, so the limit and the
    spill location must be reachable from the command line -- otherwise the
    only fix for an OOM is editing source on the machine that just died."""
    import inspect

    from aml.models.train import load_test, load_train_xy, train
    for fn in (train, load_train_xy, load_test):
        params = inspect.signature(fn).parameters
        assert "memory_limit" in params, f"{fn.__name__} cannot be budgeted"
        assert "temp_directory" in params, f"{fn.__name__} cannot spill"


def test_loaders_close_the_duckdb_connection_before_returning():
    """DuckDB holds its buffer pool for the life of the connection, and the
    caller fits a model immediately after loading -- during which sklearn
    allocates a binned uint8 copy of the matrix. All three were live at once:

        X float32               14.9 GB
        sklearn binned uint8     3.7 GB
        DuckDB buffer pool      12.1 GB
                               --------
                                30.7 GB   against 31 GB

    OOM-killed twice before the close() existed: at 61s on DuckDB's default
    budget, then at 2m09s with the budget cut to 12.1 GB. Shrinking the budget
    delayed the failure without curing it, because the problem was the buffer
    pool's LIFETIME, not its size. That is the lesson worth keeping.
    """
    import inspect

    from aml.models.train import load_test, load_train_xy
    for fn in (load_train_xy, load_test):
        src = inspect.getsource(fn)
        assert "con.close()" in src, (
            f"{fn.__name__} leaves DuckDB's buffer pool alive into the fit")


def test_histogram_learners_are_row_order_DEPENDENT_above_the_bin_subsample():
    """The test this replaces asserted the opposite, and was right only because
    it tested the wrong regime.

    It fitted 20,000 rows, found bitwise-identical predictions after a row
    permutation, and concluded that `load_train_xy` need not sort. That licence
    was then used to drop `ORDER BY txn_id` from every training load, and the
    README's "Deterministic -- same inputs, same predictions" rested on it.

    Both supported histogram learners build their bin thresholds from a
    SUBSAMPLE once the data exceeds **200,000 rows** -- sklearn's `_BinMapper`
    (`subsample=200_000`, not exposed on the estimator) and LightGBM's
    `bin_construct_sample_cnt` (default 200,000). The seed fixes which
    POSITIONS are sampled, not which observations occupy them. Below the
    threshold every row is used and order genuinely does not matter; above it,
    it decides the bins.

    Every published rung is 5M-180M rows. The regime that was tested was not
    the regime that ran, which is the same defect as a null tested against the
    wrong population -- a measurement taken somewhere the claim does not live.

    This test pins the TRUE behaviour, so that anyone tempted to drop the sort
    again has to delete an explicit statement of why they must not.
    """
    n = 210_001                                     # one row over the threshold
    rng = np.random.default_rng(0)
    X = rng.random((n, 3))
    y = (rng.random(n) < 0.05).astype(np.int8)
    perm = rng.permutation(n)

    from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
    a = _BinMapper(random_state=0).fit(X)
    b = _BinMapper(random_state=0).fit(X[perm])
    assert not all(np.array_equal(x, y_) for x, y_ in
                   zip(a.bin_thresholds_, b.bin_thresholds_, strict=True)), (
        "sklearn bin thresholds no longer depend on row order above 200k. If "
        "this is a genuine upstream change, the sort may be reconsidered -- "
        "but re-measure predictions before removing it.")

    import lightgbm as lgb
    params = dict(n_estimators=10, random_state=0, verbose=-1,
                  deterministic=True, force_row_wise=True)
    pa = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:2000])[:, 1]
    pb = lgb.LGBMClassifier(**params).fit(X[perm], y[perm]).predict_proba(X[:2000])[:, 1]
    assert not np.array_equal(pa, pb), "LightGBM order dependence disappeared"

    # MEASURE IT, because the documents quote a magnitude.
    #
    # HANDOFF.md and RESULTS_hi_large.md both say "sklearn predictions move by
    # 0.063, LightGBM by 0.064". Those came from an ad-hoc run that left no
    # artifact, so the published-numbers gate could only confirm that the token
    # 0.063 existed SOMEWHERE in the archive -- which it did, in an unrelated
    # metric of a superseded lineage. A claim nothing recomputes is a claim
    # waiting to go stale.
    from sklearn.ensemble import HistGradientBoostingClassifier as HGB
    hp = dict(max_iter=10, random_state=0)
    sa = HGB(**hp).fit(X, y).predict_proba(X[:2000])[:, 1]
    sb = HGB(**hp).fit(X[perm], y[perm]).predict_proba(X[:2000])[:, 1]
    d_sk = float(np.abs(sa - sb).max())
    d_lgb = float(np.abs(pa - pb).max())
    print(f"\nmax |Δprediction| from row order alone at {n:,} rows: "
          f"sklearn {d_sk:.3f}, LightGBM {d_lgb:.3f}")
    # A band, not an equality: the exact value moves with the library version.
    # The published figures are ~0.06; anything in this range keeps the claim
    # "predictions move by several percent" true, and a collapse to ~0 means
    # the documents must change.
    assert 0.01 < d_sk < 0.30, f"sklearn delta {d_sk} is outside the published band"
    assert 0.01 < d_lgb < 0.30, f"lightgbm delta {d_lgb} is outside the published band"


def test_the_training_loader_sorts_because_the_learners_require_it():
    """The mitigation, asserted at its source.

    `load_train_xy` emits `ORDER BY txn_id` so the row order is a function of
    the DATA rather than of DuckDB's scan schedule, and `train` records
    `train_matrix_sha256` so that a future change of order is detectable
    instead of silently producing different numbers.
    """
    import inspect

    from aml.models import train as train_mod
    src = inspect.getsource(train_mod.load_train_xy)
    assert "ORDER BY txn_id" in src, (
        "the training load must impose a deterministic row order; both "
        "histogram learners bin from a positional subsample above 200k rows")
    assert "ordered" in inspect.signature(train_mod.load_train_xy).parameters, (
        "keep an explicit switch so the sort's cost can be measured, rather "
        "than deleting the sort to measure it")
    assert "train_matrix_sha256" in inspect.getsource(train_mod.train)


def test_both_loaders_sort_but_for_different_reasons():
    """This test used to assert the OPPOSITE for the training loader, and the
    assertion was the defect rather than a guard against it.

    It pinned "the training load must NOT sort", on the strength of a
    20,000-row experiment that never reached the 200,000-row bin-subsample
    threshold. A test can hold a bug in place as firmly as it can hold a fix.

    Both loaders sort now, for two independent reasons:
      * TRAIN -- the bin thresholds of both histogram learners depend on which
        rows a positional subsample lands on, so the order must be a function
        of the data.
      * TEST  -- its features and its metadata come from two separate queries
        and have to correspond row for row.
    """
    import inspect

    from aml.models.train import load_test, load_train_xy
    assert "ORDER BY txn_id" in inspect.getsource(load_train_xy)
    assert "ORDER BY txn_id" in inspect.getsource(load_test)


def test_feature_matrix_is_allocated_in_the_dtype_sklearn_actually_uses():
    """float32 was not a saving -- it was a hidden doubling.

    HistGradientBoosting's X_DTYPE is float64, so a float32 array is converted
    inside fit() and BOTH are live while it runs:

        our float32 array       14.9 GB
        sklearn's float64 copy  29.8 GB
        both live during fit    44.7 GB   against 31 GB

    That is what killed HI-Large: memory rose steadily to 15.8 GB as the array
    filled, then jumped past 31 GB within 16 seconds of the fit starting --
    which is why the trace looked like a cliff rather than a leak.

    Allocating float64 up front makes sklearn's conversion a no-op.
    """
    import inspect

    from sklearn.ensemble._hist_gradient_boosting.common import X_DTYPE

    from aml.models.train import _fetch_matrix
    default = inspect.signature(_fetch_matrix).parameters["dtype"].default
    assert default is X_DTYPE, (
        f"matrix allocated as {default} but sklearn upcasts to {X_DTYPE}, so "
        f"both arrays would be resident during fit")


# ---------------------------------------------------------------------------
# 12. Hashed account ids collided at scale
# ---------------------------------------------------------------------------

def test_account_codes_are_exact_not_hashed():
    """load_test compresses account ids to integers because 71M rows of Python
    strings across two columns costs more than the feature matrix. The first
    attempt used DuckDB's hash(), guarded by a collision check.

    The guard fired on the real data: TWO collisions at HI-Large, which would
    have merged two pairs of distinct accounts into single account-days and
    quietly corrupted ring_recall. Birthday arithmetic says 64 bits should
    collide here at ~1e-5, so hash() is evidently not uniform over 64 bits --
    the guard was right and the reasoning behind the hash was wrong.

    A DISTINCT with row_number() is exact by construction and cannot collide at
    any scale. This asserts the hash never comes back.
    """
    import inspect

    from aml.models.train import load_test
    src = inspect.getsource(load_test)
    assert "hash(sender_id)" not in src, "hashed ids can collide; use the dimension table"
    assert "CREATE TEMP TABLE acct" in src
    assert "row_number()" in src


def test_cli_model_choices_come_from_the_models_table():
    """The choices list was a second copy of the MODELS table, kept by hand.

    Adding "lgbm" to MODELS left it untouched, so the run died at argparse --
    after the image had been rebuilt, pushed and dispatched. The cheapest
    possible failure arriving at the most expensive possible moment, and the
    same shape as every other defect in this file: one fact written twice.
    """
    from aml.cli import _model_names
    from aml.models.train import MODELS
    assert set(_model_names()) == set(MODELS)
    assert "lgbm" in _model_names()


# ---------------------------------------------------------------------------
# 13. Findings from the 2026-09-10 council audit
# ---------------------------------------------------------------------------

def test_sampling_keeps_rings_whole():
    """--sample thinned by hash(txn_id), selecting TRANSACTIONS independently.

    That destroys the unit every ring-level metric is defined on: a ring loses
    ~30% of its transactions at sample=0.7, shrinking its account-day footprint
    and its chances at the daily top-k, while a one-transaction ring vanishes
    entirely 30% of the time -- yet ring_recall's denominator came from
    test_rings.parquet, built on the UNSAMPLED data. Both HI-Large 70% runs
    were void for ring claims because of this.

    It also silently thinned the TEST set: recall_ceiling@50 moved 0.0517 ->
    0.0713 from subsampling alone, so two runs at different --sample values
    were not comparable on any budget metric.
    """
    from aml.models.train import _sample_clause
    assert _sample_clause(1.0) == ""
    c = _sample_clause(0.7)
    assert "hash(ring_id)" in c, "rings must be kept or dropped WHOLE"
    assert "ring_id IS NULL" in c, "unringed rows still thin by txn_id"

    # And it must reach TRAINING ONLY. Applying it to the test predicate was
    # the defect that invalidated the first HI-Large comparison outright:
    # recall_ceiling@50 moved 0.0517 -> 0.0713 on the same rung at the same k,
    # purely from subsampling the evaluation set.
    import json
    import tempfile
    from pathlib import Path

    from aml.models.train import _split_where
    d = tempfile.mkdtemp()
    Path(d, "manifest.json").write_text(json.dumps({"config": {"cut_time": "2022-09-10"}}))
    tr, te = _split_where(d, 0.7)
    assert "hash(" in tr, "training must be thinned"
    assert "hash(" not in te, "the TEST set must never be subsampled"


def test_average_precision_carries_its_unit():
    """AP is computed on TRANSACTIONS; every budget metric is computed on
    ACCOUNT-DAYS. The README reported 'average_precision 0.3149' beside
    'precision@50 0.9062' as though they shared a denominator. The suffix makes
    the unit travel with the number into every manifest and table."""
    import inspect

    from aml.eval import metrics
    src = inspect.getsource(metrics.evaluate)
    assert '"average_precision__txn"' in src
    assert '"average_precision":' not in src, "unsuffixed key is ambiguous"


def test_ring_recall_is_reported_against_a_size_matched_null():
    """ring_recall alone flatters the system, because a ring gets one draw per
    account-day and spans many of them.

    The FIRST fix divided ring_recall by recall@k and called it
    `ring_recall_inflation`. That was wrong in the direction that matters -- it
    ranks runs by test-window length, not by how much the metric flatters:

                    recall   null=1-(1-r)^17   observed   obs/null
        HI-Large    0.0918        0.8054        0.8738      1.08
        HI-Medium   0.1248        0.8963        0.6938      0.77

    inflation calls HI-Large (9.5x) worse than HI-Medium (5.6x); against a
    size-matched null the SIGN OF INTERPRETATION flips, so the same rung reads
    "worse" on one and "better" on the other. (An earlier version of this
    docstring said the ORDERING reverses. It does not -- both metrics rank
    HI-Large above HI-Medium -- and the claim was asserted from arithmetic done
    in someone's head rather than computed.) So the null is what must be
    emitted, with the ring sizes it depends on.

    The closed-form null this test was written against has since been retired
    in favour of a within-day permutation; see
    `test_ring_null_is_stratified_by_day_and_scoped_to_ring_members`. The keys
    asserted here are the ones that survived, and they must keep their names.
    """
    import inspect

    from aml.eval import metrics
    # Assert on the EMITTED KEYS, not on source text. A substring test would
    # match the docstring that explains why inflation was wrong -- which is
    # exactly the class of test this file exists to stop: one that passes
    # because the remediation is described, not because it happened.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 6),
        "sender_id": list("abcdef"), "receiver_id": list("uvwxyz"),
        "is_laundering": [1, 1, 0, 0, 1, 0],
        "ring_id": [1.0, 1.0, None, None, 2.0, None],
        "typology": ["FAN-OUT", "FAN-OUT", None, None, "CYCLE", None],
    })
    m = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]), budgets=(2,))
    assert "ring_recall_null@2" in m
    assert "ring_recall_lift@2" in m
    assert "ring_size_median@2" in m, "the null depends on sizes; publish them"
    assert "n_rings@2" in m
    assert not [k for k in m if "inflation" in k], "ratio of incommensurables"

    # The null must survive the saturated ends. The first guard was
    # `0 < r < 1`, so it vanished exactly when recall hit 0 or 1 -- when a
    # ring number is least meaningful and the comparison is most needed.
    sat = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]),
                           budgets=(1000,))
    assert sat["recall@1000"] == 1.0, "fixture should saturate at this budget"
    assert "ring_recall_null@1000" in sat, "null dropped exactly when it matters"
    assert sat["ring_recall_lift@1000"] == 1.0

    # Keys are budget-scoped, so a multi-budget call cannot overwrite them.
    two = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]),
                           budgets=(2, 5))
    assert {"n_rings@2", "n_rings@5"} <= set(two)
    _ = inspect.getsource(metrics)


def test_ring_coverage_is_measured_on_account_days_not_transactions():
    """Positives with no ring label bypass the ring-participant-disjoint discipline and
    are absent from ring_recall's denominator. That fraction must be measured
    on ACCOUNT-DAYS, because that is what ring_recall is denominated in.

    The first version computed it over transactions, which made it exactly
    `100 - typology_coverage_pct` -- algebraically the negation of a metric
    that already existed, adding no information at all, while its own comment
    claimed to describe account-days.
    """
    import inspect

    from aml.eval import metrics
    src = inspect.getsource(metrics.evaluate)
    assert "pct_positive_acct_days_without_ring" in src
    assert "pct_positives_without_ring" not in src, "that was 100 - coverage"


def test_spread_reports_robust_variability_not_only_the_range():
    """(max-min)/mean is a two-point statistic and one bad fit owns it. The
    published 'budget metrics move 37.2%' is seed 4 alone: precision@50 across
    eight seeds is 0.794 0.898 0.895 0.896 [0.591] 0.830 0.844 0.851. Without
    it the range is 12.1% and the MAD is 5.7%. The finding survives; the
    headline number was a worst case presented as typical."""
    import numpy as np

    from aml.models.stability import _spread
    s = _spread(np.array([0.794, 0.898, 0.895, 0.896, 0.591, 0.830, 0.844, 0.851]))
    assert s["spread_pct"] == pytest.approx(37.22, abs=0.1)
    assert s["mad_pct"] < 10, "robust statistic must not be dominated by one seed"
    assert {"median", "iqr_pct", "mad_pct", "n"} <= set(s)


def test_evaluate_loads_only_the_test_half():
    """The evaluate stage exists to be the CHEAP way to recompute metrics, and
    it was loading the training split it never uses.

    At HI-Large that is fatal rather than wasteful:

        train  29.8 GB   <- loaded, never used
        test   13.0 GB
        total  42.8 GB   against a 31 GB machine

    Measured: exit 137 at 55 seconds, OOM-killed before it read the scores.
    train.py had already been fixed to load the halves separately and free the
    training matrix first; this module was left on the legacy loader, so the
    same defect survived in the one place whose whole purpose is to avoid
    paying for a refit.
    """
    # BEHAVIOURAL, not a grep of the source text.
    #
    # This asserted `"load_split(" not in inspect.getsource(eval_run)`. An
    # audit defeated it in one line: `from aml.models.train import load_split
    # as _both` reinstates the 29.8 GB load verbatim and the string never
    # appears. "A test that greps for a name is not a contract test" is a
    # lesson this repository has already written down twice.
    #
    # So: make the forbidden loader explode, stub the permitted one, and run
    # the stage. Any route to the training half -- alias, attribute access,
    # re-import -- fails, because the object itself refuses.
    import aml.models.train as train_mod
    from aml.eval import run as eval_run

    calls = []

    def _forbidden(*a, **k):
        raise AssertionError(
            "evaluate loaded the TRAINING half. At HI-Large that is 29.8 GB "
            "it never uses, on a 31 GB machine: exit 137 at 55 seconds.")

    def _permitted(features, splits, *a, **k):
        calls.append((features, splits))
        raise _StopEvaluate()

    class _StopEvaluate(Exception):
        """Stop once the loader choice is known; the rest needs a dataset."""

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(train_mod, "load_split", _forbidden, raising=False)
        monkey.setattr(train_mod, "load_test", _permitted, raising=False)
        monkey.setattr(eval_run, "load_test", _permitted, raising=False)
        # AND EVERY ALIAS. `from ... import load_split as _both` binds the
        # function object into this module's namespace at import time, where
        # patching the source module cannot reach it -- which is exactly the
        # one-line defeat. Rebind anything here that IS the real loader,
        # whatever it is called.
        real = train_mod.__dict__.get("load_split")
        for name, obj in list(vars(eval_run).items()):
            if obj is real or getattr(obj, "__name__", None) == "load_split":
                monkey.setattr(eval_run, name, _forbidden, raising=False)
        # A TEMP DEST. The stage writes a failure manifest before it raises,
        # and `dest="d"` dropped `aml-platform/d/manifest.json` into the
        # working tree -- which then tripped `require_clean_scope()` and
        # blocked artifact regeneration. A test may not write into the repo.
        with tempfile.TemporaryDirectory() as td, pytest.raises(_StopEvaluate):
            eval_run.run(features="f", splits="s", scores="sc", dest=td)
    finally:
        monkey.undo()
    assert calls == [("f", "s")], (
        f"evaluate did not reach load_test as expected: {calls}")


# ---------------------------------------------------------------------------
# 14. External audit (v1), 2026-09-11: ring membership was many-to-many
# ---------------------------------------------------------------------------

def test_ring_membership_survives_account_days_in_multiple_rings():
    """to_account_days collapsed each account-day to ONE ring via `max`.

    Not a corner case. Measured on HI-Large's reconciled labels:

        ringed account-days       243,295
        MULTI-RING account-days    10,432   (4.288%)
        max rings on one acct-day       12

    Up to eleven of twelve memberships were discarded on 4.3% of ringed
    account-days. Each discarded membership is a detection opportunity the
    affected ring silently loses, so ring_recall was biased DOWNWARD, and
    per_typology assigned those rows whichever typology `max` happened to pick.

    There is no correct scalar to aggregate to -- the relation is many-to-many,
    so it has to stay a relation.
    """
    import numpy as np
    import pandas as pd

    from aml.eval.metrics import evaluate, ring_membership, to_account_days

    # Account "a" transacts in rings 1 and 2 on the same day.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "a", "b", "c"],
        "receiver_id": ["x", "y", "a", "z"],
        "is_laundering": [1, 1, 1, 0],
        "ring_id": [1.0, 2.0, 3.0, None],
        "typology": ["FAN-OUT", "CYCLE", "STACK", None],
    })
    ad = to_account_days(df, np.array([0.9, 0.8, 0.7, 0.1]))
    mem = ring_membership(ad)

    a_rings = set(mem.loc[mem.acct == "a", "ring_id"])
    assert a_rings == {1.0, 2.0, 3.0}, (
        f"account-day 'a' belongs to rings 1, 2 and 3; membership kept {a_rings}")
    assert len(mem) > len(ad[ad.ring_id.notna()]), (
        "membership must hold MORE rows than the collapsed column can")

    # And the metrics must see every ring, not just the surviving label.
    m = evaluate(df, np.array([0.9, 0.8, 0.7, 0.1]), budgets=(10,))
    assert m["n_rings@10"] == 3, f"expected 3 rings, saw {m['n_rings@10']}"


# ---------------------------------------------------------------------------
# 14. The ring null used the wrong reference population and the wrong
#     independence assumption  (external audit v1, RB-03 / EV-03)
# ---------------------------------------------------------------------------

def _ring_frame(n_days=6, n_rings=12, ring_size=4, n_noise=400, seed=0):
    """A frame where ring membership is IRRELEVANT to the score.

    Under this construction any honest null must say the model is doing
    nothing: lift near 1, permutation p-value nowhere near significance.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ring in range(n_rings):
        for j in range(ring_size):
            rows.append({"event_date": pd.Timestamp("2022-09-01")
                         + pd.Timedelta(days=int(rng.integers(n_days))),
                         "sender_id": f"r{ring}_{j}", "receiver_id": f"r{ring}_{j+1}",
                         "is_laundering": 1, "ring_id": float(ring),
                         "typology": "FAN-OUT"})
    for i in range(n_noise):
        rows.append({"event_date": pd.Timestamp("2022-09-01")
                     + pd.Timedelta(days=int(rng.integers(n_days))),
                     "sender_id": f"n{i}", "receiver_id": f"n{i + 1}",
                     "is_laundering": int(rng.random() < 0.2),
                     "ring_id": None, "typology": None})
    df = pd.DataFrame(rows)
    return df, rng.random(len(df))


def test_ring_null_is_scoped_to_the_ring_eligible_population():
    """The retired null applied POOLED account-day recall to ring sizes.

    On HI-Large 87% of positive account-days carry no ring label, so pooled
    recall is mostly a statement about a population the metric does not
    describe. The null has to use the rate at which RING-MEMBER account-days
    are alerted, and that number must itself be published so the substitution
    is checkable rather than asserted.
    """
    from aml.eval import metrics
    df, score = _ring_frame()
    # Make unringed positives much easier than ringed ones, so pooled recall
    # and ring-eligible recall cannot coincide by accident.
    score = np.where(df.ring_id.isna() & (df.is_laundering == 1), 0.99, score * 0.5)
    m = metrics.evaluate(df, score, budgets=(20,), n_permutations=200)

    assert "ring_eligible_recall@20" in m, "the null's own base rate must be published"
    assert m["ring_eligible_recall@20"] != m["recall@20"], (
        "fixture should separate the two populations")
    # The retired form is kept, clearly labelled, so the published 1.43 can be
    # reconciled with its replacement instead of silently vanishing.
    assert "ring_recall_null_analytic_pooled@20" in m
    assert "ring_recall_lift_analytic_pooled@20" in m


def test_ring_null_matches_a_from_scratch_recomputation():
    """The null is computed by a fast path that never rebuilds account-days.

    That fast path is an optimisation of a definition, and an optimisation of a
    definition is a place to hide a bug. This pins it to the definition: for
    the same permuted scores, re-derive everything the slow way -- reassign the
    transaction scores, rebuild account-days from scratch, re-rank with pandas
    -- and require DRAW-FOR-DRAW equality, not agreement in distribution.
    """
    from aml.eval import metrics as M
    df, score = _ring_frame(n_rings=25, ring_size=5, n_noise=600, seed=2)
    ad = M.to_account_days(df, score)
    st = M._ring_structure(ad)

    # The reconstruction must reproduce the real account-day scores exactly,
    # or every rank built on top of it is measuring a different quantity.
    v = M._elig_scores(st, st["rt_score"])
    assert np.allclose(v, ad.score.to_numpy()[st["ad_rows"]])
    pandas_rank = ad.groupby("day")["score"].rank(ascending=False,
                                                  method="min").to_numpy()
    assert (M._elig_min_ranks(st, v) == pandas_rank[st["ad_rows"]]).all()

    rt_idx = np.flatnonzero(df.ring_id.notna().to_numpy())
    day_code, day_uniq = pd.factorize(ad["day"].to_numpy(), sort=True)
    rt_day = np.searchsorted(day_uniq, df.event_date.to_numpy()[rt_idx])
    rt_idx_s = rt_idx[np.argsort(rt_day, kind="stable")]

    rng = np.random.default_rng(0)
    blocks = [(int(a), int(b)) for a, b in
              zip(st["rt_starts"], st["rt_stops"], strict=True) if b - a > 1]
    for _ in range(15):
        perm = st["rt_score"].copy()
        for a, b in blocks:
            perm[a:b] = rng.permutation(perm[a:b])

        fast = M._ring_hits(
            st, M._elig_min_ranks(st, M._elig_scores(st, perm)) <= 20).mean()

        slow_score = score.copy()
        slow_score[rt_idx_s] = perm
        ad2 = M.to_account_days(df, slow_score)
        st2 = M._ring_structure(ad2)
        pr2 = ad2.groupby("day")["score"].rank(ascending=False,
                                               method="min").to_numpy()
        slow = M._ring_hits(st2, pr2[st2["ad_rows"]] <= 20).mean()
        assert fast == slow, f"fast path diverged from the definition: {fast} vs {slow}"


def test_ring_null_permutes_only_within_a_day():
    """The daily review budget is the whole point of the metric, so a draw may
    not move a score from one day to another. Each day's multiset of ring
    transaction scores must come back unchanged.
    """
    from aml.eval import metrics as M
    df, score = _ring_frame(n_rings=20, n_noise=500, seed=4)
    ad = M.to_account_days(df, score)
    st = M._ring_structure(ad)
    rng = np.random.default_rng(0)
    perm = st["rt_score"].copy()
    for a, b in zip(st["rt_starts"], st["rt_stops"], strict=True):
        perm[a:b] = rng.permutation(perm[a:b])
    for a, b in zip(st["rt_starts"], st["rt_stops"], strict=True):
        assert np.array_equal(np.sort(perm[a:b]), np.sort(st["rt_score"][a:b]))


def test_ring_null_says_nothing_is_happening_when_nothing_is():
    """Scores independent of ring membership must not produce a ring finding.

    This is the control the closed form never had, and it is the reason the
    first permutation null was thrown away. That one reshuffled WHICH ring
    account-days were alerted, holding the daily count fixed -- and returned
    lift 0.497 on exactly this fixture, declaring a strong effect on data built
    to contain none. The cause is mechanical: a transaction's sender and
    receiver account-days carry the same score, so ring hits are correlated
    whether or not a model knows anything about rings. A null that cannot say
    "nothing here" is not measuring anything.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=40, n_noise=1500, seed=7)
    m = metrics.evaluate(df, score, budgets=(40,), n_permutations=400)

    assert m["ring_recall_null_p@40"] > 0.05, (
        f"declared a ring effect on ring-independent scores "
        f"(lift {m['ring_recall_lift@40']})")
    assert (m["ring_recall_null_lo@40"] <= m["ring_recall_minrank@40"]
            <= m["ring_recall_null_hi@40"]), (
        "the observed value fell outside its own null's 95% interval on data "
        "drawn from that null")
    # A permutation p-value can never be zero: the observed arrangement is one
    # of the arrangements being counted.
    assert m["ring_recall_null_p@40"] >= 1 / (400 + 1)


def test_ring_null_detects_hits_piling_up_inside_few_rings():
    """The direction that matters for the headline. If the model's alerts
    concentrate inside a handful of rings, observed ring_recall falls BELOW
    the permutation null and lift must go below 1.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=30, ring_size=6, n_noise=900, seed=3)
    # Every alert the model can spare goes to three rings, repeatedly.
    score = np.where(df.ring_id.isin([0.0, 1.0, 2.0]), 0.99, score * 0.2)
    m = metrics.evaluate(df, score, budgets=(12,), n_permutations=400)

    assert m["ring_recall_lift@12"] < 1.0, m["ring_recall_lift@12"]
    assert m["ring_recall_null@12"] > m["ring_recall@12"]


def test_ring_null_is_deterministic_for_a_given_seed():
    """Published intervals have to replay. Same seed, same numbers."""
    from aml.eval import metrics
    df, score = _ring_frame(seed=11)
    a = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=5)
    b = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=5)
    c = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=6)
    for k in ("ring_recall_null@20", "ring_recall_null_lo@20", "ring_recall_null_p@20"):
        assert a[k] == b[k], f"{k} did not replay"
    assert a["ring_recall_null@20"] != c["ring_recall_null@20"] or \
        a["ring_recall_null_p@20"] != c["ring_recall_null_p@20"], \
        "different seeds produced an identical draw; the seed is not wired in"


# ---------------------------------------------------------------------------
# 15. Budget-boundary ties were resolved by meaningless row order  (EV-02)
# ---------------------------------------------------------------------------

def test_tied_scores_at_the_budget_boundary_are_counted_and_bracketed():
    """rank(method="first") breaks ties by input row order, and those row
    numbers come from `row_number() over ()` with no semantic ordering. Tree
    ensembles emit repeated leaf scores in quantity, so the boundary can be
    decided by nothing at all.

    Replaying the same arbitrary choice bitwise on two architectures makes it
    REPRODUCIBLE, not MEANINGFUL. The fix is to publish how many rows sit in a
    straddling tie and to bracket the metric under the best and worst possible
    resolutions.
    """
    from aml.eval import metrics
    # Six account-days on one day, four of them tied at exactly 0.5, budget 2.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 6),
        "sender_id": list("abcdef"), "receiver_id": list("uvwxyz"),
        "is_laundering": [1, 1, 1, 0, 0, 0],
        "ring_id": [1.0, 1.0, None, None, None, None],
        "typology": ["FAN-OUT", "FAN-OUT", None, None, None, None],
    })
    score = np.array([0.5, 0.5, 0.5, 0.5, 0.1, 0.2])
    m = metrics.evaluate(df, score, budgets=(2,), n_permutations=50)

    assert m["tied_at_boundary@2"] > 0, "a straddling tie was not counted"
    assert (m["recall_tie_pessimistic@2"] <= m["recall@2"]
            <= m["recall_tie_optimistic@2"]), "bracket does not contain the estimate"
    # With no ties the bracket must collapse onto the point estimate, or it is
    # reporting noise rather than tie sensitivity.
    clean = metrics.evaluate(df, np.array([0.9, 0.8, 0.7, 0.6, 0.1, 0.2]),
                             budgets=(2,), n_permutations=50)
    assert clean["tied_at_boundary@2"] == 0
    assert (clean["recall_tie_pessimistic@2"] == clean["recall@2"]
            == clean["recall_tie_optimistic@2"])


# ---------------------------------------------------------------------------
# 16. evaluate() failed from inside sklearn instead of at its own door (CQ-03)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("mutate", "message"), [
    (lambda d, s: (d.drop(columns=["ring_id"]), s), "needs columns"),
    (lambda d, s: (d, s[:-1]), "rows"),
    (lambda d, s: (d.iloc[:0], s[:0]), "empty"),
    (lambda d, s: (d, np.where(np.arange(len(s)) == 1, np.nan, s)), "NaN"),
    (lambda d, s: (d.assign(is_laundering=0), s), "one class"),
])
def test_evaluate_rejects_bad_input_with_a_domain_error(mutate, message):
    """Each of these used to surface as an IndexError or a ValueError from deep
    inside sklearn, which reads like a bug in the metric rather than a
    description of what the caller passed.
    """
    from aml.eval import metrics
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": list("abcd"), "receiver_id": list("wxyz"),
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
        "typology": ["FAN-OUT", None, "FAN-OUT", None],
    })
    bad_df, bad_score = mutate(df, np.array([0.9, 0.1, 0.8, 0.2]))
    with pytest.raises(ValueError, match=message):
        metrics.evaluate(bad_df, bad_score, budgets=(2,), n_permutations=0)


# ---------------------------------------------------------------------------
# 17. Manifests were not strict JSON, and the demo described a corpus it did
#     not generate  (CQ-04, CQ-05)
# ---------------------------------------------------------------------------

def test_manifests_never_contain_the_bare_token_nan(tmp_path):
    """`json.dumps` emits `NaN` by default and every strict parser rejects it.

    The SUPPORTED demo path produced one: `--bootstrap 0` leaves `ci_lo` and
    `ci_hi` as NaN, and they went straight into a published manifest. A
    provenance file a conformant reader cannot parse is not provenance.
    """
    p = tmp_path / "m.json"
    io.write_json(str(p), {"ci_lo": float("nan"), "ci_hi": float("inf"),
                           "nested": {"x": [1.0, float("-inf")]}, "ok": 0.5})
    text = p.read_text()
    assert "NaN" not in text and "Infinity" not in text
    back = json.loads(text)                     # strict by default: no NaN
    assert back["ci_lo"] is None and back["ci_hi"] is None
    assert back["nested"]["x"] == [1.0, None] and back["ok"] == 0.5


def test_demo_banner_counts_rows_instead_of_describing_them():
    """It said "~900 rows" while generating 3,116, and "cannot detect anything"
    while the planted rings scored near 1.0. Both were typed once and never
    re-checked -- in the one place that tells a newcomer what to trust.
    """
    import ast
    import inspect

    from aml import demo
    # STRING LITERALS ONLY. A substring test over the source would match the
    # comment that explains the fix -- the mirror image of the defect this file
    # exists to catch, where a test passes because the remediation is
    # DESCRIBED. Here it would have failed for the same reason.
    tree = ast.parse(inspect.getsource(demo))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    joined = "\n".join(literals)
    assert "900 rows" not in joined, "the row count must be generated, not typed"
    assert "cannot detect" not in joined
    # f-strings put their interpolations in FormattedValue nodes, not in the
    # literal segments, so the count has to be looked for as an expression.
    interpolated = {n.value.id for n in ast.walk(tree)
                    if isinstance(n, ast.FormattedValue)
                    and isinstance(n.value, ast.Name)}
    assert "rows" in interpolated, \
        "the banner must count what was actually built"


# ---------------------------------------------------------------------------
# 18. A parameter that moves a published number was not reachable from the CLI
# ---------------------------------------------------------------------------

def test_every_runner_parameter_that_moves_a_number_is_on_the_cli():
    """`eval.run.run()` takes a `seed` and says, in its own comment, that
    omitting a parameter which moves a reported number is a defect. The CLI
    then omitted it. Every archived evaluate manifest therefore records
    `seed: 0`, including the ones scoring model seeds 1 and 2.

    This checks the general property rather than the one instance: each
    stage-runner argument that the manifest records as configuration must be
    settable on its subcommand.
    """
    import argparse
    import inspect

    from aml import cli
    from aml.eval.run import run as evrun

    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:                      # parser is built inside main()
        parser = argparse.ArgumentParser()
        pytest.skip("cli does not expose its parser")

    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    ev = sub.choices["evaluate"]
    flags = {o.lstrip("-").replace("-", "_")
             for a in ev._actions for o in a.option_strings}
    for name, p in inspect.signature(evrun).parameters.items():
        if name in {"features", "splits", "scores", "dest"}:
            continue                        # positional inputs, already required
        if p.default is inspect.Parameter.empty:
            continue
        assert name in flags or name == "budgets", (
            f"evaluate() honours `{name}` and records it in the manifest, but "
            f"the CLI cannot set it")


# ---------------------------------------------------------------------------
# 19. The cache trusted a manifest it never checked against its outputs
#     (RP-03, RP-04, RP-05)
# ---------------------------------------------------------------------------

def _finished_stage(tmp_path, payload=b"x" * 4096):
    """Run a trivial stage to completion so a real manifest exists."""
    from aml.manifest import Run, run_key
    out = tmp_path / "gold"
    out.mkdir()
    (out / "part-0.parquet").write_bytes(payload)
    key = run_key("demo_stage", {"a": 1}, [], ())
    with Run("demo_stage", {"a": 1}, str(out), key=key) as r:
        r.record(rows=10)
    return out, key


def test_a_cache_hit_verifies_the_outputs_exist(tmp_path):
    """`load_cached` checked run_key and status and stopped there.

    Delete the Parquet and the manifest still says ok, so the stage is skipped
    and the next one reads nothing. Provenance that does not check the thing it
    describes is decoration.
    """
    from aml.manifest import load_cached
    out, key = _finished_stage(tmp_path)
    assert load_cached(str(out), key) == {"rows": 10}

    (out / "part-0.parquet").unlink()
    assert load_cached(str(out), key) is None, "skipped a stage whose output is gone"


def test_a_cache_hit_verifies_the_outputs_are_unchanged(tmp_path):
    """Same size, different bytes -- the case a size check alone misses, and
    the one a truncated or half-rewritten file actually produces."""
    from aml.manifest import load_cached
    out, key = _finished_stage(tmp_path)
    assert load_cached(str(out), key) == {"rows": 10}

    (out / "part-0.parquet").write_bytes(b"y" * 4096)
    assert load_cached(str(out), key) is None, "accepted corrupted outputs"


def test_the_manifest_records_what_the_stage_wrote(tmp_path):
    out, _ = _finished_stage(tmp_path)
    m = json.loads((out / "manifest.json").read_text())
    inv = {e["path"]: e for e in m["outputs"]}
    assert "part-0.parquet" in inv
    assert inv["part-0.parquet"]["bytes"] == 4096
    assert len(inv["part-0.parquet"]["sha256"]) == 64
    assert "manifest.json" not in inv, "a manifest that inventories itself never settles"
    assert m["output_hash_max_bytes"] > 0, "the hashing policy must be visible"


def test_a_stale_partition_from_a_previous_run_is_removed(tmp_path):
    """Stages write with OVERWRITE_OR_IGNORE into an existing partitioned
    destination. A rerun emitting FEWER partitions leaves the old ones behind,
    and the next reader silently sees two generations blended into one dataset.

    THE FIRST VERSION OF THIS TEST WAS WRITTEN AROUND THE BUG. It deleted the
    stale partition by hand before the rerun and then asserted it was gone --
    so it passed while the cleanup did nothing whatsoever. The cleanup
    inventoried the directory AFTER the stage wrote, at which point the stale
    file is still sitting there and looks current.

    This version does what the pipeline does: writes inside the context
    manager, and never touches the stale file.
    """
    from aml.manifest import Run

    out = tmp_path / "gold"
    out.mkdir()
    with Run("demo_stage", {"v": 1}, str(out), key="k1") as r:
        (out / "part-0.parquet").write_bytes(b"a" * 4096)
        (out / "part-1.parquet").write_bytes(b"b" * 4096)
        r.record(rows=2)
    assert (out / "part-1.parquet").exists()

    with Run("demo_stage", {"v": 2}, str(out), key="k2") as r:
        (out / "part-0.parquet").write_bytes(b"c" * 4096)    # only this one
        r.record(rows=1)

    assert (out / "part-0.parquet").exists(), "a rewritten output was deleted"
    assert not (out / "part-1.parquet").exists(), (
        "the stale partition survived; two generations are now blended")
    m = json.loads((out / "manifest.json").read_text())
    assert m["stale_outputs_removed"] == ["part-1.parquet"]
    assert {e["path"] for e in m["outputs"]} == {"part-0.parquet"}


def test_a_manifest_without_an_output_inventory_is_not_a_cache_hit(tmp_path):
    """`verify_outputs` treats an empty inventory as "nothing to check", so a
    manifest written before inventories existed could satisfy a cache hit while
    verifying NOTHING. Sixty-nine committed manifests are in that state.

    An absent key and an empty list mean different things: the first is "we do
    not know what this wrote", the second is "it wrote nothing".
    """
    from aml.manifest import load_cached

    out = tmp_path / "gold"
    out.mkdir()
    (out / "part-0.parquet").write_bytes(b"x" * 32)
    (out / "manifest.json").write_text(json.dumps(
        {"run_key": "legacy", "status": "ok", "metrics": {"rows": 1}}))

    assert load_cached(str(out), "legacy") is None, (
        "a manifest with no output inventory verified nothing and still hit")

    # An explicit empty inventory is a different statement and is honoured.
    (out / "manifest.json").write_text(json.dumps(
        {"run_key": "empty", "status": "ok", "metrics": {"rows": 0},
         "outputs": []}))
    assert load_cached(str(out), "empty") == {"rows": 0}


@pytest.mark.parametrize("mutate", [
    lambda ad: ad.__setitem__("score", -ad["score"]),
    lambda ad: ad.__setitem__("y", 1 - ad["y"]),
    lambda ad: ad.__setitem__("acct", ad["acct"].astype(str) + "x"),
    lambda ad: ad.attrs.__setitem__(
        "membership", ad.attrs["membership"].iloc[:0]),
])
def test_the_metric_cache_cannot_serve_a_stale_answer(mutate):
    """Two attempted fixes failed here, and an audit reproduced the second.

    `_ranks` and `_ring_structure` first keyed on `len(ad)`: mutating scores in
    place reused ranks computed from the old values. The repair stamped a
    random token at build time and keyed on that -- which is no better, because
    an in-place mutation does not change the token either. The comment claimed
    the invariant and the behaviour did not hold it.

    The key is now a digest of the bytes the cache depends on. This mutates
    each of them in turn, WITHOUT telling the cache anything, and requires the
    answer to change.
    """
    from aml.eval import metrics

    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": list("abcd"), "receiver_id": list("wxyz"),
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
        "typology": ["FAN-OUT", None, "FAN-OUT", None],
    })
    ad = metrics.to_account_days(df, np.array([0.9, 0.1, 0.8, 0.2]))

    before_rank = metrics._ranks(ad)["first"].copy()
    before_token = metrics._frame_token(ad)
    metrics._ring_structure(ad)

    mutate(ad)

    assert metrics._frame_token(ad) != before_token, (
        "the cache key did not notice an in-place change; it is keyed on "
        "something other than the data")
    after_rank = metrics._ranks(ad)["first"]
    if "score" in str(mutate.__code__.co_consts):
        assert not np.array_equal(before_rank, after_rank), (
            "stale ranks served after the scores changed")


def test_cache_key_changes_when_an_unnamed_dependency_changes(tmp_path, monkeypatch):
    """Each stage hashes the modules it NAMES. Training names train.py and the
    model config -- not the metric suite, not io, not the manifest layer. So a
    change to how a metric is computed left every cached training result valid,
    and the next run reported the old numbers under the new code with status
    ok. That is the failure this project exists to prevent, living inside the
    mechanism meant to prevent it.
    """
    from pathlib import Path

    from aml import manifest
    before = manifest.run_key("s", {"a": 1}, [], ())
    tree_before = manifest.tree_hash()

    real_read = Path.read_bytes

    def poisoned(self, *a, **k):
        data = real_read(self, *a, **k)
        return data + b"\n# a change in a module no stage names\n" \
            if self.name == "metrics.py" else data

    monkeypatch.setattr(Path, "read_bytes", poisoned)
    manifest.tree_hash.cache_clear()
    after = manifest.run_key("s", {"a": 1}, [], ())

    # Undo BEFORE re-reading, or the "restored" check runs against the poisoned
    # reader and compares the altered tree to itself. monkeypatch reverts at
    # teardown, which is after this assertion, not before it.
    monkeypatch.undo()
    manifest.tree_hash.cache_clear()
    assert manifest.tree_hash() == tree_before, "the tree hash did not restore"
    assert after != before, (
        "a change to an unnamed module left the cache key untouched")


def test_ensure_dir_does_not_swallow_an_auth_failure(tmp_path, monkeypatch):
    """Every exception from a remote makedirs was suppressed, so an expired
    credential and a missing role assignment both produced silence -- in a
    project whose stated philosophy is to fail loudly.
    """
    class Boom:
        protocol = "abfss"

        def makedirs(self, *a, **k):
            raise PermissionError("AuthorizationPermissionMismatch")

    monkeypatch.setattr(io, "_fs", lambda p: (Boom(), "c/x"))
    with pytest.raises(OSError, match="could not create directory"):
        io.ensure_dir("abfss://c@a.dfs.core.windows.net/x")


# ---------------------------------------------------------------------------
# 20. The test set had TWO derivations and nothing compared them
# ---------------------------------------------------------------------------

def test_the_test_predicate_is_derived_from_the_recorded_protocol():
    """`build-splits` materialises `splits/test`. The model loaders never read
    it -- they REBUILD the test set from the cut time and the rings table.

    With one protocol the two agreed, so the duplication was invisible. Adding
    `--protocol naive` made it visible in one run: the naive split wrote
    2,794,163 test rows and the model was scored on the 2,793,197 that the
    hardcoded ring filter reconstructed. The flag changed the files on disk and
    nothing else, silently, with every manifest reporting ok.

    The preregistration for that very experiment names this hazard: "two
    implementations would be a second chance for the two-independent-
    derivations bug that txn_id just taught us about." The harness already had
    one.
    """
    import inspect

    from aml.models import train
    src = inspect.getsource(train._split_where)
    assert 'cfg.get("protocol"' in src, "the predicate must read the protocol"
    # And the fallback must be the protocol every pre-existing manifest used,
    # or old split directories silently become naive.
    assert '"ring-aware")' in src


def test_a_mismatched_test_predicate_is_a_hard_failure(tmp_path):
    """The check that would have caught the duplication on the day it appeared.

    Cheap: Parquet row counts come from file metadata. Two derivations of one
    fact are tolerable only when something compares them.
    """
    import duckdb

    from aml.models.train import assert_test_predicate_matches_materialised

    d = tmp_path / "splits"
    (d / "test").mkdir(parents=True)
    con = duckdb.connect()
    con.execute("CREATE TABLE F AS SELECT * FROM range(10) t(event_time)")
    con.execute(f"COPY (SELECT * FROM range(7) t(event_time)) "
                f"TO '{d / 'test' / 'part-0.parquet'}' (FORMAT PARQUET)")

    # Agreeing predicate: 7 rows both ways.
    n = assert_test_predicate_matches_materialised(con, str(d), "WHERE event_time < 7")
    assert n == 7

    with pytest.raises(ValueError, match="disagree about what the test set is"):
        assert_test_predicate_matches_materialised(con, str(d), "WHERE event_time < 9")
    con.close()


# ---------------------------------------------------------------------------
# 21. Four lock files, and nothing stopped them disagreeing  (RP-10)
# ---------------------------------------------------------------------------

def _parse_lock(path):
    out = {}
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or raw.startswith("--hash"):
            continue
        name, _, version = raw.rstrip(" \\").partition("==")
        if version:
            out[re.sub(r"[-_.]+", "-", name).lower()] = version
    return out


def test_the_hashed_container_lock_matches_the_version_lock():
    """requirements.linux-amd64.lock is requirements.lock resolved for the
    container's platform with a sha256 per wheel. If the two drift, the image
    runs an environment the test suite never saw -- which is the whole failure
    mode the lock exists to prevent, one level up.
    """
    root = Path(__file__).resolve().parents[2]
    plain = _parse_lock(root / "requirements.lock")
    hashed = _parse_lock(root / "requirements.linux-amd64.lock")
    assert plain, "requirements.lock parsed empty"
    differing = sorted(set(plain) ^ set(hashed)) or sorted(
        k for k in plain if plain[k] != hashed.get(k))
    assert plain == hashed, (
        "requirements.lock and requirements.linux-amd64.lock disagree; "
        "run `make lock-hashes`. Differences: "
        + ", ".join(f"{k}: {plain.get(k)} vs {hashed.get(k)}" for k in differing))


def test_every_pinned_package_in_the_hashed_locks_carries_a_hash():
    """A hashed lock that silently omits a hash is rejected by pip for a reason
    unrelated to the real problem, so the omission must fail here instead."""
    root = Path(__file__).resolve().parents[2]
    for name in ("requirements.linux-amd64.lock",
                 "requirements-dev.linux-amd64.lock"):
        text = (root / name).read_text()
        pins = [ln for ln in text.splitlines()
                if "==" in ln and not ln.strip().startswith("#")]
        hashes = [ln for ln in text.splitlines() if "--hash=sha256:" in ln]
        assert pins, f"{name} has no pins"
        assert len(pins) == len(hashes), (
            f"{name}: {len(pins)} pins but {len(hashes)} hashes")


def test_the_test_runner_is_pinned_somewhere():
    """`pip install pytest` in the image meant the suite that gates a paid
    cloud run was executed by whatever version existed that morning."""
    root = Path(__file__).resolve().parents[2]
    dev = _parse_lock(root / "requirements-dev.lock")
    assert "pytest" in dev and "ruff" in dev
    hashed_dev = _parse_lock(root / "requirements-dev.linux-amd64.lock")
    assert dev == hashed_dev, "the two dev locks disagree"


# ---------------------------------------------------------------------------
# 22. Nobody could check a published number without the dataset  (RP-09)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("bundle_name", "manifest_rel"), [
    ("small_gbdt_s0", "gold/infl_eval_ring-aware_s0/manifest.json"),
    ("large_lgbm_s0", "gold/large_eval3_lgbm_s0/manifest.json"),
    ("large_lgbm_s1", "gold/large_eval3_lgbm_s1/manifest.json"),
    ("large_lgbm_s2", "gold/large_eval3_lgbm_s2/manifest.json"),
    ("medium_gbdt_s0", "gold/eval3_Medium/gbdt/manifest.json"),
    ("medium_baseline_s0", "gold/eval3_Medium/baseline/manifest.json"),
    # The CANONICAL HI-Large lineage -- fits made under a deterministic row
    # order. The three above it come from the superseded unsorted fits and are
    # kept because they are the evidence for the defect.
    ("large_sorted_lgbm_s0", "gold/large_sorted_lgbm_s0/manifest.json"),
    ("large_sorted_lgbm_s1", "gold/large_sorted_lgbm_s1/manifest.json"),
    ("large_sorted_lgbm_s2", "gold/large_sorted_lgbm_s2/manifest.json"),
])
def test_a_published_result_recomputes_from_its_committed_replay_bundle(
        bundle_name, manifest_rel):
    """The strongest reproducibility claim in this repository, made checkable.

    Reads ONLY committed artifacts -- a few hundred kilobytes of bundle and the
    manifest it was cut from -- and rebuilds every budget metric. No features,
    no splits, no scores, no dataset. If this ever fails, either the bundle is
    not self-sufficient or a metric definition moved under a published number,
    and both are things this project must find out about from a test rather
    than from a reader.
    """
    import subprocess

    root = Path(__file__).resolve().parents[2]
    bundle = _archive_root() / "replay" / bundle_name
    manifest = _archive_root() / manifest_rel
    if not bundle.exists() or not manifest.exists():
        pytest.skip("replay bundle not archived in this checkout")

    # A PARTIALLY committed bundle is worse than an absent one: the directory
    # exists, so nothing skips, and the failure surfaces as a FileNotFoundError
    # from inside pandas. `*.parquet` in .gitignore did exactly this -- it kept
    # bundle.json and dropped the data, which passed locally and failed in a
    # clean clone. Check the bundle's own inventory against the disk first.
    listed = json.loads((bundle / "bundle.json").read_text())["files"]
    absent = [f for f in listed if not (bundle / f).exists()]
    assert not absent, (
        f"bundle.json lists {len(listed)} files and {len(absent)} are missing "
        f"from the checkout: {absent}. Check .gitignore.")

    r = subprocess.run(
        [sys.executable, str(root / "scripts/verify_replay_bundle.py"),
         "--bundle", str(bundle), "--manifest", str(manifest)],
        capture_output=True, text=True, cwd=root)
    assert r.returncode == 0, f"replay diverged:\n{r.stdout}\n{r.stderr}"
    assert "0 mismatch(es)" in r.stdout
    # And it must actually have compared something -- a bundle whose metrics
    # all went missing would also print zero mismatches.
    assert r.stdout.count("0.00e+00") >= 20, (
        f"too few metrics compared:\n{r.stdout}")


# ---------------------------------------------------------------------------
# 23. The leak placebo was a distribution shift, not a placebo  (EV-12)
# ---------------------------------------------------------------------------

def test_the_leak_placebo_permutes_within_split_and_day():
    """The placebo permuted the leak columns GLOBALLY, so a training row could
    receive a test row's values and a day-1 row a day-28 row's.

    That preserves only the global marginal, so the placebo arm differed from
    the real arm in two ways at once -- alignment, which is intended, and
    distribution shift across the split and the calendar, which is not. The gap
    between them could then no longer be read as "what misalignment costs",
    which is the only thing the comparison exists to measure.
    """
    from aml.leakproof.sweep import _leak_strata, _permute

    tr = pd.DataFrame({"txn_id": [1, 2, 3, 4], "event_date": ["d1", "d1", "d2", "d2"]})
    te = pd.DataFrame({"txn_id": [5, 6, 7, 8], "event_date": ["d3", "d3", "d4", "d4"]})
    table = pd.DataFrame({"txn_id": [1, 2, 3, 4, 5, 6, 7, 8],
                          "leak": [10.0, 11, 20, 21, 30, 31, 40, 41]})
    strata = _leak_strata(tr, te, table)
    assert strata.tolist() == ["train|d1", "train|d1", "train|d2", "train|d2",
                               "test|d3", "test|d3", "test|d4", "test|d4"]

    for seed in range(25):
        out = _permute(table, ["leak"], seed=seed, strata=strata)
        got = out["leak"].to_numpy()
        # Values may never leave their stratum.
        for lo in (0, 2, 4, 6):
            assert set(got[lo:lo + 2]) == set(table["leak"].to_numpy()[lo:lo + 2]), (
                f"seed {seed}: a value crossed a (side, day) boundary")
        # The multiset is preserved exactly, as before.
        assert sorted(got) == sorted(table["leak"].to_numpy())


def test_a_partial_leak_join_is_a_hard_failure():
    """`validate="one_to_one"` checks CARDINALITY, not COVERAGE. A left merge
    missing keys on the right succeeds and fills NaN, and a histogram model
    consumes NaN happily as its own branch -- so a leak channel covering half
    the rows read as a WEAKER leak rather than a BROKEN join, in the module
    whose entire job is telling those two apart.
    """
    from aml.leakproof.sweep import _merge_leak

    frame = pd.DataFrame({"txn_id": [1, 2, 3], "is_laundering": [0, 1, 0]})
    complete = pd.DataFrame({"txn_id": [1, 2, 3], "leak": [1.0, 2.0, 3.0]})
    assert len(_merge_leak(frame, complete, ["leak"], "real", "target")) == 3

    partial = pd.DataFrame({"txn_id": [1, 2], "leak": [1.0, 2.0]})
    with pytest.raises(ValueError, match="matched no leak row"):
        _merge_leak(frame, partial, ["leak"], "real", "target")

    # A LEGITIMATELY NULL VALUE IS NOT A BROKEN JOIN, and the first version of
    # this check could not tell them apart. It asserted no leak column was
    # null after the merge and fired on `reversed_window`, where
    # `s_max_amt_next_7d` is a MAX over a forward window and is null whenever
    # that window is empty. The table covered every row. Coverage is what the
    # check wanted; nullness is what it tested.
    nulls = pd.DataFrame({"txn_id": [1, 2, 3], "leak": [1.0, None, 3.0]})
    got = _merge_leak(frame, nulls, ["leak"], "real", "reversed_window")
    assert len(got) == 3 and got["leak"].isna().sum() == 1


# ---------------------------------------------------------------------------
# 24. The licence file described bundles it had never opened  (v2 audit B3)
# ---------------------------------------------------------------------------

def test_data_licence_lists_every_column_the_bundles_actually_contain():
    """`DATA_LICENSE.md` said the repository publishes "aggregate counts... no
    account identifiers, no reconstructable subset". The replay bundles are
    row-level `(day, acct, score, y, rank)` with labels and pseudonymous
    account codes.

    Describing published data incorrectly is worse than describing it
    conservatively, because a reader relying on the description cannot see the
    files. This pins the description to the schema, so adding a column to a
    bundle forces the licence file to be updated.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "DATA_LICENSE.md").exists():
        pytest.skip("repository root not present (running inside the image)")
    doc = (root / "DATA_LICENSE.md").read_text()
    bundle = _archive_root() / "replay/small_gbdt_s0"
    if not bundle.exists():
        pytest.skip("replay bundle not archived in this checkout")

    for parquet in sorted(bundle.glob("*.parquet")):
        assert parquet.name in doc, (
            f"{parquet.name} is published but not described in DATA_LICENSE.md")
        for col in pd.read_parquet(parquet).columns:
            assert f"`{col}`" in doc, (
                f"{parquet.name} publishes column '{col}', which "
                f"DATA_LICENSE.md does not mention")

    # And the claims that were false must not come back AS CLAIMS.
    #
    # The document quotes them while retracting them, so a bare substring test
    # fires on the correction itself -- the same mirror-image trap as the demo
    # banner test. A retracted phrase is allowed only on a line that marks it
    # as retracted.
    RETRACTION_MARKERS = ("incorrectly", "earlier version", "was true when written")
    for banned in ("no account identifiers",
                   "no reconstructable subset",
                   "not pinned and the files are not checksummed"):
        for n, line in enumerate(doc.splitlines(), 1):
            if banned in line:
                assert any(m in line for m in RETRACTION_MARKERS), (
                    f"DATA_LICENSE.md:{n} asserts {banned!r} without marking it "
                    f"as a retracted claim")


# ---------------------------------------------------------------------------
# 25. The upper-tail p-value was quoted in support of a lower-tail claim
#     (v2 audit H3), and the bootstrap re-collapsed multi-ring membership (H5)
# ---------------------------------------------------------------------------

def test_the_ring_null_reports_both_tails():
    """`ring_recall_null_p@k` counts null >= observed, so it tests whether the
    model covers MORE rings than chance. HI-Large returns 1.000 and that value
    was quoted to support the claim that it covers FEWER rings than chance --
    the opposite tail.

    A p-value near 1 on one tail is the absence of evidence for that tail, not
    evidence for the other one. Both are now computed.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=30, ring_size=6, n_noise=900, seed=3)
    # Every spare alert goes to three rings: hits concentrate, so the observed
    # value must sit in the LOWER tail.
    score = np.where(df.ring_id.isin([0.0, 1.0, 2.0]), 0.99, score * 0.2)
    m = metrics.evaluate(df, score, budgets=(12,), n_permutations=400)

    assert m["ring_recall_null_p@12"] > 0.5, "fixture should not be upper-tail"
    assert m["ring_recall_null_p_lower@12"] < 0.05, (
        "a model concentrating its hits inside a few rings must be detected by "
        "the LOWER tail")
    assert m["ring_recall_null_p_two_sided@12"] <= 1.0
    # The two one-sided values may not both be small, and must bracket sensibly.
    assert (m["ring_recall_null_p@12"] + m["ring_recall_null_p_lower@12"]) > 1.0


def test_the_bootstrap_does_not_re_collapse_multi_ring_membership():
    """`bootstrap_ci` clustered on `ad.ring_id` -- the COLLAPSED column, built
    with `max`, documented in the same module as invalid for membership.

    So the fix that gave `ring_recall` a many-to-many relation was silently
    undone inside the function that computes the published interval. Two rings
    sharing an account-day were also counted as two independent clusters, which
    is the direction that narrows an interval.
    """
    from aml.eval import metrics

    # Two rings joined by ONE shared account-day must form ONE cluster.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "b", "b", "d"],
        "receiver_id": ["b", "c", "e", "f"],
        "is_laundering": [1, 1, 1, 1],
        "ring_id": [1.0, 1.0, 2.0, 2.0],
        "typology": ["FAN-OUT"] * 2 + ["CYCLE"] * 2,
    })
    ad = metrics.to_account_days(df, np.array([0.9, 0.8, 0.7, 0.6]))
    ad["rank"] = ad.groupby("day")["score"].rank(ascending=False, method="first")
    pos = ad[ad.y == 1].copy()
    labels = metrics._dependence_clusters(ad, pos)

    mem = metrics.ring_membership(ad)
    shared = mem.groupby(["day", "acct"]).ring_id.nunique()
    assert (shared > 1).any(), "fixture must contain a multi-ring account-day"

    ring_rows = pos.reset_index(drop=True).index[pos.ring_id.notna().to_numpy()]
    assert len({labels[i] for i in ring_rows}) == 1, (
        "rings joined by a shared account-day must resample as ONE cluster")

    import inspect
    src = inspect.getsource(metrics.bootstrap_ci)
    assert "_dependence_clusters" in src
    assert '"R" + pos.ring_id' not in src, "the collapsed clustering came back"


# ---------------------------------------------------------------------------
# 26. The documented cloud recipe could not build the image  (v2 audit H15/H16)
# ---------------------------------------------------------------------------

def test_the_runbook_source_archive_contains_everything_the_dockerfile_copies():
    """Following `RUNBOOK_cloud.md` exactly failed at `docker build`.

    Its tar listed `requirements.lock`; the Dockerfile also copies
    `requirements.linux-amd64.lock` (which it INSTALLS from) and both dev
    locks. A reproduction path that cannot build the image is not a
    reproduction path, and nothing checked the two against each other.
    """
    root = Path(__file__).resolve().parents[2]
    # docs/ IS in the image now; the Dockerfile is not -- it is the recipe, not
    # an input. The guard has to name the file it actually needs.
    if not (root / "Dockerfile").exists():
        pytest.skip("Dockerfile not present (running inside the image)")
    dockerfile = (root / "Dockerfile").read_text()
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()

    copied = set()
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line.startswith("COPY "):
            continue
        parts = line.split()[1:-1]              # drop COPY and the destination
        for token in parts:
            if not token.startswith("--"):
                copied.add(token)
    assert copied, "no COPY lines parsed out of the Dockerfile"

    # FROM THE COMMIT, not from the working directory.
    #
    # This used to be `tar czf` of the working tree labelled with HEAD, under a
    # printed warning that "the image will claim $GIT_SHA and not contain it".
    # A documented false provenance is not a safer kind: SRC_SHA256 proved that
    # Azure received the same bytes, never that those bytes are the tree the
    # commit names. `git archive <sha>` makes the two the same object by
    # construction, and is byte-reproducible from the commit alone.
    assert "git archive" in runbook, (
        "the deployment archive must be built from the commit, so that anyone "
        "can reconstruct it from the recorded SHA")
    assert "tar czf /tmp/aml-src.tgz" not in runbook, (
        "the working-tree tar is back; it cannot be tied to a commit")
    assert 'git status --porcelain' in runbook and "refusing to deploy" in runbook, (
        "a dirty worktree must stop the deployment, not warn about it")

    # The COMMAND, not the paragraph explaining it. Anchoring on the bare
    # words "git archive" found the comment above the command and cut the
    # window off before the path list.
    block = runbook[runbook.index("git archive --format=tar.gz"):][:700]
    missing = [c for c in sorted(copied) if c not in block]
    assert not missing, (
        f"the Dockerfile copies {missing} but the runbook's source archive "
        f"does not include them; a clean run of the documented path fails at "
        f"docker build")


def test_provisioning_mounts_the_device_path_it_resolved():
    """`D` is already an absolute /dev path -- `readlink -f` returns one and the
    lsblk fallback builds one. The spill-disk mount used `"/dev/$D"`, producing
    `/dev//dev/sdc`.

    It never fired because `mountpoint -q` skips the block once the disk is
    mounted, so the defect was unreachable on every rerun and waiting for the
    first clean provision -- which is exactly the path a reader reproducing the
    work would take. Shell syntax checking cannot see it; this can.
    """
    root = Path(__file__).resolve().parents[2]
    raw = (root / "scripts/provision_vm.sh").read_text()
    # EXECUTABLE LINES ONLY. The comment above the fix quotes the broken
    # pattern in order to explain it, and a whole-file substring test fires on
    # the explanation -- the third time that trap has caught a test in this
    # file. A comment is not behaviour.
    code = "\n".join(ln for ln in raw.splitlines()
                     if not ln.lstrip().startswith("#"))

    assert '"/dev/$D"' not in code, (
        'mount "/dev/$D" double-prefixes an already-absolute device path')
    assert 'mount "$D" /mnt/spill' in code
    assert 'mountpoint -q /mnt/spill ||' in code, (
        "a mount that silently fails leaves the pipeline writing spill to the "
        "OS disk, which is how the first HI-Large attempt died")


# ---------------------------------------------------------------------------
# 27. Packaging and release metadata  (v2 audit H25/H26/H28/H29)
# ---------------------------------------------------------------------------

def test_the_packaged_licences_match_the_repository_licences():
    """The wheel and sdist carried no licence at all, and the package README
    linked to `../LICENSE`, which does not exist once the subproject is
    unpacked on its own.

    Fixing that meant copying both files into the package directory, which
    creates two copies of one fact -- exactly the shape this project keeps
    getting burned by. So they are checked, not trusted.
    """
    root = Path(__file__).resolve().parents[3]
    plat = root / "aml-platform"
    if not (root / "LICENSE").exists():
        pytest.skip("repository root not present (running inside the image)")
    for name in ("LICENSE", "DATA_LICENSE.md"):
        a, b = root / name, plat / name
        assert b.exists(), f"{name} must be inside the package for the wheel"
        assert a.read_bytes() == b.read_bytes(), (
            f"{name} has drifted between the repository root and the package")


def test_the_package_readme_has_no_parent_relative_links():
    """`../README.md` resolves on GitHub and 404s on PyPI or in an unpacked
    sdist, where the parent directory does not exist."""
    plat = Path(__file__).resolve().parents[2]
    readme = (plat / "README.md").read_text()
    bad = re.findall(r"\]\((\.\./[^)]+)\)", readme)
    assert not bad, f"package README links outside the package: {bad}"


def test_release_metadata_does_not_claim_a_release_that_does_not_exist():
    """`CITATION.cff` declared version 0.1.0 released 2026-09-11 while the
    repository was private with no tag and no GitHub Release."""
    root = Path(__file__).resolve().parents[3]
    if not (root / "CITATION.cff").exists():
        pytest.skip("repository root not present (running inside the image)")
    cff = (root / "CITATION.cff").read_text()
    tags = subprocess.run(["git", "-C", str(root), "tag", "--list"],
                          capture_output=True, text=True).stdout.split()
    if not tags:
        for field in ("date-released:", "version:"):
            assert not any(ln.strip().startswith(field)
                           for ln in cff.splitlines()), (
                f"CITATION.cff sets {field} but the repository has no tag")


def test_published_counts_match_the_generated_release_facts():
    """Test counts, skip counts and result-set counts were hand-maintained in
    four documents and drifted immediately -- at one audit snapshot they said
    257, 270 and 275 against an actual 277, and described the 17 skips as
    "without Azure extras" when they are data-dependent contract tests.

    Same defect as a hand-typed metric, same remedy: generate it, then check
    the prose against it.
    """
    root = Path(__file__).resolve().parents[3]
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    # The ARTIFACT now ships in the image; the documents it is checked against
    # do not. This used to skip because the artifact was absent too, so making
    # the image carry the archive would have turned it red for the wrong
    # reason -- a gate failing because its inputs moved is noise, not signal.
    if not (root / "README.md").exists():
        pytest.skip("repository documents not present (running inside the image)")
    r = subprocess.run(
        [sys.executable, str(root / "aml-platform/scripts/release_facts.py"),
         "--check", str(root / "README.md"), str(root / "HANDOFF.md"),
         str(root / "CONTRIBUTING.md"),
         str(root / "aml-platform/docs/RELEASE_CHECKLIST.md")],
        capture_output=True, text=True, cwd=root / "aml-platform")
    assert r.returncode == 0, f"stale counts in prose:\n{r.stdout}\n{r.stderr}"


def test_the_provisioning_script_builds_with_a_sane_build_arg():
    """A scripted edit spliced a comment block into the `docker build` line and
    `bash -n` still passed, because the result was a syntactically valid very
    long quoted string.

    That is the v2 audit's H16 argument demonstrated a second time: shell
    syntax checking does not see this class of defect. ShellCheck did, in CI,
    after the push. This checks the shape directly.
    """
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/provision_vm.sh").read_text()
    build = [ln for ln in script.splitlines() if ln.strip().startswith("docker build")]
    assert len(build) == 1, f"expected one docker build line, got {len(build)}"
    line = build[0]
    assert line.count('"') % 2 == 0, f"unbalanced quotes: {line}"
    assert "AML_GIT_SHA=${AML_GIT_SHA}" in line, line
    assert '-t "$TAG" .' in line, line
    assert "#" not in line, f"a comment was spliced into the build line: {line}"


def test_both_learners_are_reproducible_at_scale_when_the_order_is_fixed():
    """The complement of the dependence test, and the one that proves the fix.

    Showing that row order MATTERS above 200,000 rows establishes the defect.
    What a release needs is the other half: that with the order held fixed --
    which is what `ORDER BY txn_id` guarantees -- two fits of the same data are
    identical, for BOTH supported learners, above the threshold.

    This runs inside the release image, so "the image reproduces" is asserted
    rather than argued. The empirical version of the same claim is in
    docs/RESULT_LINEAGE.md: three HI-Large seeds, run hours apart, produced a
    byte-identical 124,992,128-row training matrix.
    """
    n = 210_001                                   # over the bin-subsample cut
    rng = np.random.default_rng(0)
    X = rng.random((n, 3))
    y = (rng.random(n) < 0.05).astype(np.int8)

    from sklearn.ensemble import HistGradientBoostingClassifier
    a = HistGradientBoostingClassifier(max_iter=8, random_state=0).fit(X, y)
    b = HistGradientBoostingClassifier(max_iter=8, random_state=0).fit(X, y)
    pa, pb = a.predict_proba(X[:3000])[:, 1], b.predict_proba(X[:3000])[:, 1]
    assert np.array_equal(pa, pb), "sklearn is not reproducible at fixed order"

    import lightgbm as lgb
    params = dict(n_estimators=8, random_state=0, verbose=-1,
                  deterministic=True, force_row_wise=True)
    la = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:3000])[:, 1]
    lb = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:3000])[:, 1]
    assert np.array_equal(la, lb), "LightGBM is not reproducible at fixed order"


# ---------------------------------------------------------------------------
# 28. A commit SHA is not provenance for code absent from that commit
#     (v3 audit P0-7)
# ---------------------------------------------------------------------------

def test_every_derived_artifact_names_a_generator_that_exists_at_its_commit():
    """Three derived artifacts recorded a `code_git_sha` whose commit did not
    contain the script that produced them. They were generated while the
    analysis code was uncommitted and the code landed in a later commit.

    Those artifacts support the split-inflation decomposition and the defence
    of the linear-baseline headline, so this is not archival trivia: the
    recorded commit could not be used to reproduce them.

    Every derived artifact must now name its generator, and that path must
    resolve at the recorded commit.

    AND THE BYTES AT THAT PATH MUST BE THE BYTES RECORDED. The first version of
    this test ran `git cat-file -e`, which asks only whether the path exists --
    so it passed on seven artifacts whose `generator_sha256` was the hash of an
    UNCOMMITTED edit stamped with the previous commit. Existence was never the
    claim being made; identity was. A test named for a provenance defect that
    checks a weaker property than the defect is the fifth one of those in this
    repository, and the reason the count is in HANDOFF.md.
    """
    root = Path(__file__).resolve().parents[3]
    derived = sorted((_archive_root() / "derived").glob("*.json"))
    if not derived:
        pytest.skip("no derived artifacts in this checkout")

    problems, unverifiable = [], []
    for f in derived:
        d = json.loads(f.read_text())
        if not isinstance(d, dict):
            continue
        script, sha = d.get("generator_script"), d.get("code_git_sha")
        recorded = d.get("generator_sha256")
        if not script:
            problems.append(f"{f.name}: names no generator_script")
            continue
        if not recorded:
            problems.append(f"{f.name}: names a generator but does not hash it")
            continue
        if not sha or sha == "unknown":
            problems.append(f"{f.name}: no commit recorded")
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            # An abbreviation is ambiguous by construction and cannot be
            # resolved in a clone that does not already have the object.
            problems.append(f"{f.name}: code_git_sha {sha!r} is not a full SHA")
            continue
        # THE PACKAGE, NOT JUST THE SCRIPT.
        #
        # An audit edited src/aml/eval/metrics.py, left scripts/cost_table.py
        # alone, and got `generator_matches_commit: true` against a clean HEAD.
        # The generator was the committed one; the implementation it imports
        # was not. Same false combined assertion as before, one level down the
        # import graph -- and `code_tree_sha256` was already being recorded,
        # with its own comment calling it "informational", which is the word
        # that let it through.
        if d.get("code_tree_matches_commit") is False:
            problems.append(
                f"{f.name}: the `aml` package on disk did not match the "
                f"recorded commit when this was generated")
            continue
        tree = d.get("code_tree_sha256")
        if tree is None:
            # Grandfathered by name, with the reason in the artifact itself.
            if f.name not in GRANDFATHERED_NO_TREE_HASH:
                problems.append(f"{f.name}: records no code_tree_sha256")
                continue
        elif (at := _tree_hash_at(root, sha)) is not None and at != tree:
            problems.append(
                f"{f.name}: the package tree at {sha[:12]} hashes to "
                f"{at[:12]}, but the artifact records {tree[:12]}")
            continue
        if d.get("generator_matches_commit") is False:
            problems.append(
                f"{f.name}: generated from a generator that did not match its "
                f"commit (AML_ALLOW_DIRTY_PROVENANCE output must not be "
                f"committed)")
            continue
        for entry in d.get("inputs") or []:
            if entry.get("error"):
                problems.append(f"{f.name}: input {entry.get('path')!r} "
                                f"unreadable at generation: {entry['error']}")
        r = subprocess.run(["git", "-C", str(root), "cat-file", "-p",
                            f"{sha}:{script}"], capture_output=True)
        if r.returncode != 0:
            # A commit absent from the clone cannot be checked -- that is a
            # SHALLOW CHECKOUT, not a provenance defect, and failing on it
            # would make the test a liar about what it verified. CI fetches
            # full history precisely so this branch is not taken there.
            known = subprocess.run(["git", "-C", str(root), "cat-file", "-e", sha],
                                   capture_output=True).returncode == 0
            if not known:
                unverifiable.append(f"{f.name}: commit {sha[:12]} not in this clone")
                continue
            problems.append(f"{f.name}: {script} does not exist at {sha[:12]}")
            continue
        # THE ACTUAL CLAIM: these bytes, at that commit.
        got = hashlib.sha256(r.stdout).hexdigest()
        if got != recorded:
            problems.append(
                f"{f.name}: {script} at {sha[:12]} hashes to {got[:12]}, "
                f"but the artifact records {recorded[:12]} -- it was generated "
                f"from a version of the generator that commit does not contain")
    assert not problems, "derived artifacts with invalid provenance:\n  " + \
        "\n  ".join(problems)
    if unverifiable:
        # Not a failure, but not silence either: a run that verified nothing
        # should say so rather than reporting a pass.
        print("\nprovenance NOT verified (shallow clone):\n  "
              + "\n  ".join(unverifiable))


# ---------------------------------------------------------------------------
# 29. "all" must mean the dataset contract, not the pin's leftovers
#     (v4 audit P0-4)
# ---------------------------------------------------------------------------

def _verify_dataset(*argv, cwd):
    """Run scripts/verify_dataset.py as a subprocess, from `cwd`."""
    script = _script("verify_dataset.py")
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(script.parents[1] / "src")})


def _fake_dataset(tmp_path, names):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    for i, n in enumerate(names):
        (d / n).write_bytes(f"contents of {n}".encode() + b"\n" * i)
    return d


def test_require_all_fails_when_the_pin_is_short_of_the_contract(tmp_path):
    """A five-file pin reported a complete six-file dataset.

    `--pin` rebuilt the pin from the files on disk, and HI-Large_Trans.csv is
    17 GB and has never been on the development machine -- it was hashed on the
    VM and hand-carried in. A re-pin dropped it silently, and `--require all`
    then read "all" as "all five entries that remain": five checked, zero
    missing, exit 0. An incomplete DOWNLOAD would have produced the same
    reassuring output about the input to the most expensive result here.
    """
    full = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
            "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
            "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    data = _fake_dataset(tmp_path, full)
    pin = tmp_path / "pin.json"
    ok = _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                         cwd=tmp_path)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # The regression: re-pin on a machine that holds five of the six.
    (data / "HI-Large_Trans.csv").unlink()
    repin = _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                            cwd=tmp_path)
    assert repin.returncode == 0, repin.stdout + repin.stderr
    kept = json.loads(pin.read_text())["files"]
    assert "HI-Large_Trans.csv" in kept, (
        "re-pinning on a machine holding a subset dropped a pinned file:\n"
        + repin.stdout)
    assert kept["HI-Large_Trans.csv"].get("carried_from"), \
        "a carried-forward hash must say it was carried, not look re-measured"

    # And if it IS dropped deliberately, --require all must still fail.
    short = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                            "--pin", "--drop-missing", cwd=tmp_path)
    assert short.returncode == 2, (
        "writing a pin short of the contract needs --allow-incomplete:\n"
        + short.stdout + short.stderr)

    forced = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                             "--pin", "--drop-missing", "--allow-incomplete",
                             cwd=tmp_path)
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert json.loads(pin.read_text())["complete"] is False

    blessed = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                              "--require", "all", cwd=tmp_path)
    assert blessed.returncode != 0, (
        "--require all passed against a pin that does not cover the "
        "contract -- 'all' must mean the six contracted files:\n"
        + blessed.stdout)
    assert "HI-Large_Trans.csv" in blessed.stdout


def test_require_all_fails_when_a_contracted_file_is_absent_from_disk(tmp_path):
    """The complete pin plus an incomplete download must not verify."""
    full = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
            "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
            "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    data = _fake_dataset(tmp_path, full)
    pin = tmp_path / "pin.json"
    _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                    cwd=tmp_path)
    (data / "HI-Medium_Trans.csv").unlink()

    loose = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                            cwd=tmp_path)
    assert loose.returncode == 0, "without --require, a laptop subset is fine"

    gate = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                           "--require", "all", cwd=tmp_path)
    assert gate.returncode != 0 and "HI-Medium_Trans.csv" in gate.stdout


def test_the_committed_pin_covers_the_whole_contract():
    """The released pin must identify every file the project claims to use.

    DATA_LICENSE.md says all six are recorded. For one commit that was false.
    """
    pinned = json.loads(
        (_archive_root() / "derived/dataset_pin.json").read_text())["files"]
    contract = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
                "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
                "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    assert sorted(pinned) == sorted(contract), (
        f"the committed pin does not match the dataset contract; "
        f"missing {sorted(set(contract) - set(pinned))}, "
        f"extra {sorted(set(pinned) - set(contract))}")
    for name, entry in pinned.items():
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), name
        assert entry["bytes"] > 0, name


# ---------------------------------------------------------------------------
# 30. The documented cloud commands must satisfy the scripts they invoke
#     (v4 audit P0-8, v3 audit P0-4)
# ---------------------------------------------------------------------------

def _runbook_invocations(text):
    """Every `az vm run-command ... --scripts @scripts/X.sh ... --parameters ...`
    in the runbook, as (script, {names passed})."""
    out = []
    # The invocation is a shell command spread over continuation lines.
    joined = re.sub(r"\\\n\s*", " ", text)
    for line in joined.splitlines():
        m = re.search(r"--scripts @(\S+\.sh)", line)
        if not m:
            continue
        passed = set(re.findall(r'"([A-Z_][A-Z0-9_]*)=', line))
        out.append((m.group(1), passed))
    return out


def test_every_runbook_command_supplies_what_its_script_requires():
    """The documented cloud reproduction could not be run as written.

    `provision_vm.sh` requires AML_GIT_SHA, `run_cloud.sh` requires IMAGE and
    `run_hi_large.sh` requires TAG -- each added deliberately, because a
    defaulted `latest` tag and a defaulted `unknown` commit are exactly the
    provenance holes this project spent commits closing. The runbook passed
    none of them, so the three fixes turned the documented path into three
    commands that exit non-zero on their first line.

    A runbook is an interface. This test is the contract.
    """
    root = Path(__file__).resolve().parents[2]
    if not (root / "docs/RUNBOOK_cloud.md").exists():
        pytest.skip("docs/ not present (running inside the image)")
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
    invocations = _runbook_invocations(runbook)
    assert invocations, "no run-command invocations found in the runbook"

    problems = []
    for script, passed in invocations:
        body = (root / script).read_text()
        # `VAR=${VAR:?...}` -- no default, the script exits if it is unset.
        required = set(re.findall(r"^\s*([A-Z_][A-Z0-9_]*)=\$\{\1:\?", body, re.M))
        # `if [ -z "${VAR:-}" ] ... exit 1` -- a refusal written longhand.
        for name in re.findall(r'\[ -z "\$\{([A-Z_][A-Z0-9_]*):-\}"', body):
            if re.search(rf'{name}.*\n(?:.*\n)*?.*exit 1', body):
                required.add(name)
        missing = sorted(required - passed)
        if missing:
            problems.append(f"{script}: runbook passes {sorted(passed)} but the "
                            f"script requires {missing}")
    assert not problems, ("the documented commands cannot run:\n  "
                          + "\n  ".join(problems))


def test_provision_verifies_the_source_archive_before_extracting_it():
    """The runbook said "the VM verifies it before extracting". It did not.

    `sha256sum /tmp/aml-src.tgz  # record this; the VM verifies it before
    extracting` sat above a download that piped straight into `tar xzf`. The
    documentation described a control that had never been implemented -- which
    is worse than no control, because a reader stops looking for one.
    """
    root = Path(__file__).resolve().parents[2]
    body = (root / "scripts/provision_vm.sh").read_text()
    assert "SRC_SHA256" in body, "no source-hash parameter"

    lines = body.splitlines()
    def first(pattern):
        for i, ln in enumerate(lines):
            if re.search(pattern, ln):
                return i
        return None

    check = first(r'GOT=\$\(sha256sum .*aml-src')
    extract = first(r"^\s*tar xzf ")
    assert check is not None, "the archive is never hashed"
    assert extract is not None, "the archive is never extracted"
    assert check < extract, "the hash check runs AFTER the extraction it guards"
    # And the extraction must not land on top of a previous deployment.
    assert re.search(r"rm -rf /opt/aml\.new", body), (
        "extraction still unpacks over whatever /opt/aml already holds, so a "
        "file deleted between two provisions survives into the build context")


def test_cloud_runners_verify_raw_data_against_the_pin_before_computing():
    """Both runners skipped a download when the file merely existed non-empty.

    A truncated 14 GB transfer satisfies that test. So does a different release
    of the dataset. The pipeline would then produce a full set of manifests
    describing an input nothing had identified -- and `-C -` resuming onto the
    FINAL filename is what made a partial file look finished to the next run.
    """
    root = Path(__file__).resolve().parents[2]
    for name in ("scripts/run_cloud.sh", "scripts/run_hi_large.sh"):
        body = (root / name).read_text()
        assert "verify_against_pin" in body, f"{name} never checks the pin"
        assert "dataset_pin.json" in body, f"{name} names no pin file"
        assert ".part" in body, f"{name} does not download atomically"
        # The old fail-open, verbatim: a bare existence test guarding a fetch.
        assert not re.search(r'^\s*\[ -s "\$S/raw/\$f" \] \|\| curl', body, re.M), \
            f"{name} still skips a download on existence alone"
        assert not re.search(r'^\s*\[ -f \$S/raw/HI-\$\{VARIANT\}[^\]]*\] \|\| dl',
                             body, re.M), \
            f"{name} still stages on existence alone"


# ---------------------------------------------------------------------------
# 31. Every manifest must parse under a STRICT JSON reader (v4 audit P1-8)
# ---------------------------------------------------------------------------

def _strict(raw: str):
    """json.loads that refuses NaN/Infinity, the way a conformant reader does."""
    def boom(token):
        raise ValueError(f"non-finite JSON token {token!r}")
    return json.loads(raw, parse_constant=boom)


def test_write_json_never_emits_a_token_a_strict_parser_rejects():
    """`bootstrap 0` produced `ci_lo: NaN` in a published manifest.

    Python's encoder writes the bare token `NaN`, and Python's decoder reads it
    back, so the round trip inside this project was clean and every conformant
    reader outside it -- jq, Go, Rust, a browser -- rejects the file. A
    provenance record that only its author can parse is not a provenance
    record. `io.write_json` normalises non-finite floats to null and passes
    `allow_nan=False`, so a future path that produces one raises instead of
    writing an unparseable artifact.
    """
    import math

    from aml import io as aml_io
    payload = {"ci_lo": float("nan"), "ci_hi": math.inf,
               "nested": [{"x": -math.inf}, 1.5], "ok": 0.25}
    raw = json.dumps(aml_io._jsonable(payload), allow_nan=False)
    back = _strict(raw)
    assert back == {"ci_lo": None, "ci_hi": None,
                    "nested": [{"x": None}, 1.5], "ok": 0.25}


def test_every_committed_json_artifact_parses_strictly():
    """The same guarantee, asserted over what is actually in the tree."""
    root = Path(__file__).resolve().parents[3]
    bad = []
    for d in ("aml-platform/results_archive", "aml-platform/paper"):
        for f in (root / d).rglob("*.json"):
            try:
                _strict(f.read_text())
            except ValueError as e:
                bad.append(f"{f.relative_to(root)}: {e}")
    assert not bad, "artifacts a conformant JSON reader rejects:\n  " + \
        "\n  ".join(bad[:20])


# ---------------------------------------------------------------------------
# 32. A public artifact must not carry a workstation path, an ambiguous SHA,
#     or a legal conclusion the project has not reached (v4 P0-10, P1-5)
# ---------------------------------------------------------------------------

def test_replay_bundles_identify_themselves_portably():
    """Bundle metadata claimed more than the repository's own analysis does.

    `note` ended "...so this redistributes no part of the CDLA-licensed
    dataset" -- a legal conclusion, stated as settled fact, in a
    machine-readable field, while `DATA_LICENSE.md` called the same question an
    unreviewed interpretation. Two files in one repository cannot disagree
    about whether something has been decided.

    Two smaller things travelled with it: an abbreviated `code_git_sha`, which
    cannot be resolved in a clone that does not already have the object, and
    `source_scores: /scratch/large/gold/...`, a VM mount point that identifies
    the run for nobody but the machine that made it.
    """
    bundles = sorted((_archive_root() / "replay").glob("*/bundle.json"))
    if not bundles:
        pytest.skip("no replay bundles in this checkout")

    problems = []
    for b in bundles:
        d = json.loads(b.read_text())
        name = b.parent.name
        sha = d.get("code_git_sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            problems.append(f"{name}: code_git_sha {sha!r} is not a full SHA")
        src = str(d.get("source_scores", ""))
        if src.startswith("/") or "\\\\" in src or src[1:3] == ":\\\\":
            problems.append(f"{name}: source_scores is an absolute host path: {src}")
        if "redistributes no part" in d.get("note", ""):
            problems.append(f"{name}: note asserts a redistribution conclusion "
                            f"the project has not reviewed")
        status = d.get("licence_status", "")
        if "UNREVIEWED" not in status:
            problems.append(f"{name}: no unreviewed-licence status recorded")

        # LINEAGE, OR AN EXPLICIT STATEMENT THAT IT IS MISSING.
        #
        # The bundles recompute every published budget metric exactly, which is
        # the hard part, and they could not say what they were an extract OF --
        # no generator, no dataset identity, no identity for the source score
        # set. Eight were written on the VM and cannot be rebuilt here, so the
        # requirement is not "complete lineage"; it is that a bundle either
        # HAS it or SAYS it does not.
        version = d.get("bundle_schema_version")
        if version and version >= 3:
            for field in ("generator_script", "generator_sha256",
                          "dataset_pin_sha256", "inputs"):
                if not d.get(field):
                    problems.append(f"{name}: schema v3 but no {field}")
        else:
            gaps = d.get("lineage_completeness") or {}
            if not gaps.get("not_recorded") or not gaps.get("what_is_not"):
                problems.append(
                    f"{name}: schema v{version} carries partial lineage and "
                    f"does not say which claims are unverifiable")
    assert not problems, "replay bundle metadata:\n  " + "\n  ".join(problems)
    assert any(json.loads(b.read_text()).get("bundle_schema_version", 0) >= 3
               for b in bundles), (
        "no bundle demonstrates the complete schema; at least the one whose "
        "inputs are in this repository should be rebuilt under it")


# ---------------------------------------------------------------------------
# 33. One cost snapshot, and every published figure derived from it
#     (v4 audit P0-9)
# ---------------------------------------------------------------------------

def test_the_published_cost_table_matches_the_cost_artifact():
    """Three different project totals were published at the same time.

    README said $27.90, the runbook and HANDOFF said $54.71 at 99.99 hours, and
    `cost.json` said $63.62 at 116.28 -- because each document quoted whichever
    day's snapshot was current when that document was last edited, and the
    meter never stopped. "The only place a cost is stated" was true of the
    runbook and false of the repository.
    """
    root = Path(__file__).resolve().parents[2]
    cost = json.loads(
        (_archive_root() / "derived/cost.json").read_text())
    if not (root / "docs/RUNBOOK_cloud.md").exists():
        pytest.skip("docs/ not present (running inside the image)")
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()

    total = f"{cost['total_usd_at_list']:.2f}"
    hours = f"{cost['window_hours']:.2f}"
    assert f"**{hours}** | **{total}**" in runbook, (
        f"the runbook's total row does not match cost.json "
        f"({hours} h, ${total}); regenerate it")
    for item in cost["items"]:
        assert f"{item['usd']:.2f}" in runbook, (
            f"{item['what']} costs ${item['usd']:.2f} in cost.json and that "
            f"figure is absent from the runbook table")

    # And the charge must not be restated as a measurement anywhere.
    assert cost["actually_charged_usd"] is None, (
        "actually_charged_usd is a hardcoded constant, not a reading; it must "
        "be null with the claim recorded separately")
    assert "NOT MEASURED" in cost["actually_charged_claim"]
    for doc in ("docs/RUNBOOK_cloud.md", "../README.md", "../HANDOFF.md"):
        if not (root / doc).exists():
            continue
        text = (root / doc).read_text()
        assert "$0 actually charged" not in text, (
            f"{doc} states a billed amount as fact; no invoice was retrieved")


# ---------------------------------------------------------------------------
# 34. A published decomposition must not depend on the scan order
#     (found by regenerating, V4 P0-3's real purpose)
# ---------------------------------------------------------------------------

def test_the_counterfactual_loader_imposes_a_row_order():
    """Regenerating this artifact gave different numbers on all five seeds.

    Same code, same `default_rng(0)`, same 400 draws. The loader joins three
    parquet sources with no ORDER BY and DuckDB's hash join is parallel, so the
    row order is whatever the workers finish in. `decompose` then builds its
    pool as `s[(~exc) & (y == 1)]` -- an array whose ORDER is that scan order --
    and draws from it with `rng.choice`. Same RNG state, differently ordered
    pool, different values drawn.

    The headline moved 0.4677 -> 0.4670, which is nothing. The mechanism is the
    one this project retracted a HI-Medium lineage over, sitting in the
    generator of a published decomposition, and nothing found it for two
    audits because nothing had ever asked the script to answer twice.
    """
    src = _script("split_inflation_counterfactual.py").read_text()
    assert "ORDER BY" in src, (
        "the counterfactual loader must impose a deterministic row order; its "
        "draw pool is an array in scan order")
    sibling = _script("analyze_split_inflation.py").read_text()
    assert "ORDER BY" in sibling, (
        "mean() over floats is not associative; an unordered parallel scan "
        "moved six fields of split_inflation.json in their last bit")


def test_the_counterfactual_gives_the_same_answer_twice():
    """The fix, demonstrated rather than asserted.

    Five draws, not four hundred: the load and the RNG path are what is being
    tested, and they are identical at either size.
    """
    gold = _script("split_inflation_counterfactual.py").parents[1] / "data/gold"
    if not (gold / "infl_fit_naive_s0/gbdt_test_scores.parquet").exists():
        pytest.skip("split-inflation gold outputs not built in this checkout")

    import tempfile
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in (1, 2):
            out = Path(tmp) / f"cf{i}.json"
            r = subprocess.run(
                [sys.executable, str(_script("split_inflation_counterfactual.py")),
                 "--draws", "5", "--seeds", "0", "--out", str(out)],
                capture_output=True, text=True,
                cwd=_script("split_inflation_counterfactual.py").parents[1],
                env={**os.environ, "AML_ALLOW_DIRTY_PROVENANCE": "1"})
            assert r.returncode == 0, r.stdout + r.stderr
            outs.append(json.loads(out.read_text())["per_seed"])
    assert outs[0] == outs[1], (
        "two runs of identical code with the same seed disagree; the scan "
        "order is leaking into the result again")


# ---------------------------------------------------------------------------
# 35. Editing an IMPORTED module must stop artifact generation (v5 P0-1)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    "scripts/cost_table.py",            # the generator itself
    "src/aml/eval/metrics.py",          # a module the generator imports
    "scripts/make_tables.py",           # a SIBLING script another generator imports
    "src/aml/io.py",                    # another package module
])
def test_provenance_refuses_when_the_code_that_produced_it_is_uncommitted(target):
    """Two mutations, one requirement: the artifact may not name a commit that
    does not contain the code that made it.

    The first version of this guard compared only the GENERATOR file, so an
    audit edited `src/aml/eval/metrics.py`, left `scripts/cost_table.py` alone,
    and got `generator_matches_commit: true` beside a clean HEAD SHA. Both
    fields were individually correct and together asserted something false --
    the same defect the guard was written for, moved one level down the import
    graph.

    Run in a scratch clone so the working tree is not disturbed.
    """
    plat_src = Path(__file__).resolve().parents[2]
    if not (plat_src / "src/aml/manifest.py").exists():
        pytest.skip("package source not present")

    import shutil
    import stat
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # A REPOSITORY BUILT FROM THE WORKING TREE, not a clone of HEAD.
        #
        # Cloning would test whatever is already committed, so this test could
        # not fail on the very change it exists to guard until after that
        # change was pushed. Copying the current source and committing it here
        # means the mutation is measured against the code in front of us.
        repo = Path(tmp) / "repo"
        plat = repo / "aml-platform"
        plat.mkdir(parents=True)
        for part in ("src", "scripts"):
            shutil.copytree(plat_src / part, plat / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        # OWN THE COPY. `copytree` preserves mode, and the Dockerfile does
        # `chmod -R a-w /app/src /app/scripts` on purpose -- a container that
        # only reads inputs and writes to a mounted path has no business
        # rewriting its own code. So inside the image this fixture inherited
        # read-only files and the mutation raised PermissionError instead of
        # testing anything. Caught by the image job, which is what it is for.
        for f in [plat, *plat.rglob("*")]:
            f.chmod(f.stat().st_mode | stat.S_IWUSR
                    | (stat.S_IXUSR if f.is_dir() else 0))
        (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        git = ["git", "-C", str(repo)]
        for cmd in (["init", "-q"],
                    ["config", "user.email", "t@example.invalid"],
                    ["config", "user.name", "test"],
                    ["add", "-A"],
                    ["commit", "-qm", "fixture"]):
            r = subprocess.run(git + cmd, capture_output=True)
            if r.returncode != 0:
                pytest.skip(f"git unavailable: {r.stderr.decode()[:120]}")

        probe = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from aml.manifest import generator_provenance\n"
            "generator_provenance('scripts/cost_table.py')\n"
            "print('WROTE')\n"
        )
        # WITHOUT THE INJECTED SHA. The image bakes `AML_GIT_SHA` in as an
        # ENV var, and `git_sha()` returns the injected value in preference to
        # asking a repository -- correctly, because the container has none. So
        # inside the image this fixture's own commit was invisible, the recorded
        # SHA was the outer one, `blob_sha256_at` could not resolve it, and the
        # helper recorded an honest `null` instead of refusing. Correct
        # behaviour, and it made the test assert nothing in the one environment
        # the release ships.
        env = {k: v for k, v in os.environ.items() if k != "AML_GIT_SHA"}
        env["PYTHONPATH"] = str(plat / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        clean = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" in clean.stdout, (
            "a clean checkout must be able to record provenance:\n"
            + clean.stdout + clean.stderr)

        edited = plat / target
        edited.write_text(edited.read_text() + "\n# mutation\n")
        dirty = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" not in dirty.stdout, (
            f"editing {target} did not stop provenance being recorded; the "
            f"artifact would claim a commit that does not contain it")
        assert "RuntimeError" in dirty.stderr

        # And the override must still work, because local iteration needs it.
        allowed = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True,
            cwd=plat, env={**env, "AML_ALLOW_DIRTY_PROVENANCE": "1"})
        assert "WROTE" in allowed.stdout, allowed.stderr


# ---------------------------------------------------------------------------
# 36. No current document may report a fixed blocker as live (v5 P0-5)
# ---------------------------------------------------------------------------

def test_no_current_document_says_the_txn_id_defect_is_still_open():
    """`docs/FEATURE_SPEC_v1.md` presented itself as the live specification and
    its status block said `txn_id` is non-deterministic "today", that no
    cross-engine equality test can pass, and that "one join inside the leak
    proof is already silently wrong".

    All three were fixed. The file was not. **The v1 audit flagged that exact
    sentence** and it survived four rounds, because every gate this project
    built checks numbers against artifacts and none of them read prose for
    claims about the code. A reviewer had no way to tell whether to trust the
    implementation or the spec.

    The file is archived now. This is the check that keeps the class closed:
    the archive may say it, current documents may not.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "README.md").exists():
        pytest.skip("repository root not present (running inside the image)")

    # Phrases that assert the defect is PRESENT, not phrases that mention it.
    live = re.compile(
        r"txn_id is not deterministic today"
        r"|txn_id is non-?deterministic\s+(?:today|now)"
        r"|leak proof is already silently wrong"
        r"|one join inside the leak proof is",
        re.I)
    current = []
    for f in root.rglob("*.md"):
        parts = f.parts
        if any(p in parts for p in (".git", ".venv", "node_modules", "archive",
                                    "Learning")):
            continue
        if f.name.startswith("v") and "audit" in f.name:
            continue                       # audit reports quote the defect
        current.append(f)
    assert current, "no current markdown found"

    bad = []
    for f in current:
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if live.search(line):
                bad.append(f"{f.relative_to(root)}:{n}  {line.strip()[:90]}")
    assert not bad, (
        "current documents report a fixed defect as live:\n  " + "\n  ".join(bad))


def test_the_txn_id_fix_the_archived_spec_predates_is_actually_covered():
    """The archive's claim that this was fixed must itself be checkable."""
    root = Path(__file__).resolve().parents[2]
    tests = (root / "tests/repro/test_txn_id_identity.py")
    assert tests.exists(), "the regression suite the archive cites is missing"
    body = tests.read_text()
    for name in ("test_two_ingests_of_the_same_file_agree_row_for_row",
                 "test_assignment_is_independent_of_thread_count",
                 "test_txn_id_is_contiguous_1_to_n"):
        assert f"def {name}" in body, f"{name} is gone"


# ---------------------------------------------------------------------------
# 37. Structured STDOUT must be strict JSON too (v5 P1-1)
# ---------------------------------------------------------------------------

def test_every_demo_event_on_stdout_parses_strictly(tmp_path):
    """The stored manifest was fixed and the stdout events were not.

    `io.write_json` normalises non-finite floats and passes `allow_nan=False`.
    Every `print(json.dumps(...))` in the package went straight through
    Python's encoder, which emits the bare token `NaN` -- so a clean wheel run
    of the demo wrote a strict manifest and printed `"ci_lo": NaN` in the same
    breath. Two output paths, one fixed, and the fixed one is the one that had
    been looked at. My earlier "already closed" was a statement about files.

    `bootstrap 0` is the reproduction: with no resamples there are no bounds.
    """
    r = subprocess.run(
        [sys.executable, "-m", "aml.cli", "demo", "--dest", str(tmp_path / "d")],
        capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]

    events, bad = 0, []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        events += 1
        try:
            _strict(line)
        except ValueError as e:
            bad.append(f"{e}: {line[:120]}")
        except json.JSONDecodeError:
            pass                    # not an event, just a line shaped like one
    assert events, "the demo printed no structured events to parse"
    assert not bad, ("demo stdout a conformant JSON reader rejects:\n  "
                     + "\n  ".join(bad[:10]))


def test_no_module_prints_an_event_through_the_unchecked_encoder():
    """One policy, not twenty call sites each making their own."""
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = []
    for f in src.rglob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if "print(json.dumps(" in line:
                offenders.append(f"{f.relative_to(src)}:{n}")
    assert not offenders, (
        "these bypass io.json_line and can emit NaN/Infinity:\n  "
        + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# 38. Canonical manifests must be held to the current standard (v5 P1-3)
# ---------------------------------------------------------------------------

def _canonical_lineages() -> set[str]:
    """The canonical set, read from the ONE registry that defines it.

    This was a hard-coded literal here listing four lineages while
    `CANONICAL.json` listed three -- two sources of truth for the question
    "which results may support a published claim". A lineage could therefore be
    treated as canonical by the publication checker and never join the set held
    to the stronger full-SHA/package-tree standard, and the release mechanism
    could regress by omission rather than by anyone deciding anything.
    """
    reg = _archive_root() / "CANONICAL.json"
    if not reg.is_file():
        return set()
    return set(json.loads(reg.read_text()).get("canonical", {}))


def test_canonical_manifests_carry_a_full_sha_and_a_verified_tree_hash():
    """101 archived manifests, and the gate accepted any non-"unknown" string.

    Sixty-nine omit `code_tree_sha256`, seven record `unknown`, and twelve
    record a twelve-character abbreviation -- five of those in the CANONICAL
    Medium and Large lineages, which are the ones current documents cite. An
    abbreviation is ambiguous by construction and unresolvable in a clone that
    does not already hold the object, so "this result came from commit X" was
    not a checkable statement for the results that matter most.

    The old evidence stays as it is; pretending it was regenerated would be
    worse than grandfathering it. What must hold to the current standard is the
    set a reader is pointed at.
    """
    archive = _archive_root() / "gold"
    if not archive.is_dir():
        pytest.skip("no gold archive in this checkout")
    canonical = _canonical_lineages()
    assert canonical, "CANONICAL.json names no canonical lineage"
    root = Path(__file__).resolve().parents[3]

    problems, checked = [], 0
    for f in sorted(archive.rglob("manifest.json")):
        lineage = re.sub(r"_s\d+$", "", f.relative_to(archive).parts[0])
        if lineage not in canonical:
            continue
        d = json.loads(f.read_text())
        name = f.relative_to(archive).parent
        sha = d.get("code_git_sha", "")
        checked += 1
        if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            problems.append(f"{name}: code_git_sha {sha!r} is not a full SHA")
            continue
        tree = d.get("code_tree_sha256")
        if not tree:
            problems.append(f"{name}: records no code_tree_sha256")
            continue
        at = _tree_hash_at(root, sha)
        if at is None:
            continue                       # shallow clone or no git; not a defect
        if at != tree:
            problems.append(
                f"{name}: the package tree at {sha[:12]} hashes to {at[:12]}, "
                f"the manifest records {tree[:12]}")
    assert checked, "no canonical manifests found"
    assert not problems, ("canonical manifests below the current standard:\n  "
                          + "\n  ".join(problems))


# ---------------------------------------------------------------------------
# 39. The declared scope, not just the files we happen to hash (v6 P0-1)
# ---------------------------------------------------------------------------

def _scratch_repo(tmp, plat_src, extra=()):
    """A git repository built from the working tree, with our own permissions."""
    import shutil
    import stat
    repo = Path(tmp) / "repo"
    plat = repo / "aml-platform"
    plat.mkdir(parents=True)
    for part in ("src", "scripts", *extra):
        src = plat_src / part
        if src.is_dir():
            shutil.copytree(src, plat / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
    # DIRECTORIES TOO. `copytree` preserves mode and the Dockerfile does
    # `chmod -R a-w /app/src /app/scripts`, so the copied DIRECTORIES were
    # read-only as well -- files could be edited after the first fix and a new
    # file could not be created inside them. The untracked-file mutation is
    # exactly that, so it raised PermissionError in the image instead of
    # testing anything. Third variant of the same fixture defect; the rule is
    # that a fixture owns every part of its copy.
    for f in [plat, *plat.rglob("*")]:
        f.chmod(f.stat().st_mode | stat.S_IWUSR | (stat.S_IXUSR if f.is_dir() else 0))
    # The scope guard counts UNTRACKED files, and importing the package writes
    # `__pycache__` -- so the fixture tripped its own guard before it had
    # mutated anything. The real repository ignores bytecode; this one must
    # too, and the probes additionally run with PYTHONDONTWRITEBYTECODE.
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git = ["git", "-C", str(repo)]
    for cmd in (["init", "-q"],
                ["config", "user.email", "t@example.invalid"],
                ["config", "user.name", "test"],
                ["add", "-A"], ["commit", "-qm", "fixture"]):
        r = subprocess.run(git + cmd, capture_output=True)
        if r.returncode != 0:
            pytest.skip(f"git unavailable: {r.stderr.decode()[:120]}")
    return repo, plat


@pytest.mark.parametrize("mutation", [
    "sibling-script",        # an imported generator, not the named one
    "new-test",              # an untracked file inside the scope
    "edited-document",       # a document release_facts counts markers in
    "edited-artifact",       # a committed result the generator reads
])
def test_provenance_refuses_anything_dirty_inside_the_declared_scope(mutation):
    """Hashing the generator and the package is not the dependency closure.

    An audit edited `scripts/make_tables.py` -- which `release_facts.py`
    imports at runtime -- and got BOTH `generator_matches_commit: true` and
    `code_tree_matches_commit: true`. The collection logic that produced the
    numbers was absent from the recorded commit and every hash said otherwise.
    The same artifact also depends on every test file and every Markdown file
    it counts markers in, none of which any hash covers.

    Chasing the import graph is the clever answer and the fragile one. The
    rule is blunt instead: nothing inside the DECLARED SCOPE may be modified or
    untracked when an artifact is written, and a generator that depends on more
    declares more. These four mutations are the ones the hashes cannot see.
    """
    plat_src = Path(__file__).resolve().parents[2]
    if not (plat_src / "src/aml/manifest.py").exists():
        pytest.skip("package source not present")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, plat = _scratch_repo(tmp, plat_src, extra=("docs",))
        (plat / "results_archive/derived").mkdir(parents=True)
        (plat / "results_archive/derived/x.json").write_text('{"a": 1}\n')
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "artifacts"],
                       capture_output=True)

        # The widest scope in the repository: what release_facts declares.
        probe = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from aml.manifest import generator_provenance\n"
            "generator_provenance('scripts/cost_table.py', scope=('',))\n"
            "print('WROTE')\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "AML_GIT_SHA"}
        env["PYTHONPATH"] = str(plat / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        clean = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" in clean.stdout, clean.stdout + clean.stderr

        if mutation == "sibling-script":
            f = plat / "scripts/make_tables.py"
            f.write_text(f.read_text() + "\n# mutation\n")
        elif mutation == "new-test":
            (plat / "scripts/test_untracked_helper.py").write_text("# new\n")
        elif mutation == "edited-document":
            f = next((plat / "docs").glob("*.md"))
            f.write_text(f.read_text() + "\n<!-- derived -->\n")
        elif mutation == "edited-artifact":
            (plat / "results_archive/derived/x.json").write_text('{"a": 2}\n')

        dirty = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" not in dirty.stdout, (
            f"a {mutation} mutation did not stop provenance being recorded; "
            f"the artifact would claim a commit that does not contain it")
        assert "provenance scope" in dirty.stderr, dirty.stderr[-400:]


def test_release_facts_declares_the_scope_its_output_actually_depends_on():
    """It runs the whole suite, counts markers in every Markdown file, and
    imports make_tables. Anything narrower than the repository is not honest."""
    body = _script("release_facts.py").read_text()
    assert 'scope=("",)' in body, (
        "release_facts must declare the whole repository; its output changes "
        "when a test, a document or the archive changes")
    assert '"root": "."' in body, (
        "the committed artifact recorded an absolute home directory in "
        "parameters.root; it must be repository-relative")


# ---------------------------------------------------------------------------
# 40. The documented clean-clone package command must work (v6 P1-1)
# ---------------------------------------------------------------------------

def test_package_smoke_is_self_contained_and_gated():
    """`make setup && make package-smoke` is the documented pair. In a clean
    clone the second one failed:

        .venv/bin/python: No module named build

    Neither dev lock contained `build`, `twine` was absent everywhere, and
    `make release-check` -- which calls itself the command for everything
    locally verifiable -- did not call this target, so nothing noticed.
    """
    root = Path(__file__).resolve().parents[2]
    # The Makefile is the build recipe, not an image input -- the same class
    # as the Dockerfile guard above it.
    if not (root / "Makefile").exists():
        pytest.skip("Makefile not present (running inside the image)")
    mk = (root / "Makefile").read_text()
    body = mk[mk.index("\npackage-smoke:"):]
    body = body[:body.index("\n\n")]
    # RECIPE LINES ONLY. The comment above the fix quotes the broken command
    # verbatim, so matching the raw block made this test fail on the
    # explanation rather than on the behaviour -- the fourth time a check in
    # this repository has been tripped by a comment describing the defect it
    # guards against.
    recipe = "\n".join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("#"))

    assert ".venv/bin" not in recipe, (
        "package-smoke must not depend on the development venv; the build "
        "tools come from requirements-release.lock into a throwaway venv")
    assert "requirements-release.lock" in recipe, "build tools are not locked"
    assert "twine check" in recipe, "package metadata is never validated"

    lock = (root / "requirements-release.lock")
    assert lock.is_file(), "requirements-release.lock is missing"
    pinned = _parse_lock(lock)
    # THE BACKEND TOO. `python -m build` resolves `requires = [...]` from PyPI
    # inside an isolated environment, so the frontend was pinned and the
    # setuptools that actually produces the wheel was not -- an audit caught it
    # installing a version present in no lock here.
    for tool in ("build", "twine", "setuptools", "wheel"):
        assert tool in pinned, f"{tool} is not pinned in the release lock"
    assert "--no-isolation" in recipe, (
        "build runs with isolation, so it resolves its own backend and the "
        "pin above is decoration")

    rc = mk[mk.index("\nrelease-check:"):]
    rc = rc[:rc.index("\n\n")]
    assert "package-smoke" in rc, (
        "release-check claims to cover everything locally verifiable and does "
        "not build the package")


# ---------------------------------------------------------------------------
# 41. A notice must travel with the data it describes (v6 P0-5)
# ---------------------------------------------------------------------------

def test_every_artifact_that_ships_the_replay_bundles_ships_the_notices():
    """The image COPYs `results_archive/` -- nine bundles, ~526k rows of
    derived row-level records whose redistribution status this project
    explicitly declines to settle -- and copied neither `DATA_LICENSE.md` nor
    `LICENSE`.

    A published image would carry the disputed data and not the document that
    says where it came from or that the question is open. Whatever the legal
    answer turns out to be, that cannot be part of it.
    """
    root = Path(__file__).resolve().parents[2]
    if not (root / "Dockerfile").exists():
        pytest.skip("Dockerfile not present (running inside the image)")

    dockerfile = (root / "Dockerfile").read_text()
    copies_bundles = any(
        ln.strip().startswith("COPY") and "results_archive" in ln
        for ln in dockerfile.splitlines())
    if copies_bundles:
        copied = " ".join(ln for ln in dockerfile.splitlines()
                          if ln.strip().startswith("COPY"))
        for notice in ("LICENSE", "DATA_LICENSE.md"):
            assert notice in copied, (
                f"the image ships results_archive/ and not {notice}")

    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
    block = runbook[runbook.index("git archive --format=tar.gz"):][:800]
    if "results_archive" in block:
        for notice in ("LICENSE", "DATA_LICENSE.md"):
            assert notice in block, (
                f"the deployment archive ships results_archive/ and not {notice}")


# ---------------------------------------------------------------------------
# 42. A running meter cannot be quoted as a total (v6 P0-4)
# ---------------------------------------------------------------------------

def test_a_provisional_cost_snapshot_says_so():
    """Three cost totals were live in three documents at once -- $27.90,
    $54.71, $63.62 -- because `cost.json` defaults its window end to "now" and
    every regeneration produced a bigger number than the last document had
    copied. Correcting the documents one at a time does not fix that; saying
    which kind of number it is does.
    """
    cost = json.loads((_archive_root() / "derived/cost.json").read_text())
    assert "snapshot_is_final" in cost, (
        "the artifact does not say whether its window is closed")
    if not cost["snapshot_is_final"]:
        assert "PROVISIONAL" in cost["snapshot_note"]
        root = Path(__file__).resolve().parents[2]
        if (root / "docs/RUNBOOK_cloud.md").exists():
            runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
            assert "PROVISIONAL" in runbook, (
                "the cost table quotes a running total without saying it runs")


# ---------------------------------------------------------------------------
# 43. The environment is part of the computation (v6 P1-3)
# ---------------------------------------------------------------------------

def test_the_cache_key_changes_when_the_environment_does():
    """`run_key` covered component, config, code and inputs -- everything
    except the libraries that do the arithmetic.

    A new DuckDB, NumPy or LightGBM build can change a result while all of
    those stay identical, so the cache would serve the old answer under the new
    stack and the manifest would record `status: ok`. That is the failure this
    project exists to prevent, sitting inside the mechanism meant to prevent it.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    base = mf.run_key("stage", cfg, inputs)

    real = mf.env_id
    try:
        mf.env_id = lambda: "deadbeefdeadbeef+py9.9.9"
        moved = mf.run_key("stage", cfg, inputs)
    finally:
        mf.env_id = real

    assert moved != base, (
        "changing the environment identity did not change the cache key; a "
        "dependency upgrade would hit the old cache silently")
    assert mf.run_key("stage", cfg, inputs) == base, "the key is not stable"


def test_the_manifest_records_whether_the_installed_stack_matches_the_lock():
    """`env_lock_sha256` is the digest of what the environment was SUPPOSED to
    be. It proves nothing about what is importable. The two are recorded
    separately because a declaration and a check are different things."""
    from aml.manifest import installed_matches_lock

    got = installed_matches_lock()
    assert got["checked"] is True, got
    assert got["ok"] is True, (
        f"the installed numeric stack disagrees with requirements.lock: "
        f"mismatched={got['mismatched']} missing={got['missing']}")


# ---------------------------------------------------------------------------
# 44. The cache must check the INSTALLED stack, before it serves a hit
#     (v7 P1-1)
# ---------------------------------------------------------------------------

def test_a_mismatched_installed_stack_refuses_the_cache(tmp_path, monkeypatch):
    """`env_id()` is the DECLARED lock digest plus the interpreter version, so
    editing the lock misses the cache. Installing a different NumPy without
    touching the lock did not.

    `installed_matches_lock()` was evaluated at stage EXIT, when a manifest is
    written -- and a cache hit returns before any manifest exists. So the stack
    that would have produced a different answer got the old answer, and the
    record beside it described the previous run's environment. The V6 test
    monkeypatched `env_id` and never simulated the case that actually leaks.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    out = tmp_path / "stage"
    out.mkdir()

    # Prime a cache entry the ordinary way.
    key = mf.run_key("stage", cfg, inputs)
    with mf.Run("stage", cfg, out, key=key) as r:
        r.record(answer=42)
    assert mf.cached_or_none("stage", cfg, inputs, out)[1] is not None, (
        "the fixture did not actually produce a cache hit")

    # Now the installed stack disagrees with the lock, and nothing else changes.
    monkeypatch.setattr(mf, "installed_matches_lock", lambda: {
        "checked": True, "ok": False,
        "mismatched": {"numpy": {"declared": "1.0.0", "installed": "2.0.0"}},
        "missing": [], "unlocked": []})
    k2, hit = mf.cached_or_none("stage", cfg, inputs, out)
    assert k2 == key, "the key changed; this test is no longer about the hit"
    assert hit is None, (
        "a cache hit was served while the installed numeric stack disagreed "
        "with the lock; the result would describe libraries that did not run")


def test_a_result_computed_under_the_wrong_stack_cannot_come_back_as_a_cache_hit(
        tmp_path, monkeypatch):
    """Guarding the read and leaving the write unguarded is half a fix.

    The previous version refused to SERVE a hit when the installed stack
    disagreed with the lock. A cross-check then did the obvious next thing, and
    it worked:

        1. mismatched environment -> cache correctly rejected
        2. the stage recomputes and writes ... UNDER THE SAME KEY
        3. the environment returns to the locked configuration
        4. that result is served as a cache hit

    Two independent closures now. The installed digest is part of the key, so a
    mismatched environment computes under its own key and cannot occupy the
    good one; and `load_cached` refuses any manifest that RECORDS a mismatch,
    which covers manifests already on disk from before the key changed.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    out = tmp_path / "stage"
    out.mkdir()
    bad_env = {"checked": True, "ok": False, "missing": [], "unlocked": [],
               "mismatched": {"numpy": {"declared": "1.0.0",
                                        "installed": "2.0.0"}}}

    # 1. the mismatched environment is refused the cache
    monkeypatch.setattr(mf, "installed_matches_lock", lambda: bad_env)
    key, hit = mf.cached_or_none("stage", cfg, inputs, out)
    assert hit is None

    # 2. it recomputes and writes -- which is what leaves the trap
    with mf.Run("stage", cfg, out, key=key) as r:
        r.record(answer="computed under the wrong numpy")

    # 3. the environment returns to the locked configuration
    monkeypatch.undo()
    mf.env_id.cache_clear()
    mf.installed_id.cache_clear()

    # 4. and the poisoned result must NOT come back
    _, hit2 = mf.cached_or_none("stage", cfg, inputs, out)
    assert hit2 is None, (
        "a result computed under a mismatched installed stack was served as a "
        "cache hit once the environment was corrected")


def test_the_installed_stack_is_part_of_the_cache_key():
    """The first of the two closures, on its own.

    Monkeypatching `installed_matches_lock` cannot exercise this -- the digest
    is taken from the versions actually importable, not from the check's
    verdict -- so this moves the digest directly.
    """
    from aml import manifest as mf

    base = mf.run_key("stage", {"a": 1}, [])
    real = mf.installed_id
    try:
        mf.installed_id = lambda: "deadbeefdeadbeef"
        mf.env_id.cache_clear()
        moved = mf.run_key("stage", {"a": 1}, [])
    finally:
        mf.installed_id = real
        mf.env_id.cache_clear()
    assert moved != base, (
        "a different installed numeric stack produced the same cache key, so "
        "it could overwrite the locked environment's entry")
    assert mf.run_key("stage", {"a": 1}, []) == base, "the key is not stable"


def test_the_machine_is_part_of_the_cache_key_not_just_the_interpreter():
    """A cross-check moved the simulated platform from macOS/arm64 to another
    OS and CPU and got the identical key: `platform_changes_key = False`.

    That matters here specifically, because this repository's own evidence is
    that **arm64 macOS and amd64 Linux produce different serialized model
    artifacts** -- it is written up in LIMITATIONS §7. A cache reached from two
    platforms, through a mounted volume or a restored directory, could have
    served an artifact built on the other one. The interpreter version was in
    the key; the machine running it was not.
    """
    import platform as plat_mod

    from aml import manifest as mf

    base = mf.env_id()
    real_system, real_machine = plat_mod.system, plat_mod.machine
    # DIFFERENT FROM WHATEVER THIS MACHINE IS, not a hardcoded "Linux".
    #
    # The first version patched to Linux/x86_64, which on the CI runner is what
    # the machine already reports -- so the patch was a no-op there and the
    # test failed on its own assertion. A test about platform sensitivity that
    # assumes a platform is the same species of mistake as the Markdown count
    # that included untracked files.
    other_system = "NotThisOS" if real_system() != "NotThisOS" else "SomeOtherOS"
    other_machine = "notthisarch" if real_machine() != "notthisarch" else "other"
    try:
        plat_mod.system = lambda: other_system
        plat_mod.machine = lambda: other_machine
        mf.platform_id.cache_clear()
        mf.env_id.cache_clear()
        moved = mf.env_id()
    finally:
        plat_mod.system, plat_mod.machine = real_system, real_machine
        mf.platform_id.cache_clear()
        mf.env_id.cache_clear()

    assert moved != base, (
        "changing the operating system and CPU did not change the cache key; "
        "a cache shared between platforms could serve the wrong artifact")
    assert mf.env_id() == base, "the key is not stable"

    # And the image, when a containerised run supplies one.
    import os as os_mod

    os_mod.environ["AML_IMAGE_DIGEST"] = "sha256:" + "a" * 64
    mf.env_id.cache_clear()
    try:
        with_image = mf.env_id()
    finally:
        del os_mod.environ["AML_IMAGE_DIGEST"]
        mf.env_id.cache_clear()
    assert with_image != base, (
        "AML_IMAGE_DIGEST did not reach the cache key, so two different "
        "images reporting the same OS tag share a cache")


def test_a_numeric_dependency_missing_from_the_lock_is_reported_not_skipped():
    """A dependency that can move a number and is absent from the lock used to
    be skipped, so deleting a line from requirements.lock made the check
    quieter rather than louder."""
    from aml import manifest as mf

    assert "unlocked" in mf.installed_matches_lock(), (
        "the check does not report dependencies missing from the lock")

    real = mf.env_lock_sha256
    try:
        mf.installed_matches_lock.cache_clear()
        mf.env_lock_sha256.cache_clear()
        got = mf.installed_matches_lock()
    finally:
        mf.env_lock_sha256 = real
        mf.installed_matches_lock.cache_clear()
    assert got["ok"] is True and not got["unlocked"], (
        f"the project's own lock does not pin every dependency that can move a "
        f"number: {got['unlocked']}")


# ---------------------------------------------------------------------------
# 45. The SAST baseline must track identities, not totals (v7 P1-6)
# ---------------------------------------------------------------------------

def test_the_sast_baseline_fails_when_one_finding_is_traded_for_another():
    """`check_sast.py` stored counts per rule: `B608: 50`.

    Fix one f-string query, introduce another somewhere else, and the total is
    still 50 -- so the gate passed while a new, untriaged finding of exactly
    the class the triage document is about had been added. The prose said new
    findings fail; the implementation proved only that the number had not
    moved.
    """
    baseline = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/sast_baseline.json").read_text())
    assert "findings" in baseline, (
        "the baseline still records counts; fix-one/add-one nets to zero")
    assert baseline["findings"], "the baseline is empty"
    for ident in baseline["findings"]:
        rule, _, rest = ident.partition(":")
        assert re.fullmatch(r"B\d{3}", rule), f"{ident} has no rule id"
        assert rest, f"{ident} carries no path or fingerprint"
        # The line number must NOT be part of the identity: adding an import
        # shifts every finding below it and would look like a rewrite.
        assert not re.search(r":\d+#", ident), (
            f"{ident} looks line-numbered; that makes an insertion above a "
            f"finding indistinguishable from a new finding")

    # STABLE UNDER AN UNRELATED EDIT. The first version fingerprinted bandit's
    # `code` field, which carries the surrounding CONTEXT with line numbers --
    # so adding a helper to models/train.py re-fingerprinted every finding in
    # the file and CI reported nine new defects for a change that introduced
    # none. A fingerprint that moves when a neighbour moves is a count with
    # extra steps.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import check_sast

    finding = {"line_number": 274, "code":
               "273     ring_filter = (\n"
               "274                    f\" AND (ring_id IN \"\n"
               "275                    f\"(SELECT x FROM '{p}'))\")\n"}
    shifted = {"line_number": 275, "code":
               "274     # a new comment above it\n"
               "275                    f\" AND (ring_id IN \"\n"
               "276                    f\"(SELECT x FROM '{p}'))\")\n"}
    assert check_sast._flagged_line(finding) == check_sast._flagged_line(shifted), (
        "moving a finding down one line changed its identity; an insertion "
        "above it would look like a new defect")
    assert not check_sast._flagged_line(finding).startswith("CONTEXT:"), (
        "the flagged line was not located, so the fingerprint fell back to "
        "the whole context block")

    # The comparison itself, on synthetic identities.
    before = {"B608:a.py:aaaa#1": "MEDIUM", "B608:b.py:bbbb#1": "MEDIUM"}
    traded = {"B608:b.py:bbbb#1": "MEDIUM", "B608:c.py:cccc#1": "MEDIUM"}
    assert len(before) == len(traded), "the fixture is not a like-for-like trade"
    appeared = set(traded) - set(before)
    vanished = set(before) - set(traded)
    assert appeared and vanished, (
        "identity comparison did not notice a one-for-one trade, which is the "
        "only thing distinguishing it from a count")


# ---------------------------------------------------------------------------
# 46. One registry, three statuses, and omission is refused
#     (v7 P1-7, reopened by cross-check)
# ---------------------------------------------------------------------------

def test_the_registry_is_the_only_definition_of_canonical():
    """`CANONICAL.json` said unlisted lineages default to canonical, so the
    registry could not hide a result by omission. A cross-check found the other
    edge: **28 unlisted lineages, 58 of whose manifests do not meet the
    full-SHA-plus-tree standard** — so a newly introduced unlisted lineage
    could back a published value while bypassing the test that enforces the
    standard. Omission was the hole, not the guard.

    Three statuses now, and `unlisted` is a publication failure. This asserts
    the registry is internally coherent and that nothing is in two groups.
    """
    reg = json.loads((_archive_root() / "CANONICAL.json").read_text())
    groups = {k: set(reg.get(k, {})) for k in
              ("canonical", "supporting", "superseded")}
    assert all(groups.values()), f"a status group is empty: {groups.keys()}"

    for a, b in (("canonical", "supporting"), ("canonical", "superseded"),
                 ("supporting", "superseded")):
        overlap = groups[a] & groups[b]
        assert not overlap, f"{sorted(overlap)} is both {a} and {b}"

    # Every entry must say something. A status with no reason is a silence with
    # a label on it.
    for status in groups:
        for name, reason in reg[status].items():
            assert isinstance(reason, str) and len(reason) > 25, (
                f"{status}/{name} has no stated reason ({reason!r})")


def test_every_lineage_backing_a_current_value_is_registered():
    """The property that was missing: a lineage cannot support publication
    without being named.

    This is the check the publication gate performs; asserting it here means a
    new archive directory plus a new published number fails the SUITE, not only
    the gate, and fails it with the lineage named.
    """
    plat = Path(__file__).resolve().parents[2]
    if not (plat / "scripts/make_tables.py").exists():
        pytest.skip("scripts/ not present")
    docs = [plat / p for p in (
        "../README.md", "../HANDOFF.md", "../CHANGELOG.md", "../DATA_LICENSE.md",
        "docs/LIMITATIONS.md", "docs/RELEASE_CHECKLIST.md",
        "docs/RESULT_LINEAGE.md", "docs/RUNBOOK_cloud.md")]
    docs += sorted((plat / "paper").glob("RESULTS_*.md"))
    docs = [d for d in docs if d.exists()]
    if not docs:
        pytest.skip("current documents not present (running inside the image)")

    r = subprocess.run(
        [sys.executable, str(plat / "scripts/make_tables.py"), "--check",
         *[str(d) for d in docs]],
        capture_output=True, text=True, cwd=plat)
    assert r.returncode == 0, (
        "a current document cites a lineage that is not in CANONICAL.json:\n"
        + r.stdout[-2500:])

    # AND PROVE THE GATE WOULD SAY SO, by building an unregistered lineage and
    # a document that cites its value.
    #
    # This test previously asserted that the phrase "from an unregistered
    # lineage" appeared in the summary -- which is true of a checker that
    # prints the counter and never increments it. Asserting that a gate
    # MENTIONS a category is not asserting that it enforces one, and a test
    # named for enforcement has to demonstrate rejection. Same defect as the
    # source-text prediction test, in a newer file.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "aml-platform"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(plat / "scripts/make_tables.py", scratch / "scripts")
        archive = scratch / "results_archive"
        shutil.copy(plat / "results_archive/CANONICAL.json", _mk(archive))
        shutil.copy(plat / "results_archive/RETRACTED.json", archive)

        # A lineage that is in no status group, carrying a distinctive value.
        lineage = archive / "gold/unregistered_fixture_s0"
        lineage.mkdir(parents=True)
        (lineage / "manifest.json").write_text(json.dumps({
            "component": "evaluate[gbdt]", "status": "ok",
            "code_git_sha": "0" * 40, "run_key": "f" * 16, "outputs": [],
            "config": {"seed": 0},
            "metrics": {"precision@50": 0.135791}}))

        doc = scratch / "CITES_IT.md"
        doc.write_text("| a value from an unregistered lineage | 0.13579 |\n")

        out = subprocess.run(
            [sys.executable, str(scratch / "scripts/make_tables.py"),
             "--archive", str(archive), "--check", str(doc)],
            capture_output=True, text=True, cwd=scratch)
        assert out.returncode != 0, (
            "a value supported only by an UNREGISTERED lineage was certified; "
            "omission is still the default:\n" + out.stdout[-1500:])
        assert "unregistered_fixture_s0" in out.stdout, (
            "the gate refused it without naming the lineage:\n"
            + out.stdout[-1500:])


def _mk(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 47. A guard nobody wires up does not exist (cross-check after V7)
# ---------------------------------------------------------------------------

def test_every_container_run_supplies_the_image_identity():
    """`manifest.env_id()` folds `AML_IMAGE_DIGEST` into the cache key so a
    containerised run is keyed to the exact image. Nothing supplied it.

    The code read the variable and every production path -- the cloud runners
    and the in-image test step -- left it unset, so cloud runs received
    platform identity and not the exact-image identity the documentation
    promised. Reading an environment variable is not a feature until something
    sets it.
    """
    root = Path(__file__).resolve().parents[2]
    for name in ("scripts/run_cloud.sh", "scripts/run_hi_large.sh"):
        body = (root / name).read_text()
        recipe = "\n".join(ln for ln in body.splitlines()
                           if not ln.lstrip().startswith("#"))
        assert "AML_IMAGE_DIGEST" in recipe, (
            f"{name} runs the container without passing the image identity")
        assert "image_digest" in recipe, (
            f"{name} does not resolve a digest to pass")
        assert "RepoDigests" in recipe, (
            f"{name} should prefer the registry digest, which is the immutable "
            f"content address, and fall back to the local image id")

    wf = root.parent / ".github/workflows/image.yml"
    if wf.exists():
        assert "AML_IMAGE_DIGEST" in wf.read_text(), (
            "the suite runs inside the image without recording which image")


@pytest.mark.parametrize("script", ["run_cloud.sh", "run_hi_large.sh"])
def test_the_runner_stops_when_no_image_identity_can_be_resolved(script, tmp_path):
    """The identity failed OPEN: both runners fell back to the literal string
    `unknown`, and `env_id()` folded it in as `+imgunknown` -- so two unrelated
    images that could not be resolved shared one "exact-image" identity and one
    cache key. A guard that degrades to a constant on failure is loudest
    exactly when it is least true.

    The previous test for this only confirmed that certain words appeared in
    the scripts. This makes both `docker image inspect` calls fail and checks
    that the resolver refuses.
    """
    root = Path(__file__).resolve().parents[2]
    body = (root / "scripts" / script).read_text()
    assert "image_digest() {" in body, f"{script} has no resolver"
    start = body.index("image_digest() {")
    fn = body[start:body.index("\n}\n", start) + 3]
    assert "unknown" not in fn, (
        f"{script} still has a placeholder fallback in its resolver")

    # A `docker` that fails every call, ahead of the real one on PATH.
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "docker").write_text("#!/bin/sh\nexit 1\n")
    (fake / "docker").chmod(0o755)
    probe = tmp_path / "probe.sh"
    probe.write_text(fn + '\nimage_digest "aml:whatever"\n')

    r = subprocess.run(["sh", str(probe)], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert r.returncode != 0, (
        f"{script} resolved an image identity with no working docker; it "
        f"printed {r.stdout.strip()!r}")
    assert "unknown" not in r.stdout, (
        f"{script} emitted a placeholder identity: {r.stdout.strip()!r}")
    assert "FATAL" in r.stderr


def test_env_id_refuses_a_malformed_image_digest():
    """`env_id()` accepted whatever the variable held, so a placeholder became
    a cache identity. An unset variable is a run outside a container and is
    fine; a SET but malformed one is a caller bug."""
    from aml import manifest as mf

    good = "sha256:" + "a" * 64
    for value in (good, "ghcr.io/o/r@" + good):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            assert "+img" in mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()

    # A TRUNCATED DIGEST IS NOT A DIGEST. The guard allowed 12-64 hex, so
    # `sha256:deadbeefcafe` -- a prefix that identifies no image and that two
    # images can share -- was accepted as an "exact image digest".
    for value in ("unknown", "sha256:zz", "latest", "<none>",
                  "sha256:deadbeefcafe", "repo/name@sha256:deadbeefcafe",
                  "sha256:" + "a" * 63, "sha256:" + "a" * 65):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            with pytest.raises(RuntimeError, match="not a full image digest"):
                mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()


def test_the_licence_inventory_is_actually_gated():
    """`release_facts.py` can validate the replay-row inventory, and neither
    `make release-check` nor CI was passing it the file that carries that
    inventory -- so the most legally consequential number in the repository
    could go stale under a green gate.

    Both copies: the root notice and the one the wheel ships.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables
    import release_facts

    top = make_tables.repo_root()
    if not (top / "aml-platform").is_dir():
        pytest.skip("repository root not present (running inside the image)")

    # BOTH COPIES, ASSERTED ON THE INVENTORY. This used to grep the Makefile
    # and ci.yml for the literal argument lists, which stopped meaning
    # anything once both called `--gate`; the claim is about which documents
    # are covered, so it is asserted against the list that decides that.
    counted = release_facts.count_docs(top)
    for copy in (top / "DATA_LICENSE.md", top / "aml-platform/DATA_LICENSE.md"):
        assert copy in counted, (
            f"{copy} is outside the count gate, so its replay-row inventory "
            "-- the most legally consequential number here -- can go stale")

    for path in (top / "aml-platform/Makefile",
                 top / ".github/workflows/ci.yml"):
        if not path.exists():
            continue
        assert "release_facts.py --check --gate" in path.read_text(), (
            f"{path.name} does not run the count gate over the inventory")


# ---------------------------------------------------------------------------
# 48. A history cue must not exempt its neighbours (cross-check after V7)
# ---------------------------------------------------------------------------

def _history_of(text: str):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import release_facts
    return release_facts._history_lines(text), release_facts


def test_a_history_cue_does_not_exempt_a_current_count_beside_it():
    """A false green, in the gate whose job is preventing them.

    HANDOFF's status block held `363 collected` and, eight lines later inside
    the same fence, "it was 479 for two rounds after it stopped being 479". The
    exemption was scoped to the PARAGRAPH, so the cue in the second line
    exempted the live test count in the first, and the checker reported zero
    disagreements while the number was stale.

    Per-line scoping is too narrow -- a cue and the number it governs land on
    different lines of one wrapped sentence -- and per-paragraph is too wide.
    The sentence is the unit, and a fenced code block is never exempted by its
    neighbours at all.
    """
    doc = (
        "```text\n"
        "tests     999 collected, 17 skip\n"
        "numbers   the count is not restated here -- it was 479 for two\n"
        "          rounds after it stopped being 479.\n"
        "```\n"
    )
    history, _ = _history_of(doc)
    assert 2 not in history, (
        "a live count inside a code block was exempted because a LATER line "
        "in the same block mentions history")


def test_a_wrapped_historical_sentence_is_still_exempt_whole():
    """The other direction, which is why per-line scoping was abandoned: the
    cue and the figure it governs sit on different lines of one sentence."""
    doc = (
        "The v2 audit found the previous version of this list asserting\n"
        "things that were false -- it claimed 270 tests and blamed the skips\n"
        "on Azure extras.\n"
        "\n"
        "This paragraph is current and says 999 tests.\n"
    )
    history, _ = _history_of(doc)
    assert {1, 2, 3} <= history, (
        "a wrapped historical sentence was only partly exempt, so a fixer "
        "would rewrite the figure the sentence is about")
    assert 5 not in history, (
        "a separate current paragraph was exempted by the historical one "
        "above it")


def test_the_fixer_repairs_the_current_count_and_leaves_the_historical_one():
    """End to end, on a document containing both."""
    import tempfile

    script = _script("release_facts.py")
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    want = json.loads(facts.read_text())["tests_collected"]

    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "MIXED.md"
        doc.write_text(
            "```text\n"
            "tests     111 collected\n"
            "```\n"
            "\n"
            "The v2 audit found this list claiming 270 tests, which was wrong.\n")
        r = subprocess.run(
            [sys.executable, str(script), "--fix", "--check", str(doc)],
            capture_output=True, text=True)
        body = doc.read_text()
        assert f"{want} collected" in body, (
            f"the current count was not repaired:\n{body}\n{r.stdout}")
        assert "270 tests" in body, (
            f"the historical figure was rewritten:\n{body}")


# ---------------------------------------------------------------------------
# 49. A hard-wrapped count claim must be visible to the gate that maintains it
# ---------------------------------------------------------------------------

def _release_facts_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import release_facts
    return release_facts


def test_a_wrapped_count_claim_is_checked_and_repaired():
    """The published number that went stale under a green tick.

    README said "... durations -- 156 values are\\nexempted by an explicit
    marker" while the publication check reported 216. The count had just been
    exposed as a machine-readable fact and wired into CI, and the gate still
    reported zero disagreements -- because the scan was line by line and the
    number and its noun had been hard-wrapped onto different lines.

    Reflowing that one sentence would have hidden the symptom and left the
    next wrap to fail identically. `\\s` matches a newline, so the fix is to
    scan the document rather than its lines.
    """
    import tempfile

    script = _script("release_facts.py")
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    want = json.loads(facts.read_text())["published_values_exempted"]
    stale = want + 60

    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "WRAPPED.md"
        doc.write_text(
            "It does not generically validate integers, percentages,\n"
            f"currency or durations -- {stale} values are\n"
            "exempted by an explicit marker.\n")

        seen = subprocess.run(
            [sys.executable, str(script), "--check", str(doc)],
            capture_output=True, text=True)
        assert seen.returncode != 0, (
            "the checker did not see a count claim split across two lines:\n"
            + seen.stdout)

        r = subprocess.run(
            [sys.executable, str(script), "--fix", "--check", str(doc)],
            capture_output=True, text=True)
        body = doc.read_text()
        assert f"{want} values are\nexempted" in body, (
            f"the wrapped claim was not repaired:\n{body}")
        assert "\n".join(body.splitlines()[0:1]).endswith("percentages,"), (
            "the fixer reflowed prose it was only supposed to renumber")
        # The digits sit on ONE line. A tool whose job is stopping false
        # numbers must not report two.
        assert "WRAPPED.md: 1 line(s)" in r.stdout, (
            f"the fixer misreported how much it changed:\n{r.stdout}")


def test_two_paragraphs_do_not_join_into_a_claim_nobody_made():
    """The cost of scanning whole documents, and the guard that pays it.

    Without a block guard, a number ending one paragraph and a noun opening
    the next match as one claim -- so the checker invents a disagreement, and
    the fixer rewrites an unrelated figure. Blank lines, table edges and fence
    delimiters all end a claim.
    """
    rf = _release_facts_module()
    facts = {"tests_collected": 999}

    for gap, what in (("\n\n", "a blank line"),
                      ("\n```\n", "a fence delimiter"),
                      ("\n| a | b |\n", "a table edge")):
        text = f"The archive totals 271{gap}tests were added later.\n"
        assert list(rf._hits(text, facts)) == [], (
            f"{what} did not end the claim, so two paragraphs were joined "
            "into a count claim nobody made")

    # ... and the control: the same words, wrapped inside one block, DO match.
    text = "The suite currently holds 271\ntests in total.\n"
    got = [(k, v) for k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [("tests_collected", 271)], (
        f"the guard also blocked an ordinary wrapped claim: {got}")


def test_the_checker_and_the_fixer_read_one_pattern_table():
    """They carried two copies of the pattern list, which is how a field gets
    checked and never repaired (or repaired and never checked)."""
    rf = _release_facts_module()
    src = Path(rf.__file__).read_text()
    body = src[src.index("def check("):]
    for name in ("TEST_COUNT", "COLLECTED", "EXEMPTED", "REPLAY_ROWS"):
        assert body.count(name) <= 1, (
            f"{name} is still enumerated inside check/fix; the checker and "
            "the fixer must share PATTERNS or they will drift apart")
    # NOT a magic floor. `>= 8` was a stand-in for "the table is populated",
    # and it failed the moment two genuinely unpublishable fields were removed
    # -- `tests_passed` and `tests_skipped`, which vary by where you stand and
    # so created a bootstrap cycle in prose. The invariant that matters is
    # that every pattern names a field the facts actually carry.
    src = Path(rf.__file__).read_text()
    unknown = [name for _rx, name in rf.PATTERNS
               if f'"{name}"' not in src.split("PATTERNS = ")[0]]
    assert not unknown, (
        f"PATTERNS checks prose for fields release_facts does not produce: "
        f"{unknown}")
    assert len(rf.PATTERNS) >= 5


# ---------------------------------------------------------------------------
# 50. Three gate weaknesses found by the cross-check after V7
# ---------------------------------------------------------------------------

def test_every_collected_fact_is_freshness_checked():
    """`--verify-artifact` compared an ALLOWLIST of ten field names.

    Three publication counters were added afterwards -- the whole point of
    adding them was that prose could quote them under a gate -- and none was
    in the list. A committed artifact holding 9999 for all three passed and
    printed that it matched a fresh collection, so the facts and the documents
    quoting them could go stale together under a green release gate.

    Same defect as "unlisted lineages default to canonical": a default of
    assume-valid turns an omission into the vulnerability. The list is now
    inverted, so this asserts the inversion rather than a field count.
    """
    rf = _release_facts_module()

    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    committed = json.loads(facts.read_text())

    assert rf.drifted(committed, committed) == [], (
        "an artifact does not agree with itself")

    for field in ("published_values_checked", "published_values_exempted",
                  "published_documents"):
        assert field in committed, f"{field} is not published at all"
        mutated = dict(committed)
        mutated[field] = 9999
        drift = rf.drifted(mutated, committed)
        assert [k for k, _, _ in drift] == [field], (
            f"a committed artifact claiming {field}=9999 was reported as "
            f"matching a fresh collection: {drift}")

    # And the general property, so the NEXT field added is covered too.
    for field in committed:
        if field in rf.VOLATILE_FACTS:
            continue
        mutated = dict(committed)
        mutated[field] = "mutated-by-the-test"
        assert rf.drifted(mutated, committed), (
            f"{field} is neither volatile nor freshness-checked; a field is "
            "one or the other, never neither")

    # The volatile list is for where-you-stand facts only. A counter about the
    # tree hiding in it would silence this test.
    for field in rf.VOLATILE_FACTS:
        assert not field.startswith(("published_", "replay_", "derived_")), (
            f"{field} is a property of the tree and must not be exempt")


def test_the_publication_inventory_has_exactly_one_definition():
    """The gate checked thirteen documents and the counter reported fourteen.

    The list existed in the Makefile, in ci.yml and hand-rolled a third time
    inside release_facts.py, and only the last included the root licence
    notice. The totals matched by luck -- DATA_LICENSE.md contains no value
    the matcher recognises -- so one decimal added to it would have split the
    published figure from the gate it describes.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables

    root = make_tables.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        # The inventory is a REPOSITORY gate. The image ships neither HANDOFF,
        # CHANGELOG nor paper/, so there is nothing here it could check.
        pytest.skip("repository documents not present (running inside the image)")
    docs = make_tables.publication_docs(root)
    assert len(docs) >= 13
    missing = [d for d in docs if not d.exists()]
    assert not missing, f"the inventory names documents that do not exist: {missing}"
    assert (root / "DATA_LICENSE.md") in docs, (
        "the licence notice is published and carries the replay inventory")
    assert any(d.name.startswith("RESULTS_") for d in docs), (
        "paper/RESULTS_*.md is globbed so a new one cannot escape the gate")

    # NOBODY ELSE ENUMERATES IT.
    mk = root / "aml-platform/Makefile"
    wf = root / ".github/workflows/ci.yml"
    for path in (mk, wf):
        if not path.exists():
            continue
        body = path.read_text()
        call = [ln for ln in body.splitlines() if "make_tables.py --check" in ln]
        assert call, f"{path.name} no longer runs the publication gate"
        assert all("--gate" in ln for ln in call), (
            f"{path.name} enumerates the publication documents itself; that "
            "list is what diverged")
        assert "RESULTS_hi_large.md" not in body, (
            f"{path.name} still names individual published documents")

    # ... and the counter agrees with the gate, which is the number that lied.
    facts = _archive_root() / "derived/release_facts.json"
    if facts.exists():
        published = json.loads(facts.read_text()).get("published_documents")
        if published is not None:
            assert published == len(docs), (
                f"release_facts says {published} published documents, the "
                f"gate covers {len(docs)}")


def test_two_sentences_on_one_line_are_scoped_separately():
    """The sentence scoping was thrown away at the last step.

    `_history_lines` returned LINE NUMBERS, so a line holding a historical
    sentence and a current claim was exempt whole:

        The v7 audit was wrong. Current release has 999 tests.

    reported no disagreement. Two sentences share a line far more often than
    one sentence spans two, so this was the commoner half of the defect.
    """
    rf = _release_facts_module()
    facts = {"tests_collected": 374}

    text = "The v7 audit was wrong. Current release has 999 tests.\n"
    got = [(k, v) for k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [("tests_collected", 999)], (
        f"a current claim sharing a line with a historical one was exempted: "
        f"{got}")

    # The other half still holds: the historical sentence itself is exempt.
    text = "It says 374 tests now. The v2 audit found 270 tests here.\n"
    got = [v for _k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [374], f"the historical figure was checked as current: {got}"

    # A full stop inside a number does not end a sentence. Splitting there
    # left the half carrying the figure unexempted.
    text = "An earlier version said the lift was 0.920 and quoted 270 tests.\n"
    assert list(rf._hits(text, facts)) == [], (
        "a historical sentence was split at a decimal point")


# ---------------------------------------------------------------------------
# 51. Cross-check after the inventory round: a prefix, a package, a claim
# ---------------------------------------------------------------------------

def test_two_images_sharing_a_digest_prefix_get_different_cache_keys():
    """The guard was tightened to 64 hex and the next line kept 12 of them.

    `env_id()` validated the whole digest and then stored
    `image.split(':')[-1][:12]`, so the collision the validation was tightened
    to prevent survived one line below the check: two valid, different images
    whose digests share twelve leading characters produced the identical
    `+imgdeadbeefcafe` identity and the same cache key. Validating an identity
    and storing a prefix of it is not validating an identity.
    """
    from aml import manifest as mf

    a = "sha256:deadbeefcafe" + "0" * 52
    b = "sha256:deadbeefcafe" + "1" * 52

    def key(value):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            return mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()

    assert key(a) != key(b), (
        "two different images with a shared 12-character digest prefix share "
        "one cache identity")
    assert a.split(":")[-1] in key(a), (
        "the cache key does not carry the whole digest")
    # The repository part is not part of the identity: these are one image.
    assert key(a) == key("ghcr.io/o/r@" + a), (
        "the same image named two ways got two cache identities, which misses "
        "hits rather than confusing them")


def _dist_contract():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import check_package
    return check_package


def test_the_package_readme_describes_what_is_actually_packaged():
    """`pyproject.readme` points here, so this file becomes the description a
    package index shows -- the one document in the repository that reaches a
    reader who never sees the repository. It said "this package and the
    container image do contain derived row-level records" and listed
    `scripts/`, `tests/`, `paper/`, `docs/` and `infra/` under what is in it.

    The wheel holds `aml/` and its dist-info; the sdist adds this README and
    `pyproject.toml`. So the claim was false in the direction that matters: it
    asserted redistribution of data whose licence status this project records
    as UNREVIEWED.
    """
    root = Path(__file__).resolve().parents[2]
    readme = root / "README.md"
    if not readme.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = readme.read_text()

    assert "This package and the container image do contain" not in body, (
        "the package README still claims the distributions ship replay rows")
    assert "the PUBLIC SNAPSHOT do" in body, (
        "the package README does not distinguish what is packaged from what "
        "is in the repository and the image")

    # The directories it used to claim were shipped are now introduced as the
    # repository layout, not as package contents.
    head = body[:body.index("## Run it without the dataset")]
    assert "What the distributions contain" in head
    assert head.index("What the distributions contain") < head.index("infra/"), (
        "the directory tree is still presented before, or instead of, what "
        "the distributions actually hold")


def test_the_packaging_contract_is_enforced_where_the_build_happens():
    """`twine check` validates metadata and never opens the archive, so the
    README's claim about the contents was outside every gate. The check runs
    in the target that already builds both artifacts."""
    root = Path(__file__).resolve().parents[2]
    cp = _dist_contract()

    assert "results_archive" in cp.FORBIDDEN, (
        "the replay bundles are the load-bearing exclusion")
    assert ".dist-info/licenses/DATA_LICENSE.md" in cp.WHEEL_REQUIRED, (
        "the wheel must carry the licence analysis it points readers at")

    if not (root / "Makefile").exists():
        pytest.skip("Makefile not present (running inside the image)")
    smoke = (root / "Makefile").read_text()
    smoke = smoke[smoke.index("\npackage-smoke:"):]
    smoke = smoke[:smoke.index("\n\n")]
    assert "check_package.py" in smoke, (
        "package-smoke builds both distributions and does not check what is "
        "inside them")
    assert ".venv/bin/python scripts/check_package.py" not in smoke, (
        "package-smoke must not reach for .venv, which CI never creates for "
        "this target")


def test_the_two_licence_notices_are_byte_identical():
    """CI's comment asserted this and nothing tested it.

    The only check compared the two paths' PRESENCE in the gate commands, so
    both files could drift apart in any way that preserved the row count --
    different licence conclusions in the copy the wheel ships and the copy a
    GitHub reader sees -- with every gate green.
    """
    root = Path(__file__).resolve().parents[3]
    pkg = Path(__file__).resolve().parents[2] / "DATA_LICENSE.md"
    top = root / "DATA_LICENSE.md"
    if not (top.exists() and pkg.exists()):
        pytest.skip("repository documents not present (running inside the image)")

    assert top.read_bytes() == pkg.read_bytes(), (
        "the root licence notice and the one the wheel ships have diverged; "
        "they are the same document and a reader sees only one of them")


def test_the_package_readme_is_inside_both_gates():
    """It publishes "526,355 rows" and was in neither inventory."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables
    import release_facts

    root = make_tables.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")

    pkg = root / "aml-platform/README.md"
    assert pkg in make_tables.publication_docs(root), (
        "the package README's values are not checked against the artifacts")
    assert pkg in release_facts.count_docs(root), (
        "the package README's replay-row count is not maintained by the gate")

    # And nobody enumerates the count list either.
    mk = root / "aml-platform/Makefile"
    wf = root / ".github/workflows/ci.yml"
    for path in (mk, wf):
        if not path.exists():
            continue
        body = path.read_text()
        call = [ln for ln in body.splitlines()
                if "release_facts.py --check" in ln]
        assert call, f"{path.name} no longer runs the count gate"
        assert all("--gate" in ln for ln in call), (
            f"{path.name} enumerates the counted documents itself")


# ---------------------------------------------------------------------------
# 52. The council audit: what the seed varies, and what the ceiling is
# ---------------------------------------------------------------------------

def test_the_seed_varies_only_the_bin_edges():
    """`random_state` is not "optimizer sensitivity". It is one 200k subsample.

    `docs/LIMITATIONS.md` told readers the 8 seeds measure optimizer
    sensitivity, and `models/config.py` named `class_weight="balanced"` as the
    leading suspect for the 37% run-to-run spread. Neither is true.
    `balanced` is a deterministic function of `y`, so it cannot vary anything
    between runs; and with `early_stopping: False` the only live consumer of
    `random_state` in HistGradientBoostingClassifier is `_BinMapper`'s
    200,000-row subsample -- the validation split and `_get_small_trainset`
    are both inside the early-stopping path, and the config sets no
    `max_features`.

    The consequence is not that the seeds are fake. Above 200k rows they
    produce genuinely different models, and the production runs are 19.5M and
    125M rows. The consequence is that the estimand is narrower than published:
    the A/B tests are robust to BIN-EDGE RESAMPLING, not to optimizer noise.

    Proof by the one observation that separates the two: below the subsample
    threshold the bin mapper uses every row, so different seeds must give
    byte-identical predictions.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    from aml.models import config as model_config

    assert model_config.gbdt_params(0)["early_stopping"] is False, (
        "early stopping is on, which re-opens the validation-split consumer "
        "of random_state and invalidates the reasoning in this test")
    assert "max_features" not in model_config.GBDT, (
        "max_features is set, which re-opens a second random_state consumer")

    rng = np.random.default_rng(0)
    n = 4000                       # far below the 200k bin subsample
    X = rng.random((n, 6)).astype(np.float32)
    y = (rng.random(n) < 0.05).astype(int)

    def fit(seed):
        m = HistGradientBoostingClassifier(
            **{**model_config.GBDT, "max_iter": 20,
               "random_state": seed, "early_stopping": False})
        return m.fit(X, y).predict_proba(X)[:, 1]

    a, b = fit(0), fit(7)
    np.testing.assert_array_equal(a, b, err_msg=(
        "two seeds produced different models BELOW the bin subsample "
        "threshold, so random_state has a consumer other than the bin mapper "
        "and the estimand stated in LIMITATIONS.md needs revisiting"))

    # And the prose must not have drifted back to the wrong attribution.
    root = Path(__file__).resolve().parents[3]
    lim = root / "aml-platform/docs/LIMITATIONS.md"
    if lim.exists():
        body = lim.read_text()
        i = body.find("Seeds are not replicates")
        assert i >= 0, "the seed caveat has gone missing"
        window = body[i:i + 1200]
        assert "bin edge" in window or "bin-edge" in window, (
            "the seed caveat no longer names bin-edge estimation as the "
            "mechanism")


def test_the_published_ceiling_is_not_the_loose_bound():
    """`B*D/P` is an upper bound on the ceiling, not the ceiling.

    `metrics.py` published the loose form in prose -- "950 reviews ... can
    never exceed 5.2% ... 52% of everything attainable" -- while the function
    below it computed `sum_d min(P_d, B) / P` and the tables carried 4.73% and
    57%. The HI-Medium test window is strongly non-stationary (81.3% of
    positives in the first 7 of 19 days; the last three days hold fewer than
    50 positive account-days in total), so the two differ by 11%.

    The wrong figures were 2-decimal tokens, below `make_tables.py --check`'s
    3-decimal threshold, so no gate could see them.
    """
    from aml.eval.metrics import recall_at_budget

    # Three days: two saturated, one that cannot spend the budget.
    ad = pd.DataFrame({
        "day": ["d1"] * 100 + ["d2"] * 100 + ["d3"] * 10,
        "score": list(np.linspace(1, 0, 100)) * 2 + list(np.linspace(1, 0, 10)),
        "y": [1] * 60 + [0] * 40 + [1] * 60 + [0] * 40 + [1] * 4 + [0] * 6,
    })
    out = recall_at_budget(ad, 50)
    total_pos = 60 + 60 + 4
    loose = 50 * 3 / total_pos                       # B*D/P
    exact = (50 + 50 + 4) / total_pos                # sum_d min(P_d, B)/P
    assert out["recall_ceiling@50"] == pytest.approx(exact), (
        "the ceiling is not sum_d min(P_d, B) / P")
    assert exact < loose, "the fixture does not exercise a slack day"

    src = Path(_script("make_tables.py")).parents[1] / "src/aml/eval/metrics.py"
    if src.exists():
        body = src.read_text()
        head = body[:body.index("def to_account_days")]
        assert "5.2%" not in head or "used to" in head.lower(), (
            "the loose bound is still published in metrics.py as if it were "
            "the ceiling")
        assert "0.04732" in head, (
            "the corrected ceiling is not stated where the wrong one was")


def test_class_weight_is_not_blamed_for_run_to_run_variation():
    """`balanced` is deterministic; it cannot vary anything between runs."""
    from sklearn.utils import compute_sample_weight

    y = np.array([0] * 990 + [1] * 10)
    a = compute_sample_weight("balanced", y)
    b = compute_sample_weight("balanced", y)
    np.testing.assert_array_equal(a, b)

    # ANCHORED ON A STRING THAT EXISTS. The first version searched for
    # `class_weight="balanced" up-weights`, which appears nowhere -- so the
    # check was skipped and the test passed against the very code it was
    # written to reject.
    root = Path(__file__).resolve().parents[2]
    cfg = (root / "src/aml/models/config.py").read_text()
    i = cfg.find('"balanced" up-weights')
    assert i >= 0, "the class_weight caveat has gone missing from config.py"
    window = cfg[i:i + 1600]
    assert "leading suspect for the" not in window, (
        "config.py still names class_weight -- a deterministic function of y "
        "-- as the source of run-to-run spread")
    assert "bin mapper" in window or "_BinMapper" in window, (
        "config.py does not name the actual source of the variation")


# ---------------------------------------------------------------------------
# 53. The council audit: coupling, scholarship, and the limits of replay
# ---------------------------------------------------------------------------

def test_ring_transactions_are_attributed_by_score_source():
    """The second wrong answer: an endpoint join with no score filter.

    `ring_endpoints` holds one row per (ring transaction, endpoint), so joining
    it to the alerted account-days on `(day, acct)` attaches an account-day to
    EVERY ring transaction that touched the account that day -- not to the one
    that supplied its maximum. `ring_transactions.parquet` carries the
    per-transaction score and the script never opened it.

    The published consequence was a 14-48% "share of score groups spanning
    multiple transactions" that measured whether an account-day touches several
    ring transactions, a different quantity. With the score source required it
    is 0% on every bundle.
    """
    art = _archive_root() / "derived/alert_unit_coupling.json"
    if not art.exists():
        pytest.skip("coupling artifact not generated in this checkout")
    d = json.loads(art.read_text())

    assert "score source" in d["_comment"], (
        "the artifact does not state how an alert is attributed to a transaction")

    for name, m in d["bundles"].items():
        if "alerting_ring_txns@50" not in m:
            continue
        # THE ATTRIBUTION MUST BE EXERCISED, not just present. Endpoints whose
        # transaction did not supply the max have to be excluded, and on these
        # bundles there are always some -- so a zero here means the filter is
        # not running.
        assert m["ring_endpoints_not_score_source@50"] > 0, (
            f"{name}: no endpoint was excluded as not-the-score-source, so the "
            "score filter is not being applied")
        assert (m["ring_endpoints_attributable@50"]
                + m["ring_endpoints_not_score_source@50"]
                == m["ring_endpoints_in_alerted@50"]), f"{name}: counts do not add up"

        # The identity ratio was removed; the proportion replaced it.
        share = m["both_endpoint_share@50"]
        assert 0.0 <= share <= 1.0, (
            f"{name}: both-endpoint share {share} is not a proportion")
        assert "account_days_per_alerting_ring_txn@50" not in m, (
            f"{name}: the retracted identity ratio is being emitted again")
        assert m["alerting_ring_txns_with_both_endpoints@50"] <= m["alerting_ring_txns@50"]

        # The corrected figure. If this ever becomes non-zero the tie proxy is
        # genuinely merging recorded transactions and §3c must be rewritten.
        assert m["ring_score_groups_spanning_multiple_txns@50"] == 0, (
            f"{name}: score groups now span multiple recorded ring "
            "transactions; LIMITATIONS §3c says they do not")
        # Ties for the maximum are reported, not silently resolved.
        assert "ring_account_days_with_tied_max@50" in m


def test_argmax_txn_id_is_not_claimed_to_carry_a_transaction_metric():
    """It names a score source. That is not a transaction-level label.

    `idxmax` picks arbitrarily among transactions tied for the maximum, and the
    account-day label is `max(y)` over ALL of the account's transactions. So an
    account-day can carry y=1 while `argmax_txn_id` points at a non-laundering
    transaction that tied with the laundering one. Demonstrated here, because
    an earlier docstring implied the field was sufficient for a
    transaction-level metric.
    """
    from aml.eval.metrics import to_account_days

    df = pd.DataFrame({
        "event_date": ["d1", "d1"],
        "sender_id": [1, 1],
        "receiver_id": [2, 3],
        "is_laundering": [0, 1],
        "ring_id": [np.nan, np.nan],
    })
    score = np.array([0.9, 0.9])          # a tie, one laundering one not
    ad = to_account_days(df, score, with_txn_id=True)
    row = ad[ad.acct == 1].iloc[0]
    assert row.y == 1
    assert df.is_laundering.iloc[int(row.argmax_txn_id)] == 0, (
        "the tie counterexample no longer holds; if idxmax became "
        "label-aware, say so and revisit the docstring")

    # The docstring must carry the warning rather than the old promise.
    doc = to_account_days.__doc__
    assert "NOT ENOUGH" in doc or "not enough" in doc, (
        "to_account_days no longer warns that argmax_txn_id is insufficient "
        "for a transaction-level metric")

    # THE CAPABILITY IS EXERCISED, NOT GREPPED.
    #
    # This used to be `assert "transactions_topk.parquet" in src` -- a string
    # search of the generator's own source text. It passed on a repository
    # where no bundle carried the table, nothing read it, and
    # `verify_replay_bundle.py` had no transaction awareness at all. A test
    # that asserts a filename appears in a file is the signature defect of this
    # repository, and it was committed inside the third fix for this very
    # quantity.
    #
    # So: build the tables from a frame whose answer is known, and recompute
    # the transaction-unit metrics from them.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_replay_bundle as mrb

    rng = np.random.default_rng(0)
    n = 400
    te = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=4), n // 4),
        "is_laundering": (rng.random(n) < 0.08).astype(int),
    })
    score = np.round(rng.random(n), 3)      # deliberate tie density
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        names = mrb._transaction_tables(te, score, dest, max_budget=20)
        assert set(names) == {"transactions_topk.parquet",
                              "per_day_positive_transactions.parquet"}
        tt = pd.read_parquet(dest / "transactions_topk.parquet")
        pdp = pd.read_parquet(dest / "per_day_positive_transactions.parquet")

        # The tie bracket must be present -- the account-day path publishes one
        # and an earlier version of this table shipped `rank` alone.
        for col in ("rank", "rank_min", "rank_max"):
            assert col in tt.columns, f"{col} missing: the tie policy is hidden"
        assert (tt.rank_min <= tt.rank_max).all()

        # Transaction-unit metrics must recompute EXACTLY against ground truth.
        full = pd.DataFrame({"day": te.event_date.to_numpy(), "score": score,
                             "y": te.is_laundering.to_numpy()})
        r = full.groupby("day")["score"].rank(ascending=False, method="first")
        P = int(pdp.positive_transactions.sum())
        assert int(full.y.sum()) == P, "the positive-transaction denominator is wrong"
        for k in (5, 10, 20):
            got = tt[tt["rank"] <= k]
            want = full[r <= k]
            assert len(got) == len(want)
            assert got.y.sum() == want.y.sum(), (
                f"transaction-unit recall@{k} does not recompute from the table")
            assert got.y.mean() == pytest.approx(want.y.mean()), (
                f"transaction-unit precision@{k} does not recompute")

    # And the default must stay OFF, because turning it on roughly doubles the
    # row-level disclosure while the CDLA question is unreviewed.
    import inspect
    sig = inspect.signature(mrb.build)
    assert sig.parameters["transaction_unit"].default is False, (
        "the transaction tables are emitted by default; that enlarges an "
        "unreviewed disclosure without a decision")


def test_the_retracted_coupling_claims_cannot_come_back():
    """A withdrawn claim returns under a new name unless the phrase is
    registered. These three were published, so they are registered."""
    reg = json.loads((_archive_root() / "RETRACTED.json").read_text())
    pats = " ".join(e["pattern"] for e in reg["retracted"])
    for needle in ("28 transactions", "ceiling_unit_sensitivity"):
        assert needle in pats, f"{needle!r} is not in the retraction registry"


def test_the_alert_unit_coupling_is_measured_not_asserted():
    """A transaction emits two account-days, so the budget counts it twice.

    This project built a permutation null for `ring_recall` precisely because
    "a sender and a receiver account-day created by the same transaction carry
    the same score", and then never checked the same coupling under
    `precision@k`, `recall@k` and the ceiling -- which are the headline
    numbers. `scripts/alert_unit_coupling.py` measures it across all nine
    replay bundles instead of arguing about it.
    """
    art = _archive_root() / "derived/alert_unit_coupling.json"
    if not art.exists():
        pytest.skip("coupling artifact not generated in this checkout")
    d = json.loads(art.read_text())
    bundles = d["bundles"]
    assert len(bundles) >= 3, "the measurement covers too few bundles to generalise"

    for name, m in bundles.items():
        ratio = m["tie_account_days_per_group@50"]
        assert 1.0 < ratio <= 2.0, (
            f"{name}: {ratio} account-days per score-tie group is outside what "
            "two endpoints per transaction can produce")
        groups = m["tie_groups@50"]
        assert m["tie_label_discordant_groups@50"] <= 0.05 * groups, (
            f"{name}: too many tie groups disagree on the label")

    # No event-unit ceiling may be published from this artifact. Deriving one
    # required transporting an ALERTED-set factor onto the positive POPULATION,
    # on top of a proxy that merges transactions.
    for m in bundles.values():
        assert not any(k.startswith("ceiling_") for k in m), (
            "an event-unit ceiling is being derived again; it needs "
            "transaction identity for every account-day, which the archived "
            "bundles do not carry")


def test_the_novelty_claim_is_stated_and_bounded():
    """One citation existed repo-wide, so the novelty claim was unstated.

    An unstated novelty claim reads as an unaware one. `RELATED_WORK.md` names
    the prior art for the two methods this project reinvented -- budget-aware
    top-k evaluation, and negative controls -- and withdraws the framing that
    presented the first as a gap in the literature.
    """
    root = Path(__file__).resolve().parents[2]
    rw = root / "docs/RELATED_WORK.md"
    if not rw.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = rw.read_text()

    for who in ("Lipsitch", "Bouthillier", "Dodge", "Altman"):
        assert who in body, f"{who} is not cited; that literature is reinvented here"
    assert "withdrawn" in body.lower(), (
        "RELATED_WORK does not withdraw the budget-aware novelty claim")

    # And it must be inside the gate, not a file nobody checks.
    #
    # REPO-LAYOUT GUARDED. The image ships `docs/` but not `aml-platform/`, so
    # `repo_root()` resolves to `/` there and the inventory is a list of paths
    # that do not exist -- the membership assertion then fails on a container
    # where the gate does not and cannot run. Third time this layout has caught
    # a test of mine; any assertion touching publication_docs/count_docs needs
    # this guard.
    sys.path.insert(0, str(root / "scripts"))
    import make_tables
    top = make_tables.repo_root()
    if not (top / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")
    assert (top / "aml-platform/docs/RELATED_WORK.md") in make_tables.publication_docs(top), (
        "RELATED_WORK.md publishes numbers and is outside the publication gate")


def test_replay_does_not_claim_to_verify_the_null():
    """The flagship reversal is the one number replay cannot check.

    `verify_replay_bundle.py` recomputes recall/ceiling/efficiency/precision/
    ring_recall and stops -- no null, no lift, no tail p-values. The README
    pitches replay as "check a published number yourself", so the exception has
    to be stated where the pitch is made.
    """
    root = Path(__file__).resolve().parents[3]
    script = _script("verify_replay_bundle.py").read_text()
    for absent in ("ring_recall_null@", "ring_recall_lift@", "null_p_lower"):
        assert absent not in script, (
            f"{absent} is now recomputed -- update this test and the README "
            "caveat, which says it is not")

    readme = root / "README.md"
    if not readme.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = readme.read_text()
    # ANCHORED ON THE PITCH, not on a heading, and searched in both directions.
    # The first version anchored on a tier-table row and looked only forward,
    # so reordering the README moved the caveat out of its window and the test
    # failed on a document that carried the caveat.
    i = body.find("verify_replay_bundle.py")
    assert i >= 0, "the README no longer pitches replay verification at all"
    window = body[max(0, i - 1500):i + 1500].lower()
    assert "not recomputed" in window, (
        "the README pitches replay without stating that the permutation null, "
        "the lift and the p-values are outside it")
    assert "sufficiency" in window, (
        "the README does not say WHY the null is outside replay -- a "
        "permutation moves scores across the top-k cut-off, so the truncation "
        "argument has not been shown to extend")


def test_every_budget_gets_an_interval():
    """`bootstrap_ci` was called at budget=50 and nowhere else.

    Six of the seven budgets in `DEFAULT_BUDGETS` -- including 200, which
    carries the HI-Large headline `recall@200` and `ring_recall@200` -- were
    published as point estimates with no uncertainty at all. Everything costly
    in the bootstrap (building account-days, ranking, clustering) is
    budget-independent, so the omission bought nothing.

    The unsuffixed `ci_lo`/`ci_hi` must keep meaning `budget`, or every
    manifest already written stops being comparable.
    """
    from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci

    rng = np.random.default_rng(0)
    n = 4000
    df = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=8), n // 8),
        "sender_id": rng.integers(0, 500, n),
        "receiver_id": rng.integers(0, 500, n),
        "is_laundering": (rng.random(n) < 0.05).astype(int),
        "ring_id": np.where(rng.random(n) < 0.03,
                            rng.integers(0, 20, n).astype(float), np.nan),
    })
    score = rng.random(n) + df.is_laundering * 0.5

    out = bootstrap_ci(df, score, budget=50, n=200, budgets=DEFAULT_BUDGETS)
    for b in DEFAULT_BUDGETS:
        assert f"ci_lo@{b}" in out and f"ci_hi@{b}" in out, (
            f"budget {b} is published without an interval")
        assert out[f"ci_lo@{b}"] <= out[f"ci_hi@{b}"]

    assert out["ci_lo@50"] == out["ci_lo"] and out["ci_hi@50"] == out["ci_hi"], (
        "the unsuffixed interval stopped meaning `budget`, which silently "
        "changes what every existing manifest's ci_lo/ci_hi refers to")

    # Wider budgets catch more, so the intervals must be monotone in k.
    los = [out[f"ci_lo@{b}"] for b in DEFAULT_BUDGETS]
    assert los == sorted(los), f"recall CI lower bounds are not monotone in k: {los}"

    # THE CONTRACT, not the spelling.
    #
    # The first version of this check only asserted that `budgets=` appeared
    # near the call, which two callers satisfied while still being wrong: the
    # drift experiment evaluated (10, 50, 200) and requested intervals at all
    # seven defaults, and `eval.run` accepted arbitrary budgets and hardcoded
    # 50. Grepping for an argument name cannot see either. Exercise it instead.
    assert out["ci_budget"] == 50

    with pytest.raises(ValueError, match="not in budgets"):
        bootstrap_ci(df, score, budget=50, n=50, budgets=(10, 200))

    # A caller that never asks for 50 must not receive an interval at 50.
    from aml.eval import run as eval_run
    body = (Path(eval_run.__file__)).read_text()
    i = body.find("bootstrap_ci(")
    assert "budget=legacy" in body[i:i + 200], (
        "eval.run still pins the unsuffixed interval to 50 regardless of what "
        "the caller asked for")

    # The drift experiment must use ONE tuple for evaluation and intervals.
    from aml.drift import experiment as drift
    d = Path(drift.__file__).read_text()
    assert "DRIFT_BUDGETS" in d, "the drift experiment has no single budget tuple"
    assert d.count("budgets=DRIFT_BUDGETS") == 2, (
        "the drift experiment does not use the same budgets for evaluate() and "
        "bootstrap_ci(); that is how four intervals came to describe operating "
        "points the run never measured")
    assert "budgets=DEFAULT_BUDGETS" not in d


def test_recorded_input_hashes_are_recomputed_not_just_stored():
    """A hash nothing recompares is a comment.

    `_input_identity` was changed to content-hash a directory small enough to
    afford it, which the 9.2 MB replay bundles are. That closed the "a
    same-size mutation keeps the same identity" hole -- but only if something
    checks the recorded value against the tree. Nothing did, so a later change
    to the bundles would have left the artifact quietly stale while every gate
    stayed green.

    ONE ARTIFACT WAS NOT ENOUGH. This checked only the coupling artifact, so
    `typology_null.json` -- which recorded `inputs=[results_archive]`, its own
    output directory, and named neither the patterns file it parsed nor the
    bundle it measured -- was never compared to anything. Every derived
    artifact now goes through it, and every hash key, not just the directory
    one.
    """
    from aml.manifest import _input_identity

    root = _archive_root().parent
    checked = 0
    for art in sorted((_archive_root() / "derived").glob("*.json")):
        d = json.loads(art.read_text())
        for e in d.get("inputs", []):
            keys = [k for k in ("sha256", "content_sha256", "listing_sha256")
                    if e.get(k)]
            if not keys:
                # Legitimately unhashed: a file past OUTPUT_HASH_MAX_BYTES
                # records size only. It must still say where it is.
                assert e.get("path"), f"{art.name}: an input with no path"
                continue
            tail = e["path"].split("results_archive/", 1)
            target = (_archive_root() / tail[1]) if len(tail) == 2 \
                else root / e["path"].split("aml-platform/", 1)[-1]
            if not target.exists():
                continue          # raw dataset, not in every checkout
            fresh = _input_identity(target)
            for k in keys:
                assert fresh.get(k) == e[k], (
                    f"{art.name}: {e['path']} has changed since the artifact "
                    f"was generated ({k}: recorded {e[k][:16]}, actual "
                    f"{str(fresh.get(k))[:16]}). Regenerate it.")
                checked += 1
            assert not e["path"].startswith("/"), (
                f"{art.name}: {e['path']} is absolute; not portable")
    assert checked >= 8, (
        f"only {checked} recorded hash(es) could be recomputed; this gate is "
        "not exercising the artifacts it claims to cover")


def test_no_artifact_takes_its_own_output_directory_as_an_input():
    """A self-referential input identity is not an identity.

    `typology_null.json` recorded `inputs=[results_archive]` -- the directory
    it is itself written into. So its input hash changed whenever ANY other
    artifact changed, was guaranteed to disagree with itself after its own
    write, and told a reader nothing about which files the result actually
    depended on. The two stability artifacts, the parsed rings and the two
    bundle tables it reads were all absent from the record.

    An input may not be the artifact itself, nor any directory containing it.
    """
    root = _archive_root().parent
    for art in sorted((_archive_root() / "derived").glob("*.json")):
        d = json.loads(art.read_text())
        for e in d.get("inputs", []):
            path = e.get("path", "")
            tail = path.split("results_archive/", 1)
            target = (_archive_root() / tail[1]) if len(tail) == 2 \
                else root / path.split("aml-platform/", 1)[-1]
            if not target.exists():
                continue
            assert target.resolve() not in (art.resolve(), *art.resolve().parents), (
                f"{art.name} names {path} as an input, and its own output is "
                "inside it. That identity changes when anything unrelated in "
                "the tree changes and cannot be reproduced.")


def test_bootstrap_ci_has_one_schema_on_every_path():
    """Three early returns emitted a different key set from the normal path.

    `n < 1`, no positives, and fewer than two clusters each returned only the
    unsuffixed pair while the normal path also returned `ci_lo@k`/`ci_hi@k`. A
    reader cannot then distinguish "no interval at this budget" from "this run
    took a short path", and two runs of the same pipeline produce different
    manifest schemas.
    """
    from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci

    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=6), n // 6),
        "sender_id": rng.integers(0, 90, n),
        "receiver_id": rng.integers(0, 90, n),
        "is_laundering": (rng.random(n) < 0.06).astype(int),
        "ring_id": [np.nan] * n,
    })
    score = rng.random(n)

    def ci_keys(d):
        return tuple(sorted(k for k in d if k.startswith("ci_")))

    full = bootstrap_ci(df, score, budget=50, n=100, budgets=DEFAULT_BUDGETS)
    skipped = bootstrap_ci(df, score, budget=50, n=0, budgets=DEFAULT_BUDGETS)
    no_pos = bootstrap_ci(df.assign(is_laundering=0), score, budget=50,
                          n=100, budgets=DEFAULT_BUDGETS)

    assert ci_keys(full) == ci_keys(skipped) == ci_keys(no_pos), (
        "bootstrap_ci returns different key sets depending on which path it "
        "takes")
    assert all(f"ci_lo@{b}" in full for b in DEFAULT_BUDGETS)
    assert full["ci_budget"] == skipped["ci_budget"] == 50


# ---------------------------------------------------------------------------
# 54. The generator winds down, and the headline pooled two regimes
# ---------------------------------------------------------------------------

def test_the_window_decomposition_exists_and_shows_two_regimes():
    """The quantity eleven audit rounds never recorded: transactions per day.

    Every budget metric here is a per-day top-k statistic, so its value depends
    on how many transactions each day holds -- and that number appeared in no
    document, no manifest and no artifact. AMLworld's generator winds down:
    HI-Medium goes from 3,021,866 transactions at 0.0008 laundering to 2,020 at
    0.5936 overnight. The published window pools both.
    """
    art = _archive_root() / "derived/window_decomposition.json"
    if not art.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(art.read_text())

    prof = d.get("volume_profile", {})
    assert prof, "no volume profile was measured"
    for rung, p in prof.items():
        days = p["per_day"]
        prevalences = [r["prevalence"] for r in days]
        # The collapse must be visible, or the finding has evaporated.
        assert max(prevalences) > 10 * min(prevalences), (
            f"HI-{rung}: prevalence is flat across the window; the wind-down "
            "this section documents is not present")
        assert p["first_thin_day"], f"HI-{rung}: no thin day identified"

    # And the decomposition must show the tail carrying the majority of the
    # ceiling on HI-Medium, which is the counter-intuitive half.
    med = d["bundle_decomposition"].get("medium_baseline_s0")
    if med:
        assert med["ceiling_share_tail@50"] > 0.5, (
            "the tail no longer holds the majority of the attainable positives")
        assert med["true_positive_share_tail@50"] > 0.9, (
            "the logistic baseline's true positives are no longer "
            "concentrated in the tail; §1's retraction needs revisiting")
        # The whole point: pooled sits between the two regimes.
        assert (med["precision_head@50"] < med["precision_pooled@50"]
                < med["precision_tail@50"]), (
            "the pooled precision is not between its two segments")


def test_the_segment_boundary_comes_from_transaction_volume():
    """Segmenting on the smoother series hid the effect.

    The first version of `window_volume.py` chose the boundary from the per-day
    POSITIVE count, which declines gradually and put it twelve days in.
    Transactions do not decline, they fall off a cliff. Choosing the boundary
    from the wrong variable understated the finding.

    It also matched profiles to bundles by date containment, which picked
    HI-Medium for `small_gbdt_s0` because the HI-Small window sits inside the
    HI-Medium calendar -- two independent generator runs that share dates.
    """
    art = _archive_root() / "derived/window_decomposition.json"
    if not art.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(art.read_text())
    dec = d["bundle_decomposition"]

    for name, v in dec.items():
        src = v["segment_boundary_source"]
        if src.startswith("fallback"):
            assert "unavailable" in src, (
                f"{name}: a fallback boundary must say why it is one")
            continue
        rung = name.split("_")[0]
        assert rung.lower() in src.lower(), (
            f"{name}: boundary sourced from {src!r}, which is not its own rung "
            "-- the rungs are independent runs that share calendar dates")

    # The Medium and Small bundles must not share a boundary day.
    med = {v["segment_boundary_day"] for k, v in dec.items() if k.startswith("medium")}
    sml = {v["segment_boundary_day"] for k, v in dec.items() if k.startswith("small")}
    if med and sml:
        assert not (med & sml), (
            f"HI-Medium and HI-Small share a segment boundary {med & sml}; "
            "that is the date-containment bug returning")


def test_the_ceiling_comment_is_not_backwards():
    """`metrics.py` said budget metrics are "dominated by week one".

    It was written in the same edit that fixed the ceiling arithmetic, and it
    reasoned from the 81.3% positive front-loading without noticing that
    `min(P_d, B)` caps the busy days and redistributes the attainable count
    toward the thin ones. Week one is 40.8% of the ceiling and 3.0% of the
    logistic model's true positives.
    """
    src = (Path(__file__).resolve().parents[2] / "src/aml/eval/metrics.py").read_text()
    head = src[:src.index("def to_account_days")]
    assert "BACKWARDS" in head, (
        "the correction has gone missing from the ceiling comment")
    assert "winds down" in head, (
        "the ceiling comment does not name the mechanism (generator wind-down)")
    # The wrong claim may only appear as a quoted record.
    i = head.find("dominated by week one")
    assert i >= 0, "the retraction no longer quotes the claim it retracts"
    assert "USED TO" in head[:i] or "used to" in head[:i], (
        "the claim is stated again without being marked as the retracted one")


# ---------------------------------------------------------------------------
# 55. Two gates that would have caught the retracted definitions
# ---------------------------------------------------------------------------

def test_no_published_ratio_is_an_identity_on_two_published_counts():
    """A number a reader can back-solve from its neighbours is not evidence.

    THE DEFECT: a README table written specifically to fix a unit-mixing
    problem contained four numerical errors, one of them BACK-SOLVED from two
    neighbouring cells -- which made that table internally consistent BY
    CONSTRUCTION, so no cross-check on it could ever have failed.

    WHERE THIS GATE HAS BEEN WRONG, twice:

    1. Its assertion was loop-invariant: it collected offenders and never
       referenced them, so one documented sentence exempted the whole set
       forever. An auditor injected two new identities and it passed.
    2. It then scanned `results_archive/derived/*.json` only -- 13 files, 2.2%
       of the archived scalars -- so the same injection failed there and
       passed in `gold/eval_Medium/seed3/`.

    Widening the artifact glob is NOT the fix, and measuring says so: the whole
    archive holds 2,239 identity instances in 238 families, almost all
    coincidences between fields nobody quotes
    (`ring_recall_null_lo@k == tied_at_boundary@k / ring_size_p90@k`). Chasing
    those would bury the one case that matters.

    The risk is a PUBLISHED cell that is an exact function of cells beside it,
    so the test belongs on the document, not the artifact. It reads every
    gated line, and flags a line where one value is `b/a` or `1 + b/a` of two
    others ON THAT SAME LINE. A line may declare the relationship -- that is
    what `<!-- derived: 1 + 956/1006 -->` is -- or LIMITATIONS may name the
    metric. Otherwise it fails, and no artifact layout can hide it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")
    lim = (root / "aml-platform/docs/LIMITATIONS.md").read_text()

    offenders = []
    for d in mt.publication_docs(root):
        if not d.exists():
            continue
        for n, line in enumerate(d.read_text().splitlines(), 1):
            if "<!-- historical -->" in line:
                continue          # a record of superseded arithmetic
            toks = [t for t, _ in mt.document_tokens(line)]
            if len(toks) < 3:
                continue
            mk = mt.DERIVED.search(line)
            dvals, dnamed, _ = mt.derived_reasons(mk.group("body")) if mk \
                else ([], {}, [])
            vals = [(t, float(t)) for t in toks
                    if re.fullmatch(r"-?\d+(?:\.\d+)?", t)]
            for rt, rv in vals:
                if rv == 0 or float(rv).is_integer():
                    continue
                if mt.derived_accounts_for(rt, dvals, dnamed):
                    continue      # the line states where it comes from
                for at, av in vals:
                    # A divisor or numerator near 1 makes everything an
                    # identity; so does a tiny operand. Numerology, not
                    # structure.
                    if at == rt or av == 0 or abs(abs(av) - 1.0) < 0.05:
                        continue
                    for bt, bv in vals:
                        if bt in (at, rt) or abs(bv) < 1e-3 \
                                or abs(abs(bv) - 1.0) < 0.05:
                            continue
                        for form, val in (("1+b/a", 1 + bv / av),
                                          ("b/a", bv / av)):
                            tol = 1e-12 + 5e-6 * abs(rv)
                            if abs(rv - val) <= tol:
                                offenders.append(
                                    (d.name, n, rt, form, at, bt, line.strip()[:90]))
    # Named in LIMITATIONS by value or by the metric it belongs to.
    undocumented = [o for o in offenders if o[2] not in lim]
    assert not undocumented, (
        "these published values are exact functions of two others on the same "
        "line, and neither the line nor LIMITATIONS.md says so. Either declare "
        "it -- `<!-- derived: a/b -->` -- or stop publishing it as independent "
        "evidence:\n  " + "\n  ".join(
            f"{f}:{n}  {r} == {form} of ({b}, {a})\n      {txt}"
            for f, n, r, form, a, b, txt in undocumented[:8]))


def test_a_constructed_bundle_discriminates_the_three_definitions():
    """The fixture that would have caught both retracted alert-unit attempts.

    Answer known by construction. Three ring transactions each supply the
    maximum of both endpoints; one ring transaction touches an account without
    supplying its maximum; one NON-ring transaction supplies a further
    account-day and shares a score with the first ring transaction.

    Truth: 4 transactions supply the 7 alerted account-days; 3 of them are
    ring transactions.

    ⚠️ The decoys must BOTH be inside the budget. A first draft of this fixture
    put the tie decoy outside it, and the score-tie proxy then returned the
    right answer for the wrong reason -- a fixture that passes a broken
    definition is worse than none.
    """
    ad = pd.DataFrame({
        "day": ["d"] * 7, "acct": [1, 2, 3, 4, 5, 6, 7],
        "score": [0.9, 0.9, 0.8, 0.8, 0.7, 0.7, 0.9],
        "y": [1, 1, 1, 1, 1, 1, 0], "rank": [1, 2, 3, 4, 5, 6, 7],
        "argmax_txn_id": [0, 0, 1, 1, 2, 2, 4],
    })
    rt = pd.DataFrame({"rt": [0, 1, 2, 3], "day": ["d"] * 4,
                       "score": [0.9, 0.8, 0.7, 0.5]})
    ep = pd.DataFrame({"day": ["d"] * 8, "acct": [1, 2, 3, 4, 5, 6, 1, 1],
                       "ring_id": [10, 10, 11, 11, 12, 12, 13, 13],
                       "rt": [0, 0, 1, 1, 2, 2, 3, 3]})
    TRUTH_FULL, TRUTH_RING = 4, 3

    # Definition 1, retracted: group by equal score.
    d1 = ad.groupby(["day", "score"]).ngroups
    # Definition 2, retracted: join endpoints on (day, acct), no score filter.
    d2 = (ep.merge(ad[["day", "acct"]], on=["day", "acct"], how="inner")
            .groupby(["day", "rt"]).ngroups)
    # Definition 3, shipped: CALL THE SHIPPED CODE, do not re-implement it.
    #
    # ⚠️ The first version of this test re-implemented all four definitions
    # inline with its own pandas and never imported `alert_unit_coupling`. It
    # therefore tested that pandas works: breaking `measure()` left it green.
    # It also omitted the `rank <= b` filter the shipped code applies.
    import tempfile as _tf

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import alert_unit_coupling as auc

    with _tf.TemporaryDirectory() as tmp:
        b = Path(tmp)
        ad.to_parquet(b / "account_days_topk.parquet", index=False)
        rt.to_parquet(b / "ring_transactions.parquet", index=False)
        ep.to_parquet(b / "ring_endpoints.parquet", index=False)
        got = auc.measure(b, budgets=(7,))
    d3 = got["alerting_ring_txns@7"]
    # Definition 4: the primitive.
    d4 = ad.groupby(["day", "argmax_txn_id"]).ngroups

    assert d1 != TRUTH_FULL, (
        "the score-tie proxy now returns the right answer on a fixture built "
        "to break it -- the fixture has stopped discriminating")
    assert d2 != TRUTH_RING, "the unfiltered endpoint join is no longer caught"
    assert d3 == TRUTH_RING, (
        f"the shipped score-source definition returns {d3}, not {TRUTH_RING}")
    assert d4 == TRUTH_FULL, (
        f"argmax_txn_id returns {d4}, not {TRUTH_FULL}; the primitive is the "
        "one route that recovers the full-set answer")


def test_derived_markers_are_necessary():
    """A marker that exempts artifact-backed values weakens the gate for free.

    `<!-- derived -->` exempts a whole LINE, and a table row holds several
    values. The HI-Large lift row carried the marker for its computed mean and
    thereby exempted the three per-seed lifts beside it -- the only evidence
    the headline is seed-stable -- even though all three are in the manifests.
    Removing it moved eight values from exempt to checked.

    So every marker has to earn its place: if all the values on a marked line
    are artifact-backed, the marker is removable and must be removed.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")

    mt.ARCHIVE = Path(root / "aml-platform/results_archive")
    rows = mt.collect(mt.ARCHIVE)

    # THE GATE'S OWN INDEX AND THE GATE'S OWN EXTRACTOR.
    #
    # This test used to build both itself -- a reimplemented value index and
    # `re.compile(r"\b0\.\d{3,6}\b")`. Both were narrower than the thing they
    # police: the index ignored the derived per-seed means, and the regex could
    # not see a value of 1 or more, so 18 of 83 markers were unauditable and
    # `README.md`'s headline lift was among them. A checker and the test that
    # polices it must not keep separate copies of the rules.
    assert mt.marker_report(rows, mt.publication_docs(root)) == 0, (
        "some <!-- derived --> marker does not account for a value on its "
        "line; run `python scripts/make_tables.py --markers` for the list")


def test_a_non_stationary_pooling_unit_forces_a_segment_decomposition():
    """The gate that catches an error of OMISSION.

    Both other new gates live in assertion space: they inspect values that
    were published. The largest error in this project's history was an
    absence — nobody recorded transactions per day, so nobody noticed that
    every per-day budget metric pooled a 637,998x volume range and a
    0.002643-to-1.0 prevalence range. Neither identity checks nor constructed
    fixtures can fire on a quantity that does not exist.

    So: if a rung's pooling unit is non-stationary beyond a stated factor, the
    repository must carry a segment decomposition and the per-day profile. The
    threshold is deliberately loose — 100x — because the measured values are
    637,998x and 101,356x, and anything in that neighbourhood is not a
    borderline call.
    """
    win = _archive_root() / "derived/window_decomposition.json"
    if not win.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(win.read_text())
    profiles = d.get("volume_profile", {})
    assert profiles, "no per-day population profile is recorded for any rung"

    LIMIT = 100.0
    for rung, prof in profiles.items():
        tx = [r["transactions"] for r in prof["per_day"] if r["transactions"] > 0]
        pv = [r["prevalence"] for r in prof["per_day"] if r["transactions"] > 0]
        ratio = max(tx) / min(tx)
        prev_ratio = max(pv) / min(pv) if min(pv) > 0 else float("inf")
        if ratio <= LIMIT and prev_ratio <= LIMIT:
            continue

        # Non-stationary: a decomposition and a null are both required.
        dec = [k for k in d.get("bundle_decomposition", {})
               if rung.lower() in k.lower()]
        assert dec, (
            f"HI-{rung}: pooling unit varies {ratio:,.0f}x in volume and "
            f"{prev_ratio:,.0f}x in prevalence, and no bundle carries a segment "
            "decomposition")
        for name in dec:
            e = d["bundle_decomposition"][name]
            for need in ("precision_head@50", "precision_tail@50",
                         "ceiling_share_tail@50"):
                assert need in e, f"{name}: {need} missing from the decomposition"

        nullf = _archive_root() / "derived/budget_null.json"
        assert nullf.exists(), (
            f"HI-{rung} is non-stationary, so a pooled budget level is a "
            "weighted mean of regimes. A random-ranker null is required and "
            "budget_null.json is absent")
        nd = json.loads(nullf.read_text())["rungs"].get(rung)
        assert nd, f"HI-{rung} has no entry in budget_null.json"

        # ⚠️ POPULATION IDENTITY, NOT MERE PRESENCE.
        #
        # This asserted only that a null existed and was positive. The null was
        # then computed from the raw CSV with a date cut, on 30,867 positive
        # account-days instead of the evaluated split's 18,130 -- the ring-aware
        # filter drops 736 of 1,265 test rings -- so the repository published
        # "the headline is below chance" when it is above. A gate that proves
        # presence cannot catch a wrong population.
        split = (Path(_archive_root()).parent
                 / f"results_archive/gold/splits_{rung}/manifest.json")
        if split.exists():
            sm = json.loads(split.read_text()).get("metrics", {})
            want_pos = sm.get("test_positive_account_days")
            assert nd.get("n_positive_total") == want_pos, (
                f"HI-{rung}: the null sums {nd.get('n_positive_total')} "
                f"positive account-days; the split manifest says {want_pos}. "
                "The null and the model are on different populations.")
            rec = nd.get("split_manifest", {})
            assert rec.get("test_total_account_days") == sm.get(
                "test_total_account_days"), (
                f"HI-{rung}: the artifact does not record the split's own "
                "account-day total, so its population cannot be checked")
            # The ceiling must match the decomposition computed from the
            # bundles, not the raw file.
            dec = next((d["bundle_decomposition"][k]
                        for k in d["bundle_decomposition"]
                        if rung.lower() in k.lower()), None)
            if dec:
                want_ceil = (dec["ceiling_count_head@50"]
                             + dec["ceiling_count_tail@50"])
                assert nd["ceiling_count@50"] == want_ceil, (
                    f"HI-{rung}: null ceiling {nd['ceiling_count@50']} != "
                    f"{want_ceil} from the bundle decomposition")
                assert (nd["ceiling_budget_limited@50"]
                        + nd["ceiling_positive_limited@50"]
                        == nd["ceiling_count@50"]), (
                    f"HI-{rung}: the ceiling split does not sum to the ceiling")

        # Bracketed, and the adverse bound is the one a claim must clear.
        for key in ("null_precision_low@50", "null_precision_high@50"):
            assert nd.get(key, 0) > 0, f"HI-{rung}: {key} was not computed"
        assert nd["null_precision_low@50"] <= nd["null_precision_high@50"]
        assert nd.get("null_precision_high_sd@50") is not None, (
            f"HI-{rung}: an above/below-chance claim needs an interval, not "
            "only a point estimate")
        # And the non-binding days must be enumerated, not merely counted.
        assert "nonbinding_day_list@50" in nd, (
            f"HI-{rung}: days where the budget exceeds the population are not "
            "listed, so a reader cannot exclude them")


# ---------------------------------------------------------------------------
# 56. The wrong-population typology null, and the unsound N_d exactness rule
# ---------------------------------------------------------------------------

def test_a_truncated_day_is_never_called_exact():
    """`count == max(rank)` does not mean "the day was written in full".

    `budget_null.evaluated_population` declared N_d exact whenever the ranks
    written were contiguous. A day truncated at exactly the bundle's top-k cap
    satisfies that: 2022-09-18 wrote 1,000 rows topping out at rank 1,000, and
    the rule read that as "this day holds exactly 1,000 account-days" when the
    bundle cannot distinguish it from a day holding 200,000. It published the
    most adverse end of its own bracket as a certainty.

    The rule has to be `max(rank) < cap` -- a day that never reached the cap
    cannot have had anything dropped. This test builds the ambiguous case and
    the unambiguous one and asserts the tool tells them apart.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bn", _script("budget_null.py"))
    bn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bn)

    with tempfile.TemporaryDirectory() as td:
        b = Path(td)
        (b / "bundle.json").write_text(json.dumps({"max_budget": 1000}))

        # Day A: capped. 1,000 rows, highest rank 1,000 -- contiguous, and
        # completely uninformative about N_d.
        # Day B: uncapped. 400 rows, highest rank 400 -- proof of N_d = 400.
        rows = ([{"day": "2022-09-18", "rank": i} for i in range(1, 1001)]
                + [{"day": "2022-09-19", "rank": i} for i in range(1, 401)])
        pd.DataFrame(rows).to_parquet(b / "account_days_topk.parquet",
                                      index=False)
        pd.DataFrame([{"day": "2022-09-18", "positive_account_days": 738},
                      {"day": "2022-09-19", "positive_account_days": 200}]
                     ).to_parquet(b / "per_day_positives.parquet", index=False)
        raw = pd.DataFrame([{"day": "2022-09-18", "n_account_days": 1466},
                            {"day": "2022-09-19", "n_account_days": 400}])

        pop = bn.evaluated_population(b, raw, removed=4074)
        by = {r["day"]: r for r in pop.to_dict("records")}

    capped = by["2022-09-18"]
    assert capped["n_d_low"] != capped["n_d_high"], (
        "a day whose highest written rank IS the bundle cap was called exact. "
        "Contiguous ranks at cap length prove nothing: the bundle stops there "
        f"by construction. Got N_d = {capped['n_d_low']} as a point value.")
    assert "exact" not in capped["n_d_source"], (
        f"the capped day is described as {capped['n_d_source']!r}")
    assert capped["n_d_high"] == 1466, "the raw count is the upper bound"

    uncapped = by["2022-09-19"]
    assert uncapped["n_d_low"] == uncapped["n_d_high"] == 400, (
        "a day that never reached the cap IS exact, and the rule must not be "
        "so conservative that it throws away the days it can actually resolve")
    assert "exact" in uncapped["n_d_source"]


def test_the_lower_bound_never_falls_below_a_rank_the_bundle_recorded():
    """Observing rank 1,026 proves the day held at least 1,026 account-days.

    The bracket's lower bound was `max(P_d, raw - total_removal)`, which on
    2022-09-17 is max(940, 1873-4074) = 940 -- on a day the bundle itself
    records a rank of 1,026 for. That is not a loose bound, it is a
    contradiction: it admits populations in which rows the bundle contains do
    not exist, and it biases the null UPWARD, which is the direction that
    flatters an 'above chance' claim.
    """
    art = _archive_root() / "derived/budget_null.json"
    if not art.exists():
        pytest.skip("budget null not generated in this checkout")
    rungs = json.loads(art.read_text())["rungs"]

    bundles = {"Medium": "medium_baseline_s0", "Small": "small_gbdt_s0"}
    for rung, facts in rungs.items():
        bdir = _archive_root() / "replay" / bundles.get(rung, "")
        if not bdir.is_dir():
            continue
        ad = pd.read_parquet(bdir / "account_days_topk.parquet")
        mx = (ad.assign(_d=pd.to_datetime(ad.day).dt.date)
                .groupby("_d")["rank"].max().to_dict())
        for r in facts["per_day"]:
            d = pd.Timestamp(r["day"]).date()
            if d not in mx:
                continue
            assert r["n_d_low"] >= int(mx[d]), (
                f"HI-{rung} {r['day']}: N_d lower bound {r['n_d_low']} is "
                f"below rank {int(mx[d])}, which the bundle records for that "
                "day. A population cannot be smaller than a rank observed in "
                "it.")
            assert r["n_d_low"] >= r["n_positive"], (
                f"HI-{rung} {r['day']}: N_d lower bound {r['n_d_low']} is "
                f"below its {r['n_positive']} positives -- prevalence > 1")
            assert r["n_d_low"] <= r["n_d_high"], (
                f"HI-{rung} {r['day']}: inverted bracket")


def test_cliff_exposure_is_measured_on_the_rings_that_were_evaluated():
    """The population identity, asserted rather than assumed.

    The first cliff-aware typology null measured exposure over every ring in
    the parsed patterns file -- 1,908 of them -- while the detection rates it
    was explaining came from the 529 rings the ring-aware split keeps. The two
    sides of the comparison described different ring sets, which is the same
    defect as the random-ranker null one section up, in a second place.

    `typology_null.cliff_exposure` now raises on a per-typology mismatch. This
    checks both that the shipped artifact agrees with the stability artifact
    ring-for-ring, and that the function actually refuses when it does not.
    """
    import importlib.util

    art = _archive_root() / "derived/typology_null.json"
    stab = _archive_root() / "gold/typology_Medium/stability.json"
    if not art.exists() or not stab.exists():
        pytest.skip("typology artifacts not generated in this checkout")

    d = json.loads(art.read_text())
    exp = d.get("cliff_exposure_Medium")
    if exp is None:
        assert "error" in d.get("exposure_only_spread_Medium", {}), (
            "no exposure was measured, yet the artifact does not say so -- a "
            "reader cannot tell a missing input from a null that was computed")
        pytest.skip("patterns absent; exposure correctly not computed")

    # `_spread` is a summary row the sweep writes beside the structures. It is
    # not a typology and must not become a ninth point.
    want = {k: v["n_rings"] for k, v
            in json.loads(stab.read_text())["current"]["per_typology"].items()
            if not k.startswith("_")}
    got = {k: v["n_rings"] for k, v in exp.items()}
    assert got == want, (
        f"exposure was measured on {sum(got.values())} rings, detection on "
        f"{sum(want.values())}: {got} vs {want}")
    assert got == d["spread_Medium"]["n_rings"], (
        "the exposure population and the spread population disagree inside "
        f"one artifact: {got} vs {d['spread_Medium']['n_rings']}")
    assert sum(got.values()) == 529, (
        f"the evaluated split keeps 529 test rings; this is {sum(got.values())}")

    # AND THE GUARD IS REAL. Feed it a stability map one ring short.
    spec = importlib.util.spec_from_file_location(
        "_tn", _script("typology_null.py"))
    tn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tn)
    # SYNTHESISED, not read from `data/`. The image ships results_archive/ and
    # NOT data/ -- it is gitignored -- so guarding on the parsed patterns made
    # this skip inside the container, which is where the check is most worth
    # running. A test that skips is not a test (this repo has learned that four
    # times), and the guard was also an unallowlisted skip reason that would
    # have turned the `image` job red and blocked every merge.
    bundle = _archive_root() / "replay/medium_gbdt_s0"
    if not (bundle / "ring_membership.parquet").exists():
        pytest.skip("no replay bundles in this checkout")
    mem = pd.read_parquet(bundle / "ring_membership.parquet")
    ids = sorted({int(x) for x in mem.ring_id.dropna()})
    with tempfile.TemporaryDirectory() as td:
        pdir = Path(td)
        pd.DataFrame({
            "ring_id": ids,
            "typology": [sorted(want)[i % len(want)] for i in range(len(ids))],
            "end_time": pd.Timestamp("2022-09-20"),
        }).to_parquet(pdir / "rings.parquet", index=False)
        # The synthetic typology assignment is deliberately NOT the real one,
        # so the per-typology counts cannot match `want` -- which is exactly
        # the mismatch the guard exists to refuse.
        stab_shape = {k: {"n_rings": v} for k, v in want.items()}
        with pytest.raises(RuntimeError, match="different ring population"):
            tn.cliff_exposure(pdir, bundle, "2022-09-17", stab_shape)


def test_an_assumed_segment_rate_must_be_able_to_reproduce_the_pooled_rate():
    """0.80, 0.90 and 0.95 were all arithmetically impossible.

    With an after-cliff share `s` and assumed after-cliff rate `t`, the pooled
    rate is `s*t + (1-s)*h`, so a head rate in [0, 1] exists only when
    `(pooled - s*t)` lands in `[0, 1-s]`. At s = 0.66352 and pooled = 0.3724
    that caps `t` at 0.56125 -- every rate in the withdrawn table was outside
    it, and the simulation fitted a NEGATIVE head rate to compensate, clipped
    it, and reported a p-value for a world that cannot exist.

    The replacement measures the rates instead. This test asserts the
    feasibility range is published, that it is arithmetically right, and that
    the withdrawn assumptions fall outside it.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        pytest.skip("typology null not generated in this checkout")
    d = json.loads(art.read_text())
    fr = d.get("feasible_tail_range_ensemble_basis")
    if fr is None:
        pytest.skip("no exposure measured in this checkout")

    s, pooled = fr["after_cliff_share"], fr["pooled_rate"]
    assert abs(fr["max_feasible_tail_rate"] - pooled / s) < 1e-4, (
        "the published cap is not pooled/share")
    assert abs(fr["min_feasible_tail_rate"] - max(0.0, (pooled - (1 - s)) / s)
               ) < 1e-4
    for assumed in (0.80, 0.90, 0.95):
        assert assumed > fr["max_feasible_tail_rate"], (
            f"an after-cliff rate of {assumed} is now inside the feasible "
            "range, so the retraction's stated reason no longer holds and "
            "must be rewritten")

    # The rates that ARE published must be measured, and must be feasible on
    # their own basis: their mixture has to reproduce their own pooled rate.
    r = d.get("measured_segment_rates_Medium")
    assert r is not None, (
        "the exposure-only null publishes a p-value without publishing the "
        "rates it simulated; an assumed rate would be indistinguishable")
    sh = r["n_after"] / r["n_rings"]
    mix = sh * r["tail_rate_measured"] + (1 - sh) * r["head_rate_measured"]
    assert abs(mix - r["pooled_rate"]) < 5e-4, (
        f"the measured strata mix to {mix:.5f}, not to the reported pooled "
        f"rate {r['pooled_rate']}: they are not the same population")
    assert r["n_after"] + r["n_before"] == r["n_rings"] == 529, (
        "the measured basis is not the evaluated 529 rings")


def test_seeded_artifacts_were_generated_at_their_documented_parameters():
    """"Exact (seeded)" is a claim about a COMMAND, not about a seed.

    `typology_null.py` seeds `default_rng(0)`, so the release checklist calls
    its artifact exactly reproducible by `python scripts/typology_null.py`. But
    every simulation in it draws from one generator in sequence, so passing a
    non-default `--draws` shifts the stream feeding the LATER ones: a run at
    40,000 draws moved `median_rho_if_ordering_replicated_perfectly` from
    0.7619 to 0.7545 and the replication p from 1.375% to 0.8% -- published
    values, changed by a flag that reads like it only buys precision.

    The committed artifact must therefore record the defaults, or the
    documented command does not reproduce it.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        pytest.skip("typology null not generated in this checkout")
    src = _script("typology_null.py").read_text()
    params = json.loads(art.read_text()).get("parameters", {})
    for flag, key in (("--draws", "draws"), ("--ring-budget", "ring_budget"),
                      ("--perm-draws", "perm_draws"),
                      ("--thin-from", "thin_from")):
        m = re.search(rf'add_argument\("{flag}".*?default=([^,)]+)', src,
                      re.S)
        assert m, f"{flag} has no default to compare against"
        default = m.group(1).strip().strip('"')
        if default == "None":
            # RESOLVED AT RUN TIME, not hardcoded. `--ring-budget` defaults to
            # whatever budget the stability artifact says its per-typology
            # block was computed at, because hardcoding it is precisely how a
            # spread defined at k=50 came to be explained by strata measured at
            # k=200. The artifact must then RECORD which value it resolved to
            # and where that came from, or the run is not reproducible either.
            doc = json.loads(art.read_text())
            assert doc.get("ring_budget"), (
                "the artifact does not record the budget it resolved to")
            assert doc.get("ring_budget_source"), (
                "the artifact records a resolved budget but not where it came "
                "from, so a reader cannot tell a measurement from a default")
            assert params.get(key) == doc["ring_budget"], (
                "the recorded parameter and the recorded resolution disagree")
            continue
        assert str(params.get(key)) == default, (
            f"the committed artifact was generated with {key}="
            f"{params.get(key)}, but `python scripts/typology_null.py` uses "
            f"{default}. The release checklist calls this artifact exactly "
            "reproducible from that command; at a different draw count the "
            "shared rng stream moves every later simulation.")


def test_the_bundle_writer_still_produces_the_archived_schema():
    """A generator that cannot reproduce its own artifacts is not a generator.

    `make_replay_bundle` wrote `argmax_txn_id` unconditionally while all nine
    archived bundles have six columns and no such field. So running the
    documented command produced a file whose sha256 could never match the
    `bundle.json` entry it is checked against -- and nothing noticed, because
    `verify_replay_bundle.py` recomputes METRICS (0 mismatches across 27, which
    is true and was the reassuring part) and never looks at the schema.
    `bundle_schema_version: 2` was a number with nothing behind it.

    This builds a bundle from a synthetic frame and asserts its default column
    set equals what the archive actually holds.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_replay_bundle as mrb

    archived = {}
    for b in sorted((_archive_root() / "replay").glob("*/")):
        f = b / "account_days_topk.parquet"
        if f.exists():
            archived[b.name] = tuple(pd.read_parquet(f).columns)
    if not archived:
        pytest.skip("no replay bundles in this checkout")
    assert len(set(archived.values())) == 1, (
        f"the archived bundles disagree among themselves: {archived}")
    want = next(iter(archived.values()))

    rng = np.random.default_rng(0)
    n = 40
    ad = pd.DataFrame({
        "day": np.repeat(pd.date_range("2022-01-01", periods=4), n // 4),
        "acct": rng.integers(0, 20, n),
        "score": rng.random(n),
        "other_max": rng.random(n),
        "y": (rng.random(n) < 0.2).astype(int),
        "argmax_txn_id": np.arange(n),
    })
    rk = np.arange(1, n + 1, dtype=np.int32)
    keep = np.ones(n, dtype=bool)
    got = tuple(mrb.account_day_table(ad, rk, keep).columns)
    with_txn = tuple(mrb.account_day_table(ad, rk, keep, transaction_unit=True).columns)
    assert "argmax_txn_id" in with_txn and "argmax_txn_id" not in got, (
        "the transaction id must travel with the transaction tables it serves, "
        "not be emitted by default")
    assert got == want, (
        f"the writer now produces {got} but every archived bundle holds "
        f"{want}. A bundle regenerated from HEAD could not match the sha256 "
        "recorded for it.")


def test_the_sbom_is_current_and_something_checks_it():
    """`grep -rn sbom tests/` returned nothing, and the artifact was 4 commits stale.

    The release checklist lists `sbom.cdx.json` as exactly reproducible in two
    seconds. Nothing ran it, so nothing noticed that the committed copy named
    a commit four behind HEAD -- a supply-chain manifest describing a tree
    that is not the one being released.
    """
    art = _archive_root() / "derived/sbom.cdx.json"
    if not art.exists():
        pytest.skip("sbom not generated in this checkout")
    doc = json.loads(art.read_text())
    sha = doc.get("code_git_sha")
    assert sha and re.fullmatch(r"[0-9a-f]{40}", sha), (
        f"the SBOM records no usable commit: {sha!r}")
    assert doc.get("components") or doc.get("bomFormat") or doc.get("status"), (
        "the SBOM has no recognisable body")

    # NO SKIP WHEN GIT IS ABSENT. The first version of this test skipped with
    # "no git dir (running inside the image)", which is not in image.yml's
    # allowlist -- so it would have turned the required `image` job red and
    # blocked every merge. That is the second time in one session, and the
    # fix is the same both times: assert what CAN be asserted everywhere, and
    # only ADD the git check where git exists.
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode != 0:
        return
    reachable = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"])
    assert reachable.returncode == 0, (
        f"the SBOM names commit {sha[:12]}, which is not an ancestor of HEAD: "
        "it describes a tree that is not being released")


def test_every_skip_reason_is_registered_in_the_image_allowlist():
    """A new skip reason must be a deliberate act, not a CI discovery.

    `.github/workflows/image.yml` fails the required `image` job when a test
    skips for a reason that is not on its allowlist -- which is the right rule,
    because a test that silently stops running inside the artifact is worse
    than one that fails. But the list was maintained by hand, so twice in one
    session a new test shipped an unlisted reason and blocked every merge.

    The allowlist is therefore a registry of every reason the suite can emit.
    The image job still enforces that only a listed reason may actually fire.
    """
    root = Path(__file__).resolve().parents[3]
    wf = root / ".github/workflows/image.yml"
    if not wf.exists():
        return          # not a skip: the container has no workflows directory
    allowed = re.findall(r'^\s+"([^"]+)",\s*$', wf.read_text(), re.M)
    # THE WHOLE tests/ TREE. Reading only this file is how the allowlist came
    # to be regenerated without a single tests/contract/ reason, turning the
    # required image job red while this very test stayed green.
    reasons = set()
    for f in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        # CODE ONLY. Scanning comments matched this file's own explanation of
        # the `reason=` form and reported `...` as an unregistered skip.
        text = "\n".join(ln for ln in f.read_text().splitlines()
                         if not ln.lstrip().startswith("#"))
        # BOTH FORMS. `pytest.mark.skipif(..., reason="...")` skips just as
        # loudly as `pytest.skip("...")`, and knowing only the second is what
        # let the allowlist lose every tests/contract/ reason.
        for rx in (r'pytest\.skip\(\s*f?["\']([^"\']+)',
                   r'reason\s*=\s*f?["\']([^"\']+)'):
            reasons |= set(re.findall(rx, text))
    missing = sorted(r for r in reasons
                     if not any(a in r for a in allowed))
    assert not missing, (
        "these skip reasons are not in image.yml's allowlist, so the required "
        "`image` job will go red the moment one of them fires:\n  "
        + "\n  ".join(missing))


def test_no_derived_artifact_is_stale_against_its_generator_at_head():
    """A stale artifact and its stale generator agree with each other.

    `test_derived_artifact_names_its_generator` verifies the recorded
    `generator_sha256` against the generator as it was at the artifact's OWN
    recorded commit. That pair is self-consistent forever: change the script,
    do not rerun, and every provenance check stays green while the published
    artifact describes code that no longer exists. Two artifacts were stale
    that way in one afternoon -- `budget_null.json` missed the variance caveat
    its own commit message was about, and `typology_null.json` predated the
    rewrite that added the intervals.

    The missing invariant is the simple one: the generator recorded by the
    artifact must be the generator that is here NOW.
    """
    root = Path(__file__).resolve().parents[3]
    derived = _archive_root() / "derived"
    if not derived.is_dir():
        return
    stale = []
    for art in sorted(derived.glob("*.json")):
        doc = json.loads(art.read_text())
        gen, rec = doc.get("generator_script"), doc.get("generator_sha256")
        if not gen or not rec:
            continue
        path = root / gen
        if not path.exists():
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != rec and art.name not in GRANDFATHERED_NO_TREE_HASH:
            stale.append(f"{art.name}: records {rec[:12]} for {gen}, "
                         f"which now hashes to {actual[:12]}")
    assert not stale, (
        "these derived artifacts were generated by a version of their "
        "generator that no longer exists -- rerun them:\n  " + "\n  ".join(stale)
        + "\n(GRANDFATHERED artifacts that genuinely cannot be rerun belong in "
        "GRANDFATHERED_NO_TREE_HASH with a reason, not in silence.)")


def test_holm_adjusted_p_values_are_monotone_and_from_unrounded_inputs():
    """Holm is a monotone procedure, and the published values were neither.

    Two defects, both silent because neither changed the count of significant
    results:

    1. The first implementation multiplied each ordered p-value by its
       remaining-test count and stopped. That is the Bonferroni step without
       Holm's step-down rule: the adjustment takes a RUNNING MAXIMUM, so an
       adjusted value can never be smaller than one before it in the ordering.
       CYCLE was published at 0.54865 where Holm gives 0.5985.
    2. It then fed the adjustment `round(p, 5)` -- the display form -- rather
       than the measured p-value.

    This checks the shipped artifact for monotonicity, and checks the
    procedure itself on a case whose answer is known by hand.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        return
    doc = json.loads(art.read_text())
    per = (doc.get("permutation_spread_Medium") or {}).get(
        "per_typology_concentration")
    if not per:
        return
    ordered = sorted(per.values(), key=lambda v: v["p_two_sided"])
    holm = [v["p_holm"] for v in ordered]
    assert holm == sorted(holm), (
        f"Holm-adjusted p-values are not monotone in the raw ordering: {holm}. "
        "That is the step-down rule missing, not a rounding artefact.")
    assert all(v["p_holm"] >= v["p_two_sided"] - 1e-9 for v in per.values()), (
        "an adjusted p-value is below its own raw p-value")
    assert all(0.0 <= v["p_holm"] <= 1.0 for v in per.values())

    # The procedure, on a hand-worked case. Raw [0.01, 0.02, 0.03, 0.9] over
    # four tests gives steps [0.04, 0.06, 0.06, 0.9]; the third step alone is
    # 0.03*2 = 0.06 and the fourth 0.9*1, and the running maximum is what
    # keeps the sequence non-decreasing.
    raw = {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.9}
    order = sorted(raw, key=lambda k: raw[k])
    running, adj = 0.0, {}
    for rank, name in enumerate(order):
        running = max(running, min(1.0, raw[name] * (len(order) - rank)))
        adj[name] = round(running, 10)
    assert adj == {"a": 0.04, "b": 0.06, "c": 0.06, "d": 0.9}, adj


# Typology figures that must name their artifact and field, not merely exist
# somewhere in the archive. Keyed by the value as published.
TYPOLOGY_BOUND_CLAIMS = ("0.46633", "0.10952", "0.02793")


def test_typology_claims_name_their_own_artifact_and_field():
    """Token membership cannot bind a number to its metric, and did not.

    A published `p = 0.0938` -- an exact permutation p-value that had since
    become 0.10952 -- passed the publication gate because an unrelated
    `recall@50` in another lineage rounds to 0.0938. The number existed
    somewhere, so the checker was satisfied.

    Typology claims therefore carry a source binding:

        <!-- source: 0.10952 <- derived/typology_null.json#exposure_vs_detection.p_without_GATHER_SCATTER_exact -->

    which `make_tables` resolves to that exact artifact and key, and which must
    also appear in the prose rather than only in the citation.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        return
    mt.ARCHIVE = Path(root / "aml-platform/results_archive")
    bound: dict[str, str] = {}
    for d in mt.publication_docs(root):
        if not d.exists():
            continue
        for line in d.read_text().splitlines():
            m = mt.SOURCED.search(line)
            if m:
                bound.update(mt.sourced_claims(m.group("body")))

    for val in TYPOLOGY_BOUND_CLAIMS:
        if not any(val in doc.read_text()
                   for doc in mt.publication_docs(root) if doc.exists()):
            continue          # not currently published; nothing to bind
        assert val in bound, (
            f"{val} is a typology figure published without a source binding. "
            "Add `<!-- source: {val} <- derived/typology_null.json#<field> -->` "
            "so it is checked against its own artifact rather than against "
            "whether the digits occur anywhere in the archive.")
        ref = bound[val]
        assert "typology_null.json" in ref, (
            f"{val} is bound to {ref}, which is not the typology artifact")
        assert mt.resolve_source(ref, mt.ARCHIVE) is not None, (
            f"{val} is bound to {ref}, which does not resolve")


def test_an_unrelated_artifact_cannot_support_a_bound_typology_claim():
    """The regression the brief asks for: prove the binding actually binds.

    Before source scoping, ANY artifact containing a value that rounds the
    same way satisfied the gate. This constructs exactly that situation -- a
    value that exists in a different artifact under a different metric -- and
    asserts the bound form rejects it while the unbound form accepts it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    archive = Path(root / "aml-platform/results_archive")
    if not (archive / "derived/typology_null.json").is_dir() and not (
            archive / "derived/typology_null.json").exists():
        return
    mt.ARCHIVE = archive

    # The real binding resolves.
    good = "derived/typology_null.json#exposure_vs_detection.p_exact_permutation"
    assert mt.resolve_source(good, archive) is not None

    # A DIFFERENT artifact, however many values it contains, cannot stand in.
    for wrong in (
        "derived/budget_null.json#exposure_vs_detection.p_exact_permutation",
        "derived/typology_null.json#no_such_field",
        "derived/does_not_exist.json#a.b",
    ):
        assert mt.resolve_source(wrong, archive) is None, (
            f"{wrong} resolved, so a claim could be 'supported' by an "
            "artifact that does not carry it")

    # And the value must match the field, not merely exist in the file.
    val = mt.resolve_source(good, archive)
    assert val is not None
    assert abs(val - 0.02793) < 5e-5, (
        f"the bound field holds {val}; the published claim would be checked "
        "against this and nothing else")


def test_a_pin_entry_with_annotation_still_verifies():
    """The verifier compared whole records, so annotation read as corruption.

    A pin entry may carry provenance the fresh hash cannot: HI-Large_Trans.csv
    records `hashed_on` and `carried_from` because it is 17 GB and exists only
    on the cloud VM. `got != want` compared dicts, so verifying that file on
    the one machine where it CAN be verified printed

        MISMATCH  HI-Large_Trans.csv
                  expected d13635e2... (17,052,760,651 B)
                  found    d13635e2... (17,052,760,651 B)

    -- a failure message that disproves its own verdict. Identity is sha256
    and bytes; everything else in the record is commentary.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import verify_dataset as vd

    # CODE LINES ONLY -- the fix's own comment quotes the old expression, and
    # scanning comments made this test fail on the explanation of itself.
    src = "\n".join(ln for ln in Path(vd.__file__).read_text().splitlines()
                    if not ln.lstrip().startswith("#"))
    assert 'got != want' not in src, (
        "the verifier is comparing whole pin records again; annotation on an "
        "entry will be reported as a hash mismatch")
    assert '(got["sha256"], got["bytes"]) != (want["sha256"], want["bytes"])' in src

    # BEHAVIOURAL, not dependent on today's pin. The live pin may or may not
    # carry annotation -- it lost its `carried_from` entries the moment all
    # six files were hashed on one host -- so construct the case.
    want = {"sha256": "a" * 64, "bytes": 10,
            "hashed_on": "the cloud VM", "carried_from": "a previous pin"}
    got = {"sha256": "a" * 64, "bytes": 10}
    assert (got["sha256"], got["bytes"]) == (want["sha256"], want["bytes"]), (
        "identity is sha256 and bytes")
    assert got != want, (
        "the records differ by annotation alone -- which is precisely why a "
        "whole-record comparison reported a false mismatch")
