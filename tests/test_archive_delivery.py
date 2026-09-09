"""Reject ambiguous archives and preserve existing extraction destinations."""
import io
from pathlib import Path
import tarfile

import pytest

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.archive import pack_capsule, unpack_capsule


@pytest.mark.parametrize("names", [
    ["record/capsule.yaml", "record/capsule.yaml"],
    ["record/capsule.yaml", "other/payload"],
    ["capsule.yaml"],
    ["record/capsule.yaml", "record/./payload"],
    ["record/capsule.yaml", "record/é", "record/e\u0301"],
])
@pytest.mark.parametrize("filtered", [True, False])
def test_ambiguous_layout_rejected_before_extraction(tmp_path, monkeypatch, names, filtered):
    monkeypatch.setattr("marqov_capsule.archive._extractall_filter_supported", lambda: filtered)
    archive = tmp_path / "ambiguous.capsule"
    with tarfile.open(archive, "w:gz") as stream:
        for name in names:
            member = tarfile.TarInfo(name)
            member.size = 3
            stream.addfile(member, io.BytesIO(b"x:1"))
    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(ValueError):
        unpack_capsule(archive, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("symlink", [False, True])
def test_unpack_preserves_existing_destination(tmp_path, symlink):
    source = tmp_path / "record"
    source.mkdir()
    builder = CapsuleBuilder().start_capsule(
        name="delivery", requirements={"paradigm": ["classical"], "max_qubit_count": 0},
    )
    builder.seal(source)
    archive = pack_capsule(source, tmp_path / "record.capsule")
    destination = tmp_path / "destination"
    destination.mkdir()
    target = destination / "record"
    existing = tmp_path / "existing" if symlink else target
    existing.mkdir()
    marker = existing / "capsule.yaml"
    marker.write_text("preserve this")
    if symlink:
        target.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="already exists"):
        unpack_capsule(archive, destination)
    assert marker.read_text() == "preserve this"
    assert sorted(p.name for p in existing.iterdir()) == ["capsule.yaml"]


@pytest.mark.parametrize("metadata,operation", [("capsule.yaml", "read_text"), (".checksums", "read_bytes")])
def test_metadata_read_errors_are_failed_verdicts(tmp_path, monkeypatch, metadata, operation):
    trusted = CapsuleBuilder().start_capsule(
        name="read-error", requirements={"paradigm": ["classical"], "max_qubit_count": 0},
    ).seal(tmp_path)
    original = getattr(Path, operation)
    def denied(path, *args, **kwargs):
        if path == tmp_path / metadata:
            raise PermissionError("synthetic read error")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, operation, denied)
    result = CapsuleVerifier.verify_integrity(tmp_path, expected_id=trusted)
    assert result["status"] == "fail"
    if metadata == "capsule.yaml":
        assert not CapsuleValidator.validate_file(tmp_path / metadata)["valid"]
