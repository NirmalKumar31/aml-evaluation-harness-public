"""
The metric suite. recall@budget is the headline; everything else is context.

WHY NOT ACCURACY: at 0.1% prevalence, "always say no" scores 99.9%.
WHY NOT ROC-AUC AS HEADLINE: at this prevalence it saturates near 0.99 and
    barely moves while recall@budget swings by 20 points. Reported once, in a
    footnote, never as the lead.

THE ALERT UNIT IS (account, calendar_day). Not transactions, not rings.

It is an EXPLICIT PROXY, not an observed operational fact. This docstring used
to say it is "what a human investigator actually opens and reviews", which is an
empirical claim about compliance workflows backed by no queue, no analyst study
and no citation. Real programmes review customers, scenario alerts, cases merged
across days, or events, and those are not rescalings of one another. AMLworld
has no customer identifier and no case structure, so the unit cannot be varied
here -- see docs/LIMITATIONS.md section 3b.

What IS true and is the reason to state it every time: fifty transactions, fifty
account-days and fifty rings are three different projects with three different
numbers. Every arm in this repository is measured under the same proxy, so the
comparisons hold even where the absolute level does not transfer.
"""
import hashlib

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

DEFAULT_BUDGETS = (10, 25, 50, 100, 200, 500, 1000)

# THE CEILING PROBLEM
# ------------------------------------------------------------------
# A budget of B account-days per day over D days offers B*D reviews in total.
# If the test window holds P positive account-days and B*D < P, then recall@B
# is capped at (B*D)/P no matter how good the model is.
#
# B*D IS THE LOOSE BOUND, AND THIS COMMENT USED TO PUBLISH IT AS THE CEILING.
#
# It said "50 slots x 19 days = 950 reviews against 18,130 positive
# account-days, so recall@50 can never exceed 5.2% ... 0.027 is in fact 52% of
# everything attainable". Both numbers are wrong, and the code eight lines
# below has always computed the right ones.
#
# B*D over-counts because it assumes every day offers B positives to find. The
# HI-Medium test window is violently non-stationary -- per-day positives run
# 1431, 1543, 1938, 2220, 2331, 2548, 2737 and then collapse to 940 ... 13, 4,
# with 81.3% of all positives in the first 7 of 19 days. On the last three days
# there are fewer than 50 positive account-days in existence, so the budget
# cannot be spent. The attainable count is therefore
#
#     sum_d min(P_d, B) = 858,  not 950
#
# and the ceiling is 858/18130 = 0.04732, against which recall@50 = 0.027 is
# 57.1% of the attainable -- which is what `recall_efficiency@50` reports and
# what the published tables carry.
#
# THE SENTENCE THAT USED TO FOLLOW WAS BACKWARDS, and it was written in the
# same edit that fixed the number above. It said every budget metric here is
# "dominated by week one", reasoning from the fact that 81.3% of POSITIVES
# fall in the first seven days. The opposite is true of everything that
# matters, because `min(P_d, B)` caps the busy days at B and lets the thin days
# contribute their whole count:
#
#     ceiling      week one 350 of 858   (40.8%)  -- tail is the majority
#     GBDT TPs     week one 265 of 761   (34.8%)
#     logistic TPs week one  15 of 493   ( 3.0%)  -- tail is 97%
#
# The cause is that AMLworld's generator winds down. HI-Medium goes from
# 3,021,866 transactions on 09-16 at 0.0008 laundering to 2,020 on 09-17 at
# 0.5936 -- a 1,500x volume drop and a 740x prevalence jump overnight. Those
# are not the same detection problem. `scripts/window_volume.py` measures the
# profile and decomposes every shipped bundle by segment; nothing in this
# repository recorded per-day transaction volume before it, which is why
# eleven audit rounds discussed the positive collapse and never found this.
#
# Read no pooled budget number from this benchmark without that decomposition.
#
# The 2-decimal form of the wrong number ("5.2%", "52%") sat below
# `make_tables.py --check`'s 3-decimal match threshold, so the publication gate
# could not see it. That is the gate's documented blind spot demonstrated in
# the file that defines the concept it was built to protect.
#
# IBM's generator injects far more laundering per day than a real bank's
# investigator headcount would ever cover -- ~954 positive account-days a day
# on average here. That is a property of the synthetic data, not of the model,
# so every recall@B is reported next to its ceiling and the fraction achieved.


