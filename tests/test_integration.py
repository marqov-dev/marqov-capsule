"""End-to-end: build → seal → save → load → verify checksums → verify capsule."""

import tempfile
from pathlib import Path

from marqov_capsule import CapsuleBuilder, CapsuleVerifier


def test_full_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        capsule_dir = Path(tmpdir) / "roundtrip.capsule"
        capsule_dir.mkdir()
        capsule_path = capsule_dir / "capsule.yaml"

        # Build
        builder = CapsuleBuilder(
            "roundtrip-test",
            description="Integration test capsule",
            creator_version="test-harness-1.0",
        )
        builder.start_capsule(parameters={"distance": 3, "truncate": None})
        builder.add_task_execution(
            task_id="surface_code_analysis",
            backend="local",
            outputs={"wep": {0: 1, 2: 4, 4: 22, 6: 100, 8: 129}},
        )
        builder.add_result_digest(
            data={"wep": {0: 1, 2: 4, 4: 22, 6: 100, 8: 129}},
            digest_name="weight_enumerator",
        )

        # Seal
        sealed = builder.seal_capsule(exit_code=0, exit_message="success")
        assert sealed["lifecycle_state"] == "sealed"
        assert sealed["capsule_format_version"] == "1.0.0"
        assert sealed["creator_version"] == "test-harness-1.0"

        # Save
        builder.save_capsule(str(capsule_path))
        assert capsule_path.exists()
        assert (capsule_dir / ".checksums").exists()

        # Load
        verifier = CapsuleVerifier()
        loaded = verifier.load_capsule(str(capsule_path))
        assert loaded["name"] == "roundtrip-test"

        # Verify checksums
        checksum_result = verifier.verify_checksums(capsule_dir)
        assert checksum_result["passed"] is True
        assert checksum_result["mismatched"] == []
        assert checksum_result["missing"] == []

        # Verify capsule
        verify_result = verifier.verify_capsule(loaded, method="deterministic")
        assert verify_result["verification_passed"] is True


def test_round_trip_detects_tampering():
    with tempfile.TemporaryDirectory() as tmpdir:
        capsule_dir = Path(tmpdir) / "tamper.capsule"
        capsule_dir.mkdir()
        capsule_path = capsule_dir / "capsule.yaml"

        builder = CapsuleBuilder("tamper-test")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"x": 1})
        builder.seal_capsule(exit_code=0)
        builder.save_capsule(str(capsule_path))

        # Tamper
        with open(capsule_path, "a") as f:
            f.write("\n# injected\n")

        verifier = CapsuleVerifier()
        result = verifier.verify_checksums(capsule_dir)
        assert result["passed"] is False
        assert "capsule.yaml" in result["mismatched"]
