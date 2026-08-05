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
READONLY_COLUMNS = ["Spec Number", "Customer", "File Path", "Material Type"]


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


def build_view(entries: list[VaultEntry], section: str) -> list[dict]:
    """Flatten every parsed spec's copy of `section` into mass-edit rows,
    each tagged with which file/row/cell it came from so a write can be
    routed back to the exact source cell."""
    rows: list[dict] = []

    for entry in entries:
        spec: Spec | None = entry.spec
        if spec is None:
            continue

        if section == "Bill of Materials":
            for material_type, source_section in (("Primary", "Bill of Materials"), ("Secondary", "Secondary Approved Materials")):
                table = spec.tables.get(source_section)
                if table is None:
                    continue
                for row_index, record in enumerate(table.records(), start=1):
                    rows.append(
                        {
                            "Spec Number": spec.spec_number,
                            "Customer": spec.customer,
                            **record,
                            "Material Type": material_type,
                            "File Path": spec.file_path,
                            "_source": {
                                "section": source_section,
                                "kind": "record",
                                "row": row_index,
                                "header_row": table.header_row,
                            },
                        }
                    )
            continue

        table = spec.tables.get(section)
        if table is None:
            continue
        kind = "record" if table.shape == TableShape.RECORDS else "field"
        for row_index, record in enumerate(_rows_for_table(table), start=(1 if table.shape == TableShape.RECORDS else 0)):
            rows.append(
                {
                    "Spec Number": spec.spec_number,
                    "Customer": spec.customer,
                    **record,
                    "File Path": spec.file_path,
                    "_source": {
                        "section": section,
                        "kind": kind,
                        "row": row_index,
                        "header_row": table.header_row,
                    },
                }
            )

    return rows
