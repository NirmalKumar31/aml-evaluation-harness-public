"""
Drift schedules: the target typology mix for each time bucket.

WHY THIS EXISTS
    The original project idea was "models decay over time, measure it". We
    tested whether IBM's data actually drifts and it does not: every one of the
    8 typologies sits at ~12.5% in every week, Cramer's V = 0.075. That is
    negligible -- the generator holds the mix constant by construction.

    So we BUILD the drift instead of hoping for it. Because we hold ring-level
    typology labels, we can resample which ring shapes appear in which bucket
    and get a non-stationary mix with EXACT ground truth.

WHY THAT IS BETTER THAN FINDING DRIFT IN THE WILD
    In the wild you never know the true magnitude, so you can report one
    number. Here we control it, so we can report effect size AS A FUNCTION OF
    drift magnitude -- a curve instead of a point.

THE HONESTY REQUIREMENT (non-negotiable)
    Every mention of a result from this must say the drift is INDUCED, not
    observed. The framing that works:

        "IBM's typology mix is stationary by construction -- I measured
         Cramer's V = 0.075 -- so I built a controlled drift generator on top
         of its ring-level labels, which gives exact ground truth and lets me
         report effect size as a function of drift magnitude."

    That is a stronger statement than pretending the drift was found.
"""
import numpy as np

TYPOLOGIES = ["FAN-OUT", "FAN-IN", "CYCLE", "BIPARTITE",
              "STACK", "SCATTER-GATHER", "GATHER-SCATTER", "RANDOM"]

# What IBM actually ships: uniform, and stationary week to week.
STATIONARY = {t: 1.0 / len(TYPOLOGIES) for t in TYPOLOGIES}

# The regime we drift TOWARDS. CYCLE and STACK take over; the fan patterns
# nearly vanish. Chosen because those two are structurally the most different
# from each other and from the fans, so a detector tuned on a uniform mix has
# the most to lose.
TARGET_MIX = {
    "FAN-OUT": 0.02, "FAN-IN": 0.02, "CYCLE": 0.40, "BIPARTITE": 0.03,
    "STACK": 0.40, "SCATTER-GATHER": 0.05, "GATHER-SCATTER": 0.05, "RANDOM": 0.03,
}

# How far along the drift each bucket sits, before magnitude is applied.
# Buckets 0 and 1 are the stable regime the model gets trained on; the change
# starts at bucket 2. A step rather than a smooth ramp, because a regime change
# is what an AML team actually experiences -- a new laundering fashion appears.
DEFAULT_RAMP = [0.0, 0.0, 0.5, 1.0]


def make_schedule(n_buckets: int = 4, magnitude: float = 1.0,
                  ramp: list[float] | None = None,
                  target: dict | None = None) -> list[dict]:
    """Target typology mix per bucket.

    magnitude is the knob the sensitivity curve sweeps:
        0.0  -> every bucket stationary (the control; should show NO decay)
        0.5  -> half the shift
        1.0  -> the full TARGET_MIX by the last bucket

    Returns a list of {typology: share} dicts, one per bucket, each summing to 1.
    """
    if not 0.0 <= magnitude <= 1.0:
        raise ValueError(f"magnitude must be in [0, 1], got {magnitude}")
    target = target or TARGET_MIX
    ramp = ramp or DEFAULT_RAMP
    if len(ramp) < n_buckets:
        # Extend a short ramp by holding its last value.
        ramp = list(ramp) + [ramp[-1]] * (n_buckets - len(ramp))

    out = []
    for b in range(n_buckets):
        w = magnitude * ramp[b]
        mix = {t: (1 - w) * STATIONARY[t] + w * target[t] for t in TYPOLOGIES}
        s = sum(mix.values())
        out.append({t: v / s for t, v in mix.items()})   # renormalise for float drift
    return out


def cramers_v(counts: np.ndarray) -> tuple[float, float, float]:
    """(chi2, p, Cramer's V) for a bucket x typology contingency table.

    Cramer's V is the EFFECT SIZE and it is the number that matters. The
    baseline measurement on real IBM data was chi2 = 643.8, p = 1.3e-75,
    V = 0.075 -- overwhelming significance, negligible effect. That is the
    canonical trap this project exists to avoid, so we always report V next to
    p and never quote p alone.
    """
    from scipy import stats
    chi2, p, _, _ = stats.chi2_contingency(counts)
    n = counts.sum()
    v = float(np.sqrt(chi2 / (n * (min(counts.shape) - 1))))
    return float(chi2), float(p), v
