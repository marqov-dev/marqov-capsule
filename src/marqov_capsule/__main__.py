"""Allow running marqov-capsule as a module: python -m marqov_capsule"""

from marqov_capsule.cli.main import cli

if __name__ == "__main__":
    cli()
