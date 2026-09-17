"""Which failures may be retried, and which must never be.

The problem
-----------
The orchestrator (Azure ML pipelines) decides whether to retry a failed stage
from its exit code. Today every failure exits non-zero the same way, so the
orchestrator cannot tell these two apart:

    the storage account throttled us for 30 seconds
        -> retrying is correct, and cheap

    build-splits found a laundering ring straddling the train/test cut
        -> retrying is WRONG

The second one matters more than it looks. A pipeline configured to retry on
any failure will re-run a leakage assertion, and the project's whole claim is
that its results are not contaminated. "It passed on attempt 3" is not a
result; it is a broken gate. So correctness failures get their own exit code
and the orchestrator is configured never to retry it.

    0   success
    1   TRANSIENT   infrastructure hiccup. Retry is safe and appropriate.
    2   CORRECTNESS a claim about the data or the code was violated. A human
                    must look. Retrying cannot help and may hide the problem.

Why the default is 2, not 1
---------------------------
An unrecognised exception is classified CORRECTNESS. That is the deliberate
choice, and it is the opposite of what "be resilient" instincts suggest.

Consider the cost of each mistake:

    unknown bug misfiled as TRANSIENT
        -> the orchestrator retries a six-hour, 182-million-row feature build
           two more times, bills for all three, and fails anyway

    transient fault misfiled as CORRECTNESS
        -> somebody re-runs one command by hand

The second is an inconvenience. The first is money plus the chance that a real
defect looks like bad luck. So: retry only what we have positively identified
as retryable.
"""
from __future__ import annotations

EXIT_OK = 0
EXIT_TRANSIENT = 1
EXIT_CORRECTNESS = 2

# Our own exceptions. Every one of these means "the data or the code is not
# what we asserted it is", which no amount of retrying will change.
#
# Imported lazily inside _correctness_types() so that classifying an exception
# never drags in duckdb, sklearn or pandas.
_CORRECTNESS_NAMES = (
    ("aml.schema", "SchemaContractError"),
    ("aml.patterns.parse", "PatternParseError"),
    ("aml.splits.ring_aware", "LeakageError"),
    ("aml.leakproof.sweep", "LeakNotDetectedError"),
    ("aml.drift.resample", "DriftGenerationError"),
    # Cannot establish content identity for an input. Continuing would mean
    # trusting the stage cache without grounds -- see aml/io.py.
    ("aml.io", "FingerprintUnavailable"),
    # A URI was passed without the cloud extra installed. A configuration
    # error: the package will not appear on retry.
    ("aml.io", "StorageDependencyMissing"),
)

# Builtins that genuinely indicate infrastructure rather than logic.
#
# Note what is NOT here: bare OSError. It is the parent of FileNotFoundError
# and PermissionError, both of which are configuration or wiring problems that
# recur identically on retry.
_TRANSIENT_BUILTINS: tuple[type[BaseException], ...] = (
    ConnectionError,      # covers ConnectionReset, BrokenPipe, ConnectionAborted
    TimeoutError,         # also socket.timeout since 3.10
    InterruptedError,
    BlockingIOError,
)

# Cloud SDK exceptions, matched by CLASS NAME rather than by import.
# azure-core is an optional dependency, and this module must be importable and
# correct without it.
_TRANSIENT_CLASS_NAMES = frozenset({
    "ServiceRequestError",        # azure.core: could not reach the service
    "ServiceResponseError",       # azure.core: no/partial response
    "ServiceRequestTimeoutError",
    "ServiceResponseTimeoutError",
    "IncompleteReadError",
    "ServerTimeoutError",         # aiohttp
    "ClientConnectorError",       # aiohttp
    "ClientOSError",
    "ClientPayloadError",
    "ProtocolError",              # urllib3
    "ReadTimeoutError",
    "ConnectTimeoutError",
    "NewConnectionError",
    "OperationTimedOut",
})

# Explicitly NOT transient, even though they arrive from the same SDKs.
# Authentication and authorisation failures repeat identically until a human
# fixes a role assignment, and a retry loop on them just burns the clock.
_NEVER_TRANSIENT_CLASS_NAMES = frozenset({
    "ClientAuthenticationError",
    "CredentialUnavailableError",
    "ResourceNotFoundError",
    "ResourceExistsError",
})

# HTTP statuses worth another attempt: throttling and the transient 5xx family.
# 500 is included because Azure Storage does return it for genuinely temporary
# conditions. 501 and 505 are excluded: they are permanent.
_RETRYABLE_HTTP = frozenset({408, 429, 500, 502, 503, 504})


def _correctness_types() -> tuple[type[BaseException], ...]:
    import importlib

    out = []
    for module_name, cls_name in _CORRECTNESS_NAMES:
        try:
            out.append(getattr(importlib.import_module(module_name), cls_name))
        except (ImportError, AttributeError):
            # A component that is not installed cannot have raised. Skipping is
            # correct; failing here would turn a classification into a crash.
            continue
    return tuple(out)


def _http_status(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _chain(exc: BaseException, limit: int = 20):
    """The exception plus its __cause__ / __context__ ancestry.

    Needed because the interesting exception is often wrapped. A DuckDB call
    that fails on a throttled blob read surfaces as a duckdb.IOException with
    the azure error as its __context__, and classifying only the outermost
    exception would miss it.
    """
    seen, out, cur = set(), [], exc
    while cur is not None and id(cur) not in seen and len(out) < limit:
        seen.add(id(cur))
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def classify(exc: BaseException) -> int:
    """EXIT_TRANSIENT or EXIT_CORRECTNESS for a raised exception.

    Correctness is checked across the whole chain first and wins outright. A
    leakage assertion that happens to wrap a network error is still a
    correctness stop -- the assertion is the finding, and the orchestrator must
    not retry its way past it.
    """
    chain = _chain(exc)
    correctness = _correctness_types()

    if any(isinstance(e, correctness) for e in chain):
        return EXIT_CORRECTNESS
    # An assert that fired is a violated invariant, never a hiccup.
    if any(isinstance(e, AssertionError) for e in chain):
        return EXIT_CORRECTNESS

    # CHAIN-WIDE, and it has to be. This used to sit inside the loop below,
    # where position decided the answer: azure-core raises ServiceRequestError
    # (transient) wrapping ClientAuthenticationError (never transient), so the
    # outer element matched first and the whole thing was classified retryable.
    # The orchestrator would then retry a missing role assignment three times --
    # the exact outcome _NEVER_TRANSIENT_CLASS_NAMES exists to prevent, and on
    # a six-hour stage it is retried at full price.
    if any(type(e).__name__ in _NEVER_TRANSIENT_CLASS_NAMES for e in chain):
        return EXIT_CORRECTNESS

    for e in chain:
        name = type(e).__name__
        if isinstance(e, _TRANSIENT_BUILTINS) or name in _TRANSIENT_CLASS_NAMES:
            return EXIT_TRANSIENT
        status = _http_status(e)
        if status in _RETRYABLE_HTTP:
            return EXIT_TRANSIENT

    # Unrecognised. Do not retry -- see the module docstring.
    return EXIT_CORRECTNESS


def label(code: int) -> str:
    return {EXIT_OK: "ok", EXIT_TRANSIENT: "transient",
            EXIT_CORRECTNESS: "correctness"}.get(code, "unknown")
