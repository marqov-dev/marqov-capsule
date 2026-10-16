"""Load-phase rejection and writer roundtrips from the independent release review."""

from datetime import datetime, timezone

import pytest
import yaml

from marqov_capsule._canonical import (
    canonical_bytes,
    coerce_for_canonical,
    compute_capsule_id,
    dump_manifest_yaml,
    load_manifest_yaml,
)


@pytest.mark.parametrize(
    "tag,value",
    [
        ("null", "foo"),
        ("null", "null\\n"),
        ("null", " null"),
        ("bool", "true\\n"),
        ("int", "1\\n"),
        ("float", "1.5\\n"),
    ],
)
def test_bad_explicit_tags_rejected_by_loader_before_hashing(tag, value):
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(f'a: !!{tag} "{value}"\n')


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_unindented_quoted_continuation_is_load_error(quote, ending):
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(f"a: {quote}first{ending}second{quote}{ending}")


def test_direct_writer_coerces_legacy_keys_dates_and_nfc():
    value = {
        1: {"e\u0301": datetime(2026, 10, 14, tzinfo=timezone.utc)},
        "nested": [{False: "value"}],
    }
    restored = load_manifest_yaml(dump_manifest_yaml(value))
    assert restored == coerce_for_canonical(value)
    assert compute_capsule_id(restored) == compute_capsule_id(value)


def test_direct_writer_rejects_key_coercion_collision():
    with pytest.raises(ValueError, match="collide"):
        dump_manifest_yaml({1: "first", "1": "second"})


@pytest.mark.parametrize(
    "value",
    [
        "one\ntwo",
        "one\n\ntwo",
        "one\n  two\nthree",
        "\nleading",
        "trailing\n",
        "quoted ' single and double \"\nnext",
        "\\\nnext",
        "line\n\tvalue",
        "line\n # text",
    ],
)
def test_writer_multiline_strings_remain_readable_in_nested_values_and_keys(value):
    obj = {"outer": {value: [value, {"text": value}]}}
    assert canonical_bytes(load_manifest_yaml(dump_manifest_yaml(obj))) == canonical_bytes(obj)
