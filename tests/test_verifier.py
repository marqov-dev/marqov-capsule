import tempfile
from pathlib import Path

import pytest
import yaml

from marqov_capsule import CapsuleBuilder, CapsuleVerifier


def _make_sealed_capsule(tmpdir: str) -> Path:
    """Helper: create a sealed capsule on disk."""
    builder = CapsuleBuilder("verify-test")
    builder.start_capsule(parameters={"x": 1})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 42})
    builder.seal_capsule(exit_code=0)
    capsule_dir = Path(tmpdir) / "verify-test.capsule"
    capsule_dir.mkdir()
    path = capsule_dir / "capsule.yaml"
    builder.save_capsule(str(path))
    return path


def test_load_and_verify_deterministic():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _make_sealed_capsule(tmpdir)
        verifier = CapsuleVerifier()
        capsule = verifier.load_capsule(str(path))
        result = verifier.verify_capsule(capsule, method="deterministic")
        assert result["verification_passed"] is True


def test_verify_checksums():
    """Verifier detects tampered files via .checksums."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _make_sealed_capsule(tmpdir)
        capsule_dir = path.parent

        # Verify passes on clean capsule
        verifier = CapsuleVerifier()
        result = verifier.verify_checksums(capsule_dir)
        assert result["passed"] is True

        # Tamper with capsule.yaml
        with open(path, "a") as f:
            f.write("\n# tampered\n")

        # Verify should now detect the tampering
        result = verifier.verify_checksums(capsule_dir)
        assert result["passed"] is False
        assert "capsule.yaml" in result["mismatched"]


try:
    import scipy
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

@pytest.mark.skipif(not HAS_SCIPY, reason="scipy not installed")
def test_statistical_verification():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = _make_sealed_capsule(tmpdir)
        verifier = CapsuleVerifier()
        capsule = verifier.load_capsule(str(path))
        # Statistical verify with reference results
        result = verifier.verify_capsule(
            capsule,
            method="statistical",
            reference_results={"counts": {"00": 500, "11": 500}},
        )
        assert "verification_passed" in result


def _create_test_capsule(name="test-capsule", **kwargs):
    """Helper to create a sealed test capsule (in-memory)."""
    builder = CapsuleBuilder(name=name, **kwargs)
    builder.start_capsule()
    builder.add_task_execution(
        task_id="task1",
        backend="local",
        wall_time_seconds=2.0,
        cost_usd=0.0,
    )
    builder.seal_capsule()
    return builder.get_capsule_data()


def test_calibration_drift_check():
    """Test QPU calibration drift detection."""
    capsule1 = _create_test_capsule()
    capsule2 = _create_test_capsule()

    # Add calibration data
    capsule1["extensions"]["qpu_calibration"] = {
        "calibration_timestamp": "2026-01-06T10:00:00Z",
        "gate_fidelities": {
            "single_qubit_gate_fidelity_mean": 0.9995,
            "two_qubit_gate_fidelity_mean": 0.9920,
        },
    }

    # Small drift (should pass)
    capsule2["extensions"]["qpu_calibration"] = {
        "calibration_timestamp": "2026-01-06T11:00:00Z",
        "gate_fidelities": {
            "single_qubit_gate_fidelity_mean": 0.9993,  # -0.0002
            "two_qubit_gate_fidelity_mean": 0.9915,  # -0.0005
        },
    }

    verifier = CapsuleVerifier()
    result = verifier.check_calibration_drift(
        capsule1,
        capsule2,
        max_fidelity_drift=0.01,
    )

    assert result["calibration_drift_check"] is True
    assert "single_qubit_fidelity_delta" in result
    assert "two_qubit_fidelity_delta" in result


def test_compare_capsules():
    """Test comparing two capsules."""
    capsule1 = _create_test_capsule(name="vqe-h2")
    capsule2 = _create_test_capsule(name="vqe-h2")

    with tempfile.TemporaryDirectory() as tmpdir:
        path1 = Path(tmpdir) / "capsule1.yaml"
        path2 = Path(tmpdir) / "capsule2.yaml"

        with open(path1, "w") as f:
            yaml.dump(capsule1, f)
        with open(path2, "w") as f:
            yaml.dump(capsule2, f)

        verifier = CapsuleVerifier()
        result = verifier.compare_capsules(path1, path2)

        assert "overall_consistent" in result
        assert result["metadata"]["same_workflow"] is True
        assert "cost" in result
        assert "execution" in result


def test_verify_with_reference_results():
    """Test verification with reference result digests."""
    capsule_data = _create_test_capsule()

    # Add result digests
    capsule_data["extensions"]["result_digests"] = {
        "energy": {
            "digest": "sha256:abc123",
            "type": "statistical",
        }
    }

    reference_results = {
        "energy": {
            "digest": "sha256:abc123",
            "type": "statistical",
        }
    }

    verifier = CapsuleVerifier()
    result = verifier.verify_capsule(
        capsule_data,
        method="deterministic",
        reference_results=reference_results,
    )

    assert "digest_comparison" in result["details"]


def test_compare_digests():
    """Test digest comparison between two sets of digests."""
    verifier = CapsuleVerifier()

    digests1 = {
        "result1": {"digest": "sha256:abc123"},
        "result2": {"digest": "sha256:def456"},
    }

    digests2 = {
        "result1": {"digest": "sha256:abc123"},  # Match
        "result2": {"digest": "sha256:different"},  # Mismatch
    }

    matches = verifier._compare_digests(digests1, digests2)

    assert matches["result1"] is True
    assert matches["result2"] is False


def test_energy_tolerance_check():
    """Test energy tolerance check."""
    verifier = CapsuleVerifier()

    # Within tolerance should pass
    result = verifier._energy_tolerance_check(
        energy1=-1.1372,
        energy2=-1.1370,
        tolerance=0.01,
    )

    assert result["test"] == "energy_tolerance"
    assert result["passed"] is True
    assert "delta" in result

    # Outside tolerance should fail
    result = verifier._energy_tolerance_check(
        energy1=-1.1372,
        energy2=-1.0000,
        tolerance=0.01,
    )

    assert result["passed"] is False
