import tempfile
from pathlib import Path

import pytest
import yaml

from marqov_capsule import CapsuleBuilder


class TestEnvironmentLock:
    def test_seal_generates_lock_data(self):
        builder = CapsuleBuilder("lock-test", description="Lock test capsule")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        sealed = builder.seal_capsule(exit_code=0)

        assert "environment_lock" in sealed
        lock = sealed["environment_lock"]
        assert "packages" in lock
        assert "python_version" in lock
        assert "platform" in lock
        assert "locked_at" in lock

        pkg_names = [p["name"].lower() for p in lock["packages"]]
        assert "pyyaml" in pkg_names

    def test_seal_without_lock(self):
        builder = CapsuleBuilder("no-lock", description="No lock test")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        sealed = builder.seal_capsule(exit_code=0, lock_environment=False)
        assert "environment_lock" not in sealed

    def test_save_writes_lock_file(self):
        builder = CapsuleBuilder("lock-save", description="Lock save test")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        builder.seal_capsule(exit_code=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = Path(tmpdir) / "lock.capsule"
            capsule_dir.mkdir()
            builder.save_capsule(str(capsule_dir / "capsule.yaml"))

            lock_path = capsule_dir / "environment.lock.yaml"
            assert lock_path.exists()

            with open(lock_path) as f:
                lock_data = yaml.safe_load(f)
            assert "packages" in lock_data
            assert "python_version" in lock_data

    def test_lock_file_in_checksums(self):
        builder = CapsuleBuilder("lock-chk", description="Lock checksum test")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        builder.seal_capsule(exit_code=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            capsule_dir = Path(tmpdir) / "lock-chk.capsule"
            capsule_dir.mkdir()
            builder.save_capsule(str(capsule_dir / "capsule.yaml"))
            checksums_text = (capsule_dir / ".checksums").read_text()
            assert "environment.lock.yaml" in checksums_text

    def test_lock_package_format(self):
        builder = CapsuleBuilder("fmt-test", description="Format test")
        builder.start_capsule(parameters={})
        builder.add_task_execution(task_id="t1", backend="local", outputs={"r": 1})
        sealed = builder.seal_capsule(exit_code=0)
        for pkg in sealed["environment_lock"]["packages"]:
            assert "name" in pkg
            assert "version" in pkg
