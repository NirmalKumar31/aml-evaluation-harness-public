# Security policy

## Reporting a vulnerability

> ⛔ **There is currently no working private disclosure route, and this file
> will not pretend otherwise.** Two earlier versions did: the first pointed at
> `Security → Report a vulnerability`, which returns 404 on a private
> repository, and the second pointed at "the address on the GitHub profile that
> owns this repository", which does not display one. Both read like a policy
> and neither could carry a report. A security policy that names a channel
> nobody can use is worse than one that names none, because it stops the
> reporter looking further.

**Before this repository is made public, exactly one of the following must be
done**, and it is a blocking row in
[`aml-platform/docs/RELEASE_CHECKLIST.md`](aml-platform/docs/RELEASE_CHECKLIST.md):

1. **Enable GitHub private vulnerability reporting** (Settings → Code security →
   Private vulnerability reporting). It requires a public repository, so it can
   only be switched on at the moment of publication. Then verify it from a
   logged-out browser — the checklist row is not satisfied by the setting
   being on, it is satisfied by the form loading for someone who is not the
   maintainer.
2. **Publish a monitored contact address here**, in this file, in plain text.

Until one of those is true, treat this project as having **no coordinated
disclosure channel** and do not report anything sensitive to it.

Please do not open a public issue for anything that looks exploitable. If you
are unsure whether something qualifies, treat it as though it does.

Expect an acknowledgement within about a week. This is a research project
maintained by one person, not a product with an on-call rotation, and it is
better to say that plainly than to imply a response time that will not hold.

## Scope

This repository is a **research harness**. It is not a production AML system,
it has no deployment that serves traffic, and it processes a public synthetic
dataset — no real customer or transaction data exists anywhere in it.

What is genuinely in scope:

- credentials, tokens or connection strings committed to the tree or history
- the provisioning scripts under `aml-platform/scripts/` and the Bicep in
  `aml-platform/infra/`, which create real cloud resources and can destroy data
- dependency or container vulnerabilities that reach a user running the
  documented commands
- code paths that execute untrusted input, including the SQL built in
  `aml.features.online`

What is out of scope:

- the model's detection performance, or its failure to detect laundering.
  Every claim boundary is in `aml-platform/docs/LIMITATIONS.md`, and "this
  model would not work at a bank" is documented, not a vulnerability
- anything requiring a foothold this project does not grant

## What this project already does

- **No service principals, no client secrets, no connection strings.** Local
  work uses `az login`; services use managed identity.
- **`allowSharedKeyAccess: false`** on storage, so an account key cannot be
  used even if one existed.
- **Role assignments scoped to the resource group**, never the subscription.
- **No allowed inbound path to the VM.** Access is via `az vm run-command`.
  The NSG carries one custom inbound rule, TCP/22 from `*` with access
  **Deny** — flipped by hand after it was found set to Allow. "No inbound
  rules" was the previous wording and it was not true; the accurate statement
  is that nothing inbound is permitted.
- **Containers run as a non-root user.**
- **Full-history secret scanning** runs in CI (`.github/workflows/gates.yml`).
  A `.gitignore` entry is not a privacy control: an ignored file that was ever
  committed stays reachable after a repository goes public. **This repository
  has proved that twice** — `Cloud/_v1_superseded/` was listed in `.gitignore`
  after its files were already committed, and a `.coverage` database containing
  64 occurrences of the maintainer's absolute home directory was tracked for a
  day. Both are untracked now and both remain in history.

## Handling of the dataset

IBM AMLworld is published by IBM under CDLA-Sharing-1.0 and is **not**
redistributed here. See [DATA_LICENSE.md](DATA_LICENSE.md). The data is
synthetic; it contains no real persons or accounts.
