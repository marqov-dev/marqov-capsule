import json
from pathlib import Path
import pytest
from marqov_capsule.validator import CapsuleValidator


FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


def test_valid_capsule_passes():
    result = CapsuleValidator.validate_file(FIXTURE_DIR / "valid_capsule/capsule.yaml")
    assert result["valid"] is True
    assert result["errors"] == []


def test_invalid_capsule_fails():
    result = CapsuleValidator.validate_file(FIXTURE_DIR / "invalid_capsule/capsule.yaml")
    assert result["valid"] is False
    assert len(result["errors"]) > 0


def test_multi_task_capsule_passes():
    result = CapsuleValidator.validate_file(FIXTURE_DIR / "multi_task_capsule/capsule.yaml")
    assert result["valid"] is True


def test_missing_required_field():
    result = CapsuleValidator.validate({"name": "test", "lifecycle_state": "draft"})
    assert result["valid"] is False
    field_paths = [e["path"] for e in result["errors"]]
    assert any("version" in p for p in field_paths)


def test_wrong_lifecycle_state():
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "test",
        "lifecycle_state": "invalid_state"
    })
    assert result["valid"] is False


def test_probabilistic_task_requires_verification_settings():
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "test",
        "lifecycle_state": "draft",
        "task_executions": [{
            "task_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "success",
            "result_type": "probabilistic",
            "backend": {"provider": "ibm", "name": "ibm_kyiv", "shots": 1000}
            # verification_settings intentionally omitted
        }]
    })
    assert result["valid"] is False


def test_deterministic_task_no_verification_settings_needed():
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "test",
        "lifecycle_state": "draft",
        "task_executions": [{
            "task_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "success",
            "result_type": "deterministic",
            "backend": {"provider": "ibm", "name": "ibm_simulator", "shots": 1}
        }]
    })
    assert result["valid"] is True


def test_missing_file_returns_error():
    result = CapsuleValidator.validate_file("/nonexistent/capsule.yaml")
    assert result["valid"] is False
    assert any("not found" in e["message"].lower() or "no such" in e["message"].lower()
               for e in result["errors"])


def test_structured_errors_have_path_and_message():
    result = CapsuleValidator.validate({"name": "test"})
    assert result["valid"] is False
    for err in result["errors"]:
        assert "path" in err
        assert "message" in err


def test_sealed_capsule_requires_requirements_and_checksums():
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "test",
        "lifecycle_state": "sealed",
        # requirements, checksums_digest, sealed_at, sealed_by intentionally absent
    })
    assert result["valid"] is False
    paths = [e["path"] for e in result["errors"]]
    assert any("requirements" in p or "checksums_digest" in p or p == "/" for p in paths)


def test_sealed_capsule_with_required_fields_passes():
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "test",
        "lifecycle_state": "sealed",
        "sealed_at": "2026-06-11T00:00:00Z",
        "sealed_by": "test",
        "checksums_digest": "sha256:" + "a" * 64,
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
    })
    assert result["valid"] is True


def test_annealing_paradigm_validates():
    """#53: D-Wave / annealing workloads must produce schema-valid capsules."""
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "dwave-run",
        "lifecycle_state": "runnable",
        "requirements": {"paradigm": ["annealing"], "max_qubit_count": 2000},
    })
    assert result["valid"] is True


def test_unknown_paradigm_still_rejected():
    """Adding 'annealing' must not weaken the enum — junk still fails."""
    result = CapsuleValidator.validate({
        "version": "1.0.0",
        "name": "x",
        "lifecycle_state": "runnable",
        "requirements": {"paradigm": ["photonic"], "max_qubit_count": 2},
    })
    assert result["valid"] is False
