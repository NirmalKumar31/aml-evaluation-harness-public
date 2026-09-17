"""
train_model: fit on the train side of the split, score the test side.

Two models, deliberately boring -- the model is not this project's contribution.

  baseline  logistic regression. Establishes the floor. Anything that cannot
            beat it is broken, and knowing the floor is what makes the GBDT
            number mean something.
  gbdt      HistGradientBoostingClassifier. Best accuracy-per-effort on tabular
            data, handles NaN natively (our history features are legitimately
            null for an account's first ever transaction), CPU-only, and the
            artifact is small enough for Lambda inference.

NO SMOTE / synthetic oversampling. It fabricates transactions that belong to no
ring, which corrupts every ring-level metric. We use class weighting instead.
"""
import hashlib
import os
import sys

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from aml import io
from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci, evaluate
from aml.features.build import FEATURES
from aml.manifest import Run, cached_or_none
from aml.models import config as model_config
from aml.models.config import CHECKPOINT_EVERY, GBDT_ITERS

MODELS = {
    "baseline": lambda seed: make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)),
    # Hyperparameters live in aml/models/config.py -- one definition, read by
    # this module, the leak sweep and the stability sweep. See that file for why
    # three hand-synced copies were a defect waiting to happen.
    "gbdt": lambda seed: model_config.gbdt(seed),
    # Same hyperparameters, different library. Exists to separate a library
    # ceiling from a data ceiling at HI-Large -- see models/config.py.
    "lgbm": lambda seed: model_config.lgbm(seed),
}

# The width to load the feature matrix at, per model. Not a tuning knob: it is
# the dtype each library will use internally regardless, and loading anything
# else means holding two copies.
#
#   gbdt      sklearn's X_DTYPE is float64 and it upcasts whatever it is given
#   lgbm      LightGBM consumes float32 directly and bins it to uint8
#   baseline  StandardScaler/LogisticRegression are float64 pipelines
#
# At HI-Large's 125M x 32 that choice is 33.5 GB against 16.7 GB, which is the
# difference between not fitting on this machine and fitting comfortably.
MODEL_DTYPE = {
    "baseline": np.float64,
    "gbdt": np.float64,
    "lgbm": np.float32,
}


def _fit_gbdt_checkpointed(Xtr, ytr, seed: int, ckpt, resume: bool):
    """Boosting is incremental, so a crash at round 280 of 300 need not throw
    away 280 rounds of work. warm_start lets us grow the same model in steps and
    save after each one. On the 182M-row cloud runs a lost run costs real money;
    locally it costs 25 minutes.

    `ckpt` MUST live under the stage's output path, not on node-local disk.
    On Azure ML the working directory is ephemeral and, with min_nodes = 0, the
    node is expected to disappear. A checkpoint on node disk therefore dies from
    node preemption, OOM kills and timeouts -- which is the entire set of
    failures checkpointing exists to survive. Uploading a ~1 MB model every 50
    rounds is cheap; that interval is why this is affordable.
    """
    start = 0
    if resume and io.exists(ckpt):
        clf = io.load_joblib(ckpt)
        start = clf.n_iter_
        print(io.json_line({"event": "resumed_from_checkpoint", "iterations_done": start}))
        if start >= GBDT_ITERS:
            return clf
    else:
        # Same shipped hyperparameters, grown incrementally so each interval can
        # be checkpointed. max_iter is raised in the loop below.
        clf = model_config.gbdt(seed, max_iter=CHECKPOINT_EVERY, warm_start=True)

    for target in range(max(start + CHECKPOINT_EVERY, CHECKPOINT_EVERY),
                        GBDT_ITERS + 1, CHECKPOINT_EVERY):
        clf.set_params(max_iter=target)
        clf.fit(Xtr, ytr)
        io.dump_joblib(clf, ckpt)
        print(io.json_line({"event": "checkpoint", "iterations": int(clf.n_iter_),
                          "of": GBDT_ITERS}), flush=True)
    return clf


# One million rows x 32 float32 columns is ~128 MB per batch: small beside the
# destination array, large enough that per-batch overhead does not matter.
_BATCH_ROWS = 1_000_000


