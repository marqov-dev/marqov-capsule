"""CLI surface for the one-sided UCB count-equivalence test (#15).

The estimator itself is covered in test_verifier.py; these tests cover the
command wiring: how counts are read, which verdict maps to which exit code,
and that a base install without numpy/scipy fails cleanly.
"""
import json

import pytest
from click.testing import CliRunner

from marqov_capsule.cli.main import cli


@pytest.fixture
def statistical_dependencies():
    """Only the verdict tests need numpy/scipy. The input-shape and error
    tests must still run on a base install — that job exists to catch exactly
    the regressions they cover (#116)."""
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")


# Exit codes are part of the contract: INCONCLUSIVE is deliberately NOT 1,
# because this estimator cannot assert that two distributions differ. A
# caller that treats "not enough shots" as "did not reproduce" is the exact
# misreading #15 exists to prevent.
EXIT_VERIFIED = 0
EXIT_ERROR = 1
EXIT_INCONCLUSIVE = 3


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return str(path)


def _balanced(shots):
    """A Bell-like two-outcome distribution with `shots` total samples."""
    half = shots // 2
    return {"00": half, "11": shots - half}


def _run(*args):
    return CliRunner().invoke(cli, ["compare", *args])


# --- input shapes ---------------------------------------------------------

@pytest.mark.usefixtures("statistical_dependencies")
def test_reads_bare_counts_mapping(tmp_path):
    ref = _write(tmp_path / "ref.json", _balanced(50_000))
    new = _write(tmp_path / "new.json", _balanced(50_000))
    result = _run(ref, new)
    assert result.exit_code == EXIT_VERIFIED, result.output


@pytest.mark.usefixtures("statistical_dependencies")
def test_reads_wrapped_counts_key(tmp_path):
    ref = _write(tmp_path / "ref.json", {"counts": _balanced(50_000), "shots": 50_000})
    new = _write(tmp_path / "new.json", {"counts": _balanced(50_000), "shots": 50_000})
    result = _run(ref, new)
    assert result.exit_code == EXIT_VERIFIED, result.output


@pytest.mark.usefixtures("statistical_dependencies")
def test_counts_key_override(tmp_path):
    ref = _write(tmp_path / "ref.json", {"histogram": _balanced(50_000)})
    new = _write(tmp_path / "new.json", {"histogram": _balanced(50_000)})
    result = _run(ref, new, "--counts-key", "histogram")
    assert result.exit_code == EXIT_VERIFIED, result.output


def test_missing_counts_key_errors_cleanly(tmp_path):
    ref = _write(tmp_path / "ref.json", {"histogram": _balanced(1000)})
    new = _write(tmp_path / "new.json", {"histogram": _balanced(1000)})
    result = _run(ref, new, "--counts-key", "nope")
    assert result.exit_code == EXIT_ERROR
    assert "nope" in result.output
    assert "Traceback" not in result.output


# --- verdicts -------------------------------------------------------------

@pytest.mark.usefixtures("statistical_dependencies")
def test_high_shot_equivalence_is_verified(tmp_path):
    ref = _write(tmp_path / "ref.json", _balanced(50_000))
    new = _write(tmp_path / "new.json", {"00": 24_900, "11": 25_100})
    result = _run(ref, new)
    assert result.exit_code == EXIT_VERIFIED, result.output
    assert "VERIFIED" in result.output


@pytest.mark.usefixtures("statistical_dependencies")
def test_low_shots_are_inconclusive_not_rejected(tmp_path):
    # 1024 shots cannot clear any usable epsilon: the McDiarmid slack alone
    # is ~0.054. This must read as INCONCLUSIVE, never as a failed check.
    ref = _write(tmp_path / "ref.json", _balanced(1024))
    new = _write(tmp_path / "new.json", _balanced(1024))
    result = _run(ref, new)
    assert result.exit_code == EXIT_INCONCLUSIVE, result.output
    assert "INCONCLUSIVE" in result.output
    assert "REJECTED" not in result.output


@pytest.mark.usefixtures("statistical_dependencies")
def test_identical_distributions_are_never_rejected(tmp_path):
    # The #15 regression: the retired bootstrap rejected byte-identical
    # inputs from roughly four qubits upward.
    counts = {format(i, "06b"): 1000 for i in range(64)}
    ref = _write(tmp_path / "ref.json", counts)
    new = _write(tmp_path / "new.json", dict(counts))
    result = _run(ref, new)
    assert result.exit_code in (EXIT_VERIFIED, EXIT_INCONCLUSIVE), result.output
    assert "REJECTED" not in result.output


def test_below_min_shots_is_inconclusive_and_says_so(tmp_path):
    ref = _write(tmp_path / "ref.json", _balanced(10))
    new = _write(tmp_path / "new.json", _balanced(10))
    result = _run(ref, new, "--min-shots", "100")
    assert result.exit_code == EXIT_INCONCLUSIVE, result.output
    assert "min_shots" in result.output or "shots" in result.output


