"""Metric tests. These pin the definition of the headline number."""
import numpy as np
import pandas as pd
import pytest

from aml.eval.metrics import bootstrap_ci, recall_at_budget, ring_recall, to_account_days


def _df(rows):
    """rows: (day, sender, receiver, is_laundering, ring_id)"""
    d = pd.DataFrame(rows, columns=["event_date", "sender_id", "receiver_id",
                                    "is_laundering", "ring_id"])
    d["typology"] = np.where(d.ring_id.notna(), "CYCLE", None)
    return d


def test_perfect_ranking_is_recall_one():
    df = _df([("d1", "A", "B", 1, 0.0)] + [("d1", f"N{i}", f"M{i}", 0, None)
                                           for i in range(100)])
    score = np.array([1.0] + [0.0] * 100)
    assert recall_at_budget(to_account_days(df, score), 2)["recall@2"] == 1.0


def test_worst_ranking_is_recall_zero():
    df = _df([("d1", "A", "B", 1, 0.0)] + [("d1", f"N{i}", f"M{i}", 0, None)
                                           for i in range(100)])
    score = np.array([0.0] + [1.0] * 100)
    assert recall_at_budget(to_account_days(df, score), 2)["recall@2"] == 0.0


def test_a_day_with_no_positives_returns_nan_not_zero():
    """Zero would silently drag the average down; NaN says 'no information'."""
    df = _df([("d1", f"N{i}", f"M{i}", 0, None) for i in range(10)])
    r = recall_at_budget(to_account_days(df, np.zeros(10)), 5)
    assert np.isnan(r["recall@5"])


def test_budget_renews_each_day():
    """B slots today AND B slots tomorrow -- not B in total. A model that wins
    on day 1 must not spend day 2's budget."""
    rows, scores = [], []
    for day in ("d1", "d2"):
        rows.append((day, "A", "B", 1, 0.0))
        scores.append(1.0)
        for i in range(50):
            rows.append((day, f"N{i}", f"M{i}", 0, None))
            scores.append(0.0)
    ad = to_account_days(_df(rows), np.array(scores))
    # Each day has 2 positive account-days (the sender AND the receiver), so a
    # budget of 2 is what covers one day's worth. Under a GLOBAL budget of 2 we
    # would catch day 1 only and score 0.5; because the budget renews daily we
    # catch all four.
    assert (ad.y == 1).sum() == 4
    assert recall_at_budget(ad, 2)["recall@2"] == 1.0
    assert recall_at_budget(ad, 1)["recall@1"] == 0.5   # 1 of 2 slots each day


def test_one_transaction_makes_two_account_days():
    """Either party can be the account an investigator is told to review."""
    ad = to_account_days(_df([("d1", "A", "B", 1, 0.0)]), np.array([0.9]))
    assert len(ad) == 2
    assert set(ad.acct) == {"A", "B"}
    assert (ad.y == 1).all()


def test_account_day_is_positive_if_any_transaction_that_day_is():
    df = _df([("d1", "A", "B", 0, None), ("d1", "A", "C", 1, 0.0)])
    ad = to_account_days(df, np.array([0.1, 0.9]))
    a = ad[ad.acct == "A"].iloc[0]
    assert a.y == 1 and a.score == 0.9        # positive, and scored by its max


def test_ring_recall_needs_only_one_member_alerted():
    """Catching one account opens the case and unravels the rest."""
    rows = [("d1", "A", "B", 1, 7.0), ("d1", "C", "D", 1, 7.0)]
    rows += [("d1", f"N{i}", f"M{i}", 0, None) for i in range(50)]
    score = np.array([1.0, 0.0] + [0.5] * 50)   # only the first pair ranks top
    # ring_recall returns a dict now: the bare number is not publishable
    # without the size-matched null it is compared against.
    out = ring_recall(to_account_days(_df(rows), score), 2)
    assert out["ring_recall@2"] == 1.0
    assert out["n_rings@2"] == 1


def test_bootstrap_interval_brackets_the_point_estimate():
    rng = np.random.default_rng(0)
    rows, scores = [], []
    for ring in range(40):
        for _ in range(3):
            rows.append(("d1", f"S{ring}", f"R{ring}", 1, float(ring)))
            scores.append(rng.uniform(0.5, 1.0))
    for i in range(2000):
        rows.append(("d1", f"N{i}", f"M{i}", 0, None))
        scores.append(rng.uniform(0, 1))
    df, score = _df(rows), np.array(scores)
    point = recall_at_budget(to_account_days(df, score), 50)["recall@50"]
    ci = bootstrap_ci(df, score, budget=50, n=400, seed=0)
    assert ci["ci_lo"] <= point <= ci["ci_hi"]
    assert ci["n_ring_clusters"] == 40


