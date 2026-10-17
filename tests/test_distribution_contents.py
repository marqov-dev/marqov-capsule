"""Exercise the artifact boundary against files that must never be uploaded."""

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "distribution_check", Path(__file__).parents[1] / "tools/check_distribution.py"
)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

REQUIRED = [
    "pyproject.toml",
    "README.md",
    "LICENSE-CODE",
    "LICENSE-SPEC",
    "src/marqov_capsule/__init__.py",
    "spec/v1/capsule-schema.json",
    "examples/run_bell.py",
    "examples/seal_bell.py",
]


def archive(path, extra=()):
    with tarfile.open(path, "w:gz") as stream:
        for name in REQUIRED + list(extra):
            member = tarfile.TarInfo(f"marqov_capsule-0.1.0/{name}")
            member.size = 1
            stream.addfile(member, io.BytesIO(b"x"))
    return path


def test_release_sources_are_allowed(tmp_path):
    assert checks.check_sdist(archive(tmp_path / "source.tar.gz")) == len(REQUIRED)


@pytest.mark.parametrize(
    "name",
    [
        ".claude/worktrees/agent/spec/v1/capsule-schema.json",
        ".claude/worktrees/agent/README.md",
        "spec/.venv/local.py",
        "examples/__pycache__/example.pyc",
        "README.md",
        "../outside",
        "private-notes.txt",
    ],
)
def test_extra_workspace_or_ambiguous_content_is_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        checks.check_sdist(archive(tmp_path / "source.tar.gz", [name]))
