"""Spec section 8: a conformant implementation produces a capsule.yaml that
validates against the schema (#111); section 4: a sealed or archived capsule
rejects modification (#107); D1: ``max_qubit_count: 0`` is legal (#112).
"""
import json

import pytest
from click.testing import CliRunner

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.builder import CapsuleBuilder, CapsuleStateError, CapsuleValidationError
from marqov_capsule.cli.main import cli
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.verifier import CapsuleVerifier

GATE = {"paradigm": ["gate-based"], "max_qubit_count": 2}
TASK_ID = "550e8400-e29b-41d4-a716-446655440000"
BACKEND = {"provider": "ibm", "name": "ibm_kyiv", "shots": 1024}
SETTINGS = {"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"}


def _dir(tmp_path, name="cap"):
    d = tmp_path / name
    d.mkdir()
    (d / "payload.txt").write_text("x\n")
    return d


def _sealed_manifest(tmp_path):
    d = _dir(tmp_path, "parent")
    b = CapsuleBuilder().start_capsule(name="parent", requirements=GATE)
    sealed_id = b.seal(d)
    return d, sealed_id, load_manifest_yaml((d / "capsule.yaml").read_text(encoding="utf-8"))


# --- #111: seal validates --------------------------------------------------

def test_seal_refuses_schema_invalid_requirements(tmp_path):
    d = _dir(tmp_path)
    b = CapsuleBuilder().start_capsule(
        name="bad", requirements={"paradigm": ["photonic"], "max_qubit_count": -5})
    with pytest.raises(CapsuleValidationError) as info:
        b.seal(d)
    assert isinstance(info.value, ValueError)
    assert "paradigm" in str(info.value) and "max_qubit_count" in str(info.value)
    assert [e["path"] for e in info.value.errors]
    assert not (d / "capsule.yaml").exists()
    assert not (d / ".checksums").exists()
    assert b.to_dict()["lifecycle_state"] == "draft"


def test_seal_refuses_probabilistic_task_without_verification_settings(tmp_path):
    d = _dir(tmp_path)
    b = CapsuleBuilder().start_capsule(name="t", requirements=GATE)
    b.add_task_execution(task_id=TASK_ID, status="success", result_type="probabilistic", backend=BACKEND)
    with pytest.raises(CapsuleValidationError, match="verification_settings"):
        b.seal(d)


def test_seal_refuses_unversioned_derived_from(tmp_path):
    d = _dir(tmp_path)
    b = CapsuleBuilder().start_capsule(name="t", requirements=GATE)
    with pytest.raises(CapsuleValidationError, match="derived_from"):
        b.seal(d, derived_from="a" * 64)


def test_seal_validate_false_is_the_escape_hatch(tmp_path):
    d = _dir(tmp_path)
    b = CapsuleBuilder().start_capsule(
        name="bad", requirements={"paradigm": ["photonic"], "max_qubit_count": 7})
    sealed_id = b.seal(d, validate=False)
    assert sealed_id.startswith("mqc:1:")
    assert CapsuleValidator.validate_file(d / "capsule.yaml")["valid"] is False


@pytest.mark.parametrize("shape", ["minimal", "probabilistic", "deterministic", "derived",
                                   "notes", "all-optional-none", "classical-zero"])
