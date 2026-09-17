"""Per-day transaction volume and laundering prevalence across the test window.

THE QUANTITY ELEVEN AUDIT ROUNDS NEVER RECORDED.

Every budget metric in this project is a per-day top-k statistic, so its value
depends on how many transactions each day actually holds. That number appears
nowhere: not in `README.md`, not in `docs/LIMITATIONS.md`, not in
`paper/RESULTS_*.md`, not in any manifest. Eleven rounds documented the
collapse in positive ACCOUNT-DAYS across the window and never asked about the
denominator.

It matters because AMLworld's generator winds down. On HI-Medium the first
seven test days carry millions of transactions at roughly 0.1% laundering; the
last twelve carry a few thousand at 40-60%. Those are not the same detection
problem, and pooling them produces a headline that is mostly the second one.

    `sum_d min(P_d, B)` caps the busy days at B and lets the thin days
    contribute their whole (small) count, so the ATTAINABLE positives are
    majority-tail even though the POSITIVES are 81% front-loaded.

This script measures both halves: the volume/prevalence profile from the raw
file, and the decomposition of each shipped replay bundle's alerts and true
positives by window segment. Both are needed to read any published budget
number.

    python scripts/window_volume.py                 # HI-Medium + HI-Small
    python scripts/window_volume.py --variant Small
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The segment boundary is DATA-DRIVEN, not chosen: it is the first day whose
# transaction count falls below this fraction of the window median. Stating the
# rule rather than the date keeps it honest if the window ever changes.
COLLAPSE_FRACTION = 0.01


def volume_profile(csv: Path) -> dict:
    """Read the raw file with THE PROJECT'S OWN SCHEMA, not a re-derived one.

    An earlier version of this function re-parsed the header with
    `read_csv_auto` and its own `strptime` format, which is a second
    implementation of something `aml.schema` already defines -- exactly the
    "reconstruct instead of reuse the primitive" pattern that produced three
    retracted definitions of the alert unit.
    """
    import duckdb

    from aml import schema

    cols = ", ".join(f"'{n}': '{t}'" for n, t in schema.COLUMNS)
    con = duckdb.connect()
    q = f"""
        SELECT CAST(event_time AS DATE)        AS day,
               count(*)                        AS transactions,
               sum(is_laundering)              AS laundering
        FROM read_csv('{csv.as_posix()}',
                      header = false, skip = 1,
                      columns = {{{cols}}},
                      timestampformat = '{schema.TIMESTAMP_FORMAT}')
        GROUP BY 1 ORDER BY 1
    """
    df = con.execute(q).fetchdf()
    df["prevalence"] = df.laundering / df.transactions
    med = float(df.transactions.median())
    thin = df[df.transactions < COLLAPSE_FRACTION * med]
    first_thin = str(thin.day.min()) if len(thin) else None
    return {
        "days": len(df),
        "transactions_total": int(df.transactions.sum()),
        "laundering_total": int(df.laundering.sum()),
        "median_transactions_per_day": med,
        "collapse_fraction": COLLAPSE_FRACTION,
        "first_thin_day": first_thin,
        "per_day": [
            {"day": str(r.day), "transactions": int(r.transactions),
             "laundering": int(r.laundering), "prevalence": round(r.prevalence, 6)}
            for r in df.itertuples()],
    }


def bundle_decomposition(bundle: Path, profiles: dict, budgets=(50, 200)) -> dict:
    """Split a bundle's alerts, true positives and ceiling by window segment.

    SEGMENTED ON TRANSACTION VOLUME, which is the variable that collapses.

    An earlier version of this function segmented on the per-day POSITIVE
    count, which declines gradually (2737 -> 940 -> 738 -> ... -> 4) and put
    the boundary twelve days in. Transactions do not decline; they fall off a
    cliff -- 3,021,866 on 09-16 to 2,020 on 09-17, with prevalence going
    0.0008 -> 0.5936 overnight. Those are the two halves that matter, and
    choosing the boundary from the smoother series hides the thing being
    measured. Segmenting on the wrong variable is how this file's own first
    draft understated the effect.

    The boundary comes from the matching raw-volume profile, joined by day
    range, so it is a measured property of the generator rather than a date
    typed in here.
    """
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    per = pd.read_parquet(bundle / "per_day_positives.parquet").sort_values("day")
    # EVERY DAY THE BUNDLE ALERTS ON, not only the days that hold a positive.
    #
    # `per_day_positives` omits days with zero positives, so segmenting on its
    # index left 105 alerted account-days at HI-Large in neither half -- caught
    # by the partition assertion below rather than published as a silent
    # undercount. The day axis is the union, with zero filled in.
    counts = (pd.Series(per.positive_account_days.to_numpy(),
                        index=pd.to_datetime(per.day).dt.date)
              .reindex(sorted(set(pd.to_datetime(ad.day).dt.date)
                              | set(pd.to_datetime(per.day).dt.date)),
                       fill_value=0))
    P = counts.to_numpy()
    days_all = list(counts.index)

    # The boundary: the matching profile's first thin day, if one of the
    # profiles covers this bundle's window.
    # MATCHED BY NAME, THEN VALIDATED BY DATE RANGE.
    #
    # Matching purely on "the bundle's days are a subset of the profile's"
    # picked HI-Medium for `small_gbdt_s0`, because the HI-Small window
    # (09-05..09-18) sits inside the HI-Medium calendar (09-01..09-28). The
    # rungs are independent generator runs that happen to share dates, so a
    # date-containment test cannot tell them apart. The bundle name carries the
    # rung; the date check then has to agree, or this raises.
    boundary, source = None, "none"
    rung = next((v for v in profiles if v.lower() in bundle.name.lower()), None)
    if rung and profiles[rung].get("first_thin_day"):
        prof = profiles[rung]
        pdays = {pd.Timestamp(r["day"]).date() for r in prof["per_day"]}
        missing = set(days_all) - pdays
        if missing:
            raise RuntimeError(
                f"{bundle.name} names rung {rung} but has {len(missing)} day(s) "
                f"outside that profile, e.g. {sorted(missing)[:3]}")
        boundary = pd.Timestamp(prof["first_thin_day"]).date()
        source = f"HI-{rung} transaction-volume collapse"
    if boundary is not None:
        drop = next((i for i, d in enumerate(days_all) if d >= boundary),
                    len(days_all))
    else:
        # No profile covers this window (the raw file is absent). Fall back to
        # the positive-count decline and SAY SO, rather than presenting a
        # different boundary as if it were the same one.
        below = np.less(P, 0.1 * P.max())
        drop = int(below.argmax()) if below.any() else len(P)
        source = "fallback: positive-count decline (raw volume unavailable)"
    # NORMALISED TO DATES ON BOTH SIDES. The first version compared
    # `str(Timestamp)` against `ad.day.astype(str)`, which render differently
    # ("2022-09-15 00:00:00" vs "2022-09-15"), so every membership test was
    # False and every count came out zero. A join whose key formats disagree is
    # the defect class this whole file exists to document; the assertion below
    # is what makes it impossible to ship silently.
    head, tail = set(days_all[:drop]), set(days_all[drop:])

    out = {"segment_boundary_index": drop,
           "segment_boundary_day": str(days_all[drop]) if drop < len(days_all) else None,
           "segment_boundary_source": source,
           "head_days": len(head), "tail_days": len(tail),
           "positive_account_days_head": int(P[:drop].sum()),
           "positive_account_days_tail": int(P[drop:].sum())}
    ad = ad.assign(_d=pd.to_datetime(ad.day).dt.date)
    for b in budgets:
        top = ad[ad["rank"] <= b]
        tp = top[top.y == 1]
        ah = int(top._d.isin(head).sum())
        at = int(top._d.isin(tail).sum())
        th = int(tp._d.isin(head).sum())
        tt = int(tp._d.isin(tail).sum())
        ch = int(pd.Series(P[:drop]).clip(upper=b).sum())
        ct = int(pd.Series(P[drop:]).clip(upper=b).sum())
        # THE SEGMENTS MUST PARTITION THE ALERTS. If the day keys ever stop
        # matching, this fails instead of reporting zeros.
        if ah + at != len(top):
            raise RuntimeError(
                f"{bundle.name}: head+tail alerts {ah}+{at} != {len(top)} at "
                f"k={b}; the day keys do not match between the bundle's "
                f"account-day table and its per-day positives")
        if th + tt != len(tp):
            raise RuntimeError(
                f"{bundle.name}: head+tail true positives do not partition")
        out.update({
            f"alerts_head@{b}": ah, f"alerts_tail@{b}": at,
            f"true_positives_head@{b}": th, f"true_positives_tail@{b}": tt,
            f"true_positive_share_tail@{b}": round(tt / (th + tt), 5) if th + tt else None,
            f"ceiling_count_head@{b}": ch, f"ceiling_count_tail@{b}": ct,
            f"ceiling_share_tail@{b}": round(ct / (ch + ct), 5) if ch + ct else None,
            f"precision_head@{b}": round(th / ah, 5) if ah else None,
            f"precision_tail@{b}": round(tt / at, 5) if at else None,
            f"precision_pooled@{b}": round(len(tp) / len(top), 5) if len(top) else None,
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", action="append", default=None,
                    help="Medium, Small; default both when the CSV is present")
    a = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    variants = a.variant or ["Medium", "Small"]

    profiles, inputs = {}, []
    for v in variants:
        csv = root / f"data/HI-{v}_Trans.csv"
        if not csv.exists():
            print(f"  {csv.name} not present; skipping volume profile", file=sys.stderr)
            continue
        profiles[v] = volume_profile(csv)
        inputs.append(csv)

    replay = root / "results_archive" / "replay"
    bundles = {p.name: bundle_decomposition(p, profiles)
               for p in sorted(replay.glob("*"))
               if (p / "account_days_topk.parquet").exists()}
    if bundles:
        inputs.append(replay)

    facts = {
        "_comment": (
            "Per-day transaction volume and laundering prevalence across the "
            "test window, and the decomposition of each replay bundle's alerts "
            "and true positives by window segment. Every budget metric in this "
            "project is a per-day top-k statistic, so both are required to read "
            "one. The segment boundary is data-driven: the first day whose "
            "TRANSACTION count falls below 1% of the window median, read from "
            "the rung's own volume profile. An earlier version of this string "
            "described a positive-count rule the code had already abandoned "
            "for understating the effect -- and the publication gate passed it, "
            "because the gate checks numbers and not prose. Where the raw file "
            "is absent the positive-count fallback is used and "
            "`segment_boundary_source` says so."),
        "volume_profile": profiles,
        "bundle_decomposition": bundles,
    }
    from aml.manifest import generator_provenance
    facts.update(generator_provenance(
        __file__, inputs=inputs,
        parameters={"variants": variants, "collapse_fraction": COLLAPSE_FRACTION},
        scope=("aml-platform/src", "aml-platform/scripts")))

    out = root / "results_archive/derived/window_decomposition.json"
    out.write_text(json.dumps(facts, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
