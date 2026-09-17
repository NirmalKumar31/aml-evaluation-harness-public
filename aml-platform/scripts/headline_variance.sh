#!/usr/bin/env bash
# How precise is the headline number, actually?
#
# The project reports recall_efficiency@50 as a point value. Three independent
# measurements of it have now landed at 0.8986, 0.8322 and 0.7995 -- a 10 point
# spread with no change to the data, the split or the model configuration. AP
# over the same three runs moved only ~6% relative.
#
# This runs the production configuration across N seeds so the headline can be
# reported as a distribution instead of a point. Per-seed output directories,
# because train writes both its manifest and its scores under --dest and would
# otherwise clobber them between seeds.
set -euo pipefail

PY=.venv/bin/python
D=data
V=Medium
SEEDS="${SEEDS:-0 1 2 3 4 5 6 7}"

for s in $SEEDS; do
  echo "===== $(date '+%H:%M:%S')  seed $s"
  dest=$D/gold/models_${V}/seed$s
  $PY -m aml.cli train --features $D/silver/features_$V --splits $D/gold/splits_$V \
      --dest "$dest" --model gbdt --seed "$s"
  $PY -m aml.cli evaluate --features $D/silver/features_$V --splits $D/gold/splits_$V \
      --scores "$dest/gbdt_test_scores.parquet" \
      --dest $D/gold/eval_${V}/seed$s --model gbdt
done
echo "===== $(date '+%H:%M:%S')  DONE"
