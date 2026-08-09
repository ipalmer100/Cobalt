"""Multiple tables per section (Franklin's two-process-path specs) and the
exception queue that catches everything the classifier won't guess at."""

from docx import Document

from specwrite.docx_sections import IGNORE, classify_heading, parse_document
from specwrite.section_mappings import load_mappings, save_mapping
from specwrite.views import build_view
from specwrite.vault import VaultEntry


def _doc_with(path: str, blocks: list[tuple[str, list[list[str]]]]):
    doc = Document()
    for heading, rows in blocks:
        doc.add_paragraph(heading)
        table = doc.add_table(rows=len(rows), cols=len(rows[0]))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                table.cell(r, c).text = text
    doc.save(path)


ROUTING_DUPLEX = [["Pass", "Process", "Machine"], ["1", "Print", "Rotomec"]]
ROUTING_TRIPLEX = [["Pass", "Process", "Machine"], ["1", "Laminate", "Triplex"]]


def test_classify_recognizes_qualified_variants():
    assert classify_heading("Process Routing - Duplex") == ("Process Routing", "Duplex")
    assert classify_heading("Physical Attributes & Testing - Triplex") == (
        "Physical Attributes & Testing",
        "Triplex",
    )
    assert classify_heading("Slitting Information - IMS Dairy Product") == (
        "Slitting Information",
        "IMS Dairy Product",
    )


def test_classify_escalates_rather_than_guessing():
    """Anything that isn't clearly one of the 11 must go to a human, not get
    filed somewhere plausible-looking."""
    for heading in ["Press Specification", "Quality Issues", "S3 Machine Conditions"]:
        assert classify_heading(heading) == (None, ""), heading


def test_spec_keeps_every_table_for_a_section(tmp_path):
    path = str(tmp_path / "two_paths.docx")
    _doc_with(path, [("Process Routing - Duplex", ROUTING_DUPLEX),
                     ("Process Routing - Triplex", ROUTING_TRIPLEX)])

    tables = parse_document(path).tables["Process Routing"]
    assert [t.variant for t in tables] == ["Duplex", "Triplex"]
    # distinct physical tables -- this is what lets a write target one of them
    assert tables[0].table_index != tables[1].table_index


def test_view_merges_variants_into_the_one_section(tmp_path):
    path = str(tmp_path / "two_paths.docx")
    _doc_with(path, [("Process Routing - Duplex", ROUTING_DUPLEX),
                     ("Process Routing - Triplex", ROUTING_TRIPLEX)])
    spec = parse_document(path)
    entry = VaultEntry(path=path, spec=spec, error=None, supported=True)

    rows = build_view([entry], "Process Routing")

    assert [r["Variant"] for r in rows] == ["Duplex", "Triplex"]
    assert [r["Process"] for r in rows] == ["Print", "Laminate"]
    # Same row number in each table -- only table_index tells them apart, so
    # without it an edit to one would land in the other.
    assert rows[0]["_source"]["row"] == rows[1]["_source"]["row"]
    assert rows[0]["_source"]["table_index"] != rows[1]["_source"]["table_index"]


def test_variant_column_absent_when_nothing_has_one(tmp_path):
    path = str(tmp_path / "single.docx")
    _doc_with(path, [("Process Routing", ROUTING_DUPLEX)])
    spec = parse_document(path)
    rows = build_view([VaultEntry(path=path, spec=spec, error=None, supported=True)], "Process Routing")
    assert "Variant" not in rows[0]


def test_unrecognized_table_goes_to_the_exception_queue(tmp_path):
    path = str(tmp_path / "odd.docx")
    _doc_with(path, [("Press Specification", [["Speed", "Units"], ["650", "ft/min"]])])

    spec = parse_document(path)

    assert [u.heading for u in spec.unclassified] == ["Press Specification"]
    assert spec.unclassified[0].row_count == 2
    assert spec.unclassified[0].preview[0] == ["Speed", "Units"]


def test_assigned_heading_lands_in_its_section(tmp_path):
    """A decision recorded in the queue reclassifies the table on reparse."""
    path = str(tmp_path / "odd.docx")
    _doc_with(path, [("Press Specification", [["Pass", "Process", "Machine"], ["1", "Print", "P15"]])])

    save_mapping(str(tmp_path), "Press Specification", "Process Routing", who="tester")
    overrides = {k: m.section for k, m in load_mappings(str(tmp_path)).items()}
    spec = parse_document(path, overrides)

    assert spec.unclassified == []
    assert [t.heading for t in spec.tables["Process Routing"]] == ["Press Specification"]


def test_ignored_heading_disappears_from_the_queue(tmp_path):
    path = str(tmp_path / "odd.docx")
    _doc_with(path, [("Quality Issues", [["Issue", "Action"], ["x", "y"]])])

    save_mapping(str(tmp_path), "Quality Issues", IGNORE, who="tester")
    overrides = {k: m.section for k, m in load_mappings(str(tmp_path)).items()}
    spec = parse_document(path, overrides)

    assert spec.unclassified == []
    assert "Quality Issues" not in spec.tables


def test_banner_row_above_the_header_is_not_mistaken_for_it(tmp_path):
    """FR0282's duplex Process Routing opens with a merged "Comments:" band.
    Reading that as the header leaves every column unmapped and the rows
    blank in the grid."""
    path = str(tmp_path / "banner.docx")
    # Shaped like the real one: the merged band only fills the cells it
    # spans, leaving the rest of the row empty.
    _doc_with(path, [("Process Routing", [
        ["Comments:", "Comments:", "", "", ""],
        ["Pass", "Process", "Machine", "Process Conditions", "Comments"],
        ["1", "Print", "Rotomec", "TL-014", "12 hr cure"],
    ])])

    table = parse_document(path).primary("Process Routing")
    assert table.header_index == 1
    assert table.header_row == ["Pass", "Process", "Machine", "Process Conditions", "Comments"]
    assert table.records() == [
        {
            "Pass": "1",
            "Process": "Print",
            "Machine": "Rotomec",
            "Process Conditions": "TL-014",
            "Comments": "12 hr cure",
        }
    ]
