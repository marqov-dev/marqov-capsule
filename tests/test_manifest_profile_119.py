"""Writer/readback and public rejection behavior for the common YAML profile."""

import pytest
import yaml

from marqov_capsule import CapsuleBuilder, CapsuleVerifier
from marqov_capsule._canonical import (
    compute_capsule_id,
    dump_manifest_yaml,
    load_manifest_yaml,
)


@pytest.mark.parametrize(
    "value", ["x\x00y", "x\x7fy", "x\x80y", "x\u0085y", "x\u2028y", "x\u2029y"]
)
def test_writer_escapes_restricted_raw_characters_without_changing_identity(value):
    manifest = {"name": value, value: "key too", "nested": [value]}
    rendered = dump_manifest_yaml(manifest)
    assert value not in rendered
    restored = load_manifest_yaml(rendered)
    assert restored == manifest
    assert compute_capsule_id(restored) == compute_capsule_id(manifest)


@pytest.mark.parametrize("value", ["note\u0085line", "note\u2028line", "note\u2029line"])
def test_sealed_manifest_with_line_separator_value_still_verifies(tmp_path, value):
    (tmp_path / "payload.txt").write_bytes(b"fixture\n")
    ident = (
        CapsuleBuilder()
        .start_capsule(name=value, requirements={"paradigm": ["classical"], "max_qubit_count": 0})
        .seal(tmp_path)
    )
    result = CapsuleVerifier.verify_integrity(tmp_path, expected_id=ident)
    assert result["status"] == "pass" and result["manifest_authenticated"]


@pytest.mark.parametrize("ending", ["\r", "\r\n", "\n"])
def test_transport_line_breaks_preserve_block_and_quoted_values(ending):
    text = 'name: "x\n  y"\nblock: |\n  x\n  y\n'.replace("\n", ending)
    assert load_manifest_yaml(text) == {"name": "x y", "block": "x\ny\n"}


@pytest.mark.parametrize("escape", [r"\uD800", r"\uDE00", r"\uD83D\uDE00", r"\U0000D800"])
def test_surrogate_escapes_fail_at_loading_not_only_hashing(escape):
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(f'name: "{escape}"\n')
