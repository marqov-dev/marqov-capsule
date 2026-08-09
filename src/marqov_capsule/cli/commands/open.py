import json
import shutil
import sys
from pathlib import Path
import click
from marqov_capsule.verifier import CapsuleVerifier


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--dest", "-d", default=None, help="Destination directory")
@click.option("--id", "expected_id", default=None,
              help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def open_cmd(capsule, dest, expected_id, as_json):
    """Extract a capsule after full integrity verification."""
    capsule_path = Path(capsule)

    check = CapsuleVerifier.verify_integrity(capsule_path, expected_id=expected_id)
    if check["status"] != "pass":
        if as_json:
            click.echo(json.dumps({"status": "error", "message": "Integrity verification failed", "detail": check}, indent=2))
        else:
            click.echo("Error: integrity verification failed — capsule may be corrupt or tampered", err=True)
            for err in check.get("errors", []):
                click.echo(f"  {err}", err=True)
        sys.exit(1)

    if dest:
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        # symlinks=True copies links as links rather than materialising their target
        # content into the destination (defence-in-depth; verify_checksums already
        # rejects capsules containing symlinks).
        shutil.copytree(str(capsule_path), str(dest_path / capsule_path.name),
                        dirs_exist_ok=True, symlinks=True)
        if as_json:
            click.echo(json.dumps({"status": "opened", "dest": str(dest_path / capsule_path.name)}, indent=2))
        else:
            click.echo(f"Opened to: {dest_path / capsule_path.name}")
    else:
        if as_json:
            click.echo(json.dumps({"status": "verified", "capsule": str(capsule_path)}, indent=2))
        else:
            click.echo(f"Verified: {capsule_path}")
