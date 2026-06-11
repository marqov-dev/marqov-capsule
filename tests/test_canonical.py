import hashlib
from datetime import datetime, timezone
from marqov_capsule._canonical import compute_capsule_id, canonical_bytes


def test_canonical_bytes_sorts_keys():
    a = canonical_bytes({"z": 1, "a": 2})
    b = canonical_bytes({"a": 2, "z": 1})
    assert a == b


def test_canonical_bytes_no_whitespace():
    raw = canonical_bytes({"key": "value"})
    assert b" " not in raw
    assert b"\n" not in raw


def test_capsule_id_is_sha256_hex():
    id_ = compute_capsule_id({"name": "test", "version": "1.0.0"})
    assert len(id_) == 64
    assert all(c in "0123456789abcdef" for c in id_)


def test_capsule_id_changes_with_content():
    id_a = compute_capsule_id({"name": "a"})
    id_b = compute_capsule_id({"name": "b"})
    assert id_a != id_b


def test_capsule_id_stable_across_key_order():
    id_a = compute_capsule_id({"z": 1, "a": 2})
    id_b = compute_capsule_id({"a": 2, "z": 1})
    assert id_a == id_b


def test_load_manifest_yaml_preserves_timestamp_as_string():
    from marqov_capsule._canonical import load_manifest_yaml
    manifest = load_manifest_yaml("created_at: 2026-06-11T00:00:00Z\nname: test\n")
    assert isinstance(manifest["created_at"], str), (
        f"expected str, got {type(manifest['created_at'])} — timestamp resolver not disabled"
    )
    assert manifest["created_at"] == "2026-06-11T00:00:00Z"


def test_unquoted_and_quoted_timestamps_yield_same_capsule_id():
    from marqov_capsule._canonical import load_manifest_yaml
    unquoted = load_manifest_yaml("version: '1.0.0'\nname: test\ncreated_at: 2026-06-11T00:00:00Z\n")
    quoted = load_manifest_yaml("version: '1.0.0'\nname: test\ncreated_at: \"2026-06-11T00:00:00Z\"\n")
    assert compute_capsule_id(unquoted) == compute_capsule_id(quoted)


def test_datetime_object_backstop_does_not_raise():
    dt = datetime(2026, 6, 11, 0, 0, 0, tzinfo=timezone.utc)
    result = compute_capsule_id({"meta": {"ts": dt}, "name": "test"})
    assert len(result) == 64
