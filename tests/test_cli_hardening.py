"""CLI robustness on hand-edited drafts and operator input (#95, #97, #99, #109)."""

import json

import pytest
from click.testing import CliRunner

from marqov_capsule._canonical import load_manifest_yaml
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli
from marqov_capsule.policy import VerificationPolicy

REQUIREMENTS = {"paradigm": ["gate-based"], "max_qubit_count": 2}
DRAFT_HEAD = (
    "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
    "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
)


def _sealed(tmp_path, name="mycap"):
    d = tmp_path / name
    d.mkdir()
    (d / "payload.txt").write_text("x\n")
    CapsuleBuilder().start_capsule(name=name, requirements=REQUIREMENTS).seal(d)
    return d


# --- #97 ----------------------------------------------------------------------


def test_open_dot_with_dest_uses_the_real_directory_name(tmp_path, monkeypatch):
    d = _sealed(tmp_path)
    monkeypatch.chdir(d)
    dest = tmp_path / "out"
    result = CliRunner().invoke(cli, ["open", ".", "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    assert (dest / "mycap" / "capsule.yaml").is_file()
    assert "mycap" in result.output


def test_open_dotdot_with_dest_uses_the_real_directory_name(tmp_path, monkeypatch):
    d = _sealed(tmp_path)
    inner = d / "payload"
    inner.mkdir()
    (inner / "note.txt").write_text("n\n")
    # Reseal is a one-way door; build a fresh sealed capsule with the subdir.
    d2 = tmp_path / "second"
    d2.mkdir()
    (d2 / "sub").mkdir()
    (d2 / "sub" / "f.txt").write_text("f\n")
    CapsuleBuilder().start_capsule(name="second", requirements=REQUIREMENTS).seal(d2)
    monkeypatch.chdir(d2 / "sub")
    dest = tmp_path / "out2"
    result = CliRunner().invoke(cli, ["open", "..", "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    assert (dest / "second" / "capsule.yaml").is_file()


# --- #99 ----------------------------------------------------------------------


@pytest.fixture
def counts_files(tmp_path):
    ref = tmp_path / "ref.json"
    new = tmp_path / "new.json"
    ref.write_text(json.dumps({"00": 500, "11": 500}))
    new.write_text(json.dumps({"00": 500, "11": 500}))
    return str(ref), str(new)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--alpha", "5"),
        ("--alpha", "0"),
        ("--alpha", "1"),
        ("--alpha", "-0.1"),
        ("--epsilon", "-1"),
        ("--epsilon", "0"),
        ("--epsilon", "5"),
        ("--epsilon", "1"),
        ("--min-shots", "0"),
        ("--min-shots", "-5"),
    ],
)
def test_compare_rejects_out_of_range_thresholds_as_usage_errors(flag, value, counts_files):
    result = CliRunner().invoke(cli, ["compare", *counts_files, flag, value])
    assert result.exit_code == 2, result.output
    assert flag in result.output
    assert "alpha:    0.05" not in result.output


def test_compare_in_range_thresholds_are_accepted(counts_files):
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    result = CliRunner().invoke(
        cli, ["compare", *counts_files, "--alpha", "0.1", "--epsilon", "0.5", "--min-shots", "1"]
    )
    assert result.exit_code in (0, 3), result.output


@pytest.mark.parametrize(
    "kwargs",
    [
        {"epsilon": 0.0},
        {"epsilon": -1.0},
        {"epsilon": 1.0},
        {"epsilon": 1.5},
        {"epsilon_drift": 0.0},
        {"epsilon_drift": 1.0},
        {"epsilon_drift": 2.0},
        {"min_shots": 0},
        {"min_shots": -1},
        {"alpha": 0.0},
        {"alpha": 1.0},
        {"alpha": 5.0},
    ],
)
def test_policy_rejects_out_of_range_thresholds(kwargs):
    with pytest.raises(ValueError):
        VerificationPolicy(**kwargs)


def test_policy_accepts_the_documented_range():
    VerificationPolicy(epsilon=0.999, epsilon_drift=0.999, min_shots=1, alpha=0.999)


# --- #109 ---------------------------------------------------------------------


def test_init_hint_names_the_directory_given(tmp_path):
    target = tmp_path / "mycap"
    result = CliRunner().invoke(cli, ["init", str(target)])
    assert result.exit_code == 0, result.output
    assert f"marqov-capsule seal {target}" in result.output


def test_init_hint_for_dot_stays_dot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["init", "."])
    assert result.exit_code == 0, result.output
    assert "marqov-capsule seal ." in result.output


def test_init_paradigm_help_lists_classical():
    result = CliRunner().invoke(cli, ["init", "--help"])
    assert "classical" in result.output


def test_readme_cli_table_has_a_compare_row():
    from pathlib import Path

    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    assert "| `marqov-capsule compare` |" in readme


# --- #95: from_manifest on hand-edited drafts --------------------------------


def test_seal_treats_null_task_executions_as_empty(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "capsule.yaml").write_text(DRAFT_HEAD + "task_executions:\n")
    result = CliRunner().invoke(cli, ["seal", str(d)])
    assert result.exit_code == 0, result.output
    sealed = load_manifest_yaml((d / "capsule.yaml").read_text(encoding="utf-8"))
    assert sealed["task_executions"] == []
    assert sealed["lifecycle_state"] == "sealed"


@pytest.mark.parametrize(
    "draft",
    [
        DRAFT_HEAD + "task_executions: 5\n",
        DRAFT_HEAD + "task_executions: {a: 1}\n",
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\nrequirements: [gate-based]\ntask_executions: []\n",
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\nrequirements: 7\ntask_executions: []\n",
        DRAFT_HEAD + "task_executions: []\ndigests: 3\n",
    ],
)
def test_seal_rejects_wrongly_typed_containers_cleanly(draft, tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "capsule.yaml").write_text(draft)
    result = CliRunner().invoke(cli, ["seal", str(d)])
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert "Error:" in result.output
    assert not (d / ".checksums").exists()


@pytest.mark.parametrize(
    "draft",
    [
        DRAFT_HEAD + "task_executions: 5\n",
        DRAFT_HEAD + "task_executions:\n",
        DRAFT_HEAD + "task_executions: []\nderived_from: 5\n",
        DRAFT_HEAD + "task_executions: []\nchecksums_digest: 12\n",
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\nrequirements: 7\n",
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\ntask_executions: [1, 'x', null]\n",
    ],
)
def test_inspect_never_tracebacks_on_odd_but_parsable_drafts(draft, tmp_path):
    (tmp_path / "capsule.yaml").write_text(draft)
    result = CliRunner().invoke(cli, ["inspect", str(tmp_path)])
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert result.exit_code == 0, result.output
