"""Regression cases from the 0.2.0 publication readiness review."""

import os

import pytest

from marqov_capsule.builder import CapsuleBuilder, CapsuleStateError
from marqov_capsule.redactor import CapsuleRedactor, RedactorError
from marqov_capsule.verifier import CapsuleVerifier

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}
# Deliberately synthetic shape accepted by the credential detector.
TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@pytest.mark.parametrize("field", ["sealed_by", "notes", "derived_from"])
def test_seal_metadata_secrets_block_without_changing_draft(tmp_path, field):
    builder = CapsuleBuilder().start_capsule(name="test", requirements=REQUIREMENTS)
    before = builder.to_dict()
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text("# keep the author's draft comments\n")
    checksums = tmp_path / ".checksums"
    checksums.write_bytes(b"previous checksums\n")
    kwargs = {field: TOKEN}
    # A malformed parent ID must still be scanned when schema validation is
    # explicitly disabled; a valid parent ID cannot contain this token shape.
    if field == "derived_from":
        kwargs["validate"] = False
    with pytest.raises(RedactorError):
        builder.seal_capsule(tmp_path, **kwargs)
    assert builder.to_dict() == before
    assert manifest.read_text() == "# keep the author's draft comments\n"
    assert checksums.read_bytes() == b"previous checksums\n"


@pytest.mark.parametrize("field", ["sealed_by", "notes", "derived_from"])
def test_warn_only_scans_the_written_sealed_manifest(tmp_path, monkeypatch, field):
    scanned = []
    original_scan = CapsuleRedactor.scan_and_raise

    def record_scan(redactor, overrides=None):
        scanned.append(overrides["capsule.yaml"])
        return original_scan(redactor, overrides=overrides)

    monkeypatch.setattr(CapsuleRedactor, "scan_and_raise", record_scan)
    builder = CapsuleBuilder().start_capsule(name="test", requirements=REQUIREMENTS)
    builder.seal_capsule(
        tmp_path, **{field: TOKEN}, warn_only=True, validate=field != "derived_from"
    )
    builder.save_capsule(tmp_path)
    written = (tmp_path / "capsule.yaml").read_text()
    assert TOKEN in written
    assert scanned == [written]
    assert any(f["reason"] == "github_token" for f in builder.scan_result["findings"])


def test_nested_inputs_and_exports_cannot_change_sealed_record(tmp_path):
    requirements = {"paradigm": ["gate-based"], "max_qubit_count": 2}
    parameters = {"nested": {"angle": 1}}
    tags = ["original"]
    backend = {"provider": "local", "name": "sim", "shots": 1000}
    settings = {"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"}
    builder = CapsuleBuilder().start_capsule(
        name="test", requirements=requirements, parameters=parameters, tags=tags
    )
    builder.add_task_execution(
        "550e8400-e29b-41d4-a716-446655440000", "success", "probabilistic", backend, settings
    )
    exported_before_seal = builder.to_dict()
    capsule_id = builder.seal(tmp_path)
    written = (tmp_path / "capsule.yaml").read_bytes()
    requirements["paradigm"].append("analog")
    parameters["nested"]["angle"] = 99
    tags.append("changed")
    backend["shots"] = 1
    settings["epsilon"] = 0.9
    exported_before_seal["requirements"]["max_qubit_count"] = 99
    exported_after_seal = builder.to_dict()
    exported_after_seal["task_executions"][0]["backend"]["name"] = "changed"
    builder.save_capsule(tmp_path)
    assert (tmp_path / "capsule.yaml").read_bytes() == written
    assert CapsuleVerifier.verify_integrity(tmp_path, expected_id=capsule_id)["status"] == "pass"


def test_sealed_snapshot_refuses_modified_internal_manifest(tmp_path):
    builder = CapsuleBuilder().start_capsule(name="test", requirements=REQUIREMENTS)
    builder.seal(tmp_path)
    written = (tmp_path / "capsule.yaml").read_bytes()
    builder._capsule["requirements"]["max_qubit_count"] = 99
    with pytest.raises(CapsuleStateError, match="modified sealed"):
        builder.save_capsule(tmp_path)
    assert (tmp_path / "capsule.yaml").read_bytes() == written


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses control characters in filenames")
@pytest.mark.parametrize("char", ["\x01", "\t", "\x1f", "\x7f"])
def test_unsupported_filename_refuses_seal_before_writes(tmp_path, char):
    builder = CapsuleBuilder().start_capsule(name="test", requirements=REQUIREMENTS)
    (tmp_path / f"bad{char}name.txt").write_text("payload")
    with pytest.raises(ValueError, match="control character"):
        builder.seal(tmp_path)
    assert builder.to_dict()["lifecycle_state"] == "draft"
    assert not (tmp_path / ".checksums").exists()
    assert not (tmp_path / "capsule.yaml").exists()


@pytest.mark.parametrize("arm", ["ref_counts", "new_counts"])
@pytest.mark.parametrize(
    "invalid",
    [
        {"0": 1100, "1": -100},
        {"0": 1000.5},
        {"0": True},
        {"0": float("nan")},
        {"0": float("inf")},
        {"0": "1000"},
        {0: 1000},
        None,
        [1000],
    ],
)
def test_statistical_api_rejects_invalid_counts_before_verdict(arm, invalid):
    inputs = {"ref_counts": {"0": 1000}, "new_counts": {"0": 1000}}
    inputs[arm] = invalid
    with pytest.raises(ValueError, match=arm):
        CapsuleVerifier().verify_statistical(**inputs, verification_settings={"epsilon": 0.1})


def test_zero_integer_counts_remain_inconclusive():
    result = CapsuleVerifier().verify_statistical({"0": 0}, {}, {})
    assert result["verdict"] == "INCONCLUSIVE"
