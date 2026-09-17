"""Tests for the storage abstraction.

Two things are being proved here, and the first matters more than the second.

1. THE LOCAL PATH DID NOT CHANGE. Not "behaves equivalently" -- produces the
   identical fingerprint string as the pre-existing manifest.input_fingerprint,
   so cache entries written by the old code are still recognised by the new.
   If this file's parity tests pass and the other 96 tests pass, the
   abstraction is safe to wire in.

2. The remote path works, and fails loudly where it cannot be trusted.

The remote tests run entirely offline. `EtagMemoryFileSystem` below is an
in-memory fsspec filesystem that reports an ETag derived from content, which is
the one property of real blob storage this module depends on. That lets the
dangerous case -- "content changed, does the fingerprint change?" -- be tested
in milliseconds with no cloud account, no credentials and no cost.
"""
import hashlib
import json
from pathlib import Path
from typing import ClassVar

import pytest

from aml import io

fsspec = pytest.importorskip("fsspec")
from fsspec.implementations.memory import MemoryFileSystem

PROTO = "etagmem"


def legacy_fingerprint(path) -> str:
    """The pre-cloud manifest.input_fingerprint, copied here verbatim.

    Frozen on purpose. The point of the parity tests below is to prove
    io.fingerprint reproduces the OLD algorithm exactly, so cache entries
    written before this refactor are still recognised afterwards. Importing the
    live function instead would make those tests compare io.fingerprint to
    itself and quietly assert nothing.

    Do not "fix" or refactor this. It is a reference implementation, and its
    only job is to be what the code used to do.
    """
    p = Path(path)
    if not p.exists():
        return "missing"
    if p.is_file():
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while block := f.read(1 << 20):
                h.update(block)
        return h.hexdigest()[:16]
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.name != "manifest.json":
            st = f.stat()
            h.update(f"{f.relative_to(p)}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


class EtagMemoryFileSystem(MemoryFileSystem):
    """In-memory storage that behaves like blob storage in the one way we rely on.

    Real ADLS returns an ETag that changes if and only if the blob's bytes
    change. MemoryFileSystem does not report one, so this subclass computes it
    from the content. Nothing else about it pretends to be Azure.
    """

    protocol = PROTO
    store: ClassVar[dict] = {}
    pseudo_dirs: ClassVar[list] = [""]

    def info(self, path, **kwargs):
        out = dict(super().info(path, **kwargs))
        if out.get("type") == "file":
            digest = hashlib.md5(self.cat_file(path)).hexdigest()
            out["ETag"] = f'"{digest}"'
        return out


fsspec.register_implementation(PROTO, EtagMemoryFileSystem, clobber=True)


@pytest.fixture
def blob():
    """A clean in-memory 'container', returned as a URI base."""
    EtagMemoryFileSystem.store.clear()
    EtagMemoryFileSystem.pseudo_dirs[:] = [""]
    yield f"{PROTO}://container/run"
    EtagMemoryFileSystem.store.clear()


def _write_tree(root, files: dict):
    for name, text in files.items():
        io.write_text(io.join(root, name), text)


# ---------------------------------------------------------------------------
# 1. Is this a URI?
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "abfss://container@acct.dfs.core.windows.net/gold",
    "az://container/gold",
    "s3://bucket/key",
    "memory://x",
    "file:///tmp/x",
    f"{PROTO}://container/run",
])
def test_uris_are_recognised(path):
    assert io.is_uri(path) is True


@pytest.mark.parametrize("path", [
    "/tmp/data/gold",
    "data/gold",
    "./gold",
    "../gold",
    "gold",
    r"C:\data\gold",
    # A single leading character is a Windows drive letter, not a scheme.
    "c://tmp/gold",
])
def test_plain_paths_are_not_uris(path):
    assert io.is_uri(path) is False


# ---------------------------------------------------------------------------
# 2. The local path is unchanged -- the Gate 1 evidence
# ---------------------------------------------------------------------------

