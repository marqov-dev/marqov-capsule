"""Bounded macOS Bell replay with network-denied execution stages.

Only consumes a frozen kit. Preparation/downloads are a separate online step.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location("bell_oracle", Path(__file__).with_name("oracle.py"))
_oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_oracle)
check_export = _oracle.check_export

MAX_RSS = 4 * 1024**3
MAX_DISK = 5 * 1024**3
MAX_EVIDENCE = 2 * 1024**3


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path):
    with path.open("rb") as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
        return value.hexdigest()


def disk_bytes(root):
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def preflight(kit, expected_freeze):
    """Require authored inputs before reading any installed simulator code."""
    required = [
        "reference.json",
        "experiment.json",
        "requirements.txt",
        "run_bell.py",
        "seal_bell.py",
        "freeze.json",
    ]
    for name in required:
        if not (kit / name).is_file():
            raise ValueError(f"MISSING_REQUIRED_INPUT:{name}")
    if digest(kit / "freeze.json") != expected_freeze:
        raise ValueError("UNTRUSTED_FREEZE_HASH")
    if any(p.is_symlink() for p in kit.rglob("*")):
        raise ValueError("SYMLINK_IN_KIT")
    freeze = json.loads((kit / "freeze.json").read_text())
    actual = {
        p.relative_to(kit).as_posix(): digest(p)
        for p in kit.rglob("*")
        if p.is_file() and p.relative_to(kit).as_posix() != "freeze.json"
    }
    if actual != freeze["files"]:
        raise ValueError("KIT_HASH_OR_CLOSED_SET_MISMATCH")
    if digest(Path(sys.executable).resolve()) != freeze["interpreter_sha256"]:
        raise ValueError("INTERPRETER_MISMATCH")
    experiment = json.loads((kit / "experiment.json").read_text())
    if experiment != {"qubits": 2, "shots": 1000, "seed": 42, "backend": "local"}:
        raise ValueError("EXPERIMENT_MISMATCH")
    _oracle.check_reference(json.loads((kit / "reference.json").read_text()))
    return freeze


def offline_probe():
    """Probe the same inherited sandbox policy used by every execution stage."""
    code = (
        "import socket,sys; s=socket.socket(); s.settimeout(1); "
        "\ntry: s.connect(('1.1.1.1',443))"
        "\nexcept PermissionError as e: print(e.errno); sys.exit(0)"
        "\nexcept OSError: sys.exit(2)"
        "\nsys.exit(3)"
    )
    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            "(version 1)(allow default)(deny network*)",
            sys.executable,
            "-I",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0 or result.stdout.strip() != "1":
        raise RuntimeError("NETWORK_DENIAL_NOT_PROVEN:" + result.stderr)
    return {"status": "pass", "errno": 1, "policy": "sandbox deny network* per stage"}


def stage(name, command, root, env, timeout):
    """Watch a new process group; preserve raw logs and cap receipts on all exits."""
    started = time.monotonic()
    peak = 0
    reason = None
    with (root / f"{name}.log").open("wb") as log:
        sandboxed = [
            "/usr/bin/sandbox-exec",
            "-p",
            "(version 1)(allow default)(deny network*)",
            *command,
        ]
        proc = subprocess.Popen(
            sandboxed,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=root,
            start_new_session=True,
        )
        try:
            while proc.poll() is None:
                rows = subprocess.check_output(["/bin/ps", "-axo", "pgid=,rss="], text=True)
                rss = sum(
                    int(row.split()[1]) * 1024
                    for row in rows.splitlines()
                    if row.split() and int(row.split()[0]) == proc.pid
                )
                peak = max(peak, rss)
                if time.monotonic() - started > timeout:
                    reason = "TIME_CAP"
                elif peak > MAX_RSS:
                    reason = "MEMORY_CAP"
                elif disk_bytes(root) > MAX_DISK:
                    reason = "DISK_CAP"
                elif disk_bytes(root / "exports") > MAX_EVIDENCE:
                    reason = "EVIDENCE_CAP"
                if reason:
                    raise RuntimeError(reason)
                time.sleep(0.2)
            # A short-lived child may exit between samples. Check final usage too.
            if time.monotonic() - started > timeout:
                reason = "TIME_CAP"
            elif disk_bytes(root) > MAX_DISK:
                reason = "DISK_CAP"
            elif disk_bytes(root / "exports") > MAX_EVIDENCE:
                reason = "EVIDENCE_CAP"
            if reason:
                raise RuntimeError(reason)
            if proc.returncode:
                reason = "NONZERO_EXIT"
                raise RuntimeError(f"{name}: exit {proc.returncode}")
        finally:
            # Also clean up any surviving descendants of a completed group leader.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            write(
                root / f"{name}.receipt.json",
                {
                    "command": command,
                    "network_policy": "sandbox deny network*",
                    "exit_code": proc.returncode,
                    "cap_failure": reason,
                    "wall_seconds": time.monotonic() - started,
                    "sampled_peak_group_rss_bytes": peak,
                    "disk_bytes": disk_bytes(root),
                    "rss_sampling_seconds": 0.2,
                },
            )


def run(kit, evidence, expected_freeze=None):
    kit, evidence = kit.resolve(), evidence.resolve()
    if evidence == kit or kit in evidence.parents or evidence in kit.parents:
        raise ValueError("KIT_AND_EVIDENCE_MUST_BE_DISJOINT")
    evidence.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"status": "fail", "stage": "preflight", "simulator_invocations": 0}

    def bounded(name, command, root, env, timeout):
        remaining = 900 - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeError("TOTAL_TIME_CAP")
        stage(name, command, root, env, min(timeout, remaining))

    try:
        freeze = preflight(kit, expected_freeze)
        report["freeze_sha256"] = digest(kit / "freeze.json")
        report["network"] = offline_probe()
        report["stage"] = "replay"
        (evidence / "exports").mkdir()
        home = evidence / "empty-home"
        home.mkdir()
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "TMPDIR": str(home),
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": "/dev/null",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "2",
            "VECLIB_MAXIMUM_THREADS": "2",
            "MPLCONFIGDIR": str(home / "mpl"),
        }
        reference = json.loads((kit / "reference.json").read_text())
        reports = []
        for label in ("a", "b"):
            if time.monotonic() - started > 900:
                raise RuntimeError("TOTAL_TIME_CAP")
            venv = evidence / f"venv-{label}"
            bounded(
                f"{label}-venv", [sys.executable, "-I", "-m", "venv", str(venv)], evidence, env, 60
            )
            python = str(venv / "bin/python")
            bounded(
                f"{label}-install",
                [
                    python,
                    "-I",
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    str(kit / "wheels"),
                    "--require-hashes",
                    "--report",
                    str(evidence / f"{label}-install.json"),
                    "-r",
                    str(kit / "requirements.txt"),
                ],
                evidence,
                env,
                300,
            )
            bounded(f"{label}-check", [python, "-I", "-m", "pip", "check"], evidence, env, 60)
            bounded(
                f"{label}-environment",
                [
                    python,
                    "-I",
                    "-c",
                    "import json,sys,site,importlib.metadata as m; "
                    "print(json.dumps({'prefix':sys.prefix,'path':sys.path,'user_site':site.ENABLE_USER_SITE,"
                    "'packages':{d.metadata['Name']: {'version':d.version,'location':str(d.locate_file(''))} "
                    "for d in m.distributions()}},sort_keys=True))",
                ],
                evidence,
                env,
                60,
            )
            export = evidence / "exports" / label
            report["simulator_invocations"] += 1
            bounded(
                f"{label}-simulate",
                [python, "-I", str(kit / "run_bell.py"), str(export)],
                evidence,
                env,
                60,
            )
            reports.append(check_export(export, reference))
            bounded(
                f"{label}-seal",
                [
                    python,
                    "-I",
                    str(kit / "seal_bell.py"),
                    str(export),
                    str(evidence / "exports" / f"sealed-{label}"),
                ],
                evidence,
                env,
                60,
            )
        if reports[0]["counts"] != reports[1]["counts"]:
            raise ValueError("SEEDED_REPLAY_MISMATCH")
        report.update(
            status="pass",
            stage="complete",
            oracles=reports,
            exact_counts_equal=True,
            package_count=len(freeze["packages"]),
        )
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    finally:
        report["wall_seconds"] = time.monotonic() - started
        write(evidence / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument(
        "--expected-freeze-sha256",
        required=True,
        help="Trusted freeze digest retained outside the kit",
    )
    args = parser.parse_args()
    result = run(args.kit, args.evidence, args.expected_freeze_sha256)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result["status"] == "pass" else 1)
