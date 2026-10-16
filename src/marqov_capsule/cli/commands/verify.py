import json
import sys
import tarfile
import tempfile
from pathlib import Path

import click

from marqov_capsule.archive import payload_digest, unpack_capsule
from marqov_capsule.cli._manifest import check_expected_id
from marqov_capsule.verifier import CapsuleVerifier


@click.command()
@click.argument("capsule", type=click.Path(exists=True))
@click.option(
    "--id",
    "expected_id",
    default=None,
    callback=check_expected_id,
    help="Trusted capsule ID to verify the manifest against (spec §6 layer 3)",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def verify(capsule, expected_id, as_json):
    """Verify the integrity of a sealed capsule directory or archive.

    This checks that the artifact is unchanged since sealing. To test whether
    two result samples are equivalent, use `marqov-capsule compare`.
    """
    path = Path(capsule)
    verifier = CapsuleVerifier()

    if path.is_dir():
        result = verifier.verify_integrity(path, expected_id=expected_id)
        result["payload_digest"] = _payload_digest_or_none(path)
        _report(result, as_json)
        sys.exit(0 if result["status"] == "pass" else 1)

    # An archive: unpack to a temporary directory and verify the contents.
    if not tarfile.is_tarfile(str(path)):
        message = f"{path} is not a capsule directory or archive"
        if as_json:
            click.echo(json.dumps({"status": "fail", "errors": [message]}))
        else:
            click.echo(f"Error: {message}", err=True)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            unpacked = unpack_capsule(path, output_dir=tmp)
        except (ValueError, OSError, tarfile.TarError, EOFError) as e:
            if as_json:
                click.echo(
                    json.dumps({"status": "fail", "errors": [f"could not unpack archive: {e}"]})
                )
            else:
                click.echo(f"Error: could not unpack {path}: {e}", err=True)
            sys.exit(1)
        result = verifier.verify_integrity(unpacked, expected_id=expected_id)
        result["payload_digest"] = _payload_digest_or_none(unpacked)
        result["archive"] = str(path)
        _report(result, as_json)
        sys.exit(0 if result["status"] == "pass" else 1)


def _payload_digest_or_none(capsule_dir: Path):
    """The payload digest of an unsealed or malformed capsule is meaningless."""
    try:
        return payload_digest(capsule_dir)
    except (OSError, ValueError):
        return None


def _report(result: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    click.echo(f"Integrity verification: {result['status'].upper()}")
    if result.get("payload_digest"):
        click.echo(f"  Payload digest: {result['payload_digest']}")
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
        click.echo(
            "  Note: manifest is not authenticated — nothing on disk can "
            "attest to it. Pass --id <trusted-id> to check layer 3."
        )
