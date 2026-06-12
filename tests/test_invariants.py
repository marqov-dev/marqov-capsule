"""Cross-cutting invariant checks — these run in CI on every PR."""
import json
from pathlib import Path

import pytest

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.redactor import CapsuleRedactor, RedactorError
from marqov_capsule.validator import CapsuleValidator

FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


# Invariant 1: No credential patterns survive sealing
def test_capsule_with_secrets_seal_blocked():
    """capsule_with_secrets fixture must cause CapsuleRedactor to raise in block mode."""
    redactor = CapsuleRedactor(FIXTURE_DIR / "capsule_with_secrets", mode="block")
    with pytest.raises(RedactorError):
        redactor.scan_and_raise()


# Invariant 2: Redactor does not false-positive on spec-defined digest fields
def test_redactor_allowlist_digest_fields():
    """valid_capsule contains checksums_digest — must not be flagged."""
    redactor = CapsuleRedactor(FIXTURE_DIR / "valid_capsule")
    result = redactor.scan()
    assert result["has_secrets"] is False, f"False positives: {result['findings']}"


# Invariant 3: Digests are deterministic (same logical capsule → same ID)
def test_capsule_id_is_deterministic():
    cap = load_manifest_yaml((FIXTURE_DIR / "valid_capsule/capsule.yaml").read_text())
    id1 = compute_capsule_id(cap)
    id2 = compute_capsule_id(cap)
    assert id1 == id2


# Invariant 3b: load_manifest_yaml gives the same ID regardless of timestamp quoting
def test_capsule_id_stable_across_timestamp_quoting():
    """Core guarantee of load_manifest_yaml: unquoted and quoted timestamps are equal."""
    unquoted = load_manifest_yaml(
        "version: '1.0.0'\nname: test\nlifecycle_state: draft\n"
        "created_at: 2026-06-11T00:00:00Z\n"
    )
    quoted = load_manifest_yaml(
        "version: '1.0.0'\nname: test\nlifecycle_state: draft\n"
        'created_at: "2026-06-11T00:00:00Z"\n'
    )
    assert compute_capsule_id(unquoted) == compute_capsule_id(quoted), (
        "Capsule IDs differ between unquoted and quoted timestamps — "
        "load_manifest_yaml timestamp resolver disabled incorrectly"
    )


# Invariant 4: Capsule ID changes when any file in the bundle changes
def test_capsule_id_changes_with_content(tmp_path):
    from marqov_capsule.builder import CapsuleBuilder

    for i, counts in enumerate([{"00": 500, "11": 500}, {"00": 900, "11": 100}]):
        cap_dir = tmp_path / f"cap{i}.capsule"
        cap_dir.mkdir()
        (cap_dir / "payload").mkdir()
        (cap_dir / "payload" / "results.json").write_text(json.dumps({"counts": counts}))
        (cap_dir / "source").mkdir()
        (cap_dir / "source" / "circuit.qasm").write_text("OPENQASM 3.0;\n")

        b = CapsuleBuilder()
        b.start_capsule(
            name="Test",
            requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
        )
        b.seal_capsule(capsule_dir=cap_dir, sealed_by="test")
        b.save_capsule(cap_dir)

    id0 = compute_capsule_id(load_manifest_yaml((tmp_path / "cap0.capsule/capsule.yaml").read_text()))
    id1 = compute_capsule_id(load_manifest_yaml((tmp_path / "cap1.capsule/capsule.yaml").read_text()))
    assert id0 != id1


# Invariant 5: valid_capsule fixture passes schema validation
def test_valid_capsule_fixture_passes_schema():
    result = CapsuleValidator.validate_file(FIXTURE_DIR / "valid_capsule/capsule.yaml")
    assert result["valid"] is True, f"Errors: {result['errors']}"


# Invariant 6: invalid_capsule fixture fails schema validation
def test_invalid_capsule_fixture_fails_schema():
    result = CapsuleValidator.validate_file(FIXTURE_DIR / "invalid_capsule/capsule.yaml")
    assert result["valid"] is False


# Invariant 7: requirements core fields present after schema validation
def test_valid_capsule_has_requirements_fields():
    cap = load_manifest_yaml((FIXTURE_DIR / "valid_capsule/capsule.yaml").read_text())
    assert "paradigm" in cap["requirements"]
    assert isinstance(cap["requirements"]["paradigm"], list)
    assert "max_qubit_count" in cap["requirements"]


# Invariant 8: multi_task_capsule exercises array paradigm
def test_multi_task_capsule_paradigm_is_array():
    cap = load_manifest_yaml((FIXTURE_DIR / "multi_task_capsule/capsule.yaml").read_text())
    assert isinstance(cap["requirements"]["paradigm"], list)
    assert len(cap["requirements"]["paradigm"]) > 1


# Invariant 9: derived_capsule chain is well-formed
def test_derived_capsule_chain():
    parent = load_manifest_yaml((FIXTURE_DIR / "derived_capsule/parent/capsule.yaml").read_text())
    child = load_manifest_yaml((FIXTURE_DIR / "derived_capsule/child/capsule.yaml").read_text())
    parent_id = compute_capsule_id(parent)
    assert child["derived_from"] == parent_id, (
        f"child.derived_from={child['derived_from']!r} does not match "
        f"parent capsule ID={parent_id!r}"
    )


# Invariant 10: CLI commands exit non-zero on error paths
def test_validate_exits_nonzero_on_invalid():
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(FIXTURE_DIR / "invalid_capsule/capsule.yaml")])
    assert result.exit_code != 0


def test_verify_exits_nonzero_on_tampered(tmp_path):
    import shutil
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli

    # Copy valid capsule and tamper with a payload file
    src = FIXTURE_DIR / "valid_capsule"
    dest = tmp_path / "tampered.capsule"
    shutil.copytree(str(src), str(dest))
    (dest / "payload" / "results.json").write_text('{"tampered": true}')

    runner = CliRunner()
    result = runner.invoke(cli, ["verify", str(dest)])
    assert result.exit_code != 0