def test_every_builder_shape_validates_after_sealing(shape, tmp_path):
    d = _dir(tmp_path)
    b = CapsuleBuilder()
    if shape == "all-optional-none":
        b.start_capsule(name="t", requirements=GATE, run_id=None, workflow_ref=None,
                        environment_ref=None, max_budget_usd=None)
    elif shape == "classical-zero":
        b.start_capsule(name="t", requirements={"paradigm": ["classical"], "max_qubit_count": 0})
    else:
        b.start_capsule(name="t", description="d", parameters={"shots": 1024},
                        requirements=GATE, tags=["x"])
    if shape == "probabilistic":
        b.add_task_execution(task_id=TASK_ID, status="success", result_type="probabilistic",
                             backend=BACKEND, verification_settings=SETTINGS,
                             start_time="2026-01-01T00:00:00Z", wall_time_seconds=1.5, cost_usd=0.0)
        b.add_result_digest({"counts": {"00": 1}})
    if shape == "deterministic":
        b.add_task_execution(task_id=TASK_ID, status="success", result_type="deterministic", backend=BACKEND)
    kwargs = {}
    if shape == "derived":
        kwargs["derived_from"] = "mqc:1:" + "a" * 64
    if shape == "notes":
        b.seal_capsule(d, notes="first run")
        b.save_capsule(d / "capsule.yaml")
    else:
        b.seal(d, **kwargs)
    result = CapsuleValidator.validate_file(d / "capsule.yaml")
    assert result["valid"] is True, result["errors"]


# --- D1 / #112: schema fixes -----------------------------------------------

def test_classical_capsule_with_zero_qubits_is_schema_valid():
    manifest = {"version": "1.0.0", "name": "c", "lifecycle_state": "draft",
                "requirements": {"paradigm": ["classical"], "max_qubit_count": 0}}
    assert CapsuleValidator.validate(manifest)["valid"] is True
    manifest["requirements"]["max_qubit_count"] = -1
    assert CapsuleValidator.validate(manifest)["valid"] is False


def test_archived_manifest_needs_the_sealed_fields():
    manifest = {"version": "1.0.0", "name": "a", "lifecycle_state": "archived"}
    result = CapsuleValidator.validate(manifest)
    assert result["valid"] is False
    assert {e["path"].split("/")[-1] for e in result["errors"]} >= {"requirements", "checksums_digest", "sealed_at", "sealed_by"}


def test_seal_notes_is_a_schema_field():
    manifest = {"version": "1.0.0", "name": "a", "lifecycle_state": "draft", "seal_notes": 5}
    assert CapsuleValidator.validate(manifest)["valid"] is False
    manifest["seal_notes"] = "ok"
    assert CapsuleValidator.validate(manifest)["valid"] is True


def test_bundled_schema_is_byte_identical_to_spec():
    from pathlib import Path
    root = Path(__file__).parent.parent
    assert (root / "spec/v1/capsule-schema.json").read_bytes() == \
        (root / "src/marqov_capsule/schemas/capsule-schema.json").read_bytes()


# --- #111: init validates its own flags -------------------------------------

def test_init_rejects_unknown_paradigm(tmp_path):
    result = CliRunner().invoke(cli, ["init", str(tmp_path / "c"), "--paradigm", "photonic"])
    assert result.exit_code == 2, result.output
    assert "photonic" in result.output
    assert not (tmp_path / "c" / "capsule.yaml").exists()


def test_init_rejects_negative_qubits(tmp_path):
    result = CliRunner().invoke(cli, ["init", str(tmp_path / "c"), "--qubits", "-5"])
    assert result.exit_code == 2, result.output


def test_init_accepts_classical_zero_qubits_and_writes_a_valid_draft(tmp_path):
    result = CliRunner().invoke(cli, ["init", str(tmp_path / "c"), "--paradigm", "classical", "--qubits", "0"])
    assert result.exit_code == 0, result.output
    assert CapsuleValidator.validate_file(tmp_path / "c" / "capsule.yaml")["valid"] is True


def test_cli_seal_refuses_invalid_draft_and_lists_errors(tmp_path):
    d = _dir(tmp_path)
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [photonic]\n  max_qubit_count: -5\ntask_executions: []\n")
    result = CliRunner().invoke(cli, ["seal", str(d)])
    assert result.exit_code == 1, result.output
    assert "requirements/paradigm" in result.output
    assert "--no-validate" in result.output
    assert not (d / ".checksums").exists()
    as_json = CliRunner().invoke(cli, ["seal", "--json", str(d)])
    data = json.loads(as_json.output)
    assert data["status"] == "error" and data["errors"]


