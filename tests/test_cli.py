from pathlib import Path
import pytest
from click.testing import CliRunner
from marqov_capsule.cli.main import cli

FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


def test_validate_valid_capsule_exits_0():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURE_DIR / "valid_capsule/capsule.yaml")])
    assert result.exit_code == 0


def test_validate_invalid_capsule_exits_1():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURE_DIR / "invalid_capsule/capsule.yaml")])
    assert result.exit_code == 1


def test_validate_json_output():
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--json", str(FIXTURE_DIR / "valid_capsule/capsule.yaml")])
    import json
    data = json.loads(result.output)
    assert "valid" in data


def test_validate_accepts_directory():
    # Consistent with inspect/verify/seal: passing the capsule directory
    # should resolve capsule.yaml inside it.
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURE_DIR / "valid_capsule")])
    assert result.exit_code == 0, result.output


def test_validate_directory_without_manifest_errors_cleanly(tmp_path):
    # An existing directory with no capsule.yaml must produce a clean error
    # and exit 1 — never an unhandled IsADirectoryError traceback.
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert not isinstance(result.exception, IsADirectoryError), result.output
    assert "capsule.yaml" in result.output


def test_inspect_shows_name():
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", str(FIXTURE_DIR / "valid_capsule")])
    assert result.exit_code == 0
    assert "Bell State" in result.output


def test_inspect_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["inspect", "--json", str(FIXTURE_DIR / "valid_capsule")])
    assert result.exit_code == 0
    import json
    data = json.loads(result.output)
    assert data["name"] == "Bell State Preparation"


def test_verify_valid_capsule_exits_0():
    runner = CliRunner()
    result = runner.invoke(cli, ["verify", str(FIXTURE_DIR / "valid_capsule")])
    assert result.exit_code == 0, result.output


def test_seal_dry_run_clean_capsule(tmp_path):
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: test\nlifecycle_state: draft\ntask_executions: []\n"
    )
    (tmp_path / "circuit.py").write_text("from qiskit import QuantumCircuit\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["seal", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0
    assert "no issues" in result.output


def test_seal_dry_run_detects_secrets_exits_0(tmp_path):
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: test\nlifecycle_state: draft\ntask_executions: []\n"
    )
    (tmp_path / "run.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    runner = CliRunner()
    result = runner.invoke(cli, ["seal", "--dry-run", str(tmp_path)])
    assert result.exit_code == 0, f"dry-run must not exit 1; got: {result.output}"
    assert "credential" in result.output.lower() or "warning" in result.output.lower() or "credential pattern" in result.output.lower()


def test_seal_blocks_secrets_exits_1(tmp_path):
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: test\nlifecycle_state: draft\ntask_executions: []\n"
    )
    (tmp_path / "run.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    runner = CliRunner()
    result = runner.invoke(cli, ["seal", str(tmp_path)])
    assert result.exit_code == 1


def test_seal_actually_seals(tmp_path):
    import yaml
    (tmp_path / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: test-capsule\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 1\n"
        "task_executions: []\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["seal", "--sealed-by", "test-runner", str(tmp_path)])
    assert result.exit_code == 0, result.output
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml((tmp_path / "capsule.yaml").read_text())
    assert manifest["lifecycle_state"] == "sealed"
    assert manifest.get("checksums_digest", "").startswith("sha256:")
    assert (tmp_path / ".checksums").exists()
    # Output contains 64-char capsule ID after "Sealed: "
    sealed_line = [l for l in result.output.splitlines() if l.startswith("Sealed:")]
    assert sealed_line, f"No 'Sealed:' line in output: {result.output}"
    capsule_id = sealed_line[0].split("Sealed: ")[-1].strip()
    assert capsule_id.startswith("mqc:1:") and len(capsule_id.split(":")[-1]) == 64, f"Expected mqc:1:<64hex> ID, got: {capsule_id!r}"


def test_init_creates_draft_manifest(tmp_path):
    new_dir = tmp_path / "my-capsule"
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(new_dir)])
    assert result.exit_code == 0, result.output
    manifest_path = new_dir / "capsule.yaml"
    assert manifest_path.exists()
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml(manifest_path.read_text())
    assert manifest["lifecycle_state"] == "draft"
    assert manifest["name"] == "my-capsule"


def test_init_respects_name_flag(tmp_path):
    new_dir = tmp_path / "capsule-dir"
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--name", "custom-name", str(new_dir)])
    assert result.exit_code == 0
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml((new_dir / "capsule.yaml").read_text())
    assert manifest["name"] == "custom-name"


def test_init_refuses_overwrite_without_force(tmp_path):
    (tmp_path / "capsule.yaml").write_text("existing: true\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 1


def test_init_paradigm_and_qubits_flags(tmp_path):
    new_dir = tmp_path / "cap"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "init", "--name", "bell", "--paradigm", "gate-based", "--qubits", "2", str(new_dir)
    ])
    assert result.exit_code == 0, result.output
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml((new_dir / "capsule.yaml").read_text())
    assert manifest["requirements"]["paradigm"] == ["gate-based"]
    assert manifest["requirements"]["max_qubit_count"] == 2


def test_init_multiple_paradigms(tmp_path):
    new_dir = tmp_path / "cap"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "init", "--paradigm", "gate-based", "--paradigm", "analog", str(new_dir)
    ])
    assert result.exit_code == 0, result.output
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml((new_dir / "capsule.yaml").read_text())
    assert "gate-based" in manifest["requirements"]["paradigm"]
    assert "analog" in manifest["requirements"]["paradigm"]


def test_open_rejects_capsule_with_symlink(tmp_path):
    """`open` must refuse a capsule containing a symlink and must not materialize
    the symlink target's content into the destination (#32)."""
    import hashlib, yaml
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY CONTENT")

    capsule_dir = tmp_path / "evil.capsule"
    (capsule_dir / "payload").mkdir(parents=True)
    real = capsule_dir / "payload" / "results.json"
    real.write_text('{"counts": {"00": 1}}')
    digest = "sha256:" + hashlib.sha256(real.read_bytes()).hexdigest()
    (capsule_dir / "payload" / "link.txt").symlink_to(secret)
    (capsule_dir / ".checksums").write_text(yaml.dump({"payload/results.json": digest}, sort_keys=True))

    dest = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(cli, ["open", str(capsule_dir), "--dest", str(dest)])
    assert result.exit_code == 1, result.output
    copied = dest / "evil.capsule" / "payload" / "link.txt"
    if copied.exists() and not copied.is_symlink():
        assert copied.read_text() != "PRIVATE KEY CONTENT"



# --- Statistical equivalence is not in 0.1.0 (#15) --------------------------

def test_verify_has_no_against_option():
    """`--against` is cut from 0.1.0: the estimator is miscalibrated and returns
    REJECTED on identical distributions above ~2 qubits. Tracked in #15."""
    runner = CliRunner()
    result = runner.invoke(cli, ["verify", "--against", ".", "."])
    assert result.exit_code != 0
    assert "no such option" in result.output.lower(), result.output


def test_verify_help_does_not_advertise_statistical_equivalence():
    result = CliRunner().invoke(cli, ["verify", "--help"])
    out = result.output.lower()
    assert "statistical" not in out, result.output
    assert "epsilon" not in out, result.output
