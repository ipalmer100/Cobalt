from specwrite.docx_sections import ALL_SECTIONS, parse_document
from specwrite.models import TableShape

from .fixtures.builder import build_sample_spec_docx


def test_parses_all_sections(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)

    spec = parse_document(path)

    assert spec.spec_number == "SW0001"
    assert spec.customer == "ACME Corp"
    assert spec.revision_number == "01"
    assert spec.warnings == []
    assert set(spec.tables) == set(ALL_SECTIONS)


def test_records_shape_for_bom(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)
    spec = parse_document(path)

    bom = spec.tables["Bill of Materials"]
    assert bom.shape == TableShape.RECORDS
    assert bom.header_row == ["Caliper (mils)", "Raw Material", "Supplier", "Designation", "Part Number"]
    records = bom.records()
    assert len(records) == 1
    assert records[0]["Raw Material"] == "48g PET"
    assert records[0]["Supplier"] == "Flex Films"


def test_fields_shape_for_locations(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)
    spec = parse_document(path)

    locations = spec.tables["Locations"]
    assert locations.shape == TableShape.FIELDS
    fields = locations.fields()
    assert fields["Customer Location"] == "Test Customer"
    assert fields["Facility"] == "Test Plant"


def test_product_description_from_header_with_merged_cell(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)
    spec = parse_document(path)

    pd = spec.tables["Product Description"]
    assert pd.location == "header"
    fields = pd.fields()
    assert fields["Spec #"] == "SW0001"
    assert fields["Revision #"] == "01"
    assert fields["Structure Code"] == "TC-001"
    # merged "Structure Description" label collapses to one entry, not two
    assert fields["Structure Description"] == "48g PET / Ink / Adh / 2.0 mil PE"


def test_revision_history_records(tmp_path):
    path = str(tmp_path / "spec.docx")
    build_sample_spec_docx(path)
    spec = parse_document(path)

    rev = spec.tables["Revision History"]
    assert rev.shape == TableShape.RECORDS
    records = rev.records()
    assert records[0]["Revision #"] == "01"
    assert records[0]["Revision"] == "Spec created."
