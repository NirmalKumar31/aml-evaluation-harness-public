# The pipeline image. Used by Azure ML compute; NOT by Synapse Spark, which
# runs Microsoft's managed runtime and takes our feature code as a wheel.
#
# Base image pinned to a patch version, not `3.12-slim`, because a floating tag
# means the image that runs the 182M-row job is not the image the tests passed
# on. Pinning by digest would be stricter still; the trade is that every security
# update becomes a manual edit. Patch-level is the compromise, and the lock file
# below is what actually fixes the Python environment.
# Pinned by DIGEST, not by tag. A patch tag is still mutable: the image the
# tests passed on and the image that runs the 180M-row job can differ while
# both call themselves 3.12.3-slim-bookworm. The trade is that a security
# update is now a deliberate edit -- which is the point, and Dependabot
# raises it.
FROM python:3.12.3-slim-bookworm@sha256:afc139a0a640942491ec481ad8dda10f2c5b753f5c969393b12480155fe15a63

# - build-essential: some wheels still compile on arm64/musl edge cases
# - ca-certificates: TLS to ADLS
# - git: manifest.py records the commit SHA in every run's provenance. Without
#   git the manifest silently records "unknown", which is exactly the sort of
#   quiet degradation this project exists to avoid.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Provenance, injected because the image cannot discover it: .dockerignore
# excludes .git (correctly -- it is not needed at runtime), so without this
# every manifest the container writes records code_git_sha "unknown". Seven
# archived manifests are in exactly that state, including all three current
# HI-Large fits.
ARG AML_GIT_SHA=unknown
ENV AML_GIT_SHA=${AML_GIT_SHA}

# Dependencies first, from the LOCK -- so a code change does not re-resolve the
# environment, and so the container gets the exact versions the test suite ran
# against rather than whatever pyproject's ranges permit today.
COPY requirements.linux-amd64.lock ./
# --require-hashes, for real this time.
#
# An earlier version of this line carried `--require-hashes=false`, which is a
# usage error rather than a no-op -- --require-hashes is a FLAG. It had never
# been executed, because Docker was not installed on the development machine,
# and the first real build failed here. It was then removed, because
# requirements.lock came from `pip list --format=freeze` and carries exact
# versions but no hashes, so there was nothing to check against.
#
# requirements.linux-amd64.lock is resolved for THIS platform and carries a
# sha256 per wheel, so pip now refuses to install anything whose bytes do not
# match. "The versions I tested" and "the bytes that ran" are different claims,
# and this is the one that makes the second one checkable.
RUN pip install --no-cache-dir --require-hashes -r requirements.linux-amd64.lock

# Pre-install DuckDB's azure extension AT BUILD TIME.
#
# Without this, every container fetches it from the extension repository on
# first use. On a 182M-row job spread over many task containers that is a
# per-container network round trip and an outbound dependency in the middle of
# the most expensive stage -- a transient failure there costs the whole run.
RUN python -c "import duckdb; c=duckdb.connect(); c.execute('INSTALL azure'); c.execute('LOAD azure'); print('duckdb azure extension baked in')"

