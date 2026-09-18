"""How much of the alert budget is spent twice on one transaction?

THE QUESTION

`to_account_days` emits TWO account-days per transaction -- the sender's and
the receiver's -- and an account-day's score is the max over that account's
transactions that day. So one transaction can consume two review slots.

This project treated that coupling as fatal in one place: `ring_recall`'s
permutation null exists because "a sender and a receiver account-day created by
the same transaction carry the same score", and the first null, which ignored
it, reported a strong ring effect on data with none by construction. The same
coupling sits underneath `precision@k`, `recall@k` and the ceiling.

⚠️ TWO PREVIOUS ANSWERS WERE WRONG, IN DIFFERENT WAYS.

1. A SCORE-TIE PROXY. Grouping alerted account-days by exact `(day, score)` and
   calling each group one transaction. Sender/receiver pairs do share a score,
   but so can unrelated transactions, so the group count is a LOWER bound on
   distinct transactions and the ratio an UPPER bound on the over-counting
   factor. Claims stated as point values on top of it were retracted.

2. AN ENDPOINT JOIN WITH NO SCORE FILTER -- the attempt to replace (1).
   `ring_endpoints` holds one row per (ring transaction, endpoint), so joining
   it to the alerted account-days on `(day, acct)` attaches an account-day to
   EVERY ring transaction that touched the account that day, not to the one
   that supplied its maximum. That inflated the transaction count, and the
   `nunique(rt)` per score group it produced measured "this account-day touches
   several ring transactions", which is a different statement about a different
   thing. The 14-48% figures published from it did not measure score ties at
   all. `ring_transactions.parquet` carries the per-transaction score and the
   script never opened it.

THE DEFINITION NOW, STATED SO IT CAN BE DISAGREED WITH

A ring transaction is the SCORE SOURCE of an alerted account-day iff its own
score equals that account-day's score. The account-day score IS a max over its
transactions, so the supplier's value is bit-identical and exact `==` is the
right test, not a tolerance.

Four cases, and all four are reported rather than assumed away:

  * supplies the max uniquely           -> counted
  * ties with another ring transaction  -> all tied suppliers counted, and the
                                           count of such account-days is
                                           published (`..._with_tied_max`), so
                                           the ambiguity is visible
  * another transaction supplies the max -> NOT counted; the alert is not
                                           attributable to it
  * only one endpoint alerted            -> counted once; the pair count is
                                           published separately

WHAT IS STILL OUT OF REACH

This covers ring transactions only, because they are the only ones whose
identity and score the bundles record. The factor for the full alerted set --
mostly non-ring account-days -- is not measurable from these bundles, and
neither is a transaction-level precision, recall or ceiling.
`make_replay_bundle.py` now emits a transaction-level table for that; every
bundle in the archive predates it.

    python scripts/alert_unit_coupling.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BUDGETS = (50, 200, 1000)


def measure(bundle: Path, budgets=BUDGETS) -> dict:
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    epf, rtf = bundle / "ring_endpoints.parquet", bundle / "ring_transactions.parquet"
    ep = pd.read_parquet(epf) if epf.exists() else None
    rt = pd.read_parquet(rtf) if rtf.exists() else None
    has_txn = "argmax_txn_id" in ad.columns

    # THE ALERTING unit is the account-day; the ring-transaction counts
    # here are consequences of an account-day budget, and are named to say
    # so. Declared because this file exists to study that very coupling.
    out = {"alert_unit": "account-day",
           "estimand": (
               "how many distinct ring TRANSACTIONS an account-day alert "
               "budget actually touches, and how often both endpoints of a "
               "ring transaction are attributable. The alerting unit is the "
               "account-day throughout; the transaction counts are "
               "consequences of that budget, not a second alert unit."),
           "has_transaction_identity": bool(has_txn)}
    for b in budgets:
        top = ad[ad["rank"] <= b]
        if top.empty:
            continue
        g = top.groupby(["day", "score"])
        sizes = g.size()
        labels = g["y"].agg(["min", "max"])

        # (1) THE SCORE-TIE GROUPING, honestly bounded. Kept because it is the
        #     only thing computable for the whole alerted set.
        out[f"alerted_account_days@{b}"] = len(top)
        out[f"tie_groups@{b}"] = int(sizes.size)
        out[f"tie_account_days_per_group@{b}"] = round(len(top) / sizes.size, 4)
        out[f"tie_group_size_histogram@{b}"] = {
            str(k): int(v) for k, v in sizes.value_counts().sort_index().items()}
        out[f"tie_label_discordant_groups@{b}"] = int(
            (labels["min"] != labels["max"]).sum())
        out[f"precision_per_account_day@{b}"] = round(float(top.y.mean()), 5)
        out[f"precision_per_tie_group@{b}"] = round(float(g["y"].max().mean()), 5)

        # (2) RING TRANSACTIONS, ATTRIBUTED BY SCORE SOURCE.
        if ep is None or rt is None:
            continue
        m = ep.merge(rt[["rt", "score"]].rename(columns={"score": "txn_score"}),
                     on="rt", how="left")
        m = m.merge(top[["day", "acct", "score"]], on=["day", "acct"],
                    how="inner")
        if m.empty:
            continue
        out[f"ring_endpoints_in_alerted@{b}"] = len(m)
        # EXACT equality: the account-day score is a max over its own
        # transactions, so its source carries the identical float.
        src = m[m["txn_score"] == m["score"]]
        out[f"ring_endpoints_attributable@{b}"] = len(src)
        out[f"ring_endpoints_not_score_source@{b}"] = len(m) - len(src)
        if src.empty:
            continue
        per_txn = src.groupby(["day", "rt"]).size()
        tied = src.groupby(["day", "acct"])["rt"].nunique()
        out[f"alerting_ring_txns@{b}"] = int(per_txn.size)
        out[f"alerting_ring_txns_with_both_endpoints@{b}"] = int((per_txn == 2).sum())
        # THE PROPORTION, NOT THE IDENTITY.
        #
        # This used to publish `account_days_per_alerting_ring_txn`, which is
        # exactly `1 + both/n` -- a monotone relabelling of the proportion
        # below, published as though it were an independent mean. The ratio is
        # gone; the proportion is the quantity, and it swings 0.624-0.950
        # across bundles because the POPULATION moves, which is the finding.
        out[f"both_endpoint_share@{b}"] = round(
            float((per_txn == 2).sum() / per_txn.size), 4)
        out[f"ring_account_days_with_tied_max@{b}"] = int((tied > 1).sum())
        out[f"ring_account_days_attributed@{b}"] = int(tied.size)
        # The number the previous version got wrong: do score groups actually
        # contain more than one RECORDED ring transaction?
        spans = src.groupby(["day", "score"])["rt"].nunique()
        out[f"ring_score_groups@{b}"] = int(spans.size)
        out[f"ring_score_groups_spanning_multiple_txns@{b}"] = int((spans > 1).sum())

        # (3) The only exact full-set answer, when a bundle carries identity.
        if has_txn:
            pt = top.groupby(["day", "argmax_txn_id"]).size()
            out[f"score_source_ids@{b}"] = int(pt.size)
            out[f"account_days_per_score_source_id@{b}"] = round(
                len(top) / pt.size, 4)
    return out


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    replay = root / "results_archive" / "replay"
    bundles = sorted(p for p in replay.glob("*")
                     if (p / "account_days_topk.parquet").exists())
    if not bundles:
        print(f"no replay bundles under {replay}", file=sys.stderr)
        return 2

    per_bundle = {b.name: measure(b) for b in bundles}
    facts = {
        "_comment": (
            "Alert-unit coupling. `tie_*` groups alerted account-days by exact "
            "(day, score); unrelated transactions can share a score, so "
            "tie_groups is a LOWER bound on distinct transactions and "
            "tie_account_days_per_group is an UPPER bound on the over-counting "
            "factor. `*_ring_txn*` fields attribute an alert to the ring "
            "transaction whose own score EQUALS the account-day maximum -- the "
            "score source -- read from ring_transactions.parquet; an earlier "
            "version joined endpoints without that filter and therefore counted "
            "ring transactions that did not cause the alert. Ring transactions "
            "are the only ones whose identity and score these bundles record, "
            "so nothing here covers the full alerted set, and a "
            "transaction-level precision, recall or ceiling is NOT derivable "
            "from these fields. Earlier attempts at both are retracted."),
        "budgets": list(BUDGETS),
        "bundles": per_bundle,
    }

    from aml.manifest import generator_provenance
    facts.update(generator_provenance(
        __file__,
        inputs=[replay],
        parameters={"budgets": list(BUDGETS)},
        scope=("aml-platform/src", "aml-platform/scripts")))

    out = root / "results_archive/derived/alert_unit_coupling.json"
    out.write_text(json.dumps(facts, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