def _fetch_matrix(con, sql: str, n_rows: int, cols: list[str], label: str | None = None,
                  dtype=np.float64):
    """Stream a query into a preallocated float32 array.

    WHY NOT `.df()` THEN `.to_numpy()`

        That is two full copies of the feature matrix. At HI-Medium it is
        wasteful; at HI-Large it is fatal. Measured from the real split ratios
        (111M train rows, 71M test, 32 features, float32):

            train DataFrame   14.2 GB
            + numpy copy      14.2 GB
            test DataFrame     9.1 GB
            + numpy copy       9.1 GB
                             --------
            peak              ~47 GB   against a 31 GB machine

        (Those figures are float32. See the dtype note below: the matrix is
        actually allocated float64, because sklearn upcasts regardless and
        doing it here avoids holding both.)

        The VM cannot be made bigger: `az quota update` on a trial
        subscription returns ResourceNotAvailableForOffer, so 4 vCPU / 31 GB
        is a ceiling, not a setting.

        Streaming Arrow batches into one preallocated array makes the peak the
        array plus a single batch -- 14.2 GB rather than 28.4 GB -- and the
        caller can free it before loading the other split.

    The array is filled by column because that is how Arrow hands the data
    over; `zero_copy_only=False` is required since nullable columns arrive as
    Arrow arrays with a validity bitmap and NULL must become NaN, which is the
    same thing `.df()` did.

    WHY float64 AND NOT float32

        Because sklearn will convert to float64 anyway, and doing it here
        means it happens ONCE. HistGradientBoosting's X_DTYPE is np.float64
        (verified against sklearn 1.9.0, not read from a doc), so handing it a
        float32 array produces a second, doubled array inside `fit`:

            our float32 array       14.9 GB
            sklearn's float64 copy  29.8 GB
            both live during fit    44.7 GB   against 31 GB

        That is what killed the HI-Large fit: memory rose steadily to 15.8 GB
        as this array filled, then jumped past 31 GB within 16 seconds of the
        fit starting. Passing float64 up front removes the smaller array
        entirely and makes sklearn's conversion a no-op:

            direct float64 at 100%  33.5 GB   still too large
            direct float64 at  70%  23.5 GB   fits, with ~6 GB spare

        So float32 was not a saving. It was a hidden doubling.
    """
    X = np.empty((n_rows, len(cols)), dtype=dtype)
    # The label rides along in the same scan. Fetching it separately would mean
    # a second ORDER BY txn_id over 111M rows, and that sort is the expensive
    # part of the query, not the transfer.
    y = np.empty(n_rows, dtype=np.int8) if label else None
    i = 0
    # `to_arrow_reader`, not `fetch_record_batch`: the latter is deprecated in
    # DuckDB 1.5 and emits a warning on every call. Same streaming semantics --
    # this deliberately does NOT materialise the whole result, because the
    # HI-Large scan is 125M rows and the destination array is already
    # allocated. Kept behind a getattr so an older DuckDB still works.
    result = con.execute(sql)
    reader = (result.to_arrow_reader(_BATCH_ROWS)
              if hasattr(result, "to_arrow_reader")
              else result.fetch_record_batch(_BATCH_ROWS))
    for batch in reader:
        m = batch.num_rows
        for j, c in enumerate(cols):
            X[i:i + m, j] = batch.column(c).to_numpy(zero_copy_only=False)
        if label:
            y[i:i + m] = batch.column(label).to_numpy(zero_copy_only=False)
        i += m
    if i != n_rows:
        raise RuntimeError(f"expected {n_rows} rows, streamed {i}")
    return (X, y) if label else X



def _sample_clause(sample: float) -> str:
    """The --sample predicate. RING-AWARE, and that is the whole point.

    Thinning by hash(txn_id) -- the obvious implementation, and the one that was
    here -- selects TRANSACTIONS independently, which silently destroys the unit
    every ring-level metric is defined on:

      * a ring with m transactions keeps ~sample*m of them, so its account-day
        footprint shrinks and with it its number of chances at the daily top-k.
        Detection gets harder for a reason that is not the model.
      * a ring disappears entirely with probability (1-sample)^m -- 30% for a
        one-transaction ring at sample=0.7 -- while `test_rings.parquet`, which
        supplies ring_recall's denominator, was built on the UNSAMPLED data.
        Those rings become structurally guaranteed misses.
      * the per-day competitor pool thins too, which pushes the other way. The
        two biases are size-dependent and oppose each other, so the net
        direction cannot even be signed.

    Measured consequence of the old behaviour: --sample also thinned the TEST
    set, and recall_ceiling@50 moved 0.0517 -> 0.0713 from subsampling alone.
    Two runs at different --sample values were not comparable on any budget
    metric, and neither was comparable to a full-data run on another rung.

    So: keep or drop WHOLE rings by hash(ring_id), and thin unringed rows
    independently by hash(txn_id). Ring membership then matches the rows
    actually scored, and ring_recall's denominator is the rings present.

    Still deterministic -- hash, not random -- so a given --sample always picks
    the same rows and two sampled runs remain comparable to each other.
    """
    # Validate at the boundary. `type=float` accepted 0, -1, 2 and nan; 0
    # silently selected no rows, and >1 silently meant "everything", so a
    # typo produced a different experiment rather than an error.
    if sample != sample or not (0 < sample <= 1):      # NaN-safe
        raise ValueError(f"--sample must be in (0, 1], got {sample!r}")
    if sample >= 1.0:
        return ""
    k = int(sample * 10000)
    return (f" AND (CASE WHEN ring_id IS NULL"
            f" THEN hash(txn_id) % 10000 < {k}"
            f" ELSE hash(ring_id) % 10000 < {k} END)")


