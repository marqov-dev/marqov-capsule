import datetime
import hashlib
from pathlib import Path

import pytest

from marqov_capsule.verifier import CapsuleVerifier


@pytest.fixture
def statistical_dependencies():
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")


FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


@pytest.mark.usefixtures("statistical_dependencies")
def test_identical_distributions_verified():
    """When ref == new, the TVD upper confidence bound should be well below epsilon.

    Using 10,000 shots so the UCB is comfortably < 0.05.
    """
    counts = {"00": 5000, "11": 5000}  # 10,000 shots
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "VERIFIED"
    assert result["metrics"]["tvd_ucb"] <= 0.05


@pytest.mark.usefixtures("statistical_dependencies")
def test_identical_distributions_verified_at_large_outcome_count():
    """Regression test for #15: the old bootstrap CI rejected byte-identical
    distributions as non-reproducible above ~4 qubits (K=16+ outcomes) because
    it was miscalibrated at exactly this null. The old suite only covered
    K=2, the one regime where the defect was invisible — this covers K=64.

    epsilon=0.05 is the discriminating margin: at these inputs (K=64, 100
    shots/outcome) the old bootstrap CI returns INCONCLUSIVE at epsilon=0.05
    (it only clears the bar at looser epsilon, e.g. 0.1, where it returns
    VERIFIED with ci_upper ~0.0666 — which does not discriminate against the
    bug). The new closed-form UCB returns VERIFIED with tvd_ucb ~0.0216 here,
    so this test fails on the old code and passes on the new one.
    """
    counts = {format(i, "06b"): 100 for i in range(64)}  # K=64, 6,400 shots/arm
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "VERIFIED"
    assert result["metrics"]["total_variation_distance"] == 0.0


@pytest.mark.usefixtures("statistical_dependencies")
def test_completely_different_distributions_not_verified():
    """No valid construction lower-bounds true TVD from the biased plug-in
    estimator (#15) — clearly different inputs must not be VERIFIED, but the
    honest verdict is INCONCLUSIVE ("equivalence not demonstrated"), not an
    affirmative REJECTED claim the statistics cannot support."""
    ref = {"00": 1000}
    new = {"11": 1000}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    # chi-squared needs cell counts >= 5 on both arms; not met here, so it's
    # simply absent as a diagnostic — the verdict itself is the point of this test.
    assert "chi_squared_p_value" not in result["metrics"]


@pytest.mark.usefixtures("statistical_dependencies")
def test_tvd_ucb_clamped_to_one_at_disjoint_supports_and_shot_floor():
    """At the min_shots floor with disjoint supports, the McDiarmid slack term
    alone exceeds 1.0 (log(1/alpha) is large relative to the per-arm 1/n terms
    at n=100), so tvd_point + slack overshoots the schema's declared
    ``maximum: 1.0`` for tvd_ucb — this exact input regressed capsule-schema
    validation until the bound was clamped (#15 follow-up). TV(p,q) <= 1
    always holds, so clamping to 1.0 is a tightening, not a weakening, of the
    (1-alpha) coverage guarantee: it never fires unless the raw bound already
    exceeded the only value a TVD can legally take at its ceiling, so no
    verdict flips from INCONCLUSIVE to VERIFIED because of it."""
    ref = {"00": 100}
    new = {"11": 100}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    assert result["metrics"]["tvd_ucb"] == 1.0
    assert result["verdict"] == "INCONCLUSIVE"


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


@pytest.mark.usefixtures("statistical_dependencies")
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
    )
    drift_result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={
            "epsilon": 0.02,
            "epsilon_drift": 0.10,
            "min_shots": 100,
            "tolerance_regime": "calibration_drift",
        },
    )
    assert drift_result["metrics"]["epsilon_used"] == 0.10
    # Drift regime must not be stricter
    verdicts = ("VERIFIED", "INCONCLUSIVE")
    strict_rank = verdicts.index(strict_result["verdict"])
    drift_rank = verdicts.index(drift_result["verdict"])
    assert drift_rank <= strict_rank, (
        f"calibration_drift ({drift_result['verdict']}) stricter than strict ({strict_result['verdict']})"
    )


@pytest.mark.usefixtures("statistical_dependencies")
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


@pytest.mark.usefixtures("statistical_dependencies")
def test_metrics_include_diagnostics_not_verdict():
    ref = {"00": 500, "11": 500}
    new = {"00": 495, "11": 505}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=ref,
        new_counts=new,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    m = result["metrics"]
    assert "chi_squared_p_value" in m
    assert "energy_distance" in m
    assert "tvd_ucb" in m
    assert "alpha" in m
    assert m["alpha"] == pytest.approx(0.05)


