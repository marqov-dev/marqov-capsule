"""CLI surface for the archive layer: pack, unpack, and archive-aware verify.

Restored with #48. The original was deleted alongside `archive.py` when the
monolithic `cli.py` was replaced — losing the caller made the module look like
dead code, and the tests that would have said otherwise went in the same commit.
"""
import json
import tarfile
from pathlib import Path

from click.testing import CliRunner

from marqov_capsule.builder import CapsuleBuilder
from marqov_capsule.cli.main import cli


def _sealed(parent: Path, name: str = "bell") -> Path:
    capsule_dir = parent / f"{name}.capsule"
    (capsule_dir / "payload").mkdir(parents=True)
    (capsule_dir / "payload" / "results.json").write_text('{"counts": {"00": 512}}')
    CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": name, "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    }).seal(capsule_dir=capsule_dir, sealed_by="test")
    return capsule_dir


# --- pack -------------------------------------------------------------------


def test_pack_creates_an_archive(tmp_path):
    d = _sealed(tmp_path)
    out = tmp_path / "bell.capsule.tgz"
    result = CliRunner().invoke(cli, ["pack", str(d), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists() and tarfile.is_tarfile(str(out))


def test_pack_json_reports_path_and_digest(tmp_path):
    d = _sealed(tmp_path)
    result = CliRunner().invoke(cli, ["pack", str(d), "-o", str(tmp_path / "a.capsule"), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "path" in data
    assert data["payload_digest"].startswith("sha256:")


def test_pack_is_deterministic_through_the_cli(tmp_path):
    """The whole point of the format: same capsule in, same bytes out."""
    d = _sealed(tmp_path)
    runner = CliRunner()
    for name in ("one", "two"):
        r = runner.invoke(cli, ["pack", str(d), "-o", str(tmp_path / f"{name}.capsule")])
        assert r.exit_code == 0, r.output
    assert (tmp_path / "one.capsule").read_bytes() == (tmp_path / "two.capsule").read_bytes()


def test_pack_refuses_an_unsealed_directory(tmp_path):
    d = tmp_path / "draft.capsule"
    (d / "payload").mkdir(parents=True)
    (d / "payload" / "results.json").write_text("{}")
    result = CliRunner().invoke(cli, ["pack", str(d), "-o", str(tmp_path / "x.capsule")])
    assert result.exit_code != 0
    assert ".checksums" in result.output


# --- unpack -----------------------------------------------------------------


def test_unpack_restores_the_capsule(tmp_path):
    d = _sealed(tmp_path)
    archive = tmp_path / "a.capsule"
    CliRunner().invoke(cli, ["pack", str(d), "-o", str(archive)])

    dest = tmp_path / "restored"
    result = CliRunner().invoke(cli, ["unpack", str(archive), "-o", str(dest)])
    assert result.exit_code == 0, result.output
    restored = next(dest.iterdir()) if dest.is_dir() else dest
    assert (restored / "capsule.yaml").exists()
    assert (restored / ".checksums").exists()
    assert (restored / "payload" / "results.json").exists()


def test_unpack_json_reports_path(tmp_path):
    d = _sealed(tmp_path)
    archive = tmp_path / "a.capsule"
    CliRunner().invoke(cli, ["pack", str(d), "-o", str(archive)])
    result = CliRunner().invoke(cli, ["unpack", str(archive), "-o", str(tmp_path / "r"), "--json"])
    assert result.exit_code == 0, result.output
    assert "path" in json.loads(result.output)


# --- verify accepts an archive ---------------------------------------------


def test_verify_accepts_an_archive(tmp_path):
    d = _sealed(tmp_path)
    archive = tmp_path / "a.capsule"
    CliRunner().invoke(cli, ["pack", str(d), "-o", str(archive)])

    result = CliRunner().invoke(cli, ["verify", str(archive)])
    assert result.exit_code == 0, result.output


def test_verify_archive_reports_the_payload_digest(tmp_path):
    d = _sealed(tmp_path)
    archive = tmp_path / "a.capsule"
    CliRunner().invoke(cli, ["pack", str(d), "-o", str(archive)])

    result = CliRunner().invoke(cli, ["verify", str(archive), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["payload_digest"].startswith("sha256:")


def test_payload_digest_agrees_between_directory_and_archive(tmp_path):
    """The property that makes content addressing coherent: an archive and the
    directory it came from name the same thing."""
    d = _sealed(tmp_path)
    archive = tmp_path / "a.capsule"
    packed = json.loads(CliRunner().invoke(
        cli, ["pack", str(d), "-o", str(archive), "--json"]).output)
    verified = json.loads(CliRunner().invoke(
        cli, ["verify", str(archive), "--json"]).output)
    assert verified["payload_digest"] == packed["payload_digest"]


def test_verify_rejects_a_tampered_archive(tmp_path):
    """Repack a modified payload: the digest chain must still catch it."""
    d = _sealed(tmp_path)
    (d / "payload" / "results.json").write_text('{"counts": {"00": 999}}')  # after sealing
    archive = tmp_path / "tampered.capsule"
    CliRunner().invoke(cli, ["pack", str(d), "-o", str(archive)])

    result = CliRunner().invoke(cli, ["verify", str(archive)])
    assert result.exit_code != 0, result.output


# --- archive identity must cover the manifest (#48) -------------------------

def _sealed_as(parent: Path, name: str, sealed_by: str) -> Path:
    d = parent / f"{name}.capsule"
    (d / "payload").mkdir(parents=True)
    (d / "payload" / "results.json").write_text('{"counts": {"00": 512}}')
    CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": name, "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    }).seal(capsule_dir=d, sealed_by=sealed_by)
    return d


def test_payload_digest_is_named_honestly_not_as_content_id(tmp_path):
    """`.checksums` excludes capsule.yaml, so its digest cannot identify a
    capsule — it identifies the payload set. Calling it a content ID would
    reintroduce the layer-1-only identity that #14 was about."""
    from marqov_capsule import archive
    assert hasattr(archive, "payload_digest"), dir(archive)
    assert not hasattr(archive, "content_id"), "overclaiming name still exported"


def test_pack_reports_the_capsule_id_as_identity(tmp_path):
    d = _sealed(tmp_path)
    out = json.loads(CliRunner().invoke(
        cli, ["pack", str(d), "-o", str(tmp_path / "a.capsule"), "--json"]).output)
    assert len(out["capsule_id"]) == 64, out
    assert out["payload_digest"].startswith("sha256:"), out


def test_two_capsules_differing_only_in_manifest_get_distinct_identities(tmp_path):
    """Same payload, different name and sealed_by. The payload digest collides
    by construction; the reported identity must not."""
    a = _sealed_as(tmp_path, "alpha", "alice")
    b = _sealed_as(tmp_path, "beta", "mallory")
    runner = CliRunner()
    oa = json.loads(runner.invoke(cli, ["pack", str(a), "-o", str(tmp_path / "a.cap"), "--json"]).output)
    ob = json.loads(runner.invoke(cli, ["pack", str(b), "-o", str(tmp_path / "b.cap"), "--json"]).output)

    assert oa["payload_digest"] == ob["payload_digest"], "precondition: payloads are identical"
    assert oa["capsule_id"] != ob["capsule_id"], "distinct capsules must have distinct IDs"
