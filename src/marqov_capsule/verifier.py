"""CapsuleVerifier — integrity verification and equivalence testing."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.builder import UNCHECKSUMMED_ROOT_FILES
from marqov_capsule.policy import resolve_alpha


def _is_within_root(rel_path: str, root: Path) -> bool:
    """True if ``root / rel_path`` stays inside ``root``.

    Rejects absolute paths and ``..`` escapes. Uses lexical normalisation
    anchored at an *absolute* root (not bare ``normpath``) so the check is
    independent of symlinks — those are handled separately by the caller — and
    so a capsule addressed as ``.`` does not false-alarm (#60): bare
    ``normpath('.')`` stays ``'.'`` while ``normpath('./rel')`` becomes ``rel``,
    which never shares the ``'.'`` prefix.
    """
    if os.path.isabs(rel_path):
        return False
    root_str = os.path.abspath(str(root))
    full = os.path.abspath(os.path.join(root_str, rel_path))
    return full == root_str or full.startswith(root_str + os.sep)


def _require_numpy():
    try:
        import numpy as np
        import scipy.stats as ss
        return np, ss
    except ImportError:
        raise ImportError(
            "Statistical verification requires numpy and scipy: "
            "pip install numpy scipy"
        )


def _tvd_point(ref_counts: dict, new_counts: dict, n_ref: int, n_new: int) -> float:
    """Plug-in total variation distance between two count distributions.

    ``n_ref``/``n_new`` are passed in rather than recomputed here: callers
    already have the shot totals (and, in ``verify_statistical``, have
    already checked them against ``min_shots``), so this stays pure
    arithmetic on numbers the caller derived once.
    """
    np, _ = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])
    new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])
    return float(0.5 * np.sum(np.abs(ref_probs - new_probs)))


def _tvd_upper_confidence_bound(
    ref_counts: dict,
    new_counts: dict,
    alpha: float = 0.05,
):
    """One-sided (1-alpha) upper confidence bound on the true TVD.

    Closed-form, no resampling. Two steps, each rigorous on its own:

    1. The plug-in TVD estimator is upward-biased: TV(p,q) <= E[TVD(p_hat,q_hat)]
       by Jensen's inequality (|.| is convex).
    2. TVD(p_hat,q_hat) concentrates around its mean within
       sqrt((log(1/alpha)/2) * (1/n_ref + 1/n_new)) with probability >= 1-alpha,
       by McDiarmid's *one-sided* bounded-difference inequality (a single sample
       moves two probability coordinates by 1/n, halved by the 1/2 in TVD, so
       the bounded difference is 1/n per arm).

    Chaining the two gives P(TV(p,q) <= tvd_point + t) >= 1-alpha. The slack is
    independent of the number of outcomes K, so this is valid (if conservative)
    at any K, unlike the bootstrap it replaces — TVD is not Hadamard-
    differentiable at p=q, which is fatal to bootstrap consistency at exactly
    the null this function is used to test.

    Uses log(1/alpha), not log(2/alpha): the two-sided constant would silently
    under-report the true one-sided error rate.

    The returned bound is clamped to 1.0. TV(p,q) <= 1 deterministically for
    every pair of distributions, so intersecting the McDiarmid bound with that
    known constraint is always valid: it can only ever fire when the raw
    tvd_point + slack already exceeded 1.0, in which case the true value was
    already known to lie in [0, 1] with certainty, so tightening to 1.0 loses
    no coverage — it only removes a number (e.g. 1.17) that conveys nothing a
    bound of 1.0 does not. This keeps the (1-alpha) coverage guarantee while
    matching the schema's declared ``maximum: 1.0`` for this metric.

    See docs/research/2026-08-10-tvd-equivalence-testing.md §5 for the full
    derivation, coverage measurements, and citations.
    """
    np, _ = _require_numpy()
    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    tvd_point = _tvd_point(ref_counts, new_counts, n_ref, n_new)
    slack = float(np.sqrt((np.log(1.0 / alpha) / 2.0) * (1.0 / n_ref + 1.0 / n_new)))
    return tvd_point, min(tvd_point + slack, 1.0)


def _compute_chi_squared_p(ref_counts: dict, new_counts: dict):
    """Chi-squared diagnostic only — never verdict-changing.

    Returns None when cell counts are insufficient for a valid test.
    """
    np, ss = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    ref_obs = np.array([ref_counts.get(k, 0) for k in all_keys], dtype=float) + 0.5
    new_obs = np.array([new_counts.get(k, 0) for k in all_keys], dtype=float) + 0.5
    new_scaled = new_obs * (n_ref / n_new)
    if np.all(ref_obs >= 5) and np.all(new_scaled >= 5):
        _, p_value = ss.chisquare(new_scaled, f_exp=ref_obs)
        return float(p_value)
    return None


_ENERGY_DISTANCE_MAX_OUTCOMES = 2000  # n×n doubles above this is ~800 MB


def _compute_energy_distance(ref_counts: dict, new_counts: dict):
    """Energy distance using normalised Hamming distance on bitstrings (diagnostic only).

    Uses: 2·E[d(X,Y)] - E[d(X,X')] - E[d(Y,Y')]
    where d is Hamming distance normalised by string length.

    Returns None when unique outcomes > _ENERGY_DISTANCE_MAX_OUTCOMES (OOM guard).
    """
    np, _ = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    if not all_keys:
        return None
    if len(all_keys) > _ENERGY_DISTANCE_MAX_OUTCOMES:
        return None

    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())
    ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])
    new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])

    key_len = max(len(k) for k in all_keys) or 1
    n = len(all_keys)

    # Build pairwise normalised Hamming distance matrix
    d = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                d[i, j] = sum(a != b for a, b in zip(all_keys[i], all_keys[j])) / key_len

    e_pq = float(ref_probs @ d @ new_probs)
    e_pp = float(ref_probs @ d @ ref_probs)
    e_qq = float(new_probs @ d @ new_probs)
    return 2.0 * e_pq - e_pp - e_qq


class CapsuleVerifier:
    """Verify capsule integrity and equivalence."""

    def __init__(self, schema_path: Optional[Path] = None):
        """
        Initialize the verifier.

        Args:
            schema_path: Path to capsule.schema.json for validation (optional)
        """
        self.schema_path = schema_path
        self.schema = None

        if schema_path and Path(schema_path).exists():
            with open(schema_path) as f:
                self.schema = json.load(f)

    # -------------------------------------------------------------------------
    # New API (Task 7): closed-form upper confidence bound on TVD
    # -------------------------------------------------------------------------

    def verify_statistical(
        self,
        ref_counts: dict,
        new_counts: dict,
        verification_settings: dict,
    ) -> dict[str, Any]:
        """One-sided upper-confidence-bound equivalence test on TVD (#15).

        Certifies equivalence within tolerance; it does not — and cannot,
        rigorously, from this construction — assert that two distributions
        differ. There is no valid ``REJECTED`` verdict here — the verdict
        space stays VERIFIED / INCONCLUSIVE. That is not because no lower
        bound on the true TVD exists: the triangle inequality gives one
        (the plug-in estimate minus the McDiarmid slack minus a one-sample
        bias bound per arm), and it is valid. It is not deployed because,
        unlike the upper bound (Jensen + McDiarmid, see
        ``_tvd_upper_confidence_bound``, whose slack is free of the outcome
        count), that lower bound's slack depends on the number of outcomes
        K — and taking K from the observed support rather than the declared
        register width fails open, exactly the failure mode this project's
        threat model flags for verifier-side parameters. Separately, the one
        candidate detection tool, a permutation test against the sharp null,
        has measured power as low as 42% at K=256 outcomes — too weak to
        carry an affirmative verdict on its own.
        A low ``chi_squared_p_value`` is surfaced as a diagnostic hint only;
        it never changes the verdict.

        This replaces a bootstrap CI that was provably miscalibrated: TVD is
        not Hadamard-differentiable at ``p = q``, which is fatal to bootstrap
        consistency at exactly the null this function tests. The bootstrap
        rejected byte-identical distributions as non-reproducible from roughly
        four qubits upward. Full analysis, citations, and coverage
        measurements: ``docs/research/2026-08-10-tvd-equivalence-testing.md``.

        Decision matrix as implemented:
          - either arm has zero shots → INCONCLUSIVE
          - shots < min_shots         → INCONCLUSIVE
          - tvd_ucb <= epsilon        → VERIFIED
          - else                      → INCONCLUSIVE

        ``alpha`` (the confidence-bound error rate) is read only from the
        resolved settings, never trusted raw from a capsule's declaration —
        see ``marqov_capsule.policy`` — and a malformed value falls back to
        the default rather than crashing or silently widening the error rate.
        """
        min_shots = verification_settings.get("min_shots", 100)
        tolerance_regime = verification_settings.get("tolerance_regime", "strict")
        epsilon = verification_settings.get("epsilon", 0.02)

        if tolerance_regime == "calibration_drift":
            epsilon = verification_settings.get("epsilon_drift", 0.08)

        alpha = resolve_alpha(verification_settings.get("alpha"))

        n_ref = sum(ref_counts.values())
        n_new = sum(new_counts.values())

        if n_ref == 0 or n_new == 0:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": "one or both arms have zero shots; TVD is undefined",
                "metrics": {
                    "epsilon_used": epsilon,
                    "shots_ref": n_ref,
                    "shots_new": n_new,
                    "min_shots": min_shots,
                },
            }

        total_shots = min(n_ref, n_new)

        if total_shots < min_shots:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"shots ({total_shots}) below min_shots ({min_shots}); declined without computing a confidence bound",
                "metrics": {
                    "epsilon_used": epsilon,
                    "shots_ref": n_ref,
                    "shots_new": n_new,
                    "min_shots": min_shots,
                },
            }

        tvd_point, tvd_ucb = _tvd_upper_confidence_bound(ref_counts, new_counts, alpha=alpha)
        chi2_p = _compute_chi_squared_p(ref_counts, new_counts)
        energy_dist = _compute_energy_distance(ref_counts, new_counts)

        metrics: dict[str, Any] = {
            "total_variation_distance": tvd_point,
            "tvd_ucb": tvd_ucb,
            "alpha": alpha,
            "epsilon_used": epsilon,
            "shots_ref": n_ref,
            "shots_new": n_new,
        }
        if chi2_p is not None:
            metrics["chi_squared_p_value"] = chi2_p
        if energy_dist is not None:
            metrics["energy_distance"] = energy_dist

        if tvd_ucb <= epsilon:
            verdict = "VERIFIED"
            reason = f"tvd_ucb ({tvd_ucb:.4f}) <= epsilon ({epsilon})"
        else:
            verdict = "INCONCLUSIVE"
            reason = f"tvd_ucb ({tvd_ucb:.4f}) > epsilon ({epsilon}); TVD = {tvd_point:.4f}; equivalence not demonstrated"

        return {
            "verdict": verdict,
            "reason": reason,
            "metrics": metrics,
        }

    @staticmethod
    def verify_deterministic(
        ref_data: Any,
        new_data: Any,
    ) -> dict[str, Any]:
        """Digest equality for deterministic (classical) results."""
        def _digest(obj):
            s = json.dumps(obj, sort_keys=True, default=str)
            return "sha256:" + hashlib.sha256(s.encode()).hexdigest()

        ref_digest = _digest(ref_data)
        new_digest = _digest(new_data)
        match = ref_digest == new_digest
        return {
            "verdict": "VERIFIED" if match else "REJECTED",
            "ref_digest": ref_digest,
            "new_digest": new_digest,
        }

    # -------------------------------------------------------------------------
    # Checksum verification
    # -------------------------------------------------------------------------

    @staticmethod
    def verify_checksums(capsule_dir: Union[str, Path]) -> dict[str, Any]:
        """Verify SHA-256 checksums for all files in capsule directory.

        Returns a dict with:
          - ``status``: ``"pass"`` or ``"fail"``
          - ``files``: per-file match details (new API)
          - ``passed``: bool alias for backwards compatibility
          - ``mismatched``: list of mismatched relative paths (backwards compat)
          - ``missing``: list of missing relative paths (backwards compat)
        """
        capsule_path = Path(capsule_dir)
        checksums_file = capsule_path / ".checksums"
        if not checksums_file.exists():
            return {
                "status": "fail",
                "passed": False,
                "error": ".checksums not found",
                "files": {},
                "mismatched": [],
                "missing": [],
                "extra": [],
            }

        # .checksums is untrusted input: malformed bytes must produce a FAIL
        # verdict, never an uncaught traceback out of the verifier (#61).
        try:
            raw = checksums_file.read_text()
        except (UnicodeDecodeError, OSError):
            return {
                "status": "fail",
                "passed": False,
                "error": ".checksums could not be read as text",
                "files": {},
                "mismatched": [],
                "missing": [],
                "extra": [],
            }
        # Support both YAML dict format AND legacy "digest  path" lines
        try:
            expected = yaml.safe_load(raw) or {}
            if not isinstance(expected, dict):
                raise ValueError("not a mapping")
        except Exception:
            # Legacy parser: a line without the "  " separator would raise on
            # unpacking, so any malformed line fails the whole capsule (#61).
            try:
                expected = {}
                for line in raw.strip().split("\n"):
                    if not line.strip():
                        continue
                    digest, name = line.split("  ", 1)
                    expected[name] = digest
            except ValueError:
                return {
                    "status": "fail",
                    "passed": False,
                    "error": ".checksums is malformed and could not be parsed",
                    "files": {},
                    "mismatched": [],
                    "missing": [],
                    "extra": [],
                }

        # Resolve the capsule root once, up front. Every checksummed file must
        # resolve to a real path *inside* this, or it is rejected before any read.
        resolved_root = capsule_path.resolve()

        files: dict[str, dict] = {}
        mismatched: list[str] = []
        missing: list[str] = []
        invalid: list[str] = []
        symlinks: list[str] = []
        all_match = True

        for rel_path, expected_digest in expected.items():
            # Keys must be strings; a non-string mapping key (e.g. YAML null or a
            # nested list) must fail, never raise from a path operation (#61).
            if not isinstance(rel_path, str):
                files[str(rel_path)] = {"expected": expected_digest, "actual": None,
                                        "match": False, "error": "non-string .checksums key"}
                invalid.append(str(rel_path))
                all_match = False
                continue
            # Reject keys that escape the capsule root (absolute or ``..``) before
            # touching the filesystem — a crafted .checksums must not read outside.
            if not _is_within_root(rel_path, capsule_path):
                files[rel_path] = {"expected": expected_digest, "actual": None,
                                   "match": False, "error": "path escapes capsule root"}
                invalid.append(rel_path)
                all_match = False
                continue
            file_path = capsule_path / rel_path
            # Never dereference symlinks — the target may live outside the capsule.
            if file_path.is_symlink():
                files[rel_path] = {"expected": expected_digest, "actual": None,
                                   "match": False, "error": "symlink not permitted"}
                symlinks.append(rel_path)
                all_match = False
                continue
            # The lexical check above is symlink-blind: a *parent* directory that
            # is itself a symlink pointing outside the capsule would let a crafted
            # key read an arbitrary file (#54). Resolve real paths and confirm
            # containment against the resolved root BEFORE any read.
            try:
                resolved = file_path.resolve()
            except (OSError, RuntimeError):
                resolved = None
            if resolved is None or not resolved.is_relative_to(resolved_root):
                files[rel_path] = {"expected": expected_digest, "actual": None,
                                   "match": False, "error": "path escapes capsule root"}
                invalid.append(rel_path)
                all_match = False
                continue
            if not file_path.exists():
                files[rel_path] = {"expected": expected_digest, "actual": None, "match": False}
                missing.append(rel_path)
                all_match = False
                continue
            actual = "sha256:" + hashlib.sha256(file_path.read_bytes()).hexdigest()
            match = actual == expected_digest
            files[rel_path] = {"expected": expected_digest, "actual": actual, "match": match}
            if not match:
                mismatched.append(rel_path)
                all_match = False

        # Walk the tree once: collect every on-disk entry (for "extra") and flag
        # any symlink anywhere in the capsule — symlinks are an exfiltration
        # vector. The closed set is enforced over ALL entry types, not just
        # regular files: a FIFO/socket/device node injected into a sealed capsule
        # must not slip past the check by failing ``is_file()`` (#56).
        actual_files = set()
        for fp in capsule_path.rglob("*"):
            rel = str(fp.relative_to(capsule_path))
            if fp.is_symlink():
                if rel not in symlinks:
                    symlinks.append(rel)
                    all_match = False
                continue
            if fp.is_dir():
                continue
            if rel not in UNCHECKSUMMED_ROOT_FILES:
                actual_files.add(rel)
        # .checksums pins a *closed* set: anything on disk but not listed is an
        # injected file. It leaves checksums_digest and the capsule ID intact,
        # so no other layer can catch it (#17).
        extra = sorted(actual_files - set(expected.keys()))
        if extra:
            all_match = False

        return {
            "status": "pass" if all_match else "fail",
            "passed": all_match,
            "files": files,
            "mismatched": mismatched,
            "missing": missing,
            "invalid": invalid,
            "symlinks": symlinks,
            "extra": extra,
        }

    @staticmethod
    def verify_integrity(
        capsule_dir: Union[str, Path],
        expected_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Full spec §6 integrity check — all three layers.

        1. payload files vs ``.checksums`` (delegated to :meth:`verify_checksums`)
        2. ``SHA-256(.checksums bytes)`` vs ``checksums_digest`` in the manifest
        3. recomputed capsule ID vs ``expected_id``, when the caller supplies one

        Layer 1 alone is not tamper-evidence: anyone who edits a payload file can
        re-run ``save_checksums`` and pass. Layer 2 catches that, because the
        manifest pins the original ``.checksums`` bytes. Layer 3 catches edits to
        the manifest itself, which is deliberately outside ``.checksums``.

        Without ``expected_id`` the manifest is *unauthenticated* — nothing on
        disk can attest to it, since a tamperer who rewrites the whole chain
        produces a self-consistent capsule with a different ID. Callers should
        record ``capsule_id`` at seal time and pass it back here.
        """
        capsule_path = Path(capsule_dir)
        errors: list[str] = []

        checksums = CapsuleVerifier.verify_checksums(capsule_path)
        if checksums["status"] != "pass":
            errors.append("payload does not match .checksums")

        checksums_digest_match: Optional[bool] = None
        capsule_id: Optional[str] = None
        capsule_id_match: Optional[bool] = None

        manifest_path = capsule_path / "capsule.yaml"
        manifest: Optional[dict] = None
        if not manifest_path.exists():
            errors.append("capsule.yaml not found — no manifest to anchor .checksums to")
        else:
            # The manifest is untrusted input: a corrupt or hostile one must fail
            # verification, never raise out of the verifier.
            try:
                parsed = load_manifest_yaml(manifest_path.read_text())
            except (yaml.YAMLError, UnicodeDecodeError) as exc:
                errors.append(f"capsule.yaml could not be parsed: {exc.__class__.__name__}")
            else:
                if isinstance(parsed, dict):
                    manifest = parsed
                else:
                    errors.append("capsule.yaml is not a YAML mapping")

        if manifest is not None:
            # Layer 2 — manifest → .checksums binding
            declared = manifest.get("checksums_digest")
            checksums_file = capsule_path / ".checksums"
            if declared is None:
                errors.append("manifest has no checksums_digest — capsule is not sealed")
            elif not checksums_file.exists():
                checksums_digest_match = False
                errors.append(".checksums not found but manifest declares checksums_digest")
            else:
                actual = "sha256:" + hashlib.sha256(checksums_file.read_bytes()).hexdigest()
                checksums_digest_match = actual == declared
                if not checksums_digest_match:
                    errors.append(
                        f"checksums_digest mismatch: manifest declares {declared}, "
                        f".checksums hashes to {actual}"
                    )

            # Layer 3 — manifest identity. The manifest is untrusted: a value
            # that cannot be RFC 8785 canonicalised (NaN, non-string keys, …)
            # must fail verification, never raise out of the verifier (#61).
            try:
                capsule_id = compute_capsule_id(manifest)
            except Exception as exc:
                errors.append(
                    f"capsule ID could not be computed: {exc.__class__.__name__}"
                )
            else:
                if expected_id is not None:
                    capsule_id_match = capsule_id == expected_id
                    if not capsule_id_match:
                        errors.append(
                            f"capsule ID mismatch: expected {expected_id}, recomputed {capsule_id}"
                        )

        authenticated = capsule_id_match is True
        # Surface the authentication state for machine consumers. Without a
        # trusted --id the manifest is unauthenticated even when every other
        # layer passes; text mode already prints this note, so JSON must carry
        # it too or a CI gate reading `status` alone accepts a forgery (#58).
        warning = None
        if not authenticated:
            warning = (
                "manifest is not authenticated — nothing on disk can attest to it; "
                "pass --id <trusted-id> to verify layer 3 (spec §6)"
            )

        return {
            "status": "fail" if errors else "pass",
            "checksums": checksums,
            "checksums_digest_match": checksums_digest_match,
            "capsule_id": capsule_id,
            "capsule_id_match": capsule_id_match,
            "manifest_authenticated": authenticated,
            "warning": warning,
            "errors": errors,
        }

    # -------------------------------------------------------------------------
    # Legacy capsule-level API (kept for backwards compatibility)
    # -------------------------------------------------------------------------

    def load_capsule(self, filepath: Union[str, Path]) -> Dict[str, Any]:
        """Load a Capsule from a YAML file."""
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Capsule not found: {filepath}")
        with open(filepath) as f:
            return yaml.safe_load(f)

    def verify_capsule(
        self,
        capsule: Dict[str, Any],
        method: Optional[str] = None,
        reference_results: Optional[Dict[str, Any]] = None,
        tolerance: float = 0.01,
        significance_level: float = 0.05,
    ) -> Dict[str, Any]:
        """Verify Capsule reproducibility (legacy API)."""
        if method is None:
            tier = capsule.get("reproducibility_tier", "deterministic")
            method = self._tier_to_method(tier)

        if method == "deterministic":
            return self._verify_deterministic(capsule, reference_results)
        elif method == "statistical":
            return self._verify_statistical(
                capsule, reference_results, tolerance, significance_level
            )
        elif method == "verification-only":
            return self._verify_metadata_only(capsule)
        else:
            raise ValueError(f"Unknown verification method: {method}")

    @staticmethod
    def _tier_to_method(tier: str) -> str:
        mapping = {
            "deterministic": "deterministic",
            "statistical": "statistical",
            "verification-only": "verification-only",
        }
        return mapping.get(tier, "deterministic")

    def _verify_deterministic(
        self,
        capsule: Dict[str, Any],
        reference_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        warnings: list = []
        details: dict = {}

        if capsule.get("lifecycle_state") != "sealed":
            warnings.append("Capsule is not sealed - verification may be incomplete")

        digests = capsule.get("digests", {})
        missing_digests = [k for k in ["workflow", "environment", "backends", "provenance"] if not digests.get(k)]
        if missing_digests:
            warnings.append(f"Missing digests: {', '.join(missing_digests)}")
        details["digests_present"] = {k: v is not None for k, v in digests.items()}

        if reference_results:
            digest_matches = self._compare_digests(
                capsule.get("extensions", {}).get("result_digests", {}),
                reference_results,
            )
            details["digest_comparison"] = digest_matches
            verification_passed = all(digest_matches.values())
        else:
            verification_passed = len(missing_digests) == 0

        return {
            "verification_passed": verification_passed,
            "method": "deterministic",
            "details": details,
            "warnings": warnings,
        }

    def _verify_metadata_only(self, capsule: Dict[str, Any]) -> Dict[str, Any]:
        warnings: list = []
        details: dict = {}

        lifecycle_state = capsule.get("lifecycle_state")
        details["lifecycle_state"] = lifecycle_state
        if lifecycle_state != "sealed":
            warnings.append(f"Capsule lifecycle_state is '{lifecycle_state}', expected 'sealed'")

        required_sections = ["name", "digests", "tasks"]
        missing_sections = [s for s in required_sections if s not in capsule]
        details["required_sections_present"] = len(missing_sections) == 0
        if missing_sections:
            warnings.append(f"Missing required sections: {', '.join(missing_sections)}")

        digests = capsule.get("digests", {})
        digests_present = {k: v is not None for k, v in digests.items()}
        any_digest_recorded = any(digests_present.values()) if digests_present else False
        details["digests_present"] = digests_present
        details["any_digest_recorded"] = any_digest_recorded
        if not any_digest_recorded:
            warnings.append("No digests recorded in capsule")

        verification_passed = (
            lifecycle_state == "sealed"
            and len(missing_sections) == 0
            and any_digest_recorded
        )

        return {
            "verification_passed": verification_passed,
            "method": "verification-only",
            "details": details,
            "warnings": warnings,
        }

    def _verify_statistical(
        self,
        capsule: Dict[str, Any],
        reference_results: Optional[Dict[str, Any]] = None,
        tolerance: float = 0.01,
        significance_level: float = 0.05,
    ) -> Dict[str, Any]:
        try:
            import numpy as np
            from scipy import stats as _stats
        except ImportError:
            raise ImportError(
                "numpy and scipy are required for statistical verification. "
                "Install with: pip install numpy scipy"
            )

        warnings: list = []
        details: dict = {}
        statistical_tests: list = []

        if capsule.get("lifecycle_state") != "sealed":
            warnings.append("Capsule is not sealed - verification may be incomplete")

        if reference_results:
            if "distribution" in reference_results:
                statistical_tests.append(self._ks_test(
                    capsule.get("extensions", {}).get("distribution"),
                    reference_results["distribution"],
                    significance_level,
                ))
            if "counts" in reference_results:
                statistical_tests.append(self._chi_squared_test(
                    capsule.get("extensions", {}).get("counts"),
                    reference_results["counts"],
                    significance_level,
                ))
            if "energy" in reference_results:
                statistical_tests.append(self._energy_tolerance_check(
                    capsule.get("extensions", {}).get("energy"),
                    reference_results["energy"],
                    tolerance,
                ))
            verification_passed = all(t.get("passed", False) for t in statistical_tests)
        else:
            warnings.append("No reference results - cannot perform statistical verification")
            verification_passed = False

        details["statistical_tests"] = statistical_tests
        details["tolerance"] = tolerance
        details["significance_level"] = significance_level

        return {
            "verification_passed": verification_passed,
            "method": "statistical",
            "details": details,
            "warnings": warnings,
        }

    def _ks_test(self, distribution1, distribution2, significance_level):
        from scipy import stats as _stats
        if distribution1 is None or distribution2 is None:
            return {"test": "kolmogorov_smirnov", "passed": False, "error": "Distribution data missing"}
        try:
            d_stat, p_value = _stats.ks_2samp(distribution1, distribution2)
            return {
                "test": "kolmogorov_smirnov",
                "d_statistic": float(d_stat),
                "p_value": float(p_value),
                "threshold": significance_level,
                "passed": p_value > significance_level,
            }
        except Exception as e:
            return {"test": "kolmogorov_smirnov", "passed": False, "error": str(e)}

    def _chi_squared_test(self, counts1, counts2, significance_level):
        import numpy as np
        from scipy import stats as _stats
        if counts1 is None or counts2 is None:
            return {"test": "chi_squared", "passed": False, "error": "Counts data missing"}
        try:
            all_keys = sorted(set(counts1.keys()) | set(counts2.keys()))
            observed = np.array([counts1.get(k, 0) for k in all_keys], dtype=float)
            expected = np.array([counts2.get(k, 0) for k in all_keys], dtype=float)
            observed = observed / observed.sum() * expected.sum()
            chi2_stat, p_value = _stats.chisquare(observed, expected)
            return {
                "test": "chi_squared",
                "chi_squared_statistic": float(chi2_stat),
                "p_value": float(p_value),
                "threshold": significance_level,
                "passed": p_value > significance_level,
            }
        except Exception as e:
            return {"test": "chi_squared", "passed": False, "error": str(e)}

    def _energy_tolerance_check(self, energy1, energy2, tolerance):
        if energy1 is None or energy2 is None:
            return {"test": "energy_tolerance", "passed": False, "error": "Energy values missing"}
        try:
            delta = abs(energy1 - energy2)
            return {
                "test": "energy_tolerance",
                "energy1": float(energy1),
                "energy2": float(energy2),
                "delta": float(delta),
                "tolerance": tolerance,
                "passed": delta <= tolerance,
            }
        except Exception as e:
            return {"test": "energy_tolerance", "passed": False, "error": str(e)}

    def _compare_digests(self, digests1: Dict[str, Any], digests2: Dict[str, Any]) -> Dict[str, bool]:
        all_keys = set(digests1.keys()) | set(digests2.keys())
        matches = {}
        for key in all_keys:
            d1 = digests1.get(key, {}).get("digest") if isinstance(digests1.get(key), dict) else digests1.get(key)
            d2 = digests2.get(key, {}).get("digest") if isinstance(digests2.get(key), dict) else digests2.get(key)
            matches[key] = d1 == d2 if d1 and d2 else False
        return matches

    def check_calibration_drift(
        self,
        capsule1: Dict[str, Any],
        capsule2: Dict[str, Any],
        max_fidelity_drift: float = 0.01,
    ) -> Dict[str, Any]:
        """Check if QPU calibration has drifted between two capsules."""
        cal1 = capsule1.get("extensions", {}).get("qpu_calibration")
        cal2 = capsule2.get("extensions", {}).get("qpu_calibration")

        if not cal1 or not cal2:
            return {
                "calibration_drift_check": False,
                "error": "Calibration data missing from one or both capsules",
            }

        fid1 = cal1.get("gate_fidelities", {})
        fid2 = cal2.get("gate_fidelities", {})
        single_qubit_drift = abs(
            fid1.get("single_qubit_gate_fidelity_mean", 0) -
            fid2.get("single_qubit_gate_fidelity_mean", 0)
        )
        two_qubit_drift = abs(
            fid1.get("two_qubit_gate_fidelity_mean", 0) -
            fid2.get("two_qubit_gate_fidelity_mean", 0)
        )
        acceptable = (
            single_qubit_drift <= max_fidelity_drift and
            two_qubit_drift <= max_fidelity_drift
        )
        return {
            "calibration_drift_check": acceptable,
            "single_qubit_fidelity_delta": single_qubit_drift,
            "two_qubit_fidelity_delta": two_qubit_drift,
            "max_allowed_drift": max_fidelity_drift,
            "calibration_timestamps": {
                "capsule1": cal1.get("calibration_timestamp"),
                "capsule2": cal2.get("calibration_timestamp"),
            },
        }

    def compare_capsules(
        self,
        capsule1_path: Union[str, Path],
        capsule2_path: Union[str, Path],
        method: str = "statistical",
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """Compare two Capsules for consistency."""
        capsule1 = self.load_capsule(capsule1_path)
        capsule2 = self.load_capsule(capsule2_path)

        metadata_comparison = {
            "same_workflow": capsule1.get("name") == capsule2.get("name"),
            "workflow1": capsule1.get("name"),
            "workflow2": capsule2.get("name"),
        }
        cost_comparison = {
            "cost1_usd": capsule1.get("cost", {}).get("actual_cost_usd"),
            "cost2_usd": capsule2.get("cost", {}).get("actual_cost_usd"),
        }
        time1 = capsule1.get("execution", {}).get("wall_time_seconds")
        time2 = capsule2.get("execution", {}).get("wall_time_seconds")
        execution_comparison = {
            "wall_time1_seconds": time1,
            "wall_time2_seconds": time2,
            "speedup_ratio": time1 / time2 if time1 and time2 and time2 > 0 else None,
        }
        calibration_comparison = None
        if (capsule1.get("extensions", {}).get("qpu_calibration") and
                capsule2.get("extensions", {}).get("qpu_calibration")):
            calibration_comparison = self.check_calibration_drift(capsule1, capsule2)

        return {
            "overall_consistent": metadata_comparison["same_workflow"],
            "metadata": metadata_comparison,
            "cost": cost_comparison,
            "execution": execution_comparison,
            "calibration": calibration_comparison,
        }
