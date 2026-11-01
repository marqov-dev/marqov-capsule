"""RFC 8785 canonical JSON and capsule ID computation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

import jcs
import yaml
from yaml.composer import ComposerError
from yaml.constructor import ConstructorError
from yaml.scanner import ScannerError

# The largest integer JSON/RFC-8785 (IEEE-754 double) round-trips exactly. Above
# this, ``jcs`` serialises through float() and silently loses precision, so any
# integer with a larger magnitude is rejected — fail closed rather than mint an
# ID over a value that cannot be reproduced.
_MAX_SAFE_INT = 2**53 - 1  # 9007199254740991

# Deepest nesting a manifest may have. A real manifest is ~5 levels deep; the
# cap exists so a hostile document is rejected by the composer with a clean
# error rather than by the interpreter with RecursionError (#122).
_MAX_NESTING_DEPTH = 64


class ManifestError(yaml.YAMLError):
    """A capsule manifest could not be loaded.

    Raised for anything the loader rejects that is not already a structured
    PyYAML error, so every ``except yaml.YAMLError`` in the verifier, the
    validator and the CLI catches the whole family (#122).
    """


# ---------------------------------------------------------------------------
# YAML 1.2 / JSON-aligned manifest loader
# ---------------------------------------------------------------------------


class _ManifestLoader(yaml.SafeLoader):
    """SafeLoader restricted to YAML 1.2 core / JSON-compatible implicit typing.

    PyYAML's ``SafeLoader`` uses the YAML **1.1** implicit resolvers. Those
    coerce far more than JSON does, and every one of these is a cross-emitter
    determinism hazard: two conformant emitters can write byte-identical
    ``capsule.yaml`` and yet a YAML-1.1 reader and a YAML-1.2 reader parse them
    to different Python values, hence different canonical JSON, hence different
    capsule IDs. The 1.1-only coercions dropped here are:

      * ``timestamp``            ``2026-06-11T00:00:00Z`` -> datetime
      * ``yes``/``no``/``on``/``off`` (and ``y``/``n``) -> bool
      * ``0x1A``/``0o27``/``027`` (hex/octal) -> int
      * ``1_000`` (underscored digits) -> int/float
      * ``12:30:00`` (sexagesimal) -> int/float

    After this, an unquoted scalar is typed only when it is unambiguously a
    JSON value: ``true``/``false`` -> bool, ``null`` -> None, a plain decimal
    integer -> int, a decimal/exponent float -> float. Everything else — hex,
    sexagesimal, ``yes``, ISO timestamps — reads as the literal string, exactly
    as a YAML 1.2 (JSON-schema) implementation would.

    On top of the resolver table this loader also:
      * constructs integers as base-10 (an all-digit leading-zero scalar is a
        decimal, never octal — ``0755`` -> 755, ``007`` -> 7, ``08540`` -> 8540)
        and rejects any integer whose magnitude exceeds ``_MAX_SAFE_INT``;
      * rejects duplicate mapping keys, which SafeLoader silently collapses to
        the last value — a tamper/ambiguity hazard for a content-addressed ID —
        and mapping keys that are not strings;
      * rejects anchors used through aliases. Aliases have no JSON
        representation, and an aliased manifest of a few hundred bytes expands
        to a tree that takes hours to canonicalise (billion laughs, #110);
      * rejects explicit tags outside the core set (``!!timestamp``,
        ``!!binary``, ``!!set``, ``!!omap``, ``!!pairs``, local tags) and
        applies the 1.2 grammar to explicitly tagged ``!!int``/``!!float``/
        ``!!bool`` scalars, so a tagged scalar can never raise a bare Python
        exception out of a SafeConstructor constructor (#122);
      * caps nesting depth at ``_MAX_NESTING_DEPTH``.
    """

    def __init__(self, stream):
        super().__init__(stream)
        self._depth = 0

    def scan_directive(self):
        token = super().scan_directive()
        if token.name not in {"YAML", "TAG"}:
            raise ManifestError(f"unsupported manifest directive %{token.name}")
        if token.name == "YAML" and token.value not in {(1, 1), (1, 2)}:
            raise ManifestError("manifest YAML directive must name 1.1 or 1.2")
        return token

    def scan_flow_scalar_breaks(self, double, start_mark):
        chunks = super().scan_flow_scalar_breaks(double, start_mark)
        # SafeLoader intentionally relaxes quoted continuation indentation.
        # Require the containing block's indentation plus one space, just as
        # the YAML 1.2 reader does. A root flow collection has indent -1 and
        # may continue at column zero. Blank lines are consumed by the parent.
        if self.line > start_mark.line and self.indent >= 0:
            prefix = self.buffer[self.pointer - self.column : self.pointer]
            if not prefix.startswith(" " * (self.indent + 1)):
                raise ScannerError(
                    "while scanning a quoted scalar",
                    start_mark,
                    "continuation must be indented beyond its containing block",
                    self.get_mark(),
                )
        return chunks

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise ComposerError(
                None,
                None,
                f"found alias *{event.anchor}: aliases are not permitted in a "
                "capsule manifest (they have no JSON representation and are a "
                "denial-of-service vector)",
                event.start_mark,
            )
        self._depth += 1
        try:
            if self._depth > _MAX_NESTING_DEPTH:
                event = self.peek_event()
                raise ComposerError(
                    None,
                    None,
                    f"nesting depth exceeds {_MAX_NESTING_DEPTH}",
                    event.start_mark,
                )
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node, deep=False):
        """Like SafeConstructor.construct_mapping but rejects duplicate keys
        and keys that are not strings.

        A duplicate key makes the parsed mapping — and therefore the capsule ID —
        depend on which value the reader happens to keep. Fail closed instead.

        JSON object keys are strings, so a key the profile types as something
        else (``1:``, ``true:``, ``~:``) has no canonical form two readers
        agree on. Stringifying it loses information — an unquoted ``00:`` reads
        as the integer 0 and would become ``"0"`` — so it is rejected; quote
        the key (spec §5).
        """
        if not isinstance(node, yaml.MappingNode):
            raise ConstructorError(
                None,
                None,
                f"expected a mapping node, but found {node.id}",
                node.start_mark,
            )
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found unhashable key ({exc})",
                    key_node.start_mark,
                ) from exc
            if not isinstance(key, str):
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found non-string key ({key!r}): mapping keys must be strings "
                    "in a capsule manifest; quote the key",
                    key_node.start_mark,
                )
            if key in mapping:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key ({key!r})",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


# The YAML 1.2 core / JSON-shaped scalar grammars. Shared by the implicit
# resolver table below and by the explicit-tag constructors, so ``!!int 0x10``
# is rejected by exactly the rule that makes a bare ``0x10`` a string.
_BOOL_RE = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")
_NULL_RE = re.compile(r"^(?:~|null|Null|NULL|)$")
_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_FLOAT_RE = re.compile(
    r"^[-+]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
    r"|[0-9]+[eE][-+]?[0-9]+)$"
)
# Any decimal literal longer than this is outside the safe range regardless
# of its digits; checking length first keeps a 5000-digit literal from
# reaching int(), which refuses (ValueError) above 4300 digits (#93).
_MAX_INT_LITERAL_LEN = len(str(_MAX_SAFE_INT)) + 1  # sign + 16 digits


def _construct_manifest_string(loader: _ManifestLoader, node: yaml.ScalarNode) -> str:
    value = loader.construct_scalar(node)
    if re.search(r"[\ud800-\udfff]", value):
        raise ConstructorError(
            None,
            None,
            "surrogate escapes are not Unicode scalars; use a literal or full scalar escape",
            node.start_mark,
        )
    return value


def _construct_int_base10(loader: _ManifestLoader, node: yaml.ScalarNode) -> int:
    """Construct integers as base-10 with a magnitude guard.

    The implicit resolver only tags ``^[-+]?[0-9]+$`` scalars as ints, so an
    implicitly typed value is always plain (optionally signed) digits; an
    explicitly tagged ``!!int`` scalar is held to the same grammar, so hex,
    octal, underscores and garbage are rejected rather than crashing
    ``int()``. ``int(value)`` reads it as decimal — the inherited
    ``construct_yaml_int`` would instead treat a leading zero as octal
    (``0755`` -> 493, ``08540`` -> crash), which is a YAML-1.1 behaviour the
    spec forbids.
    """
    value = loader.construct_scalar(node)
    if not _INT_RE.fullmatch(value):
        raise ConstructorError(
            None,
            None,
            f"found {value!r}: not a decimal integer in the YAML 1.2 / JSON profile",
            node.start_mark,
        )
    if len(value) > _MAX_INT_LITERAL_LEN or abs(result := int(value, 10)) > _MAX_SAFE_INT:
        raise ConstructorError(
            None,
            None,
            f"integer {value[:20]}{'…' if len(value) > 20 else ''} exceeds the "
            f"RFC 8785 safe range (|n| <= {_MAX_SAFE_INT}); it cannot be "
            "canonicalised without precision loss",
            node.start_mark,
        )
    return result


def _construct_float_strict(loader: _ManifestLoader, node: yaml.ScalarNode) -> float:
    """``!!float`` held to the JSON-shaped grammar: no ``.inf``/``.nan``, no
    sexagesimal, no underscores — and never a bare ``ValueError`` from
    ``float()`` (#122)."""
    value = loader.construct_scalar(node)
    if not _FLOAT_RE.fullmatch(value) and not _INT_RE.fullmatch(value):
        raise ConstructorError(
            None,
            None,
            f"found {value!r}: not a finite decimal float in the YAML 1.2 / JSON profile",
            node.start_mark,
        )
    return float(value)


def _construct_null_strict(loader: _ManifestLoader, node: yaml.ScalarNode) -> None:
    value = loader.construct_scalar(node)
    if not _NULL_RE.fullmatch(value):
        raise ConstructorError(
            None,
            None,
            "explicit null must use a null spelling in the manifest profile",
            node.start_mark,
        )
    return None


def _construct_bool_strict(loader: _ManifestLoader, node: yaml.ScalarNode) -> bool:
    """``!!bool`` held to the YAML 1.2 core set: ``true``/``false`` and their
    capitalised forms only — never ``yes``/``no``, never a ``KeyError``."""
    value = loader.construct_scalar(node)
    if not _BOOL_RE.fullmatch(value):
        raise ConstructorError(
            None,
            None,
            f"found {value!r}: not a boolean in the YAML 1.2 / JSON profile",
            node.start_mark,
        )
    return value.lower() == "true"


def _reject_tag(tag: str):
    def construct(loader: _ManifestLoader, node: yaml.Node):
        raise ConstructorError(
            None,
            None,
            f"found tag {tag}: only the YAML core tags (str, int, float, bool, "
            "null, seq, map) are permitted in a capsule manifest",
            node.start_mark,
        )

    return construct


_ManifestLoader.add_constructor("tag:yaml.org,2002:str", _construct_manifest_string)
_ManifestLoader.add_constructor("tag:yaml.org,2002:int", _construct_int_base10)
_ManifestLoader.add_constructor("tag:yaml.org,2002:float", _construct_float_strict)
_ManifestLoader.add_constructor("tag:yaml.org,2002:bool", _construct_bool_strict)
_ManifestLoader.add_constructor("tag:yaml.org,2002:null", _construct_null_strict)
for _non_core in ("timestamp", "binary", "set", "omap", "pairs"):
    _ManifestLoader.add_constructor(f"tag:yaml.org,2002:{_non_core}", _reject_tag(f"!!{_non_core}"))


# Rebuild the implicit-resolver table from scratch rather than surgically
# deleting 1.1 regexes: the resolver set is small and doing it explicitly makes
# the accepted grammar auditable. Assigning a fresh dict into the subclass'
# __dict__ means add_implicit_resolver appends here, not onto SafeLoader.
_ManifestLoader.yaml_implicit_resolvers = {}

# bool — YAML 1.2 core (true/false and their capitalised forms only; NOT yes/no)
_ManifestLoader.add_implicit_resolver("tag:yaml.org,2002:bool", _BOOL_RE, list("tTfF"))

# null — matches PyYAML's own null resolver, including the empty scalar
_ManifestLoader.add_implicit_resolver("tag:yaml.org,2002:null", _NULL_RE, ["~", "n", "N", ""])

# int — decimal only. No hex (0x), octal (0o/0NN), binary, underscores, or
# sexagesimal. Registered before float so a bare integer resolves as int.
_ManifestLoader.add_implicit_resolver("tag:yaml.org,2002:int", _INT_RE, list("-+0123456789"))

# float — JSON-shaped: must carry a decimal point or an exponent, so a plain
# integer never falls through to here. No sexagesimal, no underscores, no .inf.
_ManifestLoader.add_implicit_resolver("tag:yaml.org,2002:float", _FLOAT_RE, list("-+0123456789."))


# These raw characters are either outside YAML's printable range or receive
# different line-break semantics in YAML 1.1 and 1.2 parsers. Escaped scalar
# values remain allowed; rejecting raw text avoids silently changing its value.
_RAW_MANIFEST_CHAR = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff\ufffe\uffff]"
)


def load_manifest_yaml(text: str) -> Any:
    """Parse a capsule.yaml string with YAML 1.2 / JSON-aligned implicit typing.

    Use this everywhere a capsule manifest is read from disk. Never use
    yaml.safe_load on capsule manifests directly — its YAML 1.1 coercions break
    cross-emitter ID determinism.
    """
    try:
        if _RAW_MANIFEST_CHAR.search(text):
            raise ManifestError("manifest contains a forbidden raw character; use a scalar escape")
        # LF, CRLF and CR-only are transport spellings of the same YAML line
        # breaks. Normalize before parsing, including within block scalars.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return yaml.load(text, Loader=_ManifestLoader)  # noqa: S506
    except yaml.YAMLError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as exc:
        # Belt and braces: the strict constructors above should leave nothing
        # for this clause, but the loader is a trust boundary and a bare
        # Python exception must never escape it (#122).
        raise ManifestError(
            f"manifest could not be loaded: {exc.__class__.__name__}: {exc}"
        ) from exc


def describe_manifest_error(exc: yaml.YAMLError) -> str:
    """One line locating a manifest load failure, without quoting the manifest.

    PyYAML's own message embeds the offending source line and the rejected
    key or tag, and an unmarked ``ManifestError`` can quote a directive name;
    any of these may be the credential the redactor exists to catch.
    """
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        return f"line {mark.line + 1}, column {mark.column + 1}"
    return exc.__class__.__name__


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------


class _ManifestDumper(yaml.SafeDumper):
    """SafeDumper whose quoting decisions match ``_ManifestLoader``.

    PyYAML's emitter writes a string as a plain (unquoted) scalar unless one of
    the *dumper's* implicit resolvers would type it as something else — and
    ``SafeDumper`` carries only the YAML 1.1 resolvers. The loader above types
    with the 1.2 / JSON profile, and the two disagree on exponent-shaped strings
    (``1e5``, ``1e-3``): 1.1's float regex requires a decimal point, so the
    string is emitted bare, and the 1.2 loader reads it back as a float. The ID
    the sealer publishes is then computed from a string while every verifier
    recomputes it from a float, so an untouched capsule fails layer 3 (#92).

    This dumper's resolver table is the *union* of SafeDumper's 1.1 rules and
    the loader's 1.2 rules, so a string is quoted whenever either profile would
    type it. ``yes``/``007``/``1e5``/``1.0.0`` all come out quoted; what the
    loader reads back is exactly what was written.
    """


def _represent_manifest_string(dumper, value):
    # PyYAML emits NEL/LS/PS literally with allow_unicode=True, even in quoted
    # strings. Force double quotes so those values use \N, \L and \P escapes.
    style = '"' if _RAW_MANIFEST_CHAR.search(value) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_ManifestDumper.add_representer(str, _represent_manifest_string)


for _first, _rules in _ManifestLoader.yaml_implicit_resolvers.items():
    for _tag, _regexp in _rules:
        # add_implicit_resolver copies SafeDumper's table into this subclass on
        # first use and appends — so SafeDumper itself is left untouched.
        _ManifestDumper.add_implicit_resolver(_tag, _regexp, [_first])


def dump_manifest_yaml(obj: Any) -> str:
    """Serialise a valid manifest value in its canonical-ready form.

    Apply the same NFC, timestamp and legacy typed-key conversion as ID
    computation. Readback preserves that converted value, not the original
    Python key types. Key collisions fail rather than silently losing a value.

    Use this everywhere a capsule manifest is written — ``yaml.dump`` and
    ``yaml.safe_dump`` quote for YAML 1.1 and silently change the type of
    exponent-shaped strings under this project's loader (#92).
    """
    return yaml.dump(
        coerce_for_canonical(obj),
        Dumper=_ManifestDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


# ---------------------------------------------------------------------------
# Canonical JSON helpers
# ---------------------------------------------------------------------------


def _nfc(text: str) -> str:
    """Unicode NFC normalisation — the spec's canonical string form (§2.2/§5).

    Two byte sequences that are canonically-equivalent under Unicode (e.g. a
    precomposed 'é' vs 'e' + combining acute) must produce one capsule ID, so
    every string that feeds the ID — mapping keys, string values, payload paths —
    is normalised to NFC first.
    """
    return unicodedata.normalize("NFC", text)


def _canonical_number_str(number: int | float) -> str:
    """Return the RFC 8785 / ES6 number spelling for ``number``.

    Delegates to ``jcs`` so a numeric mapping key is spelled exactly as the same
    number would be as a value (``100.0`` -> ``"100"``, ``2.5`` -> ``"2.5"``),
    rather than via ``repr`` which diverges (``repr(100.0) == "100.0"``).
    """
    if isinstance(number, int) and not isinstance(number, bool) and abs(number) > _MAX_SAFE_INT:
        raise ValueError(
            f"integer {number} exceeds the RFC 8785 safe range (|n| <= {_MAX_SAFE_INT})"
        )
    return jcs.canonicalize(number).decode("utf-8")


def _stringify_key(key: Any) -> str:
    """Return the JSON object-key string for a mapping key.

    JSON (and therefore RFC 8785) object keys are always strings; ``jcs`` raises
    on any other key type. A capsule.yaml can nonetheless carry non-string keys
    (e.g. an unquoted ``1:`` parses to int, ``true:`` to bool), so normalise
    them to a deterministic JSON-literal spelling instead of crashing. Numeric
    keys go through the same canonical number formatter used for values.
    """
    if isinstance(key, str):
        return _nfc(key)
    if isinstance(key, bool):
        return "true" if key else "false"
    if key is None:
        return "null"
    if hasattr(key, "isoformat"):
        return key.isoformat()
    if isinstance(key, (int, float)):
        return _canonical_number_str(key)
    return str(key)


def coerce_for_canonical(obj: Any) -> Any:
    """Return ``obj`` in a JSON-serialisable, canonical-ready shape.

    Normalisations, applied recursively:

      * datetime/date/time values -> ISO 8601 strings (``isoformat``). The
        builder may set timestamps as ``datetime`` objects; the ID must be
        computed from a string so it matches what a verifier reads back from the
        written YAML.
      * non-string mapping keys -> JSON-literal strings, so ``jcs.canonicalize``
        never raises on a manifest that happens to carry a typed key.
      * string keys and string values -> Unicode NFC.
      * integers beyond the RFC 8785 safe range -> ValueError (fail closed
        rather than let jcs round through float()).

    Used for BOTH capsule-ID computation and on-disk serialisation, so the two
    agree by construction and a datetime-bearing manifest round-trips.
    """
    if isinstance(obj, dict):
        normalized = {}
        for key, value in obj.items():
            canonical_key = _stringify_key(key)
            if canonical_key in normalized:
                raise ValueError("mapping keys collide after canonical normalization")
            normalized[canonical_key] = coerce_for_canonical(value)
        return normalized
    if isinstance(obj, (list, tuple)):
        return [coerce_for_canonical(v) for v in obj]
    if isinstance(obj, str):
        return _nfc(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, int) and not isinstance(obj, bool) and abs(obj) > _MAX_SAFE_INT:
        raise ValueError(
            f"integer {obj} exceeds the RFC 8785 safe range "
            f"(|n| <= {_MAX_SAFE_INT}); it cannot be canonicalised without "
            "precision loss"
        )
    return obj


# Backwards-compatible private alias (previous internal name).
_coerce_for_canonical = coerce_for_canonical


def canonical_bytes(obj: Any) -> bytes:
    """Return RFC 8785 canonical JSON encoding of obj."""
    return jcs.canonicalize(coerce_for_canonical(obj))


# The capsule ID is a self-describing identifier: ``mqc:<version>:<hex>``.
# ``version`` names the *whole* derivation procedure (canonicalisation +
# ``.checksums`` grammar + hash), so any reader can tell from the ID alone
# which format produced it (cf. OCI ``sha256:…``, SWHID ``swh:1:…``, IPFS
# CIDv1). A future format change increments the version without invalidating
# existing IDs; readers MUST reject an unrecognised version rather than guess.
CAPSULE_ID_SCHEME = "mqc"
CAPSULE_ID_VERSION = 1
_CAPSULE_ID_RE = re.compile(r"^mqc:([0-9]+):([0-9a-f]{64})$")


def compute_capsule_id(capsule_dict: dict) -> str:
    """Return the capsule's content-addressed identity: ``mqc:1:<64-hex>``.

    The hash is SHA-256 of the RFC 8785 canonical JSON of the parsed manifest
    — stable across YAML emitters because it operates on the parsed dict, not
    raw YAML bytes. The ``mqc:<version>:`` prefix makes the ID self-describing
    (see the module note); this is format version 1.

    Raises ValueError if ``capsule_dict`` is not a mapping: a manifest is a
    single mapping, and an empty document, a list or a bare scalar has no
    capsule ID (spec §5).
    """
    if not isinstance(capsule_dict, dict):
        raise ValueError(f"a capsule manifest must be a mapping; got {type(capsule_dict).__name__}")
    digest = hashlib.sha256(canonical_bytes(capsule_dict)).hexdigest()
    return f"{CAPSULE_ID_SCHEME}:{CAPSULE_ID_VERSION}:{digest}"


def parse_capsule_id(capsule_id: str) -> tuple[int, str]:
    """Parse ``mqc:<version>:<hex>`` into ``(version, hex)``.

    Raises ``ValueError`` on anything that is not a well-formed capsule ID.
    Consumers use this to dispatch on the format version and to reject an
    unrecognised version rather than guessing (spec §5, Layer 3).
    """
    m = _CAPSULE_ID_RE.match(capsule_id)
    if not m:
        raise ValueError(f"not a valid capsule ID: {capsule_id!r}")
    return int(m.group(1)), m.group(2)