# Source last: the layers above are the slow ones and should stay cached.
#
# tests/ is included deliberately. Being able to run the full suite INSIDE the
# built image is how we show the cloud environment behaves like the local one --
# a stronger statement than "the image starts", and directly what Gate 4 needs.
# THE NOTICES TRAVEL WITH THE THING THEY DESCRIBE.
#
# The image COPYs `results_archive/`, which contains nine replay bundles --
# 526,355 rows of derived row-level records whose redistribution status this
# project explicitly declines to settle. It did not copy `DATA_LICENSE.md` or
# `LICENSE`. A published OCI image would therefore carry the disputed data and
# not the document that says where it came from, what terms attach, or that the
# question is open. Whatever the legal answer turns out to be, shipping the
# rows without the notice cannot be part of it.
COPY LICENSE DATA_LICENSE.md ./
COPY pyproject.toml README.md ./
# The other three lock files, so the image carries a record of its own
# environment and the lock-consistency tests can run INSIDE it. Copied in this
# layer rather than beside requirements.linux-amd64.lock above, so that editing
# a dev pin does not invalidate the expensive dependency layer.
#
# The suite running in the image caught their absence on the first build after
# those tests were added, which is exactly what running it in here is for.
COPY requirements.lock requirements-dev.lock ./
COPY requirements-dev.linux-amd64.lock ./
COPY src ./src
COPY tests ./tests
# scripts/ too. The replay-bundle generator and the publication checker are run
# against cloud data, in this image, on a machine with no checkout -- and the
# first attempt to do that failed with "can't open file
# /app/scripts/make_replay_bundle.py". An image that can run the pipeline but
# not the tooling that AUDITS the pipeline is half an image.
COPY scripts ./scripts
# results_archive/ too -- 13 MB, and it is what turns "the suite runs in the
# image" into "the image validates the released archive".
#
# Without it the archive-dependent tests found no artifacts and skipped: the
# image job reported 283 passed / 31 skipped against the host's 297 / 17, and
# the 14 missing were exactly the replay recomputations, the provenance checks
# and the dataset-pin contract -- the reproducibility evidence. A container
# that can run the pipeline but cannot check the pipeline's published outputs
# proves the environment starts, not that it agrees.
#
# paper/archive/ stays excluded by .dockerignore; this is the current archive.
COPY results_archive ./results_archive
# docs/ too, ~200 KB. Three release-critical tests read a document and a script
# and check they agree -- the runbook's commands against the scripts' required
# inputs, and the cost table against cost.json. Shipping the scripts without
# the documents they are checked against means the image can run those tests
# and cannot answer them.
#
# The remaining image skips are the repository-ROOT documents (README,
# HANDOFF, CONTRIBUTING, CHANGELOG), the Dockerfile itself, and the tests that
# need built gold outputs. They are outside this build context by construction.
# The number is deliberately NOT stated here -- this comment said "four" and
# the checklist said "five" while the runs showed six, because a count written
# in prose is wrong as soon as a test is added. The image job asserts the
# permitted REASONS instead; see docs/RELEASE_CHECKLIST.md section 3a.
COPY docs ./docs
RUN pip install --no-deps -e .

# Run as non-root. Azure ML does not require it, but a container that only ever
# reads inputs and writes to a mounted output path has no need for root, and the
# DuckDB extension cache must be readable by whoever runs.
# APPLICATION CODE STAYS ROOT-OWNED.
#
# This used to `chown -R aml:aml /app`, which makes every module writable by
# the account the container runs as. For a container whose only job is to read
# inputs and write to a mounted output path, writable application code buys
# nothing and means a process that gets execution can also modify what runs
# next. Only the home directory and the DuckDB extension cache need to be
# owned by the runtime user.
#
# NOT A FULL BUILDER-STAGE WHEEL. The audit is right that the ideal is a wheel
# built in a builder stage and installed non-editably into a slim runtime
# image, with tests in a separate image. That trades away the thing this image
# is FOR -- running the whole suite inside the artifact that ran the results,
# which is the evidence the cloud environment matches the local one. Recorded
# as a known gap rather than half-done.
RUN useradd --create-home --uid 10001 aml \
 && cp -r /root/.duckdb /home/aml/.duckdb \
 && chown -R aml:aml /home/aml \
 && chmod -R a-w /app/src /app/scripts /app/results_archive /app/docs
USER aml

# Fail fast and visibly if the image is broken, rather than at stage 6 of a
# pipeline run.
RUN aml --help > /dev/null && python -c "\
import duckdb, aml.io, aml.exits;\
from aml.models import config;\
c = duckdb.connect(); c.execute('LOAD azure');\
assert aml.io.is_uri('abfss://c@a.dfs.core.windows.net/x');\
print('image self-check OK; production GBDT =', config.GBDT)"

ENTRYPOINT ["aml"]
CMD ["--help"]
