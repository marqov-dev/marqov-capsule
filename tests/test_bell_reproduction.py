"""Test the independent oracle against meaningful wrong and missing evidence."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "tools/reproduction"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oracle = load("oracle")
runner = load("run_bell_reproduction")


def symlink_or_skip(link, target):
    """Windows runners may lack symlink privilege; do not hide other errors."""
    try:
        link.symlink_to(target)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows runner lacks symlink creation privilege")
        raise


def result(counts):
    return {"counts": counts, "shots": 1000, "seed": 42, "backend": "local"}


@pytest.mark.parametrize("n", [420, 500, 580])
def test_fixed_analytic_acceptance(n):
    assert (
        oracle.check(result({"00": n, "11": 1000 - n}), oracle.CIRCUIT, oracle.REFERENCE)["status"]
        == "pass"
    )


@pytest.mark.parametrize(
    "counts",
    [
        {"00": 1000},
        {"00": 419, "11": 581},
        {"00": 581, "11": 419},
        {"00": 499, "11": 500, "01": 1},
        {"00": 500.0, "11": 500},
        {"00": True, "11": 999},
        {"00": -1, "11": 1001},
        {"00": 500, "11": 499},
        {"00": 500, "bad": 500},
        {},
    ],
)
def test_wrong_counts_fail(counts):
    with pytest.raises(ValueError):
        oracle.check(result(counts), oracle.CIRCUIT, oracle.REFERENCE)


def test_wrong_circuit_and_reference_fail():
    for circuit, reference in [({"gates": []}, oracle.REFERENCE), (oracle.CIRCUIT, {})]:
        with pytest.raises(ValueError):
            oracle.check(result({"00": 500, "11": 500}), circuit, reference)


def test_missing_reference_fails_before_simulator(tmp_path):
    kit = tmp_path / "kit"
    kit.mkdir()
    evidence = tmp_path / "evidence"
    report = runner.run(kit, evidence)
    assert report["status"] == "fail"
    assert report["stage"] == "preflight"
    assert report["simulator_invocations"] == 0
    assert report["error"] == "MISSING_REQUIRED_INPUT:reference.json"
    assert json.loads((evidence / "report.json").read_text()) == report


def test_existing_evidence_is_not_overwritten(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(FileExistsError):
        runner.run(tmp_path / "kit", evidence)


freezer = load("freeze_bell_kit")


@pytest.fixture
def frozen_kit(tmp_path):
    kit = tmp_path / "kit"
    kit.mkdir()
    for name in ("requirements.txt", "run_bell.py", "seal_bell.py"):
        (kit / name).write_text("synthetic test fixture\n")
    (kit / "environment.json").write_text(
        json.dumps({"packages": {"marqov": "0.5.1", "marqov-capsule": "0.2.3"}})
    )
    trusted = freezer.freeze(kit, "synthetic-test-source")
    return kit, trusted


def refreeze(kit):
    """Model an adversary rewriting their own inventory, not a trusted re-freeze."""
    path = kit / "freeze.json"
    data = json.loads(path.read_text())
    data["files"] = {
        p.relative_to(kit).as_posix(): runner.digest(p)
        for p in kit.rglob("*")
        if p.is_file() and p != path
    }
    runner.write(path, data)
    return runner.digest(path)


def test_valid_freeze_and_refuse_overwrite(frozen_kit):
    kit, trusted = frozen_kit
    assert runner.preflight(kit, trusted)["source_ref"] == "synthetic-test-source"
    with pytest.raises(ValueError, match="REFUSE_TO_OVERWRITE_FREEZE"):
        freezer.freeze(kit, "new")


def test_rewritten_inventory_does_not_replace_external_trust(frozen_kit):
    kit, trusted = frozen_kit
    (kit / "run_bell.py").write_text("changed experiment")
    new_digest = refreeze(kit)
    assert new_digest != trusted
    with pytest.raises(ValueError, match="UNTRUSTED_FREEZE_HASH"):
        runner.preflight(kit, trusted)


@pytest.mark.parametrize("action", ["change", "extra", "nested-freeze", "symlink", "interpreter"])
def test_preflight_rejects_drift(frozen_kit, action):
    kit, trusted = frozen_kit
    if action == "change":
        (kit / "run_bell.py").write_text("changed")
    elif action == "extra":
        (kit / "extra.py").write_text("injected")
    elif action == "nested-freeze":
        (kit / "nested").mkdir()
        (kit / "nested/freeze.json").write_text("unlisted")
    elif action == "symlink":
        symlink_or_skip(kit / "link", kit / "reference.json")
    else:
        data = json.loads((kit / "freeze.json").read_text())
        data["interpreter_sha256"] = "0" * 64
        runner.write(kit / "freeze.json", data)
        trusted = runner.digest(kit / "freeze.json")
    with pytest.raises(ValueError):
        runner.preflight(kit, trusted)


@pytest.mark.parametrize("kind", ["reference", "circuit"])
def test_boolean_and_float_contract_values_do_not_equal_integers(kind):
    circuit, reference = json.loads(json.dumps(oracle.CIRCUIT)), dict(oracle.REFERENCE)
    if kind == "reference":
        reference["shots"] = 1000.0
    else:
        circuit["gates"][0]["qubits"] = [False]
    with pytest.raises(ValueError):
        oracle.check(result({"00": 500, "11": 500}), circuit, reference)


def test_no_evidence_written_into_or_around_kit(frozen_kit):
    kit, trusted = frozen_kit
    for path in (kit, kit / "evidence", kit.parent):
        with pytest.raises(ValueError, match="DISJOINT"):
            runner.run(kit, path, trusted)


def test_missing_reference_keeps_original_freeze(frozen_kit, tmp_path):
    kit, trusted = frozen_kit
    (kit / "reference.json").unlink()
    report = runner.run(kit, tmp_path / "evidence", trusted)
    assert report["error"] == "MISSING_REQUIRED_INPUT:reference.json"
    assert report["stage"] == "preflight" and report["simulator_invocations"] == 0


@pytest.mark.parametrize("code,stdout", [(0, "1\n"), (0, ""), (2, ""), (3, "")])
def test_network_probe_requires_explicit_policy_denial(monkeypatch, code, stdout):
    from types import SimpleNamespace

    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=code, stdout=stdout, stderr="diagnostic"),
    )
    if code == 0 and stdout == "1\n":
        assert runner.offline_probe()["status"] == "pass"
    else:
        with pytest.raises(RuntimeError, match="NETWORK_DENIAL_NOT_PROVEN"):
            runner.offline_probe()


@pytest.mark.parametrize(
    "failure", [None, "NONZERO_EXIT", "DISK_CAP", "EVIDENCE_CAP", "TIME_CAP", "MEMORY_CAP"]
)
@pytest.mark.skipif(
    not hasattr(os, "killpg"), reason="POSIX process-group watchdog; macOS pilot only"
)
def test_watchdog_records_and_cleans_up(monkeypatch, tmp_path, failure):
    """Exercise short-lived exits and running-process caps without real large allocations."""

    class Process:
        pid = 424242
        returncode = 1 if failure == "NONZERO_EXIT" else 0

        def poll(self):
            return None if failure in ("MEMORY_CAP", "TIME_CAP") else self.returncode

        def wait(self):
            return self.returncode

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: "424242 10\n")
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    killed = []
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(runner, "MAX_RSS", 1 if failure == "MEMORY_CAP" else 100000)
    monkeypatch.setattr(runner, "MAX_DISK", 1 if failure == "DISK_CAP" else 100000)
    monkeypatch.setattr(runner, "MAX_EVIDENCE", 1 if failure == "EVIDENCE_CAP" else 100000)
    monkeypatch.setattr(runner, "disk_bytes", lambda _: 10)
    if failure:
        with pytest.raises(RuntimeError):
            runner.stage(
                "control", ["synthetic"], tmp_path, {}, -1 if failure == "TIME_CAP" else 60
            )
    else:
        runner.stage("control", ["synthetic"], tmp_path, {}, 60)
    receipt = json.loads((tmp_path / "control.receipt.json").read_text())
    assert receipt["cap_failure"] == failure
    assert receipt["network_policy"] == "sandbox deny network*"
    assert killed == [424242]


def test_complete_report_requires_both_actual_exports(frozen_kit, tmp_path, monkeypatch):
    kit, trusted = frozen_kit
    monkeypatch.setattr(runner, "offline_probe", lambda: {"status": "pass"})

    def fake_stage(name, command, root, env, timeout):
        assert "PYTHONPATH" not in env and env["PYTHONNOUSERSITE"] == "1"
        if name.endswith("simulate"):
            export = Path(command[-1])
            export.mkdir()
            (export / "results.json").write_text(json.dumps(result({"00": 503, "11": 497})))
            (export / "circuit.json").write_text(json.dumps(oracle.CIRCUIT))

    monkeypatch.setattr(runner, "stage", fake_stage)
    report = runner.run(kit, tmp_path / "evidence", trusted)
    assert report["status"] == "pass" and report["exact_counts_equal"]
    assert report["simulator_invocations"] == 2


def test_cli_missing_input_and_external_digest_are_visible(tmp_path, monkeypatch, capsys):
    import runpy
    import sys

    kit = tmp_path / "kit"
    kit.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ROOT / "run_bell_reproduction.py"),
            "--kit",
            str(kit),
            "--evidence",
            str(tmp_path / "evidence"),
            "--expected-freeze-sha256",
            "0" * 64,
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(ROOT / "run_bell_reproduction.py"), run_name="__main__")
    assert exit_info.value.code == 1
    assert '"simulator_invocations": 0' in capsys.readouterr().out


def test_freeze_cli_records_operator_source(frozen_kit, monkeypatch, capsys):
    import runpy
    import sys

    kit, _ = frozen_kit
    (kit / "freeze.json").unlink()
    monkeypatch.setattr(
        sys,
        "argv",
        [str(ROOT / "freeze_bell_kit.py"), "--kit", str(kit), "--source-ref", "synthetic-cli"],
    )
    runpy.run_path(str(ROOT / "freeze_bell_kit.py"), run_name="__main__")
    assert capsys.readouterr().out.strip() == runner.digest(kit / "freeze.json")
    assert json.loads((kit / "freeze.json").read_text())["source_ref"] == "synthetic-cli"


@pytest.mark.parametrize("kind", ["package", "symlink"])
def test_freeze_refuses_incompatible_or_linked_input(frozen_kit, kind):
    kit, _ = frozen_kit
    (kit / "freeze.json").unlink()
    if kind == "package":
        (kit / "environment.json").write_text(json.dumps({"packages": {"marqov": "0.5.2"}}))
    else:
        symlink_or_skip(kit / "linked", kit / "run_bell.py")
    with pytest.raises(ValueError):
        freezer.freeze(kit, "synthetic")


def test_disk_measurement_does_not_follow_links(tmp_path):
    data = tmp_path / "data"
    data.write_bytes(b"123")
    symlink_or_skip(tmp_path / "link", data)
    assert runner.disk_bytes(tmp_path) == 3


def test_changed_experiment_does_not_pass_preflight(frozen_kit):
    kit, _ = frozen_kit
    (kit / "experiment.json").write_text(
        json.dumps({"qubits": 20, "shots": 1000, "seed": 42, "backend": "local"})
    )
    trusted = refreeze(kit)
    with pytest.raises(ValueError, match="EXPERIMENT_MISMATCH"):
        runner.preflight(kit, trusted)


@pytest.mark.parametrize("field,value", [("seed", True), ("shots", 1000.0), ("backend", "cloud")])
def test_run_metadata_is_verifier_owned(field, value):
    output = result({"00": 500, "11": 500})
    output[field] = value
    with pytest.raises(ValueError, match="RUN_CONTRACT_MISMATCH"):
        oracle.check(output, oracle.CIRCUIT, oracle.REFERENCE)


def test_actual_differing_exports_fail_even_when_both_analytic_checks_pass(
    frozen_kit, tmp_path, monkeypatch
):
    kit, trusted = frozen_kit
    monkeypatch.setattr(runner, "offline_probe", lambda: {"status": "pass"})

    def fake_stage(name, command, root, env, timeout):
        if name.endswith("simulate"):
            export = Path(command[-1])
            export.mkdir()
            n = 500 if name.startswith("a") else 501
            (export / "results.json").write_text(json.dumps(result({"00": n, "11": 1000 - n})))
            (export / "circuit.json").write_text(json.dumps(oracle.CIRCUIT))

    monkeypatch.setattr(runner, "stage", fake_stage)
    report = runner.run(kit, tmp_path / "evidence", trusted)
    assert report["status"] == "fail" and report["error"] == "SEEDED_REPLAY_MISMATCH"
