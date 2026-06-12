import hashlib
from pathlib import Path
import pytest
from marqov_capsule.verifier import CapsuleVerifier

pytest.importorskip("numpy")
pytest.importorskip("scipy")

FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


def test_identical_distributions_verified():
    """When ref == new, TVD upper CI should be well below epsilon.

    Using 10,000 shots so the CI upper bound is comfortably < 0.05.
    With 1,000 shots and a 2-outcome distribution the 97.5th-percentile CI upper
    bound is ~0.0502, which sits exactly on the threshold and flakes ~50% of runs.
    """
    counts = {"00": 5000, "11": 5000}  # 10,000 shots
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
        seed=12345,
    )
    assert result["verdict"] == "VERIFIED"
    assert result["metrics"]["tvd_ci_upper"] <= 0.05


def test_completely_different_distributions_rejected():
    ref = {"00": 1000}
    new = {"11": 1000}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "REJECTED"


def test_low_shots_inconclusive():
    counts = {"00": 5, "11": 5}  # 10 shots total
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "shots" in result["reason"].lower()


def test_calibration_drift_uses_epsilon_drift():
    """calibration_drift regime uses epsilon_drift not epsilon.

    Invariant: calibration_drift must never be stricter than strict mode for the
    same distribution pair. Verified by rank comparison on the verdict ordering.
    """
    ref = {"00": 500, "11": 490, "01": 10}
    new = {"00": 480, "11": 510, "01": 10}
    verifier = CapsuleVerifier()
    strict_result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"},
        seed=12345,
    )
    drift_result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.02, "epsilon_drift": 0.10, "min_shots": 100, "tolerance_regime": "calibration_drift"},
        seed=12345,
    )
    assert drift_result["metrics"]["epsilon_used"] == 0.10
    # Drift regime must not be stricter
    verdicts = ("VERIFIED", "INCONCLUSIVE", "REJECTED")
    strict_rank = verdicts.index(strict_result["verdict"])
    drift_rank = verdicts.index(drift_result["verdict"])
    assert drift_rank <= strict_rank, (
        f"calibration_drift ({drift_result['verdict']}) stricter than strict ({strict_result['verdict']})"
    )


def test_epsilon_drift_defaults_to_0_08_when_absent():
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.02,
            "min_shots": 100,
            "tolerance_regime": "calibration_drift",
            # epsilon_drift deliberately absent
        },
    )
    assert result["metrics"]["epsilon_used"] == 0.08


def test_metrics_include_diagnostics_not_verdict():
    ref = {"00": 500, "11": 500}
    new = {"00": 495, "11": 505}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
        seed=12345,
    )
    m = result["metrics"]
    assert "chi_squared_p_value" in m
    assert "energy_distance" in m
    assert "tvd_ci_lower" in m
    assert "tvd_ci_upper" in m
    assert "bootstrap_resamples" in m
    assert m["bootstrap_resamples"] == 9999
    assert "rng_seed" in m
    assert m["rng_seed"] == 12345


def test_energy_distance_uses_hamming_metric():
    """Energy distance must use Hamming distance on bitstrings, not index proximity."""
    # "00" and "11" are Hamming-distance 2; "00" and "01" are Hamming-distance 1.
    verifier = CapsuleVerifier()
    far = verifier.verify_statistical(
        ref_counts={"00": 1000},
        new_counts={"11": 1000},
        verification_settings={"epsilon": 0.5, "min_shots": 100, "tolerance_regime": "strict"},
        seed=12345,
    )
    near = verifier.verify_statistical(
        ref_counts={"00": 1000},
        new_counts={"01": 1000},
        verification_settings={"epsilon": 0.5, "min_shots": 100, "tolerance_regime": "strict"},
        seed=12345,
    )
    assert far["metrics"]["energy_distance"] > near["metrics"]["energy_distance"]


def test_verify_checksums_pass(tmp_path):
    import yaml
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    f = payload / "results.json"
    f.write_text('{"counts": {"00": 500}}')
    digest = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
    checksums = {"payload/results.json": digest}
    (capsule_dir / ".checksums").write_text(yaml.dump(checksums, sort_keys=True))

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "pass"


def test_verify_checksums_fail_on_tampered_file(tmp_path):
    import yaml
    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    f = payload / "results.json"
    f.write_text('{"counts": {"00": 500}}')
    digest = "sha256:" + hashlib.sha256(b"original content").hexdigest()
    checksums = {"payload/results.json": digest}
    (capsule_dir / ".checksums").write_text(yaml.dump(checksums, sort_keys=True))

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"


def test_deterministic_verification_exact_match():
    verifier = CapsuleVerifier()
    result = verifier.verify_deterministic(
        ref_data={"value": 42},
        new_data={"value": 42},
    )
    assert result["verdict"] == "VERIFIED"


def test_deterministic_verification_mismatch():
    verifier = CapsuleVerifier()
    result = verifier.verify_deterministic(
        ref_data={"value": 42},
        new_data={"value": 43},
    )
    assert result["verdict"] == "REJECTED"
