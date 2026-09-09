"""Release regressions across schema, filesystem, and trusted-ID boundaries."""
import hashlib
import json
import os
from pathlib import Path
import unicodedata

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.cli.main import cli


def seal(path):
    path.mkdir()
    (path / "result.json").write_text('{"value":1}\n')
    return CapsuleBuilder().start_capsule(
        name="readiness", requirements={"paradigm": ["classical"], "max_qubit_count": 0},
    ).seal(path)


def test_uuid_format_is_enforced():
    task = {"task_id": "not-a-uuid", "status": "success", "result_type": "deterministic",
            "backend": {"provider": "local", "name": "simulator", "shots": 1}}
    manifest = {"version": "1.0.0", "name": "test", "lifecycle_state": "draft",
                "task_executions": [task]}
    result = CapsuleValidator.validate(manifest)
    assert not result["valid"]
    assert any(e["path"] == "task_executions/0/task_id" for e in result["errors"])
    task["task_id"] = "550e8400-e29b-41d4-a716-446655440000"
    assert CapsuleValidator.validate(manifest)["valid"]


def test_invalid_utf8_is_a_validation_failure(tmp_path):
    (tmp_path / "capsule.yaml").write_bytes(b"name: \xff")
    result = CapsuleValidator.validate_file(tmp_path / "capsule.yaml")
    assert not result["valid"]
    assert "UTF-8" in result["errors"][0]["message"]
    assert CliRunner().invoke(cli, ["validate", str(tmp_path)]).exit_code == 1


@pytest.mark.parametrize("value", [{1: "value"}, {"é": 1, "e\u0301": 2}, float("nan"), float("inf"), b"binary", 2**53])
def test_non_json_manifest_values_are_invalid(value):
    manifest = {"version": "1.0.0", "name": "test", "lifecycle_state": "draft",
                "parameters": {"value": value}}
    result = CapsuleValidator.validate(manifest)
    assert not result["valid"]
    assert result["errors"][0]["path"] == "parameters/value"


def test_recursive_yaml_alias_fails_without_recursion_error(tmp_path):
    (tmp_path / "capsule.yaml").write_text("parameters: &loop [*loop]\n")
    result = CapsuleValidator.validate_file(tmp_path / "capsule.yaml")
    assert not result["valid"]


def test_shared_acyclic_value_is_allowed():
    shared = {"value": 1}
    manifest = {"version": "1.0.0", "name": "test", "lifecycle_state": "draft",
                "parameters": {"first": shared, "second": shared}}
    assert CapsuleValidator.validate(manifest)["valid"]


def test_decomposed_filename_roundtrips(tmp_path):
    name = unicodedata.normalize("NFD", "café.txt")
    (tmp_path / name).write_text("payload")
    builder = CapsuleBuilder().start_capsule(
        name="unicode", requirements={"paradigm": ["classical"], "max_qubit_count": 0},
    )
    trusted = builder.seal(tmp_path)
    assert "café.txt" in (tmp_path / ".checksums").read_text()
    assert CapsuleVerifier.verify_integrity(tmp_path, expected_id=trusted)["status"] == "pass"


def test_unicode_collisions_are_rejected(tmp_path):
    first, second = tmp_path / "é", tmp_path / "e\u0301"
    first.write_text("first")
    if second.exists():
        pytest.skip("filesystem aliases NFC and NFD names")
    second.write_text("second")
    with pytest.raises(ValueError, match="collide"):
        CapsuleBuilder().save_checksums(tmp_path)
    (tmp_path / ".checksums").write_text("sha256:" + hashlib.sha256(b"first").hexdigest() + "  é\n")
    result = CapsuleVerifier.verify_checksums(tmp_path)
    assert result["status"] == "fail"
    assert "é" in result["invalid"]


@pytest.mark.parametrize("metadata", ["capsule.yaml", ".checksums"])
def test_symlinked_metadata_is_never_read(tmp_path, monkeypatch, metadata):
    capsule = tmp_path / "capsule"
    trusted = seal(capsule)
    outside = tmp_path / "outside"
    (capsule / metadata).rename(outside)
    (capsule / metadata).symlink_to(outside)
    original_text, original_bytes = Path.read_text, Path.read_bytes
    def text(path, *args, **kwargs):
        assert path != capsule / metadata, "must not read symlinked metadata"
        return original_text(path, *args, **kwargs)
    def binary(path, *args, **kwargs):
        assert path != capsule / metadata, "must not read symlinked metadata"
        return original_bytes(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", text)
    monkeypatch.setattr(Path, "read_bytes", binary)
    assert CapsuleVerifier.verify_integrity(capsule, expected_id=trusted)["status"] == "fail"


@pytest.mark.parametrize("kind", ["directory", "fifo"])
def test_listed_nonregular_payload_fails_without_reading(tmp_path, monkeypatch, kind):
    target = tmp_path / "payload"
    if kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    (tmp_path / ".checksums").write_text("sha256:" + "0" * 64 + "  payload\n")
    original = Path.read_bytes
    def no_blocking_read(path):
        assert path != target, "must not read a nonregular file"
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", no_blocking_read)
    result = CapsuleVerifier.verify_checksums(tmp_path)
    assert result["status"] == "fail"
    assert "payload" in result["invalid"]


@pytest.mark.parametrize("attack", ["delete", "rewrite-all"])
def test_cli_trusted_id_rejects_missing_or_forged_payload(tmp_path, attack):
    capsule = tmp_path / "capsule"
    trusted = seal(capsule)
    if attack == "delete":
        (capsule / "result.json").unlink()
    else:
        (capsule / "result.json").write_text('{"value":2}\n')
        CapsuleBuilder().save_checksums(capsule)
        manifest = yaml.safe_load((capsule / "capsule.yaml").read_text())
        manifest["checksums_digest"] = "sha256:" + hashlib.sha256((capsule / ".checksums").read_bytes()).hexdigest()
        (capsule / "capsule.yaml").write_text(json.dumps(manifest))
        assert CapsuleVerifier.verify_integrity(capsule)["status"] == "pass"
    result = CliRunner().invoke(cli, ["verify", str(capsule), "--id", trusted])
    assert result.exit_code == 1
    assert CapsuleVerifier.verify_integrity(capsule, expected_id=trusted)["status"] == "fail"