def _split_where(splits: str, sample: float):
    """The train/test predicates, so they cannot drift between loaders."""
    cfg = io.read_json(io.join(splits, "manifest.json"))["config"]
    cut = cfg["cut_time"]
    # THE PROTOCOL IS READ, NOT ASSUMED.
    #
    # This predicate is a SECOND derivation of the test set: build-splits
    # materialises `splits/test`, and this rebuilds it from the cut time and
    # the rings table. The loaders never read the materialised directory.
    #
    # While there was one protocol the two agreed, so the duplication was
    # invisible. Adding `--protocol naive` made it visible immediately: the
    # naive split wrote 2,794,163 test rows and the model was scored on the
    # 2,793,197 the ring filter below reconstructed, so the flag changed the
    # files on disk and nothing else. The preregistration for that experiment
    # names this exact hazard -- "two implementations would be a second chance
    # for the two-independent-derivations bug that txn_id just taught us
    # about" -- and the harness already had one.
    #
    # Old manifests predate the field; they were all ring-aware.
    protocol = cfg.get("protocol", "ring-aware")
    samp = _sample_clause(sample)
    # --sample THINS TRAINING ONLY. The test set is never subsampled.
    #
    # It used to apply to both, and that alone invalidated the first HI-Large
    # comparison. Every budget metric ranks account-days WITHIN A DAY against a
    # competitor pool, so thinning the test side changes the numbers
    # mechanically and in a direction that cannot be signed:
    #
    #   * recall_ceiling@50 moved 0.0517 -> 0.0713 on the same rung at the same
    #     k, purely from subsampling. Two runs at different --sample values were
    #     not comparable on ANY budget metric, and neither was comparable to a
    #     full-data run on another rung.
    #   * a thinner competitor pool makes surviving positives rank higher
    #     (recall up), while a member account losing transactions lowers its
    #     account-day max (recall down). Both scale with sample AND with ring
    #     size, so they do not cancel and their net sign is unknown.
    #
    # The purpose of --sample is a fast development loop and a way to fit a
    # too-large TRAINING matrix. Neither needs a smaller test set, and a
    # smaller test set destroys the only thing the run is for.
    train = f"WHERE event_time < TIMESTAMP '{cut}'{samp}"
    ring_filter = ("" if protocol == "naive" else
                   f" AND (ring_id IS NULL OR ring_id IN "
                   f"(SELECT ring_id FROM '{splits}/test_rings.parquet'))")
    test = f"WHERE event_time >= TIMESTAMP '{cut}'{ring_filter}"
    return train, test


def assert_test_predicate_matches_materialised(con, splits: str, where: str) -> int:
    """The reconstructed test set must be the one build-splits actually wrote.

    Cheap -- Parquet row counts come from file metadata, not from reading the
    data -- and it is the check that would have caught the duplication above on
    the day it was introduced rather than on the day an experiment needed the
    second protocol. Two derivations of one fact are tolerable only when
    something compares them.
    """
    n_pred = con.execute(f"SELECT count(*) FROM F {where}").fetchone()[0]
    n_mat = con.execute(
        f"SELECT count(*) FROM read_parquet({io.parquet_arg(splits + '/test')})"
    ).fetchone()[0]
    if n_pred != n_mat:
        raise ValueError(
            f"the test predicate selects {n_pred:,} rows but build-splits wrote "
            f"{n_mat:,} to {splits}/test. The loader and the split disagree "
            f"about what the test set is.")
    return n_pred


