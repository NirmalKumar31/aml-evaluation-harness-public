#!/bin/sh
# One-time VM setup: mount disks, install docker, build the image.
#
# Runs ON the VM, via `az vm run-command invoke` -- no SSH, no inbound port,
# no key. Idempotent: safe to re-run, and re-running is how you rebuild the
# image after a code change.
set -eu
ACCT=${ACCT:?storage account name}
TAG=${TAG:-}
# THE SOURCE HASH, and the runbook was claiming this check existed before the
# code did: "record this; the VM verifies it before extracting" sat above a
# download that piped straight into `tar xzf`. A blob the VM cannot authenticate
# is a blob that decides what the VM builds.
SRC_SHA256=${SRC_SHA256:-}
# Passed from the host, which has the repository; the VM does not.
# NO SILENT "unknown". A build whose image cannot say which commit produced it
# yields manifests recording code_git_sha "unknown" -- and seven archived
# manifests, including all three HI-Large FITS, are in exactly that state
# because this defaulted rather than refused. Provenance you have to remember
# to supply is provenance you will forget to supply.
if [ -z "${AML_GIT_SHA:-}" ] || [ "${AML_GIT_SHA}" = "unknown" ]; then
  echo "FATAL: set AML_GIT_SHA=<commit> before provisioning." >&2
  echo "       Every manifest this image writes records it; 'unknown' is not" >&2
  echo "       a provenance record. Use AML_ALLOW_UNKNOWN_SHA=1 to override" >&2
  echo "       for a throwaway experiment that will not be published." >&2
  [ "${AML_ALLOW_UNKNOWN_SHA:-0}" = "1" ] || exit 1
  AML_GIT_SHA=unknown
fi
# ONE IMAGE IDENTITY, and it is not `latest`. provision_vm.sh built `aml:latest`
# while run_cloud.sh ran `aml:v5` -- a tag nothing built -- so following the
# runbook exactly could not work, and the two runners had different implicit
# image identities. The tag now defaults to the commit being built, so the
# image names the code inside it.
TAG=${TAG:-aml:${AML_GIT_SHA:-latest}}


log() { echo "=== $1 :: $(date -u +%H:%M:%S) ==="; }

log "packages"
export DEBIAN_FRONTEND=noninteractive
command -v docker >/dev/null || { apt-get update -qq && apt-get install -y -qq docker.io curl; }
systemctl enable --now docker
# PINNED REPOSITORY, not `curl | bash`. The installer script is mutable and
# unsigned; the Microsoft apt repository is signed and versioned. This is
# the one place provisioning executed arbitrary current code from the
# network as root.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
  | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg
chmod a+r /etc/apt/keyrings/microsoft.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $(lsb_release -cs) main" \
  > /etc/apt/sources.list.d/azure-cli.list
apt-get update -qq && apt-get install -y -qq azure-cli

log "mount local NVMe as /mnt/scratch"
# The RESOURCE disk: fast, and wiped on deallocate. Holds raw input and
# intermediates.
#
# NEVER FORMAT A DISK CHOSEN BY SIZE ALONE. The first version of this picked
# the first ~200 GB block device and ran `mkfs.ext4 -F` unconditionally
# whenever /mnt/scratch was not mounted -- so re-running this "idempotent"
# script after an unmount would destroy the data on it, and a second similarly
# sized disk could be selected instead. Azure surfaces the resource disk at a
# stable udev path, and an existing filesystem is now a hard stop rather than
# something -F silently overwrites.
if ! mountpoint -q /mnt/scratch; then
  D=""
  [ -e /dev/disk/azure/resource ] && D=$(readlink -f /dev/disk/azure/resource)
  if [ -z "$D" ]; then
    # Fallback, still not by size alone: the resource disk is the one NOT
    # holding the root filesystem and NOT the attached data disk.
    ROOT=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null | head -1)
    for c in $(lsblk -dn -o NAME,SIZE | awk '$2 ~ /^[0-9]+G$/ {print $1}'); do
      [ "$c" = "$ROOT" ] && continue
      [ "$(lsblk -dn -o SIZE "/dev/$c")" = "1T" ] && continue   # the spill disk
      D="/dev/$c"; break
    done
  fi
  [ -n "$D" ] || { echo "FATAL: could not identify the resource disk"; exit 1; }

  if blkid "$D" >/dev/null 2>&1; then
    echo "FATAL: $D already has a filesystem. Refusing to format."
    echo "Mount it, or wipe it deliberately, then re-run."
    exit 1
  fi
  mkfs.ext4 -q "$D"                       # no -F: fail rather than overwrite
  mkdir -p /mnt/scratch
  mount "$D" /mnt/scratch; chmod 777 /mnt/scratch
