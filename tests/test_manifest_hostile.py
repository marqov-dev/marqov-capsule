"""The manifest loader is a trust boundary: hostile text must produce a
structured YAMLError (and a fail verdict / clean exit downstream), never an
arbitrary Python exception, a stall, or a traceback (#110, #122, #93).
"""

import time

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule._canonical import load_manifest_yaml
from marqov_capsule.cli.main import cli
from marqov_capsule.validator import CapsuleValidator
from marqov_capsule.verifier import CapsuleVerifier


def _alias_bomb(depth: int) -> str:
    lines = ["parameters:", "  a0: &a0 [x,x,x,x,x,x,x,x]"]
    for i in range(1, depth + 1):
        prev = f"*a{i - 1}"
        lines.append(f"  a{i}: &a{i} [{','.join([prev] * 8)}]")
    return "\n".join(lines) + "\n"


# (label, manifest text). Each one used to escape as a non-YAML exception or
# to stall; every one must now be a clean rejection.
HOSTILE = [
    ("alias-bomb-depth-8", _alias_bomb(8)),
    ("alias-simple", "a: &x 1\nb: *x\n"),
    ("alias-merge-key", "a: &x {k: 1}\nb:\n  <<: *x\n"),
    ("alias-cyclic", "parameters: &loop [*loop]\n"),
    ("timestamp-garbage", "a: !!timestamp foo\n"),
    ("timestamp-bad-day", "a: !!timestamp 2001-02-30\n"),
    ("timestamp-bad-hour", "a: !!timestamp 2001-01-01T25:00:00\n"),
    ("timestamp-bad-offset", "a: !!timestamp 2001-01-01T00:00:00+25:00\n"),
    ("timestamp-valid", "a: !!timestamp 2001-01-01\n"),
    ("float-garbage", "a: !!float foo\n"),
    ("float-nan", "a: !!float .nan\n"),
    ("float-inf", "a: !!float .inf\n"),
    ("int-garbage", "a: !!int foo\n"),
    ("int-hex", "a: !!int 0x10\n"),
    ("int-empty", "0: !!int\n"),
    ("int-octal-tagged", "a: !!int 0o17\n"),
    ("bool-garbage", "a: !!bool foo\n"),
    ("bool-yes", "a: !!bool yes\n"),
    ("binary", "a: !!binary aGk=\n"),
    ("set", "a: !!set {x: null}\n"),
    ("omap", "a: !!omap [b: 1]\n"),
    ("pairs", "a: !!pairs [b: 1]\n"),
    ("python-object", "a: !!python/object:os.system [echo]\n"),
    ("python-name", "a: !!python/name:sys.exit\n"),
    ("local-tag", "a: !custom 1\n"),
    ("deep-flow-sequence", "a: " + "[" * 1000 + "]" * 1000 + "\n"),
    ("deep-flow-mapping", "a: " + "{b: " * 1000 + "1" + "}" * 1000 + "\n"),
    (
        "deep-block-mapping",
        "".join("  " * i + f"k{i}:\n" for i in range(300)) + "  " * 300 + "v: 1\n",
    ),
    ("int-4300-digits", "big: " + "9" * 5000 + "\n"),
    ("int-tagged-huge", "big: !!int " + "9" * 5000 + "\n"),
]
IDS = [label for label, _ in HOSTILE]
TEXTS = [text for _, text in HOSTILE]

# The loader may legitimately *accept* these, but each one is still typed by
# the 1.2 profile and must not raise.
BENIGN_TAGGED = [
    ("a: !!str 5\n", {"a": "5"}),
    ("a: !!int 5\n", {"a": 5}),
    ("a: !!int -7\n", {"a": -7}),
    ("a: !!float 1e5\n", {"a": 100000.0}),
    ("a: !!float 2.5\n", {"a": 2.5}),
    ("a: !!bool true\n", {"a": True}),
    ("a: !!bool False\n", {"a": False}),
    ("a: !!null ''\n", {"a": None}),
    ("a: !!seq [1]\n", {"a": [1]}),
    ("a: !!map {b: 1}\n", {"a": {"b": 1}}),
    ("a: &anchor_without_use 1\n", {"a": 1}),
]


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_loader_raises_only_yaml_errors(text):
    started = time.perf_counter()
    with pytest.raises(yaml.YAMLError):
        load_manifest_yaml(text)
    assert time.perf_counter() - started < 5.0


