#!/usr/bin/env bash
# Rebuild HI-Medium under the txn_id-at-ingest scheme (schema 1.1.0) and re-run
# the leak ladder.
#
# WHY: the previous ladder was computed through a join keyed on a txn_id that
# two components derived independently and non-deterministically, so leak
# columns were attached to the wrong transactions for ~2% of rows. The
# pre-fix results are archived in paper/archive/before_txn_id_fix/ so the
# ladder can be compared before and after.
#
# Parameters are copied from the original manifests so this is the same
# protocol, not a new one. Only the identity scheme changed.
set -euo pipefail

PY=.venv/bin/python
D=data
V=Medium
CUT=2022-09-10
say() { echo; echo "===== $(date '+%H:%M:%S')  $*"; }

say "1/11 normalize (assigns txn_id at ingest)"
$PY -m aml.cli normalize --src $D/HI-${V}_Trans.csv --dest $D/bronze/txns_$V

say "2/11 parse-patterns"
$PY -m aml.cli parse-patterns --src $D/HI-${V}_Patterns.txt --dest $D/bronze/patterns_$V

say "3/11 reconcile-labels"
$PY -m aml.cli reconcile-labels --txns $D/bronze/txns_$V \
  --patterns $D/bronze/patterns_$V --dest $D/gold/reconcile_$V

say "4/11 build-splits (cut $CUT)"
$PY -m aml.cli build-splits --patterns $D/bronze/patterns_$V \
  --labeled $D/gold/reconcile_$V --cut $CUT --dest $D/gold/splits_$V

say "5/11 build-features  <-- the slow stage"
$PY -m aml.cli build-features --src $D/gold/reconcile_$V/txns_labeled \
  --dest $D/silver/features_$V

for kind in reversed_window future_counterparty target; do
  say "6/11 plant-leak [$kind]"
  $PY -m aml.cli plant-leak --labeled $D/gold/reconcile_$V/txns_labeled \
    --dest $D/gold/leak_$V/$kind --kind $kind
done

# One sweep covers every channel, with a permuted-leak placebo arm per channel
# and a shared noise floor. The old per-kind `prove-leak` calls this replaced
# fitted one model per channel against a fixed AP-ratio threshold, which the
# measured 22% placebo spread showed to be uninterpretable below ~1.22.
#
# --iters MUST stay equal to the shipped GBDT_ITERS, or the harness certifies a
# configuration nobody reports.
say "7/11 leak-sweep  <-- all channels, real + placebo arm, 8 seeds"
$PY -m aml.cli leak-sweep --features $D/silver/features_$V \
  --splits $D/gold/splits_$V --leak-root $D/gold/leak_$V \
  --dest $D/gold/leaksweep_$V --seeds 0,1,2,3,4,5,6,7 --iters 300

say "8/11 leak ladder summary written to $D/gold/leaksweep_$V/sweep_summary.json"

say "9/11 train baseline"
$PY -m aml.cli train --features $D/silver/features_$V --splits $D/gold/splits_$V \
  --dest $D/gold/models_$V --model baseline

say "10/11 train gbdt"
$PY -m aml.cli train --features $D/silver/features_$V --splits $D/gold/splits_$V \
  --dest $D/gold/models_$V --model gbdt

for m in baseline gbdt; do
  say "11/11 evaluate [$m]"
  $PY -m aml.cli evaluate --features $D/silver/features_$V --splits $D/gold/splits_$V \
    --scores $D/gold/models_$V/${m}_test_scores.parquet \
    --dest $D/gold/eval_$V/$m --model $m
done

say "DONE"
