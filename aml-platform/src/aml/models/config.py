"""The production model configuration. One definition, read everywhere.

WHY THIS FILE EXISTS
    The GBDT hyperparameters were written out three times -- in train.py's MODELS
    table, in the leak proof's own fitter, and again as the incumbent in the
    stability sweep. Three copies of one fact, kept in sync by hand.

    That is the same shape as the txn_id defect: two components each derived
    txn_id with an identical expression, and a comment in each said the
    expressions must stay identical. They did stay identical, and it broke
    anyway. "Keep the copies in sync" is not a control.

    Here the failure mode would be quieter and worse. If the leak proof fits at
    learning_rate=0.1 while the shipped model moves to 0.05, the harness
    validates a model nobody reports, every detection verdict describes a
    configuration that does not exist, and nothing errors.

    So: one dict, imported by train, by the leak sweep, and by the stability
    sweep. Changing the production model means editing this file and nothing
    else.
"""
from __future__ import annotations

# Boosting rounds for the shipped model. Checkpoints are written every
# CHECKPOINT_EVERY rounds, so a crash at 280 resumes at 250.
GBDT_ITERS = 300
CHECKPOINT_EVERY = 50

# The shipped GBDT.
#
# class_weight="balanced" and NOT resampling: SMOTE and friends fabricate
# transactions belonging to no ring, which corrupts every ring-level metric.
#
# ⚠️ At 0.11% prevalence "balanced" up-weights each positive roughly 620x, so a
# few thousand rows dominate the gradient.
#
# THIS COMMENT USED TO NAME `balanced` AS THE LIKELIEST CAUSE OF THE 37%
# RUN-TO-RUN SPREAD, AND IT CANNOT BE. `class_weight="balanced"` is a deterministic
# function of `y`: sklearn computes it with `compute_sample_weight`, the same
# vector every run. A quantity that never varies between runs cannot be the
# source of variation between runs.
#
# The source is the bin mapper. With `early_stopping: False` below, the only
# live consumer of `random_state` in HistGradientBoostingClassifier is
# `_BinMapper`'s 200,000-row subsample -- verified two ways in
# `test_the_seed_varies_only_the_bin_edges`: by tracing sklearn's own call
# sites, and by observing that below 200k rows different seeds give BYTE-
# IDENTICAL predictions. LightGBM's `subsample_for_bin` default is the same
# 200,000 and this file sets no bagging or feature fraction, so the same is
# true there.
#
# What `balanced` plausibly does is AMPLIFY that: up-weighting a few thousand
# positives 620x makes the fit acutely sensitive to which of them landed in the
# subsample that set the bin edges. Amplifier, not source. `stability.py`
# exists to test it; if a candidate configuration wins there it is promoted by
# editing THIS dict.
GBDT: dict = {
    "learning_rate": 0.1,
    "max_iter": GBDT_ITERS,
    "max_depth": 8,
    "min_samples_leaf": 40,
    "class_weight": "balanced",
}


def gbdt_params(seed: int, **overrides) -> dict:
    """The shipped hyperparameters as plain data, for cache keys and manifests.

    Separate from gbdt() because a manifest has to be JSON, and a fitted
    estimator is not. Keeping the two in one function is what let train.py's
    run key omit the hyperparameters entirely: there was no serialisable form
    to put in it.
    """
    return {**GBDT, "random_state": seed, "early_stopping": False, **overrides}


