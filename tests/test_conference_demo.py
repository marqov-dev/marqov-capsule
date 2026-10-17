"""Exercise the demo's public contract using an offline export fixture."""

import importlib.util
import json
from pathlib import Path


def test_capsule_demo_roundtrip_and_tamper_detection(tmp_path):
    path = Path(__file__).parents[1] / "examples/seal_bell.py"
    spec = importlib.util.spec_from_file_location("seal_bell", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    export = tmp_path / "export"
    export.mkdir()
    for name, content in {
        "results.json": '{"counts":{"00":503,"11":497},"shots":1000}',
        "circuit.json": '{"description":"synthetic test circuit"}',
        "environment.json": '{"description":"offline test fixture"}',
        "run_bell.py": "# Synthetic test export; the live SDK run is a separate check.\n",
    }.items():
        (export / name).write_text(content)
    output = tmp_path / "demo"
    report = module.demo(export, output)
    assert json.loads((output / "report.json").read_text()) == report
    assert (output / "trusted-id.txt").read_text().strip() == report["capsule_id"]
    assert report["changed_manifest"]["capsule_id_match"] is False
    assert (output / "bell-state/results.json").read_bytes() == (
        export / "results.json"
    ).read_bytes()
