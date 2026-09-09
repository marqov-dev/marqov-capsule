"""Export a real Marqov SDK local-simulator run; no credentials required."""
import argparse
import asyncio
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path

from marqov.circuits import Circuit
from marqov.executors.local import LocalExecutor, LocalExecutorConfig


async def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    circuit = Circuit().h(0).cnot(0, 1)
    result = await LocalExecutor(LocalExecutorConfig(seed=42)).execute(circuit, shots=1000)
    exports = {
        "results.json": {"counts": result.counts, "shots": result.shots,
                         "backend": result.backend, "seed": 42},
        "circuit.json": circuit.to_dict(),
        "environment.json": {
            "python": platform.python_version(),
            "packages": {name: importlib.metadata.version(name) for name in
                         ("marqov", "marqov-quantumflow", "numpy")},
        },
    }
    for name, data in exports.items():
        (output / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(__file__, output / "run_bell.py")
    print(f"Local simulator counts: {result.counts}")
    print(f"Exported circuit, result, source, and environment to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New export directory")
    asyncio.run(run(parser.parse_args().output))
