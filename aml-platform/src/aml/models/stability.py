"""Find a model configuration whose reported numbers hold still.

THE PROBLEM THIS SOLVES
-----------------------
Measured on HI-Medium, 8 seeds, production config, nothing varying but the seed:

    ROC-AUC                       0.1% spread
    average precision            16.9%
    recall_efficiency@50         37.2%    range [0.5956, 0.9044]
    precision@50                 37.2%
    alerts per true positive     46.8%

A 31-point range on the headline metric. That is not a reporting problem to be
papered over with error bars -- it is a model that has not settled, and taking
it to a one-shot cloud budget would mean paying for a number we cannot stand
behind.

WHY IT IS PROBABLY UNSTABLE
---------------------------
Prevalence is 0.11%: 15,713 positives in 19,487,126 training rows. With
`class_weight="balanced"` each positive is up-weighted roughly 620x, so a
handful of rows dominates the gradient. At `learning_rate=0.1` over 300
iterations, small changes in which of those rows land in which histogram bin
propagate hard. Hypotheses, each with a knob:

    too-aggressive steps      -> lower learning_rate, more iterations
    leaves fit to few rows    -> raise min_samples_leaf
    extreme up-weighting      -> test class_weight=None as a control
    single-fit lottery        -> average predictions over seeds (an ensemble)

WHAT THIS MODULE DECIDES
------------------------
For each candidate configuration: fit once per seed, and report the MEAN and the
RANGE of the metrics that matter. The configuration we take to the cloud is the
one that is stable AND good -- in that order, because a great number we cannot
reproduce is worth less than a good number we can.

The ensemble arm is not another configuration; it is a reporting strategy. It
averages the per-seed predicted probabilities of a configuration already fitted,
so it costs no extra fits and it is what the paper would actually report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aml import io
from aml.eval.metrics import evaluate
from aml.features.build import FEATURES
from aml.manifest import Run
from aml.models import config as model_config

# Candidates. `current` is the incumbent and must stay first so every table
# reads as "what we have" then "what we tried".
CONFIGS: dict[str, dict] = {
    # Not a copy: the incumbent IS the shipped configuration, read from its one
    # definition. A hand-written duplicate here could drift and turn this whole
    # comparison into a straw man.
    "current": dict(model_config.GBDT),
    "slow_long": {**model_config.GBDT, "learning_rate": 0.05, "max_iter": 600},
    "slow_long_bigleaf": {**model_config.GBDT, "learning_rate": 0.05,
                          "max_iter": 600, "min_samples_leaf": 200},
    "bigleaf": {**model_config.GBDT, "min_samples_leaf": 200},
    # Control, not a recommendation. If dropping the 620x up-weighting collapses
    # the variance, the weighting is the culprit and the fix is a milder weight
    # rather than no weight -- the project rejected resampling for good reasons
    # and unweighted training at 0.11% prevalence has its own problems.
    "unweighted": {**model_config.GBDT, "class_weight": None},
}

# The metrics a decision actually turns on. ROC-AUC is excluded on purpose: it
# is stable because it is saturated, so including it would reward the wrong
# thing.
REPORT = ["average_precision__txn", "recall_efficiency@50", "precision@50",
          "recall@50", "ring_recall@200"]
BUDGETS = (10, 50, 200)

# How many seed orderings to average the ensemble-size curve over. The curve
# decides how many training runs we pay for at 182M rows, so it should not be an
# artifact of which seed happened to be first.
#
# Was 12, which is N_ORDERINGS x N_SEEDS = 96 full evaluations -- and each one
# aggregates the whole test set into account-days. On HI-Medium that tail took
# longer than the eight model fits it was supposed to be free relative to. At
# 182M rows it would be an expensive mistake. 4 is enough: the spread across
# orderings collapses to near zero by n=3.
N_CURVE_ORDERINGS = 4


def _fit_predict(Xtr, ytr, Xte, cfg: dict, seed: int) -> np.ndarray:
    clf = model_config.gbdt(seed, **cfg)
    clf.fit(Xtr, ytr)
    return clf.predict_proba(Xte)[:, 1]


def _spread(values: np.ndarray) -> dict:
    """Variability of a metric across seeds, reported three ways on purpose.

    WHY NOT JUST (max-min)/mean

        Because it is a two-point statistic and one bad fit owns it. The
        project's headline "budget metrics move 37.2%" is exactly that: on
        HI-Medium, precision@50 across eight seeds is

            0.794 0.898 0.895 0.896 [0.591] 0.830 0.844 0.851

        Seed 4 alone produces the 37.2%. Drop it and the range is 12.1%; the
        median absolute deviation is 5.7%. All three numbers are true and they
        support different sentences, so all three are now reported rather than
        the most dramatic one.

        The finding survives -- these metrics really are far less stable than
        ROC-AUC, and an outlier fit is itself the instability being described.
        But "the spread is 37%" invites reading it as typical when it is a
        worst case, and the honest headline is the robust figure with the range
        quoted beside it.

    iqr_pct and mad_pct are the robust pair; spread_pct is kept because earlier
    results quote it and removing it would silently change published numbers.
    """
    v = np.asarray(values, dtype=float)
    mean, med = float(v.mean()), float(np.median(v))
    q1, q3 = (float(x) for x in np.percentile(v, [25, 75]))
    mad = float(np.median(np.abs(v - med)))
    pct = lambda num, den: round(float(100 * num / den), 2) if den else None
    return {
        "mean": round(mean, 5),
        "median": round(med, 5),
        "min": round(float(v.min()), 5),
        "max": round(float(v.max()), 5),
        "range": round(float(v.max() - v.min()), 5),
        # Worst case. One outlier fit can own it -- see the docstring.
        "spread_pct": pct(v.max() - v.min(), mean),
        # Typical case, outlier-resistant.
        "iqr_pct": pct(q3 - q1, med),
        "mad_pct": pct(mad, med),
        "n": int(v.size),
    }


def run(features: str, splits: str, dest: str, seeds=(0, 1, 2, 3, 4),
        configs=None, sample: float = 1.0):
    """Fit every (config, seed), then score each config and its seed-ensemble."""
    from aml.models.train import load_split

    names = list(configs) if configs else list(CONFIGS)
    # feature_set is NOT decoration. It is the columns actually handed to the
    # model, and without it two runs over different feature sets hash the same.
    # That is not hypothetical: three graph-feature A/B runs (2026-08-25 and
    # -08-28) all wrote config_hash 4522216a... while two of them produced
    # different numbers, so the manifests could not tell the experiments apart.
    # Read from the module global on purpose -- a caller that rebinds
    # stability.FEATURES to probe a subset gets that subset recorded here.
    cfg_meta = {"features": str(features), "splits": str(splits),
                "seeds": list(seeds), "configs": {n: CONFIGS[n] for n in names},
                "sample": sample, "stability_version": "1.1.0",
                "feature_set": list(FEATURES), "n_features": len(FEATURES)}

    with Run("model_stability", cfg_meta, dest) as run_:
        tr, te = load_split(str(features), str(splits), sample=sample)
        Xtr = tr[FEATURES].to_numpy(dtype=np.float32)
        ytr = tr.is_laundering.to_numpy()
        Xte = te[FEATURES].to_numpy(dtype=np.float32)
        print(io.json_line({"event": "stability_loaded", "train_rows": len(tr),
                          "test_rows": len(te), "train_positives": int(ytr.sum())}))

        results = {}
        for name in names:
            cfg = CONFIGS[name]
            per_seed, preds, typ_per_seed = [], [], []
            for s in seeds:
                p = _fit_predict(Xtr, ytr, Xte, cfg, s)
                preds.append(p)
                m = evaluate(te, p, budgets=BUDGETS, per_typology=True)
                per_seed.append({k: m[k] for k in REPORT if k in m})
                typ_per_seed.append(m.get("per_typology") or {})
                print(io.json_line({"event": "stability_fit", "config": name, "seed": s,
                                  "ap": round(m["average_precision__txn"], 5),
                                  "eff50": round(m["recall_efficiency@50"], 5)}),
                      flush=True)

            # PERSIST THE PREDICTIONS.
            #
            # Three separate analyses so far had to refit all eight models
            # because these arrays were thrown away -- the ensemble-size curve,
            # the per-typology breakdown, and a re-check of the noise floor. On
            # a laptop that is 80 wasted minutes each time. At 182M rows it is
            # real money against a one-shot budget, and every "what about metric
            # X?" question after the run would be unanswerable.
            #
            # Scores are keyed by txn_id, never by position: see the F8 note in
            # models/train.py for what positional score joins cost here.
            scores = pd.DataFrame({"txn_id": te.txn_id.to_numpy()})
            for s, p in zip(seeds, preds, strict=True):
                scores[f"score_seed{s}"] = p.astype("float32")
            io.ensure_dir(dest)
            scores.to_parquet(io.join(dest, f"predictions_{name}.parquet"), index=False)
            print(io.json_line({"event": "predictions_saved", "config": name,
                              "rows": len(scores), "seeds": list(seeds)}), flush=True)

            # The ensemble: mean predicted probability across the seeds already
            # fitted. No extra fits, and it is the reporting strategy the paper
            # would use.
            ens = evaluate(te, np.mean(preds, axis=0), budgets=BUDGETS,
                           per_typology=True)

            # HOW MANY SEEDS DO WE ACTUALLY NEED? This decides real money.
            #
            # The reported model is an ensemble, so at 182M rows we pay for one
            # feature build plus N training runs. If the gain plateaus at N=4,
            # buying 8 wastes half the training budget; if it does not, buying 4
            # throws away accuracy we could have had. Computing the curve here
            # costs nothing -- the fits already exist -- and it is the only way
            # to choose N from evidence rather than by feel.
            # Averaged over several ORDERINGS of the seeds, not just preds[:k].
            #
            # The naive version takes the first k fits in seed order, so the k=1
            # point is one specific seed. Observed on HI-Medium: seed 0 was the
            # worst of the eight (eff@50 0.7995 vs a mean of 0.8306), which made
            # the 1->2 step look like +14% when the honest figure against a
            # typical single fit is +10%. Averaging over orderings removes that
            # artifact, and it is free -- the fits already exist.
            rng = np.random.default_rng(0)
            orderings = [list(range(len(preds)))] + [
                list(rng.permutation(len(preds))) for _ in range(N_CURVE_ORDERINGS - 1)
            ]
            curve = []
            for k in range(1, len(preds) + 1):
                vals: dict[str, list] = {}
                for order in orderings:
                    mk = evaluate(te, np.mean([preds[i] for i in order[:k]], axis=0),
                                  budgets=BUDGETS, per_typology=False)
                    for m in REPORT:
                        if m in mk:
                            vals.setdefault(m, []).append(mk[m])
                row = {"n_seeds": k, "n_orderings": len(orderings)}
                for m, xs in vals.items():
                    a = np.array(xs)
                    row[m] = round(float(a.mean()), 5)
                    row[f"{m}__min"] = round(float(a.min()), 5)
                    row[f"{m}__max"] = round(float(a.max()), 5)
                curve.append(row)

            results[name] = {
                "config": cfg,
                "per_seed": per_seed,
                "stability": {k: _spread(np.array([d[k] for d in per_seed]))
                              for k in REPORT if k in per_seed[0]},
                "ensemble": {k: round(ens[k], 5) for k in REPORT if k in ens},
                "ensemble_size_curve": curve,
                "per_typology": _typology_summary(typ_per_seed,
                                                  ens.get("per_typology") or {}),
                "typology_coverage_pct__txn": ens.get("typology_coverage_pct__txn"),
            }
            print(io.json_line({"event": "stability_config_done", "config": name,
                              "ap_spread_pct": results[name]["stability"]
                              ["average_precision__txn"]["spread_pct"],
                              "eff50_spread_pct": results[name]["stability"]
                              ["recall_efficiency@50"]["spread_pct"],
                              "ensemble_ap": results[name]["ensemble"]
                              ["average_precision__txn"]}), flush=True)

        io.ensure_dir(dest)
        io.write_json(io.join(dest, "stability.json"), results, default=str)
        best = _recommend(results)
        io.write_json(io.join(dest, "recommendation.json"), best, default=str)
        run_.record(n_configs=len(names), n_seeds=len(seeds),
                    n_fits=len(names) * len(seeds), train_rows=len(tr),
                    test_rows=len(te), **best)
        print(io.json_line({"event": "model_stability_complete", **best}))
        return results


def _typology_summary(per_seed: list, ensemble: dict) -> dict:
    """Per-laundering-structure detection, with the spread across seeds.

    This is the one result here that is about laundering rather than about the
    harness: an aggregate "we catch 71% of rings" can hide catching two thirds
    of one structure and one seventh of another, and a bank would care far more
    about the gap than the average.

    Reported with a range because each typology has only 55-78 rings in the
    HI-Medium test set. A single-seed value on that few rings is not a
    measurement, and the first version of this number was exactly that.
    """
    # THE BUDGET TRAVELS WITH THE NUMBER.
    #
    # This returned `per_seed_mean` and `ensemble` with the budget stripped,
    # inside an artifact whose `per_seed` block reports `ring_recall@200`. So
    # the per-typology block was ring_recall@50 under budget-free names sitting
    # beside an @200 headline, every consumer had to guess, and a downstream
    # null guessed 200 -- measuring a spread at one budget against strata
    # measured at another, which is the error class this project keeps hitting.
    # `metric` and `budget` are now recorded so nothing has to infer them.
    budget = 50
    key = f"ring_recall@{budget}"
    typs = sorted({t for d in per_seed for t in d})
    out: dict = {"_metric": {"metric": key, "budget": budget,
                             "note": "every per-typology value in this block "
                                     "is " + key + "; the per_seed block above "
                                     "reports ring_recall@200, a different "
                                     "budget"}}
    for t in typs:
        vals = np.array([d[t][key] for d in per_seed if t in d and key in d[t]],
                        dtype=float)
        if not vals.size:
            continue
        n_rings = next((d[t].get("n_rings") for d in per_seed if t in d), None)
        out[t] = {
            "n_rings": n_rings,
            "per_seed_mean": round(float(vals.mean()), 4),
            "per_seed_min": round(float(vals.min()), 4),
            "per_seed_max": round(float(vals.max()), 4),
            "n_seeds": int(vals.size),
            "ensemble": round(float(ensemble.get(t, {}).get(key)), 4)
            if ensemble.get(t, {}).get(key) is not None else None,
        }
    # The headline: how far apart are the easiest and hardest structures? Taken
    # from the ENSEMBLE, since that is the reported model.
    ens_vals = {t: v["ensemble"] for t, v in out.items() if v["ensemble"] is not None}
    if len(ens_vals) >= 2:
        lo_t = min(ens_vals, key=ens_vals.get)
        hi_t = max(ens_vals, key=ens_vals.get)
        lo, hi = ens_vals[lo_t], ens_vals[hi_t]
        out["_spread"] = {
            "hardest": lo_t, "hardest_recall": lo,
            "easiest": hi_t, "easiest_recall": hi,
            "ratio": round(hi / lo, 2) if lo else None,
        }
    return out


def _recommend(results: dict) -> dict:
    """Stable first, then good.

    A configuration qualifies if its headline metric's spread is at most half
    the incumbent's. Among those that qualify, take the best ensemble average
    precision. If none qualify, say so plainly rather than crowning a winner --
    an unstable best is what we are trying to get away from.
    """
    key = "recall_efficiency@50"
    base = results["current"]["stability"][key]["spread_pct"]
    qualifying = {n: r for n, r in results.items()
                  if r["stability"][key]["spread_pct"] <= base / 2}
    if qualifying:
        pick = max(qualifying,
                   key=lambda n: qualifying[n]["ensemble"]["average_precision__txn"])
        reason = (f"{key} spread {results[pick]['stability'][key]['spread_pct']}% "
                  f"vs incumbent {base}%; best ensemble AP among qualifying")
    else:
        pick = min(results, key=lambda n: results[n]["stability"][key]["spread_pct"])
        reason = (f"NO config halved the incumbent's {base}% spread. "
                  f"Least-unstable is {pick} at "
                  f"{results[pick]['stability'][key]['spread_pct']}%. "
                  f"Report ensembles with ranges and do not claim a point value.")
    return {
        "recommended_config": pick,
        "incumbent_spread_pct": base,
        "recommended_spread_pct": results[pick]["stability"][key]["spread_pct"],
        "recommended_ensemble_ap": results[pick]["ensemble"]["average_precision__txn"],
        "recommended_ensemble_eff50": results[pick]["ensemble"][key],
        "halved_incumbent_spread": bool(qualifying),
        "reason": reason,
    }
