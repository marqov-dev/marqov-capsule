"""Exercise an installed wheel: python -I tools/smoke_distribution.py.

Requires only the base package. All experiment files live in a temporary
directory, and each CLI command runs in isolated Python outside the checkout.
"""
import importlib.metadata
import importlib.resources
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    check(sys.flags.isolated, "Run with python -I to exclude PYTHONPATH and user site packages")
    distribution = importlib.metadata.distribution("marqov-capsule")
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    check(not direct_url.get("dir_info", {}).get("editable"),
          "Acceptance requires an installed distribution, not an editable checkout")

    import marqov_capsule
    package_file = Path(marqov_capsule.__file__).resolve()
    installed_file = Path(distribution.locate_file("marqov_capsule/__init__.py")).resolve()
    check(package_file == installed_file, "Imported package does not match the installed distribution")
    schema = importlib.resources.files("marqov_capsule.schemas").joinpath("capsule-schema.json").read_bytes()
    expected_schema = Path(__file__).resolve().parents[1] / "spec/v1/capsule-schema.json"
    check(schema == expected_schema.read_bytes(), "Installed schema differs from the release specification")

    with tempfile.TemporaryDirectory(prefix="capsule-acceptance-") as directory:
        root = Path(directory)

        def cli(*args, expected=0):
            result = subprocess.run(
                [sys.executable, "-I", "-m", "marqov_capsule", *args],
                cwd=root, capture_output=True, text=True, timeout=30,
            )
            check(result.returncode == expected,
                  f"CLI {args!r}: expected exit {expected}, got {result.returncode}\n"
                  f"{result.stdout}\n{result.stderr}")
            return result.stdout

        cli("init", "experiment", "--name", "release-acceptance", "--paradigm", "gate-based", "--qubits", "2")
        payload = root / "experiment" / "results.json"
        payload.write_text('{"counts":{"00":503,"11":497}}\n', encoding="utf-8")
        sealed = cli("seal", "experiment")
        match = re.search(r"mqc:1:[0-9a-f]{64}", sealed)
        check(match is not None, "Seal did not emit a versioned capsule ID")
        trusted_id = match.group()
        cli("validate", "experiment")
        cli("verify", "experiment", "--id", trusted_id)
        cli("pack", "experiment", "-o", "first.capsule")
        cli("pack", "experiment", "-o", "second.capsule")
        check((root / "first.capsule").read_bytes() == (root / "second.capsule").read_bytes(),
              "Repeated packing changed archive bytes")
        cli("verify", "first.capsule", "--id", trusted_id)
        cli("unpack", "first.capsule", "-o", "restored")
        manifests = list((root / "restored").rglob("capsule.yaml"))
        check(len(manifests) == 1, "Archive did not restore exactly one manifest")
        restored = manifests[0].parent
        cli("verify", str(restored), "--id", trusted_id)
        payload.write_text('{"counts":{"00":1000}}\n', encoding="utf-8")
        cli("verify", "experiment", "--id", trusted_id, expected=1)
        manifest = manifests[0]
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(
            "release-acceptance", "altered-experiment"), encoding="utf-8")
        cli("verify", str(restored), "--id", trusted_id, expected=1)

    print(json.dumps({"status": "pass", "version": distribution.version,
                      "package": str(package_file), "capsule_id": trusted_id,
                      "checks": ["bundled-schema", "CLI-roundtrip", "deterministic-archive",
                                 "trusted-ID", "payload-tamper", "manifest-tamper"]}, indent=2))


if __name__ == "__main__":
    main()
