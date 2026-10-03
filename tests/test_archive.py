"""Tests for the archive module (pack, unpack, payload_digest)."""

import hashlib
import io
import os
import tarfile
import tempfile
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder
from marqov_capsule import archive as archive_mod
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

    def test_pack_creates_archive(self, tmp_path, monkeypatch):
        """pack_capsule creates a .capsule archive file."""
        src = tmp_path / "src"
        src.mkdir()
        capsule_dir = _make_sealed_capsule_dir(src)
        # Default output lands in cwd; chdir into an isolated dir so nothing
        # is written into the repository working tree.
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
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

    def test_pack_default_output_name(self, tmp_path, monkeypatch):
        """Default output is {name}.capsule in the current working directory."""
        src = tmp_path / "src"
        src.mkdir()
        capsule_dir = _make_sealed_capsule_dir(src, name="my-wf")
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        archive_path = pack_capsule(capsule_dir)
        # Directory is "my-wf.capsule"; the archive keeps that name.
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


class TestSymlinkNoDereference:
    """#55 — pack must not dereference payload symlinks into the archive."""

    def test_pack_does_not_dereference_payload_symlink(self, tmp_path):
        """A payload symlink is stored as a symlink member, not its target's
        bytes.  Following it would embed an outside file (here, a "secret")
        into the shipped .capsule — the exfiltration #55 is about."""
        secret = tmp_path / "secret.txt"
        secret_text = "TOP-SECRET-PRIVATE-KEY-MATERIAL"
        secret.write_text(secret_text)

        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="linky")
        link = capsule_dir / "payload" / "link.txt"
        link.symlink_to(secret)  # points OUTSIDE the capsule

        archive = pack_capsule(capsule_dir, output_path=tmp_path / "packed.capsule")

        with tarfile.open(str(archive), "r:gz") as tf:
            member = tf.getmember("linky.capsule/payload/link.txt")
            assert member.issym(), "symlink was dereferenced into the archive"
            # A symlink member carries no data blocks; the target's bytes were
            # never read into the archive.
            assert member.size == 0, "symlink member carries file content"
            # os.readlink is what the link says; on Windows that carries a
            # \\?\ prefix that str(secret) does not.
            assert member.linkname == os.readlink(link)

    def test_pack_symlink_member_names_the_target_not_its_content(self, tmp_path):
        """The stored symlink points at its original target (linkname), and the
        secret's content is not present as a regular-file member anywhere."""
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-PRIVATE-KEY-MATERIAL")

        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="linky2")
        link = capsule_dir / "payload" / "link.txt"
        link.symlink_to(secret)

        archive = pack_capsule(capsule_dir, output_path=tmp_path / "packed.capsule")
        with tarfile.open(str(archive), "r:gz") as tf:
            member = tf.getmember("linky2.capsule/payload/link.txt")
            assert member.issym()
            assert member.linkname == os.readlink(link)


class TestArcnameSafety:
    """#61 — packing '.' / '..' must not yield unsafe archive members."""

    def test_pack_dot_directory_has_a_safe_top_level(self, tmp_path, monkeypatch):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="dotcap")
        monkeypatch.chdir(capsule_dir)

        archive = pack_capsule(".", output_path=tmp_path / "out.capsule")
        with tarfile.open(str(archive), "r:gz") as tf:
            names = tf.getnames()

        assert names, "archive has no members"
        for n in names:
            assert n, f"empty member name in {names}"
            assert not n.startswith("/"), f"absolute-looking member: {n}"
            assert n != ".." and not n.startswith("../") and "/../" not in n, (
                f"traversal-shaped member: {n}"
            )
        tops = {n.split("/")[0] for n in names}
        assert len(tops) == 1, f"expected a single top-level dir, got {tops}"
        top = tops.pop()
        assert top not in ("", ".", ".."), f"unsafe top-level: {top!r}"
        # It should be the resolved directory's real name.
        assert top == capsule_dir.resolve().name

    def test_pack_unpack_roundtrip_through_dot(self, tmp_path, monkeypatch):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="dotcap2")
        monkeypatch.chdir(capsule_dir)
        archive = pack_capsule(".", output_path=tmp_path / "out.capsule")

        dest = tmp_path / "dest"
        dest.mkdir()
        restored = unpack_capsule(archive, output_dir=dest)
        assert (restored / "capsule.yaml").exists()
        assert (restored / "payload" / "results.json").exists()


