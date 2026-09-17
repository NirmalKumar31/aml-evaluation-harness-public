"""
GATE 3: does the pipeline run when every path is a URI instead of a local path?

WHY THIS TEST EXISTS, AND WHY IT IS NOT AN AZURE TEST

    The cloud run is one-shot and paid. The failure we cannot afford is a stage
    that works perfectly on `data/gold/x` and dies on `abfss://c@acct.../gold/x`
    -- discovered at minute forty of a run that has already provisioned a
    cluster. That failure has nothing to do with Azure specifically. It is a
    LOCAL PATH ASSUMPTION: a `Path(...)`, an `open()`, an `os.makedirs`, a
    string concatenation that collapses `//`, a DuckDB connection with no
    credential attached.

    Every one of those breaks identically under `file://`, which fsspec and
    DuckDB both accept, and which costs nothing and needs no account. So this
    runs the WHOLE pipeline through `file://` URIs and asserts it produces the
    same answers as the local-path run.

    What this proves:   no stage assumes a local filesystem path.
    What it does NOT:   nothing about Azure auth, RBAC, or network behaviour.
                        Those need a real account and are checked by the
                        smoke run, not here.

    The distinction matters. Passing this does not mean the cloud run will
    work. FAILING it means the cloud run definitely will not, and finding that
    out here costs seconds instead of an afternoon and a cluster.
"""

import re
from pathlib import Path

import duckdb
import pytest

from aml import io
from aml.features.build import build as build_features
from aml.ingest.normalize import normalize
from aml.patterns.parse import parse
from aml.patterns.reconcile import reconcile
from aml.splits.ring_aware import build as build_splits

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mini_trans.csv"


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    """The same pipeline twice: once on plain paths, once on file:// URIs."""
    root = tmp_path_factory.mktemp("gate3")

    out = {}
    for mode in ("local", "uri"):
        base = root / mode
        base.mkdir()
        # The ONLY difference between the two runs. Bound as defaults rather
        # than closed over: a late-binding closure here would silently make
        # both iterations write to the SECOND directory, and the comparison
        # would trivially pass.
        pre = "" if mode == "local" else "file://"

        def d(*p, _pre=pre, _base=base):
            return _pre + str(_base.joinpath(*p))

        src = pre + str(FIXTURE)
        normalize(src, d("bronze", "txns"), hash_input=False)
        out[mode] = {"bronze": d("bronze", "txns")}
    return out


def test_uri_paths_are_recognised_as_uris(two_runs):
    """Guard the guard: if file:// were treated as a local path, this whole
    test would pass while exercising nothing."""
    assert io.is_uri(two_runs["uri"]["bronze"])
    assert not io.is_uri(two_runs["local"]["bronze"])


def test_ingest_produces_identical_output_through_a_uri(two_runs):
    """Same rows, same txn_id range, from a URI as from a path."""
    q = ("SELECT count(*), min(txn_id), max(txn_id), count(DISTINCT txn_id) "
         "FROM read_parquet('{}/**/*.parquet')")
    con = duckdb.connect()
    a = con.execute(q.format(two_runs["local"]["bronze"])).fetchone()
    b = con.execute(q.format(two_runs["uri"]["bronze"])).fetchone()
    assert a == b
    assert a[0] == a[3], "txn_id not unique"
    assert (a[1], a[2]) == (1, a[0]), "txn_id not contiguous from 1"


def test_manifest_is_readable_back_through_the_uri(two_runs):
    """Stage caching reads the manifest through io. If that only worked on
    local paths, every cloud stage would recompute -- silently, and at cost."""
    m = io.read_json(io.join(two_runs["uri"]["bronze"], "manifest.json"))
    assert m["status"] == "ok"
    assert m["component"] == "normalize_schema"


