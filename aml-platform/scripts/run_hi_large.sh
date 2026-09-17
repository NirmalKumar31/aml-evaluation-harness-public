#!/bin/sh
# The HI-Large run, end to end. Runs ON the VM.
#
# Every stage is resumable: each writes a manifest, and re-running skips any
# stage whose inputs and code are unchanged. That matters here because the
# feature stage takes two hours and the fit takes one, and this run needed six
# attempts to get through training.
set -eu
ACCT=${ACCT:?storage account name}
# See run_cloud.sh: `latest` is not an identity a published result can cite.
TAG=${TAG:?set TAG to the tag provision_vm.sh built, e.g. aml:<sha>}
CUT=${CUT:-2022-10-07}          # chosen by split-sweep, see RUNBOOK step 6

# THESE DEFAULTS REPRODUCE THE PUBLISHED RESULT. Do not change them casually.
#
# They used to be SAMPLE=0.7 MODEL=gbdt SEEDS=0 -- the configuration that was
# RETRACTED (see paper/archive/RESULTS_hi_large_RETRACTED.md). Anyone running
# the documented command would have reproduced the withdrawn experiment and
# concluded the repository disagreed with itself.
#
# The published result is full-data LightGBM at seeds 0, 1 and 2:
#   * sample=1.0 because --sample thins the training split only for a memory
#     ceiling that LightGBM does not hit (14.9 GB vs sklearn's 33.5 GB).
#   * lgbm because sklearn CANNOT fit 125M x 32 in 31 GB at any setting.
#   * three seeds because one is not a measurement -- budget metrics move 26%
#     across these three.
SAMPLE=${SAMPLE:-1.0}
MODEL=${MODEL:-lgbm}
SEEDS=${SEEDS:-0 1 2}
S=/mnt/scratch
O=$S/large

# ---------------------------------------------------------------------------
# VERIFY THE INPUT BEFORE SPENDING HOURS ON IT.
#
# Both runners used to skip a download when the file merely EXISTED and was
# non-empty, and called that resumable. A truncated transfer, a half-written
# file from a killed run, or a different release of the dataset all satisfy
# "exists and is non-empty", and nothing downstream would notice: the pipeline
# would produce a complete set of manifests describing the wrong input.
#
# The pin is `results_archive/derived/dataset_pin.json`, shipped inside the
# source archive, so the VM can check the bytes it is about to compute on
# against the bytes the published numbers describe.
#
# Duplicated in run_cloud.sh and run_hi_large.sh on purpose: `az vm run-command`
# uploads ONE file, so a shared library would not be present when this runs.
# ---------------------------------------------------------------------------
PIN=${PIN:-/opt/aml/results_archive/derived/dataset_pin.json}

pin_sha() {                       # $1 = file name as it appears in the pin
  [ -f "$PIN" ] || return 0
  python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))["files"][sys.argv[2]]["sha256"])
except Exception:
    pass' "$PIN" "$1"
}

verify_against_pin() {            # $1 = path on disk, $2 = name in the pin
  WANT=$(pin_sha "$2")
  if [ -z "$WANT" ]; then
    if [ "${ALLOW_UNPINNED_DATA:-0}" = "1" ]; then
      echo "  WARNING: $2 is not in the pin; proceeding unverified" >&2
      return 0
    fi
    echo "FATAL: $2 has no entry in $PIN, so the input cannot be identified." >&2
    echo "       ALLOW_UNPINNED_DATA=1 overrides for an unpublished run." >&2
    return 1
  fi
  GOT=$(sha256sum "$1" | cut -d" " -f1)
  if [ "$GOT" != "$WANT" ]; then
    echo "FATAL: $2 is not the pinned dataset." >&2
    echo "  expected $WANT" >&2
    echo "  got      $GOT" >&2
    return 1
  fi
  echo "  verified $2  $GOT"
}

