import sys
from pathlib import Path
import click

from marqov_capsule._canonical import dump_manifest_yaml


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
              help="Paradigm (gate-based, analog, annealing, classical). Repeatable.")
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

    # The profile-aware dumper quotes what the loader would otherwise type, so
    # ``--name 1e-3`` stays the string the user typed (#92).
    manifest_path.write_text(dump_manifest_yaml(manifest), encoding="utf-8")
    click.echo(f"Initialised: {manifest_path}")
    click.echo(f"Edit capsule.yaml, add payload files, then run: marqov-capsule seal {directory}")
