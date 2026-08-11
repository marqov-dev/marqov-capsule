"""Verification policy — the trust boundary between verifier and artifact (#30).

A capsule is untrusted input. Acceptance thresholds must come from the party
doing the verifying, never from the artifact under test. Otherwise a published
capsule declaring `epsilon: 1.0` certifies any comparison made against it.

The danger is one-directional: a declared value that makes verification
*stricter* is harmless, one that loosens it is an attack. Not every parameter
tightens in the same direction, so the rule is per-parameter — see
VerificationPolicy.resolve.

The CLI surface this policy served (`verify --against`) is cut from 0.1.0
along with statistical equivalence (#15). The policy and these tests stay so
the trust boundary is already correct when that feature returns — it is much
easier to keep than to remember.
"""
from marqov_capsule.policy import VerificationPolicy


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







# --- --against must not skip integrity ------------------------------------



