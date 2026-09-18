"""Nulls and power for the per-typology claims.

`RESULTS_typology.md` made two claims its uncertainty does not support:

  1. "Detection varies substantially across structures", evidenced by a
     max/min spread of 3.05x. A max/min ratio over eight noisy estimates is
     biased upward BY CONSTRUCTION -- even with no true variation at all, the
     largest of eight binomial estimates exceeds the smallest. The question is
     not whether the ratio is above 1, it is whether it is above what the null
     produces.

  2. "The ordering does not replicate", evidenced by Spearman rho = 0.286,
     p = 0.49 between two rungs. That is NO EVIDENCE OF CORRELATION, which is
     not the same as evidence of no correlation. With 14-78 rings per structure
     the estimates are noisy enough that a PERFECTLY replicating ordering would
     often produce a rho this low -- which is a statement about power, and
     power is what the document never computed.

Both nulls use the ACTUAL per-typology ring counts, because both quantities
depend on them and neither is recoverable from a summary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def load(archive: Path, rung: str) -> dict:
    j = json.loads((archive / f"gold/typology_{rung}/stability.json").read_text())
    # `_spread` is a summary the sweep writes alongside the structures; it is
    # not a typology and must not become a ninth point in any of these tests.
    return {k: v for k, v in j["current"]["per_typology"].items()
            if not k.startswith("_")}


def spread_null(per_typ: dict, n_draws: int, rng) -> dict:
    """How large is max/min when every structure is EQUALLY detectable?"""
    names = sorted(per_typ)
    n = np.array([per_typ[k]["n_rings"] for k in names])
    obs_rate = np.array([per_typ[k]["ensemble"] for k in names])
    hits = np.rint(obs_rate * n).astype(int)
    pooled = hits.sum() / n.sum()

    observed = obs_rate.max() / obs_rate.min()
    draws = rng.binomial(n[None, :], pooled, size=(n_draws, len(n))) / n
    # A structure with zero hits makes the ratio infinite; those draws are
    # counted as >= observed rather than dropped, which is the conservative
    # direction for a claim that the spread is LARGE.
    lo = draws.min(axis=1)
    null_spread = np.where(lo > 0, draws.max(axis=1) / np.maximum(lo, 1e-12), np.inf)
    return {
        "observed_spread": float(observed),
        "pooled_rate": float(pooled),
        "null_spread_median": float(np.median(null_spread[np.isfinite(null_spread)])),
        "null_spread_p95": float(np.percentile(
            null_spread[np.isfinite(null_spread)], 95)),
        "p_value": float((1 + int((null_spread >= observed).sum())) / (n_draws + 1)),
        "n_rings": {k: int(per_typ[k]["n_rings"]) for k in names},
    }


def replication_power(a: dict, b: dict, n_draws: int, rng) -> dict:
    """If the ordering replicated PERFECTLY, how often would we see rho this low?

    Truth for both rungs is taken as rung A's observed profile, rescaled to each
    rung's own overall detection level -- so the RANKING is identical by
    construction and only the sampling noise differs. Any rho below 1 in this
    simulation is noise, nothing else.
    """
    shared = sorted(set(a) & set(b))
    na = np.array([a[k]["n_rings"] for k in shared])
    nb = np.array([b[k]["n_rings"] for k in shared])
    pa = np.array([a[k]["ensemble"] for k in shared])
    pb_level = np.average([b[k]["ensemble"] for k in shared], weights=nb)
    pa_level = np.average(pa, weights=na)
    pb = np.clip(pa * (pb_level / pa_level), 1e-6, 1 - 1e-6)

    obs_rho = float(spearmanr([a[k]["ensemble"] for k in shared],
                              [b[k]["ensemble"] for k in shared]).statistic)
    rhos = np.empty(n_draws)
    for i in range(n_draws):
        ra = rng.binomial(na, pa) / na
        rb = rng.binomial(nb, pb) / nb
        rhos[i] = spearmanr(ra, rb).statistic
    return {
        "observed_rho": obs_rho,
        "n_typologies": len(shared),
        "median_rho_if_ordering_replicated_perfectly": float(np.median(rhos)),
        "fraction_at_or_below_observed": float((rhos <= obs_rho).mean()),
        "rho_2p5": float(np.percentile(rhos, 2.5)),
        "rho_97p5": float(np.percentile(rhos, 97.5)),
    }


def cliff_exposure(patterns_dir: Path, bundle: Path, cliff: str,
                   stability: dict) -> dict:
    """Per-typology wind-down exposure, on THE RINGS THAT WERE EVALUATED.

    ⚠️ THE FIRST TWO VERSIONS OF THIS FUNCTION USED THE WRONG POPULATION.

    The first parsed the raw patterns file by hand and produced labels the
    typology keys could not join. The second fixed the labels but still called
    every pattern whose last transaction fell after the date cut a "test ring"
    -- **1,908** of them. The ring-aware split keeps **529**: it drops 736 of
    the 1,265 post-cut rings so ring participants cannot appear on both sides.
    Exposure measured on 1,908 rings was then applied to detection measured on
    529 different ones, and the numbers are not close -- GATHER-SCATTER's
    exposure goes from 0.5863 to **1.0000**.

    The evaluated ring IDs are in the replay bundle's `ring_membership`, and
    `data/bronze/patterns_<V>/rings.parquet` carries `ring_id -> typology,
    end_time` with the labels `parse-patterns` already normalised. Join those,
    and **assert the per-typology counts equal the stability artifact's**, which
    is the only check that would have caught either mistake.

    Exposure uses a ring's LAST transaction date, because `ring_recall` counts
    a ring as caught if any of its member-days is alerted.
    """
    rings = pd.read_parquet(patterns_dir / "rings.parquet",
                            columns=["ring_id", "typology", "end_time"])
    mem = pd.read_parquet(bundle / "ring_membership.parquet")
    ids = set(mem.ring_id.dropna().astype(int))

    r = rings[rings.ring_id.isin(ids)].copy()
    r["after"] = pd.to_datetime(r.end_time).dt.date >= dt.date.fromisoformat(cliff)
    g = r.groupby("typology").agg(n=("ring_id", "size"), n_after=("after", "sum"))

    # POPULATION IDENTITY, ASSERTED. Both earlier versions would have failed
    # here immediately.
    want = {k: v["n_rings"] for k, v in stability.items() if not k.startswith("_")}
    got = {k: int(v) for k, v in g.n.items()}
    if got != want:
        raise RuntimeError(
            "cliff exposure was measured on a different ring population from "
            f"the detection results: joined {got}, stability artifact says "
            f"{want}. Totals {sum(got.values())} vs {sum(want.values())}.")

    return {k: {"n_rings": int(g.loc[k, "n"]),
                "n_after_cliff": int(g.loc[k, "n_after"]),
                "share_after_cliff": round(float(g.loc[k, "n_after"] / g.loc[k, "n"]), 4)}
            for k in sorted(g.index)}


def measured_segment_rates(patterns_dir: Path, bundle: Path, cliff: str,
                           budget: int) -> dict:
    """Head and tail detection rates MEASURED, not assumed.

    Assumed rates cannot settle this. Across the feasible range on the
    ensemble basis -- and it is narrow, because 66.35% of evaluated rings fall
    after the cliff, so a tail rate above 0.5613 would need a negative head
    rate to reproduce the observed pooled 0.3724 -- the simulated p swings from
    0.0014 at a tail rate of 0.40 to 0.90 at 0.55. A null whose answer is set
    by an unmeasured nuisance parameter is not a null.

    So the rates come from the one basis where they are observable: this
    bundle, this budget, these 529 rings. The observed spread is recomputed on
    the same basis, because comparing a spread from one basis to a null from
    another is the error this whole function exists to correct.
    """
    rings = pd.read_parquet(patterns_dir / "rings.parquet",
                            columns=["ring_id", "typology", "end_time"])
    mem = pd.read_parquet(bundle / "ring_membership.parquet")
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    mem = mem.assign(_d=pd.to_datetime(mem.day).dt.date)
    ad = ad.assign(_d=pd.to_datetime(ad.day).dt.date)
    j = mem.merge(ad[["_d", "acct", "rank"]], on=["_d", "acct"], how="left")

    hit = j.groupby("ring_id")["rank"].apply(lambda x: bool((x <= budget).any()))
    idx = rings.set_index("ring_id")
    df = pd.DataFrame({"hit": hit})
    df["typology"] = idx.typology.reindex(df.index)
    df["after"] = (pd.to_datetime(idx.end_time.reindex(df.index)).dt.date
                   >= dt.date.fromisoformat(cliff))

    g = df.groupby("typology").agg(n=("hit", "size"), n_after=("after", "sum"),
                                   rate=("hit", "mean"))
    return {
        "budget": budget,
        "n_rings": len(df),
        "pooled_rate": round(float(df.hit.mean()), 5),
        "tail_rate_measured": round(float(df[df.after].hit.mean()), 5),
        "head_rate_measured": round(float(df[~df.after].hit.mean()), 5),
        "n_after": int(df.after.sum()), "n_before": int((~df.after).sum()),
        "observed_spread": round(float(g.rate.max() / g.rate.min()), 5),
        "per_typology": {k: {"n_rings": int(g.loc[k, "n"]),
                             "n_after_cliff": int(g.loc[k, "n_after"]),
                             "rate": round(float(g.loc[k, "rate"]), 5)}
                         for k in sorted(g.index)},
    }


def exposure_vs_detection(exposure: dict, rates: dict) -> dict:
    """Does exposure track detection? Tested EXACTLY, not asymptotically.

    The withdrawn version published `p = 0.0465` from `scipy.stats.spearmanr`'s
    t-approximation on n = 8. With eight points the permutation null is
    discrete and tiny -- 40,320 orderings -- so an asymptotic approximation has
    no reason to be accurate near a threshold. On that basis it was 0.0576
    exactly, on the other side of 0.05 from what was published. Both numbers
    are gone now because they were also measured at the wrong budget; the
    figures this returns are computed at the budget the spread is defined on,
    and every p here is exact.

    The correlation still rests heavily on one point: GATHER-SCATTER, whose
    rings are 100% after the cliff and 23.3% of which end on days where the
    budget exceeds the whole population. Its exclusion is reported beside the
    full result rather than instead of it.
    """
    import itertools
    import math

    names = sorted(exposure)
    x = np.array([exposure[k]["share_after_cliff"] for k in names])
    y = np.array([rates["per_typology"][k]["rate"] for k in names])
    obs = float(spearmanr(x, y).statistic)
    perms = [abs(float(spearmanr(x, y[list(q)]).statistic))
             for q in itertools.permutations(range(len(names)))]
    exact = sum(1 for v in perms if v >= abs(obs) - 1e-12) / len(perms)
    keep = [i for i, k in enumerate(names) if k != "GATHER-SCATTER"]
    x7, y7 = x[keep], y[keep]
    r7 = float(spearmanr(x7, y7).statistic)
    # EXACTLY HERE TOO. The first version published scipy's t-approximation for
    # the n=7 case on the line after the note saying the approximation must not
    # be quoted. 5,040 orderings is nothing to enumerate.
    p7 = sum(1 for q in itertools.permutations(range(len(x7)))
             if abs(float(spearmanr(x7, y7[list(q)]).statistic))
             >= abs(r7) - 1e-12) / math.factorial(len(x7))
    return {
        "rho": round(obs, 4),
        "p_exact_permutation": round(exact, 5),
        "n_orderings": len(perms),
        "p_t_approximation_WITHDRAWN": round(float(spearmanr(x, y).pvalue), 5),
        "rho_without_GATHER_SCATTER": round(float(r7), 4),
        "p_without_GATHER_SCATTER_exact": round(float(p7), 5),
        "note": ("the t-approximation is recorded only to show what was "
                 "withdrawn and must not be quoted; with n = 8 the exact "
                 "permutation p is the test"),
    }


def nonbinding_rings(patterns_dir: Path, bundle: Path, budget: int) -> dict:
    """Rings that END on a day where the budget exceeds the population.

    On such a day the top-k IS the whole day, so every ranker -- including a
    constant -- alerts every account-day, and any ring touching it is caught
    with probability 1. The repo has always said this about `precision@k`
    (`nonbinding_days@k`) and never once applied it to `ring_recall`, which is
    the metric the per-typology table is built from. Scrutiny applied to one
    metric and not its neighbour is the tell.

    It matters because the affected rings are not spread evenly: they
    concentrate in the typology that tops the spread, which is what turns a
    generator artifact into an apparent finding.
    """
    rings = pd.read_parquet(patterns_dir / "rings.parquet",
                            columns=["ring_id", "typology"])
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    mem = pd.read_parquet(bundle / "ring_membership.parquet")
    cap = json.loads((bundle / "bundle.json").read_text())["max_budget"]
    ad["_d"] = pd.to_datetime(ad.day).dt.date
    mem["_d"] = pd.to_datetime(mem.day).dt.date
    g = ad.groupby("_d")["rank"].agg(size="size", mx="max")
    # N_d is known exactly only where the day never reached the bundle's cap.
    nb = {d for d, r in g.iterrows() if r.mx < cap and r.mx <= budget}
    last = mem.groupby("ring_id")["_d"].max()
    df = pd.DataFrame({"end": last})
    df["typology"] = rings.set_index("ring_id").typology.reindex(df.index)
    df["nonbinding"] = df.end.isin(nb)
    per = df.groupby("typology").nonbinding.agg(["size", "sum"])
    return {
        "budget": budget,
        "nonbinding_days": sorted(str(d) for d in nb),
        "rings_ending_on_a_nonbinding_day": int(df.nonbinding.sum()),
        "rings_total": len(df),
        "per_typology": {k: {"n_rings": int(r["size"]),
                             "n_on_nonbinding_days": int(r["sum"]),
                             "share": round(float(r["sum"] / r["size"]), 4)}
                         for k, r in per.iterrows()},
        "note": ("these rings are caught by ANY ranker, including a constant "
                 "one, so they carry no information about the model and they "
                 "inflate a max/min spread through whichever typology holds "
                 "most of them"),
    }


def permutation_spread_null(patterns_dir: Path, bundle: Path, budget: int,
                            n_draws: int, rng) -> dict:
    """The typology spread against the repo's OWN null. Nine audits missed it.

    Every previous null here drew from a binomial: one rate per ring, or one
    rate per cliff stratum. Both are false for a budget-constrained metric,
    and for the same reason `ring_recall` already HAS a permutation null in
    `aml.eval.metrics` and `precision@k` has a non-binding-day caveat. On a day
    whose population is smaller than the budget, every ranker alerts the whole
    day, so a ring ending there is caught with probability 1 by a constant
    ranker -- and those rings concentrate in one typology (see
    `nonbinding_rings`).

    So the null must hold the ranking mechanism fixed and permute only the
    scores, within a day, which is what `metrics._permutation_null` does.
    Reproduced here from the replay bundle: ring-transaction scores are
    shuffled inside each day's block, an eligible account-day's score is the
    max over its ring transactions and its non-ring maximum, and each is
    re-ranked against its own day's untouched non-eligible scores. For a
    budget at or under the bundle's cap those scores are complete, which is
    what makes this recomputable from 548 KB.

    WHAT IT SAYS, and it is not what was published: the observed spread sits
    at the 54th percentile of this null (p = 0.47) -- the median outcome of
    chance, not an effect. And the ORDERING inverts: see `per_typology_lift`,
    where GATHER-SCATTER, published as the easiest typology and the only one
    stable across rungs, detects BELOW its own null.
    """
    rings = pd.read_parquet(patterns_dir / "rings.parquet",
                            columns=["ring_id", "typology"])
    ad = pd.read_parquet(bundle / "account_days_topk.parquet")
    ep = pd.read_parquet(bundle / "ring_endpoints.parquet")
    rt = pd.read_parquet(bundle / "ring_transactions.parquet")
    for f in (ad, ep, rt):
        f["_d"] = pd.to_datetime(f.day).dt.date

    elig = set(map(tuple, ep[["_d", "acct"]].drop_duplicates().to_numpy()))
    ad["_elig"] = [(d, a) in elig for d, a in zip(ad._d, ad.acct, strict=True)]
    om = ad[ad._elig].set_index(["_d", "acct"]).other_max
    days = sorted(set(ep._d))
    nonelig = {d: np.sort(ad[(ad._d == d) & (~ad._elig)].score.to_numpy())[::-1]
               for d in days}
    rt_of_day = {d: np.where(rt._d.to_numpy() == d)[0] for d in days}
    pos = {r: i for i, r in enumerate(rt.rt.to_numpy())}
    ep_rt = np.array([pos[r] for r in ep.rt.to_numpy()])
    ep_day, ep_acct = ep._d.to_numpy(), ep.acct.to_numpy()
    pair = pd.MultiIndex.from_arrays([ep_day, ep_acct])
    om_arr = om.reindex(pair).fillna(-np.inf).to_numpy()
    ring_u, ring_inv = np.unique(ep.ring_id.to_numpy(), return_inverse=True)
    typ = rings.set_index("ring_id").typology.reindex(ring_u).to_numpy()
    names = sorted(set(typ))
    masks = np.array([[t == n for t in typ] for n in names])
    dser, aser = pd.Series(ep_day), pd.Series(ep_acct)

    def rates(txn_scores) -> np.ndarray:
        sc = np.maximum(txn_scores[ep_rt], om_arr)
        gm = (pd.DataFrame({"d": dser, "a": aser, "s": sc})
                .groupby(["d", "a"]).s.max())
        cut = {}
        for d in days:
            allsc = np.concatenate([nonelig[d], gm.loc[d].to_numpy()])
            allsc[::-1].sort()
            cut[d] = allsc[budget - 1] if len(allsc) >= budget else -np.inf
        on = gm.reindex(pair).to_numpy() >= np.array([cut[d] for d in ep_day])
        hit = np.zeros(len(ring_u), bool)
        np.logical_or.at(hit, ring_inv, on)
        return np.array([hit[m].mean() for m in masks])

    obs = rates(rt.score.to_numpy())
    observed = float(obs.max() / obs.min())
    base = rt.score.to_numpy()
    sims = np.empty((n_draws, len(names)))
    for i in range(n_draws):
        q = base.copy()
        for d in days:
            ix = rt_of_day[d]
            if len(ix) > 1:
                q[ix] = rng.permutation(q[ix])
        sims[i] = rates(q)
    lo = sims.min(axis=1)
    spread = np.where(lo > 0, sims.max(axis=1) / np.maximum(lo, 1e-12), np.inf)
    fin = spread[np.isfinite(spread)]
    null_rate = sims.mean(axis=0)
    ratio = obs / np.where(null_rate > 0, null_rate, np.nan)

    # AN ORDERING WITHOUT AN INTERVAL IS NOT AN ORDERING.
    #
    # The first version of this published eight ratios, called the ordering
    # "inverted", and said a ratio below 1 meant the model did worse than a
    # random ranker. Both were wrong, and the second was wrong in a way this
    # repository had already written a comment to prevent -- see
    # `metrics.py:640`, where the same quantity is re-exported as
    # `ring_coverage_concentration` precisely because H0 conditions on the
    # model's OWN per-day score multiset, so a value below 1 means the alerts
    # CONCENTRATE into fewer distinct rings, not that they are worse than
    # chance at finding rings.
    #
    # With intervals, six of eight span 1 and the two that do not
    # (FAN-IN, SCATTER-GATHER) do not survive multiplicity. P(the two
    # typologies at the ends of the "inversion" land that way under H0) is
    # about 0.48 -- a coin flip.
    per: dict = {}
    raw_p: dict[str, float] = {}
    for i, name in enumerate(names):
        col = sims[:, i]
        r_lo = obs[i] / np.percentile(col, 97.5) if np.percentile(col, 97.5) else np.nan
        r_hi = obs[i] / np.percentile(col, 2.5) if np.percentile(col, 2.5) else np.nan
        centred = np.abs(col / null_rate[i] - 1.0) if null_rate[i] else np.zeros_like(col)
        beyond = int((centred >= abs(ratio[i] - 1.0)).sum())
        pv = (1 + beyond) / (n_draws + 1)
        raw_p[name] = float(pv)          # UNROUNDED, for the adjustment
        per[name] = {
            "observed": round(float(obs[i]), 5),
            "null": round(float(null_rate[i]), 5),
            "concentration": round(float(ratio[i]), 4),
            "ci95": [round(float(r_lo), 4), round(float(r_hi), 4)],
            "p_two_sided": round(pv, 5),
            # THE INTEGER BEHIND THE p-VALUE. At 400 draws the smallest
            # attainable p is 1/401 and FAN-IN's 0.00998 rests on four draws,
            # so a p quoted to five decimals asserts a precision the
            # simulation does not have. Publishing the count makes that
            # visible without a reader having to invert the arithmetic.
            "n_draws_at_or_beyond": beyond,
            "p_mc_se": round(float((pv * (1 - pv) / n_draws) ** 0.5), 5),
            # RENAMED. This was `distinguishable_from_1`, which reads as
            # significance -- and it was True for exactly the two typologies
            # that FAIL Holm (p_holm 0.0798 and 0.10474). It is a statement
            # about one unadjusted interval and nothing more.
            "ci95_excludes_1": bool(r_lo > 1.0 or r_hi < 1.0),
        }
    # Holm, because eight ratios are eight tests.
    #
    # WITH THE RUNNING MAXIMUM. The first version multiplied each ordered
    # p-value by its remaining-test count and stopped there, which is not
    # Holm: the procedure is monotone, so an adjusted value may never be
    # smaller than one that came before it. Omitting the cumulative max
    # understated four of the eight -- CYCLE 0.54865 where Holm gives 0.5985,
    # RANDOM 0.88279 where Holm gives 1.0. It did not change the count of
    # significant results, which is exactly why nothing noticed.
    # FROM THE UNROUNDED p-VALUES, and with the running maximum.
    #
    # Two separate errors lived here. The first version omitted the cumulative
    # max, which is not Holm at all -- the procedure is monotone, so an
    # adjusted value may never fall below one that came before it. The second
    # fed it `round(p, 5)`, so the adjustment was computed from the display
    # form rather than the measurement. Neither changed the count of
    # significant results, which is exactly why neither was noticed.
    order = sorted(raw_p, key=lambda k: raw_p[k])
    running = 0.0
    for rank, name in enumerate(order):
        running = max(running, min(1.0, raw_p[name] * (len(order) - rank)))
        per[name]["p_holm"] = round(float(running), 5)
    assert all(
        per[a]["p_holm"] <= per[b]["p_holm"] + 1e-12
        for a, b in itertools.pairwise(order)), \
        "Holm-adjusted p-values must be monotone in the ordered raw p-values"
    # FROM THE UNROUNDED ADJUSTMENT. Counting on `per[...]["p_holm"]` counts
    # the DISPLAY form, which is the same mistake as computing Holm from
    # rounded inputs, one step later. No attainable value currently sits in
    # the ambiguous band, so this changed nothing -- which is why it survived.
    holm_unrounded: dict[str, float] = {}
    running_u = 0.0
    for rank, name in enumerate(order):
        running_u = max(running_u, min(1.0, raw_p[name] * (len(order) - rank)))
        holm_unrounded[name] = running_u
    n_sig = sum(1 for v in holm_unrounded.values() if v < 0.05)
    spans_one = sum(1 for v in per.values() if not v["ci95_excludes_1"])
    # AND WHETHER THE SIMULATION COULD HAVE SAID OTHERWISE. With k tests the
    # smallest Holm value reachable at all is k/(n_draws+1); if that is not
    # comfortably below 0.05 then "nothing survives Holm" is a statement about
    # the draw count, not about the typologies.
    holm_floor = len(order) / (n_draws + 1)
    # ⚠️ AND THE FLOOR IS THE WRONG TEST OF RESOLVED-NESS. It only says the
    # grid is fine enough to EXPRESS a small value; it says nothing about
    # whether the value actually measured is separated from 0.05. FAN-IN's
    # p_holm came out 0.0436 against a threshold of 0.05 with a Monte-Carlo
    # standard error that puts the adjusted interval at roughly [0.035,
    # 0.051] -- straddling the threshold -- while `holm_conclusion_is_resolved`
    # read `true` off a floor of 0.0004. Resolved means the INTERVAL clears
    # the threshold.
    best = order[0]
    k_tests = len(order)
    p0 = raw_p[best]
    se0 = (p0 * (1 - p0) / n_draws) ** 0.5
    holm_ci = [max(0.0, min(1.0, (p0 - 1.96 * se0) * k_tests)),
               max(0.0, min(1.0, (p0 + 1.96 * se0) * k_tests))]
    resolved = holm_ci[1] < 0.05 or holm_ci[0] > 0.05

    return {
        "estimand": (
               "ring_coverage_concentration per typology: the share of a "
               "typology's rings the ranker covers, divided by what a WITHIN-"
               "DAY permutation of ring-transaction scores gives it. Below 1 "
               "means the alerts concentrate into fewer distinct rings than a "
               "ring-blind reassignment of the same scores -- it is NOT a "
               "statement that the model is worse than chance at finding "
               "rings, and metrics.py:640 renames the metric to stop that "
               "reading."),
        "budget": budget,
        "draws": n_draws,
        "observed_spread": round(observed, 5),
        "null_spread_median": round(float(np.median(fin)), 5),
        "null_spread_p95": round(float(np.percentile(fin, 95)), 5),
        "p_value": round((1 + int((spread >= observed).sum())) / (n_draws + 1), 5),
        "observed_percentile": round(float(100 * (spread < observed).mean()), 1),
        "per_typology_concentration": per,
        "n_significant_after_holm_at_0.05": n_sig,
        "smallest_p_holm": round(min(holm_unrounded.values()), 5),
        "smallest_p_holm_attainable_at_this_draw_count": round(holm_floor, 5),
        "smallest_p_holm_mc_ci95": [round(holm_ci[0], 5), round(holm_ci[1], 5)],
        # TRUE only when the Monte-Carlo interval on the smallest adjusted
        # p-value falls entirely on one side of 0.05. At 20000 draws it does
        # not, so the FAN-IN result is inside simulation error and must be
        # reported as such rather than as a significant finding.
        "holm_conclusion_is_resolved": bool(resolved),
        "draws_needed_to_resolve_at_0.05": (
            None if resolved else
            int((1.96 ** 2) * p0 * (1 - p0) / ((0.05 / k_tests - p0) ** 2)) + 1
            if p0 < 0.05 / k_tests else None),
        # THE FAMILY IS A CHOICE, AND IT DECIDES THE ANSWER. This artifact
        # carries more p-values than these eight; multiplying by 11 gives
        # 0.0600 and by 14 gives 0.0763, so a reader could move FAN-IN across
        # 0.05 without doing anything dishonest. The multiplier is fixed here,
        # in the artifact, as the eight per-typology concentration tests --
        # declared rather than chosen after seeing the result.
        "holm_family": {
            "n_tests": k_tests,
            "definition": "the per-typology ring_coverage_concentration tests "
                          "in this block, one per typology present",
            "members": list(order),
            "note": "other p-values in this file (the spread null, "
                    "exposure_vs_detection) are separate pre-specified "
                    "questions and are NOT in this family",
        },
        # THE TWO SIDES ARE NOT THE SAME BASIS, AND SAYING SO IS THE POINT.
        #
        # The withdrawn 3.05x is an EIGHT-SEED score-averaged ensemble read
        # from gold/typology_Medium/stability.json. This null is computed on
        # ONE archived replay of a single fit from the `models` lineage. They
        # differ in model basis, in lineage, and in ring-membership
        # implementation: the stability artifact predates the many-to-many
        # correction, and this replay contains 5 account-days belonging to two
        # rings each, which the old collapsed-column join would have assigned
        # to whichever typology `max` happened to pick
        # (src/aml/eval/metrics.py:794).
        #
        # So this does NOT show that 3.05x is at chance. It shows that a
        # corrected single-seed spread on the same rings is ordinary under its
        # own null. Stating that difference here means no downstream document
        # can quietly treat the two as interchangeable -- which is the error
        # that produced every withdrawn version of this result.
        "basis": {
            "this_null": {
                "model": "single fit, replay bundle, `models` lineage",
                "metric": f"ring_recall@{budget}",
                "ring_membership": "current many-to-many join",
                "observed_spread": round(observed, 5),
            },
            "withdrawn_claim": {
                "model": "eight-seed score-averaged ensemble",
                "source": "gold/typology_Medium/stability.json",
                "metric": f"ring_recall@{budget}",
                "ring_membership": "predates the many-to-many correction",
                "observed_spread": 3.04745,
            },
            "like_for_like_test_not_run": (
                "an ensemble replay under current HEAD, asserting that the "
                "null's per-typology observed rates equal the source "
                "artifact's. It needs the HI-Medium feature table rebuilt "
                "(hours, and more free disk than this machine has), so the "
                "3.05x figure is withdrawn because its H0 is false -- not "
                "because a valid null was computed for it"),
        },
        # GENERATED FROM THE NUMBERS, never written alongside them. This
        # string has now been stale TWICE: it read "nothing survives Holm, and
        # it is a null result" after the draw count rose from 400 to 20000 and
        # one deviation did survive, and it then read "its Monte-Carlo
        # interval straddles 0.05" after 50000 draws moved the interval
        # entirely below the threshold. Prose written beside a number goes
        # stale when the number moves; prose computed from it cannot.
        "interpretation": _interpretation(per, spans_one, n_sig, holm_ci,
                                          min(holm_unrounded.values()),
                                          resolved, len(order)),
    }


def _interpretation(per: dict, spans_one: int, n_sig: int, holm_ci: list,
                    best_holm: float, resolved: bool, k_tests: int) -> str:
    """The reading of this block, derived from the block."""
    fixed = (
        "`concentration` is `ring_coverage_concentration` computed per "
        "typology: observed ring recall over a within-day permutation null "
        "that conditions on the model's own per-day score multiset. Below 1 "
        "means the alerts concentrate into FEWER DISTINCT RINGS than a "
        "ring-blind reassignment of the same scores -- NOT that the model is "
        "worse than chance at finding rings, and not that the typology is "
        "harder to detect (see metrics.py:640). ")
    order_note = (
        f"No per-typology ORDERING is established: {spans_one} of "
        f"{len(per)} intervals span 1. ")
    if not n_sig:
        return fixed + order_note + "No deviation survives Holm."
    who = sorted((v["p_holm"], k) for k, v in per.items())[0][1]
    # The family size at which the smallest adjusted p would cross 0.05. A
    # finding that dies on the next test is fragile and has to say so.
    raw = best_holm / k_tests
    flips = next((k for k in range(1, 200) if raw * k >= 0.05), None)
    return (
        fixed + order_note +
        f"{n_sig} deviation ({who}) has an adjusted p-value of {best_holm:.5f} "
        f"with a Monte-Carlo interval of {holm_ci}, which "
        f"{'clears' if resolved else 'straddles'} 0.05. "
        + (f"It is FRAGILE IN THE FAMILY SIZE: the multiplier here is "
           f"{k_tests}, declared in `holm_family`, and at {flips} tests the "
           f"same raw p-value gives {raw * flips:.5f} and the finding is gone. "
           if flips else "")
        + "Report it with the family, or not at all.")


def feasible_tail_range(exposure: dict, pooled: float) -> dict:
    """Which assumed tail rates could reproduce the observed pooled rate.

    Reported because an earlier version ASSUMED 0.80/0.90/0.95 and silently
    fell back to the pooled rate when no head rate in [0, 1] could balance
    them. With 66.35% of evaluated rings after the cliff, a tail rate of 0.80
    implies pooled >= 0.531 even with zero head detection, against an observed
    0.3724. Those rates were impossible, and the fallback hid it.
    """
    n = sum(v["n_rings"] for v in exposure.values())
    na = sum(v["n_after_cliff"] for v in exposure.values())
    share = na / n
    return {"after_cliff_share": round(share, 5),
            "pooled_rate": round(pooled, 5),
            "max_feasible_tail_rate": round(pooled / share, 5),
            "min_feasible_tail_rate": round(
                max(0.0, (pooled - (1 - share)) / share), 5),
            "note": ("a tail rate outside this range cannot reproduce the "
                     "observed pooled rate with a head rate in [0, 1]")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="results_archive", type=Path)
    ap.add_argument("--draws", type=int, default=20000)
    ap.add_argument("--out", default="results_archive/derived/typology_null.json")
    ap.add_argument("--patterns-dir", default="data/bronze/patterns_Medium",
                    type=Path,
                    help="PARSED patterns (rings.parquet), which carries "
                         "ring_id -> typology with normalised labels")
    ap.add_argument("--bundle", default="results_archive/replay/medium_gbdt_s0",
                    type=Path,
                    help="replay bundle whose ring_membership defines the "
                         "EVALUATED ring population")
    ap.add_argument("--thin-from", default="2022-09-17",
                    help="the rung's transaction-volume collapse date")
    ap.add_argument("--ring-budget", type=int, default=None,
                    help="budget at which the per-typology rates are measured. "
                         "Defaults to the budget the stability artifact "
                         "actually used, which is NOT the one beside it in the "
                         "same file -- see below.")
    # 50000, because that is what the committed artifact used and the
    # documented command has to reproduce it. At 20000 the FAN-IN result came
    # out p_holm = 0.0436 with a Monte-Carlo interval of [0.0354, 0.0518],
    # straddling 0.05 -- so `python scripts/typology_null.py` produced a
    # DIFFERENT CONCLUSION from the archived artifact, and the checklist told
    # a reader to run exactly that. The draw count is not a tuning knob here:
    # it is the difference between a resolved finding and an unresolved one.
    ap.add_argument("--perm-draws", type=int, default=50000,
                    help="draws for the within-day permutation null, which "
                         "re-ranks every eligible account-day per draw and so "
                         "costs far more than a binomial")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    from aml.manifest import generator_provenance
    rng = np.random.default_rng(0)
    med, small = load(a.archive, "Medium"), load(a.archive, "Small")

    # THE BUDGET THE SPREAD IS ACTUALLY ON.
    #
    # `stability.json`'s per_typology block is `ring_recall@50` published under
    # budget-free names, in a file whose per_seed block reports
    # `ring_recall@200`. Nothing recorded which, so a previous version of this
    # script defaulted to 200 and measured strata at one budget against a
    # spread computed at another -- publishing, in ONE artifact, a measured
    # tail rate of 0.78348 beside its own feasibility cap of 0.56125.
    # `_typology_summary` now records `_metric.budget`; where an artifact
    # predates that label, 50 is the value its code used.
    stab_raw = json.loads(
        (a.archive / "gold/typology_Medium/stability.json").read_text())
    meta = stab_raw["current"]["per_typology"].get("_metric", {})
    budget = a.ring_budget or int(meta.get("budget", 50))

    out = {
        "ring_budget": budget,
        "ring_budget_source": ("recorded in stability.json `_metric`"
                               if meta.get("budget") else
                               "stability.json predates the `_metric` label; "
                               "50 is what `_typology_summary` used"),
        "draws": a.draws,
        "spread_Medium": spread_null(med, a.draws, rng),
        "spread_Small": spread_null(small, a.draws, rng),
        # The power simulation re-runs spearmanr per draw, so it gets fewer.
        "replication_power": replication_power(med, small, min(a.draws, 4000), rng),
    }

    # THE DEFENSIBLE NULL, plus exposure as a DESCRIPTION rather than a test.
    #
    # `exposure_only_spread_null` is gone. Its p-value (0.0026) is withdrawn:
    # it stratified a per-day process into two levels, at the wrong budget, on
    # a model outside the ensemble whose spread it was explaining. Every
    # binomial null tried here shares that flaw -- see
    # `permutation_spread_null`. Exposure is still measured, because it is a
    # real property of the generator; it is no longer a hypothesis test.
    rings_pq = a.patterns_dir / "rings.parquet"
    stab_med = a.archive / "gold/typology_Medium/stability.json"
    cliff_inputs = []
    if rings_pq.exists() and (a.bundle / "ring_membership.parquet").exists():
        stab = stab_raw["current"]["per_typology"]
        exp = cliff_exposure(a.patterns_dir, a.bundle, a.thin_from, stab)
        rates = measured_segment_rates(a.patterns_dir, a.bundle, a.thin_from,
                                       budget)
        out["cliff_exposure_Medium"] = exp
        out["measured_segment_rates_Medium"] = rates
        out["permutation_spread_Medium"] = permutation_spread_null(
            a.patterns_dir, a.bundle, budget, a.perm_draws,
            np.random.default_rng(0))
        out["exposure_vs_detection"] = exposure_vs_detection(exp, rates)
        out["nonbinding_rings_Medium"] = nonbinding_rings(
            a.patterns_dir, a.bundle, budget)
        out["feasible_tail_range_ensemble_basis"] = feasible_tail_range(
            exp, float(out["spread_Medium"]["pooled_rate"]))
        # THE ASSERTION THE PREVIOUS GATE WAS NAMED FOR AND DID NOT MAKE: it
        # checked the withdrawn ASSUMED rates against the cap and never the
        # measured rate published beside it -- which violated that cap.
        cap = out["feasible_tail_range_ensemble_basis"]["max_feasible_tail_rate"]
        tail = rates["tail_rate_measured"]
        if tail > cap + 1e-9:
            raise RuntimeError(
                f"the measured tail rate {tail} exceeds the feasibility cap "
                f"{cap} computed from the ensemble's pooled rate. The two are "
                "on different bases -- almost certainly different budgets -- "
                "and publishing them side by side is what this refuses.")
        cliff_inputs = [rings_pq, a.bundle / "ring_membership.parquet",
                        a.bundle / "account_days_topk.parquet",
                        a.bundle / "ring_endpoints.parquet",
                        a.bundle / "ring_transactions.parquet"]
    else:
        out["permutation_spread_Medium"] = {
            "error": "parsed patterns or replay bundle absent; the "
                     "within-day permutation null was NOT computed and no "
                     "p-value for the typology spread may be published"}

    # PROVENANCE THAT NAMES WHAT WAS ACTUALLY READ.
    #
    # This recorded `inputs=[a.archive]` -- the artifact's own output directory
    # -- so its input identity was self-referential and drifted whenever
    # anything else in the archive changed. It also omitted the patterns file
    # and every cliff parameter, so the artifact could not be reproduced from
    # what it recorded. Now: the two stability files, the parsed rings and the
    # two bundle tables actually read, and every parameter.
    out.update(generator_provenance(
        __file__,
        inputs=[stab_med, a.archive / "gold/typology_Small/stability.json",
                *cliff_inputs],
        parameters={"draws": a.draws, "thin_from": a.thin_from,
                    "ring_budget": budget, "perm_draws": a.perm_draws,
                    "patterns_dir": str(a.patterns_dir),
                    "bundle": str(a.bundle),
                    "rates": "MEASURED from the bundle, not assumed"}))

    d = Path(a.out)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