# THE EXACT IMAGE, PASSED IN.
#
# `manifest.env_id()` folds `AML_IMAGE_DIGEST` into the cache key so a
# containerised run is keyed to the image rather than to the OS tag the image
# happens to report. Nothing supplied it: the code read the variable and every
# production path left it unset, so cloud runs got platform identity and not
# the promised exact-image identity. A guard nobody wires up is a guard that
# does not exist.
#
# RepoDigest when the image came from a registry -- that is the immutable
# content address. Local image ID when it was built here, which is the same
# guarantee for an image that was never pushed.
#
# AND NOTHING ELSE. This fell back to the literal string "unknown", which
# `env_id()` then folded into the cache key as `+imgunknown` -- so two
# unrelated images that both failed to resolve shared one "exact-image"
# identity and one cache. A guard that degrades to a constant on failure is a
# guard that is loudest exactly when it is least true.
image_digest() {
  # No `local`: these scripts are /bin/sh, where it is undefined. ShellCheck
  # SC3043 catches it; `bash -n` does not, which is the same lesson as the
  # spliced comment in provision_vm.sh.
  _d=$(docker image inspect --format '{{index .RepoDigests 0}}' "$1" 2>/dev/null) \
    || _d=$(docker image inspect --format '{{.Id}}' "$1" 2>/dev/null) \
    || _d=""
  case "$_d" in
    sha256:*|*@sha256:*) printf '%s' "$_d" ;;
    *)
      echo "FATAL: cannot resolve an image identity for '$1'." >&2
      echo "       Neither a registry digest nor a local image id came back." >&2
      echo "       Refusing to run: every manifest this produces would record" >&2
      echo "       the same placeholder, so two unrelated unresolved images" >&2
      echo "       would share one supposed exact-image identity and one" >&2
      echo "       cache key." >&2
      return 1 ;;
  esac
}
IMAGE_DIGEST=$(image_digest "$TAG") || exit 1
echo "image identity: $IMAGE_DIGEST"

R() { docker run --rm -v $S:/scratch -v /mnt/spill:/spill \
        -e AML_IMAGE_DIGEST="$IMAGE_DIGEST" \
        --entrypoint python "$TAG" -m aml.cli "$@"; }
log() { echo "=== $1 :: $(date -u +%H:%M:%S) ==="; }

# Memory is sampled throughout because Docker reports exit 137 and NOTHING
# else on an OOM kill. Four of the six failed attempts were diagnosed from
# this trace and would have been guesswork without it.
mon() { ( while :; do echo "$(date -u +%H:%M:%S) mem=$(free -m|sed -n 2p|awk '{print $3}')MB spill=$(df -m /mnt/spill|tail -1|awk '{print $3}')MB"; sleep 20; done ) > "$1" 2>&1 & echo $!; }

mkdir -p $O $S/raw && chmod -R 777 $O $S/raw

log "0 fetch HI-Large (15.9 GB)"
# Public: no Kaggle credential is needed or used. Resumable (-C -), because a
# dropped connection 14 GB in should not restart the download.
D=ealtman2019/ibm-transactions-for-anti-money-laundering-aml
for f in HI-Large_Trans.csv HI-Large_Patterns.txt; do
  if [ -s "$S/raw/$f" ] && verify_against_pin "$S/raw/$f" "$f" 2>/dev/null; then
    echo "  already downloaded and verified: $f"
    continue
  fi
  # Resume into .part -- `-C -` on the FINAL name is what made a truncated
  # 14 GB transfer look finished to the next run. The rename happens only
  # after the hash matches, so "present" and "correct" stop being different
  # things.
  curl -sL --retry 5 --retry-delay 10 -C - \
     -o "$S/raw/$f.part" "https://www.kaggle.com/api/v1/datasets/download/$D/$f"
  if ! verify_against_pin "$S/raw/$f.part" "$f"; then
    echo "  discarding $f.part and retrying once from zero" >&2
    rm -f "$S/raw/$f.part"
    curl -sL --retry 5 --retry-delay 10 \
       -o "$S/raw/$f.part" "https://www.kaggle.com/api/v1/datasets/download/$D/$f"
    verify_against_pin "$S/raw/$f.part" "$f" || { rm -f "$S/raw/$f.part"; exit 1; }
  fi
  mv "$S/raw/$f.part" "$S/raw/$f"
done
ls -la $S/raw

MON=$(mon /var/log/aml-resources.log)
trap 'kill $MON 2>/dev/null || true' EXIT

