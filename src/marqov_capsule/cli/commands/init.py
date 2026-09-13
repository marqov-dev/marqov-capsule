import sys
from pathlib import Path
import click
import yaml


_DRAFT_MANIFEST = {
    "version": "1.0.0",
    "name": "my-capsule",
    "lifecycle_state": "draft",
    "requirements": {
        "paradigm": ["gate-based"],
        "max_qubit_count": 1,
    },
    "task_executions": [],
}


@click.command()
@click.argument("directory", type=click.Path(file_okay=False))
@click.option("--name", default=None, help="Capsule name (defaults to directory name)")
@click.option("--paradigm", "paradigms", multiple=True,
              type=click.Choice(["gate-based", "analog", "classical"]),
              help="Paradigm (gate-based, analog, classical). Repeatable.")
@click.option("--qubits", default=None, type=int, help="Maximum qubit count")
@click.option("--force", is_flag=True, help="Overwrite existing capsule.yaml")
def init(directory, name, paradigms, qubits, force):
    """Create a draft capsule.yaml in DIRECTORY."""
    capsule_dir = Path(directory)
    capsule_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = capsule_dir / "capsule.yaml"
    if manifest_path.exists() and not force:
        click.echo(f"Error: {manifest_path} already exists. Use --force to overwrite.", err=True)
        sys.exit(1)

    import copy
    manifest = copy.deepcopy(_DRAFT_MANIFEST)
    manifest["name"] = name or capsule_dir.name
    if paradigms:
        manifest["requirements"]["paradigm"] = list(paradigms)
    if qubits is not None:
        manifest["requirements"]["max_qubit_count"] = qubits

    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
    click.echo(f"Initialised: {manifest_path}")
    click.echo("Edit capsule.yaml, add payload files, then run: marqov-capsule seal .")
