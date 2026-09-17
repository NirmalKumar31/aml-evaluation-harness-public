#!/usr/bin/env python
"""Measure the dataset facts the documents cite, and write them as an artifact.

WHY

    LIMITATIONS.md states laundering rate by payment format -- the evidence for
    "this benchmark is near-saturated". Those numbers were measured once, by
    hand, in a shell, and pasted in. `make_tables.py --check` correctly flagged
    every one of them as supported by no artifact.

    The wrong fix is to mark them exempt. A claim about the data is exactly the
    kind of number that must be reproducible, and it is the claim the whole
    README now leads with. So: measure it in code, write the artifact, let the
    check verify the document against it.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import duckdb


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/HI-Medium_Trans.csv")
    ap.add_argument("--dest", default="results_archive/derived/dataset_facts.json")
    a = ap.parse_args(argv)

    # FAIL FAST. The scope guard also runs when the artifact is
    # written; by then this script has done all of its work.
    from aml.manifest import require_clean_scope
    require_clean_scope()

    if not Path(a.src).exists():
        print(f"{a.src} not found; run `make get-data`", file=sys.stderr)
        return 2

    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT "Payment Format" AS fmt, count(*) AS n,
               sum("Is Laundering") AS pos
        FROM read_csv_auto('{a.src}') GROUP BY 1 ORDER BY 3 DESC
    """).fetchall()

    total = sum(r[1] for r in rows)
    tot_pos = sum(r[2] for r in rows)
    out = {
        "source": a.src,
        "rows": total,
        "positives": tot_pos,
        "prevalence_pct": round(100 * tot_pos / total, 4),
        "by_payment_format": [
            {"format": f, "rows": n, "positives": p,
             "laundering_rate_pct": round(100 * p / n, 4),
             "share_of_rows_pct": round(100 * n / total, 2),
             "share_of_positives_pct": round(100 * p / tot_pos, 2)}
            for f, n, p in rows
        ],
    }
    zero = [r["format"] for r in out["by_payment_format"] if r["positives"] == 0]
    out["formats_with_zero_positives"] = zero
    out["pct_rows_in_zero_positive_formats"] = round(
        100 * sum(r["rows"] for r in out["by_payment_format"]
                  if r["positives"] == 0) / total, 2)

    # PROVENANCE, because this artifact supports published numbers.
    #
    # It carried none, so `make_tables.py --check` could confirm that
    # LIMITATIONS' payment-format figures appear in an artifact and could NOT
    # confirm which commit produced that artifact. A derived artifact that
    # supports a release figure needs the same provenance as a stage manifest,
    # and it is cheap to add.
    from aml.manifest import generator_provenance
    out.update(generator_provenance(__file__, inputs=[a.src],
                                    parameters={"src": str(a.src)}))
    out["written_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out["source_csv"] = str(a.src)

    d = Path(a.dest)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps(out, indent=1))
    print(f"wrote {d}")
    for r in out["by_payment_format"]:
        print(f"  {r['format']:14s} {r['rows']:>12,} rows  {r['positives']:>7,} pos  "
              f"{r['laundering_rate_pct']:>8.4f}%")
    print(f"  zero-positive formats: {zero} = "
          f"{out['pct_rows_in_zero_positive_formats']}% of rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