fi

log "mount managed disk as /mnt/spill"
# PERSISTENT, and separate from /mnt/scratch on purpose: the feature stage
# spilled 96 GB, and sharing one disk with the outputs is what filled the
# 216 GB NVMe and killed the first HI-Large attempt.
if ! mountpoint -q /mnt/spill; then
  # LUN 0, as the Bicep template attaches it -- a stable identity, unlike size.
  D=""
  [ -e /dev/disk/azure/scsi1/lun0 ] && D=$(readlink -f /dev/disk/azure/scsi1/lun0)
  [ -n "$D" ] || D=$(lsblk -dn -o NAME,SIZE | awk '$2 == "1T" {print "/dev/"$1; exit}')
  [ -n "$D" ] || { echo "FATAL: no data disk at LUN 0"; exit 1; }
  # Format ONLY a genuinely blank device. -F is deliberately absent.
  blkid "$D" >/dev/null 2>&1 || mkfs.ext4 -q "$D"
  # "$D", not "/dev/$D". D is ALREADY an absolute device path -- readlink -f
  # returns one, and the lsblk fallback builds one with its own "/dev/" prefix.
  # The old line produced /dev//dev/sdc and could only fail. It never did,
  # because `mountpoint -q` skips this whole block once /mnt/spill is mounted:
  # the bug was unreachable on every rerun and waiting for the first clean
  # provision, which is the reproduction path.
  mkdir -p /mnt/spill
  mount "$D" /mnt/spill || { echo "FATAL: mount $D /mnt/spill failed"; exit 1; }
  mountpoint -q /mnt/spill || { echo "FATAL: /mnt/spill not mounted"; exit 1; }
  chmod 777 /mnt/spill
fi
mkdir -p /mnt/spill/duckdb-tmp && chmod 777 /mnt/spill/duckdb-tmp

log "authenticate as the VM's managed identity"
az login --identity -o none

log "fetch source and build the image"
# Source comes from blob, not git: the repo may be private, and a deploy key on
# the VM would be a long-lived secret. The managed identity already has blob
# read, so this needs no new credential.
az storage blob download --account-name "$ACCT" --auth-mode login \
   -c aml -n src/aml-src.tgz -f /tmp/aml-src.tgz.part --overwrite -o none

# VERIFY BEFORE EXTRACTING, not after, and not never.
if [ -n "$SRC_SHA256" ]; then
  GOT=$(sha256sum /tmp/aml-src.tgz.part | cut -d" " -f1)
  if [ "$GOT" != "$SRC_SHA256" ]; then
    echo "FATAL: source archive does not match the hash recorded on the host." >&2
    echo "  expected $SRC_SHA256" >&2
    echo "  got      $GOT" >&2
    rm -f /tmp/aml-src.tgz.part
    exit 1
  fi
  echo "source archive verified: $GOT"
elif [ "${AML_ALLOW_UNVERIFIED_SRC:-0}" = "1" ]; then
  echo "WARNING: SRC_SHA256 not supplied; building UNVERIFIED source." >&2
else
  echo "FATAL: set SRC_SHA256=<sha256 of aml-src.tgz> (the runbook prints it" >&2
  echo "       when it builds the archive). AML_ALLOW_UNVERIFIED_SRC=1" >&2
  echo "       overrides for a throwaway experiment." >&2
  rm -f /tmp/aml-src.tgz.part
  exit 1
fi
mv /tmp/aml-src.tgz.part /tmp/aml-src.tgz

# REPLACE THE TREE, do not extract over it. tar unpacks on top of whatever is
# already in /opt/aml, so a file DELETED between two provisions survives on the
# VM and stays in the Docker build context -- and the image built from "the
# source at commit X" then contains a file commit X does not have.
rm -rf /opt/aml.new && mkdir -p /opt/aml.new
tar xzf /tmp/aml-src.tgz -C /opt/aml.new
rm -rf /opt/aml.old
# `[ -d ] && mv` would be a FALSE test on the first provision, and under
# `set -e` a false last command exits 1 -- the script would abort on the one
# path where /opt/aml legitimately does not exist yet.
if [ -d /opt/aml ]; then mv /opt/aml /opt/aml.old; fi
mv /opt/aml.new /opt/aml
rm -rf /opt/aml.old
cd /opt/aml
docker build --build-arg "AML_GIT_SHA=${AML_GIT_SHA}" -t "$TAG" .

log "verify"
docker run --rm --entrypoint python "$TAG" -c "import aml, duckdb, sklearn, lightgbm; print('ok')"
df -h /mnt/scratch /mnt/spill | tail -2
free -g | sed -n 2p
log "PROVISION COMPLETE"