log "1 normalize";        R normalize       --src /scratch/raw/HI-Large_Trans.csv --dest /scratch/large/bronze/txns
log "2 parse-patterns";   R parse-patterns  --src /scratch/raw/HI-Large_Patterns.txt --dest /scratch/large/bronze/patterns
log "3 reconcile-labels"; R reconcile-labels --txns /scratch/large/bronze/txns \
                            --patterns /scratch/large/bronze/patterns --dest /scratch/large/gold/reconcile
log "4 split-sweep (informational: how CUT was chosen)"
                          R split-sweep     --patterns /scratch/large/bronze/patterns --labeled /scratch/large/gold/reconcile
log "5 build-splits cut=$CUT"
                          R build-splits    --patterns /scratch/large/bronze/patterns --labeled /scratch/large/gold/reconcile \
                            --cut "$CUT" --dest /scratch/large/gold/splits
log "6 build-features"
# --temp-directory is not optional at this size. The default spills into the
# container's writable layer on the OS disk; this stage spilled 96 GB.
                          R build-features  --src /scratch/large/gold/reconcile/txns_labeled \
                            --dest /scratch/large/silver/features \
                            --temp-directory /spill/duckdb-tmp --memory-limit 24GB
log "7 train $MODEL sample=$SAMPLE seeds=$SEEDS"
# Assert the configuration before spending hours on it. A run that silently
# reproduces a different experiment than the documents describe is worse than
# a run that refuses to start.
case "$MODEL" in lgbm|gbdt|baseline) ;; *) echo "unknown MODEL=$MODEL"; exit 2;; esac
awk -v s="$SAMPLE" 'BEGIN{ if (s<=0 || s>1) { print "SAMPLE must be in (0,1]"; exit 2 } }' || exit 2
if [ "$MODEL" = gbdt ] && [ "$SAMPLE" = "1.0" ]; then
  echo "REFUSING: sklearn gbdt needs 33.5 GB for the full split on a 31 GB host."
  echo "Use MODEL=lgbm, or set SAMPLE<=0.7 and understand it is not the published run."
  exit 2
fi
# SAMPLE exists because of a measured ceiling, not convenience: sklearn's
# HistGradientBoosting upcasts to float64 (X_DTYPE), so 100% of the training
# split needs 33.5 GB on a 31 GB machine that cannot be enlarged -- a trial
# subscription cannot raise its vCPU quota. LightGBM consumes float32 and fits
# more. See paper/RESULTS_hi_large.md section 4.
# One destination PER SEED. They used to share a directory, so the model,
# scores, checkpoint and manifest of every seed but the last were overwritten
# and only one manifest survived to be published.
for SEED in $SEEDS; do
  log "  seed=$SEED"
  R train --features /scratch/large/silver/features \
     --splits /scratch/large/gold/splits \
     --dest "/scratch/large/gold/final_${MODEL}_s${SEED}" \
     --model "$MODEL" --seed "$SEED" --sample "$SAMPLE" \
     --temp-directory /spill/duckdb-tmp
  log "  evaluate seed=$SEED from the saved scores"
  R evaluate --features /scratch/large/silver/features \
     --splits /scratch/large/gold/splits \
     --scores "/scratch/large/gold/final_${MODEL}_s${SEED}/${MODEL}_test_scores.parquet" \
     --dest "/scratch/large/gold/eval_${MODEL}_s${SEED}" --model "$MODEL" --bootstrap 1000
done

log "8 publish manifests to blob"
# Manifests only. The Parquet is reproducible from the raw input by definition
# -- that is the claim -- so shipping tens of GB back would cost money to store
# something the pipeline regenerates.
az storage blob upload-batch --account-name "$ACCT" --auth-mode login \
   --destination aml --destination-path "runs/large-$MODEL-$(date -u +%Y%m%dT%H%M%SZ)" \
   --source $O --pattern "*.json" --overwrite -o none

echo "--- peak memory ---"
awk '{gsub(/[^0-9]/,"",$2); print $2}' /var/log/aml-resources.log | sort -n | tail -1 \
  | awk '{printf "  %.1f GB\n", $1/1024}'
log "HI-LARGE COMPLETE"