@pytest.mark.usefixtures("statistical_dependencies")
def test_ci_level_is_ignored():
    """ci_level was the pre-fix name for the confidence-bound knob and was read
    raw from the untrusted settings dict (#15 follow-up). It must have zero
    effect now: only a policy-sourced ``alpha`` is honoured."""
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    baseline = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={"epsilon": 0.05, "min_shots": 100, "tolerance_regime": "strict"},
    )
    with_ci_level = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.05,
            "min_shots": 100,
            "tolerance_regime": "strict",
            "ci_level": 0.0,  # would give alpha=1.0 (zero slack) if honoured
        },
    )
    assert with_ci_level["metrics"]["alpha"] == baseline["metrics"]["alpha"] == pytest.approx(0.05)
    assert with_ci_level["metrics"]["tvd_ucb"] == baseline["metrics"]["tvd_ucb"]


@pytest.mark.parametrize("bad_ci_level", [0.0, 1.0, 1.5, "0.95"])
@pytest.mark.usefixtures("statistical_dependencies")
def test_malformed_ci_level_does_not_crash_or_widen_error_rate(bad_ci_level):
    """Reproduced failures of the pre-fix code: ci_level=0.0 -> alpha=1 (no
    slack, false VERIFIED on the bare point estimate); ci_level=1.0 ->
    ZeroDivisionError; ci_level=1.5 -> tvd_ucb=nan, silent INCONCLUSIVE;
    ci_level="0.95" -> TypeError. None of that reads through any more: the
    field is not consulted at all, so every one of these must behave exactly
    like its absence."""
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.05,
            "min_shots": 100,
            "tolerance_regime": "strict",
            "ci_level": bad_ci_level,
        },
    )
    assert result["metrics"]["alpha"] == pytest.approx(0.05)
    assert result["metrics"]["tvd_ucb"] == result["metrics"]["tvd_ucb"]  # not NaN


@pytest.mark.parametrize("bad_alpha", [0.0, 1.0, 1.5, -0.1, "0.05", None, float("nan"), True])
@pytest.mark.usefixtures("statistical_dependencies")
def test_malformed_alpha_falls_back_to_default(bad_alpha):
    """alpha is verifier-owned but still passes through the same guard as any
    other value coming from a settings dict — a resolved dict could in
    principle carry a bad value from a bug elsewhere, and the guard must not
    let that crash or produce a nan/degenerate bound."""
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.05,
            "min_shots": 100,
            "tolerance_regime": "strict",
            "alpha": bad_alpha,
        },
    )
    assert result["metrics"]["alpha"] == pytest.approx(0.05)
    assert result["metrics"]["tvd_ucb"] == result["metrics"]["tvd_ucb"]  # not NaN


@pytest.mark.usefixtures("statistical_dependencies")
def test_policy_resolved_alpha_carries_through_to_metrics():
    """A policy.resolve() dict's alpha must reach the metrics untouched."""
    from marqov_capsule.policy import VerificationPolicy

    policy = VerificationPolicy(epsilon=0.05, min_shots=100, alpha=0.01)
    settings = policy.resolve({})
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings=settings,
    )
    assert result["metrics"]["alpha"] == pytest.approx(0.01)


@pytest.mark.usefixtures("statistical_dependencies")
def test_valid_alpha_is_honoured():
    """A well-formed alpha (as policy.resolve would emit) changes the bound,
    proving the guard does not silently ignore good values too."""
    counts = {"00": 500, "11": 500}
    verifier = CapsuleVerifier()
    loose = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.5,
            "min_shots": 100,
            "tolerance_regime": "strict",
            "alpha": 0.5,
        },
    )
    tight = verifier.verify_statistical(
        ref_counts=counts,
        new_counts=counts,
        verification_settings={
            "epsilon": 0.5,
            "min_shots": 100,
            "tolerance_regime": "strict",
            "alpha": 0.01,
        },
    )
    assert loose["metrics"]["alpha"] == pytest.approx(0.5)
    assert tight["metrics"]["alpha"] == pytest.approx(0.01)
    assert loose["metrics"]["tvd_ucb"] < tight["metrics"]["tvd_ucb"]


# --- Degenerate input (#15 finding 10) -------------------------------------


def test_empty_counts_never_verified():
    """The research document lists 'degenerate input never VERIFIED' as an
    invariant needing a test. Empty dicts must not raise ZeroDivisionError."""
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts={},
        new_counts={},
        verification_settings={"epsilon": 0.05, "min_shots": 0, "tolerance_regime": "strict"},
    )
    assert result["verdict"] != "VERIFIED"
    assert result["verdict"] == "INCONCLUSIVE"


def test_zero_count_new_against_populated_ref_never_verified():
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts={"00": 500, "11": 500},
        new_counts={},
        verification_settings={"epsilon": 0.05, "min_shots": 0, "tolerance_regime": "strict"},
    )
    assert result["verdict"] == "INCONCLUSIVE"
    assert "zero shots" in result["reason"].lower()


