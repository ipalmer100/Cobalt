import pytest

from specwrite.creation import CreationError, create_blank_spec, duplicate_spec
from specwrite.docx_sections import parse_document

from .fixtures.builder import build_sample_spec_docx


def test_duplicate_spec_resets_identity_and_carries_over_data(tmp_path):
    source = str(tmp_path / "source.docx")
    build_sample_spec_docx(source, spec_number="SW0001", revision="06")

    dest = str(tmp_path / "new_spec.docx")
    new_spec = duplicate_spec(source, dest, spec_number="SW0099", customer="New Customer Inc", who="Isaac")

    assert new_spec.spec_number == "SW0099"
    assert new_spec.customer == "New Customer Inc"
    assert new_spec.revision_number == "01"

    # data tables carried over as a starting point
    bom = new_spec.tables["Bill of Materials"].records()
    assert bom[0]["Raw Material"] == "48g PET"
    assert bom[0]["Supplier"] == "Flex Films"

    # revision history reset, not inherited from the source spec
    rev = new_spec.tables["Revision History"].records()
    assert len(rev) == 1
    assert rev[0]["Revision #"] == "01"
    assert rev[0]["Who"] == "Isaac"
    assert "SW0001" in rev[0]["Revision"]


def test_duplicate_spec_refuses_existing_destination(tmp_path):
    source = str(tmp_path / "source.docx")
    build_sample_spec_docx(source)
    dest = tmp_path / "new_spec.docx"
    dest.write_text("already here")

    with pytest.raises(CreationError, match="already exists"):
        duplicate_spec(source, str(dest), "SW0099", "Customer", "Isaac")


def test_duplicate_spec_missing_source_raises(tmp_path):
    with pytest.raises(CreationError, match="does not exist"):
        duplicate_spec(str(tmp_path / "nope.docx"), str(tmp_path / "dest.docx"), "SW0099", "Customer", "Isaac")


def test_create_blank_spec_from_template(tmp_path):
    dest = str(tmp_path / "brand_new.docx")
    spec = create_blank_spec(dest, spec_number="SW0100", customer="Fresh Co", who="Isaac")

    assert spec.spec_number == "SW0100"
    assert spec.customer == "Fresh Co"
    assert spec.revision_number == "01"
    assert spec.warnings == []

    rev = spec.tables["Revision History"].records()
    assert len(rev) == 1
    assert rev[0]["Revision"] == "Spec created from blank template."

    # blank template's data tables are genuinely empty (just headers)
    assert spec.tables["Bill of Materials"].records() == []


def test_create_blank_spec_refuses_existing_destination(tmp_path):
    dest = tmp_path / "brand_new.docx"
    dest.write_text("already here")

    with pytest.raises(CreationError, match="already exists"):
        create_blank_spec(str(dest), "SW0100", "Fresh Co", "Isaac")


def test_created_specs_creates_missing_parent_directories(tmp_path):
    dest = str(tmp_path / "new_customer_folder" / "spec.docx")
    spec = create_blank_spec(dest, "SW0200", "Another Co", "Isaac")
    assert spec.spec_number == "SW0200"

    reparsed = parse_document(dest)
    assert reparsed.customer == "Another Co"
