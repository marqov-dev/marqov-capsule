"""Bounded preservation evaluation; synthetic records, never quantum execution."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import shutil
import statistics
import sys
import time

from marqov_capsule import CapsuleBuilder, CapsuleValidator, CapsuleVerifier
from marqov_capsule.archive import pack_capsule, unpack_capsule


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def corpus():
    """Inspectable circuit descriptions and invented results; no backend used."""
    return {
        "bell": (2, {"source.qasm": b"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
                      "counts.json": encode({"00": 500, "11": 500})}),
        "ghz": (3, {"source.qasm": b"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[3];\ncreg c[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\nmeasure q -> c;\n",
                     "counts.json": encode({"000": 500, "111": 500})}),
        "parameter-sweep": (1, {
            "source.qasm": b"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\ncreg c[1];\nry(0.5) q[0];\nmeasure q -> c;\n",
            "config.json": encode({"angles": [0.0, 0.5, 1.0], "scope": "synthetic fixture; source shows one setting"}),
            **{f"results/setting-{i}.json": encode({"angle": angle, "counts": {"0": 800-i*100, "1": 200+i*100}})
               for i, angle in enumerate([0.0, 0.5, 1.0])}}),
        "classical": (0, {"source.py": b"values = [1, 2, 3]\nprint(sum(values))\n",
                          "result.json": encode({"sum": 6}),
                          "notes.txt": "Synthetic classical record: résultat.\n".encode()}),
        "multi-result": (2, {"source.qasm": b"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;\n",
                             "results/first.json": encode({"00": 510, "11": 490}),
                             "results/second.json": encode({"00": 490, "11": 510}),
                             "report.md": b"# Synthetic preservation fixture\nNo hosted or hardware execution claimed.\n"}),
    }


def inventory(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def timed(operation):
    start = time.perf_counter_ns()
    value = operation()
    return value, (time.perf_counter_ns() - start) / 1e9


def exercise(directory, files, qubits, tamper):
    record = directory / "record"
    record.mkdir(parents=True)
    for name, data in files.items():
        path = record / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    # Do not pretend fixture counts are executed task records.
    builder = CapsuleBuilder().start_capsule(
        name=directory.name, description="Synthetic preservation evaluation; no execution claimed.",
        requirements={"paradigm": ["gate-based"] if qubits else ["classical"], "max_qubit_count": qubits})
    ident, seal_s = timed(lambda: builder.seal(record))
    require(CapsuleValidator.validate_file(record / "capsule.yaml")["valid"], "schema invalid")
    verification, verify_s = timed(lambda: CapsuleVerifier.verify_integrity(record, expected_id=ident))
    require(verification["status"] == "pass" and verification["manifest_authenticated"], "verification failed")
    archive, pack_s = timed(lambda: pack_capsule(record, directory / "record.capsule"))
    second = pack_capsule(record, directory / "repeat.capsule")
    require(archive.read_bytes() == second.read_bytes(), "packing not deterministic")
    restored, unpack_s = timed(lambda: unpack_capsule(archive, directory / "restored"))
    require(inventory(record) == inventory(restored), "restored file set or bytes differ")
    check = CapsuleVerifier.verify_integrity(restored, expected_id=ident)
    require(check["status"] == "pass" and check["manifest_authenticated"], "restored integrity failed")
    refusals = []
    if tamper:
        first = sorted(files)[0]
        for kind in ("changed-payload", "missing-payload", "extra-payload", "changed-manifest", "changed-checksums", "wrong-trusted-id"):
            damaged = directory / kind
            shutil.copytree(restored, damaged)
            expected = ident
            if kind == "changed-payload":
                with (damaged / first).open("ab") as out:
                    out.write(b"\n")
            elif kind == "missing-payload":
                (damaged / first).unlink()
            elif kind == "extra-payload":
                (damaged / "unexpected.txt").write_bytes(b"extra")
            elif kind == "changed-manifest":
                path = damaged / "capsule.yaml"
                text = path.read_text()
                require(f"name: {directory.name}" in text, "manifest mutation target absent")
                path.write_text(text.replace(f"name: {directory.name}", "name: changed-record", 1))
            elif kind == "changed-checksums":
                with (damaged / ".checksums").open("ab") as out:
                    out.write(b"\n")
            else:
                expected = "mqc:1:" + ("0" if ident[-64:] != "0"*64 else "1")*64
            require(CapsuleVerifier.verify_integrity(damaged, expected_id=expected)["status"] == "fail", f"accepted {kind}")
            refusals.append(kind)
    payload_bytes = sum(map(len, files.values()))
    return dict(capsule_id=ident, payload_files=len(files), payload_bytes=payload_bytes,
                sealed_bytes=sum(p.stat().st_size for p in record.rglob("*") if p.is_file()),
                archive_bytes=archive.stat().st_size, exact_restoration=True, deterministic_archive=True,
                refused=refusals, inventory_sha256=hashlib.sha256(encode(inventory(record))).hexdigest(),
                seconds=dict(seal=seal_s, verify=verify_s, pack=pack_s, unpack=unpack_s))


def run(output, repeats=3):
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= 5:
        raise ValueError("repeats must be an integer from 1 through 5")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for name, (qubits, files) in corpus().items():
        result = exercise(output / name, files, qubits, tamper=True)
        cases.append(dict(case=name, **result))
    measurements = []
    # Fixed total bytes separates file-count cost from payload-volume cost.
    # Deterministic high-entropy bytes avoid measuring only gzip's zero compression.
    for file_count in (1, 16, 128):
        for total_bytes in (0, 65536, 1048576):
            data = random.Random(42).randbytes(total_bytes)
            width, remainder = divmod(total_bytes, file_count)
            files = {}
            offset = 0
            for index in range(file_count):
                length = width + (index < remainder)
                files[f"payload/file-{index:03d}.bin"] = data[offset:offset+length]
                offset += length
            trials = [exercise(output / f"scale-{file_count}-{total_bytes}-{trial}", files, 0, False)
                      for trial in range(repeats)]
            measurements.append(dict(payload_files=file_count, payload_bytes=total_bytes, trials=trials,
                median_seconds={op: statistics.median(t["seconds"][op] for t in trials)
                                for op in ("seal", "verify", "pack", "unpack")}))
    report = dict(status="pass", report_version=1, capsule_version=importlib.metadata.version("marqov-capsule"),
        environment=dict(python=platform.python_version(), os=platform.system(), architecture=platform.machine(),
            dependencies={name: importlib.metadata.version(name) for name in
                          ("marqov-capsule", "PyYAML", "jsonschema", "jcs")}),
        harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), repeats=repeats,
        scope="Synthetic byte preservation, integrity refusal and local timing; no execution or scientific replication.",
        timing_method="perf_counter_ns; sequential fresh records, warm process/filesystem, no cache flushing; setup/schema/repeated-pack/restored-verify excluded from individual timings",
        limitations=["Fixture counts are invented; circuits and source are not executed or semantically validated.",
                     "Preserved inventories do not prove exporter completeness, authorship or backend provenance.",
                     "Timings are descriptive for this environment, not service-level guarantees or cold-cache benchmarks.",
                     "No statistical equivalence, interoperability adapter, concurrency or crash-recovery evaluation."],
        cases=cases, scaling=measurements)
    (output / "report.json").write_bytes(encode(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New evidence directory; existing outputs refused")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.error("Use python -I to exclude user-site and working-source imports")
    dist = importlib.metadata.distribution("marqov-capsule")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    if direct.get("dir_info", {}).get("editable"):
        parser.error("Use an installed wheel, not an editable checkout")
    run(args.output, args.repeats)
    print("PASS: 5 synthetic records, 30 integrity refusals, 9 bounded scaling conditions")
    print(args.output / "report.json")


if __name__ == "__main__":
    main()
