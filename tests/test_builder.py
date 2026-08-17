import hashlib
from pathlib import Path
import pytest
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.redactor import RedactorError


def _parse_checksums(text: str) -> dict[str, str]:
    """Parse the spec-format .checksums ('sha256:<hex>  <path>' lines)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, path = line.split("  ", 1)
        out[path] = digest
    return out


def test_start_capsule_sets_required_fields():
    b = CapsuleBuilder()
    b.start_capsule(
        name="Test",
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
    )
    d = b.to_dict()
    assert d["name"] == "Test"
    assert d["version"] == "1.0.0"
    assert d["lifecycle_state"] == "draft"
    assert d["requirements"]["paradigm"] == ["gate-based"]
    assert d["requirements"]["max_qubit_count"] == 2


def test_requirements_required_for_seal(tmp_path):
    b = CapsuleBuilder()
    b.start_capsule(name="NoReqs")  # no requirements
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    with pytest.raises(ValueError, match="requirements"):
        b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")


def test_seal_sets_lifecycle_state(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")
    assert b.to_dict()["lifecycle_state"] == "sealed"


def test_save_checksums_excludes_capsule_yaml(tmp_path):
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    (capsule_dir / "capsule.yaml").write_text("version: '1.0.0'\n")
    payload = capsule_dir / "payload"
    payload.mkdir()
    (payload / "results.json").write_text('{"counts": {"00": 100}}')

    b = CapsuleBuilder()
    checksums_path = b.save_checksums(capsule_dir)
    checksums = _parse_checksums(checksums_path.read_text())

    assert "capsule.yaml" not in checksums
    assert ".checksums" not in checksums
    assert "payload/results.json" in checksums


def test_checksums_digest_embedded_in_sealed_capsule(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    _populate_capsule_dir(capsule_dir)
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")
    b.save_capsule(capsule_dir)

    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    assert "checksums_digest" in manifest
    assert manifest["checksums_digest"].startswith("sha256:")


def test_checksums_digest_is_sha256_of_checksums_file(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    _populate_capsule_dir(capsule_dir)
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")
    b.save_capsule(capsule_dir)

    checksums_bytes = (capsule_dir / ".checksums").read_bytes()
    expected = "sha256:" + hashlib.sha256(checksums_bytes).hexdigest()
    manifest = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    assert manifest["checksums_digest"] == expected


def test_save_checksums_skips_symlinks(tmp_path):
    """Symlinks must not be hashed/enrolled — otherwise re-sealing a received capsule
    would bake an outside file's content into the derived capsule (#32)."""
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY CONTENT")

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    (payload / "results.json").write_text('{"counts": {"00": 1}}')
    (payload / "link.txt").symlink_to(secret)

    b = CapsuleBuilder()
    checksums_path = b.save_checksums(capsule_dir)
    checksums = _parse_checksums(checksums_path.read_text())

    assert "payload/link.txt" not in checksums
    assert "payload/results.json" in checksums


def test_save_checksums_after_seal_raises(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")
    with pytest.raises(RuntimeError, match="sealed"):
        b.save_checksums(capsule_dir)


def test_capsule_id_changes_when_payload_changes(tmp_path):
    b1 = _make_builder()
    dir1 = tmp_path / "cap1.capsule"
    dir1.mkdir()
    _populate_capsule_dir(dir1, counts={"00": 500, "11": 500})
    b1.seal_capsule(capsule_dir=dir1, sealed_by="test")
    b1.save_capsule(dir1)
    id1 = compute_capsule_id(load_manifest_yaml((dir1 / "capsule.yaml").read_text()))

    b2 = _make_builder()
    dir2 = tmp_path / "cap2.capsule"
    dir2.mkdir()
    _populate_capsule_dir(dir2, counts={"00": 900, "11": 100})
    b2.seal_capsule(capsule_dir=dir2, sealed_by="test")
    b2.save_capsule(dir2)
    id2 = compute_capsule_id(load_manifest_yaml((dir2 / "capsule.yaml").read_text()))

    assert id1 != id2


def test_derived_from_embedded_when_provided(tmp_path):
    parent_id = "a" * 64
    b = _make_builder()
    capsule_dir = tmp_path / "child.capsule"
    capsule_dir.mkdir()
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test", derived_from=parent_id)
    assert b.to_dict()["derived_from"] == parent_id


def test_seal_blocks_on_secrets(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "secret.capsule"
    capsule_dir.mkdir()
    src = capsule_dir / "source"
    src.mkdir()
    (src / "run.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    with pytest.raises(RedactorError):
        b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test")


def test_seal_warn_only_does_not_raise(tmp_path):
    b = _make_builder()
    capsule_dir = tmp_path / "secret.capsule"
    capsule_dir.mkdir()
    src = capsule_dir / "source"
    src.mkdir()
    (src / "run.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    b.seal_capsule(capsule_dir=capsule_dir, sealed_by="test", warn_only=True)
    assert b.to_dict()["lifecycle_state"] == "sealed"


def test_from_manifest_roundtrip():
    """from_manifest() loads an existing manifest dict into a new builder."""
    original = {
        "version": "1.0.0",
        "name": "Loaded Capsule",
        "lifecycle_state": "draft",
        "task_executions": [{"task_id": "abc", "status": "success"}],
    }
    b = CapsuleBuilder.from_manifest(original)
    d = b.to_dict()
    assert d["name"] == "Loaded Capsule"
    assert d["task_executions"][0]["task_id"] == "abc"
    # Deep copy — mutations don't alias original
    d["name"] = "Changed"
    assert original["name"] == "Loaded Capsule"


def test_seal_convenience_returns_capsule_id(tmp_path):
    """CapsuleBuilder.seal() runs the full sequence and returns the 64-char hex capsule ID."""
    import yaml
    manifest = {
        "version": "1.0.0",
        "name": "test-capsule",
        "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 1},
        "task_executions": [],
    }
    b = CapsuleBuilder.from_manifest(manifest)
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    capsule_id = b.seal(capsule_dir=capsule_dir, sealed_by="test-runner")
    assert capsule_id.startswith("mqc:1:")
    assert all(c in "0123456789abcdef" for c in capsule_id.split(":")[-1])
    assert len(capsule_id.split(":")[-1]) == 64
    # capsule.yaml was written
    assert (capsule_dir / "capsule.yaml").exists()
    sealed = load_manifest_yaml((capsule_dir / "capsule.yaml").read_text())
    assert sealed["lifecycle_state"] == "sealed"


# --- helpers ---

def _make_builder():
    b = CapsuleBuilder()
    b.start_capsule(
        name="Test Capsule",
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
    )
    b.add_task_execution(
        task_id="550e8400-e29b-41d4-a716-446655440000",
        status="success",
        result_type="probabilistic",
        backend={"provider": "ibm", "name": "ibm_kyiv", "shots": 1000},
        verification_settings={
            "epsilon": 0.05,
            "min_shots": 100,
            "tolerance_regime": "strict",
        },
    )
    return b


def _populate_capsule_dir(capsule_dir: Path, counts=None):
    if counts is None:
        counts = {"00": 500, "11": 500}
    import json
    payload = capsule_dir / "payload"
    payload.mkdir(exist_ok=True)
    (payload / "results.json").write_text(json.dumps({"counts": counts, "shots": sum(counts.values())}))
    src = capsule_dir / "source"
    src.mkdir(exist_ok=True)
    (src / "circuit.qasm").write_text("OPENQASM 3.0;\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n")