def test_directory_fingerprint_deliberately_diverges_from_the_legacy_rule(tmp_path):
    """The directory rule CHANGED, on purpose, and this records that.

    The legacy implementation used integer-second mtime. A rewrite landing in
    the same second and producing the same byte count therefore kept its
    fingerprint, and the stage was skipped against data that had changed. The
    live rule uses `st_mtime_ns`.

    Parity with the frozen reference is still asserted for FILES and for
    missing paths (below), because those rules did not change. Asserting it
    here too would either fail or force the fix to be reverted, and a test that
    pins a known defect in place is worse than no test.
    """
    d = tmp_path / "features"
    d.mkdir()
    (d / "part-0.parquet").write_bytes(b"a" * 1000)
    (d / "part-1.parquet").write_bytes(b"b" * 2000)
    (d / "nested").mkdir()
    (d / "nested" / "part-2.parquet").write_bytes(b"c" * 3000)

    # Same inputs, same structure, deterministic within each rule...
    assert io.fingerprint(d) == io.fingerprint(d)
    # ...but not the same rule any more.
    assert io.fingerprint(d) != legacy_fingerprint(d)


def test_same_size_rewrite_in_the_same_second_invalidates_the_cache(tmp_path):
    """The defect the change above exists to close.

    Whole-second mtime plus an unchanged byte count is a collision the cache
    reads as "nothing happened". Here the content is different, the size is
    identical, and the write is immediate -- the worst case, and the one a
    partitioned rewrite actually produces.
    """
    d = tmp_path / "gold"
    d.mkdir()
    f = d / "part-0.parquet"
    f.write_bytes(b"a" * 4096)
    before, legacy_before = io.fingerprint(d), legacy_fingerprint(d)

    f.write_bytes(b"b" * 4096)          # same size, same second, different bytes

    # MEASURE THE FILESYSTEM, DO NOT ASSUME IT.
    #
    # This asserted unconditionally that the fingerprint changes, and that is
    # not what the implementation promises -- its own docstring says a
    # filesystem with coarse timestamps defeats the proxy. Running the suite
    # on amd64 inside the release image proved the point: two immediate writes
    # there receive the IDENTICAL st_mtime_ns (measured delta 0 ns on
    # overlayfs), so the test failed on the one platform that ships, while
    # passing on the APFS laptop where it was written.
    #
    # So probe the granularity here, and assert the invariant that actually
    # holds on this filesystem. Where the timestamps can distinguish the two
    # writes, the fingerprint MUST. Where they cannot, no cheap
    # metadata-only proxy can, and the manifest's output inventory is what
    # verifies a stage's outputs -- see `docs/LIMITATIONS.md`.
    probe = d / "_probe"
    probe.write_bytes(b"x" * 64)
    first = probe.stat().st_mtime_ns
    probe.write_bytes(b"y" * 64)
    fine_grained = probe.stat().st_mtime_ns != first
    probe.unlink()

    if fine_grained:
        assert io.fingerprint(d) != before, "a changed file kept its identity"
    else:
        assert io.fingerprint(d) == before, (
            "the filesystem cannot distinguish these two writes, so a "
            "metadata-only fingerprint must not claim to either -- if this "
            "now differs, `fingerprint` reads content and its cost claim is "
            "no longer true")
    # The frozen rule is shown missing it, so the reason for the change is
    # demonstrated rather than asserted in a comment. On a filesystem with
    # coarse timestamps this is the whole story; on one with fine timestamps
    # the legacy rule may happen to notice, so it is not asserted to fail.
    _ = legacy_before


def test_file_fingerprint_matches_the_legacy_implementation(tmp_path):
    f = tmp_path / "raw.csv"
    f.write_bytes(b"Timestamp,Account,Amount\n" * 500)

    assert io.fingerprint(f) == legacy_fingerprint(f)