def _duckdb_budget(n_rows: int, n_cols: int, reserve_gb: float = 4.0) -> str:
    """How much memory DuckDB may use, given the array we are about to hold.

    THE BUG THIS FIXES

        DuckDB's default memory_limit is 80% of SYSTEM RAM. That is a sensible
        default for a process whose only large allocation is DuckDB -- and
        wrong here, because _fetch_matrix preallocates the feature matrix in
        the same process. The two budgets do not know about each other:

            numpy train array   14.9 GB   (125.0M rows x 32 x float32)
            DuckDB default      25.0 GB   (80% of 31 GB)
                               --------
                                39.9 GB   against 31 GB

        The OOM reaper killed the container 61 seconds in, exit 137, before a
        single tree was fitted. Nothing in the logs said "memory" -- an exit
        code and a dead container is all you get, which is why the resource
        sampler that caught this exists.

        It cannot be fixed by making DuckDB's default smarter: only the caller
        knows that a 14.9 GB array is coming.

    So subtract the array from physical RAM, keep a reserve for the model, the
    interpreter and the OS, and give DuckDB the rest. With a temp_directory set
    DuckDB spills rather than failing when that is not enough, which is the
    behaviour we want -- slower, not dead.
    """
    try:
        total_gb = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / 2 ** 30
    except (ValueError, AttributeError, OSError):   # pragma: no cover - non-POSIX
        return "4GB"
    array_gb = n_rows * n_cols * 4 / 2 ** 30
    return f"{max(1.0, total_gb - array_gb - reserve_gb):.1f}GB"


def _connect(features: str, splits: str, memory_limit=None, temp_directory=None):
    con = io.duckdb_connect((features, splits), memory_limit=memory_limit,
                            temp_directory=temp_directory)
    con.execute(f"CREATE VIEW F AS SELECT * FROM read_parquet({io.parquet_arg(features)})")
    return con


def load_train_xy(features: str, splits: str, sample: float = 1.0,
                  memory_limit: str | None = None, temp_directory: str | None = None,
                  dtype=np.float64, ordered: bool = True):
    """Train features and labels as arrays, never as a DataFrame.

    Same rows, same order and same values as load_split()'s train half -- it is
    the same SQL -- but the peak is one array instead of a DataFrame plus a
    copy of it. See _fetch_matrix for why that matters at HI-Large.

    `ordered=False` is for measuring the cost of the sort, and for the test that
    proves the sort is load-bearing. It must not be used to produce a published
    result.
    """
    features, splits = str(features), str(splits)
    where, _ = _split_where(splits, sample)
    con = _connect(features, splits, temp_directory=temp_directory)
    n = con.execute(f"SELECT count(*) FROM F {where}").fetchone()[0]
    # Set AFTER counting, because the budget depends on how many rows the
    # array will hold, and that is what the count just established.
    con.execute(f"SET memory_limit='{memory_limit or _duckdb_budget(n, len(FEATURES))}'")
    feat_sql = ", ".join(f"CAST({f} AS FLOAT) AS {f}" for f in FEATURES)
    # ORDER BY txn_id. THIS WAS REMOVED ONCE AND THE REMOVAL WAS WRONG.
    #
    # The sort is expensive: DuckDB materialises the sorted rows to emit them
    # in order, and at HI-Large it spilled and then drained back into memory
    # while the destination array was also being filled --
    #
    #     mem 10.2 GB  spill 2.3 GB
    #     mem 12.7 GB  spill 7.7 GB   <- sort spilled
    #     mem 17.1 GB  spill 7.1 GB   <- draining back in
    #     mem 21.4 GB  spill 4.5 GB
    #     killed
    #
    # -- so it was dropped, with a comment asserting that dropping it was safe
    # "because HistGradientBoostingClassifier is row-order-independent...
    # Measured rather than assumed -- fitting on X and on a row-permuted X
    # gives BITWISE identical predict_proba output."
    #
    # THAT MEASUREMENT WAS TAKEN AT 20,000 ROWS AND DOES NOT HOLD AT 200,000+.
    #
    # Both supported histogram learners build their bin thresholds from a
    # SUBSAMPLE once the data exceeds 200,000 rows -- sklearn's `_BinMapper`
    # (`subsample=200_000`, not exposed on the estimator) and LightGBM's
    # `bin_construct_sample_cnt` (default 200,000). The seed fixes which
    # POSITIONS are sampled, not which observations occupy them. Change the row
    # order and different observations define the bins. Measured at 210,001
    # rows on the pinned environment:
    #
    #     sklearn   bin thresholds differ by up to 2.3e-3; predictions by 0.063
    #     lightgbm  every one of 10,000 predictions changed; max delta 0.064
    #     logistic  differs by 3.5e-17 -- float summation order, not a model
    #
    # Every published rung is far above 200,000 rows, so the regime that was
    # tested is not the regime that ran. The sort is load-bearing and is back.
    # `train_matrix_sha256` in the manifest makes any future drift detectable
    # rather than silent.
    order = " ORDER BY txn_id" if ordered else ""
    try:
        return _fetch_matrix(
            con,
            # load_test sorts for a second, independent reason: its features
            # and its metadata come from two separate queries and have to
            # correspond row for row.
            f"SELECT {feat_sql}, is_laundering FROM F {where}{order}",
            n, FEATURES, label="is_laundering", dtype=dtype)
    finally:
        # CLOSE IT. DuckDB holds its buffer pool for the life of the
        # connection, and the caller is about to fit a model -- during which
        # sklearn allocates a binned uint8 copy of the matrix. All three were
        # live at once:
        #
        #     X float32               14.9 GB
        #     sklearn binned uint8     3.7 GB
        #     DuckDB buffer pool      12.1 GB   (nobody had closed it)
        #                            --------
        #                             30.7 GB   against 31 GB
        #
        # The container was OOM-killed twice before this line existed: at 61s
        # with DuckDB's default budget, then at 2m09s with the budget reduced
        # to 12.1 GB. Shrinking the budget delayed the failure without curing
        # it, because the problem was the buffer pool's LIFETIME, not its size.
        con.close()


