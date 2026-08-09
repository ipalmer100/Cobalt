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
    """A section's table as extracted from the document, plus its shape.

    A spec can legitimately carry more than one table for the same section
    -- Franklin, OH writes specs covering two process paths, so FR0282 has
    both a "Process Routing - Duplex" and a "Process Routing - Triplex"
    table. ``variant`` holds whatever qualified the heading ("Duplex"),
    empty when the heading was just the plain section name. ``table_index``
    is what actually identifies the table for writes, since section name
    alone is no longer unique within a document.
    """

    section: str
    table_index: int  # position within doc.tables, or -1 if it's a header table
    location: str  # "body" or "header"
    shape: TableShape
    header_row: list[str] | None  # only set for RECORDS shape
    rows: list[list[str]]  # raw grid, as read from the table cells
    variant: str = ""  # e.g. "Duplex"; "" when the heading had no qualifier
    heading: str = ""  # the heading text as written in the document
    # Which physical row holds the column names. Usually 0, but some tables
    # open with a merged banner row (FR0282's duplex Process Routing starts
    # with a "Comments:" band), and reading that as the header leaves every
    # column unmapped and the rows blank in the grid.
    header_index: int = 0

    def records(self) -> list[dict[str, str]]:
        """For RECORDS shape: one dict per data row, keyed by header text."""
        if self.shape != TableShape.RECORDS or not self.header_row:
            return []
        out = []
        for row in self.rows[self.header_index + 1:]:
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
class UnclassifiedTable:
    """A table whose heading the parser could not confidently map onto one
    of the 11 canonical sections. Rather than guessing (and silently filing
    real data under the wrong section), these are surfaced in the exception
    queue for a human to allocate."""

    heading: str
    table_index: int
    shape: TableShape
    header_row: list[str] | None
    row_count: int
    preview: list[list[str]]  # first few rows, for deciding where it belongs

    def to_dict(self) -> dict:
        return {
            "heading": self.heading,
            "table_index": self.table_index,
            "shape": self.shape.value,
            "header_row": self.header_row,
            "row_count": self.row_count,
            "preview": self.preview,
        }


@dataclass
class Spec:
    """A single parsed spec document.

    ``tables`` maps each canonical section to *every* table found for it,
    in document order -- normally a one-element list, but two or more when
    a spec covers multiple process paths (see ParsedTable.variant).
    """

    file_path: str
    spec_number: str
    customer: str
    revision_number: str
    tables: dict[str, list[ParsedTable]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    unclassified: list[UnclassifiedTable] = field(default_factory=list)

    def primary(self, section: str) -> ParsedTable | None:
        """The first table for a section -- the right one for anything that
        is per-spec rather than per-table (Revision #, Product Description
        fields, "does this spec have a BOM at all")."""
        tables = self.tables.get(section)
        return tables[0] if tables else None

    def all_tables(self) -> list[ParsedTable]:
        return [t for tables in self.tables.values() for t in tables]

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "spec_number": self.spec_number,
            "customer": self.customer,
            "revision_number": self.revision_number,
            "sections": {
                name: [
                    {
                        "shape": t.shape.value,
                        "location": t.location,
                        "header_row": t.header_row,
                        "rows": t.rows,
                        "fields": t.fields() if t.shape == TableShape.FIELDS else None,
                        "variant": t.variant,
                        "heading": t.heading,
                        "table_index": t.table_index,
                    }
                    for t in tables
                ]
                for name, tables in self.tables.items()
            },
            "warnings": self.warnings,
            "unclassified": [u.to_dict() for u in self.unclassified],
        }
