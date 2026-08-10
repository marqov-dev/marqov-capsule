import json
import sys
from pathlib import Path
import click
from marqov_capsule.verifier import CapsuleVerifier
from marqov_capsule._canonical import load_manifest_yaml
from marqov_capsule.policy import VerificationPolicy


def _load_counts(cap_dir: Path) -> dict:
    """Read shot counts from payload/results.json."""
    results_path = cap_dir / "payload" / "results.json"
    if not results_path.exists():
        click.echo(f"Error: payload/results.json not found in {cap_dir}", err=True)
        sys.exit(1)

    results = json.loads(results_path.read_text())
    counts = results.get("counts")
    if not isinstance(counts, dict):
        click.echo(f"Error: payload/results.json must have a 'counts' dict in {cap_dir}", err=True)
        sys.exit(1)
    return counts


def _load_declared_settings(cap_dir: Path) -> dict:
    """Read the capsule's *declared* verification_settings.

    Advisory only. These come from untrusted input and must be passed through
    VerificationPolicy.resolve before anything acts on them (#30) — never used
    as thresholds directly.
    """
    manifest_path = cap_dir / "capsule.yaml"
    if not manifest_path.exists():
        click.echo(f"Error: capsule.yaml not found in {cap_dir}", err=True)
        sys.exit(1)

    cap = load_manifest_yaml(manifest_path.read_text())
    if not isinstance(cap, dict):
        return {}
    tasks = cap.get("task_executions") or []
    declared = tasks[0].get("verification_settings") if tasks else None
    return declared if isinstance(declared, dict) else {}


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--against", default=None, type=click.Path(exists=True, file_okay=False),
              help="Reference capsule for statistical equivalence test")
@click.option("--id", "expected_id", default=None,
              help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)")
@click.option("--epsilon", type=float, default=None,
              help="Acceptance threshold on TVD. Policy value; a capsule may declare a "
                   "tighter one but never a looser one.")
@click.option("--min-shots", type=int, default=None,
              help="Minimum shots for a verdict. Never read from the capsule.")
@click.option("--honor-calibration-drift", is_flag=True,
              help="Allow a capsule's calibration_drift regime to widen the threshold, "
                   "up to the policy drift ceiling. Off by default.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def verify(capsule, against, expected_id, epsilon, min_shots, honor_calibration_drift, as_json):
    """Verify capsule integrity, or statistical equivalence against a reference."""
    verifier = CapsuleVerifier()

    # With two capsules there is no unambiguous target for a single trusted ID.
    if against is not None and expected_id is not None:
        click.echo("Error: --id is ambiguous with --against, which takes two capsules. "
                   "Verify each capsule's identity separately.", err=True)
        sys.exit(2)

    overrides = {}
    if epsilon is not None:
        overrides["epsilon"] = epsilon
    if min_shots is not None:
        overrides["min_shots"] = min_shots
    policy = VerificationPolicy(honor_calibration_drift=honor_calibration_drift, **overrides)

    if against is None:
        result = verifier.verify_integrity(capsule, expected_id=expected_id)
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Integrity verification: {result['status'].upper()}")
            if result.get("capsule_id"):
                click.echo(f"  Capsule ID: {result['capsule_id']}")
            checksums = result.get("checksums", {})
            for path, info in checksums.get("files", {}).items():
                if not info.get("match", True):
                    click.echo(f"  FAIL: {path}")
            for path in checksums.get("extra", []):
                click.echo(f"  EXTRA (not listed in .checksums): {path}")
            for err in result.get("errors", []):
                click.echo(f"  {err}")
            if result["status"] == "pass" and not result["manifest_authenticated"]:
                click.echo("  Note: manifest is not authenticated — nothing on disk can "
                           "attest to it. Pass --id <trusted-id> to check layer 3.")
        sys.exit(0 if result["status"] == "pass" else 1)

    ref_dir, new_dir = Path(against), Path(capsule)

    # Integrity first. Comparing shot counts from a capsule whose payload does not
    # match its own seal is meaningless — the numbers being compared are not the
    # ones that were sealed. This path previously ran no integrity check at all.
    for label, cap_dir in (("reference", ref_dir), ("candidate", new_dir)):
        check = verifier.verify_integrity(cap_dir)
        if check["status"] != "pass":
            if as_json:
                click.echo(json.dumps({"status": "error", "capsule": label,
                                       "message": f"integrity verification failed for the {label} capsule",
                                       "detail": check}, indent=2))
            else:
                click.echo(f"Error: integrity verification failed for the {label} "
                           f"capsule ({cap_dir})", err=True)
                for err in check.get("errors", []):
                    click.echo(f"  {err}", err=True)
            sys.exit(1)

    ref_counts = _load_counts(ref_dir)
    new_counts = _load_counts(new_dir)

    # The reference capsule declares what its author considers equivalent. That is
    # useful information and not a threshold: resolve() clamps it to policy.
    resolved = policy.resolve(_load_declared_settings(ref_dir))

    result = verifier.verify_statistical(ref_counts, new_counts, resolved)
    result["policy"] = {k: resolved[k] for k in (
        "epsilon", "epsilon_declared", "epsilon_ceiling", "epsilon_clamped",
        "min_shots", "calibration_drift_declared", "calibration_drift_honoured")}

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Statistical verification: {result['verdict']}")
        click.echo(f"  {result['reason']}")
        m = result.get("metrics", {})
        click.echo(f"  TVD: {m.get('total_variation_distance', 0):.4f}  "
                   f"CI: [{m.get('tvd_ci_lower', 0):.4f}, {m.get('tvd_ci_upper', 0):.4f}]  "
                   f"ε: {m.get('epsilon_used', '—')}")
        if resolved["epsilon_clamped"]:
            click.echo(f"  Note: reference capsule declared ε={resolved['epsilon_declared']}, "
                       f"clamped to the policy ceiling {resolved['epsilon_ceiling']}. "
                       f"A capsule may tighten the threshold, never loosen it.")
        if resolved["calibration_drift_declared"] and not resolved["calibration_drift_honoured"]:
            click.echo("  Note: reference declared tolerance_regime=calibration_drift; "
                       "not honoured. Pass --honor-calibration-drift to allow it.")
    sys.exit(0 if result["verdict"] == "VERIFIED" else 1)
