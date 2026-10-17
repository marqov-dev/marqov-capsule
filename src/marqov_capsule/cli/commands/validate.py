import json
import sys
from pathlib import Path

import click

from marqov_capsule.validator import CapsuleValidator


@click.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def validate(yaml_file: str, as_json: bool) -> None:
    """Validate a capsule against the v1 schema.

    YAML_FILE may be a capsule directory (capsule.yaml is resolved inside it)
    or a path to a capsule.yaml file directly.
    """
    path = Path(yaml_file)
    if path.is_dir():
        path = path / "capsule.yaml"
        if not path.exists():
            click.echo(f"Error: capsule.yaml not found in {yaml_file}", err=True)
            sys.exit(1)

    result = CapsuleValidator.validate_file(path)
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            click.echo(f"Valid: {path}")
        else:
            click.echo(f"Invalid: {path}")
            for err in result["errors"]:
                click.echo(f"  {err['path']}: {err['message']}")
    sys.exit(0 if result["valid"] else 1)
