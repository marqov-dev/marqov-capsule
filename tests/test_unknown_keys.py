"""Unknown manifest keys stay legal in v1 but are reported at seal (#112)."""

import json
from datetime import datetime

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule.cli.commands.seal import _dry_run_unknown_keys
from marqov_capsule.cli.main import cli
from marqov_capsule.validator import CapsuleValidator

REQUIREMENTS = {"paradigm": ["classical"], "max_qubit_count": 0}


def _draft(tmp_path, **extra):
    manifest = {
        "version": "1.0.0",
        "name": "t",
        "lifecycle_state": "draft",
        "requirements": REQUIREMENTS,
        **extra,
    }
    (tmp_path / "capsule.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return tmp_path


def _task(**extra):
    return {
        "task_id": "t1",
        "status": "success",
        "result_type": "deterministic",
        "backend": {"provider": "p", "name": "n", "shots": 1},
        **extra,
    }


def test_declared_and_free_form_keys_are_not_unknown():
    assert (
        CapsuleValidator.unknown_keys(
            {
                "version": "1.0.0",
                "parameters": {"anything": 1},
                "extensions": {"anything": 1},
                "digests": {"anything": None},
                "task_executions": [_task(metrics={"anything": 1}, signatures={"a": 1})],
            }
        )
        == []
    )


def test_unknown_keys_are_found_at_every_fixed_vocabulary_level():
    task = _task(queue_time=1, verification_settings={"ci_level": 0.9})
    task["backend"]["shotss"] = 1
    assert CapsuleValidator.unknown_keys({"derived_From": "x", "task_executions": [task]}) == [
        "derived_From",
        "task_executions/0/queue_time",
        "task_executions/0/backend/shotss",
        "task_executions/0/verification_settings/ci_level",
    ]


@pytest.mark.parametrize(
    "manifest",
    [None, [], "text", {"task_executions": "x"}, {"task_executions": [1, {"backend": 2}]}],
)
def test_malformed_shapes_are_left_to_the_schema(manifest):
    assert CapsuleValidator.unknown_keys(manifest) == []


def test_unknown_keys_do_not_make_a_manifest_invalid():
    manifest = {"version": "1.0.0", "name": "t", "lifecycle_state": "draft", "derived_From": "x"}
    assert CapsuleValidator.validate(manifest)["valid"] is True


def test_seal_warns_and_still_seals(tmp_path):
    result = CliRunner().invoke(cli, ["seal", str(_draft(tmp_path, derived_From="x"))])
    assert result.exit_code == 0, result.output
    assert "Sealed: mqc:1:" in result.output
    assert "derived_From" in result.stderr
    assert "were sealed" in result.stderr


def test_seal_is_silent_without_unknown_keys(tmp_path):
    result = CliRunner().invoke(cli, ["seal", str(_draft(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "Warning" not in result.stderr


def test_seal_json_names_unknown_keys(tmp_path):
    result = CliRunner().invoke(cli, ["seal", "--json", str(_draft(tmp_path, derived_From="x"))])
    assert json.loads(result.stdout)["unknown_keys"] == ["derived_From"]


def test_dry_run_warns_before_anything_is_sealed(tmp_path):
    capsule = _draft(tmp_path, derived_From="x")
    result = CliRunner().invoke(cli, ["seal", "--dry-run", str(capsule)])
    assert result.exit_code == 0, result.output
    assert "would be sealed" in result.stderr
    assert "no issues found" not in result.output
    assert not (capsule / ".checksums").exists()


def test_dry_run_json_names_unknown_keys(tmp_path):
    capsule = _draft(tmp_path, derived_From="x")
    result = CliRunner().invoke(cli, ["seal", "--dry-run", "--json", str(capsule)])
    assert json.loads(result.stdout)["unknown_keys"] == ["derived_From"]


def test_dry_run_check_treats_an_unparseable_manifest_as_having_no_unknown_keys(tmp_path):
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text("a: [", encoding="utf-8")
    assert _dry_run_unknown_keys(manifest) == []


def test_init_records_created_at(tmp_path):
    capsule = tmp_path / "c"
    result = CliRunner().invoke(cli, ["init", str(capsule)])
    assert result.exit_code == 0, result.output
    manifest = yaml.safe_load((capsule / "capsule.yaml").read_text(encoding="utf-8"))
    stamp = manifest["created_at"]
    assert stamp.endswith("Z")
    assert datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo
    assert CapsuleValidator.validate(manifest)["valid"] is True
