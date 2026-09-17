"""A CycloneDX SBOM for the container environment, from the hashed lock.

H24. There was no SBOM, no checksum file and no way for a consumer to know what
is inside the published image without pulling and inspecting it.

Built from `requirements.linux-amd64.lock`, which is the file the image
installs with `--require-hashes` -- so the SBOM describes the bytes that run,
not a resolution performed at SBOM time. Those are different documents and only
the first one is worth having.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="requirements.linux-amd64.lock", type=Path)
    ap.add_argument("--out", default="results_archive/derived/sbom.cdx.json",
                    type=Path)
    a = ap.parse_args(argv)

    components, name, version = [], None, None
    for raw in a.lock.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.rstrip(" \\").split("==", 1)
        elif line.startswith("--hash=sha256:") and name:
            digest = line.split("sha256:", 1)[1].strip()
            components.append({
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{re.sub(r'[-_.]+', '-', name).lower()}@{version}",
                "hashes": [{"alg": "SHA-256", "content": digest}],
            })
            name = version = None

    if not components:
        raise SystemExit(f"no pinned components parsed from {a.lock}")

    from aml.manifest import generator_provenance
    prov = generator_provenance(__file__, inputs=[a.lock],
                                parameters={"lock": str(a.lock)})
    sbom = {
        **prov,
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "component": {"type": "application",
                          "name": "aml-evaluation-harness",
                          "version": prov["code_git_sha"]},
            "properties": [
                {"name": "source", "value": str(a.lock)},
                {"name": "platform", "value": "linux/amd64, CPython 3.12"},
                {"name": "note",
                 "value": "Generated from the hashed lock the image installs "
                          "with --require-hashes, so it describes the bytes "
                          "that run rather than a fresh resolution."},
            ],
        },
        "components": components,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(sbom, indent=1))
    print(f"{a.out}: {len(components)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
