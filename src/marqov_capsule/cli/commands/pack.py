import json
import tarfile
from pathlib import Path

import click

from marqov_capsule._canonical import compute_capsule_id
from marqov_capsule.archive import pack_capsule, payload_digest, unpack_capsule
from marqov_capsule.cli._manifest import fail, load_manifest_or_exit

# Everything the archive layer documents, plus the OS and tarfile families it
# can still surface — a crafted or merely broken .capsule must be a one-line
# error and exit 1 in both output modes, never a traceback (#96, #124).
_ARCHIVE_ERRORS = (FileNotFoundError, ValueError, OSError, tarfile.TarError, EOFError)


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
    # Read the manifest *before* writing anything: a draft that does not parse
    # must not leave an archive behind (#95).
    manifest = load_manifest_or_exit(Path(directory) / "capsule.yaml", as_json)

    try:
        archive_path = pack_capsule(directory, output_path=output)
        # Identity is the capsule ID: it covers the manifest, which .checksums
        # deliberately does not. The payload digest is reported too, but
        # labelled as what it is rather than as a content identifier (#48).
        capsule_id = compute_capsule_id(manifest)
        digest = payload_digest(archive_path)
    except _ARCHIVE_ERRORS as e:
        fail(str(e), as_json)

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
    except _ARCHIVE_ERRORS as e:
        fail(str(e), as_json)

    if as_json:
        click.echo(json.dumps({"path": str(restored)}, indent=2))
    else:
        click.echo(f"Unpacked: {restored}")
