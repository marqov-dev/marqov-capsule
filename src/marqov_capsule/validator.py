"""CapsuleValidator — validates capsule.yaml against spec/v1/capsule-schema.json."""
from __future__ import annotations

import datetime
import importlib.resources as _pkg_resources
import json
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema
    from jsonschema import Draft202012Validator, FormatChecker
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False

_schema_cache: dict | None = None
_format_checker_cache: "FormatChecker | None" = None


def _build_format_checker() -> "FormatChecker":
    """Build a FormatChecker that enforces ``format: date-time``.

    jsonschema's built-in "date-time" checker only registers itself if the
    optional ``rfc3339-validator`` package is installed; without it, no
    checker exists for "date-time" and — per JSON Schema semantics, where
    ``format`` is merely an annotation unless a checker understands it — the
    schema's ``format: date-time`` on created_at/sealed_at/start_time/end_time
    is silently unenforced. Registering our own stdlib-only checker here
    avoids adding a new dependency for a single format.
    """
    checker = FormatChecker()

    @checker.checks("date-time", raises=ValueError)
    def _check_date_time(value: object) -> bool:
        if not isinstance(value, str):
            return True  # format applies only to strings; type is checked separately
        text = value[:-1] + "+00:00" if value[-1:] in ("Z", "z") else value
        datetime.datetime.fromisoformat(text)
        return True

    return checker


def _get_format_checker() -> "FormatChecker":
    global _format_checker_cache
    if _format_checker_cache is None:
        _format_checker_cache = _build_format_checker()
    return _format_checker_cache


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
        if not _JSONSCHEMA_AVAILABLE:
            raise ImportError("jsonschema>=4.0 required: pip install marqov-capsule")

        schema = _load_schema()
        validator = Draft202012Validator(schema, format_checker=_get_format_checker())
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
        except yaml.YAMLError as e:
            return {"valid": False, "errors": [{"path": "/", "message": f"YAML parse error: {e}"}]}

        if not isinstance(capsule, dict):
            return {"valid": False, "errors": [{"path": "/", "message": "capsule.yaml must be a YAML mapping"}]}

        return cls.validate(capsule)
