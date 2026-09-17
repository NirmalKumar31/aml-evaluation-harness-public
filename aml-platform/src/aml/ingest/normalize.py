"""
normalize_schema: raw IBM CSV -> day-partitioned Parquet with canonical names.

This is the first pipeline component. It does five things:
  1. refuses the file if the header is not exactly what we contracted for
  2. reads by POSITION, so the duplicate 'Account' column cannot bite us
  3. assigns txn_id -- the transaction's identity -- exactly once
  4. builds the real account key: (bank, account), not account alone
  5. writes Parquet partitioned by event_date

WHY txn_id IS ASSIGNED HERE AND NOWHERE ELSE
    It used to be derived downstream, in two places, as

        row_number() OVER (ORDER BY event_time, sender_id, receiver_id)

    with a comment in each saying the two expressions must stay identical. They
    were identical. It still broke, because that ordering key is not unique --
    658,850 rows of HI-Medium (2.1%) share one, in groups of up to four -- and
    DuckDB parallelises the sort. Three runs of the same query on the same data
    produced three different assignments, two of them at identical thread
    settings.

    The consequence was silent: features/build.py and leakproof/plant.py
    disagreed about which transaction a given txn_id meant, and prove.py joined
    them on it with validate="one_to_one", which checks cardinality only. Leak
    columns were attached to the wrong transactions and every validation passed.

    So identity is now assigned once, at ingest, and carried. Downstream
    components call schema.require_txn_id() and refuse to run without it,
    rather than helpfully regenerating it.

WHY row_number() OVER () AND NOT A SORT
    An empty OVER() numbers rows in scan order, which for a CSV is physical
    file order -- so txn_id is "this transaction was line N of the source
    file", which is stable, meaningful and reproducible. Crucially it needs no
    sort: normalize is the one stage whose throughput is FLAT from 5M to 32M
    rows (~4M rows/sec, I/O-bound), and a global sort over 182M rows would
    turn it into a blocking, memory-hungry stage.

    Verified on the full 5,078,345-row parallel scan: identical assignment at
    threads = 1, 2, 4 and 8, and matching the raw file's line order. The
    contiguity assertion below re-checks it on every run rather than trusting
    it, because the failure mode is silent.
"""
import sys

from aml import io, schema
from aml.manifest import Run, cached_or_none, sha256_file


def _select_sql(src: str) -> str:
    cols = ", ".join(f"'{n}': '{t}'" for n, t in schema.COLUMNS)
    return f"""
    SELECT
        row_number() OVER ()                     AS txn_id,
        *,
        sender_bank   || '_' || sender_account   AS sender_id,
        receiver_bank || '_' || receiver_account AS receiver_id,
        CAST(event_time AS DATE)                 AS event_date
    FROM read_csv(
        '{src}',
        header     = false,        -- we skip it deliberately
        skip       = 1,            -- ...and drop the line ourselves
        columns    = {{{cols}}},   -- positional: OUR names, not theirs
        timestampformat = '{schema.TIMESTAMP_FORMAT}'
    )
    """


def normalize(src: str, dest: str, manifest_dir: str | None = None, hash_input: bool = True,
              force: bool = False):
    src, dest = str(src), str(dest)
    # 1.1.0 adds txn_id at ingest. The bump is deliberate: it changes the run
    # key, so every cached downstream stage recomputes rather than silently
    # mixing old and new identity schemes.
    # hash_input is in the key because a --no-hash run records no
    # input_sha256; without it, that run satisfies the cache for a later
    # run that asked for the provenance hash, which then never appears.
    cfg = {"src": src, "dest": dest, "schema_version": "1.1.0",
           "hash_input": bool(hash_input)}
    mdir = manifest_dir or dest

    key, hit = cached_or_none("normalize_schema", cfg, [src], mdir,
                             modules=(sys.modules[__name__], schema), force=force)
    if hit is not None:
        return hit

    with Run("normalize_schema", cfg, mdir, key=key) as run:
        schema.validate_header(src)                      # step 1: fail loud
        if hash_input:
            run.record(input_sha256=sha256_file(src))

        con = io.duckdb_connect((src, dest))
        # row_number() OVER () follows scan order, so scan order must be file
        # order. This is DuckDB's default; setting it explicitly means a stray
        # global config or env var cannot silently turn identity into garbage.
        con.execute("SET preserve_insertion_order=true")
        io.ensure_dir(dest)
        con.execute(f"""
            COPY ({_select_sql(src)})
            TO '{dest}'
            (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
        """)

        stats = con.execute(f"""
            SELECT count(*)                                   AS rows,
                   sum(is_laundering)                         AS positives,
                   min(event_time)                            AS min_time,
                   max(event_time)                            AS max_time,
                   count(DISTINCT event_date)                 AS days,
                   count(DISTINCT sender_id)                  AS senders,
                   count(DISTINCT txn_id)                     AS distinct_txn_ids,
                   min(txn_id)                                AS min_txn_id,
                   max(txn_id)                                AS max_txn_id
            FROM read_parquet({io.parquet_arg(dest)})
        """).fetchone()

        rows, distinct_ids, min_id, max_id = int(stats[0]), int(stats[6]), stats[7], stats[8]

        # THE IDENTITY CONTRACT, checked every run rather than assumed.
        #
        # txn_id must be exactly 1..N with no gaps and no repeats. If it is not,
        # every downstream join by txn_id is unsound, and the failure would
        # otherwise be silent -- which is precisely how the previous scheme hid
        # for three phases. Cheap to check, catastrophic to skip.
        if not (distinct_ids == rows and min_id == 1 and max_id == rows):
            raise schema.SchemaContractError(
                f"txn_id is not a contiguous 1..N identity after ingest.\n"
                f"  rows={rows:,}  distinct txn_id={distinct_ids:,}  "
                f"min={min_id}  max={max_id}\n"
                f"Every downstream join is keyed on txn_id, so this must hold "
                f"exactly. Duplicates or gaps mean row numbering did not follow "
                f"scan order -- check that preserve_insertion_order is true."
            )

        run.record(
            rows=rows,
            positives=int(stats[1]),
            prevalence_pct=round(100 * stats[1] / stats[0], 4) if stats[0] else None,
            min_event_time=str(stats[2]),
            max_event_time=str(stats[3]),
            days=int(stats[4]),
            distinct_senders=int(stats[5]),
            txn_id_contiguous=True,
        )
        print(io.json_line({"event": "normalize_complete", **run.metrics}))
        return run.metrics
