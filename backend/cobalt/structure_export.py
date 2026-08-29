"""Export the *shape* of a spec library, with none of its content.

Cobalt's parsing bugs are shape bugs: a data row read as a header, a
merged banner that leaves every column unmapped, a section whose heading is
worded differently in one plant's template. Diagnosing those needs the
skeleton of a large, real library -- which sections exist, how each table is
laid out, which column names appear together and how often -- and none of
it needs a single cell value.

So this walks a vault and writes a report of structure only:

  * included -- section headings as written, table shapes, column and field
    labels, column and row counts, how many specs share each layout, and
    per-column fill rates and text lengths (a number, not the text)
  * excluded -- every cell value, and the file paths, which carry customer
    names and the archive's own filing structure

Paths are replaced by a short hash. A companion mapping file is written
alongside the report so a hash can be traced back to a file locally; that
mapping is the one file NOT meant to be sent anywhere.

One honest caveat, printed by the tool as well: column and field labels are
read out of the documents verbatim, and where Cobalt has mis-detected a
header the "labels" are really that spec's data. Those cases are exactly
what makes the report worth having, and they are also the one way content
can reach it -- so read the labels before sending the file on.

Usage:
    cobalt-export-structure <folder> [--out report.json] [--limit N]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .docx_sections import parse_document
from .models import ParsedTable, Spec, TableShape

REPORT_VERSION = 1


def _spec_id(root: Path, path: Path) -> str:
    """A stable, meaningless name for a spec.

    Derived from the path relative to the vault so the same spec keeps the
    same id between runs, hashed so the id itself carries no customer name,
    folder name or spec number.
    """
    rel = str(path.relative_to(root)).replace("\\", "/")
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:10]


def _is_inactive(root: Path, path: Path) -> bool:
    """Matches the app's own Active/Inactive rule, per folder segment."""
    parts = path.relative_to(root).parts[:-1]
    return any("inactive" in part.lower() for part in parts)


_PATHISH = re.compile(r"""["'`]?(?:[A-Za-z]:)?[^\s"'`]*[\\/][^\s"'`]*["'`]?""")


def _scrub(message: str) -> str:
    """Strip anything path-shaped out of an error message.

    python-docx reports a file it cannot open as "Package not found at
    '<full path>'", which would put the customer's folder tree into a report
    whose whole premise is that it holds none. The exception type and the
    shape of the message are what make it diagnosable; the path is not.
    """
    return _PATHISH.sub("<path>", message).strip()


def _labels(table: ParsedTable) -> list[str]:
    if table.shape == TableShape.RECORDS:
        return table.column_labels()
    return list(table.fields().keys())


def _data_rows(table: ParsedTable) -> list[list[str]]:
    if table.shape == TableShape.RECORDS:
        return table.rows[table.header_index + 1:]
    return table.rows


@dataclass
class ColumnStats:
    """How a column is used -- counts and lengths, never the text itself."""

    label: str
    cells: int = 0
    filled: int = 0
    max_length: int = 0
    multiline: int = 0

    def observe(self, value: str) -> None:
        self.cells += 1
        if value.strip():
            self.filled += 1
        self.max_length = max(self.max_length, len(value))
        if "\n" in value:
            self.multiline += 1

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "filled_pct": round(100 * self.filled / self.cells) if self.cells else 0,
            "max_length": self.max_length,
            "multiline_cells": self.multiline,
        }


@dataclass
class TableLayout:
    """One table's shape, as the key that groups specs together."""

    section: str
    variant: str
    location: str
    shape: str
    heading: str
    header_index: int
    labels: tuple[str, ...]

    def key(self) -> tuple:
        return (self.section, self.variant, self.location, self.shape, self.header_index, self.labels)


@dataclass
class LayoutGroup:
    """Every spec that lays its tables out identically."""

    tables: list[TableLayout]
    specs: list[str] = field(default_factory=list)
    row_counts: Counter = field(default_factory=Counter)
    stats: dict[int, dict[str, ColumnStats]] = field(default_factory=lambda: defaultdict(dict))

    def to_json(self, examples: int = 5) -> dict:
        return {
            "specs": len(self.specs),
            "example_ids": self.specs[:examples],
            "tables": [
                {
                    "section": t.section,
                    "variant": t.variant,
                    "location": t.location,
                    "shape": t.shape,
                    "heading_as_written": t.heading,
                    "header_row_index": t.header_index,
                    "column_count": len(t.labels),
                    "typical_data_rows": self.row_counts.get(i, 0),
                    "columns": [self.stats[i][label].to_json() for label in t.labels if label in self.stats[i]],
                }
                for i, t in enumerate(self.tables)
            ],
        }


# A label that reads like a value rather than a column name. Not proof of
# anything -- it is a list of things worth looking at first.
def _suspect(label: str) -> str | None:
    if len(label) > 40:
        return "unusually long for a column name"
    if label.startswith("Column "):
        return "header cell was empty"
    if label.endswith(("(2)", "(3)", "(4)", "(5)")):
        return "repeated header text across columns"
    if label.strip() in {"--", "-", "N/A", "X", ""}:
        return "placeholder text where a column name should be"
    return None


