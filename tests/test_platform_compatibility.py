"""Pin the legacy platform boundary without importing or vendoring its code."""

import hashlib
import json
import shutil
from pathlib import Path

import yaml
from click.testing import CliRunner

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.cli.main import cli

FIXTURE = Path(__file__).parent / "fixtures/platform-legacy"


def test_legacy_platform_payload_checksums_do_not_imply_full_integrity():
    assert CapsuleVerifier.verify_checksums(FIXTURE)["status"] == "pass"
    result = CapsuleVerifier.verify_integrity(FIXTURE)
    assert result["status"] == "fail"
    assert not result["manifest_authenticated"]
    assert any("no checksums_digest" in error for error in result["errors"])
    validation = CapsuleValidator.validate_file(FIXTURE / "capsule.yaml")
    assert not validation["valid"]
    paths = {error["path"] for error in validation["errors"]}
    assert {
        "requirements",
        "checksums_digest",
        "task_executions/0/backend",
        "task_executions/0/status",
        "task_executions/0/result_type",
    } <= paths
    cli_result = CliRunner().invoke(cli, ["verify", str(FIXTURE), "--json"])
    assert cli_result.exit_code == 1
    assert json.loads(cli_result.output)["status"] == "fail"


def test_rewriting_legacy_manifest_and_checksums_does_not_upgrade_identity(tmp_path):
    target = tmp_path / "legacy"
    shutil.copytree(FIXTURE, target)
    manifest = target / "capsule.yaml"
    manifest.write_text(
        manifest.read_text().replace("synthetic-platform-bell", "different-experiment")
    )
    checksums = yaml.safe_load((target / ".checksums").read_text())
    checksums["capsule.yaml"] = "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    (target / ".checksums").write_text(yaml.safe_dump(checksums))
    assert CapsuleVerifier.verify_checksums(target)["status"] == "pass"
    assert CapsuleVerifier.verify_integrity(target)["status"] == "fail"


def test_explicit_new_record_can_preserve_legacy_result_bytes(tmp_path):
    # This is a synthetic mapping example, not a general migration adapter.
    # Production must obtain requirements/status/backend identity from its job
    # contract, not guess them from an arbitrary legacy backend label.
    old_bytes = (FIXTURE / "results.json").read_bytes()
    old = yaml.safe_load((FIXTURE / "capsule.yaml").read_text())
    execution = old["task_executions"][0]
    new = tmp_path / "new-record"
    new.mkdir()
    (new / "results.json").write_bytes(old_bytes)
    builder = CapsuleBuilder().start_capsule(
        name=old["name"],
        parameters=old["parameters"],
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
    )
    builder.add_task_execution(
        task_id=execution["task_id"],
        status="success",
        result_type="probabilistic",
        backend={"provider": "local", "name": "local_simulator", "shots": 1000},
        verification_settings={"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"},
        start_time=execution["start_time"],
        end_time=execution["end_time"],
    )
    trusted_id = builder.seal(new)
    assert CapsuleValidator.validate_file(new / "capsule.yaml")["valid"]
    assert CapsuleVerifier.verify_integrity(new, expected_id=trusted_id)["status"] == "pass"
    assert (new / "results.json").read_bytes() == old_bytes
    assert (FIXTURE / "results.json").read_bytes() == old_bytes
    assert "checksums_digest" not in old
