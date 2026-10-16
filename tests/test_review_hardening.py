"""Adversarial reproductions from the independent review of PR #131."""

import json
import os

import pytest
from click.testing import CliRunner

import marqov_capsule.builder as builder_module
from marqov_capsule.builder import CapsuleBuilder, CapsuleStateError, _checksum_path
from marqov_capsule.cli.main import cli
from marqov_capsule.redactor import RedactorError
from marqov_capsule.verifier import CapsuleVerifier

REQ = {"paradigm": ["gate-based"], "max_qubit_count": 2}
TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
HEX64 = "7e2a91c4f0b8d63e5a1f8c02d94b7e6a3f5c8091b2d4e6f7a0c1b3d5e7f9a2c4"


@pytest.mark.parametrize("pattern", ["capsule.yaml", "*.yaml", "*"])
@pytest.mark.parametrize("late_metadata", [False, True])
def test_ignore_cannot_disable_manifest_scan(tmp_path, pattern, late_metadata):
    (tmp_path / ".capsuleignore").write_text(pattern + "\n")
    builder = CapsuleBuilder().start_capsule(
        "test", requirements=REQ, parameters={} if late_metadata else {"token": TOKEN}
    )
    with pytest.raises(RedactorError):
        builder.seal_capsule(tmp_path, notes=TOKEN if late_metadata else "")
    assert not (tmp_path / ".checksums").exists()
    assert builder.to_dict()["lifecycle_state"] == "draft"


@pytest.mark.parametrize(
    "parameters",
    [
        {"ibm_token": [HEX64]},
        {"IBM_QUANTUM_TOKEN": ["s3cr3tvalue123"]},
        {"IBM_QUANTUM_TOKEN": {"value": "s3cr3tvalue123"}},
        {"note": "x " * 34 + "ibm token " + HEX64},
        {"token": TOKEN + " # capsule:allow"},
    ],
)
def test_yaml_layout_and_data_annotations_do_not_hide_manifest_credentials(tmp_path, parameters):
    builder = CapsuleBuilder().start_capsule("test", requirements=REQ, parameters=parameters)
    with pytest.raises(RedactorError):
        builder.seal(tmp_path)
    assert not (tmp_path / "capsule.yaml").exists()


def test_structured_manifest_findings_include_field_path(tmp_path):
    builder = CapsuleBuilder().start_capsule(
        "test", requirements=REQ, parameters={"IBM_QUANTUM_TOKEN": ["s3cr3tvalue123"]}
    )
    builder.seal(tmp_path, warn_only=True)
    finding = next(f for f in builder.scan_result["findings"] if f["reason"] == "name_pattern")
    assert finding["field"] == "/parameters/IBM_QUANTUM_TOKEN/0"
    assert "s3cr3tvalue123" not in finding["match"]


def test_structured_finding_does_not_echo_secret_in_field_name(tmp_path):
    builder = CapsuleBuilder().start_capsule(
        "test", requirements=REQ, parameters={TOKEN: {"IBM_QUANTUM_TOKEN": [HEX64]}}
    )
    builder.seal(tmp_path, warn_only=True)
    assert all(TOKEN not in f.get("field", "") for f in builder.scan_result["findings"])


def test_numpy_integer_counts_preserve_statistical_result():
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    verifier = CapsuleVerifier()
    settings = {"epsilon": 0.1}
    plain = {"0": 500, "1": 500}
    expected = verifier.verify_statistical(plain, plain, settings)
    actual = verifier.verify_statistical({"0": np.int64(500), "1": np.uint64(500)}, plain, settings)
    assert actual == expected
    for count in (np.bool_(True), np.float64(500.0)):
        with pytest.raises(ValueError, match="integer"):
            verifier.verify_statistical({"0": count}, plain, settings)