def to_account_days(df: pd.DataFrame, score: np.ndarray,
                    with_txn_id: bool = False) -> pd.DataFrame:
    """Transactions -> (account, day) rows.

    Each transaction produces TWO account-days (sender's and receiver's),
    because either party can be the one an investigator is told to look at.
    An account-day's score is the max over that account's transactions that
    day; it is positive if ANY of them was laundering.

    `with_txn_id` adds `argmax_txn_id`: the POSITIONAL index of the transaction
    that supplied the account-day's score. Opt-in, because it costs an int32
    column over the 2N concatenated frame -- about 1.4 GB at HI-Large, on a run
    that already peaked at 30.8 GB of 31 -- and nothing in the metric path
    needs it.

    The replay bundle does. Without it, "how many distinct transactions does a
    50-account-day budget actually cover?" can only be answered with a
    score-tie proxy, and unrelated transactions can share a score, so that
    proxy bounds the transaction count from below rather than estimating it.
    The index is positional and dense, so it identifies nothing outside the
    frame -- the same posture as the opaque account codes the bundle ships.

    ⚠️ ON ITS OWN THIS IS NOT ENOUGH FOR A TRANSACTION-LEVEL METRIC, and an
    earlier version of this docstring implied it was. `idxmax` picks
    arbitrarily among transactions tied for the maximum; the account-day label
    is `max(y)` over ALL of the account's transactions, not the label of the
    one named here, so an account-day can carry y=1 while `argmax_txn_id`
    points at a non-laundering transaction that tied; and a transaction-level
    recall needs per-day positive TRANSACTION counts, which this does not
    provide. `make_replay_bundle.py` emits a separate transaction-level table
    for that. This field answers "which transaction set this score", and only
    that.
    """
    day = df.event_date.to_numpy()
    ring = df.ring_id.to_numpy()
    t = pd.DataFrame({"day": day, "score": score,
                      "y": df.is_laundering.to_numpy(), "ring_id": ring,
                      # The max over this account-day's NON-ring transactions,
                      # carried alongside the overall max. The permutation null
                      # reshuffles ring transaction scores and must know what
                      # the account-day would still score without them. Built
                      # here, on N rows, rather than assigned onto the
                      # concatenated 2N frame afterwards -- on HI-Large that
                      # is the difference between one 432 MB column and a copy
                      # of a multi-gigabyte frame.
                      "score_nonring": np.where(pd.isna(ring), score, -np.inf)})
    if with_txn_id:
        t["argmax_txn_id"] = np.arange(len(t), dtype=np.int32)
    both = pd.concat([t.assign(acct=df.sender_id.to_numpy()),
                      t.assign(acct=df.receiver_id.to_numpy())],
                     ignore_index=True)
    agg = dict(score=("score", "max"), y=("y", "max"))
    if with_txn_id:
        agg["argmax_txn_id"] = ("argmax_txn_id", "first")
    ad = both.groupby(["day", "acct"], observed=True, sort=False).agg(
        score=("score", "max"), y=("y", "max"),
        # RETAINED ONLY AS A LABEL, never as ring membership. See `membership`.
        ring_id=("ring_id", "max"),
        other_max=("score_nonring", "max")).reset_index()

    if with_txn_id:
        # THE ARGMAX, not an arbitrary member. `first` above would take
        # whichever row the groupby happened to see first, which is not the
        # transaction that set the score, and the whole point is to name that
        # one. Computed by locating the maximum per group directly.
        idx = both.groupby(["day", "acct"], observed=True,
                           sort=False)["score"].idxmax()
        ad["argmax_txn_id"] = both.loc[idx.to_numpy(),
                                       "argmax_txn_id"].to_numpy()

    # MEMBERSHIP IS MANY-TO-MANY AND MUST NOT BE AGGREGATED.
    #
    # `ring_id=max` collapses each account-day to ONE ring. That is wrong
    # whenever an account-day participates in several, and it is not a corner
    # case -- measured on HI-Large's reconciled labels:
    #
    #     ringed account-days       243,295
    #     MULTI-RING account-days    10,432   (4.288%)
    #     max rings on one acct-day       12
    #
    # So up to eleven of twelve memberships were being discarded on 4.3% of
    # ringed account-days. Every discarded membership is a detection
    # opportunity the affected ring silently loses, which biases ring_recall
    # DOWNWARD, and it mis-assigns typology for those rows.
    #
    # The fix is not a better aggregate -- there is no correct scalar. Scores
    # live on account-days; membership is a separate relation joined only at
    # the point a detection event is defined.
    rt = np.flatnonzero(pd.notna(ring))
    ep = pd.DataFrame({
        "day": np.concatenate([day[rt], day[rt]]),
        "acct": np.concatenate([df.sender_id.to_numpy()[rt],
                                df.receiver_id.to_numpy()[rt]]),
        "ring_id": np.concatenate([ring[rt], ring[rt]]),
        # Which ring TRANSACTION this endpoint came from. The null permutes
        # transaction scores, so the endpoint -> transaction map is the join
        # that makes a sender and a receiver move together.
        "rt": np.concatenate([np.arange(rt.size), np.arange(rt.size)]),
    })
    ad.attrs["membership"] = ep[["day", "acct", "ring_id"]].drop_duplicates(
        ignore_index=True)
    ad.attrs["ring_endpoints"] = ep
    ad.attrs["ring_txn"] = {"day": day[rt], "score": np.asarray(score)[rt]}
    return ad


def _frame_token(ad: pd.DataFrame) -> str:
    """A key derived from the frame's CONTENTS, so a stale cache is impossible.

    THE FIX THIS REPLACES DID NOT WORK, and an audit reproduced that.

        `_ranks` and `_ring_structure` first keyed their caches on `len(ad)`.
        Mutating scores in place then reused ranks computed from the old
        values -- silently, inside the functions that produce every published
        budget metric.

        The first repair stamped a random token in `to_account_days` and keyed
        on that. It is no better: an in-place mutation does not change the
        token either, so the cache still served stale ranks. The comment
        claimed the invariant; the behaviour did not hold it. A narrated
        invariant is not an invariant.

    So the key is a digest of the bytes the cache actually depends on -- the
    score, the label, the day, the account, and the membership relation. One
    pass, no copies (memoryview, not tobytes), and correct by construction
    rather than by convention: if any of them changes, the key changes.

    Cost is a hash over a few hundred megabytes at HI-Large, against an
    `evaluate()` that runs for minutes. That is the right side of the trade.
    """
    h = hashlib.blake2b(digest_size=16)
    h.update(str(len(ad)).encode())
    for col in ("score", "y", "day", "acct", "other_max"):
        if col not in ad.columns:
            continue
        arr = np.ascontiguousarray(ad[col].to_numpy())
        h.update(col.encode())
        h.update(str(arr.dtype).encode())
        # datetime64 and object columns have no buffer protocol we can hash
        # directly; fall back to their integer view or their repr.
        try:
            h.update(memoryview(arr).cast("B"))
        except (TypeError, ValueError):
            h.update(np.asarray(arr).astype("datetime64[ns]").view("i8").tobytes()
                     if np.issubdtype(arr.dtype, np.datetime64)
                     else repr(arr.tolist()).encode())
    mem = ad.attrs.get("membership")
    if mem is not None:
        h.update(b"membership")
        h.update(str(len(mem)).encode())
        for col in mem.columns:
            arr = np.ascontiguousarray(mem[col].to_numpy())
            try:
                h.update(memoryview(arr).cast("B"))
            except (TypeError, ValueError):
                h.update(repr(arr.tolist()).encode())
    return h.hexdigest()


