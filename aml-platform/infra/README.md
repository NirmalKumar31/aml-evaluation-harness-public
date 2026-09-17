# Infrastructure

One resource group. **A VM, two managed disks, a virtual network with a public
IP, storage, an identity, and optionally a registry.**

> ⚠️ This file used to say "Storage, a registry, one identity. Nothing else
> billable." That described the design before the scale run, and by the time an
> audit read it the template also created the VM and disks that account for
> almost all of the cost. The registry is now **off by default**
> (`deployRegistry=false`): `az acr build` returns `TasksOperationsNotAllowed`
> on a trial subscription, so it was provisioned and never used. See
> [`../docs/RESULT_LINEAGE.md`](../docs/RESULT_LINEAGE.md) for which image flow
> is real — GitHub Actions into GHCR, or `docker build` on the VM from a
> sha256-verified source tarball.

**What actually costs money**, at East US list price, from
[`../docs/RUNBOOK_cloud.md`](../docs/RUNBOOK_cloud.md) — the one cost table:

| resource | $/hour |
|---|---:|
| VM `Standard_E4ds_v7` (Linux) | 0.41600 |
| spill disk, Standard SSD 1 TB | 0.10521 |
| OS disk, Premium SSD 64 GB | 0.01398 |
| container registry, Basic (unused) | 0.00694 |
| public IP, Standard static | 0.00500 |

**The deployed state is not the template.** ARM incremental deployments leave
resources the template omits, so turning `deployRegistry` off does not delete
an existing registry. Reconciling the two requires an explicit lifecycle
mechanism (deployment stacks) or a delete-and-redeploy, and neither has been
done here.

## The cost brake, in order of what actually works

| mechanism | does it stop spend? |
|---|---|
| **Free-account spending limit** | ✅ **yes — blocks it by design** |
| **`az group delete`** | ✅ yes — stops the meter |
| Budget alerts | ❌ **no.** Email only, and they lag 8–24 hours |

> ⚠️ **Never click "Upgrade to pay-as-you-go."** That prompt is the only thing
> that removes the free-account spending limit, and it is irreversible. Until
> then, the account cannot overspend — it stops serving requests instead.

> ⚠️ Azure Cloud Shell creates its own `cloud-shell-storage-<region>` resource
> group on first use. It is **outside** this template and survives deleting
> `aml-rg`. Delete it separately, or use an ephemeral Cloud Shell session.

## Deploy

No `az` CLI needed locally — use [Cloud Shell](https://shell.azure.com), where
it is preinstalled and already authenticated.

```bash
az group create -n aml-rg -l eastus

# Always dry-run first. `what-if` prints exactly what will be created.
az deployment group what-if -g aml-rg -f infra/main.bicep

az deployment group create -g aml-rg -f infra/main.bicep
```

## Build the image — two flows, and `az acr build` is not one of them

The development laptop is arm64 with no Docker, so the image has to be built
somewhere else. There are exactly two working answers:

1. **GitHub Actions → GHCR.** `.github/workflows/image.yml` builds for
   linux/amd64 from a `--require-hashes` lock, runs the whole suite inside the
   built image, then tags *that tested image* and pushes it. This is the one
   that produces the published digest.
2. **`docker build` on the VM**, from a sha256-verified source archive that
   `git archive <commit>` produced on the host. See
   [`../docs/RUNBOOK_cloud.md`](../docs/RUNBOOK_cloud.md) §4–5.

> ⛔ **This section used to instruct the reader to run `az acr build` against
> the deployment's registry output. That command cannot work here, and this
> same file says so twelve lines from the top.** The registry is off by default
> (`deployRegistry=false`), so `registryLoginServer` is empty with the
> documented deployment; and on the trial subscription ACR Tasks returns
> `TasksOperationsNotAllowed`, which is why it was turned off. A README that
> contradicts itself within one screen is worse than one that omits the
> section: a reader cannot tell which half is current.
>
> If the registry is ever wanted, deploy with `deployRegistry=true` **and** a
> subscription where ACR Tasks are permitted, and verify the output is
> non-empty before using it.

## Prove teardown BEFORE the real run

Deploy, destroy, deploy again. If teardown does not work, find out on an empty
resource group rather than on a running one.

```bash
az group delete -n aml-rg --yes
az group create -n aml-rg -l eastus
az deployment group create -g aml-rg -f infra/main.bicep
```

## Teardown

```bash
az group delete -n aml-rg --yes --no-wait
az group delete -n cloud-shell-storage-eastus --yes --no-wait   # if it exists
```

Definition of done: **Cost Analysis shows $0/day for 48 consecutive hours.**

## Two things that will bite

**RBAC propagation takes up to 30 minutes.** The identity and its role
assignments are created here, deliberately separate from any compute, so they
have time to propagate. If the first blob read still 403s, wait and retry — it
is not a configuration error.

**DuckDB cannot choose between user-assigned identities.** Its
`credential_chain` resolves managed identity through IMDS with no way to name
one. Set `AZURE_CLIENT_ID` on the container to the `identityClientId` output,
or the chain picks the wrong identity and fails confusingly.

## Deliberately absent

- **Azure ML** — pulls in Key Vault, App Insights and its own registry, and its
  compute needs a vCPU quota that is **zero** on a trial subscription. This is
  a single-node DuckDB job.
- **Spot instances** — ACI Spot is preview, documented as not for production,
  and trial subscriptions cannot get the quota. Saves cents, adds a hard-fail
  path.
- **Terraform** — needs a state file, which needs a storage account, which
  needs to exist before the thing that creates storage accounts. Bicep has no
  state; ARM is the state.
