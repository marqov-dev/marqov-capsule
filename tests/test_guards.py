"""Guards that survived mutation testing with the suite green (#117).

Each test here pins one guard the Fable review found uncovered: deleting or
inverting the guarded line must turn the test red.
"""

import io
import tarfile

import pytest

from marqov_capsule import archive as archive_mod
from marqov_capsule._canonical import _stringify_key, compute_capsule_id
from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.policy import VerificationPolicy
from marqov_capsule.verifier import CapsuleVerifier


# M3 — policy.py: a non-positive declared epsilon is unusable, never honoured.
@pytest.mark.parametrize("declared", [0, 0.0, -0.0, -1, -1e-9])
def test_non_positive_declared_epsilon_falls_back_to_policy_ceiling(declared):
    policy = VerificationPolicy(epsilon=0.02)
    resolved = policy.resolve({"epsilon": declared})
    assert resolved["epsilon"] == 0.02
    assert resolved["epsilon_clamped"] is False


# M4 — builder.py: sealing needs BOTH paradigm and max_qubit_count.
@pytest.mark.parametrize(
    "requirements",
    [
        {"paradigm": ["gate-based"]},
        {"max_qubit_count": 2},
        {},
    ],
)
def test_seal_requires_both_paradigm_and_max_qubit_count(requirements, tmp_path):
    builder = CapsuleBuilder().start_capsule(name="t", requirements=requirements)
    with pytest.raises(ValueError, match="paradigm.*max_qubit_count"):
        builder.seal_capsule(tmp_path)
    assert not (tmp_path / ".checksums").exists()


def _archive_with(tmp_path, extra_member):
    bad = tmp_path / "bad.capsule"
    with tarfile.open(str(bad), "w:gz") as tf:
        manifest = b"version: '1.0.0'\n"
        ti = tarfile.TarInfo("bad.capsule/capsule.yaml")
        ti.size = len(manifest)
        tf.addfile(ti, io.BytesIO(manifest))
        tf.addfile(extra_member)
    return bad


# M19 — archive.py fallback extractor refuses device members.
@pytest.mark.parametrize("typeflag", [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_fallback_extractor_refuses_device_members(typeflag, tmp_path):
    dev = tarfile.TarInfo("bad.capsule/dev")
    dev.type = typeflag
    dev.devmajor, dev.devminor = 1, 3
    bad = _archive_with(tmp_path, dev)
    dest = tmp_path / "dest"
    dest.mkdir()
    # unpack_capsule refuses these up front; the fallback keeps its own guard.
    with tarfile.open(str(bad), "r:gz") as tf:
        with pytest.raises(ValueError, match="device"):
            archive_mod._safe_extractall(tf, dest)
    assert not (dest / "bad.capsule" / "dev").exists()


# M20 — archive.py fallback extractor checks HARDLINK targets, not just symlinks.
def test_fallback_extractor_refuses_hardlink_escaping_destination(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("outside\n")
    link = tarfile.TarInfo("bad.capsule/link")
    link.type = tarfile.LNKTYPE
    link.linkname = "../secret.txt"  # relative to the archive root -> escapes
    bad = _archive_with(tmp_path, link)
    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(str(bad), "r:gz") as tf:
        with pytest.raises(ValueError, match="link target escapes"):
            archive_mod._safe_extractall(tf, dest)


# M24 — verifier.py: the shot floor applies to the SMALLER arm.
def test_shot_floor_uses_the_smaller_arm():
    ref = {"00": 20_000, "11": 20_000}
    new = {"00": 5, "11": 5}
    result = CapsuleVerifier().verify_statistical(ref, new, {"min_shots": 100, "epsilon": 0.02})
    assert result["verdict"] == "INCONCLUSIVE"
    assert "below min_shots" in result["reason"]
    assert "tvd_ucb" not in result["metrics"]
    # and the other way round
    result = CapsuleVerifier().verify_statistical(new, ref, {"min_shots": 100, "epsilon": 0.02})
    assert result["verdict"] == "INCONCLUSIVE"
    assert "tvd_ucb" not in result["metrics"]


# M42 — _canonical.py: non-string keys stringify by the JSON value rule.
@pytest.mark.parametrize(
    "key,spelling",
    [
        (True, "true"),
        (False, "false"),
        (None, "null"),
        (1, "1"),
        (2.5, "2.5"),
        (100.0, "100"),
    ],
)
def test_non_string_keys_use_json_literal_spelling(key, spelling):
    assert _stringify_key(key) == spelling
    assert compute_capsule_id({key: 1}) == compute_capsule_id({spelling: 1})
