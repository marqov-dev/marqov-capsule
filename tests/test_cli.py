"""Tests for CLI tooling (Stage 2).

Uses subprocess to test the actual entry point behavior,
matching the testing strategy from D8.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

from marqov_capsule import CapsuleBuilder


def _run_capsule(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run the capsule CLI via python -m marqov_capsule."""
    return subprocess.run(
        [sys.executable, "-m", "marqov_capsule", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _make_sealed_capsule_dir(tmpdir: str, name: str = "cli-test") -> Path:
    """Create a sealed capsule directory on disk."""
    builder = CapsuleBuilder(name, description="CLI test capsule")
    builder.start_capsule(parameters={"x": 1})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 42})
    builder.seal_capsule(exit_code=0)
    capsule_dir = Path(tmpdir) / f"{name}.capsule"
    capsule_dir.mkdir()
    builder.save_capsule(str(capsule_dir / "capsule.yaml"))
    return capsule_dir


class TestCLIInit:
    """capsule init <name> scaffolds a new capsule directory."""

    def test_init_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_capsule("init", "my-analysis", "--output-dir", tmpdir)
            assert result.returncode == 0

            capsule_dir = Path(tmpdir) / "my-analysis.capsule"
            assert capsule_dir.is_dir()
            assert (capsule_dir / "capsule.yaml").exists()
            assert (capsule_dir / "workflow.yaml").exists()
            assert (capsule_dir / "environment.yaml").exists()
            assert (capsule_dir / "backends.yaml").exists()

    def test_init_capsule_yaml_is_valid_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_capsule("init", "my-analysis", "--output-dir", tmpdir)
            capsule_dir = Path(tmpdir) / "my-analysis.capsule"

            with open(capsule_dir / "capsule.yaml") as f:
                data = yaml.safe_load(f)

            assert data["name"] == "my-analysis"
            assert data["lifecycle_state"] == "draft"
            assert data["version"] == "1.0.0"

    def test_init_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = Path(tmpdir) / "exists.capsule"
            capsule_dir.mkdir()
            result = _run_capsule(
                "init", "exists", "--output-dir", tmpdir, check=False
            )
            assert result.returncode != 0
            assert "already exists" in result.stderr.lower()

    def test_init_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_capsule(
                "init", "json-test", "--output-dir", tmpdir, "--json"
            )
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert "path" in output
            assert output["name"] == "json-test"


class TestCLIVerify:
    """capsule verify <path> checks checksums and digest consistency."""

    def test_verify_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            result = _run_capsule("verify", str(capsule_dir))
            assert result.returncode == 0
            assert "PASS" in result.stdout.upper() or "pass" in result.stdout.lower()

    def test_verify_fail_tampered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(tmpdir)

            # Tamper
            capsule_yaml = capsule_dir / "capsule.yaml"
            with open(capsule_yaml, "a") as f:
                f.write("\n# tampered\n")

            result = _run_capsule("verify", str(capsule_dir), check=False)
            assert result.returncode != 0
            assert "FAIL" in result.stdout.upper() or "fail" in result.stdout.lower()

    def test_verify_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            result = _run_capsule("verify", str(capsule_dir), "--json")
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert "checksums" in output
            assert "verification" in output

    def test_verify_nonexistent_path(self):
        result = _run_capsule("verify", "/nonexistent/path", check=False)
        assert result.returncode != 0

    def test_verify_auto_method_from_tier(self):
        """Verify auto-selects method based on reproducibility_tier in capsule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = CapsuleBuilder(
                "auto-method",
                description="Auto method CLI test",
                reproducibility_tier="verification-only",
            )
            builder.start_capsule(parameters={})
            builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
            builder.seal_capsule(exit_code=0)
            capsule_dir = Path(tmpdir) / "auto.capsule"
            capsule_dir.mkdir()
            builder.save_capsule(str(capsule_dir / "capsule.yaml"))

            # check=False because verification-only may not fully pass
            # (e.g. missing 'tasks' section); we only care about method detection
            result = _run_capsule("verify", str(capsule_dir), "--json", check=False)
            output = json.loads(result.stdout)
            assert output["verification"]["method"] == "verification-only"


class TestCLISeal:
    """capsule seal <path> seals a draft capsule."""

    def test_seal_draft_capsule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init a draft capsule
            _run_capsule("init", "seal-test", "--output-dir", tmpdir)
            capsule_dir = Path(tmpdir) / "seal-test.capsule"

            result = _run_capsule("seal", str(capsule_dir))
            assert result.returncode == 0

            with open(capsule_dir / "capsule.yaml") as f:
                data = yaml.safe_load(f)
            assert data["lifecycle_state"] == "sealed"

    def test_seal_generates_lock_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_capsule("init", "lock-test", "--output-dir", tmpdir)
            capsule_dir = Path(tmpdir) / "lock-test.capsule"

            _run_capsule("seal", str(capsule_dir))
            assert (capsule_dir / "environment.lock.yaml").exists()

    def test_seal_already_sealed_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = _make_sealed_capsule_dir(tmpdir)
            result = _run_capsule("seal", str(capsule_dir), check=False)
            assert result.returncode != 0
            assert "already sealed" in result.stderr.lower()

    def test_seal_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_capsule("init", "json-seal", "--output-dir", tmpdir)
            capsule_dir = Path(tmpdir) / "json-seal.capsule"

            result = _run_capsule("seal", str(capsule_dir), "--json")
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert output["lifecycle_state"] == "sealed"


class TestCLIHelp:
    """CLI provides useful help text."""

    def test_help_flag(self):
        result = _run_capsule("--help")
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "verify" in result.stdout
        assert "seal" in result.stdout
        assert "pack" in result.stdout
        assert "unpack" in result.stdout

    def test_subcommand_help(self):
        for cmd in ["init", "verify", "seal", "pack", "unpack"]:
            result = _run_capsule(cmd, "--help")
            assert result.returncode == 0

    def test_no_args_shows_help(self):
        result = _run_capsule(check=False)
        # Should show help or error with usage
        assert result.returncode != 0 or "usage" in result.stdout.lower()
