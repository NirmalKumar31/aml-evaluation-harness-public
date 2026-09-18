"""What a random ranker scores at the same budget, ON THE EVALUATED POPULATION.

⚠️ THE FIRST VERSION OF THIS SCRIPT COMPARED TWO DIFFERENT POPULATIONS, and
the conclusion it produced was the reverse of the truth.

It read every post-cut transaction straight from the raw CSV and applied only
the date cut. But the models are evaluated on the **ring-aware** test split,
which drops 736 of 1,265 test rings (58.18%) to keep ring participants out of
both sides. Measured against `results_archive/gold/splits_Medium/manifest.json`:

    positive account-days      raw date-cut 30,867   evaluated split 18,130
    total account-days              6,208,448              6,204,374
    alert slots at k=50                   876                    864
    ceiling count at k=50                 876                    858

A 70% inflation of the positive class inflates a prevalence-weighted null, so
the script reported `null_precision@50 = 0.60209` and the repository published
"the headline is below chance". On the evaluated population the null is lower
and the headline is **above** chance. Every lift computed from the old artifact
is withdrawn; see `results_archive/RETRACTED.json`.

WHERE THE POPULATION COMES FROM NOW

The replay bundles ARE the evaluated split, so:

  * per-day positives come from `per_day_positives.parquet` and must sum to the
    split manifest's `test_positive_account_days`, asserted below;
  * per-day `N_d` is exact only where the bundle PROVABLY wrote the day in
    full -- its highest rank is strictly below the bundle's `max_budget` cap,
    so nothing can have been dropped. That is 10 of 19 days on HI-Medium;
  * on every other day `N_d` is bracketed between `max(highest rank written,
    P_d, raw count - the window's total removal)` and the raw count, because
    the ring-aware split only removes account-days. `n_d_source` records which
    route each day used.

    The criterion used to be `count == max(rank)`, "the ranks written are
    contiguous". A day truncated at exactly the cap satisfies it: 2022-09-18
    wrote 1,000 rows topping out at rank 1,000, and the old rule called that
    exact at N_d = 1,000, publishing a prevalence of 0.738 for a day whose
    prevalence is only bracketed to [0.503, 0.738] -- i.e. it asserted the
    most adverse end of its own bracket -- and on 2022-09-17 it let the
    lower bound fall to 940 on a day the bundle records a rank of 1,026 for,
    which is not a bound but a contradiction. Cap length is the one length at
    which contiguity proves nothing.

AND THE NULL IS REPORTED WITH UNCERTAINTY. A random ranker's true positives on
day d are Hypergeometric(N_d, P_d, k_d); the per-day variances add. An
"above/below chance" claim needs an interval, not a point.

    python scripts/budget_null.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BUDGETS = (50, 200)


def raw_account_days(csv: Path) -> pd.DataFrame:
    """Per-day account-day and positive counts from the raw file.

    Used ONLY to bound `N_d`. The positives come from the bundle, because the
    raw file's positives include the 736 dropped test rings -- the mistake the
    first version of this script made everywhere.
    """
    import duckdb

    from aml import schema

    cols = ", ".join(f"'{n}': '{t}'" for n, t in schema.COLUMNS)
    q = f"""
        WITH t AS (
            SELECT CAST(event_time AS DATE) AS day,
                   sender_bank   || '_' || sender_account   AS s,
                   receiver_bank || '_' || receiver_account AS r,
                   is_laundering
            FROM read_csv('{csv.as_posix()}', header = false, skip = 1,
                          columns = {{{cols}}},
                          timestampformat = '{schema.TIMESTAMP_FORMAT}')
        ), ad AS (
            SELECT day, s AS acct, max(is_laundering) AS y FROM t GROUP BY 1, 2
            UNION ALL
            SELECT day, r AS acct, max(is_laundering) AS y FROM t GROUP BY 1, 2
        ), dedup AS (
            SELECT day, acct, max(y) AS y FROM ad GROUP BY 1, 2
        )
        SELECT day, count(*) AS n_account_days FROM dedup GROUP BY 1 ORDER BY 1
    """
    return duckdb.connect().execute(q).fetchdf()


def _split_metrics(root: Path, variant: str) -> dict:
    m = root / f"results_archive/gold/splits_{variant}/manifest.json"
    if not m.exists():
        return {}
    d = json.loads(m.read_text())
    return {**d.get("metrics", {}), "cut_time": d.get("config", {}).get("cut_time")}


def evaluated_population(bundle: Path, raw_profile: pd.DataFrame,
                         removed: int) -> pd.DataFrame:
    """Per-day (P_d, N_d bounds) for the population the models were scored on.

    P_d is exact: the bundle's `per_day_positives` IS the evaluated split's
    per-day positive account-day count. N_d is exact only where the bundle
    PROVABLY did not truncate the day, and otherwise bracketed:

        lower bound = max(highest rank written, P_d, raw_N - total removal)
        upper bound = the RAW per-day account-day count

    because the ring-aware split only ever REMOVES account-days, so the split's
    N_d cannot exceed the raw count.

    WHEN IS N_d EXACT? The bundle writes every account-day ranked at or under
    `max_budget`, plus every ring account-day whatever its rank. So the day was
    written in full if and only if its highest rank is BELOW `max_budget`: then
    no row can have been dropped, because a dropped row would have had to rank
    above a cap the day never reached.

    The previous criterion was `kept == max_rank`, i.e. "the ranks written are
    contiguous". That is satisfied by a truncated day too: on 2022-09-18 the
    bundle wrote exactly 1,000 rows with a highest rank of 1,000, which is the
    cap -- the day could hold 1,000 account-days or 200,000, and the bundle
    cannot tell you which. The old rule declared N_d = 1,000 exactly, publishing
    a prevalence of 0.178 for a day whose prevalence could be anything down to
    0.0009. A cap-length day is the one case where contiguity proves nothing.
    """
    cap = json.loads((bundle / "bundle.json").read_text())["max_budget"]
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    per = pd.read_parquet(bundle / "per_day_positives.parquet")
    ad = ad.assign(_d=pd.to_datetime(ad.day).dt.date)
    per = per.assign(_d=pd.to_datetime(per.day).dt.date)

    g = ad.groupby("_d").agg(kept=("rank", "size"), mx=("rank", "max"))
    pos = dict(zip(per._d, per.positive_account_days, strict=False))
    raw_ad = {pd.Timestamp(r.day).date(): int(r.n_account_days)
              for r in raw_profile.itertuples()}

    # HOW MUCH THE SPLIT CAN HAVE REMOVED FROM ANY ONE DAY.
    #
    # The ring-aware filter only ever removes account-days, so the split's N_d
    # is at most the raw count. And it removed `removed` account-days over the
    # WHOLE window, so no single day can be lower than its raw count minus
    # that total. A first attempt used "rows the bundle kept" as the lower
    # bound; on a busy day the bundle keeps ~1,100 rows while the day holds
    # ~1,400 positives, so it produced prevalence above 1 and a vacuous
    # bracket.
    #
    # THE HIGHEST RANK WRITTEN IS ALSO A LOWER BOUND, and a much stronger one
    # on the thinning days: observing a row at rank 1,030 proves the day held
    # at least 1,030 account-days. Omitting it let the bracket open below a
    # rank the bundle itself records -- N_d as low as 197 on a day carrying a
    # rank of 1,030 -- which is not a bound, it is a contradiction.
    rows = []
    for d, r in g.iterrows():
        pdv, mx = int(pos.get(d, 0)), int(r.mx)
        n_raw = raw_ad.get(d)
        if mx < cap:
            lo = hi = mx
            src = f"exact (highest rank {mx} is below the cap of {cap}, so the "
            src += "day was written in full)"
        elif n_raw is None:
            # Silently dropping the day was wrong: it removes a day from the
            # null's denominator that the metric it is compared against still
            # pools over, so the two sides stop sharing a population.
            raise RuntimeError(
                f"day {d} reached the bundle cap ({mx} >= {cap}) so N_d must be "
                "bracketed against the raw per-day count, and the raw volume "
                "profile has no row for it. The null cannot be computed on a "
                "population the profile does not cover.")
        else:
            hi = n_raw
            lo = max(mx, pdv, n_raw - removed)
            src = (f"bounded (raw {n_raw}, highest rank {mx}, "
                   f"window removal {removed})")
        if lo > hi:
            raise RuntimeError(
                f"day {d}: N_d lower bound {lo} exceeds the raw count {hi}. "
                "The bundle and the raw profile disagree about the population.")
        rows.append({"day": str(d), "n_positive": pdv,
                     "n_d_low": int(lo), "n_d_high": int(hi),
                     "n_d_source": src})
    return pd.DataFrame(rows)


def null_bounds(pop: pd.DataFrame, thin_from, budgets=BUDGETS) -> dict:
    """Random-ranker expectation, bracketed, with hypergeometric spread.

    The per-day contribution `k_d * P_d / N_d` DECREASES in N_d, so the
    smallest admissible N_d gives the highest null and vice versa. Both are
    reported; a claim of "above chance" has to clear the high end.
    """
    day = pd.to_datetime(pop["day"]).dt.date.to_numpy()
    P = pop["n_positive"].to_numpy().astype(float)
    head = day < thin_from
    out = {"alert_unit": "account-day",
           # WHAT THIS NUMBER IS, stated in the artifact rather than inferred
           # from its key. Provenance cannot detect a wrong estimand, and this
           # project spent a day proving that: a table of lifts traced
           # correctly to a real artifact while measuring transactions where
           # the headline measured account-days.
           "estimand": (
               "the precision@k a UNIFORMLY RANDOM ranker attains on the "
               "evaluated ring-aware test split -- the slot-weighted mean of "
               "daily account-day prevalence, bracketed because a truncated "
               "day bounds its population rather than fixing it. It is a "
               "property of the SPLIT, not of any model."),
           "days": len(P), "head_days": int(head.sum()),
           "tail_days": int((~head).sum()), "thin_from": str(thin_from),
           "n_positive_total": int(P.sum())}

    for b in budgets:
        for tag, Ncol in (("high", "n_d_low"), ("low", "n_d_high")):
            N = pop[Ncol].to_numpy().astype(float)
            k = np.minimum(b, N)
            exp_tp = k * (P / N)
            for lab, m in (("", slice(None)), ("_head", head), ("_tail", ~head)):
                kk = k[m]
                if kk.sum() == 0:
                    continue
                out[f"null_precision_{tag}@{b}{lab}"] = round(
                    float(exp_tp[m].sum() / kk.sum()), 5)
            # Hypergeometric spread on the pooled count, at this bound.
            #
            # ⚠️ AN UNDERSTATEMENT, AND BY A KNOWN MECHANISM. The
            # hypergeometric assumes k slots drawn without replacement from N
            # EXCHANGEABLE units. They are not exchangeable: one transaction
            # emits two account-days that share a score, so alerts arrive in
            # correlated pairs. Measured on `medium_gbdt_s0` at k=50, 754 of
            # 761 true-positive alerts have their counterpart alerted too.
            # Positive correlation between co-alerted units INFLATES the true
            # variance, so the sd below is a lower bound on the null's spread
            # -- the optimistic direction for an "above chance" claim.
            #
            # This is the same coupling that `ring_recall` has a permutation
            # null for. It is not fixed here because the fix is a permutation
            # null for `precision@k` too, which needs the day's full score
            # vector rather than the bundle's top-k; stating the direction is
            # what can honestly be done from the archive.
            frac = np.clip(P / N, 0.0, 1.0)
            var = (k * frac * (1 - frac)
                   * np.where(np.greater(N, 1), (N - k) / np.maximum(N - 1, 1), 0.0))
            out[f"null_precision_{tag}_sd@{b}"] = round(
                float(np.sqrt(var.sum()) / k.sum()), 6)
            out[f"null_precision_{tag}_sd_is_a_lower_bound@{b}"] = True
        N = pop["n_d_high"].to_numpy().astype(float)
        k = np.minimum(b, N)
        out[f"alert_slots@{b}"] = int(k.sum())
        out[f"ceiling_count@{b}"] = int(np.minimum(P, b).sum())
        out[f"ceiling_budget_limited@{b}"] = int(
            np.where(np.greater(P, b), b, 0.0).sum())
        out[f"ceiling_positive_limited@{b}"] = int(
            np.where(np.less_equal(P, b), P, 0.0).sum())
        nb = np.less_equal(N, b)
        out[f"nonbinding_days@{b}"] = int(nb.sum())
        out[f"nonbinding_day_list@{b}"] = [str(d) for d in day[nb]]
    return out


def nonbinding_from_bundle(bundle: Path, budgets=(10, 50, 200)) -> dict:
    """Non-binding days for one bundle, WITHOUT the raw file.

    A day is non-binding at budget k when it holds no more account-days than
    k. Every ranker then alerts that day's entire population, so precision on
    it equals its prevalence for any ranker and it carries no information
    about the ranking at all -- which is why this project's own rule is to
    exclude such days and bracket rather than point (`docs/LIMITATIONS.md`
    section 1).

    THAT RULE WAS APPLIED TO TWO RUNGS AND NOT TO THE THIRD. `null_bounds`
    runs only where the raw CSV is present, because bounding N_d on a
    TRUNCATED day needs it -- so HI-Large, whose raw file is 18 GB and is not
    kept, had no non-binding accounting in any artifact or any document. It is
    the worst of the three rungs (28 of 97 days at k=50, carrying 16.2% of
    every alert) and it supplies six of the nine archived bundles.

    Identifying non-binding days needs no raw file. The bundle holds each
    day's top `max_budget` rows plus every ring account-day, so a day whose
    highest rank is strictly BELOW the cap was written in full and its N_d is
    exactly that highest rank -- the same rule this module already states. At
    k equal to the cap the question is not answerable, which is why the
    budgets here stay under it and the truncated days are counted separately.
    """
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    cap = json.loads((bundle / "bundle.json").read_text())["max_budget"]
    mx = ad.groupby("day")["rank"].max()
    n_days = int(mx.size)
    out = {
        "alert_unit": "account-day",
        "n_days": n_days,
        "max_budget": cap,
        "days_provably_written_in_full": int((mx < cap).sum()),
        "days_truncated_at_the_cap": int((mx >= cap).sum()),
        "rule": "a day is non-binding at k when N_d <= k; N_d is known only "
                "for days whose highest rank is strictly below max_budget, so "
                "budgets at or above the cap are not reported",
    }
    pos = pd.read_parquet(bundle / "per_day_positives.parquet")
    total_pos = int(pos.positive_account_days.sum())
    for b in budgets:
        if b >= cap:
            continue
        nb = mx[mx <= b]
        days = set(nb.index)
        alerts_all = int((ad["rank"] <= b).sum())
        # On a non-binding day every account-day is alerted, so the day's own
        # contribution is its whole population.
        alerts_nb = int(nb.sum())
        p_nb = int(pos[pos.day.isin(days)].positive_account_days.sum())
        out[f"nonbinding_days@{b}"] = int(nb.size)
        out[f"nonbinding_day_share@{b}"] = round(nb.size / n_days, 5)
        out[f"nonbinding_alert_share@{b}"] = (
            round(alerts_nb / alerts_all, 5) if alerts_all else None)
        out[f"nonbinding_positive_share@{b}"] = (
            round(p_nb / total_pos, 5) if total_pos else None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", action="append", default=None)
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    win = json.loads(
        (root / "results_archive/derived/window_decomposition.json").read_text())

    # One representative bundle per rung: the population is a property of the
    # split, not of the model, so any bundle from that rung carries it.
    pick = {"Medium": "medium_baseline_s0", "Small": "small_gbdt_s0"}
    facts, inputs = {}, []
    for v in (a.variant or ["Medium", "Small"]):
        bundle = root / "results_archive/replay" / pick.get(v, "")
        if not bundle.is_dir() or v not in win["volume_profile"]:
            print(f"  HI-{v}: no bundle or profile, skipped", file=sys.stderr)
            continue
        sm = _split_metrics(root, v)
        csv = root / f"data/HI-{v}_Trans.csv"
        if not csv.exists():
            print(f"  HI-{v}: raw file absent, cannot bound N_d", file=sys.stderr)
            continue
        raw = raw_account_days(csv)
        cut = pd.Timestamp(sm["cut_time"]).date()
        raw = raw[pd.to_datetime(raw.day).dt.date >= cut].reset_index(drop=True)
        removed = int(raw.n_account_days.sum()) - int(sm["test_total_account_days"])
        pop = evaluated_population(bundle, raw, max(removed, 0))

        # POPULATION IDENTITY, ASSERTED. The previous version of this script
        # silently used a different population from the one evaluated.
        want = sm.get("test_positive_account_days")
        if want is not None and int(pop.n_positive.sum()) != int(want):
            raise RuntimeError(
                f"HI-{v}: population mismatch -- summed {int(pop.n_positive.sum())} "
                f"positive account-days, split manifest says {want}. The null "
                f"must be computed on the evaluated split.")

        thin = pd.Timestamp(win["volume_profile"][v]["first_thin_day"]).date()
        facts[v] = null_bounds(pop, thin)
        facts[v]["split_manifest"] = {
            k: sm.get(k) for k in ("test_positive_account_days",
                                   "test_total_account_days", "dropped_rings",
                                   "test_rings_kept", "cut_time")}
        cap = json.loads((bundle / "bundle.json").read_text())["max_budget"]
        facts[v]["population_source"] = (
            f"positives EXACT from replay bundle {pick[v]}; N_d exact only on "
            f"days whose highest written rank is below the bundle cap of {cap}, "
            f"else bracketed between max(highest rank, P_d, raw count - the "
            f"window's total removal of {max(removed, 0)} account-days) and the "
            f"raw count")
        facts[v]["per_day"] = pop.to_dict("records")
        inputs.append(bundle)
        inputs.append(csv)
        inputs.append(root / f"results_archive/gold/splits_{v}/manifest.json")

    if not facts:
        print("no rung could be processed", file=sys.stderr)
        return 2

    doc = {
        "_comment": (
            "Random-ranker expectations for the budget metrics, computed on the "
            "EVALUATED ring-aware test split. An earlier version read the raw "
            "CSV with only a date cut, which included the 736 dropped test "
            "rings -- 30,867 positive account-days against the evaluated "
            "18,130 -- and so reported a null far too high. Values are "
            "BRACKETED: per-day positives are exact from the bundle, N_d is "
            "exact only where the day's highest written rank is BELOW the "
            "bundle's top-k cap -- proof that nothing was dropped -- and "
            "otherwise bounded between the highest rank written and the raw "
            "per-day count, because the split only removes account-days. A day "
            "truncated at exactly the cap is NOT exact, however contiguous its "
            "ranks look. `null_precision_high` is the "
            "adverse bound; an 'above chance' claim must clear it. "
            "`*_sd` is the hypergeometric standard deviation of the pooled "
            "count. `nonbinding_day_list@k` names days where N_d <= k, on "
            "which precision@k equals the day's prevalence for every ranker."),
        "budgets": list(BUDGETS),
        # EVERY ARCHIVED BUNDLE, including the rungs whose raw file is absent.
        # This is the accounting HI-Large never had.
        "nonbinding_by_bundle": {
            d.name: nonbinding_from_bundle(d)
            for d in sorted((root / "results_archive/replay").iterdir())
            if (d / "account_days_topk.parquet").exists()},
        "rungs": facts,
    }
    from aml.manifest import generator_provenance
    doc.update(generator_provenance(
        __file__, inputs=inputs, parameters={"budgets": list(BUDGETS)},
        scope=("aml-platform/src", "aml-platform/scripts")))
    dest = root / "results_archive/derived/budget_null.json"
    dest.write_text(json.dumps(doc, indent=1))
    print(f"wrote {dest}")
    for v, f in facts.items():
        print(f"  HI-{v}: null precision@50 in "
              f"[{f['null_precision_low@50']}, {f['null_precision_high@50']}] "
              f"(head {f['null_precision_high@50_head']}), "
              f"{f['nonbinding_days@50']} non-binding day(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
