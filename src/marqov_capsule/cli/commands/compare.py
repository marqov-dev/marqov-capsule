import json
import sys
from pathlib import Path

import click

from marqov_capsule.policy import VerificationPolicy
from marqov_capsule.verifier import CapsuleVerifier

# INCONCLUSIVE gets its own exit code rather than 1. This estimator certifies
# equivalence within a tolerance; it cannot assert that two distributions
# differ, so "1" — which every shell reads as failure — would licence exactly
# the misreading the one-sided bound exists to prevent. 2 stays click's usage
# error.
EXIT_VERIFIED = 0
EXIT_ERROR = 1
EXIT_INCONCLUSIVE = 3

_VERDICT_EXIT = {"VERIFIED": EXIT_VERIFIED, "INCONCLUSIVE": EXIT_INCONCLUSIVE}


class _CountsError(Exception):
    """A supplied file could not be read as a counts mapping."""


def _fail(message, as_json):
    if as_json:
        click.echo(json.dumps({"status": "error", "message": message}, indent=2))
    else:
        click.echo(f"Error: {message}", err=True)
    sys.exit(EXIT_ERROR)


def _load_counts(path, counts_key):
    """Read a counts mapping from a JSON file.

    Accepts both shapes this project produces: a bare outcome->count mapping,
    and a wrapper carrying the mapping under a key (``counts`` by default).
    """
    try:
        raw = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise _CountsError(f"{path} is not valid JSON: {e}") from e
    except OSError as e:
        raise _CountsError(f"could not read {path}: {e}") from e

    if not isinstance(raw, dict):
        raise _CountsError(f"{path} must contain a JSON object, not {type(raw).__name__}")

    if counts_key is not None:
        if counts_key not in raw:
            raise _CountsError(f"{path} has no key '{counts_key}'")
        counts = raw[counts_key]
    elif isinstance(raw.get("counts"), dict):
        counts = raw["counts"]
    else:
        counts = raw

    if not isinstance(counts, dict):
        raise _CountsError(f"{path}: counts must be a mapping of outcome to count")

    return {str(outcome): _as_count(path, outcome, value) for outcome, value in counts.items()}


def _as_count(path, outcome, value):
    # bool is an int subclass; a True here means the file is not counts.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _CountsError(f"{path}: count for '{outcome}' must be an integer, got {value!r}")
    if value < 0:
        raise _CountsError(f"{path}: count for '{outcome}' is negative ({value})")
    return value


def _report(result, settings, as_json):
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    metrics = result.get("metrics", {})
    click.echo(f"Verdict: {result['verdict']}")
    if "tvd_ucb" in metrics:
        click.echo(f"  tvd_ucb:  {metrics['tvd_ucb']:.5f}")
    if "total_variation_distance" in metrics:
        click.echo(f"  tvd:      {metrics['total_variation_distance']:.5f}")
    click.echo(f"  epsilon:  {metrics.get('epsilon_used')}")
    click.echo(f"  shots:    {metrics.get('shots_ref')} / {metrics.get('shots_new')}")
    if "alpha" in metrics:
        click.echo(f"  alpha:    {metrics['alpha']}")
    if result.get("reason"):
        click.echo(f"  {result['reason']}")

    if result["verdict"] == "INCONCLUSIVE":
        click.echo(_inconclusive_guidance(metrics))


def _inconclusive_guidance(metrics):
    """Say which kind of INCONCLUSIVE this is.

    A bare INCONCLUSIVE cannot be told apart from "did not reproduce" (#85).
    The bound's slack shrinks as ~1/sqrt(n), so when the point estimate is
    already inside epsilon the honest advice is: take more shots.
    """
    shots_ref = metrics.get("shots_ref", 0)
    shots_new = metrics.get("shots_new", 0)
    if not shots_ref or not shots_new:
        return "  Note: one arm has zero shots — TVD is undefined for an empty sample."

    min_shots = metrics.get("min_shots")
    if min_shots is not None and min_shots > min(shots_ref, shots_new):
        return (f"  Note: below the {min_shots}-shot floor, so no bound was computed. "
                "Re-run with more shots.")

    tvd = metrics.get("total_variation_distance")
    epsilon = metrics.get("epsilon_used")
    if tvd is not None and epsilon is not None and tvd <= epsilon:
        return ("  Note: the point estimate is within epsilon but the confidence bound is not. "
                "This is a sample-size limit, not evidence of a difference — more shots "
                "should resolve it.")
    return ("  Note: equivalence was not demonstrated at this epsilon. This is not proof of a "
            "difference; the test never asserts one.")


@click.command()
@click.argument("ref", type=click.Path(exists=True, dir_okay=False))
@click.argument("new", type=click.Path(exists=True, dir_okay=False))
# Ranges are enforced at the option, as usage errors (exit 2). TVD is bounded
# by 1, so an epsilon >= 1 certifies everything; alpha outside (0, 1) is not
# an error rate; and a non-positive shot floor is never applied. Silently
# substituting a default — which the verifier does for a *capsule-declared*
# alpha — would hide an operator's typo behind a plausible report (#99).
@click.option("--epsilon", type=click.FloatRange(0.0, 1.0, min_open=True, max_open=True), default=None,
              help="Equivalence tolerance owned by the verifier, in (0, 1) (default: policy default)")
@click.option("--min-shots", type=click.IntRange(min=1), default=None,
              help="Shot floor below which no bound is computed (>= 1)")
@click.option("--alpha", type=click.FloatRange(0.0, 1.0, min_open=True, max_open=True), default=None,
              help="Error rate for the one-sided confidence bound, in (0, 1)")
@click.option("--counts-key", default=None,
              help="Key holding the counts mapping (default: 'counts', else the whole object)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def compare(ref, new, epsilon, min_shots, alpha, counts_key, as_json):
    """Test whether two count samples are equivalent within a tolerance.

    Compares the supplied result files; it does not verify the capsules they
    came from. Verify integrity separately with `marqov-capsule verify`.

    The verdict space is VERIFIED / INCONCLUSIVE — the one-sided bound
    certifies equivalence and never asserts that two distributions differ.
    Exits 0 when VERIFIED, 3 when INCONCLUSIVE, 1 on error.
    """
    try:
        ref_counts = _load_counts(ref, counts_key)
        new_counts = _load_counts(new, counts_key)
    except _CountsError as e:
        _fail(str(e), as_json)

    # Thresholds belong to the verifier, never to the artifact under test.
    # Nothing here is read from a capsule; the flags are the operator's policy.
    defaults = VerificationPolicy()
    policy = VerificationPolicy(
        epsilon=defaults.epsilon if epsilon is None else epsilon,
        epsilon_drift=defaults.epsilon_drift,
        min_shots=defaults.min_shots if min_shots is None else min_shots,
        alpha=defaults.alpha if alpha is None else alpha,
    )
    settings = policy.resolve({})

    try:
        result = CapsuleVerifier().verify_statistical(ref_counts, new_counts, settings)
    except ImportError as e:
        _fail(str(e), as_json)

    _report(result, settings, as_json)
    sys.exit(_VERDICT_EXIT.get(result["verdict"], EXIT_ERROR))
