import json
import sys
from pathlib import Path
import click
from marqov_capsule.verifier import CapsuleVerifier
from marqov_capsule._canonical import load_manifest_yaml

_DEFAULT_VSETTINGS = {"epsilon": 0.02, "min_shots": 100, "tolerance_regime": "strict"}


def _load_counts_and_vsettings(cap_dir: Path) -> tuple:
    """Read shot counts from payload/results.json and verification_settings from capsule.yaml."""
    manifest_path = cap_dir / "capsule.yaml"
    if not manifest_path.exists():
        click.echo(f"Error: capsule.yaml not found in {cap_dir}", err=True)
        sys.exit(1)

    cap = load_manifest_yaml(manifest_path.read_text())
    tasks = cap.get("task_executions", [])
    vsettings = (tasks[0].get("verification_settings") if tasks else None) or _DEFAULT_VSETTINGS

    results_path = cap_dir / "payload" / "results.json"
    if not results_path.exists():
        click.echo(f"Error: payload/results.json not found in {cap_dir}", err=True)
        sys.exit(1)

    results = json.loads(results_path.read_text())
    counts = results.get("counts")
    if not isinstance(counts, dict):
        click.echo(f"Error: payload/results.json must have a 'counts' dict in {cap_dir}", err=True)
        sys.exit(1)

    return counts, vsettings


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--against", default=None, type=click.Path(exists=True, file_okay=False),
              help="Reference capsule for statistical equivalence test")
@click.option("--id", "expected_id", default=None,
              help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def verify(capsule, against, expected_id, as_json):
    """Verify capsule integrity, or statistical equivalence against a reference."""
    verifier = CapsuleVerifier()

    # --against runs the statistical path and checks no integrity layer, so
    # accepting --id there would imply a guarantee that was never checked.
    if against is not None and expected_id is not None:
        click.echo("Error: --id cannot be combined with --against; --against does not "
                   "verify integrity. Run 'verify --id' separately.", err=True)
        sys.exit(2)

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

    ref_counts, vsettings = _load_counts_and_vsettings(Path(against))
    new_counts, _ = _load_counts_and_vsettings(Path(capsule))

    result = verifier.verify_statistical(ref_counts, new_counts, vsettings)
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Statistical verification: {result['verdict']}")
        click.echo(f"  {result['reason']}")
        m = result.get("metrics", {})
        click.echo(f"  TVD: {m.get('total_variation_distance', 0):.4f}  "
                   f"CI: [{m.get('tvd_ci_lower', 0):.4f}, {m.get('tvd_ci_upper', 0):.4f}]  "
                   f"ε: {m.get('epsilon_used', '—')}")
    sys.exit(0 if result["verdict"] == "VERIFIED" else 1)
