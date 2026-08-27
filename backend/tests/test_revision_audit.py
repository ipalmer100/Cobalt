"""The revision-numbering checker.

Its job is to find specs whose two statements of their own revision -- the
Revision # field and the last Revision History row -- have parted company,
including the ones an earlier build renumbered from 4 to "01".
"""

from docx import Document

from cobalt.docx_sections import parse_document
from cobalt.revision_audit import audit_folder, check_spec

from .fixtures.builder import build_sample_spec_docx


def _history(path: str):
    doc = Document(path)
    index = parse_document(path).primary("Revision History").table_index
    return doc, doc.tables[index]


def _kinds(path: str) -> list[str]:
    return [f.kind for f in check_spec(parse_document(path))]


def test_a_consistent_spec_produces_no_findings(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="01")
    assert _kinds(path) == []


def test_flags_a_spec_the_old_writer_renumbered_to_01(tmp_path):
    """The exact damage: a trailing blank row led the old writer to restart
    at "01", so the history now reads 4 then 01 and Product Description
    disagrees with neither cleanly."""
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="01")

    doc, table = _history(path)
    table.rows[1].cells[0].text = "4"
    row = table.add_row()
    row.cells[0].text = "01"
    row.cells[1].text = "Isaac"
    row.cells[3].text = "Renumbered by the old build."
    doc.save(path)

    kinds = _kinds(path)
    assert "out_of_sequence" in kinds, kinds

    finding = next(f for f in check_spec(parse_document(path)) if f.kind == "out_of_sequence")
    assert "goes backwards" in finding.detail
    assert '"01" after "4"' in finding.detail


def test_flags_a_stated_revision_that_disagrees_with_the_history(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="09")

    doc, table = _history(path)
    table.rows[1].cells[0].text = "02"
    doc.save(path)

    finding = next(f for f in check_spec(parse_document(path)) if f.kind == "mismatch")
    assert finding.stated == "09"
    assert finding.history_last == "02"
    # Reported, not corrected -- but it says where a save would resume, so
    # whoever owns the spec can see the consequence of leaving it as is.
    assert finding.continues_from == "09"


def test_flags_a_trailing_blank_history_row(tmp_path):
    """Harmless on its own, but it's the condition that caused the bad
    renumbering, so it's worth surfacing before someone revises the spec."""
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="01")

    doc, table = _history(path)
    table.add_row()
    doc.save(path)

    kinds = _kinds(path)
    assert "trailing_blank" in kinds, kinds


def test_flags_a_spec_that_states_no_revision(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="")

    kinds = _kinds(path)
    assert "stated_missing" in kinds, kinds


def test_repeated_revision_numbers_are_flagged(tmp_path):
    """Two people revising in parallel both write the same next number."""
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="02")

    doc, table = _history(path)
    table.rows[1].cells[0].text = "02"
    row = table.add_row()
    row.cells[0].text = "02"
    row.cells[3].text = "Same number again."
    doc.save(path)

    finding = next(f for f in check_spec(parse_document(path)) if f.kind == "out_of_sequence")
    assert "repeats" in finding.detail


def test_auditing_a_folder_reports_per_spec_and_counts_clean_ones(tmp_path):
    good = str(tmp_path / "good.docx")
    bad = str(tmp_path / "bad.docx")
    build_sample_spec_docx(good, spec_number="SW0001", revision="01")
    build_sample_spec_docx(bad, spec_number="SW0002", revision="09")

    doc, table = _history(bad)
    table.rows[1].cells[0].text = "02"
    doc.save(bad)

    result = audit_folder(str(tmp_path)).to_dict()

    assert result["checked"] == 2
    assert result["clean"] == 1
    assert {f["spec_number"] for f in result["findings"]} == {"SW0002"}
    assert result["unreadable"] == []


def test_an_unreadable_file_is_reported_not_fatal(tmp_path):
    """One corrupt document must not stop the archive being checked."""
    build_sample_spec_docx(str(tmp_path / "fine.docx"), revision="01")
    (tmp_path / "broken.docx").write_bytes(b"not a docx at all")

    result = audit_folder(str(tmp_path)).to_dict()

    assert result["checked"] == 2
    assert len(result["unreadable"]) == 1
    assert result["unreadable"][0]["path"].endswith("broken.docx")


def test_findings_are_ordered_worst_first(tmp_path):
    """A spec that can't say what revision it is matters more than one with
    a cosmetic blank row."""
    blank = str(tmp_path / "blank.docx")
    silent = str(tmp_path / "silent.docx")
    build_sample_spec_docx(blank, spec_number="SW0100", revision="01")
    build_sample_spec_docx(silent, spec_number="SW0200", revision="")

    doc, table = _history(blank)
    table.add_row()
    doc.save(blank)

    kinds = [f["kind"] for f in audit_folder(str(tmp_path)).to_dict()["findings"]]
    assert kinds.index("stated_missing") < kinds.index("trailing_blank")


def test_a_spec_renumbered_down_to_01_is_told_what_was_already_issued(tmp_path):
    """A spec the old build renumbered reads as *consistent* -- both places
    say "01" -- so no mismatch fires. The out-of-sequence finding is then
    the only thing that can tell whoever fixes it that 4 was already
    issued, and that the next revision should be 5."""
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="01")

    doc, table = _history(path)
    table.rows[1].cells[0].text = "4"
    row = table.add_row()
    row.cells[0].text = "01"
    doc.save(path)

    findings = check_spec(parse_document(path))
    assert not any(f.kind == "mismatch" for f in findings), "the two sources do agree"
    out = next(f for f in findings if f.kind == "out_of_sequence")
    assert out.continues_from == "4", out.continues_from
