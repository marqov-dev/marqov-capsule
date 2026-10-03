"""Grammar / canonicalization hardening (post-pilot, normative in spec v1 2.2/5).

Covers: base-10 leading-zero integers, the 2^53-1 integer-magnitude guard, NFC
normalization of keys/values/paths, path percent-encoding in .checksums,
duplicate-key rejection, and float-key canonical number formatting.
"""
import os
import unicodedata

import jcs
import pytest
import yaml

from marqov_capsule._canonical import (
    canonical_bytes,
    compute_capsule_id,
    load_manifest_yaml,
)
from marqov_capsule.builder import CapsuleBuilder, _checksum_path

_MAX_SAFE = 9007199254740991  # 2**53 - 1


# --- 1. leading-zero integers construct base-10 (never octal, never crash) ---

@pytest.mark.parametrize(
    "raw,expected",
    [("0755", 755), ("08540", 8540), ("007", 7), ("-0755", -755), ("0", 0), ("00", 0)],
)
def test_leading_zero_ints_are_base10(raw, expected):
    assert load_manifest_yaml(f"n: {raw}\n")["n"] == expected


# --- 2. integer-magnitude guard (fail closed above 2^53-1) ------------------

def test_max_safe_int_loads():
    assert load_manifest_yaml(f"n: {_MAX_SAFE}\n")["n"] == _MAX_SAFE


def test_over_max_safe_int_rejected_at_load():
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(f"n: {_MAX_SAFE + 1}\n")


def test_negative_over_max_safe_int_rejected_at_load():
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(f"n: {-(_MAX_SAFE + 1)}\n")


def test_over_max_safe_int_rejected_in_canonical():
    """A huge int passed programmatically must fail closed, not silently round."""
    with pytest.raises((ValueError, OverflowError)):
        canonical_bytes({"n": _MAX_SAFE + 2})


# --- 3. NFC normalization: NFD and NFC forms share one capsule ID ------------

def test_nfc_key_yields_same_id():
    nfd = unicodedata.normalize("NFD", "café")
    nfc = unicodedata.normalize("NFC", "café")
    assert nfd != nfc
    assert compute_capsule_id({nfd: 1}) == compute_capsule_id({nfc: 1})


def test_nfc_value_yields_same_id():
    nfd = unicodedata.normalize("NFD", "résumé")
    nfc = unicodedata.normalize("NFC", "résumé")
    assert nfd != nfc
    assert compute_capsule_id({"k": nfd}) == compute_capsule_id({"k": nfc})


def test_nfc_path_normalized_in_checksums_helper():
    nfd = unicodedata.normalize("NFD", "payload/café.json")
    nfc = unicodedata.normalize("NFC", "payload/café.json")
    assert nfd != nfc
    assert _checksum_path(nfd) == _checksum_path(nfc)


# --- 4. path percent-encoding (only %0A %0D %25 %5C, uppercase; space literal) -

def test_checksum_path_percent_encodes_specials():
    # newline, carriage return, percent, backslash -> uppercase triplets
    assert _checksum_path("a\nb") == "a%0Ab"
    assert _checksum_path("a\rb") == "a%0Db"
    assert _checksum_path("a%b") == "a%25b"
    assert _checksum_path("a\\b") == "a%5Cb"
    # percent is encoded first so an existing triplet is not double-decoded
    assert _checksum_path("a%5Cb") == "a%255Cb"
    # forward-slash separators and literal spaces are preserved
    assert _checksum_path("dir/a b.json") == "dir/a b.json"


@pytest.mark.skipif(os.name == "nt", reason="filename cannot exist on this filesystem")
def test_checksums_percent_encodes_special_filename(tmp_path):
    capsule_dir = tmp_path / "enc.capsule"
    payload = capsule_dir / "payload"
    payload.mkdir(parents=True)
    (payload / "a%b\\c\nd.json").write_text("{}")

    text = CapsuleBuilder().save_checksums(capsule_dir).read_text()
    assert "  payload/a%25b%5Cc%0Ad.json\n" in text


# --- 5. duplicate mapping keys are rejected ---------------------------------

def test_duplicate_mapping_key_rejected():
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml("a: 1\na: 2\n")


def test_duplicate_nested_key_rejected():
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml("x:\n  b: 1\n  b: 2\n")


def test_distinct_keys_still_load():
    assert load_manifest_yaml("a: 1\nb: 2\n") == {"a": 1, "b": 2}


# --- 6. non-string keys route through the value-side number formatter --------

def test_float_key_uses_canonical_number_form():
    # 100.0 -> "100" (ES6/JCS), not repr()'s "100.0"
    assert canonical_bytes({100.0: "x"}) == jcs.canonicalize({"100": "x"})
    assert canonical_bytes({2.5: "x"}) == jcs.canonicalize({"2.5": "x"})


def test_float_key_matches_float_value_form():
    # The key and an equal value must serialise to the same number spelling.
    assert canonical_bytes({100.0: 100.0}) == jcs.canonicalize({"100": 100.0})


def test_int_key_uses_canonical_number_form():
    assert canonical_bytes({5: "x"}) == jcs.canonicalize({"5": "x"})
