import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from marqov_capsule import CapsuleBuilder


def test_builder_initialization():
    builder = CapsuleBuilder("test-capsule", description="A test")
    builder.start_capsule(parameters={"x": 1})
    data = builder.get_capsule_data()
    assert data["name"] == "test-capsule"
    assert data["description"] == "A test"
    assert data["lifecycle_state"] == "draft"
    assert data["capsule_format_version"] is not None
    # marqov_version should NOT be present
    assert "marqov_version" not in data


def test_digests_are_deterministic():
    """Same inputs produce same digests (D4)."""
    builder1 = CapsuleBuilder("test", description="same")
    builder1.start_capsule(parameters={"x": 1})
    builder1.add_task_execution(task_id="t1", backend="local", outputs={"y": 2})
    sealed1 = builder1.seal_capsule(exit_code=0)

    builder2 = CapsuleBuilder("test", description="same")
    builder2.start_capsule(parameters={"x": 1})
    builder2.add_task_execution(task_id="t1", backend="local", outputs={"y": 2})
    sealed2 = builder2.seal_capsule(exit_code=0)

    # Provenance digest includes wall-clock timestamps so it varies;
    # all content-derived digests must match.
    for key in ("workflow", "environment", "backends", "data", "results"):
        assert sealed1["digests"][key] == sealed2["digests"][key], f"digest mismatch: {key}"


def test_full_lifecycle():
    builder = CapsuleBuilder("lifecycle-test", description="Full test")
    builder.start_capsule(parameters={"distance": 3})
    builder.add_task_execution(
        task_id="main",
        backend="local",
        outputs={"wep": {0: 1, 2: 4}},
    )
    builder.add_result_digest(
        data={"wep": {0: 1, 2: 4}},
        digest_name="weight_enumerator",
    )
    sealed = builder.seal_capsule(exit_code=0)

    assert sealed["lifecycle_state"] == "sealed"
    assert "sealed_at" in sealed
    assert sealed["execution"]["exit_code"] == 0
    assert "results" in sealed["digests"]

    # Save and reload
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "capsule.yaml"
        builder.save_capsule(str(path))
        assert path.exists()

        with open(path) as f:
            loaded = yaml.safe_load(f)
        assert loaded["name"] == "lifecycle-test"
        assert loaded["lifecycle_state"] == "sealed"


def test_save_generates_checksums():
    """save_capsule() writes .checksums manifest (D2)."""
    builder = CapsuleBuilder("checksum-test")
    builder.start_capsule(parameters={})
    builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
    builder.seal_capsule(exit_code=0)

    with tempfile.TemporaryDirectory() as tmpdir:
        capsule_dir = Path(tmpdir) / "test.capsule"
        capsule_dir.mkdir()
        path = capsule_dir / "capsule.yaml"
        builder.save_capsule(str(path))

        checksums_path = capsule_dir / ".checksums"
        assert checksums_path.exists()

        lines = checksums_path.read_text().strip().split("\n")
        # At least capsule.yaml should be listed
        filenames = [line.split("  ")[1] for line in lines]
        assert "capsule.yaml" in filenames

        # Each line: "sha256:<64hex>  <filename>"
        for line in lines:
            digest, name = line.split("  ")
            assert digest.startswith("sha256:")
            assert len(digest) == 71  # "sha256:" + 64 hex chars


def test_start_capsule():
    """Test starting a capsule sets up the correct structure."""
    builder = CapsuleBuilder(name="test-workflow")
    builder.start_capsule(
        parameters={"param1": "value1"},
        max_budget_usd=100.0,
    )

    assert builder.capsule_data["name"] == "test-workflow"
    assert builder.capsule_data["lifecycle_state"] == "draft"
    assert builder.capsule_data["cost"]["max_budget_usd"] == 100.0
    assert builder.capsule_data["provenance"]["custom_metadata"] == {"param1": "value1"}


def test_add_task_execution():
    """Test adding classical and quantum task executions."""
    builder = CapsuleBuilder(name="test-workflow")
    builder.start_capsule()

    # Add classical task
    builder.add_task_execution(
        task_id="prep_data",
        backend="local",
        wall_time_seconds=5.2,
        cost_usd=0.0,
    )

    assert builder.capsule_data["execution"]["num_tasks"] == 1
    assert builder.total_cost_usd == 0.0

    # Add quantum task
    builder.add_task_execution(
        task_id="vqe_step_1",
        backend="braket-ionq",
        wall_time_seconds=45.3,
        queue_time_seconds=120.0,
        cost_usd=3.55,
        shots=1024,
    )

    assert builder.capsule_data["execution"]["num_tasks"] == 2
    assert builder.total_cost_usd == 3.55
    assert builder.total_shots == 1024
    assert builder.capsule_data["execution"]["total_queue_time_seconds"] == 120.0


def test_add_qpu_calibration():
    """Test adding QPU calibration data."""
    builder = CapsuleBuilder(name="test-workflow")
    builder.start_capsule()

    builder.add_qpu_calibration(
        device_arn="arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1",
        calibration_timestamp=datetime(2026, 1, 6, 10, 0, 0),
        num_qubits=25,
        connectivity="all-to-all",
        gate_fidelities={
            "single_qubit_gate_fidelity_mean": 0.9995,
            "two_qubit_gate_fidelity_mean": 0.9920,
        },
    )

    qpu_cal = builder.capsule_data["extensions"]["qpu_calibration"]
    assert qpu_cal["device_arn"] == "arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1"
    assert qpu_cal["num_qubits"] == 25
    assert qpu_cal["connectivity"] == "all-to-all"


def test_compute_data_digest():
    """Test digest computation is deterministic and correctly formatted."""
    builder = CapsuleBuilder(name="test")

    # Test dict digest
    data = {"key": "value", "num": 42}
    digest1 = builder._compute_data_digest(data)
    digest2 = builder._compute_data_digest(data)

    assert digest1 == digest2  # Deterministic
    assert digest1.startswith("sha256:")
    assert len(digest1) == 71  # "sha256:" (7) + 64 hex chars


def test_add_result_digest():
    """Test adding result digests to extensions."""
    builder = CapsuleBuilder(name="test-workflow")
    builder.start_capsule()

    result_data = {"energy": -1.1372, "iterations": 24}
    digest = builder.add_result_digest(
        result_data,
        digest_name="final_energy",
        digest_type="statistical",
    )

    assert digest.startswith("sha256:")
    assert "result_digests" in builder.capsule_data["extensions"]
    assert "final_energy" in builder.capsule_data["extensions"]["result_digests"]

    entry = builder.capsule_data["extensions"]["result_digests"]["final_energy"]
    assert entry["digest"] == digest
    assert entry["type"] == "statistical"
