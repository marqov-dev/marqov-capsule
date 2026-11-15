"""Independent computational-basis Bell oracle; standard library only."""

import json
from pathlib import Path

CIRCUIT = {
    "gates": [
        {"gate": "H", "qubits": [0], "params": []},
        {"gate": "CNot", "qubits": [0, 1], "params": []},
    ]
}
REFERENCE = {
    "probabilities": {"00": 0.5, "01": 0.0, "10": 0.0, "11": 0.5},
    "shots": 1000,
    "seed": 42,
    "count_00_min": 420,
    "count_00_max": 580,
}


def check_reference(reference):
    """JSON numeric types are part of the fixed verifier-owned contract."""
    if json.dumps(reference, sort_keys=True, allow_nan=False) != json.dumps(
        REFERENCE, sort_keys=True
    ):
        raise ValueError("REFERENCE_CONTRACT_MISMATCH")


def check(result, circuit, reference):
    """Check fixed theory, exact circuit and bounded integer counts; raise on failure."""
    check_reference(reference)
    if json.dumps(circuit, sort_keys=True, allow_nan=False) != json.dumps(CIRCUIT, sort_keys=True):
        raise ValueError("CIRCUIT_MISMATCH")
    if (
        type(result.get("shots")) is not int
        or result["shots"] != 1000
        or type(result.get("seed")) is not int
        or result["seed"] != 42
        or result.get("backend") != "local"
    ):
        raise ValueError("RUN_CONTRACT_MISMATCH")
    counts = result.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise ValueError("INVALID_COUNTS")
    if any(
        k not in REFERENCE["probabilities"] or type(v) is not int or v < 0
        for k, v in counts.items()
    ):
        raise ValueError("INVALID_COUNTS")
    if sum(counts.values()) != 1000:
        raise ValueError("SHOT_TOTAL_MISMATCH")
    if counts.get("01", 0) or counts.get("10", 0):
        raise ValueError("FORBIDDEN_OUTCOME")
    if not 420 <= counts.get("00", 0) <= 580:
        raise ValueError("ANALYTIC_MISMATCH")
    return {
        "status": "pass",
        "counts": {k: counts.get(k, 0) for k in sorted(REFERENCE["probabilities"])},
        "count_00_interval": [420, 580],
        "scope": "computational-basis distribution only",
    }


def check_export(export, reference):
    export = Path(export)
    return check(
        json.loads((export / "results.json").read_text()),
        json.loads((export / "circuit.json").read_text()),
        reference,
    )