def test_bootstrap_clusters_by_ring_not_by_row():
    """40 rings x 3 account-days must resample as 40 units, not 120.
    Getting this wrong reports an interval ~sqrt(3)x too narrow."""
    rows, scores = [], []
    for ring in range(40):
        for k in range(3):
            rows.append(("d1", f"S{ring}_{k}", f"R{ring}_{k}", 1, float(ring)))
            scores.append(1.0 if ring < 20 else 0.0)
    for i in range(500):
        rows.append(("d1", f"N{i}", f"M{i}", 0, None))
        scores.append(0.5)
    ci = bootstrap_ci(_df(rows), np.array(scores), budget=50, n=400, seed=0)
    assert ci["n_clusters"] == 40


def test_bootstrap_is_fast():
    """Regression guard. An earlier version re-ranked every account-day inside
    the loop and did not finish in 10 minutes on real data."""
    import time
    rng = np.random.default_rng(0)
    rows = [("d1", f"S{i}", f"R{i}", 1, float(i % 60)) for i in range(600)]
    rows += [("d1", f"N{i}", f"M{i}", 0, None) for i in range(60_000)]
    score = rng.random(len(rows))
    t0 = time.time()
    bootstrap_ci(_df(rows), score, budget=50, n=1000, seed=0)
    assert time.time() - t0 < 15


def test_recall_ceiling_is_reported_when_the_budget_cannot_reach_everything():
    """The trap this catches: 4 positives on one day with a budget of 1 means
    recall@1 can never exceed 0.25. Reporting 0.25 as if 1.0 were reachable
    makes a perfect model look broken."""
    rows = [("d1", f"S{i}", f"R{i}", 1, float(i)) for i in range(4)]
    rows += [("d1", f"N{i}", f"M{i}", 0, None) for i in range(50)]
    score = np.array([1.0, 0.9, 0.8, 0.7] + [0.0] * 50)   # a PERFECT ranking
    ad = to_account_days(_df(rows), score)
    r = recall_at_budget(ad, 1)
    assert r["recall@1"] == pytest.approx(0.125)          # 1 of 8 account-days
    assert r["recall_ceiling@1"] == pytest.approx(0.125)  # ...and 0.125 is the max
    assert r["recall_efficiency@1"] == pytest.approx(1.0)  # so we scored perfectly


def test_ceiling_is_one_when_the_budget_is_ample():
    rows = [("d1", "A", "B", 1, 0.0)] + [("d1", f"N{i}", f"M{i}", 0, None)
                                         for i in range(50)]
    r = recall_at_budget(to_account_days(_df(rows), np.array([1.0] + [0.0] * 50)), 200)
    assert r["recall_ceiling@200"] == 1.0
    assert r["recall@200"] == 1.0 and r["recall_efficiency@200"] == 1.0


def test_efficiency_separates_a_bad_model_from_a_tight_budget():
    rows = [("d1", f"S{i}", f"R{i}", 1, float(i)) for i in range(4)]
    rows += [("d1", f"N{i}", f"M{i}", 0, None) for i in range(50)]
    bad = np.array([0.0] * 4 + [1.0] * 50)                # ranks positives LAST
    r = recall_at_budget(to_account_days(_df(rows), bad), 1)
    assert r["recall_ceiling@1"] == pytest.approx(0.125)  # same tight budget
    assert r["recall_efficiency@1"] == 0.0                # but the model is bad


def test_budget_metrics_are_affine_transforms_of_one_measurement():
    """recall@k, recall_efficiency@k and precision@k are NOT three measurements.

    For a fixed test set both `n_alerts = sum_d min(k, N_d)` and
    `best = sum_d min(k, P_d)` are score-INDEPENDENT constants, so all three
    are `caught@k` times a constant. Verified on the real HI-Large run, where
    the ratios are identical to six decimals across three seeds:

        eff/precision = 1.291000    eff/recall = 19.3471

    This survived three audit rounds because it lives in the artifacts, so no
    provenance check can see it. Its consequence is that publishing a "26%
    seed spread" for each of the three reports ONE number three times, and
    that `_recommend` gating on efficiency spread is gating on precision
    spread.

    Asserted on the CONSTANT rather than on correlation: an identity forces
    the ratio to be bit-identical, while a merely 0.99-correlated pair varies
    by ~1% -- about 1e7 times this tolerance. So two score vectors are enough
    and no seeds are needed.
    """
    rows = [("d1", f"A{i}", f"B{i}", i % 3 == 0, None) for i in range(40)]
    rows += [("d2", f"C{i}", f"D{i}", i % 4 == 0, None) for i in range(40)]
    ratios = []
    for scale in (1.0, 0.3):
        rng = np.random.default_rng(int(scale * 100))
        score = rng.random(len(rows)) * scale
        m = recall_at_budget(to_account_days(_df(rows), score), 5)
        ratios.append(m["recall_efficiency@5"] / m["precision@5"])
    assert abs(ratios[0] - ratios[1]) < 1e-9, (
        f"efficiency/precision should be a score-independent constant; got "
        f"{ratios}. If this ever fails the identity has been broken, which "
        f"would be good news -- update the docs that describe it.")
