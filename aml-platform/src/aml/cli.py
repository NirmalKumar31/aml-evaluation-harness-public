"""One entrypoint per pipeline component. Same code local and in the cloud.

Exit codes are part of the contract with the orchestrator: 0 ok, 1 transient
(retry), 2 correctness (never retry). See aml/exits.py for why an unrecognised
failure counts as correctness.
"""
import argparse
import contextlib
import sys
import traceback

from aml import exits, io


def _model_names():
    """The registered models, imported lazily so `aml --help` stays fast and
    does not require sklearn or lightgbm to be importable."""
    from aml.models.train import MODELS
    return list(MODELS)


def _protocols():
    # Same rule as _model_names: derived, never restated. A hardcoded list is a
    # second copy of the same fact, and the second copy is the one that goes
    # stale -- `lgbm` died at argparse for exactly this reason.
    from aml.splits.ring_aware import PROTOCOLS
    return list(PROTOCOLS)


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, built separately from dispatch so it can be
    inspected without running anything.

    Split out because a test needs to assert that every runner parameter the
    manifest records is actually reachable from the command line -- `evaluate`
    honoured a `seed` that no flag could set, and every archived evaluate
    manifest records seed 0 as a result."""
    p = argparse.ArgumentParser(prog="aml")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("normalize", help="raw CSV -> day-partitioned Parquet")
    n.add_argument("--src", required=True)
    n.add_argument("--dest", required=True)
    n.add_argument("--manifest-dir", default=None)
    n.add_argument("--no-hash", action="store_true",
                   help="skip input sha256 (faster on 17 GB files)")

    pp = sub.add_parser("parse-patterns", help="Patterns.txt -> rings tables")
    pp.add_argument("--src", required=True)
    pp.add_argument("--dest", required=True)

    rc = sub.add_parser("reconcile-labels", help="join rings onto transactions")
    rc.add_argument("--txns", required=True)
    rc.add_argument("--patterns", required=True)
    rc.add_argument("--dest", required=True)

    sw = sub.add_parser("split-sweep", help="diagnostic: cost/benefit of each cut point")
    sw.add_argument("--patterns", required=True)
    sw.add_argument("--labeled", required=True)

    bs = sub.add_parser("build-splits", help="ring-participant-disjoint temporal split")
    bs.add_argument("--patterns", required=True)
    bs.add_argument("--labeled", required=True)
    bs.add_argument("--cut", required=True, help="cut time, e.g. 2022-09-11")
    bs.add_argument("--dest", required=True)
    bs.add_argument("--min-test-positives", type=int, default=100)
    bs.add_argument("--protocol", choices=_protocols(), default="ring-aware",
                    help="naive = plain temporal cut, no ring discipline. Exists to be measured against, not used.")

    dm = sub.add_parser("demo", help="generate a tiny corpus and run every stage")
    dm.add_argument("--dest", default="data/demo")
    dm.add_argument("--cut", default="2022-09-09")

    bf = sub.add_parser("build-features", help="labeled txns -> feature table")
    bf.add_argument("--src", required=True)
    bf.add_argument("--dest", required=True)
    bf.add_argument("--threads", type=int, default=None)
    bf.add_argument("--memory-limit", default=None)
    # Where DuckDB spills. Unset means the working directory, which in a
    # container is the image's writable overlay on the node OS disk -- this
    # stage is an unbounded-frame window pass over 2x N account-events and
    # spills tens of GB, so filling that disk at hour four is a real failure.
    bf.add_argument("--temp-directory", default=None,
                    help="DuckDB spill location. Point at a mounted data disk "
                         "for the large runs; the default is the working dir.")

    tm = sub.add_parser("train", help="fit on train split, evaluate on test split")
    tm.add_argument("--features", required=True)
    tm.add_argument("--splits", required=True)
    tm.add_argument("--dest", required=True)
    # DuckDB's default memory_limit is 80% of SYSTEM ram, which is wrong when
    # the same process also preallocates the feature matrix -- at HI-Large the
    # two budgets summed to 40 GB on a 31 GB machine and the container was
    # OOM-killed in 61 seconds. Unset means "compute it from the row count".
    tm.add_argument("--memory-limit", default=None)
    tm.add_argument("--temp-directory", default=None,
                    help="DuckDB spill location for the sort; point at a data "
                         "disk for the large runs")
    # Derived from the MODELS table, not restated. A hardcoded list here is a
    # second copy of the same fact: adding "lgbm" to MODELS left this untouched
    # and the run died at argparse after the image had been rebuilt and the job
    # dispatched -- the cheapest possible failure, arriving at the most
    # expensive possible moment.
    tm.add_argument("--model", default="gbdt", choices=sorted(_model_names()))
    tm.add_argument("--seed", type=int, default=0)
    tm.add_argument("--bootstrap", type=int, default=500)
    tm.add_argument("--sample", type=float, default=1.0,
                    help="fraction of rows, deterministic by hash. 0.01 = fast dev loop")
    tm.add_argument("--no-resume", action="store_true",
                    help="ignore any GBDT checkpoint and start from iteration 0")

    ev = sub.add_parser("evaluate", help="recompute metrics from saved scores")
    ev.add_argument("--features", required=True)
    ev.add_argument("--splits", required=True)
    ev.add_argument("--scores", required=True)
    ev.add_argument("--dest", required=True)
    ev.add_argument("--model", default="gbdt", choices=sorted(_model_names()))
    # SEED WAS NEVER REACHABLE FROM HERE.
    #
    # eval.run.run() has taken a `seed` since it was written, and its own
    # comment says "seed is here because it changes ci_lo/ci_hi. Omitting a
    # parameter that moves a reported number is the same defect as omitting
    # the feature set." The CLI then omitted it, so every archived evaluate
    # manifest records seed=0 -- including the ones scoring model seeds 1 and
    # 2. The defect the comment names was committed two lines below the
    # comment naming it.
    ev.add_argument("--seed", type=int, default=0)
    ev.add_argument("--bootstrap", type=int, default=1000)
    ev.add_argument("--permutations", type=int, default=1000,
                    help="draws for the ring-recall permutation null "
                         "(0 disables it)")

    pl = sub.add_parser("plant-leak", help="build a deliberately leaky feature table")
    pl.add_argument("--labeled", required=True)
    pl.add_argument("--dest", required=True)
    pl.add_argument("--kind", default="reversed_window",
                    choices=["reversed_window", "future_counterparty", "target"])

    ms = sub.add_parser("model-stability",
                        help="find a configuration whose reported numbers hold still")
    ms.add_argument("--features", required=True)
    ms.add_argument("--splits", required=True)
    ms.add_argument("--dest", required=True)
    ms.add_argument("--seeds", default="0,1,2,3,4")
    ms.add_argument("--configs", default=None,
                    help="comma-separated subset of the named candidates")
    ms.add_argument("--sample", type=float, default=1.0)

    sw2 = sub.add_parser("leak-sweep",
                         help="replicated leak detection with a permuted-leak negative control")
    sw2.add_argument("--features", required=True)
    sw2.add_argument("--splits", required=True)
    sw2.add_argument("--leak-root", required=True,
                     help="directory containing <kind>/leak.parquet per channel")
    sw2.add_argument("--dest", required=True)
    sw2.add_argument("--seeds", default="0,1,2,3,4",
                     help="comma-separated. More seeds = a tighter noise floor")
    sw2.add_argument("--iters", type=int, default=300,
                     help="MUST match the headline model, or the harness validates "
                          "a configuration nobody reports")
    sw2.add_argument("--sample", type=float, default=1.0)

    md = sub.add_parser("make-drift", help="resample rings to induce a typology-mix drift")
    md.add_argument("--patterns", required=True)
    md.add_argument("--dest", required=True)
    md.add_argument("--buckets", type=int, default=4)
    md.add_argument("--magnitude", type=float, default=1.0,
                    help="0 = stationary control, 1 = full drift")
    md.add_argument("--seed", type=int, default=0)
    md.add_argument("--rings-per-bucket", type=int, default=None)
    md.add_argument("--train-buckets", type=int, default=2,
                    help="buckets below this draw from source pool A, rest from B")

    sp_ = sub.add_parser("splice-drift", help="real negatives + induced laundering")
    sp_.add_argument("--labeled", required=True)
    sp_.add_argument("--drift", required=True)
    sp_.add_argument("--dest", required=True)
    sp_.add_argument("--seed", type=int, default=0)

    dx = sub.add_parser("drift-experiment", help="frozen vs 3 retraining strategies")
    dx.add_argument("--features", required=True)
    dx.add_argument("--drift", required=True)
    dx.add_argument("--dest", required=True)
    dx.add_argument("--seed", type=int, default=0)
    dx.add_argument("--iters", type=int, default=150)
    dx.add_argument("--bootstrap", type=int, default=500)
    dx.add_argument("--sample", type=float, default=1.0)

    for sp in (n, pp, rc, bs, bf, tm, ev, pl, md, sp_):
        sp.add_argument("--force", action="store_true",
                        help="ignore the cache and rerun this stage")
    return p


def _dispatch(argv=None):
    p = build_parser()

    a = p.parse_args(argv)
    if a.cmd == "normalize":
        from aml.ingest.normalize import normalize
        normalize(a.src, a.dest, a.manifest_dir, hash_input=not a.no_hash, force=a.force)
    elif a.cmd == "parse-patterns":
        from aml.patterns.parse import parse
        parse(a.src, a.dest, force=a.force)
    elif a.cmd == "reconcile-labels":
        from aml.patterns.reconcile import reconcile
        reconcile(a.txns, a.patterns, a.dest, force=a.force)
    elif a.cmd == "split-sweep":
        from aml.splits.ring_aware import sweep
        print(sweep(a.patterns, a.labeled).to_string(index=False))
    elif a.cmd == "build-splits":
        from aml.splits.ring_aware import build
        build(a.patterns, a.labeled, a.cut, a.dest,
              min_test_positives=a.min_test_positives, force=a.force,
              protocol=a.protocol)
    elif a.cmd == "demo":
        from aml.demo import run as demo_run
        demo_run(a.dest, a.cut)

    elif a.cmd == "build-features":
        from aml.features.build import build as bfeat
        bfeat(a.src, a.dest, threads=a.threads, memory_limit=a.memory_limit,
              temp_directory=a.temp_directory, force=a.force)
    elif a.cmd == "train":
        from aml.models.train import train
        train(a.features, a.splits, a.dest, model=a.model, seed=a.seed,
              memory_limit=a.memory_limit, temp_directory=a.temp_directory,
              bootstrap=a.bootstrap, sample=a.sample, force=a.force,
              resume=not a.no_resume)
    elif a.cmd == "evaluate":
        from aml.eval.run import run as evrun
        evrun(a.features, a.splits, a.scores, a.dest, model=a.model,
              bootstrap=a.bootstrap, permutations=a.permutations, seed=a.seed)
    elif a.cmd == "plant-leak":
        from aml.leakproof.plant import plant
        plant(a.labeled, a.dest, kind=a.kind, force=a.force)
    elif a.cmd == "model-stability":
        from aml.models.stability import run as msrun
        msrun(a.features, a.splits, a.dest,
              seeds=tuple(int(s) for s in a.seeds.split(",")),
              configs=(a.configs.split(",") if a.configs else None),
              sample=a.sample)
    elif a.cmd == "leak-sweep":
        from aml.leakproof.sweep import run as sweeprun
        sweeprun(a.features, a.splits, a.leak_root, a.dest,
                 seeds=tuple(int(s) for s in a.seeds.split(",")),
                 iters=a.iters, sample=a.sample)
    elif a.cmd == "make-drift":
        from aml.drift.resample import generate
        generate(a.patterns, a.dest, n_buckets=a.buckets, magnitude=a.magnitude,
                 seed=a.seed, rings_per_bucket=a.rings_per_bucket,
                 train_buckets=a.train_buckets, force=a.force)
    elif a.cmd == "splice-drift":
        from aml.drift.splice import splice
        splice(a.labeled, a.drift, a.dest, seed=a.seed, force=a.force)
    elif a.cmd == "drift-experiment":
        from aml.drift.experiment import run as dxrun
        dxrun(a.features, a.drift, a.dest, seed=a.seed, iters=a.iters,
              bootstrap=a.bootstrap, sample=a.sample)
    return exits.EXIT_OK


def main(argv=None):
    """Run a component and translate any failure into a retry decision.

    The traceback still goes to stderr in full -- this classifies the failure,
    it does not soften it. The structured line on stdout is what makes the
    decision auditable after the fact, next to the stage's own manifest.
    """
    # Line-buffer stdout. Python block-buffers when stdout is a pipe or a log
    # file, so a long stage emits nothing until its buffer fills -- during a
    # multi-hour feature build that makes "working" and "hung" look identical,
    # and there is no way to tell without killing it. The Dockerfile also sets
    # PYTHONUNBUFFERED, but relying on that would leave every non-container
    # invocation silent.
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(line_buffering=True)

    try:
        return _dispatch(argv)
    except (KeyboardInterrupt, BrokenPipeError):
        raise
    except SystemExit:
        # argparse's own --help / usage exits. Already carries its own code.
        raise
    except BaseException as exc:  # noqa: BLE001 - deliberately the last resort
        code = exits.classify(exc)
        traceback.print_exc()
        print(io.json_line({
            "event": "stage_failed",
            "exception": type(exc).__name__,
            "message": str(exc)[:500],
            "exit_code": code,
            "classification": exits.label(code),
            "retryable": code == exits.EXIT_TRANSIENT,
        }), flush=True)
        return code


if __name__ == "__main__":
    sys.exit(main())
