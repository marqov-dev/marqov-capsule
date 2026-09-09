"""Command-level regressions for verified capsule delivery."""
import io
import json
import os
from pathlib import Path
import tarfile

import pytest
from click.testing import CliRunner

from marqov_capsule import CapsuleBuilder, CapsuleVerifier
from marqov_capsule.archive import payload_digest
from marqov_capsule.cli.main import cli


def sealed(path):
    path.mkdir()
    (path / "result.json").write_text('{"value":1}\n')
    return CapsuleBuilder().start_capsule(
        name="delivery", requirements={"paradigm": ["classical"], "max_qubit_count": 0},
    ).seal(path)


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_verify_does_not_read_rejected_checksum_metadata(tmp_path, monkeypatch, kind):
    capsule = tmp_path / "capsule"
    trusted = sealed(capsule)
    metadata = capsule / ".checksums"
    metadata.unlink()
    if kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_text("private")
        metadata.symlink_to(outside)
    elif kind == "directory":
        metadata.mkdir()
    else:
        os.mkfifo(metadata)
    original = Path.read_bytes
    def guarded(path):
        assert path != metadata, "must not read rejected checksum metadata"
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(ValueError):
        payload_digest(capsule)
    result = CliRunner().invoke(cli, ["verify", str(capsule), "--id", trusted, "--json"])
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["status"] == "fail"
    assert report["payload_digest"] is None


def test_non_archive_has_machine_readable_failure(tmp_path):
    invalid = tmp_path / "invalid.capsule"
    invalid.write_text("not an archive")
    result = CliRunner().invoke(cli, ["verify", str(invalid), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "fail"


def test_archive_without_checksums_is_reported_as_failed_verification(tmp_path):
    archive = tmp_path / "incomplete.capsule"
    with tarfile.open(archive, "w:gz") as stream:
        data = b"name: incomplete\n"
        member = tarfile.TarInfo("incomplete/capsule.yaml")
        member.size = len(data)
        stream.addfile(member, io.BytesIO(data))
    result = CliRunner().invoke(cli, ["verify", str(archive), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "fail"


@pytest.mark.parametrize("existing", ["directory", "symlink"])
def test_open_refuses_existing_destination_without_modifying_it(tmp_path, existing):
    source = tmp_path / "capsule"
    trusted = sealed(source)
    destination = tmp_path / "destination"
    destination.mkdir()
    target = destination / source.name
    preserved = tmp_path / "outside" if existing == "symlink" else target
    preserved.mkdir()
    sentinel = preserved / "result.json"
    sentinel.write_text("existing result")
    if existing == "symlink":
        target.symlink_to(preserved, target_is_directory=True)
    result = CliRunner().invoke(cli, ["open", str(source), "--dest", str(destination),
                                      "--id", trusted, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"
    assert sentinel.read_text() == "existing result"
    assert not (preserved / "capsule.yaml").exists()


def test_open_fresh_destination_preserves_trusted_identity(tmp_path):
    source = tmp_path / "capsule"
    trusted = sealed(source)
    destination = tmp_path / "destination"
    result = CliRunner().invoke(cli, ["open", str(source), "--dest", str(destination), "--id", trusted])
    assert result.exit_code == 0, result.output
    assert CapsuleVerifier.verify_integrity(destination / "capsule", expected_id=trusted)["status"] == "pass"
