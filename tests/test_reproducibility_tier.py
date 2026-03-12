import tempfile
from pathlib import Path

import pytest

from marqov_capsule import CapsuleBuilder, CapsuleVerifier


class TestReproducibilityTierBuilder:
    def test_default_tier_is_deterministic(self):
        builder = CapsuleBuilder("tier-test", description="Tier test capsule")
        builder.start_capsule(parameters={})
        data = builder.get_capsule_data()
        assert data["reproducibility_tier"] == "deterministic"

    def test_set_statistical_tier(self):
        builder = CapsuleBuilder("tier-test", description="Tier test capsule", reproducibility_tier="statistical")
        builder.start_capsule(parameters={})
        data = builder.get_capsule_data()
        assert data["reproducibility_tier"] == "statistical"

    def test_set_verification_only_tier(self):
        builder = CapsuleBuilder("tier-test", description="Tier test capsule", reproducibility_tier="verification-only")
        builder.start_capsule(parameters={})
        data = builder.get_capsule_data()
        assert data["reproducibility_tier"] == "verification-only"

    def test_invalid_tier_raises_error(self):
        with pytest.raises(ValueError, match="reproducibility_tier"):
            CapsuleBuilder("tier-test", description="Invalid tier", reproducibility_tier="invalid")

    def test_tier_persists_through_seal(self):
        builder = CapsuleBuilder("tier-test", description="Tier seal test", reproducibility_tier="statistical")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        sealed = builder.seal_capsule(exit_code=0)
        assert sealed["reproducibility_tier"] == "statistical"

    def test_tier_roundtrips_through_save_load(self):
        builder = CapsuleBuilder("tier-test", description="Tier roundtrip test", reproducibility_tier="statistical")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        builder.seal_capsule(exit_code=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = Path(tmpdir) / "tier.capsule"
            capsule_dir.mkdir()
            builder.save_capsule(str(capsule_dir / "capsule.yaml"))
            verifier = CapsuleVerifier()
            loaded = verifier.load_capsule(str(capsule_dir / "capsule.yaml"))
            assert loaded["reproducibility_tier"] == "statistical"
