import json
import sys
from pathlib import Path
import click
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.redactor import CapsuleRedactor, RedactorError
from marqov_capsule._canonical import load_manifest_yaml


def _report_scope(scan_result: dict) -> None:
    """Say out loud when .capsuleignore narrowed what was scanned.

    The ignore file lives inside the capsule, so a capsule received from
    someone else and re-sealed carries their scan scope. Silent narrowing is
    the whole problem (#34).
    """
    patterns = scan_result.get("capsuleignore_patterns") or []
    if not patterns:
        return
    skipped = scan_result.get("skipped") or []
    click.echo(f"  Note: .capsuleignore narrowed the scan — {len(skipped)} file(s) "
               f"not scanned, patterns: {', '.join(patterns)}")
    for path in skipped[:10]:
        click.echo(f"    skipped: {path}")
    if len(skipped) > 10:
        click.echo(f"    ... and {len(skipped) - 10} more")


@click.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option("--warn-only", is_flag=True, help="Warn on credentials instead of blocking")
@click.option("--dry-run", is_flag=True, help="Scan for issues and report; never write")
@click.option("--sealed-by", default=None, help="Identity string recorded in sealed_by field")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def seal(directory, warn_only, dry_run, sealed_by, as_json):
    """Scan for secrets then seal a capsule directory."""
    capsule_dir = Path(directory)
    manifest_path = capsule_dir / "capsule.yaml"

    if not manifest_path.exists():
        click.echo(f"Error: capsule.yaml not found in {directory}. Run 'marqov-capsule init' first.", err=True)
        sys.exit(1)

    # --dry-run: scan only, always exits 0 (report flag, not a gate)
    if dry_run:
        redactor = CapsuleRedactor(capsule_dir)
        scan_result = redactor.scan()
        status = "clean" if not scan_result["has_secrets"] else "warnings"
        if as_json:
            click.echo(json.dumps({
                "status": status,
                "findings": scan_result["findings"],
                "skipped": scan_result["skipped"],
                "capsuleignore_patterns": scan_result["capsuleignore_patterns"],
            }, indent=2))
        else:
            if scan_result["has_secrets"]:
                click.echo(f"Dry run: {len(scan_result['findings'])} credential pattern(s) found")
                for f in scan_result["findings"]:
                    click.echo(f"  {f['file']}:{f['line']} — {f['reason']}: {f['match']}")
            else:
                click.echo("Dry run: no issues found")
            _report_scope(scan_result)
        sys.exit(0)

    # Load draft manifest using timestamp-safe loader
    manifest = load_manifest_yaml(manifest_path.read_text())
    builder = CapsuleBuilder.from_manifest(manifest)

    try:
        capsule_id = builder.seal(
            capsule_dir=capsule_dir,
            sealed_by=sealed_by or "marqov-capsule-cli",
            warn_only=warn_only,
        )
    except RedactorError as e:
        if as_json:
            click.echo(json.dumps({"status": "error", "message": str(e)}, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
            click.echo("Use --warn-only to seal despite credential warnings.", err=True)
        sys.exit(1)

    # Reading the ignore file is cheap; this does not re-run the scan.
    narrowed = CapsuleRedactor(capsule_dir).capsuleignore_patterns

    if as_json:
        click.echo(json.dumps({"status": "sealed", "capsule_id": capsule_id,
                               "directory": str(directory),
                               "capsuleignore_patterns": narrowed}, indent=2))
    else:
        click.echo(f"Sealed: {capsule_id}")
        click.echo(f"  Directory: {directory}")
        if narrowed:
            click.echo(f"  Note: .capsuleignore narrowed the credential scan — "
                       f"patterns: {', '.join(narrowed)}. Review these when sealing "
                       f"a capsule you did not author.")