def test_cli_seal_no_validate_seals_anyway(tmp_path):
    d = _dir(tmp_path)
    (d / "capsule.yaml").write_text(
        "version: '1.0.0'\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [photonic]\n  max_qubit_count: 7\ntask_executions: []\n")
    result = CliRunner().invoke(cli, ["seal", "--no-validate", str(d)])
    assert result.exit_code == 0, result.output


# --- #107: sealed capsules are immutable -----------------------------------

@pytest.mark.parametrize("mutate", [
    lambda b, d: b.add_task_execution(task_id=TASK_ID, status="success", result_type="deterministic", backend=BACKEND),
    lambda b, d: b.add_result_digest({"k": 1}),
    lambda b, d: b.save_capsule(d / "capsule.yaml"),
    lambda b, d: b.save_checksums(d),
    lambda b, d: b.seal_capsule(d),
], ids=["add_task_execution", "add_result_digest", "save_capsule", "save_checksums", "seal_capsule"])
def test_mutators_refuse_a_sealed_manifest(mutate, tmp_path):
    d, sealed_id, manifest = _sealed_manifest(tmp_path)
    before = (d / "capsule.yaml").read_bytes()
    b = CapsuleBuilder.from_manifest(manifest)
    with pytest.raises(CapsuleStateError):
        mutate(b, d)
    assert (d / "capsule.yaml").read_bytes() == before
    assert CapsuleVerifier.verify_integrity(d, expected_id=sealed_id)["status"] == "pass"


def test_mutators_refuse_an_archived_manifest():
    manifest = {"version": "1.0.0", "name": "a", "lifecycle_state": "archived"}
    b = CapsuleBuilder.from_manifest(manifest)
    with pytest.raises(CapsuleStateError):
        b.add_result_digest({"k": 1})


def test_start_capsule_on_a_loaded_sealed_manifest_starts_fresh(tmp_path):
    # A new capsule is not a modification of the old one.
    _, _, manifest = _sealed_manifest(tmp_path)
    b = CapsuleBuilder.from_manifest(manifest)
    b.start_capsule(name="fresh", requirements=GATE)
    assert b.to_dict()["lifecycle_state"] == "draft"
    assert "checksums_digest" not in b.to_dict()


# --- #107: derive() is the sanctioned way to continue from a sealed capsule --

def test_derive_produces_a_draft_pointing_at_the_parent(tmp_path):
    d, sealed_id, manifest = _sealed_manifest(tmp_path)
    child = CapsuleBuilder.derive(manifest)
    draft = child.to_dict()
    assert draft["lifecycle_state"] == "draft"
    assert draft["derived_from"] == sealed_id == compute_capsule_id(manifest)
    assert draft["name"] == manifest["name"]
    assert draft["requirements"] == manifest["requirements"]
    assert draft["task_executions"] == [] and draft["digests"] == {}
    for key in ("checksums_digest", "sealed_at", "sealed_by"):
        assert key not in draft
    child_dir = _dir(tmp_path, "child")
    child_id = child.seal(child_dir)
    assert child_id != sealed_id
    assert CapsuleValidator.validate_file(child_dir / "capsule.yaml")["valid"] is True
    assert load_manifest_yaml((child_dir / "capsule.yaml").read_text(encoding="utf-8"))["derived_from"] == sealed_id


def test_derive_from_a_loaded_builder(tmp_path):
    _, sealed_id, manifest = _sealed_manifest(tmp_path)
    child = CapsuleBuilder.from_manifest(manifest).derive()
    assert child.to_dict()["derived_from"] == sealed_id


def test_derive_refuses_a_draft_parent():
    draft = {"version": "1.0.0", "name": "d", "lifecycle_state": "draft", "requirements": GATE}
    with pytest.raises(ValueError, match="sealed"):
        CapsuleBuilder.derive(draft)


def test_derive_does_not_alias_the_parent(tmp_path):
    _, _, manifest = _sealed_manifest(tmp_path)
    child = CapsuleBuilder.derive(manifest)
    child.to_dict()["requirements"]["max_qubit_count"] = 99
    assert manifest["requirements"]["max_qubit_count"] == 2