def ring_membership(ad: pd.DataFrame) -> pd.DataFrame:
    """The (day, acct, ring_id) relation carried alongside an account-day frame.

    Separate from the score table on purpose: one account-day can belong to
    several rings, so any column on `ad` would have to pick one and lose the
    rest. Falls back to the collapsed `ring_id` column only for frames built
    before this existed, which is strictly worse and is flagged as such.
    """
    mem = ad.attrs.get("membership")
    if mem is not None:
        return mem
    fallback = ad.loc[ad.ring_id.notna(), ["day", "acct", "ring_id"]]
    fallback.attrs["collapsed"] = True
    return fallback.drop_duplicates(ignore_index=True)


def _ranks(ad: pd.DataFrame) -> dict:
    """Per-day descending score ranks under three tie policies, computed once.

    `first` is the published policy; `min` and `max` bracket it. Ranking is the
    expensive part of every budget metric -- a groupby over ~6.2M account-days
    -- and the budget loop asks for it seven times, so the result is memoised
    on the frame and keyed by a CONTENT digest of the columns the ranking
    depends on -- not by length, which is what this line said for three audits
    after the fix. A length key is exactly the defect that was found: an
    in-place mutation keeps the length and changes the answer.
    """
    token = _frame_token(ad)
    cache = ad.attrs.get("_rank_cache")
    if cache is not None and cache.get("token") == token:
        return cache
    g = ad.groupby("day")["score"]
    cache = {"n": len(ad), "token": token}
    for method in ("first", "min", "max"):
        cache[method] = g.rank(ascending=False, method=method).to_numpy()
    ad.attrs["_rank_cache"] = cache
    return cache


def recall_at_budget(ad: pd.DataFrame, budget: int) -> dict:
    """Rank account-days within each day, take the top B, measure what we caught.

    The ranking is PER DAY because the review budget renews daily -- an
    investigator gets B slots today and B slots tomorrow, not B in total.
    """
    rk = _ranks(ad)
    y = (ad.y == 1).to_numpy()
    top = rk["first"] <= budget
    total_pos = int(y.sum())
    caught = int((y & top).sum())
    n_alerts = int(top.sum())

    # A perfect model catches min(B, positives_that_day) each day. Summing that
    # over days gives the highest recall this budget can possibly reach.
    per_day = ad[y].groupby("day").size()
    best = int(np.minimum(per_day.to_numpy(), budget).sum()) if len(per_day) else 0
    ceiling = best / total_pos if total_pos else np.nan
    recall = caught / total_pos if total_pos else np.nan

    # TIE SENSITIVITY, PUBLISHED RATHER THAN ASSUMED AWAY.
    #
    # rank(method="first") resolves ties by input row order, and gradient-
    # boosted ensembles emit repeated leaf scores in quantity. Row order here
    # comes from `row_number() over ()` with no semantic ordering, so a tie
    # straddling the budget boundary is decided by something with no meaning.
    #
    # `min` resolves every tie in a row's favour and `max` against it, so the
    # pair BRACKETS what any tie-breaking rule whatsoever could return. A wide
    # bracket means the published number is partly an artefact of row order; a
    # narrow one means it is not. Either way the reader gets to check, instead
    # of being told that bitwise-identical replay makes the policy sound. It
    # does not: replaying the same arbitrary choice twice is reproducible, not
    # meaningful, and those are different properties.
    straddle = int(((rk["min"] <= budget) & (rk["max"] > budget)).sum())
    opt = int((y & (rk["min"] <= budget)).sum())
    pess = int((y & (rk["max"] <= budget)).sum())

    return {
        f"recall@{budget}": recall,
        f"recall_ceiling@{budget}": ceiling,
        # The number to actually read: what fraction of the attainable did we get?
        f"recall_efficiency@{budget}": recall / ceiling if ceiling else np.nan,
        f"precision@{budget}": caught / n_alerts if n_alerts else np.nan,
        f"alerts_per_true_positive@{budget}": n_alerts / caught if caught else np.nan,
        f"tied_at_boundary@{budget}": straddle,
        f"recall_tie_optimistic@{budget}": opt / total_pos if total_pos else np.nan,
        f"recall_tie_pessimistic@{budget}": pess / total_pos if total_pos else np.nan,
    }


