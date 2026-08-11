"""Invariants about what we ship.

Packaging mistakes are invisible locally — they only show up on the PyPI page
or in someone else's install, which for a one-shot immutable upload is the
wrong place to find them.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC_SCHEMA = ROOT / "spec/v1/capsule-schema.json"
BUNDLED = ROOT / "src/marqov_capsule/schemas/capsule-schema.json"


def test_exactly_one_schema_ships():
    """Two schemas with two different $ids is worse than none — an independent
    implementer cannot tell which is normative."""
    shipped = sorted(p for p in (ROOT / "src/marqov_capsule/schemas").rglob("*.json"))
    assert [p.name for p in shipped] == ["capsule-schema.json"], shipped


def test_bundled_schema_is_byte_identical_to_the_spec():
    assert BUNDLED.read_bytes() == SPEC_SCHEMA.read_bytes()


def test_schema_id_points_at_one_canonical_host():
    assert json.loads(BUNDLED.read_text())["$id"].startswith("https://marqov.dev/")


def test_no_extras_advertise_unsupported_features():
    """The [verify] extra installed numpy and scipy solely for
    verify_statistical, which warns callers not to trust it (#15)."""
    pyproject = (ROOT / "pyproject.toml").read_text()
    optional = re.search(r"\[project\.optional-dependencies\](.*?)(?=\n\[|\Z)", pyproject, re.S)
    names = re.findall(r"^(\w+) = \[", optional.group(1), re.M) if optional else []
    assert "verify" not in names, names


def test_readme_does_not_claim_cryptographic_verifiability():
    """No signatures ship, so the digest chain detects modification, not
    forgery. 'Tamper-evident' is the claim that survives scrutiny (#16)."""
    readme = (ROOT / "README.md").read_text().lower()
    assert "cryptographically verifiable" not in readme
    assert "immutable" in readme  # content-addressed immutability IS true
