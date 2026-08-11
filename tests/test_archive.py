"""Tests for the archive module (pack, unpack, payload_digest)."""

import hashlib
import tarfile
import tempfile
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder
from marqov_capsule.archive import payload_digest, pack_capsule, unpack_capsule


def _make_sealed_capsule_dir(parent: Path, name: str = "test-capsule") -> Path:
    """Create a sealed capsule directory with .checksums on disk.

    Migrated to the current builder API — the original called
    ``CapsuleBuilder(name)``, which is what made every test in this file fail
    after the constructor changed, and is why the file was deleted rather than
    updated (#48).
    """
    capsule_dir = parent / f"{name}.capsule"
    (capsule_dir / "payload").mkdir(parents=True)
    (capsule_dir / "payload" / "results.json").write_text('{"counts": {"00": 42}}')
    CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": name, "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    }).seal(capsule_dir=capsule_dir, sealed_by="test")
    return capsule_dir


class TestPackCapsule:
    """Tests for pack_capsule()."""

    def test_pack_creates_archive(self):
        """pack_capsule creates a .capsule archive file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            archive_path = pack_capsule(capsule_dir)
            assert archive_path.exists()
            assert archive_path.suffix == ".capsule"
            # Should be a valid gzip tarball
            assert tarfile.is_tarfile(str(archive_path))

    def test_pack_deterministic(self):
        """Packing the same directory twice produces byte-identical archives."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))

            archive1 = pack_capsule(
                capsule_dir, output_path=Path(tmpdir) / "a1.capsule"
            )
            archive2 = pack_capsule(
                capsule_dir, output_path=Path(tmpdir) / "a2.capsule"
            )

            assert archive1.read_bytes() == archive2.read_bytes()

    def test_pack_requires_checksums(self):
        """pack_capsule raises an error if .checksums is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            # Remove the .checksums file
            (capsule_dir / ".checksums").unlink()
            with pytest.raises(FileNotFoundError, match=r"\.checksums"):
                pack_capsule(capsule_dir)

    def test_pack_default_output_name(self):
        """Default output path is {name}.capsule in same parent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir), name="my-wf")
            archive_path = pack_capsule(capsule_dir)
            # Directory is "my-wf.capsule", archive should be "my-wf.capsule"
            # placed next to (or derived from) the directory name
            assert archive_path.name == "my-wf.capsule"

    def test_pack_custom_output_path(self):
        """pack_capsule respects explicit output_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            custom = Path(tmpdir) / "custom-name.capsule"
            archive_path = pack_capsule(capsule_dir, output_path=custom)
            assert archive_path == custom
            assert archive_path.exists()


class TestUnpackCapsule:
    """Tests for unpack_capsule()."""

    def test_unpack_restores_directory(self):
        """Pack then unpack restores all original files with matching content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)

            # Collect original file contents
            original_files = {}
            for f in sorted(capsule_dir.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(capsule_dir)
                    original_files[str(rel)] = f.read_bytes()

            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "packed.capsule"
            )

            # Unpack into a separate directory
            out_dir = tmpdir / "unpacked"
            out_dir.mkdir()
            restored = unpack_capsule(archive_path, output_dir=out_dir)

            # All original files must be present with identical content
            for rel_name, content in original_files.items():
                restored_file = restored / rel_name
                assert restored_file.exists(), f"Missing: {rel_name}"
                assert restored_file.read_bytes() == content, f"Changed: {rel_name}"

    def test_unpack_requires_capsule_yaml(self):
        """unpack_capsule raises an error if the archive has no capsule.yaml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a tarball without capsule.yaml
            bad_archive = tmpdir / "bad.capsule"
            with tarfile.open(str(bad_archive), "w:gz") as tf:
                # Add a dummy file
                dummy = tmpdir / "dummy.txt"
                dummy.write_text("hello")
                tf.add(str(dummy), arcname="some-capsule/dummy.txt")

            with pytest.raises(ValueError, match=r"capsule\.yaml"):
                unpack_capsule(bad_archive)


class TestPayloadDigest:
    """Tests for payload_digest()."""

    def test_payload_digest_from_directory(self):
        """payload_digest on a directory returns SHA256 of .checksums content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid = payload_digest(capsule_dir)

            # Manually compute expected value
            checksums_bytes = (capsule_dir / ".checksums").read_bytes()
            expected = "sha256:" + hashlib.sha256(checksums_bytes).hexdigest()
            assert cid == expected

    def test_payload_digest_from_archive(self):
        """payload_digest on a .capsule archive returns same hash as on directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            dir_cid = payload_digest(capsule_dir)

            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )
            archive_cid = payload_digest(archive_path)

            assert archive_cid == dir_cid

    def test_payload_digest_deterministic(self):
        """Same capsule directory always produces the same payload_digest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid1 = payload_digest(capsule_dir)
            cid2 = payload_digest(capsule_dir)
            assert cid1 == cid2

    def test_payload_digest_format(self):
        """payload_digest returns 'sha256:' followed by 64 hex characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid = payload_digest(capsule_dir)
            assert cid.startswith("sha256:")
            hex_part = cid[len("sha256:"):]
            assert len(hex_part) == 64
            # Verify it's valid hex
            int(hex_part, 16)


class TestErrorPaths:
    """Tests for error handling across archive functions."""

    def test_pack_nonexistent_directory(self):
        """pack_capsule raises FileNotFoundError for nonexistent directory."""
        with pytest.raises(FileNotFoundError):
            pack_capsule("/nonexistent/path")

    def test_unpack_nonexistent_archive(self):
        """unpack_capsule raises FileNotFoundError for nonexistent archive."""
        with pytest.raises(FileNotFoundError):
            unpack_capsule("/nonexistent/archive.capsule")

    def test_payload_digest_nonexistent_path(self):
        """payload_digest raises FileNotFoundError for nonexistent path."""
        with pytest.raises(FileNotFoundError):
            payload_digest("/nonexistent/path")

    def test_payload_digest_directory_missing_checksums(self):
        """payload_digest raises FileNotFoundError if directory has no .checksums."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            (capsule_dir / ".checksums").unlink()
            with pytest.raises(FileNotFoundError, match=r"\.checksums"):
                payload_digest(capsule_dir)

    def test_payload_digest_archive_missing_checksums(self):
        """payload_digest raises FileNotFoundError if archive has no .checksums."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            bad_archive = tmpdir / "bad.capsule"
            with tarfile.open(str(bad_archive), "w:gz") as tf:
                dummy = tmpdir / "dummy.txt"
                dummy.write_text("hello")
                tf.add(str(dummy), arcname="cap/dummy.txt")
            with pytest.raises(FileNotFoundError, match=r"\.checksums"):
                payload_digest(bad_archive)
