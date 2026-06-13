import json
import sys
import click
from marqov_capsule.validator import CapsuleValidator


@click.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def validate(yaml_file, as_json):
    """Validate a capsule.yaml against the v1 schema."""
    result = CapsuleValidator.validate_file(yaml_file)
    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            click.echo(f"Valid: {yaml_file}")
        else:
            click.echo(f"Invalid: {yaml_file}")
            for err in result["errors"]:
                click.echo(f"  {err['path']}: {err['message']}")
    sys.exit(0 if result["valid"] else 1)
