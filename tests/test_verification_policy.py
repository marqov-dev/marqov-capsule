"""Verification policy — the trust boundary between verifier and artifact (#30).

A capsule is untrusted input. Acceptance thresholds must come from the party
doing the verifying, never from the artifact under test. Otherwise a published
capsule declaring `epsilon: 1.0` certifies any comparison made against it.

The danger is one-directional: a declared value that makes verification
*stricter* is harmless, one that loosens it is an attack. Not every parameter
tightens in the same direction, so the rule is per-parameter — see
VerificationPolicy.resolve.
"""
import json

import pytest
import yaml
from click.testing import CliRunner

from marqov_capsule.cli.main import cli
from marqov_capsule.policy import VerificationPolicy


def _capsule(path, counts, vsettings=None):
    """Write and seal a minimal capsule declaring `vsettings`.

    Sealed, because `verify --against` now refuses to compare capsules whose
    payload does not match their own seal.
    """
    from marqov_capsule.builder import CapsuleBuilder

    (path / "payload").mkdir(parents=True, exist_ok=True)
    (path / "payload" / "results.json").write_text(json.dumps({"counts": counts}))
    task = {
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "status": "success",
        "result_type": "probabilistic",
        "backend": {"provider": "ibm", "name": "ibm_kyiv", "shots": sum(counts.values())},
    }
    if vsettings is not None:
        task["verification_settings"] = vsettings
    builder = CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": path.name, "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 4},
        "task_executions": [task],
    })
    builder.seal(capsule_dir=path, sealed_by="test")
    return path


DISJOINT_REF = {"0000": 1000}
DISJOINT_NEW = {"1111": 1000}


# --- Policy resolution (no numpy needed) -----------------------------------


def test_declared_epsilon_may_tighten():
    p = VerificationPolicy(epsilon=0.02)
    assert p.resolve({"epsilon": 0.005})["epsilon"] == 0.005


def test_declared_epsilon_may_not_loosen():
    p = VerificationPolicy(epsilon=0.02)
    assert p.resolve({"epsilon": 1.0})["epsilon"] == 0.02


def test_absent_declaration_uses_policy():
    p = VerificationPolicy(epsilon=0.02)
    assert p.resolve(None)["epsilon"] == 0.02
    assert p.resolve({})["epsilon"] == 0.02


def test_min_shots_is_never_read_from_the_capsule():
    """A declared min_shots of 10^9 would force INCONCLUSIVE on every comparison —
    a publisher whose result can never be rejected gets to call it unfalsified."""
    p = VerificationPolicy(min_shots=100)
    assert p.resolve({"min_shots": 10**9})["min_shots"] == 100


def test_calibration_drift_not_honoured_by_default():
    """The drift regime swaps in a ~4x looser threshold. Opting into that is the
    verifier's judgement, not the author's."""
    p = VerificationPolicy(epsilon=0.02)
    r = p.resolve({"epsilon": 0.02, "epsilon_drift": 1.0, "tolerance_regime": "calibration_drift"})
    assert r["epsilon"] == 0.02


def test_calibration_drift_honoured_but_still_clamped():
    p = VerificationPolicy(epsilon=0.02, epsilon_drift=0.08, honor_calibration_drift=True)
    r = p.resolve({"epsilon": 0.02, "epsilon_drift": 1.0, "tolerance_regime": "calibration_drift"})
    assert r["epsilon"] == 0.08


def test_resolution_never_exceeds_policy_ceiling():
    """Property: no declaration can produce an epsilon above the policy ceiling."""
    p = VerificationPolicy(epsilon=0.02)
    for declared in ({"epsilon": v} for v in (0.0, 0.001, 0.02, 0.5, 1.0, 1e9, -1.0)):
        assert p.resolve(declared)["epsilon"] <= 0.02


def test_resolution_rejects_non_numeric_declarations():
    p = VerificationPolicy(epsilon=0.02)
    for bad in ({"epsilon": "1.0"}, {"epsilon": None}, {"epsilon": [1.0]}):
        assert p.resolve(bad)["epsilon"] == 0.02