def _ring_structure(ad: pd.DataFrame):
    """Rings, their account-days and their transactions, as integer codes.

    Built once and memoised. Everything downstream -- observed ring_recall, the
    permutation null, the per-typology breakdown -- needs the same join, and on
    HI-Large it is a 243k-row merge into 6.2M.

    Eligible account-days are ordered DAY-MAJOR, and ring transactions too,
    because the null permutes within days and a day should be a slice rather
    than a groupby.
    """
    token = _frame_token(ad)
    cache = ad.attrs.get("_ring_cache")
    if cache is not None and cache.get("token") == token:
        return cache["value"]

    ep = ad.attrs.get("ring_endpoints")
    if ep is None:                       # frame built before this existed
        mem = ring_membership(ad)
        ep = mem.assign(rt=np.arange(len(mem)))
    value = None
    if not ep.empty:
        pos_df = pd.DataFrame({"day": ad["day"].to_numpy(),
                               "acct": ad["acct"].to_numpy(),
                               "_pos": np.arange(len(ad), dtype=np.int64)})
        r = ep.merge(pos_df, on=["day", "acct"], how="left")
        if r["_pos"].isna().any():
            raise ValueError(
                f"{int(r['_pos'].isna().sum())} ring endpoints matched no "
                f"account-day. Membership and scores disagree.")
        ep_pos = r["_pos"].to_numpy(dtype=np.int64)

        day_code_ad, day_uniques = pd.factorize(ad["day"].to_numpy(), sort=True)
        n_days = len(day_uniques)

        # --- eligible account-days, day-major -----------------------------
        elig0 = np.unique(ep_pos)                       # sorted by row position
        order = np.argsort(day_code_ad[elig0], kind="stable")
        elig = elig0[order]
        elig_day = day_code_ad[elig]
        inv = np.empty(elig0.size, dtype=np.int64)      # elig0 order -> day-major
        inv[order] = np.arange(elig0.size, dtype=np.int64)

        ep_elig = inv[np.searchsorted(elig0, ep_pos)]
        ep_rt = r["rt"].to_numpy(dtype=np.int64)
        mem_ring, ring_ids = pd.factorize(r["ring_id"].to_numpy(), sort=False)
        if (mem_ring < 0).any():
            raise ValueError("ring endpoints carry a null ring_id")

        # Endpoints sorted by eligible account-day, so the segmented max over
        # "this account-day's ring transactions" is a single reduceat.
        eo = np.argsort(ep_elig, kind="stable")
        ep_elig_s, ep_rt_s = ep_elig[eo], ep_rt[eo]
        ep_starts = np.flatnonzero(
            np.r_[True, ep_elig_s[1:] != ep_elig_s[:-1]])

        # --- ring transactions, day-major ---------------------------------
        rtab = ad.attrs.get("ring_txn")
        if rtab is not None:
            rt_day_raw, rt_score = rtab["day"], np.asarray(rtab["score"])
            rt_day = np.searchsorted(day_uniques, rt_day_raw)
            rt_order = np.argsort(rt_day, kind="stable")
            rt_day_s = rt_day[rt_order]
            rt_score_s = rt_score[rt_order]
            rt_inv = np.empty(rt_order.size, dtype=np.int64)
            rt_inv[rt_order] = np.arange(rt_order.size, dtype=np.int64)
            ep_rt_s = rt_inv[ep_rt_s]
            rt_starts = np.flatnonzero(np.r_[True, rt_day_s[1:] != rt_day_s[:-1]])
            rt_stops = np.r_[rt_starts[1:], rt_day_s.size]
        else:
            rt_score_s, rt_starts, rt_stops = None, None, None

        # --- the day's fixed, non-eligible account-days --------------------
        # These never move under the null (an account-day is eligible exactly
        # when a ring transaction touches it), so each day's scores are sorted
        # once and every draw binary-searches them.
        keep = np.ones(len(ad), dtype=bool)
        keep[elig] = False
        ne_day, ne_score = day_code_ad[keep], ad["score"].to_numpy()[keep]
        no = np.lexsort((ne_score, ne_day))
        ne_day_s, ne_score_s = ne_day[no], ne_score[no]
        ne_lo = np.searchsorted(ne_day_s, np.arange(n_days), side="left")
        ne_hi = np.searchsorted(ne_day_s, np.arange(n_days), side="right")

        elig_lo = np.searchsorted(elig_day, np.arange(n_days), side="left")
        elig_hi = np.searchsorted(elig_day, np.arange(n_days), side="right")

        value = {
            "ad_rows": elig,
            "elig_day": elig_day,
            "elig_lo": elig_lo, "elig_hi": elig_hi,
            "elig_other_max": ad["other_max"].to_numpy()[elig]
            if "other_max" in ad.columns else np.full(elig.size, -np.inf),
            "mem_elig": ep_elig, "mem_ring": mem_ring.astype(np.int64),
            "n_rings": len(ring_ids), "ring_ids": ring_ids,
            # Detection OPPORTUNITIES per ring: distinct member account-days.
            "ring_sizes": np.bincount(
                pd.DataFrame({"r": mem_ring, "e": ep_elig})
                .drop_duplicates().r.to_numpy(), minlength=len(ring_ids)),
            "ep_elig_s": ep_elig_s, "ep_rt_s": ep_rt_s, "ep_starts": ep_starts,
            "rt_score": rt_score_s, "rt_starts": rt_starts, "rt_stops": rt_stops,
            "ne_score": ne_score_s, "ne_lo": ne_lo, "ne_hi": ne_hi,
            "n_days": n_days,
        }

    ad.attrs["_ring_cache"] = {"n": len(ad), "token": token, "value": value}
    return value


def _elig_min_ranks(st: dict, v: np.ndarray) -> np.ndarray:
    """Per-day rank of every eligible account-day, ties resolved in its favour.

    Exact, not approximate: the day's non-eligible account-days are fixed and
    pre-sorted, so the count above `v` is a binary search; the count above `v`
    among eligible account-days comes from one day-major sort.
    """
    m = v.size
    elig_day = st["elig_day"]
    order = np.lexsort((-v, elig_day))
    vs, ds = v[order], elig_day[order]
    pos = np.arange(m, dtype=np.int64) - st["elig_lo"][ds]
    new = np.r_[True, (vs[1:] != vs[:-1]) | (ds[1:] != ds[:-1])]
    greater_elig_sorted = pos[new][np.cumsum(new) - 1]
    greater_elig = np.empty(m, dtype=np.int64)
    greater_elig[order] = greater_elig_sorted

    greater_ne = np.empty(m, dtype=np.int64)
    ne_score, ne_lo, ne_hi = st["ne_score"], st["ne_lo"], st["ne_hi"]
    for d in range(st["n_days"]):
        a, b = st["elig_lo"][d], st["elig_hi"][d]
        if a == b:
            continue
        arr = ne_score[ne_lo[d]:ne_hi[d]]
        greater_ne[a:b] = arr.size - np.searchsorted(arr, v[a:b], side="right")
    return 1 + greater_elig + greater_ne


def _elig_scores(st: dict, rt_score: np.ndarray) -> np.ndarray:
    """Account-day scores implied by a given assignment of ring-transaction
    scores: the max over this account-day's ring transactions, floored by what
    its non-ring transactions already give it."""
    ring_max = np.maximum.reduceat(rt_score[st["ep_rt_s"]], st["ep_starts"])
    return np.maximum(ring_max, st["elig_other_max"])


def _ring_hits(st: dict, alerted: np.ndarray) -> np.ndarray:
    return np.bincount(st["mem_ring"], weights=alerted[st["mem_elig"]],
                       minlength=st["n_rings"]) > 0