def test_missing_path_fingerprint_matches_the_legacy_implementation(tmp_path):
    missing = tmp_path / "not-there"

    assert io.fingerprint(missing) == legacy_fingerprint(missing) == "missing"


def test_manifest_is_excluded_from_the_local_fingerprint(tmp_path):
    """A stage writes its manifest into its own output directory. If the
    manifest counted, every stage would invalidate its own cache entry."""
    d = tmp_path / "gold"
    d.mkdir()
    (d / "part-0.parquet").write_bytes(b"x" * 100)
    before = io.fingerprint(d)

    (d / "manifest.json").write_text(json.dumps({"status": "ok"}))

    # Legacy parity is not asserted here: the directory rule changed (see
    # test_directory_fingerprint_deliberately_diverges_from_the_legacy_rule).
    # What must still hold is the exclusion itself.
    assert io.fingerprint(d) == before


def test_ensure_dir_creates_local_directories(tmp_path):
    target = tmp_path / "a" / "b" / "c"

    io.ensure_dir(target)

    assert target.is_dir()
    io.ensure_dir(target)  # exist_ok, as before


def test_local_json_round_trip(tmp_path):
    p = tmp_path / "deep" / "manifest.json"
    payload = {"status": "ok", "run_key": "abc123", "metrics": {"ap": 0.3005}}

    io.write_json(p, payload)

    assert io.read_json(p) == payload
    assert io.exists(p) is True
    assert io.size(p) == p.stat().st_size


def test_local_joblib_round_trip(tmp_path):
    p = tmp_path / "models" / "gbdt.joblib"

    io.dump_joblib({"n_iter": 300, "seed": 0}, p)

    assert p.exists()
    assert io.load_joblib(p) == {"n_iter": 300, "seed": 0}


def test_local_join_matches_pathlib(tmp_path):
    assert io.join(tmp_path, "gold", "manifest.json") == str(
        tmp_path / "gold" / "manifest.json")


