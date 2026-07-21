"""CapsuleValidator — validates capsule.yaml against spec/v1/capsule-schema.json."""
from __future__ import annotations

import importlib.resources as _pkg_resources
import json
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema
    from jsonschema import Draft202012Validator
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False

_schema_cache: dict | None = None


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
        validator = Draft202012Validator(schema)
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
