from cobalt.vault import Vault
from cobalt.views import build_view

from .fixtures.builder import build_sample_spec_docx


def test_bill_of_materials_view_unions_primary_and_secondary(tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"), spec_number="SW0001")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        rows = build_view(vault.entries(), "Bill of Materials")
    finally:
        vault.close()

    assert len(rows) == 2
    by_type = {r["Material Type"]: r for r in rows}
    assert by_type["Primary"]["Supplier"] == "Flex Films"
    assert by_type["Secondary"]["Supplier"] == "Terphane"
    for row in rows:
        assert row["Spec Number"] == "SW0001"
        assert row["File Path"].endswith("spec1.docx")


def test_fields_shape_view_is_one_row_per_spec(tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"), spec_number="SW0001")
    build_sample_spec_docx(str(tmp_path / "spec2.docx"), spec_number="SW0002")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        rows = build_view(vault.entries(), "Locations")
    finally:
        vault.close()

    assert len(rows) == 2
    spec_numbers = {r["Spec Number"] for r in rows}
    assert spec_numbers == {"SW0001", "SW0002"}
    assert all(r["Facility"] == "Test Plant" for r in rows)
