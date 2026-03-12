"""Tests for the archive module (pack, unpack, content_id)."""

import hashlib
import tarfile
import tempfile
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder
from marqov_capsule.archive import content_id, pack_capsule, unpack_capsule


def _make_sealed_capsule_dir(parent: Path, name: str = "test-capsule") -> Path:
    """Helper: create a sealed capsule directory with .checksums on disk."""
    builder = CapsuleBuilder(name)
    builder.start_capsule(parameters={"x": 1})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 42})
    builder.seal_capsule(exit_code=0)
    capsule_dir = parent / f"{name}.capsule"
    capsule_dir.mkdir()
    builder.save_capsule(str(capsule_dir / "capsule.yaml"))
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


class TestContentId:
    """Tests for content_id()."""

    def test_content_id_from_directory(self):
        """content_id on a directory returns SHA256 of .checksums content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid = content_id(capsule_dir)

            # Manually compute expected value
            checksums_bytes = (capsule_dir / ".checksums").read_bytes()
            expected = "sha256:" + hashlib.sha256(checksums_bytes).hexdigest()
            assert cid == expected

    def test_content_id_from_archive(self):
        """content_id on a .capsule archive returns same hash as on directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            dir_cid = content_id(capsule_dir)

            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )
            archive_cid = content_id(archive_path)

            assert archive_cid == dir_cid

    def test_content_id_deterministic(self):
        """Same capsule directory always produces the same content_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid1 = content_id(capsule_dir)
            cid2 = content_id(capsule_dir)
            assert cid1 == cid2

    def test_content_id_format(self):
        """content_id returns 'sha256:' followed by 64 hex characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            cid = content_id(capsule_dir)
            assert cid.startswith("sha256:")
            hex_part = cid[len("sha256:"):]
            assert len(hex_part) == 64
            # Verify it's valid hex
            int(hex_part, 16)
