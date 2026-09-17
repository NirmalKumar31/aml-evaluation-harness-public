"""Does the 'largely linear' claim survive removing the hashed categoricals?

H7. `payment_format` and `receiving_currency` enter the feature vector as
`DuckDB hash(value) % 1000` -- a NUMBER. A logistic regression then treats
bucket 17 as lying between 16 and 18, which is meaningless as a category but is
not noise: the model can fit real structure in hash order. So part of what the
headline linear baseline exploits may be the ENCODING rather than the data, and
the claim "most of the separability is linear" cannot be evaluated until that
is measured.

Three arms, same split, same seed, same everything else:

    full          the published 32 features
    no-categorical  the 30 features with both hashed codes removed
    onehot        the hashed codes replaced by explicit one-hot indicators
                  over the values present in TRAINING only, with an
                  everything-else column

If `full` and `onehot` agree, the hash encoding is not doing anything a proper
categorical encoding would not. If `full` beats both, the linear model is
exploiting hash order and the claim must be narrowed further.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

CATEGORICAL = ["payment_format_code", "payment_currency_code"]


def segment_metrics(te, scores, budgets, thin_from) -> dict:
    """Per-arm precision@k split by window segment, plus the random null.

    WITHOUT THIS A RERUN RE-ANSWERS A RETRACTED QUESTION. The arms were
    compared on POOLED `precision@50`, and a pooled budget level on this window
    is 0.95x a random ranker (`docs/LIMITATIONS.md` §1) -- so three arms
    agreeing to 1% agreed about the window, not about the encoding. The
    encoding question needs the volume segment and a null.

    The HI-Medium features exist only on the cloud VM, so a rerun there is the
    one chance to get this; discarding the scores, as this script did for two
    of three arms, would waste it.
    """
    import pandas as pd

    day = pd.to_datetime(te.event_date).dt.date.to_numpy()
    y = te.is_laundering.to_numpy()
    head = day < thin_from
    out = {}
    for b in budgets:
        r = (pd.DataFrame({"d": day, "s": scores})
             .groupby("d")["s"].rank(ascending=False, method="first").to_numpy())
        top = r <= b
        for lab, m in (("", slice(None)), ("_head", head), ("_tail", ~head)):
            sel = top & (np.ones_like(top) if m is slice(None) else m)
            n = int(sel.sum())
            if not n:
                continue
            out[f"precision@{b}{lab}"] = round(float(y[sel].mean()), 5)
            out[f"alerts@{b}{lab}"] = n
    return out


def fit_arm(Xtr, ytr, Xte, te, cols, seed, budgets):
    from aml.eval.metrics import evaluate
    from aml.models.train import MODELS
    clf = MODELS["baseline"](seed)
    clf.fit(Xtr, ytr)
    score = clf.predict_proba(Xte)[:, 1]
    m = evaluate(te, score, budgets=budgets, per_typology=False, n_permutations=0)
    return {k: m[k] for k in
            ("average_precision__txn", "precision@50", "recall@50",
             "recall_efficiency@50", "ring_recall@200") if k in m}, score


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--splits", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--thin-from", default=None,
                    help="the rung's transaction-volume collapse date (see "
                         "results_archive/derived/window_decomposition.json, "
                         "first_thin_day). REQUIRED for the arms to be "
                         "comparable: pooled levels on this window are 0.95x "
                         "a random ranker and cannot settle the encoding.")
    ap.add_argument("--out",
                    default="results_archive/derived/categorical_ablation.json")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    from aml.features.build import FEATURES
    from aml.manifest import generator_provenance
    from aml.models.train import load_test, load_train_xy

    idx = {f: i for i, f in enumerate(FEATURES)}
    keep = [i for f, i in idx.items() if f not in CATEGORICAL]

    t0 = time.time()
    # float32 AND freed between arms.
    #
    # The first HI-Medium attempt was OOM-killed at exit 137. The one-hot arm
    # hstacks a wider matrix while the original is still live -- at 19.5M rows
    # and float64 that is 5 GB plus 8 GB, plus the test side, on a 31 GB
    # machine. A logistic baseline does not need float64, and nothing here
    # compares bitwise against a float64 fit.
    Xtr, ytr = load_train_xy(a.features, a.splits, dtype=np.float32)
    Xte, te = load_test(a.features, a.splits, dtype=np.float32)
    budgets = (50, 200)

    out = {**generator_provenance(
               __file__,
               inputs=[Path(a.features), Path(a.splits)],
               parameters={"features": a.features, "splits": a.splits,
                           "seed": a.seed}), "seed": a.seed,
           "n_train": len(ytr), "n_test": len(te),
           "categorical_features": CATEGORICAL, "arms": {}}

    full, s_full = fit_arm(Xtr, ytr, Xte, te, FEATURES, a.seed, budgets)
    out["arms"]["full"] = full

    nocat, s_nocat = fit_arm(Xtr[:, keep], ytr, Xte[:, keep], te,
                             [FEATURES[i] for i in keep], a.seed, budgets)
    out["arms"]["no_categorical"] = nocat

    # One-hot over TRAINING values only, plus an "unseen" column. Fitting the
    # vocabulary on train alone is the point: a vocabulary built on the test set
    # is a leak, which is the class of defect this repository exists to catch.
    oh_blocks_tr, oh_blocks_te, vocab = [], [], {}
    for c in CATEGORICAL:
        col = idx[c]
        vals = np.unique(Xtr[:, col])
        vocab[c] = int(vals.size)
        btr = (Xtr[:, [col]] == vals[None, :]).astype(np.float32)
        oh_blocks_tr.append(np.hstack([btr, np.zeros((len(Xtr), 1), np.float32)]))
        bte = (Xte[:, [col]] == vals[None, :]).astype(np.float32)
        unseen = (~bte.any(axis=1)).astype(np.float32)[:, None]
        oh_blocks_te.append(np.hstack([bte, unseen]))
        del btr, bte, unseen
    Xtr_oh = np.hstack([Xtr[:, keep], *oh_blocks_tr])
    del Xtr, oh_blocks_tr                      # 5 GB back before the test side
    Xte_oh = np.hstack([Xte[:, keep], *oh_blocks_te])
    del Xte, oh_blocks_te
    onehot, s_onehot = fit_arm(Xtr_oh, ytr, Xte_oh, te, None, a.seed, budgets)
    del Xtr_oh, Xte_oh
    out["arms"]["onehot"] = onehot
    out["onehot_vocabulary_sizes"] = vocab

    # SEGMENT METRICS FOR EVERY ARM. Pooled levels cannot settle the encoding
    # question on a two-regime window; see `segment_metrics`.
    if a.thin_from:
        import datetime as _dt
        thin = _dt.date.fromisoformat(a.thin_from)
        for name, sc in (("full", s_full), ("no_categorical", s_nocat),
                         ("onehot", s_onehot)):
            out["arms"][name]["by_segment"] = segment_metrics(
                te, sc, budgets, thin)
        out["thin_from"] = a.thin_from
    else:
        out["by_segment_note"] = (
            "NOT COMPUTED: pass --thin-from <YYYY-MM-DD> (the rung's "
            "transaction-volume collapse, from window_decomposition.json). "
            "Without it the arms are only comparable on pooled levels, which "
            "this window does not support.")
    out["wall_clock_sec"] = round(time.time() - t0, 1)

    f = out["arms"]["full"]["average_precision__txn"]
    out["ap_ratio_full_over_no_categorical"] = (
        f / out["arms"]["no_categorical"]["average_precision__txn"])
    out["ap_ratio_full_over_onehot"] = (
        f / out["arms"]["onehot"]["average_precision__txn"])

    d = Path(a.out)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "arms"}, indent=1))
    for name, arm in out["arms"].items():
        print(f"  {name:16s} " + "  ".join(f"{k}={v:.5f}" for k, v in arm.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