def _permutation_null(ad: pd.DataFrame, budgets, n_perm: int, seed: int) -> dict:
    """The null distribution of ring_recall, one draw serving every budget.

    THE ESTIMAND, stated so it can be disagreed with:

        H0: given the multiset of scores this model assigned to each day's
            ring transactions, and given every non-ring score unchanged, WHICH
            ring transaction receives which of those scores is independent of
            ring identity.

    A draw permutes ring-transaction scores within a day, rebuilds the affected
    account-day maxima, re-ranks against that day's untouched account-days, and
    recomputes ring_recall. Preserved exactly: the set of rings, every ring's
    size and day composition, the daily review budget, the day's score
    distribution, and -- crucially -- the fact that one transaction produces
    two account-days that rise and fall together.

    WHY NOT THE SIMPLER PERMUTATION. Reshuffling WHICH ring-member account-days
    are alerted, holding the daily count fixed, is far cheaper and was the
    first implementation. It is also wrong, and measurably so: a sender and a
    receiver account-day created by the same transaction carry the same score,
    so a model's ring hits are mechanically correlated whether or not it knows
    anything about rings. On scores drawn independently of ring membership that
    null returned lift 0.497 -- declaring a strong ring effect where none
    exists by construction. Any null that cannot say "nothing here" on data
    with nothing in it is not measuring anything.
    """
    st = _ring_structure(ad)
    if st is None or st["rt_score"] is None:
        return {}
    # Memoised per (draws, seed), NOT per budget: one draw is re-ranked once
    # and scored at every budget, so asking for seven budgets costs one pass,
    # not seven. `evaluate` primes the whole budget list before its loop.
    key = (int(n_perm), int(seed))
    cached = ad.attrs.get("_null_cache")
    if cached is None or cached.get("key") != key:
        cached = {"key": key, "value": {}}
        ad.attrs["_null_cache"] = cached
    want = [b for b in budgets if b not in cached["value"]]
    if want:
        rng = np.random.default_rng(seed)
        base = st["rt_score"]
        blocks = [(int(a), int(b)) for a, b in
                  zip(st["rt_starts"], st["rt_stops"], strict=True) if b - a > 1]
        fresh = {b: np.empty(n_perm, dtype=np.float64) for b in want}
        for i in range(n_perm):
            p = base.copy()
            for a, b in blocks:
                p[a:b] = rng.permutation(p[a:b])
            ranks = _elig_min_ranks(st, _elig_scores(st, p))
            for b in want:
                fresh[b][i] = _ring_hits(st, ranks <= b).mean()
        cached["value"].update(fresh)
    return {b: cached["value"][b] for b in budgets}


