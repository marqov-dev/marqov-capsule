"""Tests for CLI pack/unpack commands and verify-on-archive (Task 2).

Uses subprocess to test the actual entry point behavior,
matching the existing test_cli.py testing strategy.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder
from marqov_capsule.archive import pack_capsule


def _run_capsule(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run the capsule CLI via python -m marqov_capsule."""
    return subprocess.run(
        [sys.executable, "-m", "marqov_capsule", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _make_sealed_capsule_dir(parent: Path, name: str = "cli-archive-test") -> Path:
    """Create a sealed capsule directory on disk."""
    builder = CapsuleBuilder(name, description="CLI archive test capsule")
    builder.start_capsule(parameters={"x": 1})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 42})
    builder.seal_capsule(exit_code=0)
    capsule_dir = parent / f"{name}.capsule"
    capsule_dir.mkdir()
    builder.save_capsule(str(capsule_dir / "capsule.yaml"))
    return capsule_dir


class TestCLIPack:
    """capsule pack <directory> creates a .capsule archive."""

    def test_cli_pack(self):
        """capsule pack on a sealed capsule dir exits 0 and creates archive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            output_path = Path(tmpdir) / "packed.capsule"
            result = _run_capsule(
                "pack", str(capsule_dir), "--output", str(output_path)
            )
            assert result.returncode == 0
            assert output_path.exists()

    def test_cli_pack_json(self):
        """--json output from capsule pack contains path and content_id keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(Path(tmpdir))
            output_path = Path(tmpdir) / "packed.capsule"
            result = _run_capsule(
                "pack", str(capsule_dir), "--output", str(output_path), "--json"
            )
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert "path" in output
            assert "content_id" in output
            assert output["content_id"].startswith("sha256:")


class TestCLIUnpack:
    """capsule unpack <archive> extracts a capsule archive."""

    def test_cli_unpack(self):
        """capsule unpack restores a directory from an archive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )

            out_dir = tmpdir / "unpacked"
            out_dir.mkdir()
            result = _run_capsule(
                "unpack", str(archive_path), "--output-dir", str(out_dir)
            )
            assert result.returncode == 0

            # The restored capsule directory should exist
            restored = out_dir / capsule_dir.name
            assert restored.is_dir()
            assert (restored / "capsule.yaml").exists()

    def test_cli_unpack_json(self):
        """--json output from capsule unpack contains path key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )

            out_dir = tmpdir / "unpacked"
            out_dir.mkdir()
            result = _run_capsule(
                "unpack", str(archive_path), "--output-dir", str(out_dir), "--json"
            )
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert "path" in output


class TestCLIVerifyArchive:
    """capsule verify on .capsule archive files."""

    def test_cli_verify_archive(self):
        """capsule verify on a .capsule archive file works (exit code 0)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )

            result = _run_capsule("verify", str(archive_path))
            assert result.returncode == 0

    def test_cli_verify_archive_json(self):
        """--json output on archive includes content_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            archive_path = pack_capsule(
                capsule_dir, output_path=tmpdir / "test.capsule"
            )

            result = _run_capsule("verify", str(archive_path), "--json")
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert "content_id" in output
            assert output["content_id"].startswith("sha256:")
            assert output["passed"] is True

    def test_cli_pack_unpack_verify_roundtrip(self):
        """Full end-to-end: pack -> unpack -> verify on unpacked directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            capsule_dir = _make_sealed_capsule_dir(tmpdir)

            # Pack
            archive_path = tmpdir / "roundtrip.capsule"
            result = _run_capsule(
                "pack", str(capsule_dir), "--output", str(archive_path), "--json"
            )
            assert result.returncode == 0
            pack_output = json.loads(result.stdout)
            original_content_id = pack_output["content_id"]

            # Unpack
            unpack_dir = tmpdir / "unpacked"
            unpack_dir.mkdir()
            result = _run_capsule(
                "unpack", str(archive_path), "--output-dir", str(unpack_dir), "--json"
            )
            assert result.returncode == 0
            unpack_output = json.loads(result.stdout)
            restored_path = unpack_output["path"]

            # Verify unpacked directory
            result = _run_capsule("verify", restored_path, "--json")
            assert result.returncode == 0
            verify_output = json.loads(result.stdout)
            assert verify_output["passed"] is True
            assert verify_output["content_id"] == original_content_id
