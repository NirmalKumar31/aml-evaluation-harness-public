# Storage compatibility
## The real work of the cloud move, and why "one line" was wrong

v1 claimed the cloud move needed only DuckDB's Azure extension. This file is the honest
version: **every place the code assumes a local filesystem**, what breaks, and the test
that must pass before any scale run.

**Read this before believing any timeline.** 🚧 This is roughly a day of careful work.

---

# Why DuckDB reading `abfss://` is the easy part

```
✅ EASY     DuckDB reads and writes abfss:// paths and supports globs
            → one extension load + one credential chain

🚧 THE WORK  everything AROUND the data:
             manifests · cache fingerprints · model artifacts · checkpoints
             directory creation · file existence checks · sha256 of inputs
```

Our pipeline is not just SQL. It's SQL wrapped in Python that manages files.

---

# The audit — every local-filesystem assumption

## 1. Directory creation — 6 call sites

```python
Path(dest).mkdir(parents=True, exist_ok=True)
```

**Where:** `normalize.py`, `parse.py`, `reconcile.py`, `ring_aware.py`, `build.py`,
`train.py`, `splice.py`, `resample.py`

**What breaks:** object storage has no directories. `abfss://` paths are keys with
slashes in them. `pathlib` cannot create them and will either error or create a *local*
directory called `abfss:` — silently, in the container's working directory.

**Fix:** these calls become no-ops when the destination is a URI. DuckDB's `COPY ... TO`
creates the key prefix itself.

## 2. The cache fingerprint — ⚠️ the dangerous one

```python
def input_fingerprint(path):
    for f in sorted(p.rglob("*")):
        st = f.stat()
        h.update(f"{f.relative_to(p)}|{st.st_size}|{int(st.st_mtime)}".encode())
```

**Three separate problems:**

```
rglob()      does not traverse object storage
st_size      available via the blob API, but not through pathlib
st_mtime     ⚠️ blob "last modified" changes on metadata operations, on
             re-upload of identical content, and on some copy operations
```

**Why this is the most dangerous item in the file.** If the fingerprint is wrong in the
*permissive* direction, a stage reports `cached_skip` and returns **stale metrics for
data that changed**. No error. The manifest says success. That is exactly the class of
silent-wrongness this project exists to prevent — reintroduced by the cloud move.

**Fix options:**

| option | verdict |
|---|---|
| use blob `ETag` instead of mtime | ✅ ETag changes iff content changes. Correct primitive |
| use `Content-MD5` | ✅ also correct, slightly more work to populate |
| list + size only, drop mtime | ⚠️ weaker: same-size different-content collides |
| disable caching in the cloud | ⚠️ safe but expensive — loses the whole point |

**Chosen: ETag.** 📋 With a test asserting that modifying a blob changes the fingerprint,
mirroring `test_run_key_changes_when_the_input_changes`.

## 3. Manifest writing

```python
(self.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
```

**What breaks:** `write_text` on a URI writes a local file named after the URI.

**Fix:** an abstraction — `write_json(uri_or_path, obj)` — dispatching to local or blob.

⚠️ **And a subtlety:** the manifest is written in `Run.__exit__`, which runs **even when
the stage raised**. That must keep working, or failed stages stop leaving evidence — and
several bugs in this project were diagnosed from exactly those failure manifests.

## 4. Input sha256

```python
def sha256_file(path, chunk=1 << 20):
    with open(path, "rb") as f:
```

**What breaks:** `open()` on a URI.

**Fix:** stream from blob. ⚠️ Note this reads the whole 17 GB over the network — several
minutes and some egress. The `--no-hash` flag already exists for exactly this; the
decision is whether to hash HI-Large once at upload (recorded in the manifest) rather
than on every run.

**Decision:** hash once during upload, record it, and use `--no-hash` thereafter with the
recorded value carried forward.

## 5. GBDT checkpoints — ⚠️ the second dangerous one

```python
joblib.dump(clf, ckpt)          # ckpt = Path(dest) / "gbdt_seed0.ckpt.joblib"
```