@pytest.mark.usefixtures("statistical_dependencies")
def test_single_outcome_both_arms_is_verified_not_a_crash():
    """A single shared outcome with nonzero shots is a legitimate (if trivial)
    input — it must resolve normally, not be swept up by the zero-shots guard."""
    verifier = CapsuleVerifier()
    result = verifier.verify_statistical(
        ref_counts={"00": 1},
        new_counts={"00": 1},
        verification_settings={"epsilon": 0.5, "min_shots": 0, "tolerance_regime": "strict"},
    )
    assert result["verdict"] in ("VERIFIED", "INCONCLUSIVE")
    assert result["metrics"]["total_variation_distance"] == 0.0


@pytest.mark.usefixtures("statistical_dependencies")
def test_energy_distance_uses_hamming_metric():
    """Energy distance must use Hamming distance on bitstrings, not index proximity."""
    # "00" and "11" are Hamming-distance 2; "00" and "01" are Hamming-distance 1.
    verifier = CapsuleVerifier()
    far = verifier.verify_statistical(
        ref_counts={"00": 1000},
        new_counts={"11": 1000},
        verification_settings={"epsilon": 0.5, "min_shots": 100, "tolerance_regime": "strict"},
    )
    near = verifier.verify_statistical(
        ref_counts={"00": 1000},
        new_counts={"01": 1000},
        verification_settings={"epsilon": 0.5, "min_shots": 100, "tolerance_regime": "strict"},
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


# Mutation B5: digest comparison is key-order independent (sort_keys=True)
def test_deterministic_verification_ignores_key_order():
    result = CapsuleVerifier.verify_deterministic({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert result["verdict"] == "VERIFIED"


# Mutation B5: non-JSON values (datetime) are compared via default=str, not a TypeError
def test_deterministic_verification_handles_datetime_values():
    ref = {"t": datetime.datetime(2026, 1, 1)}
    new = {"t": datetime.datetime(2026, 1, 1)}
    assert CapsuleVerifier.verify_deterministic(ref, new)["verdict"] == "VERIFIED"


def test_deterministic_verification_mismatch():
    verifier = CapsuleVerifier()
    result = verifier.verify_deterministic(
        ref_data={"value": 42},
        new_data={"value": 43},
    )
    assert result["verdict"] == "REJECTED"


# --- Path-traversal hardening (#31) ---


def test_verify_checksums_rejects_parent_traversal_key(tmp_path):
    """A .checksums key that escapes the capsule root must fail without reading the outside file."""
    import yaml

    secret = tmp_path / "secret.txt"
    secret.write_text("outside-the-capsule")
    secret_digest = "sha256:" + hashlib.sha256(secret.read_bytes()).hexdigest()

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    # Key escapes the root; digest is the *real* hash of the outside file, so a
    # naive implementation would report match=True and status=pass.
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"../secret.txt": secret_digest}, sort_keys=True)
    )

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"
    assert "../secret.txt" in result.get("invalid", [])


def test_verify_checksums_rejects_absolute_path_key(tmp_path):
    """A .checksums key with an absolute path must fail (path traversal)."""
    import yaml

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"/etc/hosts": "sha256:" + "0" * 64}, sort_keys=True)
    )

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"
    assert "/etc/hosts" in result.get("invalid", [])


# --- Symlink hardening (#32) ---


def test_verify_checksums_does_not_follow_symlink_entry(tmp_path):
    """A .checksums entry that is a symlink must not be dereferenced."""
    import yaml

    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY CONTENT")
    secret_digest = "sha256:" + hashlib.sha256(secret.read_bytes()).hexdigest()

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    (payload / "link.txt").symlink_to(secret)
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"payload/link.txt": secret_digest}, sort_keys=True)
    )

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"
    assert "payload/link.txt" in result.get("symlinks", [])


def test_verify_checksums_flags_unlisted_symlink(tmp_path):
    """A symlink present in the tree but absent from .checksums must still fail verification."""
    import yaml

    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY CONTENT")

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    payload = capsule_dir / "payload"
    payload.mkdir()
    real = payload / "results.json"
    real.write_text('{"counts": {"00": 1}}')
    digest = "sha256:" + hashlib.sha256(real.read_bytes()).hexdigest()
    (payload / "link.txt").symlink_to(secret)  # not listed in .checksums
    (capsule_dir / ".checksums").write_text(
        yaml.dump({"payload/results.json": digest}, sort_keys=True)
    )

    result = CapsuleVerifier.verify_checksums(capsule_dir)
    assert result["status"] == "fail"
    assert "payload/link.txt" in result.get("symlinks", [])
