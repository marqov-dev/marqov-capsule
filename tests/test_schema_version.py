# tests/test_schema_version.py
"""Tests for schema version negotiation (D5)."""

import pytest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestSchemaVersionNegotiation:
    """CapsuleValidator accepts v1.x schemas, rejects v2.x."""

    def _make_capsule_data(self, version="1.0.0"):
        """Build minimal valid capsule data with a given version string."""
        from marqov_capsule import CapsuleBuilder

        builder = CapsuleBuilder("version-test", description="Schema version test")
        builder.start_capsule(parameters={"x": 1})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        sealed = builder.seal_capsule(exit_code=0)
        sealed["version"] = version
        return sealed

    def test_accepts_v1_0_0(self):
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("1.0.0")
        result = validator.validate_data(data)
        assert result["valid"] is True, result["errors"]

    def test_accepts_v1_1_0(self):
        """Minor version bump is forward-compatible."""
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("1.1.0")
        result = validator.validate_data(data)
        assert result["valid"] is True, result["errors"]

    def test_accepts_v1_2_5(self):
        """Patch version bump is forward-compatible."""
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("1.2.5")
        result = validator.validate_data(data)
        assert result["valid"] is True, result["errors"]

    def test_rejects_v2_0_0(self):
        """Major version bump is breaking -- must reject."""
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("2.0.0")
        result = validator.validate_data(data)
        assert result["valid"] is False
        assert any("version" in e.lower() or "2.0.0" in e for e in result["errors"])

    def test_rejects_v3_1_0(self):
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("3.1.0")
        result = validator.validate_data(data)
        assert result["valid"] is False

    def test_rejects_invalid_version_string(self):
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("not-a-version")
        result = validator.validate_data(data)
        assert result["valid"] is False

    def test_error_message_for_v2_includes_guidance(self):
        """Error message should tell user what to do."""
        from marqov_capsule.validator import CapsuleValidator

        validator = CapsuleValidator()
        data = self._make_capsule_data("2.0.0")
        result = validator.validate_data(data)
        errors_text = " ".join(result["errors"])
        assert "2.0.0" in errors_text or "major version" in errors_text.lower()