**What breaks:** on Azure ML, the working directory is **ephemeral node disk**. When the
node deallocates — which it does, because `min_nodes = 0` — the checkpoint is gone.

**The consequence:** the entire point of checkpointing is surviving a crash. If the node
dies (preemption, OOM, timeout), the checkpoint dies with it. **Checkpointing that only
survives failures which don't kill the node is nearly useless.**

**Fix:** write checkpoints to a mounted Azure ML output path or directly to ADLS.

⚠️ **Trade-off:** uploading a ~1 MB model every 50 boosting rounds is cheap; uploading a
larger artifact every round would not be. Keep the 50-round interval.

## 6. Model artifacts and score files

```python
joblib.dump(clf, art)
pd.DataFrame({"txn_id": ..., "score": ...}).to_parquet(Path(dest) / "...")
```

**`to_parquet`** accepts URIs via `fsspec`/`adlfs` — works with the right package
installed. **`joblib.dump`** does not — needs the same local-then-upload treatment as
checkpoints.

## 7. Reading the split manifest

```python
cut = json.loads((Path(splits) / "manifest.json").read_text())["config"]["cut_time"]
```

Same fix as (3), read side.

## 8. Test fixtures — no change needed

```python
tests/  →  tmp_path, tmp_path_factory     local by design ✅
```

Unit, leakage, parity, repro and drift tests stay local and fast. Only **contract tests**
optionally point at cloud paths.

---

# The abstraction

Rather than scattering `if is_uri(...)` checks:

```python
# src/aml/io.py   🚧 does not exist yet

def ensure_dir(path)          -> None      no-op for URIs
def write_json(path, obj)     -> None      local or blob
def read_json(path)           -> dict
def write_bytes(path, data)   -> None      for joblib artifacts
def fingerprint(path)         -> str       ETag-based for blobs, sha256 for local files
def exists(path)              -> bool
```

**One module, ~120 lines, one place to test.**

📋 **REQUIREMENT:** every existing test keeps passing against local paths. The abstraction
must not change local behaviour at all.

---

# The gate — a test that must pass before any scale run

🚧 **KNOWN WORK:** `tests/cloud/test_storage_compatibility.py`

```
[ ] run the FULL pipeline on HI-Small against abfss:// paths
[ ] assert identical row counts to the local run
[ ] assert identical metrics to the local run  (bit-identical where deterministic)
[ ] assert manifests are written and readable from blob
[ ] assert a FAILED stage still writes its manifest with status=failed
[ ] assert the cache skips correctly on an unchanged input
[ ] assert the cache RE-RUNS after a blob is modified      ← the ETag test
[ ] assert a GBDT checkpoint survives a simulated node restart
[ ] assert scores round-trip and join by txn_id
```

**HI-Small is 475 MB.** This whole gate runs in minutes and costs cents.

> **The rule: no 182M-row run until this passes on 5M rows in the cloud.** Debugging a
> storage bug during a six-hour job is the expensive way to find it.

---

# Authentication

```
✅ CHOSEN     managed identity via DefaultAzureCredential
              → locally: your az login
              → in Azure ML: the compute's managed identity
              → same code path, no branching, no secret
```

🚧 **KNOWN WORK:** DuckDB's Azure extension needs its credential provider configured to
use the managed identity chain rather than a connection string. Connection strings are
secrets and are not used.

---

# Honest revised claim

**v1 said:** *"one line changes."*

**v2 says:**

> The CLI-first architecture means **no pipeline logic changes** — the SQL, the features,
> the split, the metrics and all 96 tests are untouched. What changes is the **storage
> layer**: roughly 120 lines of new I/O abstraction, eight call-site updates, and a
> cloud-parity test that must pass on HI-Small before HI-Large runs.
>
> 🔬 Estimated at one focused day. Not verified.

That is still a good outcome — most projects would need the pipeline rewritten. But it is
not one line, and saying so was wrong.
