# Archive — superseded, kept on purpose

Nothing in this directory describes the project as it is now. It is kept
because the corrections are part of the contribution: a project arguing that
evaluation claims are fragile does not get to hide its own.

**Current documents live at the repository root and under `aml-platform/`.**
Start at [`../../README.md`](../../README.md); the retractions are summarised in
[`../../CHANGELOG.md`](../../CHANGELOG.md).

| file | what it was | why it is here |
|---|---|---|
| `BUILD_PLAN.md` | the original build plan and workflow map | superseded by the code. Contains the claim that split inflation is "unknowable", which was later measured |
| `AML_PROJECT_KNOWLEDGE.md` | a working knowledge dump, project codename "DriftGraph" | superseded; the name was dropped and the dataset facts it cites now live in `results_archive/derived/dataset_facts.json` |
| `Cloud/` | the v1 cloud architecture | superseded. It describes an Azure ML / Synapse design that was never built; the real deployment is one VM, documented in `../RUNBOOK_cloud.md` |
| `FEATURE_SPEC_v1.md` | the engine-neutral 32-feature specification | its status block declared the `txn_id` non-determinism a live blocker and said the leak proof was silently wrong. Both were fixed long ago; the file sat in `aml-platform/docs/` presenting itself as the current design through four audits. §1–§6 are still accurate, the Spark implementation it was written for was never built |
| `v1 audit.md` … `v7 audit.md` | seven external LLM audits | v1–v6 are remediated. **v7's technical findings are closed**; what remains needs a person rather than a commit — a licence determination, a credential rotation, an Azure decision and the GitHub launch sequence. See the status table in `../../HANDOFF.md`. The reports are the record of what was wrong and when, and v1 is the one that first flagged the `FEATURE_SPEC_v1.md` defect above |

⚠️ **Numbers in these files are stale by definition** and are deliberately
excluded from `make_tables.py --check`. Do not quote them.
