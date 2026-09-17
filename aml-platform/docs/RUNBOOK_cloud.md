# Runbook: reproducing the cloud runs

Every command here was actually run. Where something failed, the failure is
recorded rather than edited out — the failures are most of what this document
is worth.

**Cost of everything below, AT A SNAPSHOT TAKEN 128.15 RESOURCE-HOURS IN: $70.12 at list price — not a total.** `cost.json` records `snapshot_is_final: false`, the VM is still allocated, and the meter has run since: an audit measured roughly $84.79 of actual spend <!-- derived: 84.79 = a live portal reading taken during an external audit, not produced by cost_table.py and deliberately not committed as an artifact -->, above the $60 alert budget. No final figure exists until the last resource is stopped and `cost_table.py` is rerun; every cost figure in this document is that non-final snapshot. Nothing was charged
to a payment method — see the scope note; that is an inference from the trial
spending limit, not an invoice figure.**
Snapshot at 128.15 resource-hours; the clock is still running until the
resource group is deleted. Regenerate with `scripts/cost_table.py`.
See [the one cost table](#cost-one-table-one-scope) — there is exactly one, and
every other figure in this repository points at it.

---

## What runs where

| | choice | why not the obvious alternative |
|---|---|---|
| compute | **one Azure VM**, `Standard_E4ds_v7` | Azure ML needs a dedicated vCPU quota that is **0** on a trial subscription, and drags in Key Vault + App Insights + its own registry. ACI caps at ~16 GB with slow scratch. This is a single-node job |
| storage | **ADLS Gen2**, hierarchical namespace on | flat blob has no real directories; `abfss://` and partitioned Parquet want them |
| identity | **managed identity**, both system- and user-assigned | no secret exists to leak. `allowSharedKeyAccess: false` means an account key cannot be used even if one did |
| orchestration | **`az vm run-command`** | no SSH, no inbound port, no key. Goes through the Azure control plane |
| IaC | **Bicep** | Terraform's state file needs a storage account that must exist before the thing that creates storage accounts |
| registry | ACR, **not used for building** | `az acr build` returns `TasksOperationsNotAllowed` on trial subscriptions. The image is built on the VM instead |
| engine | **DuckDB** | 180M rows, one machine, no cluster. Spark would need a cluster to do worse |
| model | **LightGBM** at HI-Large; scikit-learn `HistGradientBoostingClassifier` at HI-Medium and below | ⚠️ this row used to say sklearn was the model and LightGBM "a memory comparison, not a competitor". That is backwards for the published HI-Large result: **sklearn cannot fit the 124,992,128-row matrix in 31 GB** (33.5 GB at `X_DTYPE=float64`) and LightGBM can (14.9 GB), which is why the scale result is LightGBM. See `paper/RESULTS_hi_large.md` §4 |

---

## Prerequisites

```bash
az login                      # interactive, in YOUR terminal. No service principal.
az account set --subscription <id>
```

> **Never click "Upgrade to pay-as-you-go."** It is the only thing that removes
> the free-account spending limit, and it cannot be undone. Until then the
> account physically cannot overspend — it stops serving requests instead.

---

## 1. Register providers — 3 min

A fresh subscription has none of these, and `az vm list-usage` returns **empty**
rather than an error until `Microsoft.Compute` is registered.

```bash
for ns in Microsoft.Storage Microsoft.ContainerRegistry Microsoft.Compute \
          Microsoft.ManagedIdentity Microsoft.Authorization Microsoft.Network; do
  az provider register --namespace $ns
done
```

## 2. Check quota BEFORE planning anything — 1 min

```bash
az vm list-usage -l eastus --query "[?localName=='Total Regional vCPUs']" -o table
```

This subscription: **4 vCPU total, 4 per family.** That is the binding
constraint on everything downstream, and it cannot be raised:

```bash
az quota update --resource-name cores --limit value=8 \
  --scope /subscriptions/<id>/providers/Microsoft.Compute/locations/eastus
# ERROR: (ResourceNotAvailableForOffer)
```

Also check the SKU actually provisions — `E4ds_v4`, `_v5` and `_v6` all report
`NotAvailableForSubscription` in eastus; `_v7` is the one that works:

```bash
az vm list-skus -l eastus --size Standard_E4ds --all -o table
```

## 3. Deploy — 5 min

```bash
az group create -n aml-rg -l eastus
az deployment group what-if -g aml-rg -f infra/main.bicep    # always dry-run
az deployment group create  -g aml-rg -f infra/main.bicep
```

**Prove teardown before putting data in it.** Destroy and redeploy once, on an
empty group:

```bash
az group delete -n aml-rg --yes && az group create -n aml-rg -l eastus
az deployment group create -g aml-rg -f infra/main.bicep
```

## 4. Upload source and data — ~20 min

```bash
SA=$(az deployment group show -g aml-rg -n main \
      --query properties.outputs.storageAccount.value -o tsv)

# Grant YOURSELF blob access. The Bicep grants the VM's identities, not you.
az role assignment create --assignee $(az ad signed-in-user show --query id -o tsv) \
  --role "Storage Blob Data Contributor" \
  --scope $(az storage account show -n $SA -g aml-rg --query id -o tsv)

cd aml-platform
# The commit being deployed, in full. Every manifest the image writes records
# it and the image is TAGGED with it, so a published number can name the code
# that produced it. provision_vm.sh refuses to build without it.
GIT_SHA=$(git rev-parse HEAD)

# FAIL ON A DIRTY TREE. Do not warn about it.
#
# This block used to `tar czf` the WORKING TREE and label it $GIT_SHA, with a
# printed warning that "the image will claim $GIT_SHA and not contain it". That
# is a documented false provenance, which is not a safer kind. SRC_SHA256 then
# proved only that Azure received the same tarball -- not that the tarball is
# the tree that commit names.
if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to deploy: the worktree is dirty, so the archive would not" >&2
  echo "be the tree $GIT_SHA names. Commit or stash first." >&2
  git status --short >&2
  exit 1
fi

# BUILT BY git archive, FROM THE COMMIT. Not from the working directory.
#
# `git archive` writes exactly the blobs at $GIT_SHA, so "the source the VM
# builds" and "the tree that commit identifies" become the same object by
# construction rather than by assertion. The path list is unchanged: every file
# the Dockerfile COPYs must be in here, and a test asserts that against the
# Dockerfile.
#
# results_archive/ travels with the source because the runners verify the raw
# files against derived/dataset_pin.json before starting a three-hour pipeline,
# and because the image COPYs the archive so the suite running inside it can
# recompute the published metrics instead of skipping those tests.
git archive --format=tar.gz -o /tmp/aml-src.tgz --prefix='' "$GIT_SHA" -- \
    src tests paper docs infra scripts Dockerfile pyproject.toml Makefile README.md \
    LICENSE DATA_LICENSE.md \
    requirements.lock requirements.linux-amd64.lock \
    requirements-dev.lock requirements-dev.linux-amd64.lock \
    requirements-release.lock \
    results_archive
SRC_SHA=$(sha256sum /tmp/aml-src.tgz | cut -d" " -f1)
echo "source archive $SRC_SHA  from $GIT_SHA"   # the VM verifies this before extracting

# ANYONE CAN REBUILD THIS BYTE FOR BYTE from the commit alone, which is the
# property `tar czf` of a working directory did not have:
#   git archive --format=tar.gz -o /tmp/check.tgz --prefix='' <GIT_SHA> -- <same paths>
#   sha256sum /tmp/check.tgz     # must equal $SRC_SHA

az storage blob upload --account-name $SA --auth-mode login -c aml \
  -n src/aml-src.tgz -f /tmp/aml-src.tgz --overwrite

# HI-Medium only: HI-Large is downloaded on the VM (step 6), never locally
az storage blob upload-batch --account-name $SA --auth-mode login \
  -d aml --destination-path raw -s data --pattern "HI-Medium*"
```

> **RBAC takes up to 30 minutes to propagate.** A `403`, or
> `Failed to get token from ChainedTokenCredential`, immediately after a role
> assignment is usually propagation, not misconfiguration. Wait and retry once
> before debugging.

## 5. Provision the VM — ~10 min

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/provision_vm.sh \
  --parameters "ACCT=$SA" "AML_GIT_SHA=$GIT_SHA" "SRC_SHA256=$SRC_SHA"
```

Mounts both disks, installs Docker, verifies the source archive against
`$SRC_SHA`, replaces `/opt/aml` and builds the image as `aml:$GIT_SHA`.
Idempotent — re-run it to rebuild after a code change.

> **All three parameters are required.** `provision_vm.sh` refuses to build
> without `AML_GIT_SHA`, because an image that cannot name its commit writes
> manifests recording `code_git_sha: unknown` — seven archived manifests are in
> exactly that state — and it refuses without `SRC_SHA256`, because a blob the
> VM cannot authenticate decides what the VM builds. An earlier version of this
> runbook passed neither and claimed the hash check happened anyway.

## 6. Run

**HI-Medium** (~16 min, the reproducibility result):

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/run_cloud.sh \
  --parameters "ACCT=$SA" "VARIANT=Medium" "IMAGE=aml:$GIT_SHA"
```

**HI-Large** (~3.5 h including a 16 GB download): <!-- derived: 3.5 = the HI-Large lineage's wall-clock estimate in RUNBOOK_cloud.md, not a measured artifact field -->

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/run_hi_large.sh --parameters "ACCT=$SA" "TAG=aml:$GIT_SHA"
```

Both runners hash every raw file against
`results_archive/derived/dataset_pin.json` before the first stage, and both
download to `.part` and rename only on a match — so "the file is there" and
"the file is the dataset the published numbers describe" are no longer the
same check.

`run_command` returns only the final output. Follow progress with:

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts 'grep "^===" /var/log/aml-*.log; tail -3 /var/log/aml-resources.log'
```

Every stage is resumable. Re-running skips any stage whose inputs **and code**
are unchanged, which is what made six training attempts affordable.

## ⚠️ The live resource group is not what this Bicep deploys

Checked directly against the subscription on **2026-09-14**, with read-only
`az` queries. The running group **predates** `infra/main.bicep` and diverges
from it in four ways:

| | live `aml-rg`, 2026-09-14 | `infra/main.bicep` |
|---|---|---|
| VM | **running**, and billing | — |
| NIC public IP | `aml-vmPublicIP` attached | no public IP on the NIC |
| egress | no NAT gateway; subnet `defaultOutboundAccess` unset | `natGateway` + `defaultOutboundAccess: false` |
| NSG | one rule, `default-allow-ssh` → **Deny** | `securityRules: []` |
| auto-shutdown | none | none |

The Deny rule is a **manual repair**, not a deployment: the NSG was created
with SSH allowed from `*` on a public IP while the documents said there was no
inbound path, and the rule was flipped by hand. So the live security posture is
better than it was and still not reproducible from source — redeploying this
Bicep would produce a *different* network, and the template has never been
deployed end to end.

A `$60` monthly budget `aml-guard` exists with an 80% alert. **A budget
notifies; it does not stop anything.** The VM has been running for
**128.15 resource-hours** at `$0.416/hr` list, and the only brake is
`az group delete`.

**Two decisions are open**, and both belong to the operator, not to this
document:

1. **Deallocate or delete.** Deallocating stops the VM meter and **wipes
   `/mnt/scratch`** — the 15.9 GB CSV and the 23 GB feature table, both
   regenerable but at about 3.5 hours. `/mnt/spill` is a managed disk and <!-- derived: 3.5 = the HI-Large lineage's wall-clock estimate in RUNBOOK_cloud.md, not a measured artifact field -->
   survives either way. Deleting the group stops everything.
2. **Reconcile or retire the Bicep.** Either redeploy from it into a clean
   group, or mark it as the intended design that the live group is not an
   instance of. Publishing it as "the infrastructure" without one of those is
   the same defect as publishing a number from an artifact that did not produce
   it.

The "Azure resolved" row of [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) does not close until
one of each is done and recorded.

## 7. Tear down

```bash
az group delete -n aml-rg --yes --no-wait
az group delete -n cloud-shell-storage-eastus --yes --no-wait   # if you opened Cloud Shell
```

Done means **Cost Analysis shows $0/day for 48 consecutive hours.** Budget
alerts only notify, and they lag 8–24 hours; `az group delete` is the brake.

---

## Failures worth knowing about before you hit them

| symptom | actual cause |
|---|---|
| `TasksOperationsNotAllowed` from `az acr build` | trial subscriptions cannot use ACR Tasks. Build on the VM |
| `Problem with the SSL CA cert` on every blob read | **not** auth. DuckDB's azure extension cannot find the trust store in a slim image. Fixed by `azure_transport_option_type='curl'`; `ca_cert_file`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE` all do nothing |
| `abfss do not manage recursive lookup patterns` | `**/*.parquet` is illegal on abfss. And `/**` is no substitute — each stage writes `manifest.json` into its own output directory |
| `Failed to get token from ChainedTokenCredential`, **different file each run** | not permissions — concurrency. DuckDB fetches a token per file open and never caches; IMDS cannot serve those in parallel. Azure paths are single-threaded by default now |
| `No space left on device` during features | the spill, not the output. The stage spilled **96 GB** while the output was 23 GB. That is why there is a separate 1 TB disk |
| exit **137**, no message | OOM-killed. Docker reports nothing else — sample memory during long runs or you are guessing |
| exit 137 ~16 s after the fit begins | sklearn upcasts to float64. A float32 array is duplicated at double width inside `fit` |
| 91 GB of work gone after stopping the VM | `/mnt/scratch` is the **ephemeral resource disk**. Azure wipes it on deallocate. `/mnt/spill` is a managed disk and survives |
| `best_split_info.left_count > 0` from LightGBM | `min_child_weight=0` disables the guard that check relies on. Does not reproduce below ~100M rows |

---

## What this cost

```text
VM  Standard_E4ds_v7   $0.41600/hr   the bulk of it
OS disk P6, 64 GB      $0.01398/hr
spill disk E30, 1 TB   $0.10521/hr
public IP, static      $0.00500/hr
ACR Basic              $0.00694/hr   provisioned, ultimately unused
ingress                 free
                       ─────────
snapshot (NOT final)   $70.12 over 128.15 h -- see the table below
```

⚠️ **This paragraph said the $200 credit "was never close to binding", and <!-- historical -->
that has stopped being true.** Divide the portal spend in the cost table below
by the elapsed hours beside it and the burn rate makes the credit the **first**
constraint to bind, ahead of the 30-day calendar expiry. The figures are not
restated here on purpose — a number copied into a second document is a number
that will disagree with the first — so read them from the table, which is
generated.

Two consequences the old wording hid:

- The stale reassurance is itself why nobody was watching the credit. A
  document that says a constraint is slack stops anyone checking it.
- `/mnt/scratch` is the **ephemeral resource disk** and Azure wipes it **on
  deallocate**. Credit exhaustion deallocates. So the HI-Medium features —
  and with them the only remaining path to repairing the categorical
  ablation's provenance — disappear without anyone acting.

The 4 vCPU quota remains a real constraint. It was never the only one.

⚠️ This line said **$180** and the identical line at the end of the cost
section said **$200**. One of them was simply wrong, and a document with two
ceilings has no ceiling. The subscription is an Azure free trial with a **$200**
credit and the spending limit left on; the separate `aml-guard` **$60** monthly
budget is an alert, not a cap. <!-- historical -->

## Cost: one table, one scope

Four different figures for this project's cost used to appear in four places —
"under $5", "about $21", "about $30", and "$0" — with no scope attached to any
of them, so a reader could not tell whether they contradicted each other or
described different things. They described different things. This is the only
cost statement; the others now point here.

Generated by `scripts/cost_table.py` into
`results_archive/derived/cost.json`. Prices come from the **public Azure retail
price list** (`prices.azure.com`, East US, pay-as-you-go, USD) fetched at
generation time, not typed in.

| resource | $/hour (list) | hours | $ |
|---|---:|---:|---:|
| VM (Standard_E4ds_v7, Linux) | 0.41600 | 128.15 | 53.31 |
| spill disk (Standard SSD, 1024 GB) | 0.10521 | 128.15 | 13.48 |
| OS disk (Premium SSD, 64 GB) | 0.01398 | 128.15 | 1.79 |
| container registry (Basic, unused) | 0.00694 | 128.15 | 0.89 |
| public IP (Standard, static) | 0.00500 | 128.15 | 0.64 |
| **snapshot at list price (NOT a total)** | | **128.15** | **70.12** |
| **actually charged** | | | **not measured — see below** |

> ⚠️ **This table is PROVISIONAL and grows while the resources run.**
> `cost.json` records `snapshot_is_final: false` whenever it is generated
> without an explicit `--until`, which is every generation so far, because the
> VM has not been stopped. Three different totals were live in three documents
> at once for exactly this reason. Regenerate with
> `--until <ISO-8601>` after the meters stop, and quote the result as the
> project's cost only then.

**What the scope is, exactly.** Every resource in the resource group, from the
moment the VM was created to the moment the table was generated — so it includes
the failed attempts, the idle hours, the HI-Large run, and the re-evaluations,
not just the successful run.

**Why it is an estimate.** The subscription is an Azure free trial, and its
consumption API returns `pretaxCost: null` for every meter: credits are not
billed per meter, so no authoritative per-resource figure exists to read. What
*is* exact is the elapsed resource time. Multiplying it by published list
prices gives what this would have cost on a paid subscription.

**Why it is an upper bound on compute.** It charges the VM for every elapsed
hour. The VM was deallocated for part of that window and deallocated compute is
not billed — the disks and the IP are billed either way.

**No charge is expected, and that is an inference rather than an observation.**
The trial's spending limit was never lifted, and a subscription with the limit
in place cannot bill a payment method — so the conclusion follows from the
subscription's configuration. It does **not** follow from a bill: the
consumption API returns `pretaxCost: null` for every meter here and no invoice
was retrieved. `results_archive/derived/cost.json` therefore records
`actually_charged_usd: null` with the claim in a separate field, and this
paragraph used to say "Nobody was charged anything" as a flat fact.

Four quantities, kept apart on purpose:

| | value | what it is |
|---|---|---|
| list-price estimate | **$70.12** over 128.15 h | elapsed resource time × public retail prices |
| Azure Cost Management spend | **~$60.61**, read 2026-09-15 02:00 UTC | the portal's own running figure. A DIFFERENT ESTIMAND from the row above — it is not elapsed-time × list price — and it has now passed the $60 `aml-guard` budget, which notifies and does not stop anything <!-- derived: 60.61 = the Azure portal's own running spend figure read at the stated time, and cost_table.py does not produce it --> |
| free-trial credit | $200 | the ceiling, and **the first constraint to bind** at the burn rate implied by the two rows above. Formerly described here as "never approached" <!-- historical --> |
| invoiced charge | **not measured** | no statement retrieved; expected zero under the spending limit |
