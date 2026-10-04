"""Regression tests for verify/open bug fixes.

Covers:
  #54 — arbitrary file read via a symlinked *parent* directory
  #56 — non-regular files (FIFO/socket/device) bypass the closed-set check
  #60 — `verify .` / `open .` false tamper alarm on an untampered capsule
  #58 — verify --json / open must surface the manifest-authentication state,
        and open must fail cleanly (no traceback) on a non-regular capsule
  #61 — malformed .checksums and un-canonicalisable manifests must yield a
        FAIL verdict, never an uncaught traceback
"""
import hashlib
import json
import os

import pytest
import yaml

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.verifier import CapsuleVerifier


def _seal(capsule_dir) -> str:
    """Seal a realistic capsule. Returns the capsule ID reported at seal time."""
    capsule_dir.mkdir(parents=True, exist_ok=True)
    counts = {"00": 512, "11": 512}
    payload = capsule_dir / "payload"
    payload.mkdir(exist_ok=True)
    (payload / "results.json").write_text(
        json.dumps({"counts": counts, "shots": sum(counts.values())})
    )
    source = capsule_dir / "source"
    source.mkdir(exist_ok=True)
    (source / "circuit.qasm").write_text("OPENQASM 3.0;\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n")

    b = CapsuleBuilder()
    b.start_capsule(name="Bell", requirements={"paradigm": ["gate-based"], "max_qubit_count": 2})
    b.add_task_execution(
        task_id="550e8400-e29b-41d4-a716-446655440000",
        status="success",
        result_type="probabilistic",
        backend={"provider": "ibm", "name": "ibm_kyiv", "shots": 1024},
        verification_settings={"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"},
    )
    return b.seal(capsule_dir=capsule_dir, sealed_by="test-runner")


# --- #54: arbitrary file read via a symlinked parent directory --------------

def test_verify_checksums_rejects_symlinked_parent_dir(tmp_path):
    """A .checksums key whose *parent* is a symlink out of the capsule must
    NOT be read/hashed (offline file-read oracle)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "id_rsa"
    secret.write_text("PRIVATE KEY CONTENT")
    secret_digest = "sha256:" + hashlib.sha256(secret.read_bytes()).hexdigest()

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    # stash/ is a symlink to a directory OUTSIDE the capsule; the final path
    # component (id_rsa) is a real file, so is_symlink() on it is False.
    (capsule_dir / "stash").symlink_to(outside, target_is_directory=True)
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"stash/id_rsa": secret_digest}, sort_keys=True)
    )

    result = CapsuleVerifier.verify_checksums(capsule_dir)

    assert result["status"] == "fail"
    # The verifier must not have read & hashed the outside file.
    assert result["files"]["stash/id_rsa"]["actual"] is None
    assert result["files"]["stash/id_rsa"]["match"] is False


# --- #56: non-regular files bypass the closed-set injected-file check --------

def test_injected_fifo_fails_verification(tmp_path):
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    f = payload / "results.json"
    f.write_text('{"counts": {"00": 1}}')
    digest = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"payload/results.json": digest}, sort_keys=True)
    )

    assert CapsuleVerifier.verify_checksums(capsule_dir)["status"] == "pass"

    if not hasattr(os, "mkfifo"):
        pytest.skip("this platform has no FIFOs")
    os.mkfifo(payload / "backdoor")
    result = CapsuleVerifier.verify_checksums(capsule_dir)

    assert result["status"] == "fail"
    assert "payload/backdoor" in result["extra"]


def test_injected_fifo_fails_full_integrity(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)
    if not hasattr(os, "mkfifo"):
        pytest.skip("this platform has no FIFOs")
    os.mkfifo(capsule_dir / "payload" / "backdoor")

    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)
    assert result["status"] == "fail"


# --- #60: verify . false tamper alarm on an untampered capsule --------------

def test_verify_checksums_dot_path_untampered_passes(tmp_path, monkeypatch):
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    f = payload / "results.json"
    f.write_text('{"counts": {"00": 500}}')
    digest = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"payload/results.json": digest}, sort_keys=True)
    )

    # Absolute path already works.
    assert CapsuleVerifier.verify_checksums(capsule_dir)["status"] == "pass"

    # The advertised `verify .` workflow must also pass.
    monkeypatch.chdir(capsule_dir)
    result = CapsuleVerifier.verify_checksums(".")
    assert result["status"] == "pass"
    for rel, info in result["files"].items():
        assert info["match"] is True, (rel, info)


def test_cli_verify_dot_path_passes(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    monkeypatch.chdir(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", "."])
    assert result.exit_code == 0, result.output


# --- #58: surface authentication state in JSON and on open ------------------

def test_verify_json_unauthenticated_has_warning(tmp_path):
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)  # sealed but no --id -> manifest unauthenticated

    result = CliRunner().invoke(cli, ["verify", "--json", str(capsule_dir)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "pass"
    assert data["manifest_authenticated"] is False
    assert data.get("warning"), "unauthenticated verify --json must carry a warning field"


def test_open_json_surfaces_authentication_warning(tmp_path):
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    dest = tmp_path / "out"

    result = CliRunner().invoke(
        cli, ["open", "--json", str(capsule_dir), "--dest", str(dest)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data.get("warning"), "unauthenticated open --json must carry a warning field"


def test_open_on_nonregular_capsule_fails_cleanly(tmp_path):
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)
    if not hasattr(os, "mkfifo"):
        pytest.skip("this platform has no FIFOs")
    os.mkfifo(capsule_dir / "payload" / "backdoor")
    dest = tmp_path / "out"

    result = CliRunner().invoke(
        cli, ["open", "--id", sealed_id, str(capsule_dir), "--dest", str(dest)]
    )
    assert result.exit_code == 1
    # Clean failure — no uncaught traceback (e.g. shutil.Error).
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        result.exception
    )


# --- #61: hostile input yields a FAIL verdict, not a traceback --------------

def test_malformed_legacy_checksums_fails_not_crashes(tmp_path):
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    # Parses as a YAML scalar (not a mapping) -> legacy "digest  path" parser;
    # the line has no double-space separator, so split unpacking would raise.
    (capsule_dir / ".checksums").write_text("garbage-with-no-separator")

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"


def test_uncanonicalisable_manifest_fails_not_crashes(tmp_path):
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    # A manifest that parses as a dict but cannot be RFC 8785 canonicalised
    # (NaN is rejected by jcs) — compute_capsule_id would raise ValueError.
    (capsule_dir / "capsule.yaml").write_text("name: forged\nbogus: .nan\n")

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail"  # a verdict, not an exception
