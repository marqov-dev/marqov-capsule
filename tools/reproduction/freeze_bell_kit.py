"""Finalize a prepared offline kit before any simulator execution; no downloads."""

import argparse
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "bell_runner", Path(__file__).with_name("run_bell_reproduction.py")
)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def freeze(kit, source_ref):
    kit = kit.resolve()
    if (kit / "freeze.json").exists():
        raise ValueError("REFUSE_TO_OVERWRITE_FREEZE")
    environment = json.loads((kit / "environment.json").read_text())
    packages = environment["packages"]
    if packages.get("marqov-capsule") != "0.2.3" or packages.get("marqov") != "0.5.1":
        raise ValueError("REQUIRES_CAPSULE_0_2_3_AND_SDK_0_5_1")
    for name in ("oracle.py", "run_bell_reproduction.py"):
        shutil.copyfile(Path(__file__).with_name(name), kit / name)
    runner.write(kit / "reference.json", runner._oracle.REFERENCE)
    runner.write(
        kit / "experiment.json", {"qubits": 2, "shots": 1000, "seed": 42, "backend": "local"}
    )
    # The prep tool's checksum list predates these additions. freeze.json supersedes it.
    (kit / "SHA256SUMS").unlink(missing_ok=True)
    if any(p.is_symlink() for p in kit.rglob("*")):
        raise ValueError("SYMLINK_IN_KIT")
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_ref": source_ref,
        "interpreter_sha256": runner.digest(Path(sys.executable).resolve()),
        "packages": packages,
        "files": {
            p.relative_to(kit).as_posix(): runner.digest(p)
            for p in sorted(kit.rglob("*"))
            if p.is_file()
        },
    }
    runner.write(kit / "freeze.json", payload)
    return runner.digest(kit / "freeze.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument(
        "--source-ref", required=True, help="Reviewed checkout commit or source receipt"
    )
    args = parser.parse_args()
    print(freeze(args.kit, args.source_ref))
