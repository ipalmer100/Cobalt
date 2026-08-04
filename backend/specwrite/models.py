"""Data model for a parsed spec document.

A spec's 11 sections come in two physical shapes inside the .docx:

- ``records``: a header row of column names followed by N data rows
  (Bill of Materials, Secondary Approved Materials, Process Routing,
  Physical Attributes & Testing, Revision History).
- ``fields``: a grid of repeating ``Label:`` / value cell pairs, one
  logical record per spec (Locations, Product Description, Slitting
  Information, Packing Information, Reporting Requirements, Customer
  Sampling Requirements).

Both shapes flatten cleanly onto the same tabular projection the mass-edit
view wants: one row per spec, columns named after the section's fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TableShape(str, Enum):
    RECORDS = "records"
    FIELDS = "fields"


@dataclass
class CellRef:
    """Address of a single cell inside a specific table in a specific document."""

    row: int
    col: int


@dataclass
class ParsedTable:
    """A section's table as extracted from the document, plus its shape."""

    section: str
    table_index: int  # position within doc.tables, or -1 if it's a header table
    location: str  # "body" or "header"
    shape: TableShape
    header_row: list[str] | None  # only set for RECORDS shape
    rows: list[list[str]]  # raw grid, as read from the table cells

    def records(self) -> list[dict[str, str]]:
        """For RECORDS shape: one dict per data row, keyed by header text."""
        if self.shape != TableShape.RECORDS or not self.header_row:
            return []
        out = []
        for row in self.rows[1:]:
            out.append(
                {
                    self.header_row[i]: row[i]
                    for i in range(min(len(self.header_row), len(row)))
                }
            )
        return out

    def fields(self) -> dict[str, str]:
        """For FIELDS shape: label -> value, deduplicated across the grid
        (a label repeated because of a vertically-merged cell collapses to
        one entry)."""
        if self.shape != TableShape.FIELDS:
            return {}
        out: dict[str, str] = {}
        for row in self.rows:
            i = 0
            while i < len(row):
                label = row[i].strip()
                if label.endswith(":"):
                    value = row[i + 1].strip() if i + 1 < len(row) else ""
                    out[label.rstrip(":").strip()] = value
                    i += 2
                else:
                    i += 1
        return out


@dataclass
class Spec:
    """A single parsed spec document."""

    file_path: str
    spec_number: str
    customer: str
    revision_number: str
    tables: dict[str, ParsedTable] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "spec_number": self.spec_number,
            "customer": self.customer,
            "revision_number": self.revision_number,
            "sections": {
                name: {
                    "shape": t.shape.value,
                    "location": t.location,
                    "header_row": t.header_row,
                    "rows": t.rows,
                    "fields": t.fields() if t.shape == TableShape.FIELDS else None,
                }
                for name, t in self.tables.items()
            },
            "warnings": self.warnings,
        }
