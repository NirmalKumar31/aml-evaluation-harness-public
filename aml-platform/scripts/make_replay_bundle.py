"""A few megabytes that let a reviewer recompute every published budget metric.

RP-09. The archive keeps manifests and hashes but not predictions, so checking
a number meant rerunning 179,702,229 rows on a machine most reviewers do not
have. The raw scores are 684 MB per seed and the dataset may not be
redistributed, so committing them is not an option either.

WHAT IS SUFFICIENT, AND WHY IT IS SMALL. Every budget metric here is decided by
per-day ranking against a budget of at most 1000. So:

  * the DAY'S TOP-B account-days fix every rank up to B. Anything ranked below
    B is below B for every budget we report, and its score never needs to be
    known -- only that it lost.
  * every RING-MEMBER account-day, whether or not it made the top B. There are
    8,616 of them on HI-Large. They are what ring_recall is computed over, and
    the permutation null needs the ones that did NOT make it.
  * every RING TRANSACTION with its score and endpoints. That is what the null
    permutes; ~120k rows.
  * per-day positive counts and per-ring sizes -- the denominators.

That is under ten megabytes for a 180M-row run, it contains no transaction
amounts, counterparties or identifiers beyond opaque integer codes, and it is
enough to recompute recall@k, its ceiling and efficiency, precision@k,
ring_recall@k and the permutation null exactly.

    python scripts/make_replay_bundle.py --features F --splits S --scores X \
        --dest results_archive/replay/<name>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAX_BUDGET = 1000


def account_day_table(ad, rk, keep, transaction_unit: bool = False):
    """The shipped account-day table, as a pure function of its inputs.

    Split out of `build` so the SCHEMA can be tested without a dataset. It
    could not be before, and the consequence was that the writer drifted a
    column away from every archived bundle without anything noticing.
    """
    top = pd.DataFrame({
        "day": ad["day"].to_numpy()[keep],
        "acct": ad["acct"].to_numpy()[keep],
        "score": ad["score"].to_numpy()[keep],
        "other_max": ad["other_max"].to_numpy()[keep],
        "y": ad["y"].to_numpy()[keep],
        "rank": rk[keep].astype(np.int32),
    })
    if transaction_unit:
        top["argmax_txn_id"] = ad["argmax_txn_id"].to_numpy()[keep].astype(np.int32)
    return top


def build(features: str, splits: str, scores: str, dest: Path,
          max_budget: int = MAX_BUDGET, transaction_unit: bool = False) -> dict:
    from aml.eval.metrics import _ranks, _ring_structure, to_account_days
    from aml.models.train import load_test

    _, te = load_test(features, splits)
    sc = pd.read_parquet(scores)
    te = te.merge(sc, on="txn_id", how="left", validate="one_to_one")
    if te.score.isna().any():
        raise ValueError("scores and split do not correspond")
    score = te.score.to_numpy()

    # WITH TRANSACTION IDENTITY. Without it the bundle cannot say how many
    # distinct transactions a budget covers, and the score-tie proxy used
    # instead can merge unrelated transactions, so it bounds the count from
    # below rather than estimating it. The id is a positional, dense index: it
    # identifies nothing outside this bundle, like the account codes.
    #
    # `argmax_txn_id` alone does NOT support a transaction-level metric -- see
    # `to_account_days` -- which is why the transaction-level table below
    # exists.
    # OPT-IN WITH THE TABLES IT SERVES, not unconditional.
    #
    # This was always True, so the writer emitted a seventh column that NONE
    # of the nine archived bundles contains: running the documented command
    # today produced a file whose sha256 could never match the bundle.json
    # entry it is checked against, and nothing compared the two. The metric
    # verification still passed, which is what hid it.
    #
    # It is also the licence-consistent default. The comment above says
    # `argmax_txn_id` alone cannot carry a transaction-level metric, and the
    # transaction tables it belongs with are off by default because enlarging
    # an unreviewed disclosure to answer a measurement question is the wrong
    # trade. The column now travels with them.
    ad = to_account_days(te, score, with_txn_id=transaction_unit)
    rk = _ranks(ad)["first"]
    st = _ring_structure(ad)

    keep = rk <= max_budget
    if st is not None:
        keep = keep.copy()
        keep[st["ad_rows"]] = True          # every ring account-day, ranked or not

    top = account_day_table(ad, rk, keep, transaction_unit)

    dest.mkdir(parents=True, exist_ok=True)
    top.to_parquet(dest / "account_days_topk.parquet", index=False)

    # Denominators: the positives that did NOT make the cut still count.
    per_day = (ad.loc[ad.y == 1].groupby("day").size()
               .rename("positive_account_days").reset_index())
    per_day.to_parquet(dest / "per_day_positives.parquet", index=False)

    # ------------------------------------------------------------------
    # A TRANSACTION-LEVEL TABLE, OFF BY DEFAULT.
    #
    # `argmax_txn_id` names which transaction supplied an account-day's score
    # and cannot carry a transaction-level metric on its own: `idxmax` picks
    # arbitrarily among ties, the account-day label is `max(y)` over ALL of the
    # account's transactions rather than that one's own label, and a
    # transaction-level recall needs per-day positive TRANSACTION counts, which
    # nothing else here has. This table supplies all three, so the alert unit
    # can genuinely be varied.
    #
    # ⚠️ OPT-IN, and it stays off until the licence question is settled.
    #
    # It adds up to `max_budget` rows per day per bundle -- roughly 634,000
    # across the nine archived bundles against 526,355 rows disclosed today, so
    # it MORE THAN DOUBLES the row-level footprint -- and every added row
    # carries a per-transaction laundering label, finer-grained than the
    # account-day labels shipped now. Whether any of it may be redistributed
    # under CDLA-Sharing-1.0 is unreviewed. Enlarging an unreviewed disclosure
    # to answer a measurement question is the wrong trade while the question is
    # open, so the default is off and no archived bundle carries it.
    #
    # Which means this repository ships ONE alert unit. Any claim that it
    # offers two would be false.
    files = ["account_days_topk.parquet", "per_day_positives.parquet"]
    if transaction_unit:
        files += _transaction_tables(te, score, dest, max_budget)
    n_ring_txn = 0
    if st is not None:
        mem = ad.attrs["membership"]
        mem.to_parquet(dest / "ring_membership.parquet", index=False)
        ep = ad.attrs["ring_endpoints"]
        rt = ad.attrs["ring_txn"]
        pd.DataFrame({"rt": np.arange(len(rt["score"])),
                      "day": rt["day"], "score": rt["score"]}).to_parquet(
            dest / "ring_transactions.parquet", index=False)
        ep.to_parquet(dest / "ring_endpoints.parquet", index=False)
        files += ["ring_membership.parquet", "ring_transactions.parquet",
                  "ring_endpoints.parquet"]
        n_ring_txn = len(rt["score"])

    from aml.manifest import generator_provenance, sha256_file
    # A LOGICAL SOURCE ID, not the path it happened to sit at.
    #
    # Bundles recorded `source_scores: /scratch/large/gold/sorted_lgbm_s0/...`
    # -- a VM scratch mount that exists nowhere else. It identified the run for
    # nobody but the machine that made it, and shipped the deployment layout
    # into a public artifact. The last two path components name the lineage and
    # the file, which is the part that means something.
    src = pathlib.PurePath(str(scores))
    # WHAT MADE THIS, NOT JUST WHICH COMMIT.
    #
    # Bundles recorded a commit and nothing else -- no generator script or
    # hash, no dataset identity, no identity for the score set the extract came
    # from. They recompute the published metrics exactly, which is the hard
    # part, and they could not say what they were an extract OF.
    pin = Path(__file__).resolve().parents[1] / "results_archive/derived/dataset_pin.json"
    meta = {
        "bundle_schema_version": 3,
        **generator_provenance(
            __file__,
            inputs=[Path(features), Path(splits), Path(scores)],
            parameters={"max_budget": max_budget}),
        "dataset_pin_sha256": sha256_file(pin) if pin.is_file() else None,
        "status": "ok",
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "max_budget": max_budget,
        # THE SCHEMA, RECORDED. `bundle_schema_version` was a number with
        # nothing behind it; a regression test now compares this list to what
        # the writer actually produces, so code and archive cannot drift
        # apart again in silence.
        "account_day_columns": list(top.columns),
        "source_scores": "/".join(src.parts[-2:]),
        "source_lineage": src.parts[-2] if len(src.parts) > 1 else None,
        "n_account_days_total": len(ad),
        "n_account_days_kept": int(keep.sum()),
        "n_positive_account_days": int((ad.y == 1).sum()),
        "n_rings": int(st["n_rings"]) if st else 0,
        "n_ring_account_days": int(st["ad_rows"].size) if st else 0,
        "n_ring_transactions": int(n_ring_txn),
        # THE NOTE MUST DESCRIBE THIS BUNDLE, not the capability set.
        # It claimed "at the account-day unit AND at the transaction unit"
        # unconditionally, while the transaction tables are opt-in and off --
        # so every bundle written by default asserted a unit it does not carry.
        "transaction_unit": bool(transaction_unit),
        "note": ("Sufficient to recompute every budget metric for "
                 f"k <= {max_budget} at the account-day unit"
                 + (" AND at the transaction unit" if transaction_unit
                    else "; the transaction-level tables are NOT included")
                 + ". Account ids are opaque dense codes assigned by "
                 "load_test; `argmax_txn_id`"
                 + (" and `txn_idx`" if transaction_unit else "")
                 + " are positional indices into the test frame. None "
                 "identifies anything outside this bundle. No amounts, "
                 "counterparties or timestamps beyond the calendar day are "
                 "included."),
        # STATED AT THE STRENGTH THE ANALYSIS SUPPORTS, and it used to be
        # stated higher. This field read "...so this redistributes no part of
        # the CDLA-licensed dataset", which is a legal conclusion, asserted as
        # fact, in a machine-readable field -- while DATA_LICENSE.md called the
        # very same question an unreviewed interpretation. Two documents in one
        # repository cannot disagree about whether something has been decided.
        "licence_status": "UNREVIEWED. These are row-level outputs derived from "
                          "the IBM AMLworld dataset (day, opaque account code, "
                          "label, score, rank, opaque transaction index, "
                          "ring linkage"
                          + (", per-transaction score and label"
                             if transaction_unit else "")
                          + "). The project position is "
                          "that they are CDLA 'Results' rather than "
                          "redistributed data, and that position has NOT been "
                          "reviewed by a lawyer. See DATA_LICENSE.md. Do not "
                          "rely on this field as a permission.",
        "files": {f: {"sha256": sha256_file(dest / f),
                      "bytes": (dest / f).stat().st_size} for f in files},
    }
    (dest / "bundle.json").write_text(json.dumps(meta, indent=1))
    return meta


def _transaction_tables(te, score, dest: Path, max_budget: int) -> list[str]:
    """Per-day top-k transactions and per-day positive-transaction counts.

    TIE POLICY, PUBLISHED RATHER THAN ASSUMED AWAY -- the same discipline the
    account-day path has. `rank` resolves ties by row order, which carries no
    meaning, so `rank_min`/`rank_max` bracket what any tie-breaking rule could
    return. An earlier version of this table shipped `rank` alone, which
    reintroduces exactly the arbitrary choice `recall_tie_optimistic@k` exists
    to expose.
    """
    txn = pd.DataFrame({
        "day": te.event_date.to_numpy(),
        "txn_idx": np.arange(len(te), dtype=np.int32),
        "score": score,
        "y": te.is_laundering.to_numpy(),
    })
    g = txn.groupby("day")["score"]
    r_first = g.rank(ascending=False, method="first").to_numpy()
    r_min = g.rank(ascending=False, method="min").to_numpy()
    r_max = g.rank(ascending=False, method="max").to_numpy()

    keep = r_min <= max_budget          # keep every member of a straddling tie
    out = txn[keep].copy()
    out["rank"] = r_first[keep].astype(np.int32)
    out["rank_min"] = r_min[keep].astype(np.int32)
    out["rank_max"] = r_max[keep].astype(np.int32)
    out.to_parquet(dest / "transactions_topk.parquet", index=False)

    per_day = (txn.loc[txn.y == 1].groupby("day").size()
               .rename("positive_transactions").reset_index())
    per_day.to_parquet(dest / "per_day_positive_transactions.parquet",
                       index=False)
    return ["transactions_topk.parquet", "per_day_positive_transactions.parquet"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--splits", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--dest", required=True, type=Path)
    ap.add_argument("--max-budget", type=int, default=MAX_BUDGET)
    ap.add_argument("--transaction-unit", action="store_true",
                    help="also emit the transaction-level tables. OFF by "
                         "default: they roughly double the row-level "
                         "disclosure and add per-transaction labels, and the "
                         "CDLA status of the existing rows is unreviewed. See "
                         "DATA_LICENSE.md before turning this on.")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()
    meta = build(a.features, a.splits, a.scores, a.dest, a.max_budget,
                 transaction_unit=a.transaction_unit)
    total = sum(f["bytes"] for f in meta["files"].values())
    print(json.dumps({k: v for k, v in meta.items() if k != "files"}, indent=1))
    print(f"bundle: {total/1e6:.2f} MB from {meta['n_account_days_total']:,} "
          f"account-days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
