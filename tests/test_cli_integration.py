"""End-to-end CLI test: init -> seal -> verify."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "marqov_capsule", *args],
        capture_output=True, text=True,
    )


def test_init_seal_verify_roundtrip():
    """Full CLI round-trip: init -> seal -> verify."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init
        result = _run("init", "roundtrip-cli", "--output-dir", tmpdir)
        assert result.returncode == 0, result.stderr

        capsule_dir = Path(tmpdir) / "roundtrip-cli.capsule"
        assert capsule_dir.is_dir()

        # Check draft state
        with open(capsule_dir / "capsule.yaml") as f:
            data = yaml.safe_load(f)
        assert data["lifecycle_state"] == "draft"

        # Seal
        result = _run("seal", str(capsule_dir))
        assert result.returncode == 0, result.stderr

        # Check sealed state
        with open(capsule_dir / "capsule.yaml") as f:
            data = yaml.safe_load(f)
        assert data["lifecycle_state"] == "sealed"
        assert (capsule_dir / "environment.lock.yaml").exists()
        assert (capsule_dir / ".checksums").exists()

        # Verify
        result = _run("verify", str(capsule_dir))
        assert result.returncode == 0, result.stderr
        assert "pass" in result.stdout.lower()


def test_init_seal_verify_json():
    """Full round-trip with --json output at each step."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init with JSON
        result = _run("init", "json-round", "--output-dir", tmpdir, "--json")
        assert result.returncode == 0
        init_out = json.loads(result.stdout)
        assert init_out["name"] == "json-round"

        capsule_dir = Path(tmpdir) / "json-round.capsule"

        # Seal with JSON
        result = _run("seal", str(capsule_dir), "--json")
        assert result.returncode == 0
        seal_out = json.loads(result.stdout)
        assert seal_out["lifecycle_state"] == "sealed"

        # Verify with JSON
        result = _run("verify", str(capsule_dir), "--json")
        assert result.returncode == 0
        verify_out = json.loads(result.stdout)
        assert verify_out["passed"] is True


def test_verify_detects_tampering_after_seal():
    """Init -> seal -> tamper -> verify should fail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _run("init", "tamper-cli", "--output-dir", tmpdir)
        capsule_dir = Path(tmpdir) / "tamper-cli.capsule"
        _run("seal", str(capsule_dir))

        # Tamper
        capsule_yaml = capsule_dir / "capsule.yaml"
        with open(capsule_yaml, "a") as f:
            f.write("\n# tampered\n")

        result = _run("verify", str(capsule_dir))
        assert result.returncode != 0