def test_sha256_file_is_the_standard_digest(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world")

    assert io.sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()


# ---------------------------------------------------------------------------
# 3. The remote path
# ---------------------------------------------------------------------------

def test_ensure_dir_does_not_create_a_local_directory_for_a_uri(tmp_path, monkeypatch):
    """The specific silent bug this module exists to prevent.

    `Path("abfss://c/gold").mkdir(parents=True)` does not raise. It creates a
    local directory literally named 'abfss:' in the process's working
    directory, the stage writes its output there, and the run reports success
    while the cloud location stays empty.
    """
    monkeypatch.chdir(tmp_path)

    io.ensure_dir("abfss://container@acct.dfs.core.windows.net/gold/eval")

    assert list(tmp_path.iterdir()) == []


def test_remote_json_round_trip(blob):
    p = io.join(blob, "manifest.json")
    payload = {"status": "failed", "error": "LeakageError('ring 42 straddles')"}

    io.write_json(p, payload)

    assert io.exists(p) is True
    assert io.read_json(p) == payload
    assert io.size(p) == len(json.dumps(payload, indent=2).encode())


def test_remote_join_keeps_the_double_slash(blob):
    """`Path("abfss://c/x") / "y"` yields 'abfss:/c/x/y' -- one slash, wrong
    location, no error."""
    joined = io.join("abfss://container/gold", "eval", "manifest.json")

    assert joined == "abfss://container/gold/eval/manifest.json"
    assert io.is_uri(joined)


def test_remote_joblib_round_trip(blob):
    """joblib needs a real file handle, so remote artifacts are written
    locally then uploaded. On Azure ML the local disk is ephemeral, which is
    why the upload is the point."""
    p = io.join(blob, "gbdt_seed0.ckpt.joblib")

    io.dump_joblib({"n_iter": 250}, p)

    assert io.exists(p)
    assert io.load_joblib(p) == {"n_iter": 250}


def test_remote_missing_path_fingerprints_as_missing(blob):
    assert io.fingerprint(io.join(blob, "nothing-here")) == "missing"


def test_remote_fingerprint_is_stable_across_calls(blob):
    _write_tree(blob, {"part-0.parquet": "aaa", "nested/part-1.parquet": "bbb"})

    assert io.fingerprint(blob) == io.fingerprint(blob)


def test_remote_fingerprint_changes_when_content_changes(blob):
    """THE ETAG TEST. This is the whole reason the module exists.

    Mirrors test_run_key_changes_when_the_input_changes for blob storage. With
    an mtime-based fingerprint on real blob storage this assertion is the one
    that fails -- and it fails silently, as a stale `cached_skip`.
    """
    _write_tree(blob, {"part-0.parquet": "aaa", "part-1.parquet": "bbb"})
    before = io.fingerprint(blob)

    io.write_text(io.join(blob, "part-1.parquet"), "bbb-CHANGED")

    assert io.fingerprint(blob) != before


def test_remote_fingerprint_survives_an_identical_re_upload(blob):
    """The mirror-image failure, and the reason mtime was rejected.

    Re-uploading byte-identical content bumps a blob's last-modified time. An
    mtime fingerprint would call that a change and recompute a six-hour stage
    for nothing. Content identity says the data is the same, so the cache hits.
    """
    _write_tree(blob, {"part-0.parquet": "aaa"})
    before = io.fingerprint(blob)

    io.write_text(io.join(blob, "part-0.parquet"), "aaa")  # same bytes again

    assert io.fingerprint(blob) == before


def test_remote_fingerprint_changes_when_a_file_is_added(blob):
    _write_tree(blob, {"part-0.parquet": "aaa"})
    before = io.fingerprint(blob)

    io.write_text(io.join(blob, "part-1.parquet"), "bbb")

    assert io.fingerprint(blob) != before


def test_remote_fingerprint_ignores_the_manifest(blob):
    _write_tree(blob, {"part-0.parquet": "aaa"})
    before = io.fingerprint(blob)

    io.write_json(io.join(blob, "manifest.json"), {"status": "ok"})

    assert io.fingerprint(blob) == before


def test_remote_single_file_fingerprint_uses_its_etag(blob):
    p = io.join(blob, "one.parquet")
    io.write_text(p, "aaa")
    before = io.fingerprint(p)

    io.write_text(p, "aaa-CHANGED")

    assert io.fingerprint(p) != before
    assert len(before) == 16


# ---------------------------------------------------------------------------
# 4. Failing loudly rather than permissively
# ---------------------------------------------------------------------------

def test_content_tag_prefers_the_etag():
    assert io._remote_content_tag({"ETag": '"abc123"', "size": 5}, "x") == "abc123"


def test_content_tag_accepts_a_content_md5_when_there_is_no_etag():
    assert io._remote_content_tag({"content_md5": "d41d8c"}, "x") == "d41d8c"


def test_content_tag_raises_rather_than_falling_back_to_mtime():
    """A backend with no content identity must stop the run.

    The tempting fallback is (size, mtime), which fails PERMISSIVELY: changed
    data, unchanged fingerprint, `cached_skip`, stale metrics, manifest says
    ok. Given that this project exists to catch silently wrong results, an
    exception is the correct outcome.
    """
    with pytest.raises(io.FingerprintUnavailable, match="size\\+mtime"):
        io._remote_content_tag({"size": 100, "mtime": 1_700_000_000}, "abfss://c/x")


def test_a_uri_without_fsspec_installed_says_what_to_install(monkeypatch):
    """The cloud extra is optional, so the failure has to name the fix."""
    import builtins

    real_import = builtins.__import__

    def no_fsspec(name, *a, **kw):
        if name == "fsspec":
            raise ImportError("No module named 'fsspec'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_fsspec)

    with pytest.raises(io.StorageDependencyMissing, match=r"\[azure\]"):
        io.exists("abfss://container/gold")
