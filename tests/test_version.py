"""The declared version must agree everywhere it is written down.

`__version__` is a hand-maintained duplicate of the version in pyproject.toml:
nothing in the package reads it and, until this test existed, nothing checked
it. Preparing 0.1.1 bumped pyproject.toml and left `__version__` at "0.1.0",
which would have shipped a package whose metadata and attribute disagreed.
"""
import re
from importlib import metadata
from pathlib import Path

import marqov_capsule

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _declared_version():
    # Read the [project] version without taking a TOML parser dependency on
    # Python 3.10, where tomllib does not exist.
    text = PYPROJECT.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "no version found in pyproject.toml"
    return match.group(1)


def test_dunder_version_matches_pyproject():
    assert marqov_capsule.__version__ == _declared_version()


def test_installed_metadata_matches_source():
    # Catches a stale editable install as well as a mismatched bump.
    assert metadata.version("marqov-capsule") == marqov_capsule.__version__


def test_cli_reports_the_same_version():
    from click.testing import CliRunner

    from marqov_capsule.cli.main import cli

    result = CliRunner().invoke(cli, ["--version"])
    assert marqov_capsule.__version__ in result.output
