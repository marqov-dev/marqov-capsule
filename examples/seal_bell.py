"""Seal an SDK Bell export, round-trip an archive, and detect tampering."""
import argparse
import json
import shutil
from pathlib import Path

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.archive import pack_capsule, unpack_capsule


def demo(export: Path, output: Path) -> dict:
    # Both scripts require a new destination: a rerun cannot overwrite evidence.
    output.mkdir(parents=True, exist_ok=False)
    capsule = output / "bell-state"
    capsule.mkdir()
    for name in ("results.json", "circuit.json", "environment.json", "run_bell.py"):
        shutil.copyfile(export / name, capsule / name)

    builder = CapsuleBuilder().start_capsule(
        name="quantum-week-bell-state",
        description="Marqov SDK local simulator run; no QPU execution claimed.",
        requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
        environment_ref="environment.json",
    )
    capsule_id = builder.seal(capsule, sealed_by="conference-demo")
    # The trust anchor is kept outside the capsule and its archive.
    (output / "trusted-id.txt").write_text(capsule_id + "\n", encoding="utf-8")
    validation = CapsuleValidator.validate_file(capsule / "capsule.yaml")
    if not validation["valid"]:
        raise RuntimeError(f"Invalid capsule: {validation}")
    original = CapsuleVerifier.verify_integrity(capsule, expected_id=capsule_id)
    archive = pack_capsule(capsule, output / "bell-state.capsule")
    second_archive = pack_capsule(capsule, output / "bell-state-repeat.capsule")
    deterministic = archive.read_bytes() == second_archive.read_bytes()
    restored = unpack_capsule(archive, output / "restored")
    roundtrip = CapsuleVerifier.verify_integrity(restored, expected_id=capsule_id)

    tampered = output / "tampered"
    shutil.copytree(restored, tampered)
    (tampered / "results.json").write_text('{"counts":{"00":1000}}\n', encoding="utf-8")
    changed_payload = CapsuleVerifier.verify_integrity(tampered, expected_id=capsule_id)
    manifest_copy = output / "changed-manifest"
    shutil.copytree(restored, manifest_copy)
    manifest = manifest_copy / "capsule.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace(
        "quantum-week-bell-state", "different-experiment"), encoding="utf-8")
    changed_manifest = CapsuleVerifier.verify_integrity(manifest_copy, expected_id=capsule_id)

    report = {
        "capsule_id": capsule_id, "schema_valid": validation["valid"],
        "deterministic_archive": deterministic,
        "original": original, "roundtrip": roundtrip,
        "changed_payload": changed_payload, "changed_manifest": changed_manifest,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not (deterministic and original["status"] == roundtrip["status"] == "pass"
            and roundtrip["manifest_authenticated"]
            and changed_payload["status"] == changed_manifest["status"] == "fail"):
        raise RuntimeError(f"Demo failed; inspect {output / 'report.json'}")
    print(f"Capsule ID: {capsule_id}")
    print("PASS: sealed, schema-valid, byte-identical archives, verified round-trip")
    print("PASS: changed payload and changed manifest both rejected")
    print(f"Archive: {archive}\nTrusted ID: {output / 'trusted-id.txt'}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("output", type=Path, help="New demonstration directory")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"{args.output} already exists; use a new directory")
    demo(args.export, args.output)
