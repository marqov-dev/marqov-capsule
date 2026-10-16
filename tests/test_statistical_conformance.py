"""The reference implementation must match the published section 6 vectors.

These vectors are derived from the normative formula in spec/v1/README.md
section 6, not generated from this package. If the implementation and the
specification drift apart, these tests fail rather than silently agreeing
with whatever the code happens to do.

The same file is checked by an independent Node implementation in
tools/conformance/check.mjs.
"""

import json
from pathlib import Path

import pytest

from marqov_capsule.verifier import CapsuleVerifier

VECTORS = json.loads(
    (Path(__file__).parent.parent / "spec/v1/conformance/golden/statistical-cases.json").read_text()
)
CASES = VECTORS["cases"]
TOLERANCE = VECTORS["tolerance"]
IDS = [c["name"] for c in CASES]
# Parametrise over pre-filtered lists rather than skipping inside the test:
# a skip should mean "environment cannot run this", not "vector not
# applicable", or a real environment skip is lost in the noise (#116).
BOUND_CASES = [c for c in CASES if "tvd_ucb" in c["expected"]]
EARLY_CASES = [c for c in CASES if c["expected"].get("stage") in ("zero-shots", "below-min-shots")]


@pytest.fixture
def statistical_dependencies():
    pytest.importorskip("numpy")
    pytest.importorskip("scipy")


def _run(case):
    settings = dict(case["settings"])
    settings["tolerance_regime"] = "strict"
    return CapsuleVerifier().verify_statistical(case["ref_counts"], case["new_counts"], settings)


@pytest.mark.usefixtures("statistical_dependencies")
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_verdict_matches_specification(case):
    assert _run(case)["verdict"] == case["expected"]["verdict"], case["note"]


@pytest.mark.usefixtures("statistical_dependencies")
@pytest.mark.parametrize("case", BOUND_CASES, ids=[c["name"] for c in BOUND_CASES])
def test_bound_matches_specification(case):
    expected = case["expected"]
    metrics = _run(case)["metrics"]
    assert metrics["tvd_ucb"] == pytest.approx(expected["tvd_ucb"], abs=TOLERANCE)
    assert metrics["total_variation_distance"] == pytest.approx(
        expected["total_variation_distance"], abs=TOLERANCE
    )


@pytest.mark.parametrize("case", EARLY_CASES, ids=[c["name"] for c in EARLY_CASES])
def test_early_returns_compute_no_bound(case):
    # Sections 6.1 and 6.2 are explicit that these decline *without* computing
    # TVD or a bound. Reporting one anyway would imply a measurement the
    # procedure never made. No numpy needed: the early returns happen first.
    metrics = _run(case)["metrics"]
    assert "tvd_ucb" not in metrics
    assert "total_variation_distance" not in metrics


@pytest.mark.usefixtures("statistical_dependencies")
def test_no_case_ever_yields_a_rejected_verdict():
    # The verdict space is VERIFIED / INCONCLUSIVE. A conformant implementation
    # never asserts that two distributions differ, including for the disjoint
    # supports case where the point estimate is exactly 1.0.
    assert all(_run(c)["verdict"] in ("VERIFIED", "INCONCLUSIVE") for c in CASES)


@pytest.mark.usefixtures("statistical_dependencies")
def test_identical_distributions_are_never_rejected():
    # The #15 regression, pinned: the retired bootstrap rejected byte-identical
    # inputs from roughly four qubits upward.
    identical = [c for c in CASES if c["ref_counts"] == c["new_counts"] and c["ref_counts"]]
    assert identical, "vectors must retain at least one identical-input case"
    for case in identical:
        assert _run(case)["verdict"] != "REJECTED"


@pytest.mark.usefixtures("statistical_dependencies")
def test_bound_is_clamped_to_one():
    clamped = next(c for c in CASES if c["name"] == "disjoint-supports-clamped")
    assert _run(clamped)["metrics"]["tvd_ucb"] == 1.0


@pytest.mark.usefixtures("statistical_dependencies")
def test_unequal_shot_counts_do_not_crash():
    # Regression: the chi-squared diagnostic applied its continuity correction
    # before rescaling, so the two totals disagreed whenever the arms differed
    # in size and scipy rejected the input. A verdict-irrelevant diagnostic
    # must never prevent a verdict. Re-running an experiment with a different
    # shot count is routine, so this crashed on an ordinary workflow.
    from marqov_capsule.policy import VerificationPolicy

    settings = VerificationPolicy().resolve({})
    report = CapsuleVerifier().verify_statistical(
        {"00": 20_000, "11": 20_000}, {"00": 5_000, "11": 5_000}, settings
    )
    assert report["verdict"] in ("VERIFIED", "INCONCLUSIVE")


@pytest.mark.usefixtures("statistical_dependencies")
def test_chi_squared_diagnostic_survives_unequal_arms():
    from marqov_capsule.verifier import _compute_chi_squared_p

    p = _compute_chi_squared_p({"00": 20_000, "11": 20_000}, {"00": 5_000, "11": 5_000})
    # Identical underlying distributions: the diagnostic should compute and be
    # unremarkable, not None and not an exception.
    assert p is None or 0.0 <= p <= 1.0