def test_resolution_reports_what_was_clamped():
    p = VerificationPolicy(epsilon=0.02)
    r = p.resolve({"epsilon": 1.0})
    assert r["epsilon_declared"] == 1.0
    assert r["epsilon_clamped"] is True
    assert p.resolve({"epsilon": 0.005})["epsilon_clamped"] is False


# --- The #30 attack, end to end -------------------------------------------


def test_malicious_epsilon_cannot_force_verified(tmp_path):
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    _capsule(tmp_path / "ref", DISJOINT_REF, {"epsilon": 1.0, "min_shots": 100,
                                              "tolerance_regime": "strict"})
    _capsule(tmp_path / "new", DISJOINT_NEW)

    r = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                 "--json", str(tmp_path / "new")])
    assert json.loads(r.output)["verdict"] == "REJECTED", r.output


def test_malicious_drift_regime_cannot_force_verified(tmp_path):
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    _capsule(tmp_path / "ref", DISJOINT_REF, {"epsilon": 0.02, "epsilon_drift": 1.0,
                                              "min_shots": 100,
                                              "tolerance_regime": "calibration_drift"})
    _capsule(tmp_path / "new", DISJOINT_NEW)

    r = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                 "--json", str(tmp_path / "new")])
    assert json.loads(r.output)["verdict"] == "REJECTED", r.output


def test_malicious_min_shots_cannot_force_inconclusive(tmp_path):
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    _capsule(tmp_path / "ref", DISJOINT_REF, {"epsilon": 0.02, "min_shots": 10**9,
                                              "tolerance_regime": "strict"})
    _capsule(tmp_path / "new", DISJOINT_NEW)

    r = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                 "--json", str(tmp_path / "new")])
    assert json.loads(r.output)["verdict"] == "REJECTED", r.output


def test_epsilon_flag_sets_the_policy(tmp_path):
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    counts = {"00": 5000, "11": 5000}
    _capsule(tmp_path / "ref", counts)
    _capsule(tmp_path / "new", dict(counts))

    tight = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                     "--epsilon", "0.001", "--json", str(tmp_path / "new")])
    assert json.loads(tight.output)["verdict"] != "VERIFIED", tight.output

    loose = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                     "--epsilon", "0.05", "--json", str(tmp_path / "new")])
    assert json.loads(loose.output)["verdict"] == "VERIFIED", loose.output


def test_effective_epsilon_is_reported(tmp_path):
    """A user must be able to see which threshold actually decided the verdict."""
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    _capsule(tmp_path / "ref", DISJOINT_REF, {"epsilon": 1.0, "min_shots": 100,
                                              "tolerance_regime": "strict"})
    _capsule(tmp_path / "new", DISJOINT_NEW)

    r = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                 "--json", str(tmp_path / "new")])
    data = json.loads(r.output)
    assert data["metrics"]["epsilon_used"] == 0.02
    assert data["policy"]["epsilon_declared"] == 1.0
    assert data["policy"]["epsilon_clamped"] is True


# --- --against must not skip integrity ------------------------------------


def test_against_verifies_integrity_of_both_capsules(tmp_path):
    """The statistical path currently runs no integrity check at all, so counts
    from a tampered capsule are compared as though they were sealed."""
    pytest.importorskip("numpy"); pytest.importorskip("scipy")
    counts = {"00": 5000, "11": 5000}
    for name in ("ref", "new"):
        _capsule(tmp_path / name, dict(counts))

    # Tamper the reference payload after sealing; .checksums is now stale.
    (tmp_path / "ref" / "payload" / "results.json").write_text(
        json.dumps({"counts": {"00": 10000}}))

    r = CliRunner().invoke(cli, ["verify", "--against", str(tmp_path / "ref"),
                                 str(tmp_path / "new")])
    assert r.exit_code != 0, r.output
    assert "integrity" in r.output.lower()
