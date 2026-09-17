"""Retry classification.

The asymmetry being tested: misfiling a bug as transient costs three runs of a
six-hour job; misfiling a hiccup as correctness costs one manual re-run. So the
tests below pin the safe direction, including for exceptions nobody anticipated.
"""
import pytest

from aml import exits
from aml.drift.resample import DriftGenerationError
from aml.io import FingerprintUnavailable, StorageDependencyMissing
from aml.leakproof.sweep import LeakNotDetectedError
from aml.patterns.parse import PatternParseError
from aml.schema import SchemaContractError
from aml.splits.ring_aware import LeakageError


class FakeAzureError(Exception):
    """Stands in for azure.core exceptions, which are an optional dependency.

    Classification is by class name precisely so this module stays importable
    without azure-core installed -- and so this test needs no cloud packages.
    """

    def __init__(self, msg="", status_code=None):
        super().__init__(msg)
        if status_code is not None:
            self.status_code = status_code


def _named(name, base=Exception, **attrs):
    return type(name, (base,), {})(**attrs) if attrs else type(name, (base,), {})()


# ---------------------------------------------------------------------------
# Correctness -- must never be retried
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    LeakageError("ring 42 straddles the cut"),
    SchemaContractError("header contract violation"),
    PatternParseError("nested BEGIN at line 700"),
    LeakNotDetectedError("positive control failed"),
    DriftGenerationError("source pool exhausted"),
    FingerprintUnavailable("no ETag"),
    StorageDependencyMissing("install [azure]"),
])
def test_our_own_exceptions_are_correctness_failures(exc):
    assert exits.classify(exc) == exits.EXIT_CORRECTNESS


def test_a_failed_assertion_is_a_correctness_failure():
    assert exits.classify(AssertionError("split invariant violated")) \
        == exits.EXIT_CORRECTNESS


def test_an_unrecognised_exception_is_not_retried():
    """The default, and the whole point of the module.

    Retrying an unknown failure on a 182M-row stage bills for three attempts
    and can make a real defect look like bad luck.
    """
    assert exits.classify(KeyError("event_date")) == exits.EXIT_CORRECTNESS
    assert exits.classify(ValueError("could not convert")) == exits.EXIT_CORRECTNESS
    assert exits.classify(MemoryError()) == exits.EXIT_CORRECTNESS


def test_missing_and_forbidden_files_are_not_transient():
    """Both subclass OSError, which is why bare OSError is not on the
    transient list. Neither fixes itself on a second attempt."""
    assert exits.classify(FileNotFoundError("no such blob")) == exits.EXIT_CORRECTNESS
    assert exits.classify(PermissionError("403")) == exits.EXIT_CORRECTNESS


def test_auth_failures_are_not_transient():
    """Arrive from the same SDK as the retryable errors, but repeat identically
    until somebody fixes a role assignment."""
    assert exits.classify(_named("ClientAuthenticationError")) == exits.EXIT_CORRECTNESS
    assert exits.classify(_named("CredentialUnavailableError")) == exits.EXIT_CORRECTNESS


# ---------------------------------------------------------------------------
# Transient -- retry is correct
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    ConnectionError("reset by peer"),
    ConnectionResetError(),
    TimeoutError("read timed out"),
])
def test_infrastructure_builtins_are_transient(exc):
    assert exits.classify(exc) == exits.EXIT_TRANSIENT


@pytest.mark.parametrize("name", [
    "ServiceRequestError", "ServiceResponseError", "ClientConnectorError",
    "ProtocolError", "ReadTimeoutError",
])
def test_cloud_sdk_connection_errors_are_transient(name):
    assert exits.classify(_named(name)) == exits.EXIT_TRANSIENT


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_throttling_and_transient_5xx_are_retryable(status):
    assert exits.classify(FakeAzureError("busy", status_code=status)) \
        == exits.EXIT_TRANSIENT


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 501])
def test_client_errors_and_permanent_5xx_are_not_retryable(status):
    assert exits.classify(FakeAzureError("nope", status_code=status)) \
        == exits.EXIT_CORRECTNESS


