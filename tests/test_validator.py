import pytest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_validator_accepts_valid_capsule():
    from marqov_capsule import CapsuleBuilder
    from marqov_capsule.validator import CapsuleValidator

    # Build a capsule
    builder = CapsuleBuilder("valid-test", description="A valid test capsule")
    builder.start_capsule(parameters={"x": 1})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
    sealed = builder.seal_capsule(exit_code=0)

    # Use default schema
    validator = CapsuleValidator()
    result = validator.validate_data(sealed)
    assert result["valid"] is True, result.get("errors")


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_validator_rejects_invalid_capsule():
    from marqov_capsule.validator import CapsuleValidator

    validator = CapsuleValidator()
    result = validator.validate_data({"invalid": True})
    assert result["valid"] is False
    assert len(result["errors"]) > 0
