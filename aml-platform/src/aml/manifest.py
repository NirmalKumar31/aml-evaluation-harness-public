"""
Every pipeline component writes a manifest.json describing exactly what it did.

Why: six months from now, "which data and which code produced this number?" must
have an answer. A manifest is that answer, written by the machine, not by you.
"""
import contextlib
import functools
import hashlib
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

from aml import io

# Re-exported: several components import sha256_file from here. It moved to
# aml.io because it now has to stream from blob storage as well as local disk.
sha256_file = io.sha256_file


def config_hash(config: dict) -> str:
    """Same config in -> same hash out. Used as an idempotency key."""
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def git_sha() -> str:
    """The commit this ran from, or "unknown".

    "unknown" is not acceptable for a published result and is the state every
    HI-Large manifest was written in: the container excludes .git (correctly --
    it is not needed at runtime) and the VM builds from a source tarball
    pulled out of blob storage, so no repository metadata reaches the process.
    Seven archived manifests record it, including all three current HI-Large
    fits, which means none of them can be tied to the code that produced them.

    AML_GIT_SHA is the injection point: the image build and the source-tarball
    flow set it from the host, which does have the repository. Set
    AML_REQUIRE_PROVENANCE=1 to make an unknown SHA a hard failure -- do that
    for anything whose numbers will be published.
    """
    injected = os.environ.get("AML_GIT_SHA", "").strip()
    # A SENTINEL IS NOT A SHA, and this returned one ahead of the repository.
    # The release image bakes `AML_GIT_SHA=unknown` into its environment, so a
    # run inside the container recorded `code_git_sha: "unknown"` while
    # `git rev-parse HEAD` in the same working directory resolved the commit
    # perfectly -- the injection point, which exists to SUPPLY provenance a
    # container lacks, was suppressing provenance it had. The artifact then
    # carried `scope_clean: true` beside an unnamed commit, because
    # `dirty_within` asks git directly and got a real answer: an affirmative
    # cleanliness claim about a commit the same file declines to name. It also
    # forced `generator_matches_commit` and `code_tree_matches_commit` to
    # null, since both need a resolvable commit -- which is exactly the
    # "grandfathered provenance" the release checklist demands be closed.
    if injected and injected.lower() not in _NOT_A_SHA:
        return injected
    sha = _git_sha_from_repo()
    if sha == "unknown" and os.environ.get("AML_REQUIRE_PROVENANCE") == "1":
        raise RuntimeError(
            "code provenance is unknown and AML_REQUIRE_PROVENANCE=1. "
            "Set AML_GIT_SHA at build time, or run from a git checkout.")
    return sha


# Values that mean "nobody knew", whoever wrote them. Treated as absent.
_NOT_A_SHA = frozenset({"unknown", "none", "null", "nil", "n/a", "-"})


