"""Check built source/wheel contents before upload; uses only the standard library."""
import argparse
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def check_sdist(path):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate source archive members")
    roots = set()
    relative = set()
    allowed = {"src", "spec", "examples", "LICENSE-CODE", "LICENSE-SPEC",
               "README.md", "pyproject.toml", "PKG-INFO", ".gitignore"}
    for member in members:
        parts = PurePosixPath(member.name)
        if parts.is_absolute() or ".." in parts.parts or len(parts.parts) < 2:
            raise ValueError(f"Unexpected source archive path: {member.name}")
        roots.add(parts.parts[0])
        if parts.parts[1] not in allowed:
            raise ValueError(f"Unexpected source archive root: {member.name}")
        if any(part in {".git", ".claude", ".codex", ".venv", "__pycache__", "node_modules"}
               for part in parts.parts[1:]):
            raise ValueError(f"Local workspace content in source archive: {member.name}")
        if not member.isfile() and not member.isdir():
            raise ValueError(f"Nonregular source archive member: {member.name}")
        if member.isfile():
            relative.add(PurePosixPath(*parts.parts[1:]).as_posix())
    if len(roots) != 1:
        raise ValueError("Expected one source archive root")
    required = {"pyproject.toml", "README.md", "LICENSE-CODE", "LICENSE-SPEC",
                "src/marqov_capsule/__init__.py", "spec/v1/capsule-schema.json",
                "examples/run_bell.py", "examples/seal_bell.py"}
    if required - relative:
        raise ValueError(f"Source archive missing required files: {sorted(required - relative)}")
    return len(names)


def check_wheel(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("Duplicate wheel members")
    metadata_roots = set()
    for name in names:
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError(f"Unexpected wheel path: {name}")
        root = parts.parts[0]
        if root != "marqov_capsule":
            if not (root.startswith("marqov_capsule-") and root.endswith(".dist-info")):
                raise ValueError(f"Unexpected wheel root: {name}")
            metadata_roots.add(root)
    if len(metadata_roots) != 1:
        raise ValueError("Expected one wheel metadata directory")
    metadata = metadata_roots.pop()
    required = {"marqov_capsule/__init__.py", "marqov_capsule/schemas/capsule-schema.json",
                f"{metadata}/licenses/LICENSE-CODE", f"{metadata}/licenses/LICENSE-SPEC"}
    if required - set(names):
        raise ValueError(f"Wheel missing required files: {sorted(required - set(names))}")
    if sum(name.endswith("capsule-schema.json") for name in names) != 1:
        raise ValueError("Expected exactly one bundled schema")
    return len(names)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    wheels = list(args.directory.glob("*.whl"))
    sources = list(args.directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error("Expected exactly one wheel and one source distribution")
    print(f"PASS: {check_sdist(sources[0])} source members, {check_wheel(wheels[0])} wheel members")