def ring_recall(ad: pd.DataFrame, budget: int, acct_day_recall: float | None = None,
                n_permutations: int = 1000, seed: int = 0) -> dict:
    """Fraction of rings with at least one member alerted -- AGAINST ITS NULL.

    WHY A NULL IS REQUIRED, NOT OPTIONAL

        A ring is caught if ANY of its account-days reaches the top k on its
        day, so a ring with m account-days gets m draws. ring_recall therefore
        rises with ring size and with test-window length, neither of which is
        skill. Quoted bare it reads as "we catch 87% of laundering" when the
        account-day recall is 9%.

        The first attempt at fixing this divided ring_recall by recall@k and
        called it `ring_recall_inflation`. That was wrong, and wrong in the
        direction that matters -- it ranks runs by test-window length, not by
        how much the metric flatters.

        NOTE, correcting an earlier version of this docstring: the numeric
        ordering does NOT reverse between rungs. Both metrics rank HI-Large
        above HI-Medium. What flips is the SIGN OF INTERPRETATION -- high
        inflation means bad, high lift means good -- so the same rung reads
        "worse" on one and "better" on the other. Saying "the ordering
        reverses" was literally false about the numbers, and was asserted from
        arithmetic done in someone's head rather than computed.

    THE NULL, AND WHY IT IS NOT A CLOSED FORM ANY MORE

        The published null was `mean(1 - (1-r)^m_i)` with r = recall@k over ALL
        positive account-days. Three separate things were wrong with it:

          1. WRONG POPULATION. r was pooled over every positive account-day,
             but 87% of HI-Large's positives carry no ring label at all. What
             the null needs is the rate at which RING-MEMBER account-days are
             alerted -- `ring_eligible_recall@k` below, a different number.
          2. WRONG INDEPENDENCE. It treated a ring's m member-days as m
             independent Bernoulli draws. Ranking happens per day under a
             budget, so same-day account-days COMPETE, and a transaction's two
             endpoints share a score outright.
          3. NO UNCERTAINTY. A point null against a point observation.

        `_permutation_null` replaces it; read its docstring for the estimand.
        Three p-values are emitted because they answer different questions:
        `ring_recall_null_p@k` (upper tail -- MORE rings than chance),
        `ring_recall_null_p_lower@k` (FEWER than chance) and
        `..._p_two_sided@k`. Quoting the upper-tail value near 1 as support for
        a lower-tail claim is a category error, and this file made it.
        `ring_recall_null_lo/hi@k` bound the null itself.

        The retired closed forms are still emitted -- `..._analytic@k` on the
        ring-eligible rate, `..._analytic_pooled@k` on the pooled rate. Not
        because either is defensible, but because the published 1.43 came from
        the second one and a reader is owed the arithmetic that connects the
        old number to the new one.

    Ring sizes are reported too, because the null depends on them and a reader
    cannot check it without them.
    """
    st = _ring_structure(ad)
    if st is None:
        return {f"ring_recall@{budget}": np.nan}

    rk = _ranks(ad)["first"]
    alerted = rk[st["ad_rows"]] <= budget
    observed = float(_ring_hits(st, alerted).mean())
    sizes = st["ring_sizes"]

    out = {
        f"ring_recall@{budget}": observed,
        # Budget-scoped even though the values do not depend on the budget.
        # Unscoped, a multi-budget call overwrote them, and they sat among
        # budget-suffixed keys reading as if they were budget-specific.
        f"n_rings@{budget}": int(st["n_rings"]),
        f"ring_size_median@{budget}": float(np.median(sizes)),
        f"ring_size_p90@{budget}": float(np.percentile(sizes, 90)),
        f"n_ring_account_days@{budget}": int(alerted.size),
        # The reference population the null is actually entitled to use.
        f"ring_eligible_recall@{budget}": float(alerted.mean()),
    }

    if n_permutations and n_permutations > 0 and st.get("rt_score") is not None:
        null = _permutation_null(ad, (budget,), int(n_permutations), seed).get(budget)
        if null is not None:
            # Compared LIKE FOR LIKE. The null ranks with ties resolved in the
            # row's favour, so the observed value it is divided by must too --
            # otherwise the tie policy leaks into the lift.
            obs_min = float(_ring_hits(
                st, _elig_min_ranks(st, _elig_scores(st, st["rt_score"])) <= budget
            ).mean())
            mean_null = float(null.mean())
            out[f"ring_recall_minrank@{budget}"] = obs_min
            out[f"ring_recall_null@{budget}"] = mean_null
            out[f"ring_recall_null_lo@{budget}"] = float(np.percentile(null, 2.5))
            out[f"ring_recall_null_hi@{budget}"] = float(np.percentile(null, 97.5))
            lift = round(obs_min / mean_null, 3) if mean_null > 0 else None
            out[f"ring_recall_lift@{budget}"] = lift
            # THE SAME NUMBER UNDER A NAME THAT SAYS WHAT IT IS.
            #
            # "lift" invites "the model has N times the ring skill of chance",
            # and this null cannot support that: it conditions on the model's
            # OWN per-day multiset of ring-transaction scores, so any ring
            # skill already expressed in that multiset is inside H0. What
            # varies is which ring each score lands on. So a value below 1
            # means the model's alerts CONCENTRATE into fewer distinct rings
            # than a ring-blind reassignment of the same scores -- which is
            # what account-volume features should do -- not that it is worse
            # than chance at finding rings.
            #
            # The old key is retained because every archived manifest carries
            # it; the new one is what prose should quote.
            out[f"ring_coverage_concentration@{budget}"] = lift
            # BOTH TAILS, LABELLED, because they answer different questions and
            # only one of them was being emitted.
            #
            # `ring_recall_null_p@k` counts null >= observed: it tests whether
            # the model covers MORE rings than chance. On HI-Large it returns
            # 1.000, and that was quoted in support of the claim that the model
            # covers FEWER rings than chance -- which is the opposite tail. A
            # p-value near 1 on the upper tail is not evidence for the lower
            # one; it is the absence of evidence for the upper one.
            #
            # The lower-tail value is what that claim needs, and it is now
            # computed rather than inferred from its complement.
            b = len(null)
            out[f"ring_recall_null_p@{budget}"] = float(
                (1 + int((null >= obs_min).sum())) / (b + 1))
            out[f"ring_recall_null_p_lower@{budget}"] = float(
                (1 + int((null <= obs_min).sum())) / (b + 1))
            out[f"ring_recall_null_p_two_sided@{budget}"] = float(min(
                1.0, 2 * min((1 + int((null >= obs_min).sum())) / (b + 1),
                             (1 + int((null <= obs_min).sum())) / (b + 1))))
            out[f"ring_null_permutations@{budget}"] = len(null)
            # THE SMALLEST p THIS MANY DRAWS CAN EXPRESS.
            #
            # With the add-one estimator and b draws, a tail count of zero
            # gives 1/(b+1) -- 0.000999 at b=1000. Every HI-Large seed reports
            # exactly that on the lower tail, and the paper wrote it as
            # "p = 0.001", which reads as a measurement when it is the
            # resolution limit. A reader cannot tell the two apart from the
            # p-value alone, so the floor is published beside it and the prose
            # is required to say "< 0.001".
            out[f"ring_recall_null_p_resolution@{budget}"] = float(1 / (b + 1))

    # The two closed forms, kept for continuity and comparison only.
    #
    # Emitted at EVERY budget, including the saturated ends. The first version
    # guarded on `0 < r < 1`, so the null vanished exactly when recall hit 0 or
    # 1 -- precisely when a ring number is least meaningful and the reader most
    # needs the comparison.
    r_elig = float(np.clip(out[f"ring_eligible_recall@{budget}"], 0.0, 1.0))
    out[f"ring_recall_null_analytic@{budget}"] = float(
        np.mean(1 - (1 - r_elig) ** sizes))
    if acct_day_recall is not None:
        r_pool = float(np.clip(acct_day_recall, 0.0, 1.0))
        pooled = float(np.mean(1 - (1 - r_pool) ** sizes))
        out[f"ring_recall_null_analytic_pooled@{budget}"] = pooled
        out[f"ring_recall_lift_analytic_pooled@{budget}"] = (
            round(observed / pooled, 3) if pooled > 0 else None)
    return out


REQUIRED_COLUMNS = ("event_date", "sender_id", "receiver_id", "is_laundering",
                    "ring_id")


