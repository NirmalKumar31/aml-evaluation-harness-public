#!/usr/bin/env bash
# The preregistered split-inflation experiment.
#
#   paper/PREREGISTRATION_split_inflation.md   committed 2026-08-24, before any
#                                              result below existed
#
# Nothing here may be changed to improve a contrast. The parameters are the
# ones fixed in section 4 of that file: HI-Small, cut 2022-09-05 (chosen by
# split-sweep and archived long before this ran), GBDT at 300 iterations, no
# sampling, seeds 0-4, ring-clustered bootstrap at 500 resamples.
#
# The design rests on one structural fact: the ring discipline is purely a
# TEST-set filter, so the training half is identical under both protocols. That
# is not assumed -- the two fits per seed must produce the same
# model_artifact_sha256, and analyze_split_inflation.py fails if they do not.
set -euo pipefail

VARIANT=${VARIANT:-Small}
CUT=${CUT:-2022-09-05}
SEEDS=${SEEDS:-"0 1 2 3 4"}
D=${D:-data}
PY=${PY:-.venv/bin/python}

run() { echo "+ $*" >&2; "$@"; }

# ---- shared inputs: identical for both protocols by construction -----------
run $PY -m aml.cli normalize --src "$D/HI-${VARIANT}_Trans.csv" \
    --dest "$D/bronze/txns_${VARIANT}"
run $PY -m aml.cli parse-patterns --src "$D/HI-${VARIANT}_Patterns.txt" \
    --dest "$D/bronze/patterns_${VARIANT}"
run $PY -m aml.cli reconcile-labels --txns "$D/bronze/txns_${VARIANT}" \
    --patterns "$D/bronze/patterns_${VARIANT}" --dest "$D/gold/reconcile_${VARIANT}"
run $PY -m aml.cli build-features --src "$D/gold/reconcile_${VARIANT}/txns_labeled" \
    --dest "$D/silver/features_${VARIANT}"

# ---- the two protocols, same code path, one flag apart --------------------
for P in ring-aware naive; do
  run $PY -m aml.cli build-splits --patterns "$D/bronze/patterns_${VARIANT}" \
      --labeled "$D/gold/reconcile_${VARIANT}" --cut "$CUT" --protocol "$P" \
      --dest "$D/gold/infl_splits_${P}_${VARIANT}"
done

# ---- one model per seed, scored on both test sets -------------------------
for S in $SEEDS; do
  for P in ring-aware naive; do
    run $PY -m aml.cli train --features "$D/silver/features_${VARIANT}" \
        --splits "$D/gold/infl_splits_${P}_${VARIANT}" \
        --dest "$D/gold/infl_fit_${P}_s${S}" --model gbdt --seed "$S" --bootstrap 500
    run $PY -m aml.cli evaluate --features "$D/silver/features_${VARIANT}" \
        --splits "$D/gold/infl_splits_${P}_${VARIANT}" \
        --scores "$D/gold/infl_fit_${P}_s${S}/gbdt_test_scores.parquet" \
        --dest "$D/gold/infl_eval_${P}_s${S}" --model gbdt --seed "$S" \
        --bootstrap 500 --permutations 1000
  done
done

echo "SPLIT_INFLATION_RUNS_COMPLETE"
