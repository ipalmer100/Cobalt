"""Write-side: address-based cell writes, generalized from wrdRevision.bas.

The existing VBA tools write two ways: most of them do a blind Word
``Find/Replace`` scoped to a table's range (fragile — breaks if the same
text appears twice, and can't target "this specific cell" independent of
its current value). Only the revision-history macro writes by cell address
(``tbl.Cell(r, c).Range.Text = value``). This module generalizes that
address-based approach to every table, and preserves the target cell's
existing run formatting (font, color, bold) instead of resetting it to a
default run — a docx analog of editing one field of a markdown frontmatter
block without touching the rest of the file.
"""

from __future__ import annotations

import re
from datetime import date as date_cls

from docx import Document
from docx.table import Table, _Cell

from .docx_sections import PRODUCT_DESCRIPTION, extract_product_description, find_body_section_tables
from .models import ParsedTable


def set_cell_text(cell: _Cell, value: str) -> None:
    """Set a cell's text while preserving the formatting of its first run."""
    paragraphs = cell.paragraphs
    if not paragraphs:
        cell.text = value
        return

    first = paragraphs[0]
    if first.runs:
        first.runs[0].text = value
        for extra_run in first.runs[1:]:
            extra_run._element.getparent().remove(extra_run._element)
    else:
        first.text = value

    for extra_para in paragraphs[1:]:
        extra_para._element.getparent().remove(extra_para._element)


def write_record_cell(table: Table, row: int, col: int, value: str) -> None:
    """Write a single cell by (row, col) address — the mass-edit grid's
    primary write primitive. Merge-safe: python-docx's ``table.cell()``
    already resolves a merged span's grid position to its origin cell."""
    set_cell_text(table.cell(row, col), value)


def write_field(table: Table, label: str, value: str) -> bool:
    """Find a ``Label:`` cell (case-insensitive, colon optional in the
    argument) in a FIELDS-shape table and set the value cell that follows
    it in the same row. Returns False if the label wasn't found."""
    target = label.strip().rstrip(":").strip().lower()
    for row in table.rows:
        cells = row.cells
        for i, cell in enumerate(cells):
            text = cell.text.strip()
            if text.rstrip(":").strip().lower() == target and text.endswith(":"):
                if i + 1 < len(cells):
                    set_cell_text(cells[i + 1], value)
                    return True
    return False


def add_record_row(table: Table, values: list[str]) -> None:
    """Append a data row to a RECORDS-shape table, copying run formatting
    from the previous last row so the new row doesn't fall back to Word's
    bare default style."""
    template_row = table.rows[-1] if len(table.rows) > 1 else None
    new_row = table.add_row()
    for i, cell in enumerate(new_row.cells):
        if i < len(values):
            if template_row is not None and i < len(template_row.cells):
                _copy_run_format(template_row.cells[i], cell)
            set_cell_text(cell, values[i])


def _copy_run_format(source_cell: _Cell, target_cell: _Cell) -> None:
    source_runs = source_cell.paragraphs[0].runs if source_cell.paragraphs else []
    if not source_runs or not target_cell.paragraphs:
        return
    source_rpr = source_runs[0]._element.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr")
    if source_rpr is None:
        return
    target_para = target_cell.paragraphs[0]
    if not target_para.runs:
        target_para.add_run("")
    target_run_element = target_para.runs[0]._element
    existing_rpr = target_run_element.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr")
    if existing_rpr is not None:
        target_run_element.remove(existing_rpr)
    import copy

    target_run_element.insert(0, copy.deepcopy(source_rpr))


_TRAILING_DIGITS = re.compile(r"(\d+)$")


def _next_revision_number(previous: str) -> str:
    """Increment a revision number string, preserving its zero-padded
    width (e.g. "06" -> "07", "9" -> "10", "" -> "01")."""
    match = _TRAILING_DIGITS.search(previous.strip())
    if not match:
        return "01"
    digits = match.group(1)
    incremented = str(int(digits) + 1)
    if len(incremented) < len(digits):
        incremented = incremented.zfill(len(digits))
    return incremented


def _resolve_table(doc: Document, section: str) -> Table:
    """Locate a section's table in an already-open Document, the same way
    the parser does, so writes target exactly what the reader last showed."""
    if section == PRODUCT_DESCRIPTION:
        parsed = extract_product_description(doc)
        if parsed.location == "missing":
            raise ValueError(f"{PRODUCT_DESCRIPTION} table not found")
        return doc.sections[0].header.tables[0] if parsed.location == "header" else doc.tables[parsed.table_index]

    body_tables = find_body_section_tables(doc)
    parsed = body_tables.get(section)
    if parsed is None:
        raise ValueError(f"Section not found: {section}")
    return doc.tables[parsed.table_index]


def write_cell(path: str, section: str, row: int, col: int, value: str) -> None:
    """Open a spec, write one cell by address in the named section, save.
    The mass-edit grid's primary write path."""
    doc = Document(path)
    table = _resolve_table(doc, section)
    write_record_cell(table, row, col, value)
    doc.save(path)


def write_field_value(path: str, section: str, label: str, value: str) -> bool:
    """Open a spec, write one ``Label:`` field's value in the named section, save."""
    doc = Document(path)
    table = _resolve_table(doc, section)
    found = write_field(table, label, value)
    if found:
        doc.save(path)
    return found


def append_row(path: str, section: str, values: list[str]) -> None:
    """Open a spec, append a data row to a RECORDS-shape section, save."""
    doc = Document(path)
    table = _resolve_table(doc, section)
    add_record_row(table, values)
    doc.save(path)


def apply_revision(path: str, who: str, revision_text: str, revision_date: date_cls | None = None) -> str:
    """Append a Revision History row and bump the Revision # in Product
    Description. Returns the new revision number. Generalizes
    wrdRevision.bas's ``tbl.Rows.Add`` + header cell-address write."""
    doc = Document(path)
    body_tables = find_body_section_tables(doc)
    rev_table_parsed = body_tables.get("Revision History")
    if rev_table_parsed is None:
        raise ValueError("Revision History section not found")

    rev_table = doc.tables[rev_table_parsed.table_index]
    last_row_values = [c.text.strip() for c in rev_table.rows[-1].cells]
    previous_rev = last_row_values[0] if last_row_values else ""
    new_rev = _next_revision_number(previous_rev)
    rev_date = (revision_date or date_cls.today()).strftime("%m/%d/%Y")

    add_record_row(rev_table, [new_rev, who, rev_date, revision_text])

    pd_parsed: ParsedTable = extract_product_description(doc)
    if pd_parsed.location != "missing":
        source = doc.sections[0].header.tables[0] if pd_parsed.location == "header" else doc.tables[pd_parsed.table_index]
        write_field(source, "Revision #", new_rev)

    doc.save(path)
    return new_rev
