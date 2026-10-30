import json
import sys
from pathlib import Path

import click

from marqov_capsule.cli._manifest import load_manifest_or_exit


def _safe_echo(value: object) -> None:
    """Display untrusted metadata without terminal commands or forged lines."""
    text = str(value)
    click.echo(
        "".join(
            char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
            for char in text
        )
    )


@click.command()
@click.argument("capsule", type=click.Path(exists=True, file_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def inspect_cmd(capsule: str, as_json: bool) -> None:
    """Show human-readable summary of a capsule."""
    manifest_path = Path(capsule) / "capsule.yaml"
    cap = load_manifest_or_exit(manifest_path, as_json)

    if as_json:
        click.echo(json.dumps(cap, indent=2, default=str))
        sys.exit(0)

    _safe_echo(f"Name:    {cap.get('name', '—')}")
    _safe_echo(f"Version: {cap.get('version', '—')}")
    _safe_echo(f"State:   {cap.get('lifecycle_state', '—')}")
    if cap.get("sealed_at"):
        _safe_echo(f"Sealed:  {cap['sealed_at']}")
    # inspect is a viewer, not a validator: a hand-edited draft with a field
    # of the wrong shape is shown as best it can be, never a traceback (#95).
    req = cap.get("requirements")
    if isinstance(req, dict):
        _safe_echo(f"Paradigm:   {req.get('paradigm', '—')}")
        _safe_echo(f"Max qubits: {req.get('max_qubit_count', '—')}")
    elif req is not None:
        _safe_echo(f"Requirements: {req!r} (expected a mapping)")
    tasks = cap.get("task_executions")
    if not isinstance(tasks, list):
        tasks = [] if tasks is None else [tasks]
    _safe_echo(f"Tasks:   {len(tasks)}")
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            _safe_echo(f"  [{i}] {t!r} (expected a mapping)")
            continue
        b = t.get("backend")
        b = b if isinstance(b, dict) else {}
        _safe_echo(
            f"  [{i}] {b.get('provider', '?')}/{b.get('name', '?')} — {t.get('status', '?')} — {t.get('result_type', '?')}"
        )
    if cap.get("derived_from"):
        _safe_echo(f"Derived from: {str(cap['derived_from'])[:16]}...")
    if cap.get("checksums_digest"):
        _safe_echo(f"Checksums digest: {str(cap['checksums_digest'])[:32]}...")
