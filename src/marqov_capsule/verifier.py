"""
Capsule verifier for validating reproducibility of quantum workflows.

Implements deterministic verification (for simulators) and statistical
verification (for real QPUs) using Kolmogorov-Smirnov test, chi-squared
test, and energy tolerance checks.

Based on marqov-mini's CapsuleVerifier, extended for quantum workflows.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml is required. Install with: pip install pyyaml")

try:
    import numpy as np
    from scipy import stats
except ImportError:
    np = None
    stats = None


class CapsuleVerifier:
    """
    Verifier for validating Capsule reproducibility.

    Supports two verification modes:
    1. Deterministic (for simulators): Exact digest matching
    2. Statistical (for QPUs): Statistical tests on distributions

    Example:
        >>> verifier = CapsuleVerifier()
        >>> capsule = verifier.load_capsule("my-workflow.capsule/capsule.yaml")
        >>> result = verifier.verify_capsule(capsule, method="statistical")
        >>> print(result["verification_passed"])
        True
    """

    def __init__(self, schema_path: Optional[Path] = None):
        """
        Initialize the verifier.

        Args:
            schema_path: Path to capsule.schema.json for validation (optional)
        """
        self.schema_path = schema_path
        self.schema = None

        if schema_path and schema_path.exists():
            with open(schema_path) as f:
                self.schema = json.load(f)

    def load_capsule(self, filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Load a Capsule from a YAML file.

        Args:
            filepath: Path to capsule.yaml

        Returns:
            Capsule data dictionary
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"Capsule not found: {filepath}")

        with open(filepath) as f:
            capsule_data = yaml.safe_load(f)

        return capsule_data

    def verify_capsule(
        self,
        capsule: Dict[str, Any],
        method: Optional[str] = None,
        reference_results: Optional[Dict[str, Any]] = None,
        tolerance: float = 0.01,
        significance_level: float = 0.05,
    ) -> Dict[str, Any]:
        """
        Verify Capsule reproducibility.

        Args:
            capsule: Capsule data dictionary
            method: "deterministic", "statistical", or "verification-only".
                    If None, auto-detected from capsule's reproducibility_tier.
            reference_results: Reference results for comparison (if available)
            tolerance: Numerical tolerance for energy/expectation values
            significance_level: P-value threshold for statistical tests

        Returns:
            Verification result dictionary with:
                - verification_passed: bool
                - method: str
                - details: dict with test results
                - warnings: list of warnings
        """
        if method is None:
            tier = capsule.get("reproducibility_tier", "deterministic")
            method = self._tier_to_method(tier)

        if method == "deterministic":
            return self._verify_deterministic(capsule, reference_results)
        elif method == "statistical":
            return self._verify_statistical(
                capsule,
                reference_results,
                tolerance,
                significance_level
            )
        elif method == "verification-only":
            return self._verify_metadata_only(capsule)
        else:
            raise ValueError(f"Unknown verification method: {method}")

    @staticmethod
    def _tier_to_method(tier: str) -> str:
        """Map a reproducibility_tier value to a verification method name."""
        mapping = {
            "deterministic": "deterministic",
            "statistical": "statistical",
            "verification-only": "verification-only",
        }
        return mapping.get(tier, "deterministic")

    def verify_checksums(self, capsule_dir) -> dict:
        """Verify all files against .checksums manifest.

        Returns dict with 'passed', 'mismatched', 'missing', 'extra'.
        """
        capsule_dir = Path(capsule_dir)
        checksums_path = capsule_dir / ".checksums"

        if not checksums_path.exists():
            return {"passed": False, "error": ".checksums not found",
                    "mismatched": [], "missing": [], "extra": []}

        # Parse .checksums
        expected = {}
        for line in checksums_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            digest, name = line.split("  ", 1)
            expected[name] = digest

        # Check each file
        mismatched = []
        missing = []
        for name, expected_digest in expected.items():
            filepath = capsule_dir / name
            if not filepath.exists():
                missing.append(name)
                continue
            actual = f"sha256:{hashlib.sha256(filepath.read_bytes()).hexdigest()}"
            if actual != expected_digest:
                mismatched.append(name)

        # Check for extra files
        actual_files = set()
        for filepath in capsule_dir.rglob("*"):
            if filepath.is_file() and filepath.name != ".checksums":
                actual_files.add(str(filepath.relative_to(capsule_dir)))
        extra = sorted(actual_files - set(expected.keys()))

        passed = len(mismatched) == 0 and len(missing) == 0
        return {
            "passed": passed,
            "mismatched": mismatched,
            "missing": missing,
            "extra": extra,
        }

    def _verify_deterministic(
        self,
        capsule: Dict[str, Any],
        reference_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Verify Capsule with deterministic (exact) matching.

        Used for simulators with controlled randomness.

        Args:
            capsule: Capsule data
            reference_results: Reference capsule or results

        Returns:
            Verification result
        """
        warnings = []
        details = {}

        # Check lifecycle state
        if capsule.get("lifecycle_state") != "sealed":
            warnings.append("Capsule is not sealed - verification may be incomplete")

        # Verify digests are present
        digests = capsule.get("digests", {})
        missing_digests = []

        for key in ["workflow", "environment", "backends", "provenance"]:
            if not digests.get(key):
                missing_digests.append(key)

        if missing_digests:
            warnings.append(f"Missing digests: {', '.join(missing_digests)}")

        details["digests_present"] = {
            k: v is not None for k, v in digests.items()
        }

        # If reference results provided, compare digests
        if reference_results:
            digest_matches = self._compare_digests(
                capsule.get("extensions", {}).get("result_digests", {}),
                reference_results
            )
            details["digest_comparison"] = digest_matches
            verification_passed = all(digest_matches.values())
        else:
            # No reference - just check structure
            verification_passed = len(missing_digests) == 0

        return {
            "verification_passed": verification_passed,
            "method": "deterministic",
            "details": details,
            "warnings": warnings,
        }

    def _verify_metadata_only(self, capsule: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify Capsule integrity by inspecting metadata only, without re-executing.

        Used for the "verification-only" reproducibility tier, where re-execution is
        not expected (e.g., real QPU runs that cannot be cheaply repeated).

        Checks:
        - Capsule lifecycle_state is "sealed"
        - Required top-level sections are present
        - At least one digest is recorded

        Args:
            capsule: Capsule data dictionary

        Returns:
            Verification result dictionary
        """
        warnings = []
        details = {}

        # Check lifecycle state
        lifecycle_state = capsule.get("lifecycle_state")
        details["lifecycle_state"] = lifecycle_state
        if lifecycle_state != "sealed":
            warnings.append(
                f"Capsule lifecycle_state is '{lifecycle_state}', expected 'sealed'"
            )

        # Check required top-level sections are present
        required_sections = ["name", "digests", "tasks"]
        missing_sections = [s for s in required_sections if s not in capsule]
        details["required_sections_present"] = len(missing_sections) == 0
        if missing_sections:
            warnings.append(f"Missing required sections: {', '.join(missing_sections)}")

        # Check that at least one digest is recorded
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
        """
        Verify Capsule with statistical tests.

        Used for real QPU results which are probabilistic.

        Args:
            capsule: Capsule data
            reference_results: Reference distributions/values
            tolerance: Numerical tolerance for expectation values
            significance_level: P-value threshold

        Returns:
            Verification result
        """
        if np is None or stats is None:
            raise ImportError(
                "numpy and scipy are required for statistical verification. "
                "Install with: pip install numpy scipy"
            )

        warnings = []
        details = {}
        statistical_tests = []

        # Check lifecycle state
        if capsule.get("lifecycle_state") != "sealed":
            warnings.append("Capsule is not sealed - verification may be incomplete")

        # If reference results provided, run statistical tests
        if reference_results:
            # Kolmogorov-Smirnov test for distribution comparison
            if "distribution" in reference_results:
                ks_result = self._ks_test(
                    capsule.get("extensions", {}).get("distribution"),
                    reference_results["distribution"],
                    significance_level
                )
                statistical_tests.append(ks_result)

            # Chi-squared test for count data
            if "counts" in reference_results:
                chi2_result = self._chi_squared_test(
                    capsule.get("extensions", {}).get("counts"),
                    reference_results["counts"],
                    significance_level
                )
                statistical_tests.append(chi2_result)

            # Energy/expectation value tolerance check
            if "energy" in reference_results:
                energy_result = self._energy_tolerance_check(
                    capsule.get("extensions", {}).get("energy"),
                    reference_results["energy"],
                    tolerance
                )
                statistical_tests.append(energy_result)

            verification_passed = all(
                test.get("passed", False) for test in statistical_tests
            )
        else:
            # No reference - check structure only
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

    def _ks_test(
        self,
        distribution1: Optional[List[float]],
        distribution2: List[float],
        significance_level: float,
    ) -> Dict[str, Any]:
        """
        Perform Kolmogorov-Smirnov test.

        Tests whether two distributions are significantly different.

        Args:
            distribution1: First distribution
            distribution2: Second distribution (reference)
            significance_level: P-value threshold

        Returns:
            Test result dictionary
        """
        if distribution1 is None or distribution2 is None:
            return {
                "test": "kolmogorov_smirnov",
                "passed": False,
                "error": "Distribution data missing"
            }

        try:
            d_statistic, p_value = stats.ks_2samp(distribution1, distribution2)

            return {
                "test": "kolmogorov_smirnov",
                "d_statistic": float(d_statistic),
                "p_value": float(p_value),
                "threshold": significance_level,
                "passed": p_value > significance_level,
            }
        except Exception as e:
            return {
                "test": "kolmogorov_smirnov",
                "passed": False,
                "error": str(e)
            }

    def _chi_squared_test(
        self,
        counts1: Optional[Dict[str, int]],
        counts2: Dict[str, int],
        significance_level: float,
    ) -> Dict[str, Any]:
        """
        Perform chi-squared test on measurement counts.

        Args:
            counts1: First counts dictionary
            counts2: Second counts dictionary (reference)
            significance_level: P-value threshold

        Returns:
            Test result dictionary
        """
        if counts1 is None or counts2 is None:
            return {
                "test": "chi_squared",
                "passed": False,
                "error": "Counts data missing"
            }

        try:
            # Align keys and create observed/expected arrays
            all_keys = sorted(set(counts1.keys()) | set(counts2.keys()))
            observed = np.array([counts1.get(k, 0) for k in all_keys])
            expected = np.array([counts2.get(k, 0) for k in all_keys])

            # Normalize to same total
            observed = observed / observed.sum() * expected.sum()

            # Perform chi-squared test
            chi2_statistic, p_value = stats.chisquare(observed, expected)

            return {
                "test": "chi_squared",
                "chi_squared_statistic": float(chi2_statistic),
                "p_value": float(p_value),
                "threshold": significance_level,
                "passed": p_value > significance_level,
            }
        except Exception as e:
            return {
                "test": "chi_squared",
                "passed": False,
                "error": str(e)
            }

    def _energy_tolerance_check(
        self,
        energy1: Optional[float],
        energy2: float,
        tolerance: float,
    ) -> Dict[str, Any]:
        """
        Check if energy values are within tolerance.

        Args:
            energy1: First energy value
            energy2: Second energy value (reference)
            tolerance: Absolute tolerance

        Returns:
            Test result dictionary
        """
        if energy1 is None or energy2 is None:
            return {
                "test": "energy_tolerance",
                "passed": False,
                "error": "Energy values missing"
            }

        try:
            delta = abs(energy1 - energy2)
            passed = delta <= tolerance

            return {
                "test": "energy_tolerance",
                "energy1": float(energy1),
                "energy2": float(energy2),
                "delta": float(delta),
                "tolerance": tolerance,
                "passed": passed,
            }
        except Exception as e:
            return {
                "test": "energy_tolerance",
                "passed": False,
                "error": str(e)
            }

    def _compare_digests(
        self,
        digests1: Dict[str, Any],
        digests2: Dict[str, Any]
    ) -> Dict[str, bool]:
        """
        Compare two digest dictionaries.

        Args:
            digests1: First digest dictionary
            digests2: Second digest dictionary

        Returns:
            Dictionary of {digest_name: matches}
        """
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
        """
        Check if QPU calibration has drifted between two capsules.

        Args:
            capsule1: First capsule
            capsule2: Second capsule (reference)
            max_fidelity_drift: Maximum allowed fidelity drift

        Returns:
            Drift check result
        """
        cal1 = capsule1.get("extensions", {}).get("qpu_calibration")
        cal2 = capsule2.get("extensions", {}).get("qpu_calibration")

        if not cal1 or not cal2:
            return {
                "calibration_drift_check": False,
                "error": "Calibration data missing from one or both capsules"
            }

        # Check gate fidelities
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
            }
        }

    def compare_capsules(
        self,
        capsule1_path: Union[str, Path],
        capsule2_path: Union[str, Path],
        method: str = "statistical",
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Compare two Capsules for consistency.

        Useful for comparing same workflow run on different backends
        (e.g., simulator vs QPU, or different QPU providers).

        Args:
            capsule1_path: Path to first capsule.yaml
            capsule2_path: Path to second capsule.yaml
            method: Verification method ("deterministic" or "statistical")
            tolerance: Numerical tolerance for statistical comparison

        Returns:
            Comparison result dictionary
        """
        capsule1 = self.load_capsule(capsule1_path)
        capsule2 = self.load_capsule(capsule2_path)

        # Basic metadata comparison
        metadata_comparison = {
            "same_workflow": capsule1.get("name") == capsule2.get("name"),
            "workflow1": capsule1.get("name"),
            "workflow2": capsule2.get("name"),
        }

        # Cost comparison
        cost_comparison = {
            "cost1_usd": capsule1.get("cost", {}).get("actual_cost_usd"),
            "cost2_usd": capsule2.get("cost", {}).get("actual_cost_usd"),
        }

        # Execution time comparison
        time1 = capsule1.get("execution", {}).get("wall_time_seconds")
        time2 = capsule2.get("execution", {}).get("wall_time_seconds")

        execution_comparison = {
            "wall_time1_seconds": time1,
            "wall_time2_seconds": time2,
            "speedup_ratio": time1 / time2 if time1 and time2 and time2 > 0 else None,
        }

        # Calibration drift (if both have QPU calibration)
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
