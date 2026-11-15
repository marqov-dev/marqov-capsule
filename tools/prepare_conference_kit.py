"""Prepare a host-specific offline SDK/capsule demo kit while online.

Run with Python 3.12+ and pip installed. Supply a built capsule wheel and a new
output directory. Installation and demonstration on the target remain offline.
"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path


def prepare(wheel: Path, output: Path):
    if sys.version_info < (3, 12):
        raise RuntimeError("The SDK demonstration requires Python 3.12+")
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != ".whl":
        raise ValueError("Supply a built capsule wheel")
    output.mkdir(parents=True, exist_ok=False)
    wheels = output / "wheels"
    wheels.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--dest",
            str(wheels),
            str(wheel),
            "marqov==0.5.1",
        ],
        check=True,
    )

    requirements = []
    packages = {}
    for artifact in sorted(wheels.glob("*.whl")):
        with zipfile.ZipFile(artifact) as archive:
            metadata_files = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                raise ValueError(f"Expected one package metadata file in {artifact}")
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        name, version = metadata["Name"], metadata["Version"]
        if name in packages:
            raise ValueError(f"Multiple wheels for {name}")
        packages[name] = version
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        requirements.append(f"{name}=={version} --hash=sha256:{digest}")
    (output / "requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")

    root = Path(__file__).resolve().parents[1]
    for name in ("run_bell.py", "seal_bell.py"):
        shutil.copyfile(root / "examples" / name, output / name)
    # Kit file names stay LICENSE-CODE / LICENSE-SPEC; the spec notice lives in spec/v1/.
    shutil.copyfile(root / "LICENSE-CODE", output / "LICENSE-CODE")
    shutil.copyfile(root / "spec" / "v1" / "LICENSE", output / "LICENSE-SPEC")
    metadata = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "packages": packages,
    }
    (output / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    instructions = """# Offline conference demonstration

Prepared for the Python minor version, OS and architecture in environment.json.
Use a compatible machine with Python already installed. Rebuild the kit on a
different target platform; this wheel collection is not universal.

From this directory, with network access disabled:

```sh
python3.12 -m venv demo-env
demo-env/bin/python -m pip install --no-index --find-links wheels --require-hashes -r requirements.txt
demo-env/bin/python run_bell.py bell-export
demo-env/bin/python seal_bell.py bell-export bell-demo
demo-env/bin/marqov-capsule inspect bell-demo/bell-state
demo-env/bin/marqov-capsule verify bell-demo/bell-state.capsule --id "$(cat bell-demo/trusted-id.txt)"
demo-env/bin/marqov-capsule verify bell-demo/tampered --id "$(cat bell-demo/trusted-id.txt)"
```

The last command should exit 1; earlier commands must succeed. Use fresh export
and demo directories for another run. Windows uses demo-env/Scripts executables.
The kit requires no provider credentials and executes only the local simulator.
Counts and circuit come from that SDK run; seal_bell.py checks deterministic
packing, extraction, trusted-ID verification and payload/manifest tampering.

Narration: “This is a record of a local SDK experiment. The archive preserves
its circuit, result and source. A recipient can check that the contents match
the ID I supplied. Changing the result or description fails that check.”

Share the ID through a trusted channel separate from the archive. A colocated
ID or SHA256SUMS file is not proof of sender identity. The demo does not claim
QPU provenance, signatures, automatic environment recreation or statistical
replication. Capsule is an unpublished local build. Third-party wheels retain
their own licenses.
"""
    python_command = f"python{sys.version_info.major}.{sys.version_info.minor}"
    (output / "README.md").write_text(
        instructions.replace("python3.12", python_command), encoding="utf-8"
    )
    files = sorted(path for path in output.rglob("*") if path.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(output).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )
    print(f"Prepared {len(packages)} pinned wheels in {output.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("output", type=Path, help="New kit directory")
    args = parser.parse_args()
    prepare(args.wheel, args.output)
