"""One place that knows whether a path is a local directory or an object store.

Why this module exists
----------------------
Every stage of this pipeline is a command that takes paths:

    aml normalize --src <somewhere> --dest <somewhere-else>

The pipeline LOGIC does not care whose disk that is. But the code around the
logic -- manifests, cache fingerprints, model artifacts, checkpoints -- calls
pathlib directly, and pathlib does not speak object storage. `Path("abfss://x")
.mkdir()` does not fail loudly; it creates a LOCAL directory literally named
`abfss:` in the container's working directory, and the run continues.

So: one module, one set of functions, two backends.

The rule that shapes every function here
----------------------------------------
LOCAL PATHS TAKE EXACTLY THE CODE PATH THEY TOOK BEFORE.

Not "an equivalent path" -- the same pathlib calls, in the same order. Remote
support is a new branch taken only when the path is a URI. This is deliberate:
the gate on this work is that all 96 existing tests pass unchanged, and the
cheapest way to guarantee that is to leave the local branch alone rather than
to route local files through a compatibility layer and hope.

Fingerprints, and the reason this module is careful
---------------------------------------------------
The stage cache decides "has this input changed?" from a fingerprint. Locally
that fingerprint uses (size, mtime), which is fine on a real filesystem.

On object storage it is not fine. A blob's last-modified time changes when you
touch its metadata, when you re-upload byte-identical content, and on some
server-side copies. A fingerprint built on it can be wrong in the PERMISSIVE
direction: the data changed, the fingerprint did not, the stage reports
`cached_skip`, and you get stale metrics with no error and a manifest that says
`status: ok`.

That is the exact class of silent wrongness this project exists to detect, so
the remote branch uses the blob ETag. An ETag is an OPAQUE VERSION TOKEN, not
a cryptographic digest: its semantics are provider- and operation-specific,
multipart uploads of identical bytes can produce different ETags, and nothing
in the HTTP spec makes it a function of content alone. What it does guarantee,
and all this code relies on, is that it CHANGES when the object is replaced.
That makes it sound for cache invalidation and unsound as an identity claim,
and those are different things. And when a backend offers neither an ETag nor a content hash, this
module RAISES rather than quietly falling back to something weaker -- see
FingerprintUnavailable below.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

# A URI scheme, not a Windows drive letter: require 2+ characters before "://"
# so "c://tmp" is treated as a path, while "abfss://", "s3://", "az://",
# "file://" and "memory://" are treated as URIs.
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+://")

# Never part of a fingerprint: a stage writes its own manifest INTO its output
# directory, so including it would make every output depend on the record of
# how it was produced, and no cache would ever hit twice.
_FINGERPRINT_EXCLUDE = {"manifest.json"}


class FingerprintUnavailable(RuntimeError):
    """No trustworthy content identity is available for a remote path.

    Raised instead of degrading to (size, mtime). A loud failure here costs an
    afternoon; a silent one costs confidence in every number the run produced.
    """


class StorageDependencyMissing(RuntimeError):
    """A URI was passed but the optional cloud extra is not installed.

    Install with:  pip install -e ".[azure]"
    """


# ---------------------------------------------------------------------------
# What kind of path is this?
# ---------------------------------------------------------------------------

def is_uri(path) -> bool:
    """True for 'abfss://container/x', False for '/tmp/x' or 'data/x'."""
    return bool(_URI.match(str(path)))


def _fs(path):
    """The fsspec filesystem for a URI, plus the path with its scheme stripped.

    fsspec is imported lazily and on purpose. Local runs, CI and all 96 tests
    must not need adlfs, azure-identity or their transitive dependencies
    installed. The cloud extra is only required by people actually touching a
    cloud path.
    """
    try:
        import fsspec
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise StorageDependencyMissing(
            f"{path!s} is a URI but fsspec is not installed. "
            'Install the cloud extra:  pip install -e ".[azure]"'
        ) from e
    return fsspec.core.url_to_fs(str(path))


# ---------------------------------------------------------------------------
# DuckDB connections
# ---------------------------------------------------------------------------

# Account names seen so far on this connection. DuckDB scopes an azure secret
# to one storage account, so a job reading bronze from one account and writing
# gold to another needs two.
_AZURE_SCHEMES = ("abfss://", "abfs://", "azure://", "az://")


def _azure_account(path: str) -> str | None:
    """'abfss://c@acct.dfs.core.windows.net/x' -> 'acct'.

    None when the URI does not name an account. Only the abfss/abfs form
    carries one; 'az://container/path' and 'azure://container/path' do NOT --
    their host is the CONTAINER, and reading it as an account would create a
    secret for a storage account that does not exist, turning a clear 'no
    credential' error into a confusing 'wrong credential' one. Returning None
    lets it fail loudly instead.
    """
    s = str(path)
    if not s.lower().startswith(_AZURE_SCHEMES):
        return None
    host = s.split("://", 1)[1].split("/", 1)[0]
    if "@" not in host:
        return None
    account = host.split("@")[-1].split(".", 1)[0]
    return account or None


# Where distributions put the trusted-root bundle. Debian/Ubuntu first, since
# the container is python:3.12-slim (Debian bookworm).
_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",      # Debian, Ubuntu, Alpine
    "/etc/pki/tls/certs/ca-bundle.crt",        # RHEL, Fedora, Amazon Linux
    "/etc/ssl/ca-bundle.pem",                  # openSUSE
    "/etc/ssl/cert.pem",                       # macOS via openssl, some BSDs
)


def _configure_azure_tls(con) -> None:
    """Make DuckDB's azure extension able to establish TLS inside a container.

    THE SYMPTOM

        Every blob request from inside the image failed with

            Fail to get a new connection for: https://<acct>.blob.core.windows.net.
            Problem with the SSL CA cert (path? access rights?)

        which reads like an authentication problem and is not one. The managed
        identity was correct; the connection never got far enough to use it.

    WHAT ACTUALLY FIXES IT

        `azure_transport_option_type='curl'`. The extension's default transport
        is the Azure SDK's own HTTP stack, and in a slim Debian image that stack
        cannot locate the trust store. libcurl can, so switching transports
        works. Measured on the real thing, all three variants on one VM:

            default transport                       FAIL
            default transport + ca_cert_file        FAIL
            default transport + CURL_CA_BUNDLE=...  FAIL
            default transport + SSL_CERT_FILE=...   FAIL
            azure_transport_option_type='curl'      OK

        Note the two env vars failing: they are the obvious guess, they look
        like they should work, and they do nothing, because the default
        transport is not libcurl and never reads them.

    WHY IT ONLY SHOWS UP IN A CONTAINER

        On a developer machine the default transport finds the trust store, so
        local runs, CI and the file:// storage gate in tests/cloud/ all pass.
        This needs a real blob endpoint over TLS from inside the image, which
        is exactly the gap that gate documents itself as not covering.

    ca_cert_file is set too, from the first bundle that exists. It is not what
    fixed this, but it costs nothing and removes one variable from the next
    person's debugging. Silent when no bundle is found: a wrong path turns
    "cannot verify" into "file not found", which is worse.
    """
    con.execute("SET azure_transport_option_type='curl'")
    for bundle in _CA_BUNDLES:
        if Path(bundle).is_file():
            con.execute("SET ca_cert_file=?", [bundle])
            return


def parquet_arg(path) -> str:
    """The `read_parquet(...)` argument text for a directory of Parquet files.

    WHY A HELPER AND NOT JUST A GLOB

        Every stage read `'{path}/**/*.parquet'`. On a local filesystem that is
        correct. On abfss:// DuckDB refuses it outright:

            Not implemented Error: abfss do not manage recursive lookup
            patterns, bronze/txns_Medium/**/*.parquet is therefore illegal,
            only pattern ending by ** are allowed.

        And the permitted form, `'{path}/**'`, is NOT a drop-in replacement:
        every stage writes its manifest.json INTO its own output directory, so
        `/**` hands read_parquet a JSON file and the read fails on that instead.

        So for remote paths the file list is resolved with fsspec and passed
        explicitly. Sorted, because DuckDB's row order follows file order and
        this project's whole cache-and-digest story depends on the same inputs
        producing the same bytes.

    hive_partitioning is set explicitly rather than left to auto-detection.
    Outputs are partitioned by event_date, and that column exists ONLY in the
    directory names -- if detection were to not fire, `event_date` would simply
    be absent and the failure would surface much later as a missing column.
    """
    if not is_uri(path):
        return f"'{path}/**/*.parquet', hive_partitioning=true"

    fs, base = _fs(path)
    base = base.rstrip("/")
    files = sorted(f for f in fs.find(base) if str(f).endswith(".parquet"))
    if not files:
        raise FileNotFoundError(f"no .parquet files under {path}")
    prefix = str(path).rstrip("/")
    uris = [prefix + str(f)[len(base):] for f in files]
    listed = ", ".join("'" + u.replace("'", "''") + "'" for u in uris)
    return f"[{listed}], hive_partitioning=true"


def duckdb_connect(paths=(), threads: int | None = None,
                   memory_limit: str | None = None, temp_directory: str | None = None):
    """A DuckDB connection that can actually read and write the given paths.

    WHY THIS EXISTS -- the single thing that would have killed the cloud run.

        `io` routes Python-side file access through fsspec, and adlfs picks up
        DefaultAzureCredential with no configuration. DuckDB does NOT use any
        of that. It is an embedded engine with its OWN credential store, so
        `az login` and managed identity are invisible to it until a secret is
        created. Without one, every `read_parquet('abfss://...')` returns

            401 Server failed to authenticate the request

        and every `COPY ... TO 'abfss://...'` fails NoAuthenticationInformation.
        The manifest still writes (that side is fsspec), so the symptom is a
        `status: failed` record sitting in blob storage next to no data.

        Ten call sites open connections. Fixing it in ten places is how one of
        them gets missed, so they all come through here.

    CREDENTIAL_CHAIN, not a connection string: 'cli' covers a developer who ran
    `az login`, 'managed_identity' covers the job running in Azure ML. Neither
    puts a secret in a file, an environment variable, or this repository.

    The extension itself is not installed here on purpose -- DuckDB autoloads
    it, and the container bakes it in at build time so the run does not depend
    on a network fetch at minute one.
    """
    import duckdb

    con = duckdb.connect()

    # Spill destination. DuckDB defaults to the working directory, which inside
    # a container is the image's writable overlay on the node's OS disk. The
    # feature stage is an unbounded-frame window pass over 2x182M account-events
    # and spills tens of GB; filling the OS disk at hour four of a six-hour
    # stage is the failure that cannot be afforded.
    if temp_directory:
        ensure_dir(join(temp_directory, "_"))
        con.execute(f"SET temp_directory='{temp_directory}'")
    if threads:
        con.execute(f"SET threads={int(threads)}")
    if memory_limit:
        con.execute(f"SET memory_limit='{memory_limit}'")

    accounts = {a for p in ([paths] if isinstance(paths, str) else paths)
                if p and (a := _azure_account(p))}
    if accounts:
        _configure_azure_tls(con)
        # SERIALISE AZURE ACCESS. Not a performance tweak -- a correctness one.
        #
        # DuckDB opens Parquet files in parallel, one per compute thread, and
        # the azure extension acquires a fresh token per open rather than
        # caching one. Azure's instance metadata endpoint (IMDS) cannot serve
        # those concurrently, so the run dies with
        #
        #     Failed to get token from ChainedTokenCredential
        #
        # which reads like a misconfigured identity and is not one. Measured on
        # a real VM against 28 Parquet files (31.9M rows):
        #
        #     threads=4                                    FAIL after 2.1s
        #     threads=4 + azure_read_transfer_concurrency=1 FAIL
        #     threads=4 after warming the token on 1 file   FAIL
        #     threads=1                                     OK  (5.9s)
        #
        # It fails on a DIFFERENT file each run, which is the tell that it is
        # concurrency and not permissions. Note the middle two: the obvious
        # fixes -- throttle the extension's own transfers, or warm the token
        # first -- both do nothing, because the token is never cached.
        #
        # An explicit `threads=` from the caller still wins: this is a safe
        # default, not a ceiling. For heavy compute, stage blobs to local disk
        # first and run at full width against local files, which is what
        # scripts/run_cloud.sh does.
        if threads is None:
            con.execute("SET threads=1")
    for i, acct in enumerate(sorted(accounts)):
        # Quoted identifiers are not accepted for secret names, and the account
        # name is not attacker-controlled here (it comes from our own --dest),
        # but keep it out of the SQL anyway.
        con.execute(
            f"CREATE OR REPLACE SECRET aml_az_{i} "
            "(TYPE azure, PROVIDER credential_chain, "
            "CHAIN 'cli;env;managed_identity', ACCOUNT_NAME ?)", [acct])
    return con


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

def ensure_dir(path) -> None:
    """Create a directory tree, on whatever backend the path names.

    Flat object storage has no directories -- 'gold/eval/manifest.json' is one
    key that happens to contain slashes -- so this was originally a no-op for
    every URI. That assumption is wrong for two backends we actually use:

      file://   a real filesystem. DuckDB's `COPY ... TO` creates the leaf
                directory but NOT its missing parents, so the write fails with
                "No such file or directory".
      abfss://  ADLS Gen2 with hierarchical namespace enabled has REAL
                directories, not a flat key space. It is the same shape as the
                file:// case, and it is the configuration this project targets.

    So: attempt it, with parents, and stay quiet if the backend does not care.
    On flat storage `_mkdir` is a harmless no-op; on hierarchical storage it is
    the thing that makes the write work.

    THIS USED TO SUPPRESS EVERY EXCEPTION. An expired credential, a missing
    role assignment and a malformed path all produced silence, and the failure
    surfaced later as an unrelated write error somewhere downstream -- in a
    project whose stated philosophy is to fail loudly. Only the two conditions
    that genuinely mean "nothing to do here" are tolerated now.
    """
    if is_uri(path):
        fs, p = _fs(path)
        try:
            fs.makedirs(p, exist_ok=True)
        except FileExistsError:
            pass
        except NotImplementedError:
            # A flat key space has no directories; there is nothing to create
            # and the subsequent write will succeed regardless.
            print(json_line({"event": "ensure_dir_unsupported", "path": str(path),
                              "backend": type(fs).__name__}))
        except Exception as e:
            raise OSError(
                f"could not create directory {path} on "
                f"{type(fs).__name__}: {e}") from e
        return
    Path(path).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Existence, size
# ---------------------------------------------------------------------------

def exists(path) -> bool:
    if is_uri(path):
        fs, p = _fs(path)
        return fs.exists(p)
    return Path(path).exists()


def size(path) -> int:
    """Size in bytes. Replaces `p.stat().st_size`, which URIs do not support."""
    if is_uri(path):
        fs, p = _fs(path)
        return int(fs.info(p)["size"])
    return Path(path).stat().st_size


# ---------------------------------------------------------------------------
# Bytes and text
# ---------------------------------------------------------------------------

def read_bytes(path) -> bytes:
    if is_uri(path):
        fs, p = _fs(path)
        with fs.open(p, "rb") as f:
            return f.read()
    return Path(path).read_bytes()


def write_bytes(path, data: bytes) -> None:
    if is_uri(path):
        fs, p = _fs(path)
        parent = p.rsplit("/", 1)[0]
        # Some fsspec backends (notably local-file and memory) still want the
        # parent to exist; blob backends treat this as a no-op.
        with contextlib.suppress(NotImplementedError, FileExistsError, ValueError):
            fs.makedirs(parent, exist_ok=True)
        with fs.open(p, "wb") as f:
            f.write(data)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def read_text(path, encoding: str = "utf-8") -> str:
    if is_uri(path):
        return read_bytes(path).decode(encoding)
    return Path(path).read_text(encoding=encoding)


def open_text(path, encoding: str = "utf-8"):
    """A line-iterable text handle, STREAMING. Use as a context manager.

    Streaming is not a nicety here. `schema.read_header()` reads one line to
    validate the CSV contract, and at HI-Large that file is 17 GB. Reading it
    whole to look at the first line would transfer 17 GB, cost egress, and take
    minutes -- to check a header. The pattern parser is the same shape: 13.8 MB
    of text consumed a line at a time.
    """
    if is_uri(path):
        fs, p = _fs(path)
        return fs.open(p, "rt", encoding=encoding)
    return open(path, encoding=encoding)


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write text, committing it in one step rather than in place.

    A manifest written directly is readable in a half-written state: a reader
    that arrives mid-write sees truncated JSON, and `load_cached` correctly
    treats that as a cache miss -- but a human reading it sees a corrupt
    provenance record and cannot tell whether the run failed or the file did.
    Locally `os.replace` makes the swap atomic. On object storage a single PUT
    is already all-or-nothing per key, so the direct write is the atomic one
    and adding a rename would only add a failure mode.
    """
    if is_uri(path):
        write_bytes(path, text.encode(encoding))
        return
    # Matches the previous behaviour of `(out_dir / "manifest.json")
    # .write_text(...)`, which assumed the directory already existed. Creating
    # it here as well is harmless and removes an ordering trap.
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


