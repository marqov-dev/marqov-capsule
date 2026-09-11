"""Exercise the standalone rehearsal without enabling executable result decoding."""
import importlib.util
from pathlib import Path
import pickle

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/rehearse_managed_result.py'
spec = importlib.util.spec_from_file_location('managed_rehearsal', SCRIPT)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def test_managed_result_preservation_and_refusal(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Opaque results must not be deserialized')
    monkeypatch.setattr(pickle, 'loads', forbidden)
    monkeypatch.setattr(pickle, 'load', forbidden)
    result = rehearsal.rehearsal(tmp_path / 'evidence')
    assert len(result['cases']) == 6
    assert all(case['exact_bytes'] and len(case['refused']) == 4 for case in result['cases'])
    assert result['cases'][-1]['sidecar_sha256'] is None
    assert all(case['sidecar_sha256'] for case in result['cases'][:-1])
    with pytest.raises(FileExistsError):
        rehearsal.rehearsal(tmp_path / 'evidence')