def test_fingerprint_works_on_a_uri(two_runs):
    """io.fingerprint drives the cache key. On a remote store it must use a
    content tag (ETag), never size+mtime -- and it raises rather than degrade.
    Here we only assert it RETURNS, i.e. the remote branch is reachable."""
    fp = io.fingerprint(two_runs["uri"]["bronze"])
    assert isinstance(fp, str) and len(fp) > 0


def test_duckdb_connect_attaches_no_secret_for_non_azure_uris():
    """The connection factory must not invent a credential for file:// or for
    a local path -- a secret for a storage account that does not exist turns a
    clear 'no credential' error into a confusing 'wrong credential' one."""
    con = io.duckdb_connect(("file:///tmp/x", "data/gold/y"))
    assert con.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0] == 0


def test_duckdb_connect_attaches_one_secret_per_azure_account():
    """Two containers on one account share a secret; two accounts need two."""
    one = io.duckdb_connect(("abfss://c1@acct.dfs.core.windows.net/a",
                             "abfss://c2@acct.dfs.core.windows.net/b"))
    assert one.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0] == 1

    two = io.duckdb_connect(("abfss://c@acctA.dfs.core.windows.net/a",
                             "abfss://c@acctB.dfs.core.windows.net/b"))
    names = two.execute("SELECT secret_string FROM duckdb_secrets()").fetchall()
    assert len(names) == 2
    accounts = {s[0].split("account_name=")[1].split(";")[0] for s in names}
    assert accounts == {"acctA", "acctB"}


def test_the_secret_uses_the_credential_chain_not_a_connection_string():
    """A connection string would mean an account key in an env var or a file.
    The chain resolves `az login` locally and managed identity in the cloud,
    and never materialises a secret anywhere we could leak it."""
    con = io.duckdb_connect("abfss://c@acct.dfs.core.windows.net/x")
    s = con.execute("SELECT secret_string FROM duckdb_secrets()").fetchone()[0]
    assert "provider=credential_chain" in s
    assert "managed_identity" in s
    assert "account_key" not in s
    assert "connection_string" not in s


def _synthetic_corpus(root: Path) -> tuple[Path, Path]:
    """A miniature AMLworld: a transaction CSV and a matching patterns file.

    Generated rather than committed because reconcile joins pattern rows to
    transaction rows on CONTENT (event_time, both ids, rounded amount, format).
    A hand-written fixture drifts out of alignment silently and reconciles to
    zero rings, which would make this test pass while proving nothing.
    """
    rng = __import__("random").Random(7)
    hdr = ("Timestamp,From Bank,Account,To Bank,Account,Amount Received,"
           "Receiving Currency,Amount Paid,Payment Currency,Payment Format,"
           "Is Laundering")
    rows, ring_rows = [], []

    def row(day, minute, sa, ra, amt, laund):
        return (f"2022/09/{day:02d} {minute // 60:02d}:{minute % 60:02d},"
                f"010,{sa},011,{ra},{amt:.2f},US Dollar,{amt:.2f},US Dollar,ACH,{laund}")

    for day in range(1, 15):                       # background traffic
        for i in range(60):
            rows.append(row(day, rng.randrange(0, 1440), f"BG{i % 25:04d}",
                            f"BG{(i * 7 + day) % 25:04d}", rng.uniform(10, 9000), 0))

    # Six FAN-OUT rings, spread across the timeline so the temporal split has
    # positives on both sides of any cut.
    for r in range(6):
        hub = f"HUB{r:03d}"
        for k in range(6):
            day = 2 + r * 2
            line = row(day, 100 + k * 30, hub, f"MULE{r:02d}{k}", 1000.0 + k, 1)
            rows.append(line)
            ring_rows.append((r, line))

    csv = root / "trans.csv"
    csv.write_text(hdr + "\n" + "\n".join(rows) + "\n")

    blocks = []
    for r in range(6):
        body = "\n".join(ln for rr, ln in ring_rows if rr == r)
        blocks.append(f"BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 6-degree Fan-Out\n"
                      f"{body}\nEND LAUNDERING ATTEMPT - FAN-OUT")
    pat = root / "patterns.txt"
    pat.write_text("\n".join(blocks) + "\n")
    return csv, pat


