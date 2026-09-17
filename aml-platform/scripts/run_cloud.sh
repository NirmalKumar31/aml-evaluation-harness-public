#!/bin/sh
# Run the pipeline on an Azure VM: stage from blob, compute locally, publish back.
#
# WHY NOT READ BLOB DIRECTLY FROM EVERY STAGE
#     Because DuckDB's azure extension acquires a token per file open and does
#     not cache it, and IMDS cannot serve those concurrently -- so direct blob
#     access is only safe single-threaded (see io.duckdb_connect). Correct, but
#     it would run the compute-heavy feature stage on one core.
#
#     Staging first is both faster and more honest about what a real pipeline
#     does: pull the inputs, compute at full width on local NVMe, publish the
#     outputs. Blob is the system of record at the edges, not the scratch space
#     in the middle.
#
# The host holds the managed identity and does all blob I/O with `az`. The
# container never sees a credential and never touches the network -- it reads
# and writes /scratch, which is the mounted NVMe.
set -eu

ACCT=${ACCT:?storage account name}
# No default. `aml:v5` was never built by provision_vm.sh, so the
# documented sequence could not run. Pass the tag provisioning produced.
IMAGE=${IMAGE:?set IMAGE to the tag provision_vm.sh built, e.g. aml:<sha>}
VARIANT=${VARIANT:-Medium}
CUT=${CUT:-2022-09-10}
SEEDS=${SEEDS:-0}
S=/mnt/scratch
C=aml                       # blob container

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
IMAGE_DIGEST=$(image_digest "$IMAGE") || exit 1
echo "image identity: $IMAGE_DIGEST"

run() { docker run --rm -v $S:/scratch -e AML_IMAGE_DIGEST="$IMAGE_DIGEST" \
          --entrypoint python "$IMAGE" -m aml.cli "$@"; }
step() { echo "=== $1 :: $(date -u +%H:%M:%S) ==="; }
dl() { az storage blob download --account-name "$ACCT" --auth-mode login -c $C -n "$1" -f "$2" --overwrite -o none; }

mkdir -p $S/raw $S/out
chmod -R 777 $S

step "stage raw from blob"
# Download to .part and rename only after the hash matches, so an interrupted
# transfer cannot leave behind a file that the next run treats as staged.
stage() {                         # $1 = blob name, $2 = local name
  if [ -s "$S/raw/$2" ] && verify_against_pin "$S/raw/$2" "$2" 2>/dev/null; then
    echo "  already staged and verified: $2"
    return 0
  fi
  dl "$1" "$S/raw/$2.part"
  verify_against_pin "$S/raw/$2.part" "$2" || { rm -f "$S/raw/$2.part"; exit 1; }
  mv "$S/raw/$2.part" "$S/raw/$2"
}
stage "raw/HI-${VARIANT}_Trans.csv"    "HI-${VARIANT}_Trans.csv"
stage "raw/HI-${VARIANT}_Patterns.txt" "HI-${VARIANT}_Patterns.txt"
ls -la $S/raw

step "1/6 normalize"
run normalize --src /scratch/raw/HI-${VARIANT}_Trans.csv --dest /scratch/out/bronze/txns
step "2/6 parse-patterns"
run parse-patterns --src /scratch/raw/HI-${VARIANT}_Patterns.txt --dest /scratch/out/bronze/patterns
step "3/6 reconcile-labels"
run reconcile-labels --txns /scratch/out/bronze/txns --patterns /scratch/out/bronze/patterns \
    --dest /scratch/out/gold/reconcile
step "4/6 build-splits"
run build-splits --patterns /scratch/out/bronze/patterns --labeled /scratch/out/gold/reconcile \
    --cut "$CUT" --dest /scratch/out/gold/splits
step "5/6 build-features"
run build-features --src /scratch/out/gold/reconcile/txns_labeled --dest /scratch/out/silver/features \
    --temp-directory /scratch/duckdb-tmp --memory-limit 24GB
step "6/6 train"
# ONE DESTINATION PER SEED.
#
# This loop wrote every seed to /scratch/out/gold/models, so the model, the
# scores, the checkpoint and the manifest of every seed but the last were
# overwritten -- the script exposed a multi-seed interface that silently
# produced one result. run_hi_large.sh already had this fixed; this one did
# not, and the default SEEDS=0 meant the loop never ran twice here.
for s in $SEEDS; do
  step "  seed=$s"
  run train --features /scratch/out/silver/features --splits /scratch/out/gold/splits \
      --dest "/scratch/out/gold/models_gbdt_s${s}" --model gbdt --seed "$s"
done
# Every seed must have left a manifest behind. Cheap, and it is the assertion
# that would have caught the overwrite.
n_expected=$(echo $SEEDS | wc -w)
n_found=$(find $S/out/gold -maxdepth 1 -name 'models_gbdt_s*' -type d | wc -l)
if [ "$n_found" -lt "$n_expected" ]; then
  echo "FATAL: asked for $n_expected seed(s), found $n_found output dir(s)" >&2
  exit 1
fi
echo "  $n_found seed destination(s) written"

step "publish results to blob"
# Manifests and metrics only. The Parquet is reproducible from the raw input by
# definition -- that is the entire claim -- so shipping 30 GB of it back would
# cost egress to store something the pipeline can regenerate.
az storage blob upload-batch --account-name "$ACCT" --auth-mode login \
   --destination $C --destination-path "runs/$(date -u +%Y%m%dT%H%M%SZ)" \
   --source $S/out --pattern "*.json" --overwrite -o none
echo "=== PIPELINE COMPLETE $(date -u) ==="