# ---------------------------------------------------------------------------
# JSON -- the manifest layer
# ---------------------------------------------------------------------------

def read_json(path):
    return json.loads(read_text(path))


def _jsonable(obj):
    """Replace non-finite floats with null, recursively.

    STRICT JSON HAS NO NaN. Python's encoder emits the bare token `NaN` by
    default, every strict parser rejects it, and the supported demo path
    produced exactly that: `bootstrap 0` -> `ci_lo: NaN` in a published
    manifest. A provenance file that a conformant reader cannot parse is not
    provenance, so this normalises rather than trusting callers to.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def json_line(obj, default=None, indent: int | None = None) -> str:
    """One structured event, as JSON a conformant parser will accept.

    THE STORED MANIFESTS WERE FIXED AND THE STDOUT EVENTS WERE NOT. `write_json`
    normalises non-finite floats and passes `allow_nan=False`; every `print(
    json.dumps(...))` in the package went straight through Python's encoder,
    which emits the bare token `NaN`. So a clean wheel run of the demo wrote a
    strict manifest and printed `"ci_lo": NaN` in the same breath -- two output
    paths, one of them fixed, and the fixed one is the one that had been looked
    at. `bootstrap 0` produces exactly that.

    Every event in this package goes through here, so there is one policy
    rather than twenty call sites each making their own.
    """
    return json.dumps(_jsonable(obj), default=default, indent=indent,
                      allow_nan=False)


def write_json(path, obj, indent: int = 2, default=None) -> None:
    # allow_nan=False makes the encoder RAISE on a non-finite value rather than
    # writing an unparseable token; _jsonable means it never has to.
    write_text(path, json.dumps(_jsonable(obj), indent=indent, default=default,
                                allow_nan=False))


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def join(base, *parts) -> str:
    """Join path segments for either backend.

    `Path("abfss://c/x") / "y"` collapses the double slash to `abfss:/c/x/y`,
    which is a different -- and nonexistent -- location. So URIs are joined as
    strings.
    """
    if is_uri(base):
        left = str(base).rstrip("/")
        tail = "/".join(str(x).strip("/") for x in parts if str(x) != "")
        return f"{left}/{tail}" if tail else left
    return str(Path(base).joinpath(*[str(x) for x in parts]))


# ---------------------------------------------------------------------------
# Model artifacts and checkpoints
# ---------------------------------------------------------------------------

def dump_joblib(obj, path) -> None:
    """joblib.dump that also works for URIs.

    joblib writes through a real file handle, so remote destinations get the
    write-locally-then-upload treatment. This matters more than it looks: on
    Azure ML the working directory is EPHEMERAL NODE DISK, and with
    min_nodes = 0 the node is expected to disappear. A GBDT checkpoint written
    to node disk is destroyed by exactly the failures checkpointing exists to
    survive.
    """
    import joblib

    if not is_uri(path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(obj, p)
        return

    tmp_dir = tempfile.mkdtemp(prefix="aml-artifact-")
    tmp = os.path.join(tmp_dir, "artifact.joblib")
    try:
        joblib.dump(obj, tmp)
        with open(tmp, "rb") as f:
            write_bytes(path, f.read())
    finally:
        for leftover in Path(tmp_dir).glob("*"):
            leftover.unlink(missing_ok=True)
        os.rmdir(tmp_dir)


def load_joblib(path):
    import joblib

    if not is_uri(path):
        return joblib.load(path)

    tmp_dir = tempfile.mkdtemp(prefix="aml-artifact-")
    tmp = os.path.join(tmp_dir, "artifact.joblib")
    try:
        with open(tmp, "wb") as f:
            f.write(read_bytes(path))
        return joblib.load(tmp)
    finally:
        for leftover in Path(tmp_dir).glob("*"):
            leftover.unlink(missing_ok=True)
        os.rmdir(tmp_dir)


# ---------------------------------------------------------------------------
# Content identity -- the dangerous one
# ---------------------------------------------------------------------------

def sha256_file(path, chunk: int = 1 << 20) -> str:
    """Streaming sha256 of one file, local or remote.

    Streaming rather than read-then-hash because this is also used on the raw
    CSV, which is 17 GB at HI-Large. Note that hashing a remote 17 GB file
    means transferring 17 GB: hash it once at upload, record it in the
    manifest, and use --no-hash thereafter.
    """
    h = hashlib.sha256()
    if is_uri(path):
        fs, p = _fs(path)
        with fs.open(p, "rb") as f:
            while block := f.read(chunk):
                h.update(block)
        return h.hexdigest()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _remote_content_tag(info: dict, path: str) -> str:
    """A per-blob identity that changes if and only if the content changes.

    Preference order, and why:
      1. ETag         -- what blob storage guarantees for this purpose
      2. content MD5  -- also content-derived; some backends populate only this
      3. nothing      -- RAISE

    Case 3 is the important one. The tempting fallback is (size, mtime), which
    is precisely the broken primitive this module was written to remove: it
    fails permissively, so the cache would serve stale results and say `ok`.
    Better to stop the run and make somebody look.
    """
    for field in ("ETag", "etag", "Etag"):
        tag = info.get(field)
        if tag:
            return str(tag).strip('"')
    for field in ("content_md5", "contentMD5", "md5", "checksum"):
        tag = info.get(field)
        if tag:
            return str(tag)
    raise FingerprintUnavailable(
        f"{path} exposes neither an ETag nor a content hash, so its content "
        "identity cannot be established. Refusing to fall back to size+mtime: "
        "mtime changes on metadata edits and identical re-uploads, so a "
        "fingerprint built on it can report 'unchanged' for changed data and "
        "the stage cache would serve stale results silently."
    )


def stat_files(path, exclude: set | None = None) -> dict:
    """{relative path: (size, mtime_ns)} for every file under a directory.

    The extra `mtime_ns` over `list_files` is what lets a caller tell "this run
    rewrote the file" from "this file was already here". Remote backends may
    not expose a modification time; None is returned for those, which degrades
    the check to size-only rather than breaking it.
    """
    exclude = _FINGERPRINT_EXCLUDE if exclude is None else exclude
    if is_uri(path):
        fs, p = _fs(path)
        if not fs.exists(p):
            return {}
        base = p.rstrip("/")
        out = {}
        for key in sorted(fs.find(base)):
            name = key.rsplit("/", 1)[-1]
            if name in exclude:
                continue
            info = fs.info(key)
            mtime = info.get("mtime") or info.get("last_modified")
            out[key[len(base):].lstrip("/")] = (
                int(info.get("size", 0)), str(mtime) if mtime else None)
        return out

    q = Path(path)
    if not q.exists() or q.is_file():
        return {}
    out = {}
    for f in sorted(q.rglob("*")):
        if f.is_file() and f.name not in exclude:
            st = f.stat()
            out[str(f.relative_to(q))] = (st.st_size, st.st_mtime_ns)
    return out


def remove(path) -> None:
    """Delete one file on either backend. Missing is not an error.

    Used only to retire a file a PREVIOUS run of the same stage wrote and the
    current one did not. Nothing else in this project deletes anything.
    """
    if is_uri(path):
        fs, p = _fs(path)
        with contextlib.suppress(FileNotFoundError):
            fs.rm_file(p) if hasattr(fs, "rm_file") else fs.rm(p)
        return
    with contextlib.suppress(FileNotFoundError):
        Path(path).unlink()


def list_files(path, exclude: set | None = None) -> list[tuple[str, int]]:
    """(relative path, size) for every file under a directory or prefix.

    The backend-neutral primitive the output inventory is built from. Sorted,
    because listing order is not guaranteed on either backend and an unstable
    order would make an inventory compare unequal to itself.
    """
    exclude = _FINGERPRINT_EXCLUDE if exclude is None else exclude
    if is_uri(path):
        fs, p = _fs(path)
        if not fs.exists(p):
            return []
        base = p.rstrip("/")
        if fs.info(base).get("type") == "file":
            return [(base.rsplit("/", 1)[-1], int(fs.info(base).get("size", 0)))]
        out = []
        for key in sorted(fs.find(base)):
            name = key.rsplit("/", 1)[-1]
            if name in exclude:
                continue
            out.append((key[len(base):].lstrip("/"),
                        int(fs.info(key).get("size", 0))))
        return out

    q = Path(path)
    if not q.exists():
        return []
    if q.is_file():
        return [(q.name, q.stat().st_size)]
    return sorted((str(f.relative_to(q)), f.stat().st_size)
                  for f in q.rglob("*")
                  if f.is_file() and f.name not in exclude)


def fingerprint(path) -> str:
    """Cheap content identity for a file or a directory/prefix of files.

    Directory contents are NOT read. Reading 195 MB of Parquet to decide
    whether to skip a stage would cost more than the stage. Locally that means
    (relative path, size, mtime_ns); remotely it means (relative key, ETag).

    NANOSECOND mtime, not integer seconds. With whole seconds, a rewrite that
    lands within the same second and produces the same byte count keeps its
    fingerprint, and the stage is skipped against data that changed. That is
    not hypothetical on a fast local disk with small partitions. This is a
    PROXY for content and is not claimed to be more: a backdated mtime defeats
    it, as does a filesystem with coarse timestamps. It is the cheap check; the
    output inventory in the manifest is the one that verifies what was written.

    Changing this invalidates caches computed by the previous rule, which is
    the correct direction to fail.
    """
    if is_uri(path):
        return _fingerprint_remote(path)

    p = Path(path)
    if not p.exists():
        return "missing"
    if p.is_file():
        return sha256_file(p)[:16]
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.name not in _FINGERPRINT_EXCLUDE:
            st = f.stat()
            h.update(f"{f.relative_to(p)}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def _fingerprint_remote(path) -> str:
    fs, p = _fs(path)
    if not fs.exists(p):
        return "missing"

    # `file://` is a local path wearing a URI. It has no ETag, so the strict
    # remote rule below would refuse it -- but the reason for that rule does
    # not apply here: we can read the bytes and hash them, which is a STRONGER
    # identity than an ETag, not a weaker one. Refusing would also make it
    # impossible to rehearse the cloud path without a cloud account, which is
    # exactly what tests/cloud/ does.
    if fs.protocol in ("file", ("file", "local")) or getattr(fs, "local_file", False):
        return fingerprint(p)

    info = fs.info(p)
    if info.get("type") == "file":
        return _remote_content_tag(info, str(path))[:16]

    base = p.rstrip("/")
    h = hashlib.sha256()
    # fs.find is a recursive listing of files only -- the remote equivalent of
    # rglob() filtered to is_file(). Sorted for the same reason as local:
    # listing order is not guaranteed stable, and an unstable order would make
    # the fingerprint change without the data changing.
    for key in sorted(fs.find(base)):
        name = key.rsplit("/", 1)[-1]
        if name in _FINGERPRINT_EXCLUDE:
            continue
        rel = key[len(base):].lstrip("/")
        tag = _remote_content_tag(fs.info(key), key)
        h.update(f"{rel}|{tag}".encode())
    return h.hexdigest()[:16]
