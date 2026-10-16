import json
import shutil
import sys
from pathlib import Path

import click

from marqov_capsule.cli._manifest import check_expected_id
from marqov_capsule.verifier import CapsuleVerifier


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--dest", "-d", default=None, help="Destination directory")
@click.option(
    "--id",
    "expected_id",
    default=None,
    callback=check_expected_id,
    help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def open_cmd(capsule, dest, expected_id, as_json):
    """Extract a capsule after full integrity verification."""
    capsule_path = Path(capsule)

    check = CapsuleVerifier.verify_integrity(capsule_path, expected_id=expected_id)
    if check["status"] != "pass":
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "status": "error",
                        "message": "Integrity verification failed",
                        "detail": check,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(
                "Error: integrity verification failed — capsule may be corrupt or tampered",
                err=True,
            )
            for err in check.get("errors", []):
                click.echo(f"  {err}", err=True)
        sys.exit(1)

    # Even on a pass, the manifest may be unauthenticated (no trusted --id).
    # Machine consumers must see the same warning text mode already prints, so a
    # forged-but-self-consistent capsule is not silently accepted (#58).
    warning = check.get("warning")

    if dest:
        dest_path = Path(dest)
        # ``Path(".").name`` is "" and ``Path("..").name`` is "..": resolve
        # first, as pack_capsule does for the archive name, so ``open .
        # --dest X`` lands in X/<real directory name> (#97).
        name = capsule_path.resolve().name
        if not name or name in (".", ".."):
            message = f"cannot derive a destination name from {capsule}"
            if as_json:
                click.echo(json.dumps({"status": "error", "message": message}, indent=2))
            else:
                click.echo(f"Error: {message}", err=True)
            sys.exit(1)
        opened_to = dest_path / name
        # symlinks=True copies links as links rather than materialising their target
        # content into the destination (defence-in-depth; verify_checksums already
        # rejects capsules containing symlinks). A non-regular member (FIFO/socket/
        # device) makes copytree raise shutil.Error — fail cleanly, no traceback.
        try:
            dest_path.mkdir(parents=True, exist_ok=True)
            # A fresh destination preserves the verified closed payload set and
            # prevents existing destination links from redirecting file writes.
            shutil.copytree(str(capsule_path), str(opened_to), symlinks=True)
        except (shutil.Error, OSError) as e:
            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "status": "error",
                            "message": "could not extract capsule",
                            "detail": str(e),
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(f"Error: could not extract capsule: {e}", err=True)
            sys.exit(1)
        if as_json:
            payload = {"status": "opened", "dest": str(opened_to), "warning": warning}
            click.echo(json.dumps(payload, indent=2))
        else:
            click.echo(f"Opened to: {opened_to}")
            if warning:
                click.echo(f"  Warning: {warning}", err=True)
    else:
        if as_json:
            click.echo(
                json.dumps(
                    {"status": "verified", "capsule": str(capsule_path), "warning": warning},
                    indent=2,
                )
            )
        else:
            click.echo(f"Verified: {capsule_path}")
            if warning:
                click.echo(f"  Warning: {warning}", err=True)
