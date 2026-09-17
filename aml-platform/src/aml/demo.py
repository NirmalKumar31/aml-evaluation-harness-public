"""
A miniature AMLworld, generated on the fly, so the pipeline runs with no data.

WHY THIS EXISTS
    IBM AMLworld is 3-17 GB and licensed under CDLA-Sharing-1.0, so it cannot
    live in this repository. Without something else, a stranger who clones this
    can read the code and run the unit tests, but cannot watch the actual
    pipeline do anything -- which is most of what there is to see.

    So `make demo` generates a corpus with the same schema and the same shape
    (a negative background, plus FAN-OUT rings whose member transactions also
    appear in a patterns file), then runs EVERY REAL STAGE over it. Not a mock,
    not a shortcut path: the same ingest, the same reconcile, the same
    ring-aware split, the same feature SQL.

WHAT IT IS NOT
    The numbers it prints are meaningless. It is 900-odd rows of uniform noise
    with six planted rings; a model fitted on that says nothing about
    laundering. This proves the machinery runs, not that it works. The
    published results come from the real dataset -- see `make get-data`.

    Kept deliberately honest: the demo prints that caveat itself, so nobody
    screenshots a number from it.
"""
from __future__ import annotations

import random
from pathlib import Path

from aml import io

HEADER = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,"
          "Receiving Currency,Amount Paid,Payment Currency,Payment Format,"
          "Is Laundering")

# Enough rings that the ring-aware split has whole rings to place on each side
# of the cut, and enough background that history features are not all null.
N_RINGS = 6
RING_SIZE = 6
# Must exceed N_RINGS * (1 + RING_SIZE) = 42, since ring members are drawn
# from this pool rather than given their own namespace (see synthetic_corpus).
BACKGROUND_ACCOUNTS = 120
BACKGROUND_PER_DAY = 220
DAYS = 14


def _row(day: int, minute: int, sender: str, receiver: str,
         amount: float, laundering: int) -> str:
    return (f"2022/09/{day:02d} {minute // 60:02d}:{minute % 60:02d},"
            f"010,{sender},011,{receiver},{amount:.2f},US Dollar,"
            f"{amount:.2f},US Dollar,ACH,{laundering}")


