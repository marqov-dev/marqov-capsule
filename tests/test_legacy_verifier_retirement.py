"""Legacy false-success cases must produce explicit migration errors."""
import pytest
import yaml

from marqov_capsule import CapsuleVerifier


@pytest.mark.parametrize("method", [None, "deterministic", "statistical", "verification-only"])
@pytest.mark.parametrize("capsule,reference", [
    ({}, {"unrelated": 1}),
    ({"digests": dict.fromkeys(["workflow", "environment", "backends", "provenance"], "claim")}, None),
    ({"lifecycle_state": "sealed", "name": "test", "digests": {"any": "claim"}, "tasks": []}, None),
    ({"reproducibility_tier": "unknown"}, {}),
])
def test_legacy_verification_never_returns_a_verdict(method, capsule, reference):
    with pytest.raises(NotImplementedError, match="verify_integrity"):
        CapsuleVerifier().verify_capsule(capsule, method=method, reference_results=reference)


def test_matching_names_do_not_certify_capsule_consistency(tmp_path):
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text('name: same\nextensions: {counts: {"00": 1000}}\n')
    second.write_text('name: same\nextensions: {counts: {"11": 1000}}\n')
    with pytest.raises(NotImplementedError, match="Matching capsule names"):
        CapsuleVerifier().compare_capsules(first, second)


def test_missing_fidelities_are_not_zero_drift():
    first = {"extensions": {"qpu_calibration": {"name": "first"}}}
    second = {"extensions": {"qpu_calibration": {"name": "second"}}}
    with pytest.raises(NotImplementedError, match="No replacement"):
        CapsuleVerifier().check_calibration_drift(first, second)


def test_manifest_loader_uses_capsule_scalar_profile(tmp_path):
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text("name: yes\ncreated_at: 2026-09-09T00:00:00Z\n")
    result = CapsuleVerifier().load_capsule(manifest)
    assert result == {"name": "yes", "created_at": "2026-09-09T00:00:00Z"}


def test_manifest_loader_rejects_duplicate_keys(tmp_path):
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text("name: first\nname: second\n")
    with pytest.raises(yaml.YAMLError):
        CapsuleVerifier().load_capsule(manifest)


@pytest.mark.parametrize("text", ["[]", "null", "42"])
def test_manifest_loader_requires_mapping(tmp_path, text):
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text(text)
    with pytest.raises(ValueError, match="YAML mapping"):
        CapsuleVerifier().load_capsule(manifest)