def test_full_pipeline_through_uris_matches_the_local_run(tmp_path):
    """The end-to-end statement, and the one the cloud run depends on.

    ingest -> parse -> reconcile -> splits -> features, with EVERY path a URI,
    must produce a feature table identical to the local-path run. If any stage
    still assumes a local filesystem, this is where it shows up -- for free,
    in under a second, instead of at minute forty of a paid run.
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    csv, pat_src = _synthetic_corpus(src_dir)

    results = {}
    for mode in ("local", "uri"):
        base = tmp_path / mode
        base.mkdir()
        pre = "" if mode == "local" else "file://"

        def d(*p, _pre=pre, _base=base):
            return _pre + str(_base.joinpath(*p))

        normalize(pre + str(csv), d("bronze"), hash_input=False)
        parse(pre + str(pat_src), d("patterns"))
        reconcile(d("bronze"), d("patterns"), d("labeled"))
        build_splits(d("patterns"), d("labeled"), "2022-09-09",
                     d("splits"), min_test_positives=1)
        build_features(d("labeled", "txns_labeled"), d("features"))

        results[mode] = duckdb.connect().execute(
            f"SELECT count(*), sum(txn_id), round(sum(log_amount_paid), 6) "
            f"FROM read_parquet('{d('features')}/**/*.parquet')").fetchone()

    assert results["local"][0] > 0, "pipeline produced no rows -- test proves nothing"
    assert results["local"] == results["uri"]


def test_the_synthetic_corpus_actually_reconciles(tmp_path):
    """Guard the guard. If the generated patterns did not match the generated
    transactions, reconcile would label zero rings, splits would have nothing
    to keep whole, and the test above would compare two empty pipelines."""
    src = tmp_path / "src"
    src.mkdir()
    csv, pat = _synthetic_corpus(src)
    normalize(str(csv), str(tmp_path / "bronze"), hash_input=False)
    parse(str(pat), str(tmp_path / "patterns"))
    m = reconcile(str(tmp_path / "bronze"), str(tmp_path / "patterns"),
                  str(tmp_path / "labeled"))
    assert m["flagged_with_ring"] == 36, m
    assert m["ring_txns_not_found_in_trans"] == 0, m
    assert m["typology_coverage_pct"] == 100.0, m


def test_no_module_reaches_the_filesystem_behind_io():
    """A static backstop for the dynamic tests above.

    io.py exists so one change swaps local for blob. A single `open()` or
    `os.makedirs` anywhere else silently reintroduces the local assumption for
    one stage, and that stage is the one that fails in the cloud. manifest.py
    is exempt: it hashes MODULE SOURCE, which is always local inside the
    container, and doing that through io would be wrong.
    """
    import aml

    # Word-boundary matched, not substring matched. A plain `"open(" in code`
    # also fires on `_open(`, `reopen(` and `fs.open(` -- it flagged a DuckDB
    # connection helper named `_open` and said the module reached the
    # filesystem, which it did not. A gate that cries wolf gets switched off.
    banned = [re.compile(p) for p in (
        r"(?<![\w.])os\.(makedirs|mkdir|listdir|walk|remove|rename)\(",
        r"(?<![\w.])shutil\.",
        r"(?<![\w.])open\(",
    )]
    offenders = []
    for path in Path(aml.__file__).parent.rglob("*.py"):
        if path.name in {"io.py", "manifest.py"}:
            continue
        code = "\n".join(ln.split("#", 1)[0] for ln in path.read_text().splitlines())
        for b in banned:
            if b.search(code):
                offenders.append(f"{path.name}: {b.pattern}")
    assert not offenders, (
        f"{offenders} touch the filesystem directly instead of going through "
        f"aml.io. Each one works locally and fails on blob storage."
    )
