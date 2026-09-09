import json
import sys
from pathlib import Path
import click
from marqov_capsule._canonical import load_manifest_yaml


def _safe_echo(value):
    """Display untrusted metadata without terminal commands or forged lines."""
    text = str(value)
    click.echo("".join(char if char.isprintable() else
                       char.encode("unicode_escape").decode("ascii") for char in text))


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

    _safe_echo(f"Name:    {cap.get('name', '—')}")
    _safe_echo(f"Version: {cap.get('version', '—')}")
    _safe_echo(f"State:   {cap.get('lifecycle_state', '—')}")
    if cap.get("sealed_at"):
        _safe_echo(f"Sealed:  {cap['sealed_at']}")
    if cap.get("requirements"):
        req = cap["requirements"]
        _safe_echo(f"Paradigm:   {req.get('paradigm', '—')}")
        _safe_echo(f"Max qubits: {req.get('max_qubit_count', '—')}")
    tasks = cap.get("task_executions", [])
    _safe_echo(f"Tasks:   {len(tasks)}")
    for i, t in enumerate(tasks):
        b = t.get("backend", {})
        _safe_echo(f"  [{i}] {b.get('provider', '?')}/{b.get('name', '?')} — {t.get('status', '?')} — {t.get('result_type', '?')}")
    if cap.get("derived_from"):
        _safe_echo(f"Derived from: {cap['derived_from'][:16]}...")
    if cap.get("checksums_digest"):
        _safe_echo(f"Checksums digest: {cap['checksums_digest'][:32]}...")
