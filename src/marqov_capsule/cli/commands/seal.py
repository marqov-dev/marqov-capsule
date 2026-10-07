import json
import sys
from pathlib import Path
import click
from marqov_capsule.builder import CapsuleBuilder, CapsuleStateError, CapsuleValidationError
from marqov_capsule.redactor import CapsuleRedactor, RedactorError, finding_location
from marqov_capsule.cli._manifest import load_manifest_or_exit


def _report_findings(findings: list[dict]) -> None:
    """Print every credential finding a seal let through, to stderr.

    ``--warn-only`` used to seal a token into a content-addressed record and
    say nothing; Tier B (entropy) findings were never printed at all (#105).
    Same ``file:line — reason: match`` shape as ``--dry-run``.
    """
    if not findings:
        return
    blocking = sum(1 for f in findings if f.get("blocking"))
    click.echo(f"  Warning: {len(findings)} credential finding(s) sealed into this capsule"
               f" ({blocking} blocking, {len(findings) - blocking} entropy warning(s)):", err=True)
    for f in findings:
        click.echo(f"    {finding_location(f)} — {f['reason']}: {f['match']}", err=True)


def _report_binary(scan_result: dict) -> None:
    """Name the binary files the credential scan did not read (#98)."""
    binary = scan_result.get("skipped_binary") or []
    if not binary:
        return
    click.echo(f"  Note: {len(binary)} binary file(s) not scanned for credentials:")
    for path in binary[:10]:
        click.echo(f"    binary: {path}")
    if len(binary) > 10:
        click.echo(f"    ... and {len(binary) - 10} more")


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
@click.option("--no-validate", is_flag=True,
              help="Seal even if the manifest does not validate against the schema")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def seal(directory, warn_only, dry_run, sealed_by, no_validate, as_json):
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
                "skipped_binary": scan_result["skipped_binary"],
                "capsuleignore_patterns": scan_result["capsuleignore_patterns"],
            }, indent=2))
        else:
            if scan_result["has_secrets"]:
                click.echo(f"Dry run: {len(scan_result['findings'])} credential pattern(s) found")
                for f in scan_result["findings"]:
                    click.echo(f"  {finding_location(f)} — {f['reason']}: {f['match']}")
            else:
                click.echo("Dry run: no issues found")
            _report_scope(scan_result)
            _report_binary(scan_result)
        sys.exit(0)

    # Load the draft through the profile-aware loader; a hand-edited draft that
    # does not parse, or is not a mapping, is a clean exit 1 (#95).
    manifest = load_manifest_or_exit(manifest_path, as_json)

    try:
        builder = CapsuleBuilder.from_manifest(manifest)
        capsule_id = builder.seal(
            capsule_dir=capsule_dir,
            sealed_by=sealed_by or "marqov-capsule-cli",
            warn_only=warn_only,
            validate=not no_validate,
        )
    except CapsuleStateError as e:
        # Already sealed/archived: refuse rather than silently re-seal mutated
        # content with a fresh ID. Same gate the Python API enforces. (#59)
        if as_json:
            click.echo(json.dumps({"status": "error", "message": str(e)}, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except CapsuleValidationError as e:
        # Spec §8: a sealed manifest validates against the schema. Refuse, and
        # list every error the way `validate` does (#111).
        if as_json:
            click.echo(json.dumps({"status": "error",
                                   "message": "manifest does not validate against the capsule schema",
                                   "errors": e.errors}, indent=2))
        else:
            click.echo("Error: manifest does not validate against the capsule schema:", err=True)
            for err in e.errors:
                click.echo(f"  {err['path']}: {err['message']}", err=True)
            click.echo("Fix capsule.yaml, or use --no-validate to seal anyway.", err=True)
        sys.exit(1)
    except RedactorError as e:
        if as_json:
            click.echo(json.dumps({"status": "error", "message": str(e)}, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
            click.echo("Use --warn-only to seal despite credential warnings.", err=True)
        sys.exit(1)
    except (ValueError, OSError) as e:
        # A draft the builder cannot seal (missing requirements, wrongly typed
        # containers, an integer past the canonical range): message, exit 1.
        if as_json:
            click.echo(json.dumps({"status": "error", "message": str(e)}, indent=2))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    scan_result = builder.scan_result or {}
    findings = scan_result.get("findings", [])
    narrowed = scan_result.get("capsuleignore_patterns", [])

    if as_json:
        click.echo(json.dumps({"status": "sealed", "capsule_id": capsule_id,
                               "directory": str(directory),
                               "findings": findings,
                               "skipped_binary": scan_result.get("skipped_binary", []),
                               "capsuleignore_patterns": narrowed}, indent=2))
    else:
        click.echo(f"Sealed: {capsule_id}")
        click.echo(f"  Directory: {directory}")
        _report_findings(findings)
        _report_binary(scan_result)
        if narrowed:
            click.echo(f"  Note: .capsuleignore narrowed the credential scan — "
                       f"patterns: {', '.join(narrowed)}. Review these when sealing "
                       f"a capsule you did not author.")