@dataclass
class StructureReport:
    root: str
    specs: int = 0
    inactive: int = 0
    legacy_doc: int = 0
    unreadable: list[dict] = field(default_factory=list)
    sections: Counter = field(default_factory=Counter)
    unclassified: Counter = field(default_factory=Counter)
    warnings: Counter = field(default_factory=Counter)
    groups: dict[tuple, LayoutGroup] = field(default_factory=dict)

    def to_json(self) -> dict:
        ordered = sorted(self.groups.values(), key=lambda g: -len(g.specs))
        suspects: dict[str, str] = {}
        for group in ordered:
            for table in group.tables:
                for label in table.labels:
                    reason = _suspect(label)
                    if reason:
                        suspects.setdefault(label, reason)
        return {
            "cobalt_structure_report": REPORT_VERSION,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "contains_cell_values": False,
            "vault": {
                "specs_analyzed": self.specs,
                "filed_as_inactive": self.inactive,
                "legacy_doc_files_skipped": self.legacy_doc,
                "unreadable": len(self.unreadable),
                "distinct_layouts": len(self.groups),
            },
            "sections_seen": dict(self.sections.most_common()),
            "unclassified_headings": dict(self.unclassified.most_common(60)),
            "warnings": dict(self.warnings.most_common(40)),
            "suspect_labels": suspects,
            "layouts": [g.to_json() for g in ordered],
            "unreadable_specs": self.unreadable,
        }


def _observe_spec(report: StructureReport, spec: Spec, spec_id: str) -> None:
    tables: list[ParsedTable] = []
    for section, parsed in spec.tables.items():
        report.sections[section] += len(parsed)
        tables.extend(parsed)
    # Sorted so two specs holding the same tables in a different reading
    # order still land in the same group.
    tables.sort(key=lambda t: (t.section, t.variant, t.location, t.table_index))

    layouts = [
        TableLayout(
            section=t.section,
            variant=t.variant,
            location=t.location,
            shape=t.shape.value,
            heading=t.heading,
            header_index=t.header_index,
            labels=tuple(_labels(t)),
        )
        for t in tables
    ]
    key = tuple(layout.key() for layout in layouts)
    group = report.groups.get(key)
    if group is None:
        group = LayoutGroup(tables=layouts)
        report.groups[key] = group
    group.specs.append(spec_id)

    for i, (table, layout) in enumerate(zip(tables, layouts)):
        rows = _data_rows(table)
        group.row_counts[i] = max(group.row_counts.get(i, 0), len(rows))
        if table.shape == TableShape.RECORDS:
            for row in rows:
                for c, label in enumerate(layout.labels):
                    stat = group.stats[i].setdefault(label, ColumnStats(label))
                    stat.observe(row[c] if c < len(row) else "")
        else:
            for label, value in table.fields().items():
                stat = group.stats[i].setdefault(label, ColumnStats(label))
                stat.observe(value)

    for warning in spec.warnings:
        report.warnings[warning] += 1
    for table in spec.unclassified:
        report.unclassified[table.heading] += 1


def export_folder(root: str, limit: int | None = None) -> tuple[StructureReport, dict[str, str]]:
    """Walk a vault and describe its shape. Returns the report and the
    id -> path mapping, which stays local."""
    base = Path(root).expanduser().resolve()
    report = StructureReport(root=str(base))
    mapping: dict[str, str] = {}

    paths = sorted(p for p in base.rglob("*") if p.suffix.lower() in {".docx", ".doc"})
    for path in paths:
        # Word's own lock files and Cobalt's in-flight saves are not specs.
        if path.name.startswith("~$") or ".cobalt-tmp" in path.name:
            continue
        if path.suffix.lower() == ".doc":
            report.legacy_doc += 1
            continue
        if limit is not None and report.specs >= limit:
            break
        spec_id = _spec_id(base, path)
        mapping[spec_id] = str(path.relative_to(base))
        try:
            spec = parse_document(str(path))
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the walk
            report.unreadable.append(
                {"spec_id": spec_id, "error": _scrub(f"{type(exc).__name__}: {exc}")}
            )
            continue
        report.specs += 1
        if _is_inactive(base, path):
            report.inactive += 1
        _observe_spec(report, spec, spec_id)

    return report, mapping


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0 if args else 2

    folder = args[0]
    out = Path("cobalt-structure.json")
    limit: int | None = None
    rest = args[1:]
    while rest:
        flag = rest.pop(0)
        if flag == "--out" and rest:
            out = Path(rest.pop(0))
        elif flag == "--limit" and rest:
            limit = int(rest.pop(0))
        else:
            print(f"unrecognised argument: {flag}\n")
            print(__doc__)
            return 2

    report, mapping = export_folder(folder, limit=limit)
    data = report.to_json()
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")

    mapping_path = out.with_name(out.stem + "-local-map.json")
    mapping_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    v = data["vault"]
    print(f"Analyzed {v['specs_analyzed']} spec(s) in {report.root}")
    print(f"  {v['distinct_layouts']} distinct layout(s)")
    print(f"  {v['filed_as_inactive']} filed as inactive")
    if v["legacy_doc_files_skipped"]:
        print(f"  {v['legacy_doc_files_skipped']} legacy .doc file(s) skipped -- open them in Cobalt once to convert")
    if v["unreadable"]:
        print(f"  {v['unreadable']} unreadable")
    if data["unclassified_headings"]:
        print(f"  {len(data['unclassified_headings'])} heading(s) Cobalt could not place")
    print()
    print(f"Report written to {out}  ({out.stat().st_size // 1024} KB) -- this is the file to send.")
    print(f"Path mapping written to {mapping_path} -- KEEP THIS ONE LOCAL; it names your files.")
    print()
    print("The report holds no cell values. It does hold column and field labels")
    print("read from the documents, and where a header was mis-detected those")
    print("'labels' are really that spec's data -- see \"suspect_labels\". Worth a")
    print("look before you send it on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
