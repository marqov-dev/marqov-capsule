from pathlib import Path
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
    assert len(capsule_id) == 64, f"Expected 64-char ID, got: {capsule_id!r}"


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


def test_verify_against_identical_capsules(tmp_path):
    import json, yaml
    counts = {"00": 5000, "11": 5000}
    vsettings = {"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"}
    for name in ("ref", "new"):
        d = tmp_path / name
        (d / "payload").mkdir(parents=True)
        (d / "payload" / "results.json").write_text(json.dumps({"counts": counts}))
        (d / "capsule.yaml").write_text(yaml.safe_dump({
            "version": "1.0.0", "name": name, "lifecycle_state": "sealed",
            "task_executions": [{
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "success",
                "result_type": "probabilistic",
                "backend": {"provider": "ibm", "name": "ibm_kyiv", "shots": 10000},
                "verification_settings": vsettings,
            }],
        }))
    runner = CliRunner()
    result = runner.invoke(cli, [
        "verify", "--against", str(tmp_path / "ref"),
        "--json", str(tmp_path / "new"),
    ])
    data = json.loads(result.output)
    assert data["verdict"] == "VERIFIED"
