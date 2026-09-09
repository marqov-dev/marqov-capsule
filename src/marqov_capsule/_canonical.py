"""RFC 8785 canonical JSON and capsule ID computation."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

import jcs
import yaml
from yaml.constructor import ConstructorError


# The largest integer JSON/RFC-8785 (IEEE-754 double) round-trips exactly. Above
# this, ``jcs`` serialises through float() and silently loses precision, so any
# integer with a larger magnitude is rejected — fail closed rather than mint an
# ID over a value that cannot be reproduced.
_MAX_SAFE_INT = 2 ** 53 - 1  # 9007199254740991


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
        the last value — a tamper/ambiguity hazard for a content-addressed ID.
    """

    def construct_mapping(self, node, deep=False):
        """Like SafeConstructor.construct_mapping but rejects duplicate keys.

        A duplicate key makes the parsed mapping — and therefore the capsule ID —
        depend on which value the reader happens to keep. Fail closed instead.
        """
        if not isinstance(node, yaml.MappingNode):
            raise ConstructorError(
                None, None,
                f"expected a mapping node, but found {node.id}", node.start_mark,
            )
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found unhashable key ({exc})", key_node.start_mark,
                )
            if key in mapping:
                raise ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key ({key!r})", key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _construct_int_base10(loader: _ManifestLoader, node: yaml.Node) -> int:
    """Construct integers as base-10 with a magnitude guard.

    The implicit resolver only tags ``^[-+]?[0-9]+$`` scalars as ints, so the
    value is always plain (optionally signed) digits. ``int(value)`` reads it as
    decimal — the inherited ``construct_yaml_int`` would instead treat a leading
    zero as octal (``0755`` -> 493, ``08540`` -> crash), which is a YAML-1.1
    behaviour the spec forbids.
    """
    value = loader.construct_scalar(node)
    result = int(value, 10)
    if abs(result) > _MAX_SAFE_INT:
        raise ConstructorError(
            None, None,
            f"integer {result} exceeds the RFC 8785 safe range "
            f"(|n| <= {_MAX_SAFE_INT}); it cannot be canonicalised without "
            "precision loss",
            node.start_mark,
        )
    return result


_ManifestLoader.add_constructor("tag:yaml.org,2002:int", _construct_int_base10)


# Rebuild the implicit-resolver table from scratch rather than surgically
# deleting 1.1 regexes: the resolver set is small and doing it explicitly makes
# the accepted grammar auditable. Assigning a fresh dict into the subclass'
# __dict__ means add_implicit_resolver appends here, not onto SafeLoader.
_ManifestLoader.yaml_implicit_resolvers = {}

# bool — YAML 1.2 core (true/false and their capitalised forms only; NOT yes/no)
_ManifestLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

# null — matches PyYAML's own null resolver, including the empty scalar
_ManifestLoader.add_implicit_resolver(
    "tag:yaml.org,2002:null",
    re.compile(r"^(?:~|null|Null|NULL|)$"),
    ["~", "n", "N", ""],
)

# int — decimal only. No hex (0x), octal (0o/0NN), binary, underscores, or
# sexagesimal. Registered before float so a bare integer resolves as int.
_ManifestLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^[-+]?[0-9]+$"),
    list("-+0123456789"),
)

# float — JSON-shaped: must carry a decimal point or an exponent, so a plain
# integer never falls through to here. No sexagesimal, no underscores, no .inf.
_ManifestLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^[-+]?(?:(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
        r"|[0-9]+[eE][-+]?[0-9]+)$"
    ),
    list("-+0123456789."),
)


def load_manifest_yaml(text: str) -> Any:
    """Parse a capsule.yaml string with YAML 1.2 / JSON-aligned implicit typing.

    Use this everywhere a capsule manifest is read from disk. Never use
    yaml.safe_load on capsule manifests directly — its YAML 1.1 coercions break
    cross-emitter ID determinism.
    """
    return yaml.load(text, Loader=_ManifestLoader)  # noqa: S506


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
            f"integer {number} exceeds the RFC 8785 safe range "
            f"(|n| <= {_MAX_SAFE_INT})"
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
    """
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
