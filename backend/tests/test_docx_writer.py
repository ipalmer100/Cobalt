from docx import Document

from specwrite.docx_sections import parse_document
from specwrite.docx_writer import apply_revision, write_record_cell

from .fixtures.builder import build_sample_spec_docx


def test_write_record_cell_preserves_other_cells(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)

    spec = parse_document(path)
    bom = spec.tables["Bill of Materials"]

    doc = Document(path)
    table = doc.tables[bom.table_index]
    write_record_cell(table, 1, 2, "New Supplier LLC")
    doc.save(path)

    spec2 = parse_document(path)
    records = spec2.tables["Bill of Materials"].records()
    assert records[0]["Supplier"] == "New Supplier LLC"
    assert records[0]["Raw Material"] == "48g PET"  # untouched


def test_apply_revision_bumps_number_and_appends_row(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="06")

    new_rev = apply_revision(path, who="Isaac Palmer", revision_text="Updated supplier.")
    assert new_rev == "07"

    spec = parse_document(path)
    assert spec.revision_number == "07"

    rev_records = spec.tables["Revision History"].records()
    assert len(rev_records) == 2
    assert rev_records[-1]["Revision #"] == "07"
    assert rev_records[-1]["Who"] == "Isaac Palmer"
    assert rev_records[-1]["Revision"] == "Updated supplier."


def test_apply_revision_zero_pads_width(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path, revision="09")

    new_rev = apply_revision(path, who="Tester", revision_text="Bump.")
    assert new_rev == "10"
