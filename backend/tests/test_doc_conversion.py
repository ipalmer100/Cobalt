import subprocess
import tempfile
from pathlib import Path

import docx
import pytest

from specwrite.doc_conversion import ConversionError, convert_doc_to_docx, soffice_available
from specwrite.docx_sections import parse_document

from .fixtures.builder import build_sample_spec_docx


def _soffice_actually_works() -> bool:
    """`soffice` can be on PATH but still fail to run headless conversions
    in a stripped-down container (missing runtime deps, broken profile
    bootstrap, etc.) — probe with a trivial conversion rather than trusting
    binary presence alone, so this suite skips cleanly in that case instead
    of reporting false failures."""
    if not soffice_available():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.docx"
        docx.Document().save(str(probe))
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{tmp}/lo_profile",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(probe),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and (Path(tmp) / "probe.pdf").exists()


requires_working_soffice = pytest.mark.skipif(
    not _soffice_actually_works(),
    reason="LibreOffice is present but not functional in this environment (headless conversion probe failed)",
)


def _make_legacy_doc(tmp_path, spec_number="SW0001") -> str:
    """Build a synthetic spec and downgrade it to legacy .doc via LibreOffice,
    to get a genuine .doc fixture without hand-crafting binary OLE data."""
    docx_path = tmp_path / "source" / "spec.docx"
    docx_path.parent.mkdir()
    build_sample_spec_docx(str(docx_path), spec_number=spec_number)

    doc_dir = tmp_path / "legacy"
    doc_dir.mkdir()
    result = subprocess.run(
        ["soffice", "--headless", "--norestore", "--convert-to", "doc", "--outdir", str(doc_dir), str(docx_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    doc_path = doc_dir / "spec.doc"
    assert doc_path.exists()
    return str(doc_path)


@requires_working_soffice
def test_convert_doc_to_docx_produces_parseable_file(tmp_path):
    doc_path = _make_legacy_doc(tmp_path)

    converted_path = convert_doc_to_docx(doc_path)

    assert converted_path.endswith(".docx")
    spec = parse_document(converted_path)
    assert spec.spec_number == "SW0001"
    assert spec.customer == "ACME Corp"


def test_convert_refuses_to_overwrite_existing_destination(tmp_path):
    # The destination-exists check happens before soffice is ever invoked,
    # so this doesn't need a genuinely convertible .doc — any existing file works.
    doc_path = tmp_path / "stub.doc"
    doc_path.write_bytes(b"not a real doc file")
    dest = tmp_path / "already_here.docx"
    dest.write_text("existing file")

    with pytest.raises(ConversionError, match="already exists"):
        convert_doc_to_docx(str(doc_path), dest_path=str(dest))


def test_convert_missing_source_raises(tmp_path):
    with pytest.raises(ConversionError, match="does not exist"):
        convert_doc_to_docx(str(tmp_path / "nope.doc"))


def test_convert_raises_if_soffice_missing(tmp_path, monkeypatch):
    import specwrite.doc_conversion as mod

    monkeypatch.setattr(mod, "soffice_available", lambda: False)
    doc_path = tmp_path / "stub.doc"
    doc_path.write_bytes(b"not a real doc file")

    with pytest.raises(ConversionError, match="LibreOffice"):
        convert_doc_to_docx(str(doc_path))


def test_convert_raises_if_soffice_produces_no_output(tmp_path, monkeypatch):
    """Guards against soffice reporting success (exit 0) but silently not
    writing anything — exactly the failure mode this sandbox hit."""
    import specwrite.doc_conversion as mod

    doc_path = tmp_path / "stub.doc"
    doc_path.write_bytes(b"not a real doc file")

    class FakeResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: FakeResult())

    with pytest.raises(ConversionError, match="produced no output"):
        convert_doc_to_docx(str(doc_path))
