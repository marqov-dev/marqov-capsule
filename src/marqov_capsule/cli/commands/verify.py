import json
import sys
import click
from marqov_capsule.verifier import CapsuleVerifier


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "expected_id", default=None,
              help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def verify(capsule, expected_id, as_json):
    """Verify the integrity of a sealed capsule.

    Comparing two capsules for equivalence is not available in this release —
    the estimator is miscalibrated and returns REJECTED on identical
    distributions above roughly two qubits. Tracked in #15.
    """
    verifier = CapsuleVerifier()
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