@pytest.mark.parametrize("text,expected", BENIGN_TAGGED, ids=[t for t, _ in BENIGN_TAGGED])
def test_loader_accepts_core_tags_with_12_typing(text, expected):
    loaded = load_manifest_yaml(text)
    assert loaded == expected
    assert type(loaded["a"]) is type(expected["a"])


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_validate_file_fails_closed(text, tmp_path):
    (tmp_path / "capsule.yaml").write_text(text, encoding="utf-8")
    started = time.perf_counter()
    result = CapsuleValidator.validate_file(tmp_path / "capsule.yaml")
    assert time.perf_counter() - started < 5.0
    assert result["valid"] is False
    assert result["errors"][0]["path"] == "/"


@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_verify_integrity_fails_closed(text, tmp_path):
    (tmp_path / "capsule.yaml").write_text(text, encoding="utf-8")
    (tmp_path / ".checksums").write_bytes(b"")
    started = time.perf_counter()
    result = CapsuleVerifier.verify_integrity(tmp_path)
    assert time.perf_counter() - started < 5.0
    assert result["status"] == "fail"
    assert any("could not be parsed" in e for e in result["errors"])


@pytest.mark.parametrize("command", ["validate", "verify", "inspect", "seal", "pack"])
@pytest.mark.parametrize("text", TEXTS, ids=IDS)
def test_cli_commands_exit_1_without_traceback(command, text, tmp_path):
    (tmp_path / "capsule.yaml").write_text(text, encoding="utf-8")
    (tmp_path / ".checksums").write_bytes(b"")
    args = [command, str(tmp_path)]
    if command == "pack":
        args += ["-o", str(tmp_path.parent / "out.capsule")]
    started = time.perf_counter()
    result = CliRunner().invoke(cli, args)
    assert time.perf_counter() - started < 5.0
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert "Traceback" not in result.output


def test_alias_bomb_is_rejected_fast_even_at_depth_10(tmp_path):
    # Depth 10 would be hours / OOM if expanded (#110).
    (tmp_path / "capsule.yaml").write_text(_alias_bomb(10), encoding="utf-8")
    started = time.perf_counter()
    assert CapsuleValidator.validate_file(tmp_path / "capsule.yaml")["valid"] is False
    assert time.perf_counter() - started < 5.0


def test_rejection_messages_name_the_rule():
    with pytest.raises(yaml.YAMLError, match="alias"):
        load_manifest_yaml("a: &x 1\nb: *x\n")
    with pytest.raises(yaml.YAMLError, match="timestamp"):
        load_manifest_yaml("a: !!timestamp 2001-01-01\n")
    with pytest.raises(yaml.YAMLError, match="nesting"):
        load_manifest_yaml("a: " + "[" * 1000 + "]" * 1000)
    with pytest.raises(yaml.YAMLError, match="safe range"):
        load_manifest_yaml("a: " + "9" * 5000)


@pytest.fixture
def hypothesis_available():
    pytest.importorskip("hypothesis")


@pytest.mark.usefixtures("hypothesis_available")
def test_validate_file_never_raises_on_arbitrary_text(tmp_path):
    """Tripwire: whatever the text, validate_file returns a verdict."""
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    counter = {"n": 0}

    @settings(
        max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(st.text())
    def check(text):
        counter["n"] += 1
        safe = text.encode("utf-8", "replace").decode("utf-8")
        path = tmp_path / f"capsule-{counter['n']}.yaml"
        path.write_text(safe, encoding="utf-8")
        result = CapsuleValidator.validate_file(path)
        assert isinstance(result["valid"], bool)

    check()
