"""The test suite polices itself against the skip pattern behind #39 and #116.

A module-level ``pytest.importorskip`` removes the whole file from collection
on an install without that package. The base-install CI job exists precisely
to run the suite without numpy/scipy, and it silently lost 56 items this way.
Skips belong in fixtures applied to the tests that need the dependency.
"""
import re
from pathlib import Path

TESTS = Path(__file__).parent
MODULE_LEVEL_IMPORTORSKIP = re.compile(r"^pytest\.importorskip\(", re.MULTILINE)


def test_no_module_level_importorskip():
    offenders = sorted(
        p.name for p in TESTS.glob("test_*.py")
        if MODULE_LEVEL_IMPORTORSKIP.search(p.read_text(encoding="utf-8"))
    )
    assert offenders == [], (
        "module-level pytest.importorskip drops every test in the file on a base "
        f"install; move it into a fixture: {offenders}"
    )
