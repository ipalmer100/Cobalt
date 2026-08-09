"""Tabular mass-edit projections: one view per table name, flattening
every spec in the vault into ``Spec Number | Customer | <columns> | File
Path`` rows — the shape from the Bill of Materials Excel example,
generalized to all 11 sections.

Bill of Materials is a special case: the sample workbook (and the existing
VBA extractor) union it with Secondary Approved Materials into one sheet,
distinguished by a "Material Type" column, rather than showing two
separate views for what the business treats as one editable list.
"""

from __future__ import annotations

from .docx_sections import BODY_SECTIONS, PRODUCT_DESCRIPTION
from .models import ParsedTable, Spec, TableShape
from .vault import VaultEntry

VIEW_NAMES = [PRODUCT_DESCRIPTION, *[s for s in BODY_SECTIONS if s != "Secondary Approved Materials"]]

REVISION_HISTORY = "Revision History"
REVISION_NUMBER_FIELD = "Revision #"

# Columns that are metadata/derived, not a real cell in the source table —
# the frontend renders these read-only rather than trying to write them back.
# "Variant" names which of a spec's several same-section tables a row came
# from ("Duplex"/"Triplex"); it's the heading, not a cell, so it isn't
# editable here.
READONLY_COLUMNS = ["Spec Number", "Customer", "File Path", "Material Type", "Variant"]

VARIANT_COLUMN = "Variant"


def is_view_editable(section: str) -> bool:
    """Revision History is the audit trail: it only ever changes as one
    atomic unit (a new row + Product Description's Revision # bumping
    together) via apply_revision(). Editing it cell-by-cell in the mass
    grid could desync the two, or let someone quietly rewrite audit
    history — so the whole view is read-only here, same rule enforced
    server-side in the write endpoints."""
    return section != REVISION_HISTORY


def readonly_columns_for(section: str) -> list[str]:
    """Per-view column locks, layered on top of READONLY_COLUMNS.
    Revision # is locked specifically in Product Description because it
    must only ever move in lockstep with a new Revision History row —
    letting it be edited freely here is exactly what would let table 1
    and table 11 drift apart."""
    if section == PRODUCT_DESCRIPTION:
        return [*READONLY_COLUMNS, REVISION_NUMBER_FIELD]
    return READONLY_COLUMNS


def _rows_for_table(table: ParsedTable) -> list[dict[str, str]]:
    if table.shape == TableShape.RECORDS:
        return table.records()
    fields = table.fields()
    return [fields] if fields else []


def _emit(spec: Spec, table: ParsedTable, section: str, extra: dict | None = None) -> list[dict]:
    """One mass-edit row per record (or one row for a FIELDS table), tagged
    with the exact file/table/row it came from so a write routes back to
    that cell and no other -- table_index matters because a spec can hold
    several tables for the same section."""
    kind = "record" if table.shape == TableShape.RECORDS else "field"
    # Data begins after the header row, which isn't always row 0 (a table
    # can open with a merged banner) -- and _source.row is a physical row
    # address the writer uses, so it has to account for that offset.
    start = table.header_index + 1 if table.shape == TableShape.RECORDS else 0
    out = []
    for row_index, record in enumerate(_rows_for_table(table), start=start):
        out.append(
            {
                "Spec Number": spec.spec_number,
                "Customer": spec.customer,
                **record,
                **(extra or {}),
                VARIANT_COLUMN: table.variant,
                "File Path": spec.file_path,
                "_source": {
                    "section": section,
                    "kind": kind,
                    "row": row_index,
                    "header_row": table.header_row,
                    "table_index": table.table_index,
                    "variant": table.variant,
                },
            }
        )
    return out


def build_view(entries: list[VaultEntry], section: str) -> list[dict]:
    """Flatten every parsed spec's copy of `section` into mass-edit rows.

    A spec may contribute several tables to one section (Franklin writes
    specs covering two process paths, so Process Routing shows the Duplex
    rows and the Triplex rows together, told apart by the Variant column).
    The view list itself stays the fixed set of canonical sections.
    """
    rows: list[dict] = []

    for entry in entries:
        spec: Spec | None = entry.spec
        if spec is None:
            continue

        if section == "Bill of Materials":
            for material_type, source_section in (("Primary", "Bill of Materials"), ("Secondary", "Secondary Approved Materials")):
                for table in spec.tables.get(source_section, []):
                    rows.extend(_emit(spec, table, source_section, {"Material Type": material_type}))
            continue

        for table in spec.tables.get(section, []):
            rows.extend(_emit(spec, table, section))

    # Only surface the Variant column when something in this view actually
    # has one -- most sections are single-table everywhere and an always-
    # blank column is just noise.
    if not any(row.get(VARIANT_COLUMN) for row in rows):
        for row in rows:
            row.pop(VARIANT_COLUMN, None)

    return rows