def _predictions_digest(txn_id, score) -> str:
    """The digest of what is actually written to `<model>_test_scores.parquet`.

    Ordered ids, the scores at their true dtype, and the dtype itself -- so two
    runs agreeing here agree on the bytes a reader can download, not on a
    rounding of them. Including `txn_id` matters: the same score multiset
    attached to different transactions is a different prediction, and a digest
    over scores alone cannot tell those apart.
    """
    ids = np.ascontiguousarray(txn_id)
    sc = np.ascontiguousarray(score)
    h = hashlib.sha256()
    h.update(f"{ids.dtype.str}|{sc.dtype.str}|{ids.size}|".encode())
    h.update(memoryview(ids))
    h.update(memoryview(sc))
    return h.hexdigest()


def load_test(features: str, splits: str, sample: float = 1.0,
              memory_limit: str | None = None, temp_directory: str | None = None,
              dtype=np.float64):
    """Test features as an array, plus the columns evaluation needs.

    The metadata is deliberately NOT the feature columns: evaluation needs
    event_date, is_laundering, ring_id, typology and the two account ids, and
    those are a few GB rather than the 9 GB the features would add again.

    Account ids come back as dense integer codes, not strings. They are only
    ever GROUP BY keys in to_account_days -- never printed, never joined to
    anything outside this frame -- and 71M rows of Python strings across two
    columns costs more than the feature matrix itself.

    The codes come from a dimension table rather than a hash. hash() was tried
    first and the collision check caught it: at HI-Large it produced TWO
    collisions, which would have merged two pairs of distinct accounts into
    single account-days and quietly corrupted ring_recall. Birthday arithmetic
    says 64 bits should collide at ~1e-5 for this many accounts, so DuckDB's
    hash() is evidently not uniform over 64 bits -- the guard was right and the
    reasoning behind the hash was wrong.

    A DISTINCT over both id columns with row_number() is exact by construction,
    costs one pass and a small dimension table, and cannot collide at any scale.
    """
    features, splits = str(features), str(splits)
    _, where = _split_where(splits, sample)
    con = _connect(features, splits, temp_directory=temp_directory)
    # The predicate and the materialised split must agree before either is used.
    n = assert_test_predicate_matches_materialised(con, splits, where)
    con.execute(f"SET memory_limit='{memory_limit or _duckdb_budget(n, len(FEATURES))}'")

    # Dense codes, built once, exact by construction -- AND ORDERED.
    #
    # `row_number() OVER ()` with no ORDER BY takes whatever order the scan
    # happens to produce, so the codes were non-deterministic across runs,
    # DuckDB versions and thread counts. The metrics do not care (they are
    # invariant to relabelling accounts), but the replay bundles ship `acct`
    # and their `sha256` fields then meant only "this file is unaltered", never
    # "this file agrees with a fresh run from the dataset". A reader could not
    # verify the bundles came from AMLworld at all.
    #
    # This is the same defect the training load carried until `ORDER BY txn_id`
    # was restored; it survived here because nothing downstream of it was
    # compared across runs.
    con.execute(f"""
        CREATE TEMP TABLE acct AS
        SELECT id, row_number() OVER (ORDER BY id) AS code FROM (
            SELECT DISTINCT sender_id AS id FROM F {where}
            UNION
            SELECT DISTINCT receiver_id FROM F {where}
        )
    """)
    n_acct = con.execute("SELECT count(*) FROM acct").fetchone()[0]

    feat_sql = ", ".join(f"CAST({f} AS FLOAT) AS {f}" for f in FEATURES)
    X = _fetch_matrix(con, f"SELECT {feat_sql} FROM F {where} ORDER BY txn_id",
                      n, FEATURES, dtype=dtype)
    meta = con.execute(
        f"SELECT F.txn_id, F.is_laundering, F.ring_id, F.typology, F.event_date, "
        f"       s.code AS sender_id, r.code AS receiver_id "
        f"FROM F JOIN acct s ON F.sender_id = s.id "
        f"       JOIN acct r ON F.receiver_id = r.id "
        f"{where.replace('WHERE', 'WHERE', 1)} ORDER BY F.txn_id").df()
    if len(meta) != n:
        raise RuntimeError(
            f"account join changed the row count: {n} -> {len(meta)}. Every "
            f"transaction must match exactly one sender and one receiver code.")
    print(io.json_line({"event": "account_codes", "distinct_accounts": n_acct}))
    con.close()          # same reason as load_train_xy: scoring comes next
    return X, meta


