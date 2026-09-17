"""
evaluate: recompute the metric suite from saved scores, without retraining.

Training is the expensive step and the scores it produces are the only thing
the metrics need. Keeping evaluation separate means a change to a metric
definition costs seconds instead of half an hour -- and it is what makes the
metric suite safe to iterate on.
"""

import pandas as pd

from aml import io
from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci, evaluate
from aml.features.build import FEATURES
from aml.manifest import Run
from aml.models.train import load_test


def run(features: str, splits: str, scores: str, dest: str, model: str = "gbdt",
        budgets=DEFAULT_BUDGETS, bootstrap: int = 1000, seed: int = 0,
        permutations: int = 1000):
    # seed is here because it changes ci_lo/ci_hi. Omitting a parameter that
    # moves a reported number is the same defect as omitting the feature set --
    # and `permutations` is in the config for exactly that reason too: it sets
    # the resolution of the ring null's interval and p-value.
    cfg = {"features": str(features), "splits": str(splits), "scores": str(scores),
           "model": model, "budgets": list(budgets), "bootstrap": bootstrap,
           "seed": seed, "permutations": permutations, "feature_set": list(FEATURES)}

    with Run(f"evaluate[{model}]", cfg, dest) as r:
        # load_test, NOT load_split.
        #
        # load_split returns BOTH halves, and evaluation needs only the test
        # one. At HI-Large that difference is fatal rather than wasteful:
        #
        #     train  29.8 GB   <- loaded, never used
        #     test   13.0 GB
        #     total  42.8 GB   against a 31 GB machine
        #
        # Measured: exit 137 at 55 seconds, OOM-killed before reading the
        # scores. train.py was fixed to load the halves separately and free the
        # training matrix before the test one; this stage was left on the
        # legacy loader, so the same defect survived here in a module whose
        # entire purpose is to be the CHEAP way to recompute metrics.
        #
        # load_test also returns a compact metadata frame rather than the full
        # feature matrix -- evaluation needs event_date, is_laundering, ring_id,
        # typology and the two account codes, not the 32 features.
        _, te = load_test(features, splits)
        sc = pd.read_parquet(scores)
        if len(sc) != len(te):
            raise ValueError(f"scores has {len(sc)} rows, test split has {len(te)}. "
                             f"The scores were produced against a different split.")

        # JOIN on txn_id, never zip by position: load_test's row order is only
        # deterministic because of its ORDER BY, and a positional match would
        # fail silently (as chance-level metrics) if that ever regressed.
        te = te.merge(sc, on="txn_id", how="left", validate="one_to_one")
        if te.score.isna().any():
            raise ValueError(f"{int(te.score.isna().sum())} test rows had no score. "
                             f"Scores and split do not correspond.")
        score = te.score.to_numpy()

        m = evaluate(te, score, budgets=budgets,
                     n_permutations=permutations, perm_seed=seed)
        # The CALLER'S budgets, and an unsuffixed interval at one of THEM.
        #
        # This passed `budget=50` unconditionally, so a caller asking only for
        # budget 10 received `ci_lo@10` plus an unsuffixed interval computed at
        # 50 -- a number for an operating point it never requested. 50 is still
        # preferred when present, because every manifest already written means
        # 50 by `ci_lo`/`ci_hi`; otherwise the smallest requested budget is
        # used and `ci_budget` records which.
        bs = tuple(budgets)
        legacy = 50 if 50 in bs else bs[0]
        m.update(bootstrap_ci(te, score, budget=legacy, n=bootstrap, seed=seed,
                              budgets=bs))
        per_typ = m.pop("per_typology", None)
        r.record(**m)
        r.metrics["per_typology"] = per_typ

        io.ensure_dir(dest)
        io.write_json(io.join(dest, f"{model}_metrics.json"),
                      {**m, "per_typology": per_typ}, default=str)
        print(io.json_line({"event": "evaluate_complete", "model": model,
                          **dict(m.items())}, default=str))
        return r.metrics
