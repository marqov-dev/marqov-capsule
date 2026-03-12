import tempfile
from pathlib import Path

import pytest

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