class TestDefaultOutputLocation:
    """#61 — the default output path is resolved against cwd, not the
    grandparent of a canonically-named <name>.capsule directory."""

    def test_default_output_lands_in_cwd_not_grandparent(self, tmp_path, monkeypatch):
        sub = tmp_path / "sub"
        sub.mkdir()
        capsule_dir = _make_sealed_capsule_dir(sub, name="my-wf")  # sub/my-wf.capsule
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)

        archive = pack_capsule(capsule_dir)  # no output_path

        assert archive.parent.resolve() == work.resolve()
        assert archive.name == "my-wf.capsule"
        # The grandparent of the capsule dir is tmp_path; nothing must land there.
        assert not (tmp_path / "my-wf.capsule").exists()

    def test_pack_refuses_to_overwrite_the_source_directory(self, tmp_path, monkeypatch):
        # Packing a canonically-named dir from its own parent would default to
        # the directory's own path — refuse rather than clobber or misplace it.
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="collide")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="over the capsule directory"):
            pack_capsule(capsule_dir)


class TestExtractFilterFallback:
    """#61 — unpack must survive interpreters without extractall(filter=)."""

    def test_unpack_without_filter_support_still_extracts(
        self, tmp_path, monkeypatch
    ):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="fb")
        archive = pack_capsule(capsule_dir, output_path=tmp_path / "packed.capsule")

        monkeypatch.setattr(archive_mod, "_extractall_filter_supported", lambda: False)
        dest = tmp_path / "out"
        dest.mkdir()
        restored = unpack_capsule(archive, output_dir=dest)

        assert (restored / "capsule.yaml").exists()
        assert (restored / ".checksums").exists()
        assert (restored / "payload" / "results.json").exists()

    def test_fallback_blocks_path_traversal(self, tmp_path, monkeypatch):
        bad = tmp_path / "evil.capsule"
        with tarfile.open(str(bad), "w:gz") as tf:
            good = b"version: 1.0.0\n"
            ti = tarfile.TarInfo("evil.capsule/capsule.yaml")
            ti.size = len(good)
            tf.addfile(ti, io.BytesIO(good))
            payload = b"pwned"
            evil = tarfile.TarInfo("../escaped.txt")  # escapes the destination
            evil.size = len(payload)
            tf.addfile(evil, io.BytesIO(payload))

        monkeypatch.setattr(archive_mod, "_extractall_filter_supported", lambda: False)
        dest = tmp_path / "dest"
        dest.mkdir()
        with pytest.raises(ValueError, match="unsafe archive member|escapes destination"):
            unpack_capsule(bad, output_dir=dest)
        assert not (tmp_path / "escaped.txt").exists()

    def test_fallback_blocks_symlink_escaping_destination(self, tmp_path, monkeypatch):
        bad = tmp_path / "evil2.capsule"
        with tarfile.open(str(bad), "w:gz") as tf:
            good = b"version: 1.0.0\n"
            ti = tarfile.TarInfo("evil2.capsule/capsule.yaml")
            ti.size = len(good)
            tf.addfile(ti, io.BytesIO(good))
            link = tarfile.TarInfo("evil2.capsule/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"  # absolute, outside destination
            tf.addfile(link)

        monkeypatch.setattr(archive_mod, "_extractall_filter_supported", lambda: False)
        dest = tmp_path / "dest"
        dest.mkdir()
        with pytest.raises(ValueError, match="link target escapes"):
            unpack_capsule(bad, output_dir=dest)


class TestArchiveReproducibility:
    """#61 — members are ordered by byte value and all metadata normalised, so
    repacks are byte-identical regardless of host path flavour."""

    def test_member_order_is_bytewise_sorted(self, tmp_path):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="ord")
        # Mixed-case names: Path comparison folds case on some flavours, which
        # would order these differently across OSes.  Ordering must be pure
        # byte order of the archive names.
        for fname in ("B.txt", "a.txt", "C.txt", "d.txt"):
            (capsule_dir / "payload" / fname).write_text(fname)
        archive = pack_capsule(capsule_dir, output_path=tmp_path / "packed.capsule")

        with tarfile.open(str(archive), "r:gz") as tf:
            names = tf.getnames()
        assert names == sorted(names), names

    def test_all_metadata_is_normalised(self, tmp_path):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="norm")
        # Give a file a non-default mode to prove it is normalised away.
        os.chmod(capsule_dir / "payload" / "results.json", 0o600)
        archive = pack_capsule(capsule_dir, output_path=tmp_path / "packed.capsule")

        with tarfile.open(str(archive), "r:gz") as tf:
            for m in tf.getmembers():
                assert m.mtime == 0, m.name
                assert m.uid == 0 and m.gid == 0, m.name
                assert m.uname == "" and m.gname == "", m.name
                assert m.mode in (0o644, 0o755, 0o777), (m.name, oct(m.mode))

    def test_repack_is_byte_identical(self, tmp_path):
        capsule_dir = _make_sealed_capsule_dir(tmp_path, name="repack")
        a1 = pack_capsule(capsule_dir, output_path=tmp_path / "a1.capsule")
        a2 = pack_capsule(capsule_dir, output_path=tmp_path / "a2.capsule")
        assert a1.read_bytes() == a2.read_bytes()
