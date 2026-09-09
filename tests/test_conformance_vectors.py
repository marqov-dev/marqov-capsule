"""Fixed public vectors: never regenerate expected values during a test."""
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

import pytest
import yaml

from marqov_capsule._canonical import canonical_bytes, compute_capsule_id, load_manifest_yaml
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.redactor import CapsuleRedactor
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.verifier import CapsuleVerifier

ROOT = Path(__file__).parents[1] / "spec/v1/conformance"
GOLDEN = ROOT / "golden"
VECTORS = json.loads((GOLDEN / "expected.json").read_text())


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["fixture"])
def test_fixed_fixture_outputs(vector, tmp_path):
    directory = ROOT / vector["fixture"]
    manifest = load_manifest_yaml((directory / "capsule.yaml").read_text())
    expected_bytes = (GOLDEN / vector["canonical_file"]).read_bytes()
    assert canonical_bytes(manifest) == expected_bytes
    assert compute_capsule_id(manifest) == vector["capsule_id"]
    validation = CapsuleValidator.validate(manifest)
    assert validation["valid"] == vector["schema_valid"]
    assert sorted(e["path"] for e in validation["errors"]) == vector["schema_error_paths"]
    scan = CapsuleRedactor(directory).scan()
    assert scan["has_secrets"] == vector["has_secrets"]
    assert sorted(
        ({"file": f["file"], "line": f["line"]} for f in scan["findings"]),
        key=lambda f: (f["file"], f["line"]),
    ) == vector["secret_locations"]
    if vector["checksums_digest"] is not None:
        assert manifest["checksums_digest"] == vector["checksums_digest"]
        assert CapsuleVerifier.verify_integrity(directory, expected_id=vector["capsule_id"])["status"] == "pass"
        # Also exercise the writer against fixed checksum bytes, not just reader.
        import shutil
        copy = tmp_path / "capsule"
        shutil.copytree(directory, copy)
        CapsuleBuilder().save_checksums(copy)
        assert (copy / ".checksums").read_bytes() == (directory / ".checksums").read_bytes()


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["fixture"])
def test_independent_fixture_digest_chain(vector):
    """No capsule canonicalizer, builder, verifier, or JCS calls in this check.

    This serializer applies only to these fixtures: ASCII object keys and
    JSON numbers whose stdlib spelling equals JCS. It is not a general JCS
    implementation (floating-point extremes and UTF-16 sorting differ).
    """
    data = (GOLDEN / vector["canonical_file"]).read_bytes()
    assert json.dumps(json.loads(data), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode() == data
    assert "mqc:1:" + hashlib.sha256(data).hexdigest() == vector["capsule_id"]
    if vector["checksums_digest"] is None:
        return
    directory = ROOT / vector["fixture"]
    checksums = (directory / ".checksums").read_bytes()
    assert "sha256:" + hashlib.sha256(checksums).hexdigest() == vector["checksums_digest"]
    paths = []
    for line in checksums.decode().splitlines():
        digest, encoded_path = line.split("  ", 1)
        path = unquote(encoded_path)
        paths.append(path)
        assert "sha256:" + hashlib.sha256((directory / path).read_bytes()).hexdigest() == digest
    assert paths == sorted(paths, key=lambda p: p.encode())
    assert set(paths) == {str(p.relative_to(directory)) for p in directory.rglob("*")
                          if p.is_file() and p.name not in {"capsule.yaml", ".checksums"}}


def test_versioned_derived_id_does_not_hide_same_line_credential(tmp_path):
    parent = next(v["capsule_id"] for v in VECTORS if v["fixture"] == "derived_capsule/parent")
    (tmp_path / "capsule.yaml").write_text(json.dumps({
        "derived_from": parent, "IBM_QUANTUM_TOKEN": "synthetic-not-a-real-secret",
    }))
    findings = CapsuleRedactor(tmp_path).scan()["findings"]
    assert any(f["blocking"] and f["reason"] == "name_pattern" for f in findings)


@pytest.mark.parametrize("vector", json.loads(
    (GOLDEN / "canonical-edge-cases.json").read_text()), ids=lambda v: v["name"])
def test_canonical_edge_vectors(vector):
    if vector.get("reject"):
        with pytest.raises((ValueError, TypeError, yaml.YAMLError)):
            canonical_bytes(load_manifest_yaml(vector["yaml"]))
        return
    manifest = load_manifest_yaml(vector["yaml"])
    expected = vector["canonical_utf8"].encode("utf-8")
    assert canonical_bytes(manifest) == expected
    assert "mqc:1:" + hashlib.sha256(expected).hexdigest() == vector["capsule_id"]
    assert compute_capsule_id(manifest) == vector["capsule_id"]


def test_legacy_key_conversion_cannot_drop_a_value():
    with pytest.raises(ValueError, match="collide"):
        canonical_bytes({1: "first", "1": "second"})


def test_digest_field_does_not_hide_same_line_credential(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "checksums_digest: sha256:" + "a" * 64 + ", IBM_QUANTUM_TOKEN: synthetic-secret\n"
    )
    findings = CapsuleRedactor(tmp_path).scan()["findings"]
    assert any(f["blocking"] and f["reason"] == "name_pattern" for f in findings)


def test_normalized_collision_is_integrity_failure(tmp_path):
    import shutil
    shutil.copytree(ROOT / "valid_capsule", tmp_path / "capsule")
    manifest = tmp_path / "capsule/capsule.yaml"
    with manifest.open("a") as stream:
        stream.write('\n"é": first\n"e\\u0301": second\n')
    result = CapsuleVerifier.verify_integrity(tmp_path / "capsule")
    assert result["status"] == "fail"
    assert result["capsule_id"] is None
