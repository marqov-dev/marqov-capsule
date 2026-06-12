"""CapsuleVerifier — integrity verification and equivalence testing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


def _require_numpy():
    try:
        import numpy as np
        import scipy.stats as ss
        return np, ss
    except ImportError:
        raise ImportError(
            "Statistical verification requires numpy and scipy: "
            "pip install 'marqov-capsule[verify]'"
        )


_NORMATIVE_SEED = 12345  # Spec §7: fixed seed for reproducible bootstrap CIs


def _bootstrap_tvd_ci(
    ref_counts: dict,
    new_counts: dict,
    n_resamples: int = 9999,
    ci_level: float = 0.95,
    seed: int = _NORMATIVE_SEED,
):
    """Bootstrap CI on TVD. Returns (tvd_point, ci_lower, ci_upper).

    Seed is fixed by spec so the same capsule pair yields the same verdict.
    """
    np, _ = _require_numpy()
    all_keys = sorted(set(ref_counts) | set(new_counts))
    n_ref = sum(ref_counts.values())
    n_new = sum(new_counts.values())

    ref_probs = np.array([ref_counts.get(k, 0) / n_ref for k in all_keys])
    new_probs = np.array([new_counts.get(k, 0) / n_new for k in all_keys])

    tvd_point = float(0.5 * np.sum(np.abs(ref_probs - new_probs)))

    rng = np.random.default_rng(seed)
    boot_tvds = []
    for _ in range(n_resamples):
        r = rng.multinomial(n_ref, ref_probs) / n_ref
        s = rng.multinomial(n_new, new_probs) / n_new
        boot_tvds.append(0.5 * float(np.sum(np.abs(r - s))))

    alpha = 1.0 - ci_level
    ci_lower = float(np.percentile(boot_tvds, 100.0 * alpha / 2))
    ci_upper = float(np.percentile(boot_tvds, 100.0 * (1.0 - alpha / 2)))
    return tvd_point, ci_lower, ci_upper


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
    # New API (Task 7): Bootstrap CI on TVD
    # -------------------------------------------------------------------------

    def verify_statistical(
        self,
        ref_counts: dict,
        new_counts: dict,
        verification_settings: dict,
        seed: int = _NORMATIVE_SEED,
    ) -> dict[str, Any]:
        """Bootstrap CI equivalence test on TVD.

        Decision matrix (spec §7):
          - shots < min_shots           → INCONCLUSIVE
          - tvd_ci_upper <= epsilon      → VERIFIED
          - tvd_ci_lower > epsilon       → REJECTED
          - else                         → INCONCLUSIVE
        """
        min_shots = verification_settings.get("min_shots", 100)
        tolerance_regime = verification_settings.get("tolerance_regime", "strict")
        epsilon = verification_settings.get("epsilon", 0.02)

        if tolerance_regime == "calibration_drift":
            epsilon = verification_settings.get("epsilon_drift", 0.08)

        n_ref = sum(ref_counts.values())
        n_new = sum(new_counts.values())
        total_shots = min(n_ref, n_new)

        if total_shots < min_shots:
            return {
                "verdict": "INCONCLUSIVE",
                "reason": f"shots ({total_shots}) below min_shots ({min_shots}); bootstrap CI too wide for a meaningful verdict",
                "metrics": {
                    "epsilon_used": epsilon,
                    "shots_ref": n_ref,
                    "shots_new": n_new,
                    "min_shots": min_shots,
                    "rng_seed": seed,
                },
            }

        tvd_point, ci_lower, ci_upper = _bootstrap_tvd_ci(ref_counts, new_counts, seed=seed)
        chi2_p = _compute_chi_squared_p(ref_counts, new_counts)
        energy_dist = _compute_energy_distance(ref_counts, new_counts)

        metrics: dict[str, Any] = {
            "total_variation_distance": tvd_point,
            "tvd_ci_lower": ci_lower,
            "tvd_ci_upper": ci_upper,
            "bootstrap_resamples": 9999,
            "epsilon_used": epsilon,
            "shots_ref": n_ref,
            "shots_new": n_new,
            "rng_seed": seed,
        }
        if chi2_p is not None:
            metrics["chi_squared_p_value"] = chi2_p
        if energy_dist is not None:
            metrics["energy_distance"] = energy_dist

        if ci_upper <= epsilon:
            verdict = "VERIFIED"
            reason = f"tvd_ci_upper ({ci_upper:.4f}) <= epsilon ({epsilon})"
        elif ci_lower > epsilon:
            verdict = "REJECTED"
            reason = f"tvd_ci_lower ({ci_lower:.4f}) > epsilon ({epsilon}); TVD = {tvd_point:.4f}"
        else:
            verdict = "INCONCLUSIVE"
            reason = f"CI [{ci_lower:.4f}, {ci_upper:.4f}] straddles epsilon ({epsilon}); recommend more shots"

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

        raw = checksums_file.read_text()
        # Support both YAML dict format AND legacy "digest  path" lines
        try:
            expected = yaml.safe_load(raw) or {}
            if not isinstance(expected, dict):
                raise ValueError("not a mapping")
        except Exception:
            expected = {}
            for line in raw.strip().split("\n"):
                if not line.strip():
                    continue
                digest, name = line.split("  ", 1)
                expected[name] = digest

        files: dict[str, dict] = {}
        mismatched: list[str] = []
        missing: list[str] = []
        all_match = True

        for rel_path, expected_digest in expected.items():
            file_path = capsule_path / rel_path
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

        # Extra files (present on disk but not in manifest)
        actual_files = set()
        for fp in capsule_path.rglob("*"):
            if fp.is_file() and fp.name != ".checksums":
                actual_files.add(str(fp.relative_to(capsule_path)))
        extra = sorted(actual_files - set(expected.keys()))

        return {
            "status": "pass" if all_match else "fail",
            "passed": all_match,
            "files": files,
            "mismatched": mismatched,
            "missing": missing,
            "extra": extra,
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
