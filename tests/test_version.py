"""The version is declared once, in ``src/marqov_capsule/__init__.py``.

Preparing 0.1.1 bumped pyproject.toml and left `__version__` at "0.1.0": two
hand-maintained sources of truth. pyproject.toml now reads the version from the
package (`dynamic = ["version"]`), so there is nothing left to keep in step
(#104).
"""
import re
from importlib import metadata
from pathlib import Path

import pytest

import marqov_capsule

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _project_table():
    text = PYPROJECT.read_text(encoding="utf-8")
    start = text.index("[project]")
    end = re.search(r"^\[", text[start + 1:], re.MULTILINE)
    return text[start:start + 1 + end.start()] if end else text[start:]


def test_pyproject_does_not_declare_a_second_version():
    project = _project_table()
    assert not re.search(r"^version\s*=", project, re.MULTILINE)
    assert re.search(r'^dynamic\s*=\s*\[\s*"version"\s*\]', project, re.MULTILINE)


def test_dunder_version_is_a_release_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+([a-z]+\d+)?", marqov_capsule.__version__)


def test_installed_metadata_matches_source():
    installed = metadata.version("marqov-capsule")
    if installed != marqov_capsule.__version__:
        pytest.fail(
            f"installed metadata says {installed}, the source says "
            f"{marqov_capsule.__version__}: reinstall the editable package "
            "(`uv sync` or `pip install -e .`) after a version bump"
        )


def test_cli_reports_the_same_version():
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().endswith(f"version {marqov_capsule.__version__}")
