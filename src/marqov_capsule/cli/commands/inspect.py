import json
import sys
from pathlib import Path
import click
from marqov_capsule._canonical import load_manifest_yaml


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def inspect_cmd(capsule, as_json):
    """Show human-readable summary of a capsule."""
    manifest_path = Path(capsule) / "capsule.yaml"
    if not manifest_path.exists():
        click.echo(f"Error: capsule.yaml not found in {capsule}", err=True)
        sys.exit(1)

    cap = load_manifest_yaml(manifest_path.read_text())

    if as_json:
        click.echo(json.dumps(cap, indent=2, default=str))
        sys.exit(0)

    click.echo(f"Name:    {cap.get('name', '—')}")
    click.echo(f"Version: {cap.get('version', '—')}")
    click.echo(f"State:   {cap.get('lifecycle_state', '—')}")
    if cap.get("sealed_at"):
        click.echo(f"Sealed:  {cap['sealed_at']}")
    if cap.get("requirements"):
        req = cap["requirements"]
        click.echo(f"Paradigm:   {req.get('paradigm', '—')}")
        click.echo(f"Max qubits: {req.get('max_qubit_count', '—')}")
    tasks = cap.get("task_executions", [])
    click.echo(f"Tasks:   {len(tasks)}")
    for i, t in enumerate(tasks):
        b = t.get("backend", {})
        click.echo(f"  [{i}] {b.get('provider', '?')}/{b.get('name', '?')} — {t.get('status', '?')} — {t.get('result_type', '?')}")
    if cap.get("derived_from"):
        click.echo(f"Derived from: {cap['derived_from'][:16]}...")
    if cap.get("checksums_digest"):
        click.echo(f"Checksums digest: {cap['checksums_digest'][:32]}...")