@pytest.mark.parametrize("counts", [{"0": 10**400}, {"0": 2**53 - 1, "1": 1}])
def test_oversized_counts_are_clean_api_and_cli_errors(tmp_path, counts):
    with pytest.raises(ValueError, match="supported maximum"):
        CapsuleVerifier().verify_statistical(counts, {"0": 1000}, {})
    original = tmp_path / "original.json"
    new = tmp_path / "new.json"
    original.write_text(json.dumps(counts))
    new.write_text('{"0":1000}')
    result = CliRunner().invoke(cli, ["compare", str(original), str(new), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"
    assert "supported maximum" in result.output
    assert "Traceback" not in result.output


def test_safe_shot_ceiling_accepts_boundary():
    from marqov_capsule.verifier import _normalise_counts

    assert _normalise_counts({"0": 2**53 - 1}, "counts") == {"0": 2**53 - 1}


@pytest.mark.parametrize("replacement", [True, 1.0])
def test_equal_comparing_changes_cannot_rewrite_sealed_record(tmp_path, replacement):
    builder = CapsuleBuilder().start_capsule("test", requirements=REQ, parameters={"shots": 1})
    builder.seal(tmp_path)
    before = (tmp_path / "capsule.yaml").read_bytes()
    builder._capsule["parameters"]["shots"] = replacement
    with pytest.raises(CapsuleStateError, match="modified sealed"):
        builder.save_capsule(tmp_path)
    assert (tmp_path / "capsule.yaml").read_bytes() == before


def test_checksum_partial_write_preserves_original_and_draft(tmp_path, monkeypatch):
    checksums = tmp_path / ".checksums"
    checksums.write_bytes(b"old checksum bytes")
    original_fdopen = builder_module.os.fdopen

    class FailingWriter:
        def __init__(self, fd, mode):
            self.file = original_fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.file.close()

        def write(self, data):
            self.file.write(data[:3])
            raise OSError("simulated disk full")

    monkeypatch.setattr(builder_module.os, "fdopen", FailingWriter)
    builder = CapsuleBuilder().start_capsule("test", requirements=REQ)
    (tmp_path / "payload.txt").write_text("x")
    with pytest.raises(OSError, match="disk full"):
        builder.seal_capsule(tmp_path)
    assert checksums.read_bytes() == b"old checksum bytes"
    assert builder.to_dict()["lifecycle_state"] == "draft"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("existing_checksums", [False, True])
def test_manifest_write_failure_restores_draft_and_allows_retry(
    tmp_path, monkeypatch, existing_checksums
):
    builder = CapsuleBuilder().start_capsule("test", requirements=REQ)
    builder.save_capsule(tmp_path)
    before = builder.to_dict()
    manifest = (tmp_path / "capsule.yaml").read_bytes()
    checksums = tmp_path / ".checksums"
    if existing_checksums:
        checksums.write_bytes(b"old checksums")
    original_replace = builder_module.os.replace

    def fail_manifest_replace(source, destination):
        if destination.name == "capsule.yaml":
            raise OSError("simulated manifest write failure")
        return original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(builder_module.os, "replace", fail_manifest_replace)
        with pytest.raises(OSError, match="manifest write failure"):
            builder.seal(tmp_path)
    assert builder.to_dict() == before
    assert builder.scan_result is None
    assert (tmp_path / "capsule.yaml").read_bytes() == manifest
    if existing_checksums:
        assert checksums.read_bytes() == b"old checksums"
    else:
        assert not checksums.exists()
    capsule_id = builder.seal(tmp_path)
    assert CapsuleVerifier.verify_integrity(tmp_path, expected_id=capsule_id)["status"] == "pass"


def test_cli_seal_io_failure_is_clean_error(tmp_path, monkeypatch):
    builder = CapsuleBuilder().start_capsule("test", requirements=REQ)
    builder.save_capsule(tmp_path)

    def fail_write(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(builder_module, "_atomic_write_bytes", fail_write)
    result = CliRunner().invoke(cli, ["seal", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"
    assert "Traceback" not in result.output


@pytest.mark.parametrize("kind", ["file", "directory", "broken"])
def test_seal_refuses_symlinks_before_writes(tmp_path, kind):
    target = tmp_path / "target"
    if kind == "file":
        target.write_text("x")
    elif kind == "directory":
        target.mkdir()
    try:
        (tmp_path / "link").symlink_to(target, target_is_directory=kind == "directory")
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="symlinks"):
        CapsuleBuilder().start_capsule("test", requirements=REQ).seal(tmp_path)
    assert not (tmp_path / ".checksums").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs unavailable on this host")
def test_seal_refuses_fifo_without_reading_it(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular files"):
        CapsuleBuilder().start_capsule("test", requirements=REQ).seal(tmp_path)
    assert not (tmp_path / ".checksums").exists()


def test_encoded_path_limit_matches_verifier_without_long_filesystem_path():
    assert len(_checksum_path("%" * 1365).encode()) == 4095
    with pytest.raises(ValueError, match="too long"):
        _checksum_path("%" * 1366)
