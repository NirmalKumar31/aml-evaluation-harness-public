## What changed, and why

## If this changes a published number

- [ ] The run that produced it was re-executed (not hand-edited)
- [ ] `python scripts/make_tables.py --check <docs>` passes
- [ ] The superseded value is recorded in `docs/RESULT_LINEAGE.md` with a reason

## Always

- [ ] `make lint && make test`
- [ ] A bug fix comes with a test that fails without it
- [ ] The test asserts **behaviour**, not that the source text describes a fix