def _git_sha_from_repo() -> str:
    """The commit of the repository that tracks THIS PACKAGE, or "unknown".

    ⛔ THIS ASKED ABOUT THE PROCESS WORKING DIRECTORY. `git rev-parse HEAD`
    with no `-C` answers about wherever the process happens to be standing, so
    a run whose cwd was an unrelated git repository stamped THAT repository's
    HEAD as the provenance of this code. While the `unknown` sentinel
    short-circuited ahead of it the branch was mostly unreachable; removing
    that short-circuit made it the default path inside the release container,
    which is exactly where provenance matters most. A plausible wrong
    40-character sha is far worse than "unknown", because "unknown" is
    detectable and `AML_REQUIRE_PROVENANCE=1` fires on it, while a real sha
    from the wrong repository passes every downstream check.

    So: ask about the package directory, and require that the repository
    actually TRACKS this package. An installed copy sitting inside somebody
    else's checkout is not provenance.
    """
    pkg = Path(__file__).resolve().parent
    try:
        tracked = subprocess.run(
            ["git", "-C", str(pkg), "ls-files", "--error-unmatch",
             Path(__file__).name],
            capture_output=True)
        if tracked.returncode != 0:
            return "unknown"
        return subprocess.check_output(
            ["git", "-C", str(pkg), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001 - best effort; not being in a git checkout
        return "unknown"      # is normal in a container, and must not fail a run


# ---------------------------------------------------------------------------
# Idempotency: a component that has already run with identical inputs, config
# and code should not run again.
#
# The key is  component + input fingerprint + config hash + code hash.
# Change a feature definition -> features rebuild. Change a model parameter ->
# features do NOT rebuild. That distinction is the whole point; a key built
# from the repo-wide git SHA would invalidate everything on every commit.
# ---------------------------------------------------------------------------

def input_fingerprint(path) -> str:
    """Cheap content identity for a file or a directory tree.

    Directories are fingerprinted from (relative path, size, mtime) rather than
    file contents -- reading 195 MB of Parquet to decide whether to skip a stage
    would defeat the purpose.

    Lives in aml.io now because the two backends need different primitives. On
    a local filesystem, (size, mtime) is a fine proxy for "did this change?".
    On blob storage it is not: last-modified moves on metadata edits and on
    byte-identical re-uploads, so a cache built on it can report `cached_skip`
    for data that DID change -- stale metrics, no error, manifest says ok. The
    remote branch uses the blob ETag instead. Local behaviour is unchanged, and
    tests/unit/test_io.py holds a frozen copy of this function to prove it.
    """
    return io.fingerprint(path)


def code_hash(*modules) -> str:
    """Hash the source of the modules this component explicitly names."""
    h = hashlib.sha256()
    for m in modules:
        h.update(Path(m.__file__).read_bytes())
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=1)
def tree_hash() -> str:
    """Hash every .py in the `aml` package, in sorted relative-path order.

    WHY THE PER-MODULE HASH IS NOT ENOUGH. Each stage hashes the modules it
    names: training hashes train.py and the model config, and NOT the metric
    suite, the manifest layer, the I/O layer or the feature schema. So a change
    to how a metric is computed leaves every cached training result valid, and
    the next run reports the old numbers under the new code with status ok.
    That is the exact failure this project exists to make impossible, sitting
    inside the mechanism meant to prevent it.

    The cost of hashing the whole package is a few hundred kilobytes of reads.
    The cost of not doing it is a silently stale published number. It is also
    recorded in every manifest as `code_tree_sha256` rather than surviving only
    inside a 16-character run key, so two runs can be compared without
    re-deriving it.

    Deliberately coarse: any change anywhere invalidates every cache. Rebuilding
    is cheap and wrong-and-fast is the failure mode being eliminated.
    """
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for f in sorted(root.rglob("*.py")):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def run_key(component: str, config: dict, inputs: list, modules: tuple = ()) -> str:
    """The idempotency key: same component, config, code, environment, inputs.

    THE ENVIRONMENT IS PART OF THE COMPUTATION, and it used not to be in here.
    The key covered the component, the config, the named modules, the whole
    package tree and the input fingerprints -- everything except the libraries
    that do the arithmetic. A new DuckDB, NumPy or LightGBM build can change a
    result while every one of those stays identical, so the cache would serve
    the old answer under the new stack and the manifest would record
    `status: ok`. That is precisely the failure this project exists to make
    impossible, and it was sitting inside the mechanism meant to prevent it.

    `env_id()` is the declared lock digest plus the interpreter version. It is
    not proof that the INSTALLED set matches the lock -- `installed_matches_lock`
    records that separately, because a claim and a check are different things.
    """
    parts = [component, config_hash(config), code_hash(*modules), tree_hash()[:16],
             env_id()]
    parts += [input_fingerprint(i) for i in inputs]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


@functools.lru_cache(maxsize=1)
def installed_id() -> str:
    """A digest of the numeric libraries ACTUALLY importable here.

    The declared lock is a statement of intent. This is what is installed, and
    it belongs in the cache key because it is what does the arithmetic.
    """
    import importlib.metadata as md

    parts = []
    for dep in NUMERIC_DEPS:
        try:
            parts.append(f"{dep}=={md.version(dep)}")
        except md.PackageNotFoundError:
            parts.append(f"{dep}==ABSENT")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


@functools.lru_cache(maxsize=1)
def platform_id() -> str:
    """The machine, not just the interpreter: OS, OS version and CPU.

    `sysconfig.get_platform()` is the canonical wheel-compatibility tag, and
    `system`/`machine` are beside it because they are what a reader recognises
    and what this project actually compared.

    ⚠️ THE TAG IS NOT UNIFORMLY SPECIFIC, and the comment here used to claim it
    was. On macOS it carries the OS version -- `macosx-26.3-arm64` -- and on
    Linux it generally does not: `linux-x86_64` says nothing about the
    distribution or the kernel. So "the key includes the OS version" was true
    on the development machine and false on the machine that ran the 179.7M-row
    job, which is the wrong way round. `platform.release()` is included to make
    the kernel/build explicit on both.

    THE TRADE IS DELIBERATE. A kernel or OS point upgrade now invalidates
    caches. That is the same conservative direction `tree_hash()` already
    takes by invalidating everything on any package change: a stage that
    needlessly recomputes costs time, and a stage that silently does not costs
    a wrong number. This project has already been wrong about float behaviour
    across platforms.
    """
    import sysconfig

    return (f"{sysconfig.get_platform()}|{platform.system()}|"
            f"{platform.machine()}|{platform.release()}")


@functools.lru_cache(maxsize=1)
def env_id() -> str:
    """A short identity for the environment this ran in.

    FOUR PARTS, AND EACH WAS ADDED AFTER AN AUDIT SHOWED THE LAST SET WAS NOT
    ENOUGH.

    The fourth is the platform. A cross-check simulated a move from
    macOS/arm64 to another OS and CPU and got the identical key --
    `platform_changes_key = False` -- while this repository's own evidence is
    that arm64 macOS and amd64 Linux produce *different serialized model
    artifacts*. A cache shared across a mounted volume or a restored directory
    could therefore have served an artifact built on another machine. The
    interpreter version was in the key; the machine running it was not.

    `AML_IMAGE_DIGEST` is folded in when set, so a containerised run is keyed
    to the exact image rather than to the OS tag the image happens to report.
    
    The previous version was the declared lock digest plus the interpreter
    version, and `cached_or_none` refused to SERVE a hit when the installed
    stack disagreed with the lock. A reviewer then did the obvious next thing:

        1. mismatched environment -> cache correctly rejected
        2. the stage recomputes and writes ... under THE SAME KEY
        3. the environment returns to the locked configuration
        4. that result is served as a cache hit

    Guarding the read and leaving the write unguarded is half a fix. The
    installed digest is in the key now, so a mismatched environment computes
    under its own key and cannot occupy the good one. `load_cached` also
    refuses a manifest whose recorded environment was not ok, which covers the
    manifests already on disk.
    """
    lock = env_lock_sha256() or "nolock"
    machine = hashlib.sha256(platform_id().encode()).hexdigest()[:12]
    # VALIDATED, NOT JUST READ. The cloud runners used to fall back to the
    # literal string "unknown" when Docker could resolve neither a registry
    # digest nor a local image id, and this folded it straight in as
    # `+imgunknown` -- so two unrelated unresolved images shared one
    # "exact-image" identity and one cache key. Accepting a placeholder makes
    # the field loudest exactly when it is least true.
    #
    # An unset variable is fine: that is a run outside a container, and the
    # suffix is simply absent. A SET but malformed one is a caller bug and is
    # refused.
    # EXACTLY 64 HEX. The first version of this guard allowed 12 to 64, to be
    # lenient about the short form Docker prints for humans -- which made
    # "exact, immutable image digest" false in the one place it is asserted:
    # `sha256:deadbeefcafe` is a PREFIX, it identifies no image on its own, and
    # two images sharing twelve leading hex digits would share a cache
    # identity. Leniency in an identity check is the whole vulnerability. Both
    # forms `image_digest()` can produce (`RepoDigests[0]` and `.Id`) are full
    # digests, so nothing legitimate is being turned away.
    image = os.environ.get("AML_IMAGE_DIGEST", "").strip()
    if image and not re.fullmatch(r"(?:[^@\s]+@)?sha256:[0-9a-f]{64}", image):
        raise RuntimeError(
            f"AML_IMAGE_DIGEST={image!r} is not a full image digest. Expected "
            f"`sha256:<64 hex>` or `name@sha256:<64 hex>`; an abbreviated "
            f"digest is a prefix, not an identity. Unset it for a run outside "
            f"a container; do not pass a placeholder -- every run that passed "
            f"the same placeholder would share one cache identity.")
    # THE WHOLE DIGEST. The guard above was tightened to require all 64 hex
    # characters and then this line threw 52 of them away, so the collision it
    # was tightened to prevent survived one line below the check: two valid,
    # different images sharing a twelve-character prefix produced the same
    # `+imgdeadbeefcafe` identity and the same cache key. Validating an
    # identity and then storing a prefix of it is not validating an identity.
    #
    # The repository part is dropped on purpose: `ghcr.io/o/r@sha256:X` and
    # `sha256:X` are the same image, and keying them apart would miss hits
    # rather than confuse them.
    suffix = f"+img{image.split(':')[-1]}" if image else ""
    return (f"{lock[:16]}+py{platform.python_version()}+{installed_id()}"
            f"+{machine}{suffix}")


# The libraries whose version can move a number. Not the whole lock: a
# formatter upgrade should not invalidate a 26-minute fit.
NUMERIC_DEPS = ("duckdb", "numpy", "pandas", "scikit-learn", "lightgbm",
                "pyarrow", "scipy")


@functools.lru_cache(maxsize=1)
def installed_matches_lock() -> dict:
    """Do the installed numeric libraries match what requirements.lock declares?

    `env_lock_sha256` records the lock's digest, which says what the environment
    was SUPPOSED to be. An audit made the point that this proves nothing about
    what is actually importable. This compares the two for the packages whose
    version can change a result, and records the answer rather than assuming it.
    """
    import importlib.metadata as md

    lock = None
    for up in (2, 3):
        try:
            cand = Path(__file__).resolve().parents[up] / "requirements.lock"
        except IndexError:
            continue
        if cand.is_file():
            lock = cand
            break
    if lock is None:
        return {"checked": False, "why": "requirements.lock not beside the package"}

    declared = {}
    for line in lock.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        declared[name.strip().lower().replace("_", "-")] = version.strip()

    mismatched, missing, unlocked = {}, [], []
    for dep in NUMERIC_DEPS:
        want = declared.get(dep)
        if want is None:
            # FAIL OPEN, FIXED. A dependency that can move a number and is not
            # in the lock was skipped -- so deleting a line from
            # requirements.lock made the check quieter rather than louder.
            unlocked.append(dep)
            continue
        try:
            got = md.version(dep)
        except md.PackageNotFoundError:
            missing.append(dep)
            continue
        if got != want:
            mismatched[dep] = {"declared": want, "installed": got}
    return {"checked": True, "packages": list(NUMERIC_DEPS),
            "mismatched": mismatched, "missing": missing,
            "unlocked": unlocked,
            "ok": not mismatched and not missing and not unlocked}


# Files larger than this are inventoried by size only. Hashing the 23 GB
# feature table on every cache check would cost far more than rebuilding it;
# hashing a 1 MB model artifact costs nothing. The threshold is recorded in
# every manifest so the policy is visible rather than implied.
OUTPUT_HASH_MAX_BYTES = int(os.environ.get("AML_OUTPUT_HASH_MAX_MB", "64")) << 20


def _full_sha(sha: str) -> str:
    """Expand an abbreviated commit id, when a repository is here to ask.

    `AML_GIT_SHA` is whatever the host injected, and one image build injected
    twelve characters. An abbreviation is ambiguous by construction and cannot
    be resolved in a clone that does not already hold the object, so an
    artifact stamped with one names a commit its reader may not be able to
    find. Expanded here when possible; left alone, and rejected by the
    regression test, when not.
    """
    if not sha or sha == "unknown" or len(sha) >= 40:
        return sha
    try:
        full = subprocess.check_output(
            ["git", "rev-parse", sha], stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        return sha
    return full if len(full) == 40 else sha


# The package's location in the repository, which is the same string from the
# development machine and from inside the container: `aml-platform/src/aml`.
PKG_GIT_PREFIX = "aml-platform/src/aml"


def git_oid(repo_relative: str, commit: str = "HEAD") -> str | None:
    """`git rev-parse <commit>:<path>` -- a CONTENT-ADDRESSED id, or None.

    WHY THIS AND NOT THE COMMIT SHA. A commit sha only resolves in a clone
    that has that commit. The public snapshot of this project shares no
    history with the development archive -- a force-push orphaned the base --
    so every recorded `code_git_sha` is unresolvable there: 13 of 13 derived
    artifacts, in the only repository a reader can clone.

    A blob or tree OID is the sha1 of the CONTENT, so it is identical in any
    repository holding the same bytes, with or without shared history. A
    reader verifies an artifact by running the same `git rev-parse` in their
    own clone and comparing one string. That is a provenance claim they can
    actually check, and it costs one call per artifact.

    It is also strictly stronger than `code_tree_sha256` for the generator:
    that hash covers `src/aml` only, so a modified generator over an
    unmodified package still read "verified".
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent),
             "rev-parse", f"{commit}:{repo_relative}"],
            capture_output=True, text=True)
    except OSError:
        return None
    oid = out.stdout.strip()
    return oid if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", oid) else None


def tree_hash_at(commit: str, prefix: str = PKG_GIT_PREFIX) -> str | None:
    """`tree_hash()` recomputed from git objects at `commit`, or None.

    None means "could not ask" -- no git, or an object this clone does not
    have. Never "did not match".

    This has to reproduce `tree_hash()` byte for byte: the same files, in the
    same order, with the same path strings. `tree_hash` walks
    `sorted(root.rglob("*.py"))` and feeds `str(relative_to(root))` then the
    file bytes, so this lists the tree at `prefix`, strips the prefix, sorts by
    the resulting relative path, and does the same.

    `--full-tree` because pathspecs are otherwise resolved against the current
    directory, and this runs from `aml-platform/` as often as from the root.
    `cat-file --batch` because a per-file subprocess over forty modules is a
    tenth of a second nobody needs to spend.
    """
    if not commit or commit == "unknown":
        return None
    try:
        listing = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "--full-tree", commit, "--", prefix],
            stderr=subprocess.DEVNULL).decode()
    except (OSError, subprocess.CalledProcessError):
        return None

    entries = []
    for record in listing.split("\0"):
        if not record:
            continue
        meta, name = record.split("\t", 1)
        _mode, kind, blob = meta.split()
        if kind == "blob" and name.endswith(".py"):
            entries.append((name[len(prefix) + 1:], blob))
    if not entries:
        return None
    entries.sort()

    try:
        proc = subprocess.run(
            ["git", "cat-file", "--batch"],
            input="\n".join(b for _, b in entries).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None

    out, pos = proc.stdout, 0
    h = hashlib.sha256()
    for relative, _blob in entries:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        if len(header) != 3 or header[1] != b"blob":
            return None
        size = int(header[2])
        body = out[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1                 # trailing newline
        h.update(relative.encode())
        h.update(body)
    return h.hexdigest()


def blob_sha256_at(commit: str, path: str) -> str | None:
    """sha256 of `path` as it existed at `commit`, or None if git cannot say.

    None means "could not check", never "did not match". The container has no
    .git -- that is correct, it is not needed at runtime -- so a check that
    conflated the two would refuse to run in the one environment where the
    HI-Large numbers are actually produced.
    """
    if not commit or commit == "unknown":
        return None
    try:
        blob = subprocess.check_output(
            ["git", "cat-file", "-p", f"{commit}:{path}"],
            stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    return hashlib.sha256(blob).hexdigest()


@functools.lru_cache(maxsize=1)
def env_lock_sha256() -> str | None:
    """The digest of the lock this environment was supposed to be built from.

    The run key covers the config and all of `aml`, and NOT the dependency
    environment -- so a new DuckDB, NumPy or LightGBM build can change results
    while every cache key still matches, and the README's "content-addressed"
    claim quietly covered that gap. Putting the lock digest in the manifest
    does not close it (the lock is what was *declared*, not what is installed),
    but it makes the case detectable after the fact instead of invisible.

    None when the lock is not beside the package, which is the container's
    situation for some paths and not a defect.
    """
    for parents in (2, 3):
        try:
            lock = Path(__file__).resolve().parents[parents] / "requirements.lock"
        except IndexError:
            continue
        if lock.is_file():
            return io.sha256_file(lock)
    return None


# What an artifact's correctness can depend on, unless the caller says wider.
# `src` because every generator imports the package; `scripts` because
# generators import each other -- release_facts.py imports make_tables.py at
# runtime, and editing the sibling changes which result sets are collected
# while the generator's own hash stays clean.
DEFAULT_PROVENANCE_SCOPE = ("aml-platform/src", "aml-platform/scripts")


def dirty_within(scope) -> list[str] | None:
    """Tracked-or-untracked changes inside `scope`, or None if git cannot say.

    None means "no repository to ask", which is the container's honest answer.
    An empty list means asked and clean.
    """
    # `:/` makes each pathspec REPOSITORY-ROOT-RELATIVE. Without it git
    # resolves them against the current directory, so running from
    # `aml-platform/` matched nothing at all and the check silently passed --
    # the same defect that made the first `git ls-tree` reconstruction return
    # None. A guard that cannot fail is not a guard.
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--", *(f":/{p}" for p in scope)],
            stderr=subprocess.DEVNULL).decode()
    except (OSError, subprocess.CalledProcessError):
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


def require_clean_scope(scope: tuple | list | None = None) -> None:
    """Fail NOW, not after the expensive part.

    `generator_provenance` refuses to stamp an artifact when the declared scope
    is dirty, and it runs at the END -- when the artifact is written. The
    split-inflation counterfactual spent 22 minutes on five seeds and 400 draws
    and then refused on its last statement, because an unrelated script had
    been added to the working tree while it ran. The refusal was right and the
    timing was useless.

    Expensive generators call this first. Same rule, same override, one line of
    cost instead of twenty minutes.
    """
    scope = tuple(scope) if scope else DEFAULT_PROVENANCE_SCOPE
    if os.environ.get("AML_ALLOW_DIRTY_PROVENANCE") == "1":
        return
    dirty = dirty_within(scope)
    if dirty:
        listed = "\n  ".join(dirty[:12])
        more = f"\n  ... and {len(dirty) - 12} more" if len(dirty) > 12 else ""
        raise SystemExit(
            f"refusing to start: {len(dirty)} uncommitted change(s) inside the "
            f"declared provenance scope {list(scope)}, so the artifact this "
            f"produces could not be stamped with a commit that contains the "
            f"code that produced it:\n  {listed}{more}\n"
            f"Commit them first. AML_ALLOW_DIRTY_PROVENANCE=1 overrides for "
            f"local iteration; the result must not be committed.")


def generator_provenance(script: str | Path, *,
                         inputs: list | None = None,
                         parameters: dict | None = None,
                         scope: tuple | list | None = None) -> dict:
    """Who made this artifact, in a form that can be checked.

    Three derived artifacts recorded a `code_git_sha` whose commit did not
    contain the script that produced them: they were generated while the
    analysis code was uncommitted, and the code landed in a later commit. A
    commit is not provenance for code that is absent from it, and an audit was
    right to call that invalid rather than untidy.

    So every derived artifact names its generator AND hashes it. CI can then
    resolve the named path at the recorded commit and compare.

    THAT FIX WAS NOT ENOUGH, and the next audit proved it on seven of ten
    artifacts. Naming and hashing the generator does not help if the commit
    recorded beside the hash is one the hash was never in: `git_sha()` returns
    HEAD whether or not the file on disk is what HEAD contains, so regenerating
    an artifact from an edited-but-uncommitted script stamped it with the
    previous commit -- a pair of fields that individually look right and
    together assert something false. Every one of the seven recorded bytes that
    landed in the NEXT commit.

    A hash is only provenance if something refuses to write it when it is
    wrong. So this now resolves the generator AT the commit it is about to
    record and compares:

      * match    -> `generator_matches_commit: true`, and the artifact is
                    verifiable from git objects alone.
      * mismatch -> RuntimeError. Commit the generator first, then regenerate.
      * no git   -> `null`. Recorded as unchecked, never as checked.

    Set AML_ALLOW_DIRTY_PROVENANCE=1 to downgrade the refusal to a recorded
    `generator_matches_commit: false` -- for local iteration, never for an
    artifact that will be committed. The regression test rejects `false`.
    """
    p = Path(script).resolve()
    # A PATH GIT CAN RESOLVE, from either environment.
    #
    # Two wrong versions preceded this. The first used the package directory as
    # the root and produced "scripts/x.py", where git needs
    # "aml-platform/scripts/x.py". The second used the git root -- correct on
    # the development machine and wrong inside the container, where the package
    # lives at /app and the relative path came out "app/scripts/x.py".
    #
    # So: anchor on the PACKAGE directory, which is `aml-platform/` in the repo
    # and `/app` in the image, then prefix the repository-relative name. That
    # is the same string in both places, which is the only property that
    # matters for `git cat-file -e <sha>:<path>`.
    pkg_root = Path(__file__).resolve().parents[2]
    try:
        rel = f"aml-platform/{p.relative_to(pkg_root)}"
    except ValueError:
        rel = p.name
    sha = _full_sha(git_sha())
    digest = sha256_file(p)
    at_commit = blob_sha256_at(sha, rel)
    matches = None if at_commit is None else (at_commit == digest)

    # THE GENERATOR IS ONE FILE. IT IMPORTS THE PACKAGE.
    #
    # The check above compares the generator script against the commit. An
    # audit then did the obvious next thing: edited `src/aml/eval/metrics.py`,
    # left `scripts/cost_table.py` alone, and got `generator_matches_commit:
    # true` with a clean HEAD SHA -- an artifact asserting it came from commit
    # X while the implementation that produced it was absent from X. Same false
    # combined assertion, one level down the import graph.
    #
    # `code_tree_sha256` was already recorded and its own comment called it
    # "informational", which is the word that let this through. It is now
    # recomputed from git objects at the recorded commit and compared.
    tree_now = tree_hash()
    tree_at_commit = tree_hash_at(sha)
    tree_matches = None if tree_at_commit is None else (tree_at_commit == tree_now)

    # THE DEPENDENCY CLOSURE, not just the two files we can hash cheaply.
    #
    # The two checks above cover the generator script and the `aml` package.
    # An audit walked straight past both: edit `scripts/make_tables.py`, which
    # `release_facts.py` imports at RUNTIME, and you get
    # `generator_matches_commit: true` AND `code_tree_matches_commit: true`
    # while the collection logic that produced the numbers is absent from the
    # recorded commit. The same artifact also depends on every test file and
    # every Markdown file it counts markers in -- none of which any hash here
    # covers.
    #
    # Chasing the import graph is the clever answer and the fragile one. The
    # blunt rule is the safe one: nothing inside the declared scope may be
    # modified or untracked when an artifact is written. A generator that
    # depends on more declares more.
    scope = tuple(scope) if scope else DEFAULT_PROVENANCE_SCOPE
    dirty = dirty_within(scope)

    if os.environ.get("AML_ALLOW_DIRTY_PROVENANCE") != "1":
        if dirty:
            listed = "\n  ".join(dirty[:12])
            more = f"\n  ... and {len(dirty) - 12} more" if len(dirty) > 12 else ""
            raise RuntimeError(
                f"{len(dirty)} uncommitted change(s) inside the declared "
                f"provenance scope {list(scope)}, so this artifact would name "
                f"a commit that does not contain the code that produced it:\n"
                f"  {listed}{more}\n"
                f"Commit them, then regenerate. AML_ALLOW_DIRTY_PROVENANCE=1 "
                f"overrides for local iteration; the result must not be "
                f"committed.")
        if matches is False:
            raise RuntimeError(
                f"{rel} on disk is not what {sha[:12]} contains, so recording "
                f"that commit beside its hash would be false provenance.\n"
                f"  on disk   {digest}\n"
                f"  at commit {at_commit}\n"
                f"Commit the generator, then regenerate the artifact. "
                f"AML_ALLOW_DIRTY_PROVENANCE=1 overrides for local iteration; "
                f"the result must not be committed.")
        if tree_matches is False:
            raise RuntimeError(
                f"{rel} matches {sha[:12]}, but the `aml` package it imports "
                f"does not. The artifact would name a commit that does not "
                f"contain the code that produced it.\n"
                f"  package on disk   {tree_now}\n"
                f"  package at commit {tree_at_commit}\n"
                f"Commit the package change, then regenerate. "
                f"AML_ALLOW_DIRTY_PROVENANCE=1 overrides for local iteration; "
                f"the result must not be committed.")

    prov = {
        "code_git_sha": sha,
        "generator_script": rel,
        "generator_sha256": digest,
        # The claim the regression test re-derives from git objects. `null`
        # means this environment had no repository to ask, which is the
        # container's honest answer; `false` means it asked and the answer was
        # no, which is a defect that was written down rather than hidden.
        "generator_matches_commit": matches,
        # The package bytes, and whether they are the ones at that commit.
        # `null` means no repository to ask; `false` means it asked and the
        # answer was no, which the regression test rejects.
        "code_tree_sha256": tree_now,
        "code_tree_matches_commit": tree_matches,
        # CONTENT-ADDRESSED, so a reader can check these in a clone that has
        # none of this repository's history. See `git_oid`.
        "generator_blob_oid": git_oid(rel),
        "package_tree_oid": git_oid(PKG_GIT_PREFIX),
        # WHAT WAS REQUIRED TO BE CLEAN, recorded so a reader knows how wide
        # the guarantee is rather than having to infer it.
        "provenance_scope": list(scope),
        "scope_clean": None if dirty is None else not dirty,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # Environment identity. Two artifacts generated by identical code can
        # still differ, and the interpreter is the cheapest part of that to
        # record.
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "env_lock_sha256": env_lock_sha256(),
        "status": "ok",
    }
    # Inputs and parameters, when the generator knows them. A commit identifies
    # the code; it says nothing about what the code was pointed at.
    if inputs is not None:
        prov["inputs"] = [_input_identity(i) for i in inputs]
    if parameters is not None:
        prov["parameters"] = parameters
    return prov


def _portable_path(p: Path) -> str:
    """Repository-relative when possible, absolute only as a fallback.

    A committed artifact recorded the maintainer's absolute home directory as
    the identity of its input. That is not a secret, but it is not portable
    either -- the same regeneration on another machine produces a different
    string for the same input -- and it puts local-machine detail into a file
    that ships in the wheel's sibling archive.
    """
    p = Path(p)
    try:
        here = p if p.is_dir() else p.parent
        for base in [here, *here.parents]:
            if (base / ".git").exists():
                return str(p.resolve().relative_to(base.resolve()))
    except (OSError, ValueError):
        pass
    return str(p)


def _input_identity(item) -> dict:
    """Identify one input.

    A file is hashed if it is small enough to be worth hashing; a directory is
    fingerprinted by its sorted (relative path, size) listing. The second is
    METADATA-addressed, not content-addressed, and the entry says so -- an
    audit was right that calling a size-and-name fingerprint "content
    addressing" overstates what it detects.
    """
    if isinstance(item, dict):
        return item
    p = Path(item)
    entry: dict = {"path": _portable_path(p)}
    if not p.exists():
        entry["error"] = "does not exist"
        return entry
    if p.is_dir():
        files = sorted(f for f in p.rglob("*") if f.is_file())
        h = hashlib.sha256()
        total = 0
        for f in files:
            size = f.stat().st_size
            total += size
            h.update(str(f.relative_to(p)).encode())
            h.update(str(size).encode())
        entry.update(kind="directory", n_files=len(files), bytes=total,
                     listing_sha256=h.hexdigest())
        # CONTENT WHEN IT IS AFFORDABLE, and say which was used.
        #
        # A path-and-size listing does not notice a file whose bytes changed
        # without its size changing -- and the replay bundles, the input this
        # matters most for, are 9.2 MB in total. Refusing to hash 9 MB while
        # calling the result an input identity was a choice made for
        # multi-gigabyte inputs and applied indiscriminately.
        if total <= OUTPUT_HASH_MAX_BYTES:
            c = hashlib.sha256()
            for f in files:
                c.update(str(f.relative_to(p)).encode())
                c.update(sha256_file(f).encode())
            entry["content_sha256"] = c.hexdigest()
            entry["identity"] = "content (every file hashed)"
        else:
            entry["identity"] = "metadata (path and size), NOT content"
            entry["identity_reason"] = (
                f"{total} bytes exceeds OUTPUT_HASH_MAX_BYTES="
                f"{OUTPUT_HASH_MAX_BYTES}")
        return entry
    try:
        entry["bytes"] = p.stat().st_size
    except OSError as e:
        entry["error"] = repr(e)
        return entry
    entry["kind"] = "file"
    if entry["bytes"] <= OUTPUT_HASH_MAX_BYTES:
        entry["sha256"] = sha256_file(p)
    else:
        # Deliberately not hashed, and deliberately SAID so rather than left
        # to look like an input with no hash for an unstated reason.
        entry["sha256"] = None
        entry["sha256_skipped"] = f"larger than {OUTPUT_HASH_MAX_BYTES} bytes"
    return entry


def output_inventory(out_dir) -> list[dict]:
    """What this stage actually wrote: path, size, and hash where affordable."""
    inv = []
    for rel, nbytes in io.list_files(out_dir):
        entry = {"path": rel, "bytes": nbytes}
        if nbytes <= OUTPUT_HASH_MAX_BYTES:
            try:
                entry["sha256"] = io.sha256_file(io.join(out_dir, rel))
            except Exception as e:  # noqa: BLE001 - a hash we could not take is
                entry["sha256_error"] = repr(e)   # recorded, never silently
        inv.append(entry)                          # dropped
    return inv


def verify_outputs(out_dir, inventory: list[dict]) -> str | None:
    """None if the outputs still match the inventory, else why they do not."""
    if not inventory:
        return None
    have = dict(io.list_files(out_dir))
    for entry in inventory:
        rel = entry["path"]
        if rel not in have:
            return f"missing output {rel}"
        if have[rel] != entry.get("bytes"):
            return (f"size changed for {rel}: "
                    f"{entry.get('bytes')} -> {have[rel]}")
        want = entry.get("sha256")
        if want:
            try:
                got = io.sha256_file(io.join(out_dir, rel))
            except Exception as e:  # noqa: BLE001
                return f"could not hash {rel}: {e!r}"
            if got != want:
                return f"content changed for {rel}"
    return None


def load_cached(out_dir, key: str) -> dict | None:
    """Return the previous run's metrics if it succeeded with this exact key."""
    mf = io.join(out_dir, "manifest.json")
    if not io.exists(mf):
        return None
    try:
        m = io.read_json(mf)
    except Exception:  # noqa: BLE001 - an unreadable or truncated manifest means
        return None    # "no usable cache entry", which is a cache MISS, not a
                       # crash. Failing here would make a corrupt file fatal.
    if m.get("run_key") != key or m.get("status") != "ok":
        return None

    # THE ENVIRONMENT THE CACHED RUN ACTUALLY HAD.
    #
    # Belt and braces with `env_id()`: the installed digest is in the key, so a
    # mismatched environment writes under its own key -- but manifests already
    # on disk predate that, and a manifest that RECORDS a mismatch must not be
    # served whatever its key says. A result computed under the wrong NumPy is
    # not a cache entry; it is a result that needs redoing.
    recorded_env = (m.get("env") or {}).get("installed_matches_lock") or {}
    if recorded_env.get("checked") and not recorded_env.get("ok"):
        print(io.json_line({
            "event": "cache_rejected", "run_key": key,
            "why": "the cached run recorded an installed stack that did not "
                   "match its lock",
            "mismatched": recorded_env.get("mismatched"),
            "missing": recorded_env.get("missing"),
            "unlocked": recorded_env.get("unlocked")}))
        return None

    # THE MANIFEST IS NOT THE OUTPUT.
    #
    # This used to return here. A stage whose Parquet had been deleted, moved,
    # truncated or half-written still had an intact manifest with status ok, so
    # the cache reported a hit and the next stage read whatever was left --
    # or nothing. Provenance that does not check the thing it describes is
    # decoration.
    if "outputs" not in m:
        # LEGACY MANIFEST, NO INVENTORY -- not a usable cache entry.
        #
        # `verify_outputs` treats an empty inventory as "nothing to check", so a
        # manifest predating the inventory could cache-hit while verifying
        # NOTHING. 69 committed manifests are in that state. An absent key and
        # an empty list mean different things: the first is "we do not know
        # what this wrote", the second is "it wrote nothing".
        print(io.json_line({"event": "cache_rejected", "run_key": key,
                          "out_dir": str(out_dir),
                          "reason": "manifest has no output inventory"}))
        return None
    why = verify_outputs(out_dir, m.get("outputs") or [])
    if why is not None:
        print(io.json_line({"event": "cache_rejected", "run_key": key,
                          "out_dir": str(out_dir), "reason": why}))
        return None
    return m.get("metrics")


def cached_or_none(component: str, config: dict, inputs: list, out_dir,
                   modules: tuple = (), force: bool = False):
    """(key, cached_metrics_or_None). Call at the top of every component.

    THE ENVIRONMENT IS CHECKED BEFORE THE HIT, not after it.

    `run_key` includes `env_id()`, which is the DECLARED lock digest plus the
    interpreter version -- so editing the lock misses the cache. Installing a
    different NumPy without touching the lock does not, and an audit made
    exactly that point: `installed_matches_lock()` was evaluated at stage EXIT,
    when a manifest is written, and a cache hit returns before any manifest
    exists. The stack that would have produced a different answer got the old
    answer, and the record beside it described the old run's environment.

    So the check moves in front of the lookup. A mismatch refuses the cache
    rather than serving it; the stage recomputes and records what it actually
    ran under.
    """
    key = run_key(component, config, inputs, modules)
    if force:
        return key, None

    env = installed_matches_lock()
    if env.get("checked") and not env.get("ok"):
        print(io.json_line({
            "event": "cache_rejected", "run_key": key, "component": component,
            "why": "the installed numeric stack does not match requirements.lock",
            "mismatched": env.get("mismatched"), "missing": env.get("missing"),
            "note": "the run key covers the DECLARED lock; this is the "
                    "installed one. Recomputing rather than serving a result "
                    "produced under different libraries."}))
        return key, None

    hit = load_cached(out_dir, key)
    if hit is not None:
        print(io.json_line({"event": "cached_skip", "component": component,
                          "run_key": key, "out_dir": str(out_dir)}))
    return key, hit


class Run:
    """Context manager that times a component and writes its manifest."""

    def __init__(self, component: str, config: dict, out_dir, key: str | None = None):
        self.component = component
        self.config = config
        # Kept as a string, not a Path. Path("abfss://c/gold") silently
        # rewrites the double slash to "abfss:/c/gold" -- a different and
        # nonexistent location, with no error. io.join() handles both forms.
        self.out_dir = str(out_dir)
        self.key = key
        self.metrics = {}

    def __enter__(self):
        self.t0 = time.time()
        # SNAPSHOT BEFORE THE STAGE RUNS.
        #
        # Without this, "which files did this run write?" is unanswerable at
        # exit: the stale files from the previous run are still sitting in the
        # directory, so an inventory taken afterwards lists them as current.
        # The first version of the stale-output cleanup did exactly that and
        # was therefore a NO-OP for the case it was written for -- while its
        # test passed, because the test deleted the stale file by hand first.
        self._before = io.stat_files(self.out_dir)
        return self

    def _previous_inventory(self) -> list[dict]:
        mf = io.join(self.out_dir, "manifest.json")
        if not io.exists(mf):
            return []
        try:
            return io.read_json(mf).get("outputs") or []
        except Exception:  # noqa: BLE001 - an unreadable previous manifest means
            return []      # we cannot know what it wrote, so remove nothing

    def record(self, **kw):
        self.metrics.update(kw)

    def __exit__(self, exc_type, exc, tb):
        # Runs even when the stage raised. Several bugs in this project were
        # diagnosed from a status=failed manifest, so this must not become
        # conditional -- and must not itself fail on a URI destination.
        io.ensure_dir(self.out_dir)

        # STALE PARTITIONS SURVIVE AN OVERWRITE.
        #
        # Stages write with DuckDB's OVERWRITE_OR_IGNORE into an existing
        # partitioned destination. If a rerun emits FEWER partitions than the
        # run before it -- a narrower date range, a smaller sample -- the old
        # files are not removed, and the next reader sees two generations
        # blended into one dataset with no error anywhere. Files the previous
        # run of THIS stage wrote and this one did not are removed, and the
        # removal is recorded. Nothing else is touched.
        previous, removed = self._previous_inventory(), []
        if previous and not exc_type:
            # A file is stale when the PREVIOUS run listed it as an output and
            # THIS run did not touch it -- same size and same mtime as before
            # the stage started. DuckDB's OVERWRITE_OR_IGNORE leaves such files
            # in place, so a rerun emitting fewer partitions silently blends two
            # generations into one dataset.
            after = io.stat_files(self.out_dir)
            before = getattr(self, "_before", {})
            untouched = {rel for rel, st in after.items() if before.get(rel) == st}
            for entry in previous:
                if entry["path"] in untouched:
                    with contextlib.suppress(Exception):
                        io.remove(io.join(self.out_dir, entry["path"]))
                        removed.append(entry["path"])
        inventory = output_inventory(self.out_dir) if not exc_type else []

        manifest = {
            "component": self.component,
            "run_key": self.key,
            "status": "failed" if exc_type else "ok",
            "error": repr(exc) if exc else None,
            "config": self.config,
            "config_hash": config_hash(self.config),
            "code_git_sha": git_sha(),
            "wall_clock_sec": round(time.time() - self.t0, 3),
            "metrics": self.metrics,
            "outputs": inventory,
            "output_hash_max_bytes": OUTPUT_HASH_MAX_BYTES,
            "stale_outputs_removed": removed,
            "code_tree_sha256": tree_hash(),
            "env": {"python": platform.python_version(),
                    "platform": platform.platform(),
                    # The wheel-compatibility tag, which is what the cache key
                    # hashes. `platform.platform()` above is for humans.
                    "platform_id": platform_id(),
                    "image_digest": os.environ.get("AML_IMAGE_DIGEST") or None,
                    # DECLARED, not installed: the digest of requirements.lock,
                    # which is what the environment was meant to be built from.
                    # The run key DOES include it (via env_id), so editing the
                    # lock misses the cache -- this comment claimed the
                    # opposite for one audit round after the change landed.
                    "lock_sha256": env_lock_sha256(),
                    # The lock is what was DECLARED. This is whether the
                    # numeric libraries actually importable here agree with it.
                    "installed_matches_lock": installed_matches_lock()},
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        mf = io.join(self.out_dir, "manifest.json")
        io.write_json(mf, manifest)
        print(io.json_line({"event": "manifest_written", "path": mf,
                          "status": manifest["status"]}))
        return False  # never swallow the exception
