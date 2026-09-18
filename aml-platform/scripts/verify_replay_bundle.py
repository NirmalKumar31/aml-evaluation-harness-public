"""Recompute published metrics from a replay bundle alone, and compare.

A bundle nobody has recomputed anything from is a claim, not evidence. This
reads ONLY the bundle -- no features, no splits, no scores, no 180M rows -- and
rebuilds recall@k, its ceiling and efficiency, precision@k and ring_recall@k,
then diffs them against the manifest the bundle was cut from.

    python scripts/verify_replay_bundle.py --bundle <dir> --manifest <file>

If this passes, "a reviewer can check our numbers on a laptop" is a fact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TOL = 1e-9


def recompute(bundle: Path, budgets) -> dict:
    # THE BUNDLE IS TRUNCATED, AND ASKING PAST THE TRUNCATION IS NOT A
    # QUESTION IT CAN ANSWER. `account_days_topk.parquet` holds each day's
    # top `max_budget` rows plus every ring account-day, so `rank <= b` for
    # b > max_budget silently counts a partial alert set and reports a
    # confident precision from it. `budget_null.py` reads this field twice
    # and reasons explicitly about which days were written in full; this
    # script -- whose docstring promises that passing it makes "a reviewer can
    # check our numbers on a laptop" a fact -- never read it at all.
    meta = json.loads((bundle / "bundle.json").read_text())
    cap = meta.get("max_budget")
    if cap is not None:
        over = [b for b in budgets if b > cap]
        if over:
            raise SystemExit(
                f"budgets {over} exceed this bundle's max_budget={cap}. The "
                f"top-k extract does not contain the rows those budgets would "
                f"alert, so every metric at them would be understated. Pass "
                f"--budgets values <= {cap}.")
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    per_day = pd.read_parquet(bundle / "per_day_positives.parquet")
    total_pos = int(per_day.positive_account_days.sum())

    out = {}
    for b in budgets:
        top = ad["rank"] <= b
        caught = int(((ad.y == 1) & top).sum())
        n_alerts = int(top.sum())
        best = int(np.minimum(per_day.positive_account_days.to_numpy(), b).sum())
        ceiling = best / total_pos
        recall = caught / total_pos
        out[f"recall@{b}"] = recall
        out[f"recall_ceiling@{b}"] = ceiling
        out[f"recall_efficiency@{b}"] = recall / ceiling if ceiling else np.nan
        out[f"precision@{b}"] = caught / n_alerts if n_alerts else np.nan

    mf = bundle / "ring_membership.parquet"
    if mf.exists():
        mem = pd.read_parquet(mf)
        r = mem.merge(ad[["day", "acct", "rank"]], on=["day", "acct"], how="left")
        if r["rank"].isna().any():
            raise SystemExit(
                f"{int(r['rank'].isna().sum())} ring account-days are missing "
                f"from the bundle -- it is not self-sufficient")
        for b in budgets:
            hit = r.groupby("ring_id")["rank"].apply(lambda x, b=b: (x <= b).any())
            out[f"ring_recall@{b}"] = float(hit.mean())
            out[f"n_rings@{b}"] = int(hit.size)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--budgets", default="10,25,50,100,200,500,1000")
    a = ap.parse_args(argv)

    budgets = [int(x) for x in a.budgets.split(",")]
    published = json.loads(a.manifest.read_text())
    published = published.get("metrics", published)
    got = recompute(a.bundle, budgets)

    bad = 0
    compared = []
    print(f"{'metric':34s} {'published':>13s} {'from bundle':>13s}   delta")
    for k in sorted(got):
        want = published.get(k)
        if want is None:
            continue
        compared.append(k)
        delta = abs(float(want) - float(got[k]))
        flag = "" if delta <= TOL else "   <-- MISMATCH"
        bad += delta > TOL
        print(f"{k:34s} {float(want):13.6f} {float(got[k]):13.6f}   "
              f"{delta:.2e}{flag}")
    # COMPARING NOTHING IS NOT PASSING. `want is None` skips a metric the
    # manifest does not publish, which is right -- but when it skipped ALL of
    # them the script still printed "0 mismatch(es)" and exited 0. Asked for
    # budgets no manifest carries, it certified a bundle it had not checked.
    if not compared:
        print(f"\nNOTHING WAS COMPARED. The manifest publishes none of the "
              f"metrics recomputed at budgets {budgets}, so this run verifies "
              f"nothing. Check --manifest and --budgets.")
        return 2
    print(f"\n{len(compared)} metric(s) compared; {bad} mismatch(es)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
