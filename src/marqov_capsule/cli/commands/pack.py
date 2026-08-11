import json
import sys
from pathlib import Path

import click

from marqov_capsule._canonical import compute_capsule_id, load_manifest_yaml
from marqov_capsule.archive import pack_capsule, payload_digest, unpack_capsule


@click.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--output", "-o", default=None, help="Archive path (default: <name>.capsule)")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def pack(directory, output, as_json):
    """Pack a sealed capsule directory into a deterministic archive.

    The archive is byte-reproducible: packing the same capsule twice yields
    identical bytes. Identity is the capsule ID, which covers the manifest;
    the payload digest covers only the files listed in .checksums.
    """
    try:
        archive_path = pack_capsule(directory, output_path=output)
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Identity is the capsule ID: it covers the manifest, which .checksums
    # deliberately does not. The payload digest is reported too, but labelled
    # as what it is rather than as a content identifier (#48).
    manifest = load_manifest_yaml((Path(directory) / "capsule.yaml").read_text())
    capsule_id = compute_capsule_id(manifest)
    digest = payload_digest(archive_path)

    if as_json:
        click.echo(json.dumps({
            "path": str(archive_path),
            "capsule_id": capsule_id,
            "payload_digest": digest,
        }, indent=2))
    else:
        click.echo(f"Packed: {archive_path}")
        click.echo(f"  Capsule ID:     {capsule_id}")
        click.echo(f"  Payload digest: {digest}")


@click.command()
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default=None, help="Destination directory")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def unpack(archive, output, as_json):
    """Unpack a capsule archive into a directory."""
    dest = Path(output) if output else Path.cwd()
    try:
        restored = unpack_capsule(archive, output_dir=dest)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps({"path": str(restored)}, indent=2))
    else:
        click.echo(f"Unpacked: {restored}")
