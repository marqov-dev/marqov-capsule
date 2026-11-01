"""Shared manifest loading for CLI commands that read a draft or sealed capsule.

``validate`` and ``verify`` route the manifest through APIs that already fail
closed. ``seal``, ``inspect`` and ``pack`` used to call the loader directly and
let a YAML syntax error, an empty file or a non-mapping document surface as a
Python traceback (#95). Every command now goes through this one helper so the
error contract is identical: exit 1, a one-line message on stderr, or a
``{"status": "error"}`` document when ``--json`` was asked for.

``seal --dry-run`` is a report, not a gate: it asks ``manifest_problem`` for the
same message and prints it beside its findings, at exit 0.
"""

import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import click
import yaml

from marqov_capsule._canonical import (
    describe_manifest_error,
    load_manifest_yaml,
    parse_capsule_id,
)


def fail(message: str, as_json: bool, **extra: Any) -> NoReturn:
    """Print an error in the requested format and exit 1."""
    if as_json:
        click.echo(json.dumps({"status": "error", "message": message, **extra}, indent=2))
    else:
        click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def check_expected_id(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Click callback for ``--id``: a string that is not a capsule ID is a
    usage error (exit 2), not a tamper verdict (#114)."""
    if value is None:
        return value
    try:
        parse_capsule_id(value)
    except ValueError:
        raise click.BadParameter(
            f"{value!r} is not a capsule ID (expected mqc:<version>:<64 lowercase hex>)"
        ) from None
    return value


class ManifestUnusable(Exception):
    """``capsule.yaml`` is not something a command can use; the message says why."""


def _read_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load ``capsule.yaml`` as a mapping, or raise ``ManifestUnusable``."""
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManifestUnusable(f"capsule.yaml not found in {manifest_path.parent}")
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ManifestUnusable(f"{manifest_path} is not UTF-8 text") from None
    except OSError as exc:
        raise ManifestUnusable(
            f"{manifest_path} could not be read: {exc.__class__.__name__}"
        ) from None
    try:
        manifest = load_manifest_yaml(text)
    except yaml.YAMLError as exc:
        raise ManifestUnusable(
            f"{manifest_path} could not be parsed: {describe_manifest_error(exc)}"
        ) from None
    if not isinstance(manifest, dict):
        raise ManifestUnusable(
            f"{manifest_path} must be a YAML mapping, got "
            f"{'an empty document' if manifest is None else type(manifest).__name__}"
        )
    return manifest


def load_manifest_or_exit(manifest_path: Path, as_json: bool) -> dict[str, Any]:
    """Load ``capsule.yaml`` as a mapping, or exit 1 with a clean message."""
    try:
        return _read_manifest(manifest_path)
    except ManifestUnusable as exc:
        fail(str(exc), as_json)


def manifest_problem(manifest_path: Path) -> str | None:
    """Why ``load_manifest_or_exit`` would refuse this manifest, if it would."""
    try:
        _read_manifest(manifest_path)
    except ManifestUnusable as exc:
        return str(exc)
    return None