def _validate(df: pd.DataFrame, score: np.ndarray) -> None:
    """Fail with a domain error, not an IndexError from inside sklearn.

    Every check here corresponds to a way this function was actually reachable
    with bad input: a caller passing the wrong column subset, a model emitting
    NaN for a row with an all-null feature vector, a single-class day slice
    from a narrow date filter.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"evaluate() needs columns {missing}; got {list(df.columns)}")
    if len(score) != len(df):
        raise ValueError(f"score has {len(score)} rows, frame has {len(df)}")
    if len(df) == 0:
        raise ValueError("evaluate() received an empty frame")
    if not np.isfinite(score).all():
        n = int((~np.isfinite(score)).sum())
        raise ValueError(f"{n} of {len(score)} scores are NaN or infinite")
    classes = pd.unique(df.is_laundering.dropna())
    if len(classes) < 2:
        raise ValueError(
            f"is_laundering has one class ({classes.tolist()}); ranking metrics "
            "are undefined. Widen the slice or use recall_at_budget directly.")


def evaluate(df: pd.DataFrame, score: np.ndarray,
             budgets=DEFAULT_BUDGETS, per_typology: bool = True,
             n_permutations: int = 1000, perm_seed: int = 0) -> dict:
    _validate(df, score)
    ad = to_account_days(df, score)
    pos = df[df.is_laundering == 1]
    out = {
        "n_account_days": len(ad),
        "n_positive_account_days": int((ad.y == 1).sum()),

        # UNIT SUFFIXES ARE NOT DECORATION.
        #
        # average_precision is computed on TRANSACTIONS; every budget metric
        # below is computed on ACCOUNT-DAYS. Reporting "average_precision
        # 0.3149" beside "precision@50 0.9062" without saying so puts two
        # different denominators in one sentence, and that is exactly what the
        # README did. The suffix makes the unit travel with the number into
        # every manifest, table and plot that consumes this dict.
        "average_precision__txn": float(average_precision_score(df.is_laundering, score)),
        # Reported once, deliberately de-emphasised. See module docstring.
        "roc_auc_footnote_only__txn": float(roc_auc_score(df.is_laundering, score)),

        # WHAT FRACTION OF POSITIVES THE RING DISCIPLINE ACTUALLY COVERS.
        #
        # The split is enforced on RING-PARTICIPATING accounts. Positives
        # carrying no ring label bypass it entirely -- neither dropped for
        # account overlap nor counted in ring_recall's denominator -- so every
        # ring-level claim silently applies to a sub-population nobody had
        # sized.
        #
        # ON ACCOUNT-DAYS, not transactions. The first version of this computed
        # `pos.ring_id.isna().mean()` over transactions, which made it exactly
        # `100 - typology_coverage_pct` -- algebraically the negation of a
        # metric that already existed, adding no information, while its own
        # comment claimed to describe account-days. Ring accounts transact more
        # per day, and the account-day score is a max, so the two numbers are
        # NOT the same and the account-day one is the one ring_recall is
        # denominated in.
        "pct_positive_acct_days_without_ring":
            round(100 * float(ad.loc[ad.y == 1, "ring_id"].isna().mean()), 2)
            if (ad.y == 1).any() else None,
    }
    # One permutation pass for the whole budget list, before the loop asks for
    # them one at a time.
    if n_permutations:
        _permutation_null(ad, tuple(budgets), int(n_permutations), perm_seed)
    for b in budgets:
        out.update(recall_at_budget(ad, b))
        # The retired closed-form null needs account-day recall at the SAME
        # budget, so this must come after recall_at_budget rather than beside it.
        out.update(ring_recall(ad, b, acct_day_recall=out.get(f"recall@{b}"),
                               n_permutations=n_permutations, seed=perm_seed))
    if per_typology and df.typology.notna().any():
        b = 50 if 50 in budgets else budgets[0]
        st = _ring_structure(ad)
        if st is not None:
            rk = _ranks(ad)["first"]
            alerted = rk[st["ad_rows"]] <= b
            hit = np.bincount(st["mem_ring"], weights=alerted[st["mem_elig"]],
                              minlength=st["n_rings"]) > 0
            # Same join as ring_recall, for the same reason: reading the
            # collapsed column assigned the WRONG typology to any account-day
            # belonging to more than one ring.
            ring2typ = df.dropna(subset=["ring_id"]).groupby("ring_id").typology.first()
            typ = pd.Series(st["ring_ids"]).map(ring2typ)
            per = {}
            for name, idx in pd.Series(np.arange(st["n_rings"])).groupby(typ.to_numpy()):
                sel = idx.to_numpy()
                per[name] = {"n_rings": int(sel.size),
                             f"ring_recall@{b}": float(hit[sel].mean())}
            out["per_typology"] = per
        # GOTCHA 2: typology is a nullable enrichment. Always state coverage.
        # Suffixed: this is over TRANSACTIONS, while its account-day
        # counterpart above is over account-days. They are not complements of
        # one another and were briefly reported as though they were.
        out["typology_coverage_pct__txn"] = round(100 * pos.ring_id.notna().mean(), 2)
    return out


def _dependence_clusters(ad: pd.DataFrame, pos: pd.DataFrame) -> np.ndarray:
    """Resampling units: connected components of the account-day/ring graph.

    WHY NOT `ring_id`, WHICH IS WHAT THIS USED TO DO.

        `ad.ring_id` is the COLLAPSED column -- built with `max` and documented
        three functions above as invalid for membership, because 4.288% of
        ringed account-days belong to more than one ring. Clustering on it
        silently reinstated the defect that `ring_recall` was fixed to avoid,
        inside the function that computes the published interval.

        It is also wrong in a second way that `max` cannot express: two rings
        that SHARE an account-day are not independent draws. Resampling them as
        separate clusters treats one dependency as two observations, which is
        the direction that narrows an interval.

    So the unit is a connected component of the bipartite graph joining
    positive account-days to the rings they belong to. An account-day in two
    rings merges those rings into one cluster, and so does a ring that touches
    an account-day already merged into another. Unringed positives remain their
    own cluster -- still anti-conservative, still documented as such.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    keys = pd.MultiIndex.from_arrays([pos["day"].to_numpy(), pos["acct"].to_numpy()])
    mem = ring_membership(ad)
    if mem.empty:
        return np.arange(len(pos))

    mkeys = pd.MultiIndex.from_arrays([mem["day"].to_numpy(), mem["acct"].to_numpy()])
    row = keys.get_indexer(mkeys)              # -1 where the account-day is not positive
    keep = row >= 0
    if not keep.any():
        return np.arange(len(pos))

    ring_code = pd.factorize(mem["ring_id"].to_numpy()[keep], sort=False)[0]
    n_pos, n_rings = len(pos), int(ring_code.max()) + 1
    r = row[keep]
    c = n_pos + ring_code
    g = coo_matrix((np.ones(r.size, dtype=np.int8), (r, c)),
                   shape=(n_pos + n_rings, n_pos + n_rings))
    _, labels = connected_components(g, directed=False)
    return labels[:n_pos]


