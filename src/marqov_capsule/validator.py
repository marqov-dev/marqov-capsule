"""CapsuleValidator — validates capsule.yaml against spec/v1/capsule-schema.json."""
from __future__ import annotations

import importlib.resources as _pkg_resources
import json
import math
import unicodedata
from pathlib import Path
from typing import Any

import yaml

import jsonschema
from jsonschema import Draft202012Validator

_schema_cache: dict | None = None


def _json_domain_errors(value, path="", ancestors=frozenset()):
    """Reject YAML/Python values that cannot participate in the spec JSON model."""
    def error(message):
        return {"path": path or "/", "message": message}
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            yield error("cyclic values are not permitted in a capsule manifest")
            return
        ancestors = ancestors | {id(value)}
        items = value.items() if isinstance(value, dict) else enumerate(value)
        normalized_keys = set()
        for key, child in items:
            if isinstance(value, dict) and not isinstance(key, str):
                yield error("manifest object keys must be strings")
                continue
            if isinstance(value, dict):
                normalized = unicodedata.normalize("NFC", key)
                if normalized in normalized_keys:
                    yield error("manifest keys collide after Unicode normalization")
                    continue
                normalized_keys.add(normalized)
            yield from _json_domain_errors(child, f"{path}/{key}".lstrip("/"), ancestors)
    elif isinstance(value, float) and not math.isfinite(value):
        yield error("manifest numbers must be finite")
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        yield error("manifest integer exceeds the canonical safe range")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        yield error("manifest values must belong to the JSON data model")


def _load_schema() -> dict:
    """Load the bundled schema via importlib.resources.

    Works for editable installs AND wheel installs. The schema is copied into
    marqov_capsule/schemas/ at build time (see pyproject.toml artifacts).
    Do NOT use Path(__file__).parent.parent/spec/... — that path doesn't exist
    after pip install.
    """
    global _schema_cache
    if _schema_cache is None:
        ref = _pkg_resources.files("marqov_capsule.schemas").joinpath("capsule-schema.json")
        _schema_cache = json.loads(ref.read_text(encoding="utf-8"))
    return _schema_cache


class CapsuleValidator:
    """Validates capsule.yaml against spec/v1/capsule-schema.json (JSON Schema 2020-12)."""

    @classmethod
    def validate(cls, capsule: dict[str, Any]) -> dict[str, Any]:
        """Validate a capsule manifest dict.

        Returns:
            {"valid": bool, "errors": [{"path": str, "message": str}]}
        """
        domain_errors = list(_json_domain_errors(capsule))
        if domain_errors:
            return {"valid": False, "errors": domain_errors}

        schema = _load_schema()
        # jsonschema format checks are opt-in, and date-time is only registered
        # when its validator dependency is installed. It is a runtime dependency
        # here so base and development installs enforce the same contract.
        validator = Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker(formats=["date-time", "uuid"])
        )
        errors = []
        for err in validator.iter_errors(capsule):
            parts = [str(p) for p in err.absolute_path]
            # For "required" errors, append the missing property name so callers
            # can detect which field is missing by inspecting the path.
            if err.validator == "required" and err.validator_value:
                # validator_value is the list of required fields; extract the
                # missing one from the message "'{name}' is a required property"
                import re
                m = re.search(r"'([^']+)'", err.message)
                if m:
                    parts.append(m.group(1))
            path = "/".join(parts) or "/"
            errors.append({"path": path, "message": err.message})

        return {"valid": len(errors) == 0, "errors": errors}

    @classmethod
    def validate_file(cls, filepath: str | Path) -> dict[str, Any]:
        """Validate a capsule.yaml file.

        Returns:
            {"valid": bool, "errors": [{"path": str, "message": str}]}
        """
        from marqov_capsule._canonical import load_manifest_yaml
        try:
            capsule = load_manifest_yaml(Path(filepath).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"valid": False, "errors": [{"path": "/", "message": f"File not found: {filepath}"}]}
        except IsADirectoryError:
            return {"valid": False, "errors": [{"path": "/", "message": f"Expected a capsule.yaml file, got a directory: {filepath}"}]}
        except UnicodeDecodeError:
            return {"valid": False, "errors": [{"path": "/", "message": "capsule.yaml must be UTF-8 text"}]}
        except OSError as e:
            return {"valid": False, "errors": [{"path": "/", "message": f"capsule.yaml could not be read: {type(e).__name__}"}]}
        except yaml.YAMLError as e:
            return {"valid": False, "errors": [{"path": "/", "message": f"YAML parse error: {e}"}]}

        if not isinstance(capsule, dict):
            return {"valid": False, "errors": [{"path": "/", "message": "capsule.yaml must be a YAML mapping"}]}

        return cls.validate(capsule)
