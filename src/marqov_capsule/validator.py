"""
Marqov Capsule Validator

Validates capsule data against the v1.0 JSON Schema.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import jsonschema
    import yaml
except ImportError:
    raise ImportError("Install marqov-capsule[validate] for CapsuleValidator")


class CapsuleValidator:
    """Validates Capsule manifest files and data against JSON Schema."""

    def __init__(self, schema_path: Optional[Path] = None):
        """Initialize validator with schema file.

        Args:
            schema_path: Path to capsule.schema.json. Defaults to the bundled
                         schema at schemas/v1/capsule.schema.json.
        """
        if schema_path is None:
            schema_path = Path(__file__).parent / "schemas" / "v1" / "capsule.schema.json"

        self.schema_path = schema_path
        with open(schema_path) as f:
            self.schema = json.load(f)

        # Create validator instance
        self.validator = jsonschema.Draft7Validator(self.schema)

    def validate_data(self, data: dict) -> dict:
        """Validate capsule data dict against schema.

        Args:
            data: Parsed capsule data as a dictionary

        Returns:
            Dictionary with validation results:
                - valid: bool
                - errors: list of error messages
                - warnings: list of warning messages
        """
        errors = []
        for error in self.validator.iter_errors(data):
            error_path = ".".join(str(p) for p in error.path)
            errors.append(f"{error_path}: {error.message}")
        warnings = self._semantic_checks(data)
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def validate_file(self, capsule_path: Path) -> Dict[str, Any]:
        """Validate a capsule.yaml file.

        Args:
            capsule_path: Path to capsule.yaml file

        Returns:
            Dictionary with validation results:
                - valid: bool
                - errors: list of error messages
                - warnings: list of warning messages
        """
        # Load YAML file
        try:
            with open(capsule_path) as f:
                capsule_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return {
                "valid": False,
                "errors": [f"YAML parsing error: {e}"],
                "warnings": [],
            }
        except FileNotFoundError:
            return {
                "valid": False,
                "errors": [f"File not found: {capsule_path}"],
                "warnings": [],
            }

        return self.validate_data(capsule_data)

    def _semantic_checks(self, data: Dict[str, Any]) -> List[str]:
        """Perform semantic checks beyond schema validation.

        Args:
            data: Parsed capsule data

        Returns:
            List of warning messages
        """
        warnings = []

        # Check lifecycle state consistency
        lifecycle_state = data.get("lifecycle_state")
        sealed_at = data.get("sealed_at")
        sealed_by = data.get("sealed_by")

        if lifecycle_state in ["sealed", "archived"]:
            if not sealed_at:
                warnings.append(
                    f"Lifecycle state is '{lifecycle_state}' but sealed_at is null"
                )
            if not sealed_by:
                warnings.append(
                    f"Lifecycle state is '{lifecycle_state}' but sealed_by is null"
                )

        # Check execution section populated for sealed capsules
        if lifecycle_state in ["sealed", "archived"]:
            execution = data.get("execution", {})
            if not execution.get("start_time"):
                warnings.append("Sealed capsule missing execution.start_time")
            if not execution.get("end_time"):
                warnings.append("Sealed capsule missing execution.end_time")
            if execution.get("exit_code") is None:
                warnings.append("Sealed capsule missing execution.exit_code")

        # Check digests populated for sealed capsules
        if lifecycle_state in ["sealed", "archived"]:
            digests = data.get("digests", {})
            for key in ["workflow", "environment", "backends", "results"]:
                if not digests.get(key):
                    warnings.append(f"Sealed capsule missing digest: {key}")

        # Check cost tracking
        cost = data.get("cost", {})
        estimated = cost.get("estimated_cost_usd")
        actual = cost.get("actual_cost_usd")
        max_budget = cost.get("max_budget_usd")

        if max_budget and estimated and estimated > max_budget:
            warnings.append(
                f"Estimated cost (${estimated}) exceeds max budget (${max_budget})"
            )

        if max_budget and actual and actual > max_budget:
            warnings.append(
                f"Actual cost (${actual}) exceeds max budget (${max_budget})"
            )

        # Check verification results
        verifications = data.get("verifications", [])
        if lifecycle_state in ["sealed", "archived"] and not verifications:
            warnings.append(
                "Sealed capsule has no verification reports - consider running verification"
            )

        return warnings

    def validate_directory(self, capsule_dir: Path) -> Dict[str, Any]:
        """Validate a complete capsule directory.

        Args:
            capsule_dir: Path to capsule directory

        Returns:
            Dictionary with validation results
        """
        results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "files": {},
        }

        # Check capsule.yaml exists
        capsule_yaml = capsule_dir / "capsule.yaml"
        if not capsule_yaml.exists():
            results["valid"] = False
            results["errors"].append("Missing capsule.yaml")
            return results

        # Validate capsule.yaml
        capsule_result = self.validate_file(capsule_yaml)
        results["files"]["capsule.yaml"] = capsule_result
        results["valid"] = results["valid"] and capsule_result["valid"]
        results["errors"].extend(capsule_result["errors"])
        results["warnings"].extend(capsule_result["warnings"])

        # Load capsule data to check file references
        with open(capsule_yaml) as f:
            capsule_data = yaml.safe_load(f)

        # Check referenced files exist
        for ref_field, ref_file in [
            ("workflow_ref", capsule_data.get("workflow_ref")),
            ("environment_ref", capsule_data.get("environment_ref")),
            ("backends_ref", capsule_data.get("backends_ref")),
        ]:
            if ref_file:
                ref_path = capsule_dir / ref_file
                if not ref_path.exists():
                    results["warnings"].append(
                        f"Referenced file not found: {ref_file}"
                    )

        # Check expected directories
        lifecycle_state = capsule_data.get("lifecycle_state")
        if lifecycle_state in ["sealed", "archived"]:
            for dir_name in ["artifacts", "provenance"]:
                dir_path = capsule_dir / dir_name
                if not dir_path.exists():
                    results["warnings"].append(
                        f"Sealed capsule missing {dir_name}/ directory"
                    )

        return results
