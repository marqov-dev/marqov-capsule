"""marqov-capsule CLI entry point."""
import click
from marqov_capsule.cli.commands.init import init
from marqov_capsule.cli.commands.seal import seal
from marqov_capsule.cli.commands.verify import verify
from marqov_capsule.cli.commands.inspect import inspect_cmd
from marqov_capsule.cli.commands.open import open_cmd
from marqov_capsule.cli.commands.validate import validate
from marqov_capsule.cli.commands.pack import pack, unpack


@click.group()
@click.version_option()
def cli():
    """marqov-capsule — build, seal, verify, and inspect quantum experiment capsules."""


cli.add_command(init)
cli.add_command(seal)
cli.add_command(verify)
cli.add_command(inspect_cmd, name="inspect")
cli.add_command(open_cmd, name="open")
cli.add_command(validate)
cli.add_command(pack)
cli.add_command(unpack)
