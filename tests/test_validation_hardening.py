"""Untrusted timestamps and numeric policy declarations fail predictably."""
import json

import pytest
from click.testing import CliRunner

from marqov_capsule import CapsuleValidator
from marqov_capsule.cli.main import cli
from marqov_capsule.policy import VerificationPolicy, resolve_alpha


def manifest_with_timestamp(field, value):
    manifest = {"version": "1.0.0", "name": "timestamp-test", "lifecycle_state": "draft"}
    if field in {"created_at", "sealed_at"}:
        manifest[field] = value
    else:
        manifest["task_executions"] = [{
            "task_id": "550e8400-e29b-41d4-a716-446655440000",
            "status": "success", "result_type": "deterministic",
            "backend": {"provider": "local", "name": "simulator"}, field: value,
        }]
    return manifest


@pytest.mark.parametrize("field", ["created_at", "sealed_at", "start_time", "end_time"])
@pytest.mark.parametrize("value", ["not-a-date", "2026-02-30T00:00:00Z", "2026-09-09", "2026-09-09T12:00:00"])
def test_invalid_timestamps_have_structured_errors(field, value):
    result = CapsuleValidator.validate(manifest_with_timestamp(field, value))
    path = field if field in {"created_at", "sealed_at"} else f"task_executions/0/{field}"
    assert result["valid"] is False
    assert any(e["path"] == path and "date-time" in e["message"] for e in result["errors"])


@pytest.mark.parametrize("value", [
    "2026-09-09T00:00:00Z", "2026-09-09T12:30:00+02:00",
    "2026-09-09T00:00:00.123456Z", "2024-02-29T23:59:59-05:00",
])
def test_valid_rfc3339_dates_remain_valid(value):
    result = CapsuleValidator.validate(manifest_with_timestamp("created_at", value))
    assert result["valid"] is True, result


def test_cli_rejects_invalid_timestamp(tmp_path):
    (tmp_path / "capsule.yaml").write_text(json.dumps(manifest_with_timestamp("created_at", "tomorrow")))
    result = CliRunner().invoke(cli, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "created_at" in result.output


@pytest.mark.parametrize("value", [10**1000, -(10**1000), float("inf"), float("-inf")],
                         ids=["huge-positive", "huge-negative", "positive-infinity", "negative-infinity"])
def test_unrepresentable_threshold_falls_back_to_policy(value):
    policy = VerificationPolicy(epsilon=0.02, epsilon_drift=0.08, honor_calibration_drift=True)
    assert policy.resolve({"epsilon": value})["epsilon"] == 0.02
    assert policy.resolve({"tolerance_regime": "calibration_drift", "epsilon_drift": value})["epsilon"] == 0.08
    assert resolve_alpha(value) == 0.05


def test_large_but_representable_threshold_still_clamped():
    resolved = VerificationPolicy(epsilon=0.02).resolve({"epsilon": 10**200})
    assert resolved["epsilon"] == 0.02
    assert resolved["epsilon_clamped"] is True
