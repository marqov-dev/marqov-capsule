"""Accept an export only against a separately reviewed inventory and trusted ID."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
import tarfile
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

from marqov_capsule import CapsuleValidator, CapsuleVerifier
from marqov_capsule.archive import unpack_capsule

MAX_INVENTORY_BYTES = 2 * 1024 * 1024
MAX_FILES = 10000
ROLES = {
    "source",
    "result",
    "configuration",
    "report",
    "figure",
    "analysis",
    "reference",
    "environment",
    "other",
}
RESERVED = {"capsule.yaml", ".checksums"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate inventory key: {key}")
        result[key] = value
    return result


def load_inventory(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_INVENTORY_BYTES + 1)
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError("inventory exceeds 2 MiB")
    data = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant: {value}")
        ),
    )
    validate_inventory(data)
    return data, hashlib.sha256(raw).hexdigest()


def validate_inventory(data):
    if not isinstance(data, dict) or set(data) - {
        "version",
        "required_roles",
        "files",
        "allow_extra",
    }:
        raise ValueError("inventory must be an object with only documented fields")
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("inventory version must be integer 1")
    roles = data.get("required_roles")
    if (
        not isinstance(roles, list)
        or not roles
        or any(not isinstance(r, str) or r not in ROLES for r in roles)
        or len(set(roles)) != len(roles)
    ):
        raise ValueError("required_roles must be a nonempty unique list of known roles")
    if type(data.get("allow_extra", False)) is not bool:
        raise ValueError("allow_extra must be a boolean")
    files = data.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("files must contain 1 through 10000 entries")
    paths, declared = set(), set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) - {"path", "role", "sha256", "size_bytes"}:
            raise ValueError("file entries may contain only path, role, sha256 and size_bytes")
        path, role = entry.get("path"), entry.get("role")
        if not isinstance(path, str) or not path or len(path.encode("utf-8")) > 4096:
            raise ValueError("invalid inventory path")
        if (
            path == "."
            or path in RESERVED
            or "\\" in path
            or ":" in path
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or PurePosixPath(path).is_absolute()
            or ".." in path.split("/")
            or PurePosixPath(path).as_posix() != path
            or path != unicodedata.normalize("NFC", path)
        ):
            raise ValueError(f"path must be a canonical NFC relative POSIX payload path: {path}")
        if path in paths:
            raise ValueError(f"duplicate inventory path: {path}")
        if not isinstance(role, str) or role not in ROLES:
            raise ValueError("unknown file role")
        if "sha256" in entry and (
            not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        ):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        if "size_bytes" in entry and (
            type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0
        ):
            raise ValueError("size_bytes must be a nonnegative integer")
        paths.add(path)
        declared.add(role)
    if set(roles) - declared:
        raise ValueError("every required role must have at least one expected file")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_directory(directory, inventory, expected_id):
    validate_inventory(inventory)
    directory = Path(directory)
    integrity = CapsuleVerifier.verify_integrity(directory, expected_id=expected_id)
    result = dict(
        status="fail",
        capsule_version=importlib.metadata.version("marqov-capsule"),
        integrity=integrity,
        schema=None,
        completeness=None,
        scope="Integrity plus externally declared payload completeness; no execution or provenance authentication.",
    )
    if integrity["status"] != "pass" or not integrity["manifest_authenticated"]:
        return result
    schema = CapsuleValidator.validate_file(directory / "capsule.yaml")
    result["schema"] = schema
    if not schema["valid"]:
        return result
    actual = {
        unicodedata.normalize("NFC", p.relative_to(directory).as_posix()): p
        for p in directory.rglob("*")
        if p.is_file() and p.relative_to(directory).as_posix() not in RESERVED
    }
    expected = {entry["path"] for entry in inventory["files"]}
    missing, mismatched, sizes, satisfied = [], [], [], set()
    pinned = 0
    for entry in inventory["files"]:
        path = actual.get(entry["path"])
        if path is None:
            missing.append(entry["path"])
            continue
        valid = True
        if "sha256" in entry:
            pinned += 1
            if digest(path) != entry["sha256"]:
                mismatched.append(entry["path"])
                valid = False
        if "size_bytes" in entry and path.stat().st_size != entry["size_bytes"]:
            sizes.append(entry["path"])
            valid = False
        if valid:
            satisfied.add(entry["role"])
    extra = sorted(actual.keys() - expected)
    unsatisfied = sorted(set(inventory["required_roles"]) - satisfied)
    passed = not (
        missing
        or mismatched
        or sizes
        or unsatisfied
        or (extra and not inventory.get("allow_extra", False))
    )
    result["completeness"] = dict(
        status="pass" if passed else "fail",
        missing=sorted(missing),
        sha256_mismatches=sorted(mismatched),
        size_mismatches=sorted(sizes),
        unexpected=extra,
        unsatisfied_roles=unsatisfied,
        allow_extra=inventory.get("allow_extra", False),
        expected_files=len(expected),
        present_hash_pinned_files=pinned,
        presence_only_files=sum("sha256" not in entry for entry in inventory["files"]),
    )
    result["status"] = "pass" if passed else "fail"
    return result


def check_export(capsule, inventory, expected_id, scratch_dir):
    validate_inventory(inventory)
    capsule = Path(capsule)
    if capsule.is_symlink():
        raise ValueError("capsule input must not be a symlink")
    if capsule.is_dir():
        return check_directory(capsule, inventory, expected_id)
    # The supported archive reader enforces safe extraction and its 1 GiB limit.
    with tempfile.TemporaryDirectory(prefix="capsule-acceptance-", dir=scratch_dir) as temporary:
        restored = unpack_capsule(capsule, temporary)
        return check_directory(restored, inventory, expected_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capsule", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument(
        "--id", required=True, help="ID obtained from a trusted channel, separately from the export"
    )
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        required=True,
        help="Existing session scratch directory for temporary archive extraction",
    )
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.error("Use python -I with an installed distribution")
    distribution = importlib.metadata.distribution("marqov-capsule")
    if (
        json.loads(distribution.read_text("direct_url.json") or "{}")
        .get("dir_info", {})
        .get("editable")
    ):
        parser.error("Editable installations are not consumer acceptance")
    try:
        inventory, fingerprint = load_inventory(args.inventory)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(json.dumps({"status": "error", "stage": "inventory", "error": str(exc)}))
        return 2
    try:
        result = check_export(args.capsule, inventory, args.id, args.scratch_dir)
    except (OSError, ValueError, tarfile.TarError, EOFError) as exc:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "stage": "export",
                    "error": str(exc),
                    "inventory_sha256": fingerprint,
                }
            )
        )
        return 1
    result["inventory_sha256"] = fingerprint
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
