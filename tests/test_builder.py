import tempfile
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