def gbdt(seed: int, **overrides):
    """The shipped classifier. Overrides are for experiments, not for callers
    who merely want "the model" -- those should pass nothing."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(**gbdt_params(seed, **overrides))


# ---------------------------------------------------------------------------
# The same model, a different library
# ---------------------------------------------------------------------------
#
# WHY A SECOND GBDT EXISTS, WHEN THIS FILE'S WHOLE POINT IS ONE DEFINITION
#
#     Not as an alternative to tune against. As an instrument to measure a
#     library ceiling that was mistaken for a data ceiling.
#
#     sklearn's HistGradientBoosting sets X_DTYPE = np.float64 and upcasts
#     whatever it is given, so training HI-Large's 125M x 32 matrix needs
#     33.5 GB before a single tree is built. The machine has 31 GB and cannot
#     be made larger -- `az quota update` on a trial subscription returns
#     ResourceNotAvailableForOffer. Four OOM kills went into establishing that,
#     and the first three fixes were each real and each insufficient.
#
#     LightGBM bins to uint8 during Dataset construction and can release the
#     raw array afterwards, so the same data on the same machine needs roughly
#     20 GB. That turns "we had to subsample" into a measurement:
#
#         the ceiling was the library, not the data and not the machine.
#
# WHY THE PARAMETERS ARE MAPPED THIS PEDANTICALLY
#
#     For that claim to mean anything, the two fits must differ in library and
#     nothing else. Every value below is the LightGBM spelling of a value in
#     GBDT above -- including num_leaves=31, which is NOT LightGBM's default of
#     31... it is, but only by coincidence, and it is written out because it
#     mirrors sklearn's max_leaf_nodes default of 31 rather than because
#     LightGBM happens to agree. sklearn grows leaf-wise up to max_leaf_nodes
#     with max_depth as a cap, and this reproduces that shape.
#
#     Two things genuinely cannot be mapped, and are recorded rather than
#     papered over:
#       - LightGBM has no exact equivalent of sklearn's internal binning
#         thresholds, so identical predictions are NOT expected. Comparable
#         metrics are.
#       - min_child_weight has no sklearn counterpart. It was first set to 0 to
#         mean "no constraint, like sklearn". At 125M rows that crashed:
#
#             LightGBMError: Check failed: (best_split_info.left_count) > (0)
#             at serial_tree_learner.cpp, line 860
#
#         i.e. LightGBM accepted a split with an empty child. It does not
#         reproduce at 400k or 600k rows, with or without NaN columns and
#         near-constant features -- both were tried -- so it is scale
#         dependent and cannot be chased on a 16 GB laptop. Left at LightGBM's
#         own default, which is the value its split guards are written
#         against. The cost is that LightGBM prunes a few splits sklearn would
#         keep; that is a real difference between the fits and is recorded
#         here rather than hidden.
#
# deterministic=True for the same reason every other run here is seeded: a
# comparison you cannot repeat is an anecdote.
LGBM: dict = {
    "learning_rate": GBDT["learning_rate"],
    "n_estimators": GBDT_ITERS,
    "max_depth": GBDT["max_depth"],
    "min_child_samples": GBDT["min_samples_leaf"],
    "num_leaves": 31,
    "min_child_weight": 1e-3,
    "class_weight": GBDT["class_weight"],
    "deterministic": True,
    "force_row_wise": True,
    "verbosity": -1,
}


# ⚠️ `deterministic=True` HOLDS ONLY AT A FIXED THREAD COUNT, and `n_jobs=-1`
# below does not fix one. LightGBM's own documentation makes determinism
# conditional on `num_threads` being held constant; with -1 it follows the
# machine. So the HI-Large three-seed spread is NOT a clean measurement of
# bin-subsample sensitivity alone -- thread count is a second uncontrolled
# nuisance factor, and any claim that the spread is a lower bound attributable
# to one cause has to say so. `paper/RESULTS_metric_stability.md` §3c does.
def lgbm_params(seed: int, **overrides) -> dict:
    """Plain data, for cache keys and manifests -- same reason as gbdt_params."""
    return {**LGBM, "random_state": seed, "n_jobs": -1, **overrides}


def lgbm(seed: int, **overrides):
    """LightGBM configured to match GBDT as closely as the libraries allow."""
    from lightgbm import LGBMClassifier

    return LGBMClassifier(**lgbm_params(seed, **overrides))