@pytest.mark.usefixtures("statistical_dependencies")
def test_inconclusive_explains_that_more_shots_may_help(tmp_path):
    # #85: a bare INCONCLUSIVE leaves users unable to tell "not reproducible"
    # from "you did not take enough shots".
    ref = _write(tmp_path / "ref.json", _balanced(1024))
    new = _write(tmp_path / "new.json", _balanced(1024))
    result = _run(ref, new)
    assert "shots" in result.output.lower()


def test_zero_shots_is_inconclusive(tmp_path):
    ref = _write(tmp_path / "ref.json", {})
    new = _write(tmp_path / "new.json", _balanced(1000))
    result = _run(ref, new)
    assert result.exit_code == EXIT_INCONCLUSIVE, result.output


# --- policy flags ---------------------------------------------------------

@pytest.mark.usefixtures("statistical_dependencies")
def test_epsilon_flag_changes_the_verdict(tmp_path):
    # For identical inputs the bound is pure slack, ~sqrt(ln(1/alpha)/2 * 2/n).
    # At 5k shots that is ~0.0245, which straddles the two epsilons: too wide
    # for 0.02, comfortably inside 0.05.
    ref = _write(tmp_path / "ref.json", _balanced(5_000))
    new = _write(tmp_path / "new.json", _balanced(5_000))
    assert _run(ref, new, "--epsilon", "0.02").exit_code == EXIT_INCONCLUSIVE
    assert _run(ref, new, "--epsilon", "0.05").exit_code == EXIT_VERIFIED


@pytest.mark.usefixtures("statistical_dependencies")
def test_reports_the_epsilon_actually_used(tmp_path):
    ref = _write(tmp_path / "ref.json", _balanced(50_000))
    new = _write(tmp_path / "new.json", _balanced(50_000))
    result = _run(ref, new, "--epsilon", "0.05")
    assert "0.05" in result.output


# --- malformed input ------------------------------------------------------

def test_malformed_json_errors_cleanly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    good = _write(tmp_path / "good.json", _balanced(1000))
    result = _run(str(bad), good)
    assert result.exit_code == EXIT_ERROR
    assert "Traceback" not in result.output


def test_negative_counts_error_cleanly(tmp_path):
    ref = _write(tmp_path / "ref.json", {"00": -5, "11": 100})
    new = _write(tmp_path / "new.json", _balanced(1000))
    result = _run(ref, new)
    assert result.exit_code == EXIT_ERROR
    assert "Traceback" not in result.output


def test_non_integer_counts_error_cleanly(tmp_path):
    ref = _write(tmp_path / "ref.json", {"00": "many", "11": 100})
    new = _write(tmp_path / "new.json", _balanced(1000))
    result = _run(ref, new)
    assert result.exit_code == EXIT_ERROR
    assert "Traceback" not in result.output


def test_missing_file_errors_cleanly(tmp_path):
    good = _write(tmp_path / "good.json", _balanced(1000))
    result = _run(str(tmp_path / "absent.json"), good)
    assert result.exit_code != EXIT_VERIFIED
    assert "Traceback" not in result.output


# --- json output ----------------------------------------------------------

@pytest.mark.usefixtures("statistical_dependencies")
def test_json_output_carries_verdict_and_metrics(tmp_path):
    ref = _write(tmp_path / "ref.json", _balanced(50_000))
    new = _write(tmp_path / "new.json", _balanced(50_000))
    result = _run(ref, new, "--json")
    data = json.loads(result.output)
    assert data["verdict"] == "VERIFIED"
    assert "tvd_ucb" in data["metrics"]
    assert "epsilon_used" in data["metrics"]


def test_json_output_on_error_is_still_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    good = _write(tmp_path / "good.json", _balanced(1000))
    result = _run(str(bad), good, "--json")
    assert result.exit_code == EXIT_ERROR
    json.loads(result.output)


# --- dependency guard -----------------------------------------------------

def test_missing_numpy_fails_cleanly(tmp_path, monkeypatch):
    # The base install ships without numpy/scipy. The verifier already raises
    # a guiding ImportError; the CLI must surface it, not a traceback.
    from marqov_capsule.verifier import CapsuleVerifier

    def _boom(*args, **kwargs):
        raise ImportError(
            "Statistical verification requires numpy and scipy: pip install numpy scipy"
        )

    monkeypatch.setattr(CapsuleVerifier, "verify_statistical", _boom)
    ref = _write(tmp_path / "ref.json", _balanced(1000))
    new = _write(tmp_path / "new.json", _balanced(1000))
    result = _run(ref, new)
    assert result.exit_code == EXIT_ERROR
    assert "numpy" in result.output
    assert "Traceback" not in result.output


# --- stale help text ------------------------------------------------------

def test_verify_help_no_longer_says_comparison_is_unavailable():
    result = CliRunner().invoke(cli, ["verify", "--help"])
    assert "not available in this release" not in result.output