def _empty_ci(budgets, budget: int, n: int, **extra) -> dict:
    """The SAME KEY SET on every return path.

    The early returns -- `n < 1`, no positives, fewer than two clusters --
    emitted only the unsuffixed pair, while the normal path also emitted
    `ci_lo@k` / `ci_hi@k`. A manifest reader then cannot tell "this budget had
    no interval" from "this run took a short path", and two runs of the same
    pipeline produce different schemas. Whatever is absent is present as NaN.
    """
    out = {"ci_lo": np.nan, "ci_hi": np.nan, "ci_budget": int(budget),
           "n_bootstrap": n, **extra}
    for b in budgets:
        out[f"ci_lo@{b}"] = np.nan
        out[f"ci_hi@{b}"] = np.nan
    return out


def bootstrap_ci(df: pd.DataFrame, score: np.ndarray, budget: int = 50,
                 n: int = 1000, seed: int = 0, budgets=None) -> dict:
    """Confidence interval on recall@budget, resampling at the RING level.

    EVERY BUDGET, NOT JUST ONE. This was called at `budget=50` and nowhere
    else, so six of the seven budgets in `DEFAULT_BUDGETS` -- and the HI-Large
    headline at 200 -- were published as point estimates with no interval at
    all. Everything expensive here (building account-days, ranking, clustering)
    is budget-independent, so the extra budgets cost one comparison and one
    sum each. Pass `budgets=` to get `ci_lo@k` / `ci_hi@k` for each; the
    unsuffixed `ci_lo`/`ci_hi` keep referring to `budget` so existing manifests
    stay comparable.

    One resample is shared across budgets on purpose: it is one bootstrap of
    the data read at several operating points, so the intervals are directly
    comparable with each other.

    WHY RINGS AND NOT TRANSACTIONS
        Transactions inside one ring are not independent -- they are one crime,
        observed several times. Resampling transactions would treat 50
        transactions from 6 rings as 50 independent samples and report an
        interval roughly sqrt(50/6) ~ 3x too narrow. The sampling unit has to be
        the unit of independence, which here is the ring.

    WHY THE RANKING IS HELD FIXED
        We rank once, mark each positive account-day caught / not caught, then
        resample those outcomes by cluster. The ranking is a property of the
        model's scores against the population that actually existed -- it is not
        something a resample gets to change. Re-ranking inside the loop is also
        what made an earlier version of this function quadratic: it concatenated
        ~6.2M unlabeled account-days and re-ranked them on every one of 500
        iterations, and did not finish in 10 minutes. This version is vectorised
        and runs in well under a second.

    CLUSTERS
        Labeled positives cluster by ring. The ~38% of positives with no ring
        cannot be ring-clustered, so each account becomes its own cluster.

        That is ANTI-conservative, not conservative as this docstring used to
        claim. Treating dependent positives as independent clusters shrinks
        the interval. With 87% of HI-Large positives unringed it is most of
        the sample, and it is why the bootstrap SE (~0.0013 on recall@200) is
        four times smaller than the seed-to-seed SD (~0.0056) -- the interval
        is measuring the wrong thing and measuring it too tightly.
    """
    # n=0 means "skip the bootstrap" -- a legitimate ask when the caller only
    # wants point estimates (the demo, a fast dev loop). It used to fall
    # through to np.percentile on an empty array and die with an IndexError
    # from deep inside numpy, which reads like a bug in the metric rather than
    # a value the caller chose.
    # ONE BUDGET SET, AND THE UNSUFFIXED PAIR MUST NAME ONE OF THEM.
    #
    # Two callers had drifted. The drift experiment evaluated (10, 50, 200) and
    # asked for intervals at all seven defaults, so four of them described
    # operating points the run never measured. `eval.run` accepted arbitrary
    # budgets and still hardcoded 50, so a caller asking only for budget 10 got
    # `ci_lo@10` PLUS an unsuffixed interval computed at a budget it had not
    # requested. Neither is detectable from the manifest afterwards, because
    # the unsuffixed keys do not say what they refer to.
    #
    # They do now, via `ci_budget`, and a `budget` outside `budgets` is a
    # caller bug rather than a silent one.
    budgets = tuple(budgets) if budgets else (budget,)
    if budget not in budgets:
        raise ValueError(
            f"bootstrap_ci: budget={budget} is not in budgets={budgets}, so "
            f"the unsuffixed ci_lo/ci_hi would describe an operating point "
            f"that was never evaluated. Pass a budget that is in the set.")

    if n < 1:
        return _empty_ci(budgets, budget, 0)

    rng = np.random.default_rng(seed)
    ad = to_account_days(df, score)
    ad["rank"] = ad.groupby("day")["score"].rank(ascending=False, method="first")

    pos = ad[ad.y == 1].copy()
    if pos.empty:
        return _empty_ci(budgets, budget, n, n_clusters=0)
    pos["caught"] = (pos["rank"] <= budget).astype(np.float64)
    pos["cluster"] = _dependence_clusters(ad, pos)

    g = pos.groupby("cluster", sort=False).caught.agg(["sum", "count"])
    caught, total = g["sum"].to_numpy(), g["count"].to_numpy()
    k = len(caught)
    if k < 2:
        return _empty_ci(budgets, budget, n, n_clusters=int(k))

    idx = rng.integers(0, k, size=(n, k))
    denom = total[idx].sum(axis=1)
    boot = caught[idx].sum(axis=1) / denom
    lo, hi = np.percentile(boot, [2.5, 97.5])
    out = {"ci_lo": float(lo), "ci_hi": float(hi),
           # WHICH budget the unsuffixed pair refers to. Without it a manifest
           # cannot be read back safely once callers use different sets.
           "ci_budget": int(budget),
           "n_clusters": int(k),
           "n_ring_clusters": int(pos.ring_id.notna().groupby(pos.cluster).any().sum()),
           "n_bootstrap": n}

    rank = pos["rank"].to_numpy()
    cluster = pos["cluster"].to_numpy()
    for b in budgets:
        c = pd.Series(rank <= b, dtype=np.float64).groupby(cluster, sort=False).sum().to_numpy()
        bb = c[idx].sum(axis=1) / denom
        blo, bhi = np.percentile(bb, [2.5, 97.5])
        out[f"ci_lo@{b}"] = float(blo)
        out[f"ci_hi@{b}"] = float(bhi)
    return out
