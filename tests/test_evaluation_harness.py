"""The measurement harness must fail when restoration or refusal is broken."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "capsule_evaluation", Path(__file__).parents[1] / "tools/evaluation/run.py")
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def test_corpus_and_bounded_scaling(tmp_path):
    report = evaluation.run(tmp_path / "evidence", repeats=1)
    assert report["status"] == "pass"
    assert {c["case"] for c in report["cases"]} == {
        "bell", "ghz", "parameter-sweep", "classical", "multi-result"}
    assert sum(len(c["refused"]) for c in report["cases"]) == 30
    assert len(report["scaling"]) == 9
    for case in report["scaling"]:
        assert len(case["trials"]) == 1
        assert case["trials"][0]["payload_bytes"] == case["payload_bytes"]
        assert case["trials"][0]["payload_files"] == case["payload_files"]


def test_corrupt_restoration_cannot_be_reported_as_success(tmp_path, monkeypatch):
    original = evaluation.unpack_capsule

    def corrupt(*args):
        restored = original(*args)
        (restored / "data.json").write_bytes(b"changed")
        return restored

    monkeypatch.setattr(evaluation, "unpack_capsule", corrupt)
    with pytest.raises(RuntimeError, match="restored file set or bytes differ"):
        evaluation.exercise(tmp_path / "case", {"data.json": b"{}\n"}, 0, False)


def test_missing_integrity_refusal_cannot_be_reported_as_success(tmp_path, monkeypatch):
    original = evaluation.CapsuleVerifier.verify_integrity

    def accept_extra(path, **kwargs):
        if Path(path).name == "extra-payload":
            return {"status": "pass"}
        return original(path, **kwargs)

    monkeypatch.setattr(evaluation.CapsuleVerifier, "verify_integrity", accept_extra)
    with pytest.raises(RuntimeError, match="accepted extra-payload"):
        evaluation.exercise(tmp_path / "case", {"data.json": b"{}\n"}, 0, True)


@pytest.mark.parametrize("repeats", [0, 6, True, 1.5])
def test_out_of_bounds_runs_create_no_output(tmp_path, repeats):
    target = tmp_path / "evidence"
    with pytest.raises(ValueError):
        evaluation.run(target, repeats)
    assert not target.exists()


def test_existing_evidence_is_not_overwritten(tmp_path):
    target = tmp_path / "evidence"
    target.mkdir()
    marker = target / "retain.txt"
    marker.write_text("retain")
    with pytest.raises(FileExistsError):
        evaluation.run(target)
    assert marker.read_text() == "retain"
