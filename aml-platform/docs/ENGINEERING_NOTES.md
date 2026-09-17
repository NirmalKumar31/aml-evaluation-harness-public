# Engineering notes

> ⚠️ These passages were moved verbatim out of the README, caveats included.
> One phrase was corrected in transit: the comparison is **15 metrics, all
> matching**, plus a sixteenth quantity that is not a metric at all — the
> serialized model file's hash. "15 of 16 metrics" counted a file as a metric.

Detail moved out of the README so that a first-time reader is not required to
work through it. Nothing here is abridged — these are the passages verbatim,
with their caveats, because the caveats are the point.

For the correction history, see [`CHANGELOG.md`](../../CHANGELOG.md).
For what may and may not be claimed, see [`LIMITATIONS.md`](LIMITATIONS.md).

---

## 1. What the stage cache is actually addressed on

⚠️ **"Content-addressed" was too strong for part of this, and the caveat
matters.** The run key covers the config, the per-module code hashes and the
whole-package tree hash — so a change anywhere in `aml` invalidates every
cache, which is the important half. But a local directory input is
fingerprinted by **path, size and mtime**, not by content, and an output over
64 MB is inventoried by size alone (the threshold is recorded in each
manifest). So the cache is **metadata-addressed at the data boundary** and
content-addressed for code. It will not notice a file whose bytes changed
without its size or mtime changing, and it did **not** key on the dependency
environment: a new DuckDB, NumPy or LightGBM build can change results while the
key still matches. Manifests record the interpreter, platform and the lock
digest, and the run key now includes an environment identity so a dependency
or platform change misses the cache instead of silently hitting it: the lock
digest, the interpreter version, a digest of the **installed** numeric
libraries, the OS/architecture/kernel tag, and the image digest, which the
cloud runners and the in-image test step now pass in. Each of those five was added after an audit
showed the previous set was not enough — the platform last, because this
project's own evidence is that arm64 macOS and amd64 Linux produce different
serialized model artifacts while the key could not tell them apart. Whether
the installed stack matches the lock is still recorded separately as
`installed_matches_lock`, and a cached run that recorded a mismatch is
refused.

---

## 2. Cross-architecture reproducibility, and exactly what it establishes

```text
                          laptop (arm64 macOS)    cloud (amd64 Linux)
average_precision          0.282400339714525      0.282400339714525   ✅
precision@50               0.793981481481482      0.793981481481482   ✅
ring_recall@200            0.693761814744801      0.693761814744801   ✅
bootstrap ci_lo / ci_hi          both match             both match    ✅
rows, positives, splits          all match              all match    ✅
────────────────────────────────────────────────────────────────────────
model_artifact_sha256          084dae41d5f0…          c9c38059498b…   ❌
```

**All 15 recorded metrics identical**, to full float precision — including a 500-resample
bootstrap, so the bootstrap RNG reproduces across architectures.

The defensible claim is therefore not "identical model file" but:

> same code, different architecture, different OS, containerised, blob-sourced
> data — **every metric recorded in both manifests agrees to full float
> precision**.

### The two prediction digests

> **Two digests, because they answer different questions.**
> `predictions_sha256` hashes the ordered `(txn_id, dtype, score)` payload
> read back from Parquet — it settles ***logical payload identity***: the same
> transactions, in the same order, with the same scores at the same dtype.
>
> It is **not** a hash of the serialized Parquet bytes, and an earlier version
> of this line said it settled *"are these the same bytes?"*, which it does
> not: compression level, row-group size and writer version all change the file
> without changing the predictions. Logical identity is the more useful claim
> anyway — it is the one that survives re-writing the file — but it is a
> different claim, and the wording now says which.
> `predictions_tolerance_sha256` hashes the float32 quantisation — it settles
> *"do these agree to a precision any metric could see?"*, which is the useful
> question across platforms.
>
> ⚠️ Until the seventh audit there was only one field, and it held the float32
> quantisation while being described as bitwise identity — a digest of a
> representation that is neither stored (the Parquet field is `double`) nor
> evaluated (`evaluate` gets the float64 array). **Manifests written before that
> change hold the old definition**, so their `predictions_sha256` is a
> tolerance digest and is not comparable with a value computed today. <!-- historical -->

---

## 3. Three defects that only appeared against real Azure

Three defects surfaced only under real Azure, invisible to local runs, to CI,
and to the `file://` gate below:

| defect | why it is not what it looks like |
|---|---|
| TLS failed inside the container | reads as an auth failure; `ca_cert_file`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE` all do nothing — the default transport is not libcurl and never reads them. Fixed by `azure_transport_option_type='curl'` |
| `**/*.parquet` rejected on `abfss://` | and the permitted `/**` is no substitute: each stage writes `manifest.json` into its own output directory, so it hands `read_parquet` a JSON file |
| `Failed to get token from ChainedTokenCredential` | reads as a broken identity. It is concurrency: DuckDB fetches a token per file open and never caches, and IMDS cannot serve those in parallel. It failed on a *different file each run* — that was the tell |
