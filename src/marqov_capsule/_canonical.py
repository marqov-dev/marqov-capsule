"""RFC 8785 canonical JSON and capsule ID computation."""
from __future__ import annotations

import copy
import hashlib
from typing import Any

import jcs
import yaml


# ---------------------------------------------------------------------------
# Timestamp-safe YAML loader
# ---------------------------------------------------------------------------

class _ManifestLoader(yaml.SafeLoader):
    """SafeLoader with the timestamp implicit resolver removed.

    yaml.safe_load resolves unquoted ISO timestamps to Python datetime objects.
    The same key written with quotes loads as a plain string. This ambiguity
    means two emitters that differ only in quoting style produce capsules with
    different IDs — violating the cross-emitter determinism guarantee.

    By stripping the timestamp resolver, BOTH forms load as the string literal
    that appears in the YAML, so the ID is determined entirely by the string value.
    """

_ManifestLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers
          if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in copy.deepcopy(_ManifestLoader.yaml_implicit_resolvers).items()
}


def load_manifest_yaml(text: str) -> dict:
    """Parse a capsule.yaml string with timestamps preserved as strings.

    Use this everywhere a capsule manifest is read from disk. Never use
    yaml.safe_load on capsule manifests directly.
    """
    return yaml.load(text, Loader=_ManifestLoader)  # noqa: S506


# ---------------------------------------------------------------------------
# Canonical JSON helpers
# ---------------------------------------------------------------------------

def _coerce_for_canonical(obj: Any) -> Any:
    """Backstop: coerce datetime objects to ISO strings before canonicalisation.

    With load_manifest_yaml, manifests parsed from YAML never contain datetime
    objects. This coercion handles CapsuleBuilder callers that set timestamps
    via datetime.isoformat() and pass the dict directly to compute_capsule_id.
    """
    if isinstance(obj, dict):
        return {k: _coerce_for_canonical(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_for_canonical(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def canonical_bytes(obj: Any) -> bytes:
    """Return RFC 8785 canonical JSON encoding of obj."""
    return jcs.canonicalize(_coerce_for_canonical(obj))


def compute_capsule_id(capsule_dict: dict) -> str:
    """Return SHA-256 hex digest of RFC 8785 canonical JSON of capsule_dict.

    This is the capsule's content-addressed identity — stable across YAML
    emitters because it operates on the parsed dict, not raw YAML bytes.
    """
    return hashlib.sha256(canonical_bytes(capsule_dict)).hexdigest()
