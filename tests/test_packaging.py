"""Invariants about what we ship.

Packaging mistakes are invisible locally — they only show up on the PyPI page
or in someone else's install, which for a one-shot immutable upload is the
wrong place to find them.
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC_SCHEMA = ROOT / "spec/v1/capsule-schema.json"
BUNDLED = ROOT / "src/marqov_capsule/schemas/capsule-schema.json"
SPEC_README = ROOT / "spec/v1/README.md"


def _tracked_files() -> list[str]:
    """Every path Git tracks, relative to ROOT.

    Uses ``-z`` + NUL-splitting (not `.split()`) so tracked paths containing
    spaces aren't silently dropped, and ``check=True`` + ``cwd=ROOT`` so that
    running outside a git tree (unpacked sdist, a Docker image built without
    `.git`) raises instead of degrading to an empty, vacuously-passing list.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, cwd=ROOT, check=True,
    )
    return [p for p in result.stdout.split("\0") if p]


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


def test_no_dead_domain_references():
    """The product domain is marqov.ai (marketing) and app.marqov.ai (app).

    A sibling `.dev` host is not in use — it originated in agent-written design
    docs and once shipped in the schema `$id`. Pinning that one literal is not
    the fix: the defect *class* is "some non-canonical marqov.* host slips into
    the docs", and its sibling already shipped once for real, as `.com`, in
    marqov-sdk 0.3.0 (see the historical note in tools/check_urls.py). A guard
    for one literal doesn't catch the next one.

    So this checks every `marqov.<host>` occurrence in every tracked file
    against an allowlist of hosts actually in use — any stray host is caught
    regardless of which one it turns out to be.

    Two lines *document* a historical bad host in prose rather than using it
    live, and are exempted by exact (file, line) coordinates. Each exemption is
    keyed to a content marker that has nothing to do with the host itself, so
    writing the marker here doesn't also trip this check on this file — and if
    the line is ever edited, the marker stops matching and the assertion below
    fails loudly instead of the exemption silently widening to cover a real
    regression. (That silent-widening was the bug in the exemption this
    replaces: a whole file exempted by basename, hiding any real regression
    inside it.)
    """
    allowed_hosts = {"marqov.ai"}
    host_re = re.compile(r"marqov\.[a-zA-Z]+")

    # (relative path, 1-based line number) -> a substring, unrelated to the
    # host, that must still be present on that line for the exemption to hold.
    documented_historical_references = {
        ("RELEASING.md", 129): "previously read",
        ("tools/check_urls.py", 5): "class of defect",
    }

    hits = []
    for rel in _tracked_files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, IsADirectoryError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for host in host_re.findall(line):
                if host in allowed_hosts:
                    continue
                marker = documented_historical_references.get((rel, i))
                if marker and marker in line:
                    continue
                hits.append(f"{rel}:{i}: {host}")
    assert not hits, f"non-canonical marqov.* host(s) found: {hits}"


def test_spec_readme_id_matches_schema_id():
    """spec/v1/README.md documents the schema's `$id` in prose (§7).

    Nothing ties that prose to the schema file itself, so a future `$id` change
    could leave the CC-BY spec advertising a stale identifier to independent
    implementers with no test catching it. Extract-and-assert — the same idiom
    test_readme.py uses for the root README's CLI block — so the two cannot
    drift apart.
    """
    text = SPEC_README.read_text()
    match = re.search(r"Schema `\$id`: `([^`]+)`", text)
    assert match, "spec/v1/README.md has no `Schema $id: ...` line to extract"
    documented_id = match.group(1)
    actual_id = json.loads(SPEC_SCHEMA.read_text())["$id"]
    assert documented_id == actual_id, (
        f"spec/v1/README.md documents $id={documented_id!r}, "
        f"but capsule-schema.json's $id is {actual_id!r}"
    )
