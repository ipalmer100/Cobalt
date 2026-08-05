import time

from docx import Document

from specwrite.docx_sections import parse_document
from specwrite.docx_writer import apply_revision, write_cell, write_edits_batch, write_record_cell

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


def test_write_edits_batch_applies_multiple_record_edits_in_one_file(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)

    write_edits_batch(
        [
            {"path": path, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "Supplier A"},
            {"path": path, "section": "Secondary Approved Materials", "kind": "record", "row": 1, "col": 2, "value": "Supplier B"},
        ]
    )

    spec = parse_document(path)
    assert spec.tables["Bill of Materials"].records()[0]["Supplier"] == "Supplier A"
    assert spec.tables["Secondary Approved Materials"].records()[0]["Supplier"] == "Supplier B"


def test_write_edits_batch_applies_field_edits(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)

    write_edits_batch(
        [{"path": path, "section": "Locations", "kind": "field", "label": "Facility", "value": "New Plant"}]
    )

    spec = parse_document(path)
    assert spec.tables["Locations"].fields()["Facility"] == "New Plant"


def test_write_edits_batch_spans_multiple_files(tmp_path):
    path_a = str(tmp_path / "a.docx")
    path_b = str(tmp_path / "b.docx")
    build_sample_spec_docx(path_a, spec_number="SW0001")
    build_sample_spec_docx(path_b, spec_number="SW0002")

    write_edits_batch(
        [
            {"path": path_a, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "X"},
            {"path": path_b, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "Y"},
        ]
    )

    assert parse_document(path_a).tables["Bill of Materials"].records()[0]["Supplier"] == "X"
    assert parse_document(path_b).tables["Bill of Materials"].records()[0]["Supplier"] == "Y"


def test_write_edits_batch_is_faster_than_sequential_single_writes(tmp_path):
    """The whole point of batching: one open+save per file, not per cell."""
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)
    n = 20

    t0 = time.perf_counter()
    for i in range(n):
        write_cell(path, "Bill of Materials", 1, 2, f"Sequential {i}")
    sequential_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    write_edits_batch(
        [{"path": path, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": f"Batched {i}"} for i in range(n)]
    )
    batch_time = time.perf_counter() - t0

    assert batch_time < sequential_time / 2
