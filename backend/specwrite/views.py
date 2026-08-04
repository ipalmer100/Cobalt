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

# Columns that are metadata/derived, not a real cell in the source table —
# the frontend renders these read-only rather than trying to write them back.
READONLY_COLUMNS = ["Spec Number", "Customer", "File Path", "Material Type"]


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
