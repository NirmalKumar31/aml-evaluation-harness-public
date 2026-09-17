"""
drift_experiment: does a frozen model decay under drift, and does retraining
recover it?

This is the question the project is named for. The answer is only meaningful
because the drift is CONSTRUCTED -- we know its exact magnitude, we can dial it
to zero as a control, and we know which ring shape every positive belongs to.

FOUR UPDATE STRATEGIES

  frozen          Trained once on the stable buckets, never updated. The
                  do-nothing baseline every bank starts from.

  naive_retrain   Expanding window: to score bucket k, retrain on buckets
                  0..k-1. The obvious fix, and the one most teams reach for.

  sliding_window  Retrain on bucket k-1 only. Trades sample size for
                  recency -- better if the world has genuinely moved on,
                  worse if it has not.

  typology_replay Retrain on 0..k-1 but reweight the training rings so every
                  typology carries equal total weight. The idea being tested:
                  if the incoming regime over-represents CYCLE and STACK, a
                  model that has not been allowed to under-weight the rare
                  shapes should degrade less. This is the strategy the whole
                  manufactured-drift apparatus exists to evaluate.

WHAT MAKES THE COMPARISON FAIR
  * identical model class, hyperparameters and seed for all four
  * identical evaluation buckets and identical metric
  * the source ring pools are DISJOINT PER BUCKET (see resample.py), so no
    strategy can win by recognising a ring it was trained on
  * the magnitude=0 run is a control: with no drift, no strategy should beat
    frozen by anything meaningful. If one does, the harness is measuring
    something other than drift.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from aml import io
from aml.eval.metrics import bootstrap_ci, evaluate
from aml.features.build import FEATURES
from aml.manifest import Run

# The drift experiment's operating points, used for BOTH the evaluation and
# the intervals so the two cannot drift apart.
DRIFT_BUDGETS = (10, 50, 200)

STRATEGIES = ("frozen", "naive_retrain", "sliding_window", "typology_replay")


def _fit(X, y, w=None, seed: int = 0, iters: int = 150):
    m = HistGradientBoostingClassifier(
        max_iter=iters, learning_rate=0.1, max_depth=8, min_samples_leaf=40,
        class_weight="balanced", random_state=seed, early_stopping=False)
    m.fit(X, y, sample_weight=w)
    return m


def _typology_weights(df: pd.DataFrame) -> np.ndarray:
    """Equal total weight per typology, negatives left at 1.0.

    A rare shape in training gets each of its rows up-weighted so the shape as a
    whole matters as much as a common one. That is the 'replay' idea: refuse to
    let the current mix decide how much the model cares about each shape.
    """
    w = np.ones(len(df), dtype=np.float64)
    pos = df.typology.notna().to_numpy()
    if pos.sum() == 0:
        return w
    counts = df.loc[pos, "typology"].value_counts()
    target = counts.mean()
    factor = df.loc[pos, "typology"].map(target / counts).to_numpy()
    w[pos] = factor
    return w


def _bucket_of(event_time: pd.Series, t0: pd.Timestamp, blen: pd.Timedelta,
               n_buckets: int) -> np.ndarray:
    b = ((event_time - t0) / blen).astype("float").to_numpy()
    return np.clip(np.floor(b), 0, n_buckets - 1).astype(int)


def run(features: str, drift: str, dest: str, seed: int = 0, iters: int = 150,
        bootstrap: int = 500, sample: float = 1.0):
    features, drift, dest = str(features), str(drift), str(dest)
    man = io.read_json(io.join(drift, "drift_manifest.json"))
    n_buckets = man["n_buckets"]
    train_buckets = man.get("train_buckets", 2)
    t0 = pd.Timestamp(man["window"][0])
    blen = pd.Timedelta(days=man["bucket_length_days"])
    magnitude = man["magnitude"]

    cfg = {"features": features, "drift": drift, "magnitude": magnitude,
           "n_buckets": n_buckets, "train_buckets": train_buckets,
           "seed": seed, "iters": iters, "sample": sample,
           "strategies": list(STRATEGIES), "experiment_version": "1.0.0"}

    with Run(f"drift_experiment[m={magnitude}]", cfg, dest) as r:
        con = io.duckdb_connect(features)
        feat_sql = ", ".join(f"CAST({f} AS FLOAT) AS {f}" for f in FEATURES)
        samp = "" if sample >= 1.0 else f" WHERE hash(txn_id) % 10000 < {int(sample*10000)}"
        df = con.execute(
            f"SELECT txn_id, {feat_sql}, is_laundering, ring_id, typology, "
            f"event_time, event_date, sender_id, receiver_id "
            f"FROM read_parquet({io.parquet_arg(features)}){samp} ORDER BY txn_id").df()

        df["bucket"] = _bucket_of(df.event_time, t0, blen, n_buckets)
        # NOT dict(df.groupby(...)) -- see the note in drift/resample.py.
        by_bucket = {b: g for b, g in df.groupby("bucket")}  # noqa: C416 - see above
        eval_buckets = [b for b in range(train_buckets, n_buckets) if b in by_bucket]
        if not eval_buckets:
            raise ValueError("no evaluation buckets contain data")

        X = lambda g: g[FEATURES].to_numpy(dtype=np.float32)
        y = lambda g: g.is_laundering.to_numpy()

        # The frozen model: fitted once on the stable regime, never touched.
        stable = pd.concat([by_bucket[b] for b in range(train_buckets)
                            if b in by_bucket], ignore_index=True)
        frozen = _fit(X(stable), y(stable), seed=seed, iters=iters)

        rows = []
        for b in eval_buckets:
            te = by_bucket[b]
            expanding = pd.concat([by_bucket[k] for k in range(b) if k in by_bucket],
                                  ignore_index=True)
            prev = by_bucket.get(b - 1)

            models = {
                "frozen": frozen,
                "naive_retrain": _fit(X(expanding), y(expanding), seed=seed, iters=iters),
                "sliding_window": (_fit(X(prev), y(prev), seed=seed, iters=iters)
                                   if prev is not None else frozen),
                "typology_replay": _fit(X(expanding), y(expanding),
                                        w=_typology_weights(expanding),
                                        seed=seed, iters=iters),
            }
            for name, mdl in models.items():
                score = mdl.predict_proba(X(te))[:, 1]
                # ONE TUPLE. This evaluated (10, 50, 200) and then asked for
                # intervals at all seven defaults, so four of them described
                # operating points this run never measured.
                m = evaluate(te, score, budgets=DRIFT_BUDGETS, per_typology=False)
                ci = bootstrap_ci(te, score, budget=50, n=bootstrap, seed=seed,
                                  budgets=DRIFT_BUDGETS)
                rows.append(dict(
                    bucket=b, strategy=name, magnitude=magnitude,
                    n_rows=len(te), n_positives=int(te.is_laundering.sum()),
                    train_rows=int(len(stable) if name == "frozen"
                                   else len(prev) if name == "sliding_window"
                                   else len(expanding)),
                    # startswith, not "in": "average_precision" CONTAINS
                    # "precision", so a substring test captured it here and then
                    # it was passed again below -- a duplicate keyword argument.
                    **{k: v for k, v in m.items()
                       if k.startswith(("recall", "precision", "ring_recall",
                                        "alerts_per"))},
                    # Keys carry their unit suffix, and it is KEPT on the way
                    # out. Stripping it here -- which the first version of this
                    # line did, while the line below raised KeyError for
                    # forgetting it -- writes an ambiguous column name to disk
                    # and defeats the rename two lines above it.
                    average_precision__txn=m["average_precision__txn"],
                    roc_auc_footnote_only__txn=m["roc_auc_footnote_only__txn"],
                    ci_lo=ci["ci_lo"], ci_hi=ci["ci_hi"],
                    n_clusters=ci.get("n_clusters")))

        res = pd.DataFrame(rows)
        io.ensure_dir(dest)
        # pandas routes URIs through fsspec, so this needs io.join only to stop
        # pathlib collapsing the "//" in an abfss:// destination.
        res.to_csv(io.join(dest, f"drift_results_m{magnitude}.csv"), index=False)

        # Headline: how much of the frozen model's decay does each strategy
        # recover? Decay is measured against the FIRST evaluation bucket, where
        # the drift has barely started.
        eff = res.pivot_table(index="bucket", columns="strategy",
                              values="recall_efficiency@50")
        first, last = eval_buckets[0], eval_buckets[-1]
        frozen_decay = float(eff.loc[first, "frozen"] - eff.loc[last, "frozen"])
        recovery = {}
        for s in STRATEGIES:
            if s == "frozen":
                continue
            gain = float(eff.loc[last, s] - eff.loc[last, "frozen"])
            recovery[s] = {
                "gain_at_last_bucket": round(gain, 4),
                "fraction_of_decay_recovered":
                    round(gain / frozen_decay, 4) if frozen_decay > 0 else None,
            }

        r.record(
            magnitude=magnitude, cramers_v=man["cramers_v"],
            eval_buckets=eval_buckets,
            frozen_efficiency_by_bucket={int(b): round(float(eff.loc[b, "frozen"]), 4)
                                         for b in eff.index},
            frozen_decay=round(frozen_decay, 4),
            recovery=recovery,
            drift_is="INDUCED, not observed",
        )
        print(io.json_line({"event": "drift_experiment_complete", **r.metrics},
                         default=str))
        return r.metrics
