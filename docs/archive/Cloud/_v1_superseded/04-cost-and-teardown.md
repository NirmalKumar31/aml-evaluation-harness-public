# Cost and teardown
## Where the £200 goes, and how to get back to £0

---

## The estimate

| item | cost | notes |
|---|---|---|
| ADLS Gen2, 27 GB | ~£0.50/month | 17 GB raw + ~10 GB Parquet |
| Synapse Serverless SQL | pennies | ~£4/TB scanned, partition-pruned |
| Container Apps Jobs | pennies | small stages, scale to zero |
| Azure ML compute | ~£1/hour **while running** | min_nodes = 0, so £0 idle |
| Synapse Spark pool | ~£1–3 per run | auto-pause after 15 min idle |
| Container Registry (Basic) | ~£4/month | the only fixed cost |
| Azure Functions | ~£0 | free grant covers a demo |
| Data Factory | ~£0 | ~£0.80 per 1,000 activity runs |
| Log Analytics | ~£0 | free tier, 7-day retention |
| Throwaway VM for the upload | ~£0.20 | one run, then deleted |

```
realistic total for the whole project:   £20 – £40
your credit:                             £200
```

## Where the money actually goes

**Repeated 182M-row runs.** One full pass through feature building might be £2–6
depending on how long it takes and what VM size it needs. Ten iterations while debugging
is £60.

**Mitigation, in order of importance:**

1. **Debug on 32M first.** Everything already works there. Only run 182M when you expect
   it to succeed.
2. **The stage cache.** Already built — a rerun only recomputes what changed. If
   training fails, features don't rebuild.
3. **`--sample`.** Already built — validate the whole path on 1% of rows in seconds.
4. **Budget alert.** Fires at your ceiling before you find out the hard way.

## The two things that could actually burn the credit

```
⚠️  A Spark pool with auto-pause disabled       ~£1-3/hour, forever
⚠️  An Azure ML cluster with min_nodes = 1      bills 24/7 even when idle
```

Both are set correctly in the Terraform. Both are worth checking by eye after the first
apply, because they are the only two resources here that can bill while you sleep.

---

## The clock

**The £200 credit expires 30 days after activation.** After that you fall back to
pay-as-you-go plus a limited always-free tier.

So: don't activate it until Step 2 of [03-build-order.md](03-build-order.md), and plan to
finish the scale runs inside that window.

---

## Teardown

The whole point of Terraform is that this is one command. But cloud providers leave
orphans, so there's a sweep afterwards.

### The command

```bash
terraform destroy
```

### The checklist

```
[ ] terraform destroy exits clean
[ ] Data Factory pipelines stopped
[ ] Synapse Spark pool paused AND deleted
[ ] Azure ML compute cluster deleted (not just scaled to 0)
[ ] Container Apps jobs deleted
[ ] Storage account emptied, then deleted
[ ] Container Registry images deleted, registry deleted
[ ] Log Analytics workspace deleted
[ ] the throwaway upload VM deleted (plus its disk and NIC)
[ ] Budget and alert rules deleted
[ ] resource group gone
[ ] Cost Analysis shows £0 accruing for 48 hours
```

### Why some of these are separate lines

Terraform only destroys what it created. Things it commonly misses:

- **VM disks and NICs** — these often survive the VM
- **Storage containers with data** — some configs refuse to delete a non-empty account
- **Log Analytics** — has a soft-delete period
- **The manually-created service principal** — Terraform didn't make it, so it won't remove it

### The £0 proof

Screenshot Azure Cost Analysis showing £0/day for two consecutive days. That's the
deliverable — "teardown verified at £0 for 48h" is on the definition-of-done list, and a
screenshot is what makes it a fact rather than a claim.

---

## If something goes wrong

**Budget alert fires:**

1. Azure Portal → Cost Analysis, filter by the project tag (everything is tagged)
2. Find the resource that's accruing
3. It will be the Spark pool or the ML cluster. Pause or scale it to 0.
4. If unclear: `terraform destroy` and start again. Nothing here is precious except the
   data in storage, and that's re-downloadable.

**Credit exhausted:**

Everything stops. Storage remains (it's pennies). Nothing is lost — the code, tests and
local results are all on your machine and in git.

---

## Cost discipline built into the code

Three things already exist that keep this cheap, all from earlier phases:

```
stage caching      a rerun costs only what actually changed
GBDT checkpoints   a crash at round 280 of 300 resumes at 250, not 0
--sample           validate the whole path on 1% of rows in seconds
```

These were built when the question was *"what if training fails mid-run?"* On a laptop
that saved 25 minutes. In the cloud it saves money.
