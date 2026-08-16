import json
from pathlib import Path
import pytest
from marqov_capsule.redactor import CapsuleRedactor, RedactorError


FIXTURE_DIR = Path(__file__).parent.parent / "spec/v1/conformance"


def test_clean_dir_passes(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "circuit.py").write_text("from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\n")
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False
    assert result["findings"] == []


def test_detects_name_based_token(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True
    # §9.7: report the (redacted) value, not the variable name. The finding must
    # point at the token value, and must NOT leak the whole value or echo the
    # bare variable name (the old behaviour reported m.group(0) — the name).
    findings = result["findings"]
    assert any(f["reason"] == "name_pattern" for f in findings)
    assert not any(f["match"] == "IBM_QUANTUM_TOKEN" for f in findings)
    assert any(f["match"].startswith("fake") for f in findings)
    assert not any("fake-token-abcdef1234567890" in f["match"] for f in findings)


def test_detects_constructor_pattern(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "run.py").write_text('QiskitRuntimeService(token="fake-token-abcdef1234567890")\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_detects_key_suffix(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.json").write_text('{"AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_block_mode_raises(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path, mode="block")
    with pytest.raises(RedactorError):
        redactor.scan_and_raise()


def test_warn_only_returns_result(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')
    redactor = CapsuleRedactor(tmp_path, mode="warn_only")
    result = redactor.scan()
    assert result["has_secrets"] is True  # found but not raised


def test_allowlist_digest_fields_not_flagged(tmp_path):
    # SHA-256 hashes in spec-defined fields must not trigger the high-entropy heuristic
    manifest = tmp_path / "capsule.yaml"
    manifest.write_text(
        "checksums_digest: sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890\n"
        "version: '1.0.0'\n"
    )
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_capsuleignore_excludes_files(tmp_path):
    """.capsuleignore narrows *scanning* scope, and the narrowing is reported.

    Rewritten for #34. This previously wrote a `.env` containing an AWS key,
    ignored it via `.capsuleignore`, and asserted `has_secrets is False` — the
    test encoded the vulnerability. A credential-shaped file is now a finding
    that no ignore rule can suppress; see the #34 tests below.
    """
    (tmp_path / "vendored.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    (tmp_path / ".capsuleignore").write_text("vendored.py\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False
    assert "vendored.py" in result["skipped"]


def test_capsule_with_secrets_fixture_detected():
    fixture_dir = FIXTURE_DIR / "capsule_with_secrets"
    redactor = CapsuleRedactor(fixture_dir)
    result = redactor.scan()
    assert result["has_secrets"] is True


def test_valid_capsule_fixture_clean():
    fixture_dir = FIXTURE_DIR / "valid_capsule"
    redactor = CapsuleRedactor(fixture_dir)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_redactor_does_not_follow_symlinks(tmp_path):
    """Redactor must not follow symlinks out of the capsule tree (#32).

    A symlink whose target lives outside the capsule must not be read; otherwise
    the scanner reaches arbitrary files on the sealer's machine.
    """
    outside = tmp_path / "outside_secret.py"
    outside.write_text('IBM_QUANTUM_TOKEN = "fake-token-abcdef1234567890"\n')

    capsule_dir = tmp_path / "test.capsule"
    capsule_dir.mkdir()
    src = capsule_dir / "source"
    src.mkdir()
    (src / "link.py").symlink_to(outside)

    redactor = CapsuleRedactor(capsule_dir)
    result = redactor.scan()
    assert result["has_secrets"] is False


def test_capsule_allow_suppresses_name_pattern(tmp_path):
    # capsule:allow must suppress name-pattern matches, not just entropy heuristic
    src = tmp_path / "source"
    src.mkdir()
    (src / "config.py").write_text('IBM_QUANTUM_TOKEN = "test"  # capsule:allow\n')
    redactor = CapsuleRedactor(tmp_path)
    result = redactor.scan()
    assert result["has_secrets"] is False


# --- Notebook coverage (#33) ------------------------------------------------
# _scan_notebook walked only `outputs`. A researcher pastes a live token into a
# *source* cell, which is where it actually happens, and seal gates on this scan.

def _notebook(cells):
    import json
    return json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def test_detects_secret_in_code_cell_source(tmp_path):
    (tmp_path / "run.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["IBM_QUANTUM_TOKEN = \"abc123\"\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_detects_secret_in_markdown_cell_source(tmp_path):
    (tmp_path / "notes.ipynb").write_text(_notebook([{
        "cell_type": "markdown", "source": ["Use `IBM_QUANTUM_TOKEN = \"abc\"` to run.\n"],
        "metadata": {},
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_detects_secret_in_error_traceback(tmp_path):
    """Tracebacks routinely echo the offending line, tokens included."""
    (tmp_path / "boom.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["connect()\n"], "execution_count": 1, "metadata": {},
        "outputs": [{
            "output_type": "error", "ename": "ValueError", "evalue": "bad token",
            "traceback": ["Traceback...", "  IBM_QUANTUM_TOKEN = \"abc123\""],
        }],
    }]))
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result


def test_notebook_source_as_plain_string(tmp_path):
    """nbformat allows `source` to be a string rather than a list of lines."""
    (tmp_path / "s.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": "IBM_QUANTUM_TOKEN = \"abc123\"\n",
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    assert CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_notebook_stream_output_still_scanned(tmp_path):
    """Regression: output scanning must survive the source-cell fix."""
    (tmp_path / "o.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["print(tok)\n"], "execution_count": 1, "metadata": {},
        "outputs": [{"output_type": "stream", "name": "stdout",
                     "text": ["IBM_QUANTUM_TOKEN = \"abc123\"\n"]}],
    }]))
    assert CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_clean_notebook_not_flagged(tmp_path):
    (tmp_path / "clean.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["from qiskit import QuantumCircuit\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    assert not CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_malformed_notebook_does_not_crash(tmp_path):
    (tmp_path / "bad.ipynb").write_text("{not valid json")
    (tmp_path / "odd.ipynb").write_text('{"cells": [{"cell_type": "code", "source": null}]}')
    assert not CapsuleRedactor(tmp_path).scan()["has_secrets"]


def test_notebook_reports_the_notebook_path(tmp_path):
    (tmp_path / "run.ipynb").write_text(_notebook([{
        "cell_type": "code", "source": ["IBM_QUANTUM_TOKEN = \"abc\"\n"],
        "outputs": [], "execution_count": 1, "metadata": {},
    }]))
    findings = CapsuleRedactor(tmp_path).scan()["findings"]
    assert findings and findings[0]["file"] == "run.ipynb"
# --- Ignore-file trust and credential-shaped files (#34) --------------------
# Two distinct holes. (1) .capsuleignore is read from inside the capsule and
# REPLACED the whole default ignore set, so a capsule carrying one containing
# `source` silently disabled scanning for that subtree. (2) .env/*.pem/*.key
# were excluded from *scanning* while save_checksums still packaged them, so a
# directory holding secrets scanned clean and sealed with them inside.

def test_env_file_is_a_finding_not_an_exclusion(tmp_path):
    (tmp_path / ".env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result
    assert any(f["reason"] == "credential_file" for f in result["findings"]), result


def test_private_key_files_are_findings(tmp_path):
    (tmp_path / "deploy.key").write_text("-----BEGIN PRIVATE KEY-----\n")
    (tmp_path / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    reasons = [f["reason"] for f in CapsuleRedactor(tmp_path).scan()["findings"]]
    assert reasons.count("credential_file") == 2, reasons


def test_capsuleignore_cannot_suppress_a_credential_file(tmp_path):
    """The file is being packaged into the capsule. Not scanning it doesn't help."""
    (tmp_path / ".env").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    (tmp_path / ".capsuleignore").write_text(".env\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"], result
    assert any(f["reason"] == "credential_file" for f in result["findings"]), result


def test_seal_is_blocked_by_a_credential_file(tmp_path):
    from marqov_capsule.builder import CapsuleBuilder
    (tmp_path / "payload").mkdir()
    (tmp_path / "payload" / "results.json").write_text('{"counts": {"00": 1}}')
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=abc\n")
    b = CapsuleBuilder.from_manifest({
        "version": "1.0.0", "name": "t", "lifecycle_state": "draft",
        "requirements": {"paradigm": ["gate-based"], "max_qubit_count": 2},
        "task_executions": [],
    })
    with pytest.raises(RedactorError):
        b.seal(capsule_dir=tmp_path, sealed_by="test")


def test_capsuleignore_adds_to_defaults_rather_than_replacing(tmp_path):
    """A .capsuleignore must not be able to un-skip the default noise set."""
    (tmp_path / ".capsuleignore").write_text("data\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "y.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    result = CapsuleRedactor(tmp_path).scan()
    scanned = {f["file"] for f in result["findings"]}
    assert not any("__pycache__" in s for s in scanned), scanned
    assert not any("data" in s for s in scanned), scanned


def test_scan_reports_what_it_skipped(tmp_path):
    """Narrowing scope must be visible, not silent."""
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert not result["has_secrets"]
    assert "source/circuit.py" in result["skipped"], result
    assert "source" in result["capsuleignore_patterns"], result


def test_scan_reports_no_capsuleignore_patterns_when_absent(tmp_path):
    (tmp_path / "a.py").write_text("print(1)\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["capsuleignore_patterns"] == []
    assert result["skipped"] == []


def test_seal_dry_run_reports_narrowed_scope(tmp_path):
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli
    (tmp_path / "capsule.yaml").write_text(
        "version: 1.0.0\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
        "task_executions: []\n")
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("IBM_QUANTUM_TOKEN = 'abc'\n")
    out = CliRunner().invoke(cli, ["seal", "--dry-run", str(tmp_path)]).output
    assert ".capsuleignore" in out, out
    assert "source" in out, out


def test_real_seal_also_reports_narrowed_scope(tmp_path):
    """--dry-run is the path people skip. The gate itself must say so too."""
    from click.testing import CliRunner
    from marqov_capsule.cli.main import cli
    (tmp_path / "capsule.yaml").write_text(
        "version: 1.0.0\nname: t\nlifecycle_state: draft\n"
        "requirements:\n  paradigm: [gate-based]\n  max_qubit_count: 2\n"
        "task_executions: []\n")
    (tmp_path / ".capsuleignore").write_text("source\n")
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "circuit.py").write_text("print(1)\n")
    result = CliRunner().invoke(cli, ["seal", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert ".capsuleignore" in result.output, result.output
    assert "source" in result.output, result.output


def test_credential_file_error_advises_removal_not_annotation(tmp_path):
    """`# capsule:allow` is line-based and cannot suppress a whole-file finding.
    Advising it for a .env would send the user down a dead end."""
    (tmp_path / ".env").write_text("AWS_SECRET_ACCESS_KEY=abc\n")
    with pytest.raises(RedactorError) as exc:
        CapsuleRedactor(tmp_path).scan_and_raise()
    msg = str(exc.value)
    assert "capsule:allow" not in msg, msg
    assert "move" in msg.lower() or "remove" in msg.lower(), msg


# --- #18 / research §9: two-tier detection ---------------------------------
# Tier A = distinctive shape rules -> BLOCK. Tier B = keyword-proximity +
# charset-split entropy -> WARN, never block. The current single-entropy
# mechanism produced false negatives (hex/lowercase) and false positives
# (numerical payloads) at once; these pin the corrected behaviour.

# A well-distributed 64-char hex value (IBM Quantum token shape). Written as
# 8-char groups so the length is guaranteed correct by construction.
HEX64 = ("7e2a91c4" "f0b8d63e" "5a1f8c02" "d94b7e6a"
         "3f5c8091" "b2d4e6f7" "a0c1b3d5" "e7f9a2c4")
assert len(HEX64) == 64


def _blocks(capsule_dir):
    """True iff a block-mode scan_and_raise raises on this directory."""
    try:
        CapsuleRedactor(capsule_dir, mode="block").scan_and_raise()
        return False
    except RedactorError:
        return True


def test_ibm_64hex_token_is_flagged_and_blocks(tmp_path):
    """`ibm_quantum_token = "<64-hex>"` scanned clean before (entropy 4.5 is
    above the lowercase-hex ceiling of 4.0). It must now block (Tier A)."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "cfg.py").write_text(f'ibm_quantum_token = "{HEX64}"\n')
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is True, result
    assert _blocks(tmp_path)


def test_ibm_64hex_via_keyword_proximity_blocks(tmp_path):
    """The IBM rule is keyword-proximity + 64-hex, not a bare \\b[a-f0-9]{64}\\b.
    A non-credential variable name still blocks when an IBM keyword is near."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "run.py").write_text(f'creds = "{HEX64}"  # qiskit runtime token\n')
    assert _blocks(tmp_path)


def test_bare_64hex_checksum_does_not_block(tmp_path):
    """A 64-hex with no IBM keyword nearby is a checksum, not a token. It must
    not block (the research's central warning against a bare 64-hex rule)."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "manifest.txt").write_text(f'{HEX64}  results.json\n')
    assert not _blocks(tmp_path)


def test_aws_access_key_id_is_flagged_and_blocks(tmp_path):
    """AKIA-prefixed access key IDs have a distinctive shape -> Tier A block."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "boto.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"\n')
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is True, result
    assert _blocks(tmp_path)


def test_various_shape_rules_block(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    samples = {
        "gh.py": 'tok = "ghp_' + "a" * 36 + '"\n',
        "google.py": 'k = "AIza' + "B" * 35 + '"\n',
        "stripe.py": 'k = "sk_live_' + "c" * 24 + '"\n',
        "slack.py": 'k = "xoxb-1234567890-0987654321-' + "d" * 24 + '"\n',
        "jwt.py": 'k = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
                  'eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.abcDEFghiJKL"\n',
        "pem.py": ('-----BEGIN RSA PRIVATE KEY-----\n' + 'MIIBOwIBAAJB' * 8
                   + '\n-----END RSA PRIVATE KEY-----\n'),
    }
    for name, body in samples.items():
        (src / name).write_text(body)
    assert _blocks(tmp_path)
    # every distinctive-shape file must be independently blocking
    for name, body in samples.items():
        one = tmp_path / name
        one.mkdir()
        (one / "f.py").write_text(body)
        assert _blocks(one), name


def test_base64_statevector_payload_is_not_flagged(tmp_path):
    """A base64 float64 / complex128 statevector is entropy-indistinguishable
    from a base64 secret. The length cap (safe now that Tier A catches long
    structured secrets) must skip it -> no false positive. See note §1, §9."""
    import base64
    np = pytest.importorskip("numpy")  # numpy-free base install must skip, not fail
    rng = np.random.default_rng(0)
    payload = tmp_path / "payload"
    payload.mkdir()
    f64 = base64.b64encode(rng.standard_normal(1024).tobytes()).decode()
    c128 = base64.b64encode(
        (rng.standard_normal(512) + 1j * rng.standard_normal(512)).tobytes()
    ).decode()
    (payload / "sv.py").write_text(f'statevector = "{f64}"\namplitudes = "{c128}"\n')
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False, result["findings"]


def test_os_environ_reference_does_not_block(tmp_path):
    """`os.environ['IBM_QUANTUM_TOKEN']` is a *safe* reference — reading a token
    from the environment, not embedding one. It must not block (or warn)."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "safe.py").write_text(
        "import os\n"
        "token = os.environ['IBM_QUANTUM_TOKEN']\n"
        "svc = QiskitRuntimeService(token=token)\n"
    )
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False, result["findings"]
    assert not _blocks(tmp_path)


def test_minified_json_capsule_allow_does_not_disable_whole_file(tmp_path):
    """`# capsule:allow` must suppress a single finding, not the whole line.
    A minified single-line JSON puts everything on one line; one occurrence of
    the literal must not disable scanning of a real token elsewhere on it."""
    src = tmp_path / "source"
    src.mkdir()
    line = ('{"note": "# capsule:allow", '
            '"AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE", "x": "y"}')
    (src / "data.json").write_text(line + "\n")
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is True, result
    assert _blocks(tmp_path)


def test_capsule_allow_trailing_comment_still_suppresses(tmp_path):
    """The narrowed annotation must still work as a genuine trailing comment."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "cfg.py").write_text('key = "AKIAIOSFODNN7EXAMPLE"  # capsule:allow\n')
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False, result["findings"]


def test_public_and_primary_key_names_are_not_flagged(tmp_path):
    """Allowlisted key-shaped names must not fire. A bare name can no longer
    match at all; these are the classic false positives from #18."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "db.py").write_text(
        'PUBLIC_KEY = "rsa-pub"\n'
        'PRIMARY_KEY = "id"\n'
        'SORTING_KEY = "created_at"\n'
        'foreign_key = "user_id"\n'
    )
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False, result["findings"]


def test_prose_mentioning_credential_names_is_not_flagged(tmp_path):
    """A bare name in prose/docs must not match — a capsule shipping an analysis
    README that discusses IBM_QUANTUM_TOKEN / *_KEY must still seal (#18)."""
    (tmp_path / "README.md").write_text(
        "Set the IBM_QUANTUM_TOKEN environment variable before running.\n"
        "The AWS_SECRET_ACCESS_KEY and GITHUB_TOKEN are read from the env.\n"
        "Never hardcode a _SECRET or _KEY in source.\n"
    )
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is False, result["findings"]


def test_generic_key_entropy_warns_but_does_not_block(tmp_path):
    """Tier B (keyword-proximity + entropy) warns; it never blocks."""
    src = tmp_path / "source"
    src.mkdir()
    (src / "svc.py").write_text('SERVICE_API_KEY = "aGVsbG8x9Qk3Zm9vYmFyM2Qz7cLh"\n')
    result = CapsuleRedactor(tmp_path).scan()
    assert result["has_secrets"] is True, result
    assert not _blocks(tmp_path)  # Tier B must not block


def test_env_local_bak_and_uppercase_pem_are_credential_files(tmp_path):
    """File patterns must also cover .env.local, *.bak and case-variant .PEM."""
    (tmp_path / ".env.local").write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    (tmp_path / "config.bak").write_text("secret backup\n")
    (tmp_path / "cert.PEM").write_text("-----BEGIN CERTIFICATE-----\n")
    reasons = [f["reason"] for f in CapsuleRedactor(tmp_path).scan()["findings"]]
    assert reasons.count("credential_file") == 3, reasons
    assert _blocks(tmp_path)
