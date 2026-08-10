"""Verification policy — the trust boundary between the verifier and the artifact.

A capsule is untrusted input. Acceptance thresholds must come from the party
doing the verifying, never from the artifact under test: a published capsule
declaring ``epsilon: 1.0`` would otherwise certify every comparison made
against it, since TVD is bounded by 1 (#30).

The danger is one-directional. A declared value that makes verification
*stricter* is harmless — at worst it wastes the verifier's shots. A value that
loosens it is an attack. But parameters do not all tighten in the same
direction, so there is no single "declared may only tighten" rule:

- ``epsilon`` tightens downward, so the declaration is clamped by ``min``.
- ``min_shots`` tightens *upward*, so clamping by ``max`` would preserve the
  attack — a declared 10^9 forces INCONCLUSIVE forever, and a publisher whose
  result can never be rejected gets to call it unfalsified. It is therefore
  never read from the capsule at all.
- ``tolerance_regime: calibration_drift`` swaps in a looser threshold, so
  honouring it is the verifier's opt-in, and the drift ceiling is policy too.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_EPSILON = 0.02
DEFAULT_EPSILON_DRIFT = 0.08
DEFAULT_MIN_SHOTS = 100


def _usable_threshold(value: Any) -> Optional[float]:
    """Return ``value`` as a float if it is a usable threshold, else ``None``.

    Rejects strings, ``None``, containers, booleans (``bool`` is an ``int``
    subclass and ``True`` would otherwise read as 1.0), NaN, and non-positive
    numbers. A malformed declaration falls back to policy rather than raising:
    the capsule is untrusted, so bad input is expected and must not be a crash.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v <= 0.0:  # NaN, zero, negative
        return None
    return v


@dataclass(frozen=True)
class VerificationPolicy:
    """Thresholds owned by the verifier, not by the capsule under test."""

    epsilon: float = DEFAULT_EPSILON
    epsilon_drift: float = DEFAULT_EPSILON_DRIFT
    min_shots: int = DEFAULT_MIN_SHOTS
    honor_calibration_drift: bool = False

    def resolve(self, declared: Optional[dict]) -> dict[str, Any]:
        """Resolve effective settings from this policy and a capsule's declaration.

        Returns a dict accepted by ``CapsuleVerifier.verify_statistical`` plus
        provenance keys recording what the capsule asked for and whether it was
        overridden, so a reader can see which threshold decided the verdict.

        ``tolerance_regime`` is always returned as ``"strict"``: the regime has
        already been resolved here, and the downstream verifier must not swap in
        a drift threshold a second time.
        """
        declared = declared if isinstance(declared, dict) else {}

        regime_declared = declared.get("tolerance_regime") == "calibration_drift"
        drift = regime_declared and self.honor_calibration_drift

        ceiling = self.epsilon_drift if drift else self.epsilon
        raw = declared.get("epsilon_drift" if drift else "epsilon")

        wanted = _usable_threshold(raw)
        epsilon = min(ceiling, wanted) if wanted is not None else ceiling

        return {
            "epsilon": epsilon,
            "min_shots": self.min_shots,
            "tolerance_regime": "strict",
            # provenance — not consumed by the verifier, reported to the user
            "epsilon_declared": raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None,
            "epsilon_ceiling": ceiling,
            "epsilon_clamped": wanted is not None and wanted > ceiling,
            "calibration_drift_declared": regime_declared,
            "calibration_drift_honoured": drift,
        }
