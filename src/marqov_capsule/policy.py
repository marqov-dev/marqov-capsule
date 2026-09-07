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
- ``alpha`` (the one-sided confidence-bound error rate on the TVD verdict)
  tightens *downward*, same problem shape as ``min_shots``: a declared
  ``alpha`` of 1.0 would zero out the confidence slack and let a bare,
  upward-biased point estimate carry a VERIFIED verdict. It is therefore
  never read from the capsule at all — ``resolve`` always emits the
  policy's own ``alpha``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_EPSILON = 0.02
DEFAULT_EPSILON_DRIFT = 0.08
DEFAULT_MIN_SHOTS = 100
DEFAULT_ALPHA = 0.05


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


def _usable_alpha(value: Any) -> Optional[float]:
    """Return ``value`` as a float if it is a usable confidence-bound alpha, else ``None``.

    Alpha is an error rate, not a threshold: it must be a real number strictly
    between 0 and 1. 0 or 1 would zero out the confidence slack or divide by
    zero downstream; anything outside (0, 1) is meaningless for a one-sided
    bound. Rejects strings, ``None``, containers, booleans (``bool`` is an
    ``int`` subclass and ``True`` would otherwise read as 1.0), and NaN, same
    as ``_usable_threshold``. A malformed value falls back to policy rather
    than raising: the capsule is untrusted, so bad input is expected and must
    not be a crash.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or not (0.0 < v < 1.0):  # NaN, or outside (0, 1)
        return None
    return v


def resolve_alpha(value: Any) -> float:
    """Return ``value`` as a usable confidence-bound alpha, falling back to
    ``DEFAULT_ALPHA`` when it is not one.

    Thin public wrapper around ``_usable_alpha`` so callers outside this
    module (e.g. the verifier) do not need to import the private guard and
    perform their own ``None`` fallback at the call site.
    """
    usable = _usable_alpha(value)
    return usable if usable is not None else DEFAULT_ALPHA


@dataclass(frozen=True)
class VerificationPolicy:
    """Thresholds owned by the verifier, not by the capsule under test."""

    epsilon: float = DEFAULT_EPSILON
    epsilon_drift: float = DEFAULT_EPSILON_DRIFT
    min_shots: int = DEFAULT_MIN_SHOTS
    alpha: float = DEFAULT_ALPHA
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
            "alpha": self.alpha,
            "tolerance_regime": "strict",
            # provenance — not consumed by the verifier, reported to the user
            "epsilon_declared": raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None,
            "epsilon_ceiling": ceiling,
            "epsilon_clamped": wanted is not None and wanted > ceiling,
            "calibration_drift_declared": regime_declared,
            "calibration_drift_honoured": drift,
        }
