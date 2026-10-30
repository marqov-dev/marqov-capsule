"""Offline byte-preservation rehearsal, not a managed-result importer or validator.

Synthetic contract pinned to marqov-platform 0bf3db22. No execution, network,
receipt authentication or Python deserialization is performed.
"""

import argparse
import hashlib
import json
import shutil
from importlib.metadata import version
from pathlib import Path

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.archive import pack_capsule, unpack_capsule

TEAM = "11111111-1111-4111-8111-111111111111"
ARTIFACT = "22222222-2222-4222-8222-222222222222"
CONTRACT_COMMIT = "0bf3db22"


def encoded(value):
    # Deliberate whitespace and literal Unicode exercise exact-byte retention.
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def fixture(state, value=None, reason=None):
    # Deliberately not a pickle: treating this as a Python object would fail.
    raw = b"opaque python-value/v1 fixture\x00\xff\x80\x05; never deserialize"
    digest = hashlib.sha256(raw).hexdigest()
    artifact = dict(
        artifact_id=ARTIFACT,
        team_id=TEAM,
        schema="python-value/v1",
        sha256=digest,
        size_bytes=len(raw),
    )
    display = dict(protocol_version="marqov.task-display/v1", result_sha256=digest, state=state)
    display.update({"value": value} if state == "available" else {"reason": reason})
    envelope = dict(
        protocol_version="marqov.managed-result/v1",
        outputs=[dict(task_key="final_result", port="result", artifact=artifact, display=display)],
    )
    receipt = dict(
        protocol_version="marqov.execution-receipt/v1",
        team_id=TEAM,
        submission_id="33333333-3333-4333-8333-333333333333",
        task_attempt_id="44444444-4444-4444-8444-444444444444",
        operation_id="55555555-5555-4555-8555-555555555555",
        request_sha256="a" * 64,
        task_key="final_result",
        revision=1,
        state="succeeded",
        provider_outcome="observed",
        diagnostic="none",
        cost={"state": "unresolved", "evidence_ids": []},
        outputs=[{"port": "result", "artifact": artifact}],
    )
    files = {
        "managed-result.json": encoded(envelope),
        "execution-receipt.json": encoded(receipt),
        f"artifacts/{ARTIFACT}.bin": raw,
    }
    # not_provided is a legacy projection fallback, not an uploaded sidecar.
    if reason != "not_provided":
        files["display.json"] = encoded(display)
    return files


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def rehearsal(output):
    output.mkdir(parents=True, exist_ok=False)
    cases = [
        ("false", "available", False, None),
        ("zero", "available", 0, None),
        ("null", "available", None, None),
        ("unicode", "available", {"label": "résultat", "counts": {"00": 503}}, None),
        ("unsupported", "unavailable", None, "unsupported_value"),
        ("legacy", "unavailable", None, "not_provided"),
    ]
    results = []
    for name, state, value, reason in cases:
        directory = output / name
        directory.mkdir()
        source = directory / "record"
        source.mkdir()
        files = fixture(state, value, reason)
        for path, data in files.items():
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        builder = CapsuleBuilder().start_capsule(
            name=f"synthetic-managed-{name}",
            description="Synthetic offline preservation fixture; no hosted execution claimed.",
            requirements={"paradigm": ["gate-based"], "max_qubit_count": 2},
        )
        capsule_id = builder.seal(source)
        (directory / "trusted-id.txt").write_text(capsule_id + "\n")
        require(CapsuleValidator.validate_file(source / "capsule.yaml")["valid"], "schema")
        archive = pack_capsule(source, directory / "record.capsule")
        restored = unpack_capsule(archive, directory / "restored")
        require(
            CapsuleVerifier.verify_integrity(restored, expected_id=capsule_id)["status"] == "pass",
            "integrity",
        )
        require(
            all((restored / path).read_bytes() == data for path, data in files.items()),
            "byte preservation",
        )
        refused = []
        for failure in ("missing-artifact", "corrupt-artifact", "changed-team", "changed-preview"):
            damaged = directory / failure
            shutil.copytree(restored, damaged)
            artifact_path = damaged / f"artifacts/{ARTIFACT}.bin"
            if failure == "missing-artifact":
                artifact_path.unlink()
            elif failure == "corrupt-artifact":
                artifact_path.write_bytes(b"corrupt")
            else:
                envelope = json.loads((damaged / "managed-result.json").read_bytes())
                entry = envelope["outputs"][0]
                if failure == "changed-team":
                    entry["artifact"]["team_id"] = "66666666-6666-4666-8666-666666666666"
                else:
                    entry["display"] = dict(
                        protocol_version="marqov.task-display/v1",
                        result_sha256=entry["artifact"]["sha256"],
                        state="available",
                        value="invented",
                    )
                (damaged / "managed-result.json").write_bytes(encoded(envelope))
            require(
                CapsuleVerifier.verify_integrity(damaged, expected_id=capsule_id)["status"]
                == "fail",
                failure,
            )
            refused.append(failure)
        results.append(
            dict(
                case=name,
                capsule_id=capsule_id,
                exact_bytes=True,
                refused=refused,
                sidecar_sha256=(
                    hashlib.sha256(files["display.json"]).hexdigest()
                    if "display.json" in files
                    else None
                ),
            )
        )
    report = dict(
        contract_commit=CONTRACT_COMMIT,
        capsule_version=version("marqov-capsule"),
        synthetic=True,
        cases=results,
        scope="Published Capsule byte preservation and post-seal integrity only.",
        limitations=[
            "No hosted storage, execution, signed-observation or receipt authentication tested.",
            "Capsule does not validate managed-result semantics or artifact completeness before sealing.",
            "A platform exporter must resolve and validate tenant-scoped authoritative artifacts before sealing; previews cannot fill missing artifacts.",
            "Preserved display bytes do not prove equivalence to opaque Python values.",
        ],
    )
    (output / "report.json").write_bytes(encoded(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New evidence directory")
    args = parser.parse_args()
    result = rehearsal(args.output)
    print(f"PASS: {len(result['cases'])} round-trips; 24 altered/incomplete records rejected")
    print(args.output / "report.json")