def load_split(features: str, splits: str, sample: float = 1.0
               ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild train/test membership from the split's own outputs.

    Features are computed over the FULL timeline on purpose: at inference time
    you genuinely do know an account's past, so using pre-cut transactions to
    build a test row's history is correct, not leakage. What must never cross
    the line is LABELS, and those are filtered here.

    ORDER BY txn_id IS NOT OPTIONAL. DuckDB parallelises the scan and the
    ring_id subquery, so without it the same query returns the same 12,402,530
    rows in a DIFFERENT ORDER on every run. Scores saved positionally against
    one ordering then re-read against another are silently matched to the wrong
    transactions -- which looks like a model that scores at chance (ROC-AUC
    0.49) rather than like a bug. Scores are also persisted WITH their txn_id
    so evaluation joins rather than trusting position.
    """
    con = io.duckdb_connect((features, splits))
    con.execute(f"CREATE VIEW F AS SELECT * FROM read_parquet({io.parquet_arg(features)})")

    # Load only what each side needs. Training needs features + label; the
    # string account ids are ~20M x 2 Python objects and are only used to build
    # account-days at eval time. Features are cast to FLOAT (32-bit) in SQL:
    # 19.5M x 32 as float64 is ~5 GB before sklearn copies anything.
    feat_sql = ", ".join(f"CAST({f} AS FLOAT) AS {f}" for f in FEATURES)

    # --sample gives a fast dev loop: same code path, same assertions, a
    # fraction of the rows. Selection is by hash(txn_id), NOT random(), so the
    # same sample fraction always picks the same rows -- a sampled run stays
    # reproducible and two sampled runs are comparable.
    # TRAINING ONLY, same as _split_where. This appended the clause to BOTH
    # predicates, so model-stability and leak-sweep silently evaluated on a
    # subsampled test set whenever --sample < 1 -- changing the competitor pool
    # and every budget metric. It is the defect the retraction was written
    # about, still live in the loader those two stages use.
    # ONE DERIVATION OF THE SPLIT, shared with the primary loaders.
    #
    # This function used to build its own predicates: the training WHERE by
    # hand, and the test WHERE with the ring filter written out a second time.
    # That is a third copy of "what the split is", and the audit had already
    # caught a second copy silently disagreeing with the materialised split.
    # `_split_where` is now the only place either predicate exists, so a
    # protocol it does not know about cannot quietly become ring-aware here.
    train_where, test_where = _split_where(splits, sample)

    # event_date on BOTH sides. The test half always had it (evaluate needs
    # it); the train half did not, and the leak sweep's placebo needs to
    # permute within (split side, day) -- which it cannot do for rows whose day
    # it cannot see.
    train = con.execute(
        f"SELECT txn_id, {feat_sql}, is_laundering, event_date "
        f"FROM F {train_where} ORDER BY txn_id").df()
    test = con.execute(
        f"SELECT txn_id, {feat_sql}, is_laundering, ring_id, typology, "
        f"       event_date, sender_id, receiver_id "
        f"FROM F {test_where} ORDER BY txn_id").df()
    return train, test


def train(features: str, splits: str, dest: str, model: str = "gbdt",
          seed: int = 0, manifest_dir: str | None = None, bootstrap: int = 500,
          sample: float = 1.0, force: bool = False, resume: bool = True,
          memory_limit: str | None = None, temp_directory: str | None = None):
    features, splits, dest = str(features), str(splits), str(dest)
    # hyperparameters and bootstrap are in the key ON PURPOSE, and were the
    # bug. Before this, `cfg` named the model only as "gbdt", and code_hash()
    # was called with no modules -- the sha256 of nothing. So editing
    # models/config.py and re-running printed `cached_skip` and returned the
    # PREVIOUS model's metrics, under a manifest that said status: ok. A
    # retune reported numbers from a model that no longer existed.
    cfg = {"features": features, "splits": splits, "model": model, "seed": seed,
           "sample": sample, "feature_list": FEATURES, "n_features": len(FEATURES),
           "bootstrap": bootstrap,
           "model_params": (model_config.gbdt_params(seed) if model == "gbdt"
                            else model_config.lgbm_params(seed) if model == "lgbm"
                            else None)}

    key, hit = cached_or_none(f"train_model[{model}]", cfg, [features, splits],
                              (manifest_dir or dest),
                              modules=(sys.modules[__name__], model_config),
                              force=force)
    if hit is not None:
        return hit

    with Run(f"train_model[{model}]", cfg, manifest_dir or dest, key=key) as run:
        # Loaded in two halves, and the train half is released before the
        # test half is read. Holding both plus their DataFrames peaks near
        # 47 GB at HI-Large against a 31 GB machine that cannot be made
        # bigger -- a trial subscription cannot raise its vCPU quota.
        dt = MODEL_DTYPE[model]
        Xtr, ytr = load_train_xy(features, splits, sample=sample,
                                 memory_limit=memory_limit,
                                 temp_directory=temp_directory, dtype=dt)

        if model == "gbdt":
            # The checkpoint filename carries the run_key. Without it, a rebuilt
            # feature table invalidates the stage CACHE but not the CHECKPOINT,
            # so training silently resumes a model fitted on the old features and
            # reports it as a fresh result -- observed on 2026-08-20, where a
            # rebuild logged resumed_from_checkpoint:300 with zero checkpoint
            # writes and the "new" metrics were the old model's. --force did not
            # help, because force only bypasses the cache.
            ckpt = io.join(dest, f"gbdt_seed{seed}.{key}.ckpt.joblib")
            clf = _fit_gbdt_checkpointed(Xtr, ytr, seed, ckpt, resume)
        else:
            clf = MODELS[model](seed)
            clf.fit(Xtr, ytr)

        # Free the training matrix before the test matrix is allocated. At
        # HI-Large that is 14.2 GB returned to the allocator, and it is the
        # difference between fitting inside 31 GB and being killed by the OOM
        # reaper after the fit has already succeeded.
        # Captured before the free: the manifest still reports them.
        n_train, n_train_pos = len(ytr), int(ytr.sum())
        # THE ROW ORDER, RECORDED.
        #
        # Both histogram learners build bin thresholds from a 200,000-row
        # subsample of POSITIONS, so a different row order is a different
        # model. The loader sorts by txn_id to make the order deterministic;
        # this hash is what proves the sort actually happened and that a rerun
        # saw the same rows in the same sequence. One pass over the array, no
        # copy -- memoryview, not tobytes, because tobytes would duplicate
        # 14.9 GB at HI-Large.
        #
        # If this value changes between two runs that claim to be the same
        # experiment, their predictions may legitimately differ and neither is
        # wrong. Without it, that difference is invisible.
        train_matrix_sha256 = hashlib.sha256(
            memoryview(np.ascontiguousarray(Xtr))).hexdigest()
        # THE MATRIX IS NOT THE WHOLE INPUT.
        #
        # An audit made the point that `train_matrix_sha256` identifies X and
        # nothing else: two runs could agree on it while disagreeing on the
        # labels, the dtype, or which column is which -- and a feature-order
        # change would move every prediction while leaving this hash alone,
        # because the bytes of the same values in a different column order
        # hash differently only if the order actually changed within a row,
        # which is precisely the case this does NOT distinguish from a genuine
        # data change. So record the rest of the alignment explicitly.
        train_labels_sha256 = hashlib.sha256(
            memoryview(np.ascontiguousarray(ytr))).hexdigest()
        train_schema_sha256 = hashlib.sha256(
            "|".join(FEATURES).encode() + f"|{Xtr.dtype.str}|{Xtr.shape[1]}"
            .encode()).hexdigest()
        train_matrix_dtype = Xtr.dtype.str      # includes byte order
        del Xtr, ytr
        Xte, te = load_test(features, splits, sample=sample,
                            memory_limit=memory_limit,
                            temp_directory=temp_directory, dtype=dt)
        score = clf.predict_proba(Xte)[:, 1]
        del Xte

        m = evaluate(te, score)
        m.update(bootstrap_ci(te, score, budget=50, n=bootstrap, seed=seed,
                          budgets=DEFAULT_BUDGETS))

        io.ensure_dir(dest)
        art = io.join(dest, f"{model}.joblib")
        io.dump_joblib(clf, art)
        # Persist scores WITH their transaction id. Position alone is not a
        # safe key across processes -- see the docstring in load_split().
        pd.DataFrame({"txn_id": te.txn_id.to_numpy(), "score": score}).to_parquet(
            io.join(dest, f"{model}_test_scores.parquet"), index=False)

        run.record(
            train_rows=n_train, train_positives=n_train_pos,
            test_rows=len(te), test_positives=int(te.is_laundering.sum()),
            model_artifact_sha256=io.sha256_file(art),
            train_labels_sha256=train_labels_sha256,
            train_schema_sha256=train_schema_sha256,
            train_matrix_dtype=train_matrix_dtype,
            train_matrix_sha256=train_matrix_sha256,
            train_rows_ordered_by="txn_id",
            # WHAT THE MODEL DOES, as opposed to what its file looks like.
            #
            # Running this pipeline on an Azure VM reproduced every metric
            # exactly -- average_precision, precision@50, ring_recall@200 and
            # even the 500-resample bootstrap interval, to full float
            # precision -- while model_artifact_sha256 DIFFERED:
            #
            #   laptop  arm64 macOS   084dae41d5f0f92a...
            #   cloud   amd64 Linux   c9c38059498b2b16...
            #
            # joblib embeds platform detail in the pickle, so the artifact
            # hash answers "were these bytes produced on the same machine?"
            # and not "does this model behave the same?". For a project whose
            # claim is reproducibility, the second question is the one that
            # matters, and nothing was recording it.
            #
            # TWO DIGESTS, BECAUSE THEY ANSWER DIFFERENT QUESTIONS, and for a
            # long time one of them answered neither.
            #
            # The comment here used to say the float32 cast was "the precision
            # the scores are stored and evaluated at". It is neither. The
            # Parquet field is `double`; `evaluate` receives the raw float64
            # array. So the recorded digest described a representation that is
            # not stored, not evaluated, and not comparable to the file -- and
            # README and LIMITATIONS called matching values "bitwise-identical
            # predictions". A digest of something that does not exist cannot
            # settle a question about something that does.
            #
            #   predictions_sha256            the EXACT stored payload: ordered
            #                                 txn_id, the float64 scores, and a
            #                                 dtype tag. Matches the Parquet.
            #   predictions_tolerance_sha256  the float32 quantisation, which
            #                                 is what is wanted for comparing
            #                                 two platforms: it ignores tails
            #                                 no metric can see. A TOLERANCE
            #                                 digest, and now named as one.
            predictions_sha256=_predictions_digest(te.txn_id.to_numpy(), score),
            predictions_tolerance_sha256=hashlib.sha256(
                np.asarray(score, dtype=np.float32).tobytes()).hexdigest(),
            predictions_dtype=str(np.asarray(score).dtype),
            model_artifact_mb=round(io.size(art) / 1e6, 2),
            sample_fraction=sample,
            **{k: v for k, v in m.items() if k != "per_typology"},
        )
        run.metrics["per_typology"] = m.get("per_typology")
        print(io.json_line({"event": "train_complete", "model": model,
                          **{k: v for k, v in run.metrics.items()
                             if k not in ("per_typology",)}}, default=str))
        return run.metrics
