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
    assert json.loads(BUNDLED.read_text())["$id"].startswith("https://marqov.ai/")


def test_no_extras_advertise_unsupported_features():
    """The [verify] extra would install numpy and scipy for verify_statistical,
    which is not yet wired into any public CLI/API surface — no extra to
    advertise until it is."""
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


def test_no_dead_domain_references():
    """The product domain is marqov.ai (marketing) and app.marqov.ai (app).

    A sibling `.dev` domain is not in use. It originated in agent-written design
    docs, propagated into the schema `$id`, the spec README and a test, and then
    read as authoritative to everyone who found it afterwards. Pinned so it
    cannot come back silently.

    The needle is assembled at runtime so this guard does not trip on itself.
    """
    needle = "marqov" + "." + "dev"
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True,
                             check=True, cwd=ROOT).stdout.split("\0")
    hits = []
    for rel in tracked:
        if not rel:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, IsADirectoryError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line:
                if line == f"This previously read `{needle}`, which is not a domain in use — the product":
                    continue  # Only the exact historical explanation is exempt.
                hits.append(f"{rel}:{i}")
    assert not hits, f"{needle} is not a domain in use: {hits}"


def test_spec_prose_schema_id_matches_shipped_schema():
    prose = (ROOT / "spec/v1/README.md").read_text()
    match = re.search(r"Schema `\$id`: `([^`]+)`", prose)
    assert match, "Spec must advertise its schema identifier"
    assert match.group(1) == json.loads(BUNDLED.read_text())["$id"]


def test_ci_success_includes_every_job():
    import yaml
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    assert set(jobs["ci-success"]["needs"]) == set(jobs) - {"ci-success"}