def synthetic_corpus(root) -> tuple[Path, Path]:
    """Write trans.csv and patterns.txt into `root`; return both paths.

    The pattern rows are the SAME STRINGS as the corresponding transaction
    rows, because reconcile joins them on content (event_time, both account
    ids, rounded amount, payment format) rather than on a shared key. Building
    the two files from one source of truth is the only way to guarantee they
    reconcile; a hand-written pair drifts apart silently and labels zero rings.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    rows: list[str] = []
    ring_rows: list[tuple[int, str]] = []

    for day in range(1, DAYS + 1):
        for i in range(BACKGROUND_PER_DAY):
            rows.append(_row(
                day, rng.randrange(0, 1440),
                f"BG{i % BACKGROUND_ACCOUNTS:04d}",
                f"BG{(i * 7 + day) % BACKGROUND_ACCOUNTS:04d}",
                rng.uniform(10, 9000), 0))

    # Ring members are drawn from the SAME account pool as the background, not
    # given their own "HUB"/"MULE" namespace. This mirrors a real defect this
    # project hit once: synthetic laundering accounts that appear nowhere else
    # have no prior history, so the model scores a perfect result by detecting
    # "an account I have never seen before" rather than detecting laundering.
    # A demo that prints average_precision 1.0 teaches the wrong lesson about
    # what the pipeline does.
    ring_accounts = rng.sample(range(BACKGROUND_ACCOUNTS), N_RINGS * (1 + RING_SIZE))
    for r in range(N_RINGS):
        pool = ring_accounts[r * (1 + RING_SIZE):(r + 1) * (1 + RING_SIZE)]
        hub, day = f"BG{pool[0]:04d}", 2 + r * 2
        for k in range(RING_SIZE):
            # Amounts from the SAME distribution as the background. Round
            # numbers like 1000+k would let `amount_roundness` alone separate
            # the classes perfectly, and the demo would print AP 1.0 -- which
            # is exactly the kind of too-good number this project exists to be
            # suspicious of. The signal left is the FAN-OUT structure itself.
            line = _row(day, 100 + k * 30, hub, f"BG{pool[k + 1]:04d}",
                        rng.uniform(10, 9000), 1)
            rows.append(line)
            ring_rows.append((r, line))

    csv = root / "trans.csv"
    csv.write_text(HEADER + "\n" + "\n".join(rows) + "\n")

    blocks = []
    for r in range(N_RINGS):
        body = "\n".join(line for ring, line in ring_rows if ring == r)
        blocks.append(
            f"BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max {RING_SIZE}-degree Fan-Out\n"
            f"{body}\nEND LAUNDERING ATTEMPT - FAN-OUT")
    patterns = root / "patterns.txt"
    patterns.write_text("\n".join(blocks) + "\n")
    return csv, patterns


def run(dest: str = "data/demo", cut: str = "2022-09-09") -> dict:
    """Generate the corpus, then run every stage over it."""
    from aml.features.build import build as build_features
    from aml.ingest.normalize import normalize
    from aml.models.train import train
    from aml.patterns.parse import parse
    from aml.patterns.reconcile import reconcile
    from aml.splits.ring_aware import build as build_splits

    out = Path(dest)
    csv, patterns = synthetic_corpus(out / "raw")

    def step(n, label, fn):
        print(f"  [{n}/6] {label}", flush=True)
        return fn()

    step(1, "normalize      csv -> bronze",
         lambda: normalize(str(csv), str(out / "bronze"), hash_input=False))
    step(2, "parse-patterns patterns.txt -> rings",
         lambda: parse(str(patterns), str(out / "patterns")))
    step(3, "reconcile      attach ring_id + typology to transactions",
         lambda: reconcile(str(out / "bronze"), str(out / "patterns"),
                           str(out / "labeled")))
    step(4, "build-splits   ring-participant-disjoint temporal split",
         lambda: build_splits(str(out / "patterns"), str(out / "labeled"), cut,
                              str(out / "splits"), min_test_positives=1))
    step(5, "build-features causal windows, all frames end 1 MINUTE PRECEDING",
         lambda: build_features(str(out / "labeled" / "txns_labeled"),
                                str(out / "features")))
    m = step(6, "train          gbdt + budget-aware evaluation",
             lambda: train(str(out / "features"), str(out / "splits"),
                           str(out / "models"), model="gbdt", bootstrap=0))

    # COUNT THE ROWS, DO NOT DESCRIBE THEM.
    #
    # This banner used to say "~900 rows" while the generator emitted 3,116,
    # and "a model fitted on it cannot detect anything" while the planted rings
    # made it score near 1.0. Both were written once and never re-checked --
    # the same failure mode as every hand-typed number this project has had to
    # retract, in the one place that exists to tell a newcomer what to trust.
    rows = int(m.get("train_rows", 0)) + int(m.get("test_rows", 0))
    print("\n" + "=" * 68)
    print("  Every stage ran. That is the entire claim.")
    print()
    print(f"  THESE NUMBERS ARE MEANINGLESS. {rows:,} generated rows with")
    print("  planted rings, built to exercise the pipeline, not to be")
    print("  detectable or undetectable. The demo verifies that the stages")
    print("  COMPOSE; it says nothing whatever about performance.")
    print("  The published results come from the real dataset:")
    print("  see `make get-data`, then `make all VARIANT=Small`.")
    print("=" * 68)
    return m


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default="data/demo")
    ap.add_argument("--cut", default="2022-09-09")
    a = ap.parse_args(argv)
    print(f"Generating a miniature AMLworld in {a.dest}/raw and running it.\n")
    m = run(a.dest, a.cut)
    print(io.json_line({k: v for k, v in m.items()
                      if isinstance(v, (int, float, str))}, indent=2)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
