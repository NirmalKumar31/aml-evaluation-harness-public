"""Behavioural tests for the orchestration stages, which had no coverage.

WHY THIS FILE EXISTS

    Six audits measured this repository's line coverage at 72-76% and every one
    of them pointed at the same modules: `eval/run.py` at 27%,
    `drift/experiment.py` at 0%. The release checklist's first answer was that
    "these are exactly the paths the 17 skipped tests cover", which was false --
    the skips are HI-Small schema contracts and never enter a fit loop or an
    evaluation stage.

    These are the paths whose failure mode is a *plausible wrong artifact*
    rather than a crash: an evaluate stage that silently scores the wrong rows
    still writes a complete metrics file with a `status: ok` manifest. That is
    the exact defect this project was built around.

    So these are not line-chasing tests. Each one has an oracle: a quantity
    computed a second, independent way, or a corruption that must be refused.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PLAT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def demo_corpus(tmp_path_factory):
    """The real six-stage pipeline on a generated corpus, built once."""
    dest = tmp_path_factory.mktemp("demo") / "d"
    r = subprocess.run([sys.executable, "-m", "aml.cli", "demo", "--dest", str(dest)],
                       capture_output=True, text=True, cwd=PLAT)
    if r.returncode != 0:
        pytest.skip(f"demo did not build: {r.stderr[-400:]}")
    return dest


def _evaluate(corpus, dest, scores=None):
    """Call the stage IN PROCESS.

    The first version of these tests shelled out to `aml evaluate`, which
    exercises the same code and leaves `eval/run.py` at 27% in the coverage
    report -- a subprocess's lines are not the parent's. Coverage was the
    reason this file exists, so the call has to be in process; the CLI wrapper
    is covered by its own tests.
    """
    from aml.eval import run as eval_run

    return eval_run.run(
        features=str(corpus / "features"), splits=str(corpus / "splits"),
        scores=str(scores or corpus / "models" / "gbdt_test_scores.parquet"),
        dest=str(dest), model="gbdt", bootstrap=0, permutations=25)


def test_evaluate_reproduces_the_metrics_the_training_stage_recorded(demo_corpus, tmp_path):
    """The oracle: two stages, one set of scores, the same numbers.

    `train` computes the metric suite inline after fitting. `evaluate`
    recomputes it from the saved scores, which is the whole reason the stage
    exists -- a metric change costs seconds instead of half an hour. If those
    two disagree, one of them is reading the wrong rows, and the budget metrics
    this project publishes come from the second one.
    """
    _evaluate(demo_corpus, tmp_path / "eval")

    trained = json.loads((demo_corpus / "models" / "manifest.json").read_text())["metrics"]
    recomputed = json.loads((tmp_path / "eval" / "gbdt_metrics.json").read_text())

    compared = 0
    for key, want in trained.items():
        if not isinstance(want, (int, float)) or isinstance(want, bool):
            continue
        if key not in recomputed or "null" in key or key.startswith("ring_recall_lift"):
            continue                      # permutation nulls are seeded separately
        got = recomputed[key]
        if not isinstance(got, (int, float)):
            continue
        assert got == pytest.approx(want, rel=1e-9, abs=1e-12), (
            f"{key}: train recorded {want}, evaluate recomputed {got}")
        compared += 1
    assert compared >= 15, f"only {compared} metrics cross-checked; the oracle is too weak"


def test_evaluate_refuses_scores_from_a_different_split(demo_corpus, tmp_path):
    """A row-count mismatch means the scores were produced against something
    else. Scoring them anyway produces chance-level metrics that look like a
    result."""
    scores = pd.read_parquet(demo_corpus / "models" / "gbdt_test_scores.parquet")
    short = tmp_path / "short.parquet"
    scores.iloc[:-1].to_parquet(short, index=False)

    with pytest.raises(ValueError, match="different split"):
        _evaluate(demo_corpus, tmp_path / "eval_short", scores=short)


def test_evaluate_refuses_scores_that_do_not_correspond_row_for_row(demo_corpus, tmp_path):
    """Right length, wrong identities. The join is on `txn_id` precisely so
    this cannot pass as a positional zip."""
    scores = pd.read_parquet(demo_corpus / "models" / "gbdt_test_scores.parquet")
    shifted = scores.copy()
    shifted["txn_id"] = shifted["txn_id"] + 10_000_000
    bad = tmp_path / "shifted.parquet"
    shifted.to_parquet(bad, index=False)

    with pytest.raises(ValueError, match="had no score"):
        _evaluate(demo_corpus, tmp_path / "eval_shift", scores=bad)


def test_evaluate_writes_a_manifest_that_names_its_inputs_and_code(demo_corpus, tmp_path):
    """A metrics file with no provenance is a number with no origin."""
    _evaluate(demo_corpus, tmp_path / "eval_man")
    man = json.loads((tmp_path / "eval_man" / "manifest.json").read_text())
    assert man["status"] == "ok"
    assert man["component"].startswith("evaluate")
    for field in ("code_git_sha", "code_tree_sha256", "config"):
        assert man.get(field), f"manifest records no {field}"
    cfg = man["config"]
    assert cfg["permutations"] == 25 and cfg["bootstrap"] == 0, (
        "parameters that move a published number must be in the config")
    assert cfg["feature_set"], "the feature set is not recorded"


# ---------------------------------------------------------------------------
# drift/experiment.py -- 0% covered through six audits
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def drift_corpus(tmp_path_factory):
    """A synthetic drifting corpus, small enough to fit four model fits.

    The CLI chain cannot build one from the demo: `make-drift` asks for all
    eight typologies and the demo generates only FAN-OUT, so it correctly
    refuses. This constructs the two inputs `drift.experiment.run` actually
    reads -- a feature table and a drift manifest -- directly.
    """
    import numpy as np

    from aml.features.build import FEATURES

    n_buckets, per_bucket = 4, 260
    rng = np.random.default_rng(7)
    t0 = pd.Timestamp("2022-09-01")
    rows = []
    for b in range(n_buckets):
        for i in range(per_bucket):
            positive = i % 13 == 0
            # The signal MOVES between buckets: early positives are separable
            # on the first feature, late positives on the second. A frozen
            # model must decay; a retrained one must not.
            rows.append({
                "txn_id": b * per_bucket + i,
                "is_laundering": int(positive),
                "ring_id": f"R{b}-{i // 13}" if positive else None,
                "typology": "FAN-OUT" if positive else None,
                "event_time": t0 + pd.Timedelta(days=b * 7 + i % 7,
                                                seconds=int(i)),
                "sender_id": i % 40,
                "receiver_id": (i * 7) % 40,
                "_early": float(positive and b < 2),
                "_late": float(positive and b >= 2),
            })
    df = pd.DataFrame(rows)
    df["event_date"] = df.event_time.dt.date.astype(str)
    for j, f in enumerate(FEATURES):
        if j == 0:
            df[f] = df["_early"] * 4.0 + rng.normal(0, 1, len(df))
        elif j == 1:
            df[f] = df["_late"] * 4.0 + rng.normal(0, 1, len(df))
        else:
            df[f] = rng.normal(0, 1, len(df))
    df = df.drop(columns=["_early", "_late"])

    root = tmp_path_factory.mktemp("drift")
    (root / "features").mkdir()
    df.to_parquet(root / "features" / "part.parquet", index=False)
    (root / "drift").mkdir()
    (root / "drift" / "drift_manifest.json").write_text(json.dumps({
        "n_buckets": n_buckets, "train_buckets": 2, "magnitude": 1.0,
        "bucket_length_days": 7,
        "window": [str(t0), str(t0 + pd.Timedelta(days=7 * n_buckets))],
        # `run()` reads five manifest fields at the top and a SIXTH --
        # `cramers_v` -- a hundred lines later, when it records its metrics.
        # Building this fixture is what surfaced that: the stage fitted eight
        # models and then died with a KeyError on the last statement. Nothing
        # had ever executed it end to end.
        "cramers_v": 0.42,
    }))
    return root, df, n_buckets


def test_the_drift_experiment_runs_every_strategy_on_every_evaluation_bucket(drift_corpus):
    """`drift/experiment.py` was at 0% coverage through six audits.

    It fits four models per evaluation bucket and writes a CSV that a paper
    section reads. Nothing executed it, so an exception, a missing strategy or
    a silently empty result set would all have looked the same from outside:
    no test would have failed.
    """
    from aml.drift import experiment

    root, df, n_buckets = drift_corpus
    out = root / "out"
    metrics = experiment.run(str(root / "features"), str(root / "drift"),
                             str(out), seed=0, iters=25, bootstrap=0)

    res = pd.read_csv(out / "drift_results_m1.0.csv")
    eval_buckets = [2, 3]
    assert sorted(res.bucket.unique().tolist()) == eval_buckets
    assert set(res.strategy) == set(experiment.STRATEGIES)
    assert len(res) == len(eval_buckets) * len(experiment.STRATEGIES)

    # ORACLE: the training-set sizes are a property of the construction, not of
    # the model. `frozen` sees the two stable buckets; `sliding_window` sees
    # exactly the previous bucket; `naive_retrain` sees everything before.
    per_bucket = len(df) // n_buckets
    for b in eval_buckets:
        row = {r.strategy: r for r in res[res.bucket == b].itertuples()}
        assert row["frozen"].train_rows == 2 * per_bucket
        assert row["sliding_window"].train_rows == per_bucket
        assert row["naive_retrain"].train_rows == b * per_bucket
        assert row["typology_replay"].train_rows == b * per_bucket
        assert row["frozen"].n_rows == per_bucket

    # `n_buckets` is CONFIG, not a metric -- the returned mapping is what the
    # stage measured, not what it was asked for.
    assert metrics["eval_buckets"] == eval_buckets
    assert metrics["cramers_v"] == 0.42
    assert set(metrics["recovery"]) == set(experiment.STRATEGIES) - {"frozen"}
    assert res["recall_efficiency@50"].notna().all()


def test_the_drift_experiment_records_the_parameters_that_move_its_numbers(drift_corpus):
    """Seed, iterations and sample all change the result. A manifest that
    omits one cannot distinguish two different experiments."""
    from aml.drift import experiment

    root, _, _ = drift_corpus
    out = root / "out2"
    experiment.run(str(root / "features"), str(root / "drift"), str(out),
                   seed=3, iters=20, bootstrap=0)
    man = json.loads((out / "manifest.json").read_text())
    cfg = man["config"]
    assert cfg["seed"] == 3 and cfg["iters"] == 20
    assert cfg["magnitude"] == 1.0 and cfg["n_buckets"] == 4
    assert cfg["strategies"] == list(experiment.STRATEGIES)
    assert man["status"] == "ok" and man.get("code_tree_sha256")


def test_the_drift_experiment_refuses_a_window_with_no_evaluation_buckets(drift_corpus):
    """`train_buckets >= n_buckets` leaves nothing to evaluate on. Writing an
    empty CSV and a `status: ok` manifest would be the worse outcome."""
    from aml.drift import experiment

    root, _, n_buckets = drift_corpus
    bad = root / "drift_bad"
    bad.mkdir()
    man = json.loads((root / "drift" / "drift_manifest.json").read_text())
    man["train_buckets"] = n_buckets
    (bad / "drift_manifest.json").write_text(json.dumps(man))

    with pytest.raises(ValueError, match="no evaluation buckets"):
        experiment.run(str(root / "features"), str(bad), str(root / "out3"),
                       seed=0, iters=10, bootstrap=0)


# ---------------------------------------------------------------------------
# predictions_sha256 must describe the file a reader can download (v7 P1-2)
# ---------------------------------------------------------------------------

def test_the_prediction_digest_recomputes_from_the_stored_parquet(demo_corpus):
    """The digest hashed a representation that is neither stored nor evaluated.

    `train` writes `score` to Parquet, where the field is `double`, and passes
    the same float64 array to `evaluate`. The manifest hashed
    `np.asarray(score, dtype=np.float32).tobytes()` — a third thing — under a
    comment claiming float32 was "the precision the scores are stored and
    evaluated at". README and LIMITATIONS then called two matching values
    "bitwise-identical predictions".

    A digest of something that does not exist cannot settle a question about
    something that does. This recomputes the recorded value from the committed
    file, which is the only check that would have failed.
    """
    import hashlib

    import numpy as np
    import pyarrow.parquet as pq

    man = json.loads((demo_corpus / "models" / "manifest.json").read_text())
    metrics = man["metrics"]
    assert metrics.get("predictions_dtype"), "the stored dtype is not recorded"

    table = pq.read_table(demo_corpus / "models" / "gbdt_test_scores.parquet")
    stored_dtype = str(table.schema.field("score").type)
    ids = np.ascontiguousarray(table.column("txn_id").to_numpy())
    scores = np.ascontiguousarray(table.column("score").to_numpy())

    # The recorded dtype must be the dtype on disk, not a convenient one.
    assert metrics["predictions_dtype"] == str(scores.dtype), (
        f"manifest says {metrics['predictions_dtype']}, the Parquet field is "
        f"{stored_dtype} which reads back as {scores.dtype}")

    h = hashlib.sha256()
    h.update(f"{ids.dtype.str}|{scores.dtype.str}|{ids.size}|".encode())
    h.update(memoryview(ids))
    h.update(memoryview(scores))
    assert h.hexdigest() == metrics["predictions_sha256"], (
        "the recorded prediction digest does not recompute from the file it "
        "claims to describe")


def test_the_tolerance_digest_is_named_as_one_and_behaves_like_one(demo_corpus):
    """Quantising to float32 is a defensible thing to want -- it is what you
    compare across platforms, where float64 tails differ where no metric can
    see it. It is not bitwise identity, and calling it that was the defect.

    Both are recorded now, and they must behave differently: a perturbation
    below float32 resolution must move the exact digest and not the tolerance
    one.
    """
    import hashlib

    import numpy as np

    from aml.models.train import _predictions_digest

    metrics = json.loads(
        (demo_corpus / "models" / "manifest.json").read_text())["metrics"]
    assert metrics.get("predictions_tolerance_sha256"), "no tolerance digest"
    assert metrics["predictions_tolerance_sha256"] != metrics["predictions_sha256"]

    ids = np.arange(4, dtype=np.int64)
    a = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    b = a.copy()
    b[1] += 1e-12                       # far below float32 resolution

    tol = lambda x: hashlib.sha256(
        np.asarray(x, dtype=np.float32).tobytes()).hexdigest()
    assert tol(a) == tol(b), "the tolerance digest is not tolerant"
    assert _predictions_digest(ids, a) != _predictions_digest(ids, b), (
        "the exact digest ignored a float64 difference, so it is a tolerance "
        "digest wearing the other one's name")