# ---------------------------------------------------------------------------
# Wrapped exceptions
# ---------------------------------------------------------------------------

def test_a_transient_cause_is_found_through_a_wrapper():
    """DuckDB surfaces a throttled blob read as its own IOException with the
    storage error as __cause__, so only inspecting the outermost exception
    would misfile a genuine hiccup."""
    try:
        try:
            raise ConnectionError("storage throttled")
        except ConnectionError as inner:
            raise RuntimeError("duckdb: IO Error") from inner
    except RuntimeError as e:
        assert exits.classify(e) == exits.EXIT_TRANSIENT


def test_correctness_wins_over_a_transient_in_the_same_chain():
    """A leakage assertion that happens to wrap a network error is still a
    leakage finding. The orchestrator must not retry its way past it."""
    try:
        try:
            raise ConnectionError("blip")
        except ConnectionError as inner:
            raise LeakageError("ring 42 straddles the cut") from inner
    except LeakageError as e:
        assert exits.classify(e) == exits.EXIT_CORRECTNESS


def test_classification_terminates_on_a_self_referential_chain():
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert exits.classify(a) == exits.EXIT_CORRECTNESS


# ---------------------------------------------------------------------------
# The CLI contract
# ---------------------------------------------------------------------------

def test_labels():
    assert exits.label(0) == "ok"
    assert exits.label(1) == "transient"
    assert exits.label(2) == "correctness"


def test_cli_returns_2_for_a_correctness_failure(monkeypatch, capsys, tmp_path):
    """End to end through the real entrypoint: the traceback still prints, and
    the process exits 2 so the orchestrator does not retry."""
    from aml import cli

    def boom(*a, **kw):
        raise LeakageError("ring 42 straddles the cut")

    monkeypatch.setattr("aml.splits.ring_aware.build", boom)
    code = cli.main(["build-splits", "--patterns", str(tmp_path),
                     "--labeled", str(tmp_path), "--cut", "2022-09-10",
                     "--dest", str(tmp_path / "out")])

    assert code == exits.EXIT_CORRECTNESS
    out = capsys.readouterr()
    assert '"classification": "correctness"' in out.out
    assert '"retryable": false' in out.out
    assert "LeakageError" in out.err  # the traceback is not swallowed


def test_cli_returns_1_for_a_transient_failure(monkeypatch, capsys, tmp_path):
    from aml import cli

    def boom(*a, **kw):
        raise ConnectionError("storage throttled")

    monkeypatch.setattr("aml.patterns.parse.parse", boom)
    code = cli.main(["parse-patterns", "--src", str(tmp_path / "x.txt"),
                     "--dest", str(tmp_path / "out")])

    assert code == exits.EXIT_TRANSIENT
    assert '"retryable": true' in capsys.readouterr().out


def test_cli_returns_0_on_success(monkeypatch, tmp_path):
    from aml import cli

    monkeypatch.setattr("aml.patterns.parse.parse", lambda *a, **kw: {"rings": 370})
    assert cli.main(["parse-patterns", "--src", str(tmp_path / "x.txt"),
                     "--dest", str(tmp_path / "out")]) == exits.EXIT_OK


def test_help_still_exits_through_argparse():
    from aml import cli

    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0


# ---------------------------------------------------------------------------
# Regression: a never-transient cause hidden under a transient wrapper
# ---------------------------------------------------------------------------

def test_auth_failure_under_a_transient_wrapper_is_not_retried():
    """azure-core's real shape: ServiceRequestError wrapping an auth failure.

    The transient check used to run per-element in the same loop as the
    never-transient check, so whichever appeared FIRST in the chain decided the
    answer. A missing role assignment therefore came back 'transient' and the
    orchestrator retried a six-hour stage three times at full price.
    """
    class ClientAuthenticationError(Exception):
        pass

    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise ClientAuthenticationError("no managed identity on this node")
        except ClientAuthenticationError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_CORRECTNESS


def test_the_wrapper_alone_is_still_transient():
    """The fix must not turn every wrapped error into a correctness stop."""
    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise TimeoutError("read timed out")
        except TimeoutError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_TRANSIENT
