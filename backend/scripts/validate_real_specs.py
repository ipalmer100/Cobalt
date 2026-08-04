"""Manual validation harness: parse and round-trip real spec files.

Not part of the automated test suite (real specs are customer data and
must never be committed to the repo — see .gitignore). Run by hand against
local copies:

    python scripts/validate_real_specs.py /path/to/spec1.docx /path/to/spec2.docx ...
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specwrite.docx_sections import ALL_SECTIONS, parse_document
from specwrite.docx_writer import apply_revision
from specwrite.models import TableShape


def validate(path: str) -> None:
    print(f"\n{'=' * 70}\n{path}\n{'=' * 70}")
    spec = parse_document(path)

    print(f"Spec #: {spec.spec_number!r}  Customer: {spec.customer!r}  Rev: {spec.revision_number!r}")
    if spec.warnings:
        print(f"WARNINGS: {spec.warnings}")

    for name in ALL_SECTIONS:
        table = spec.tables.get(name)
        if table is None:
            print(f"  [MISSING] {name}")
            continue
        if table.shape == TableShape.RECORDS:
            n = len(table.records())
            print(f"  [{table.location:6}] {name:32} records={n:3} cols={table.header_row}")
        else:
            fields = table.fields()
            print(f"  [{table.location:6}] {name:32} fields={list(fields.keys())}")

    # Round-trip the writer against a scratch copy — never touch the original.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = str(Path(tmp) / Path(path).name)
        shutil.copy(path, scratch)
        try:
            new_rev = apply_revision(scratch, who="Validation Script", revision_text="Round-trip test.")
            reparsed = parse_document(scratch)
            ok = reparsed.revision_number == new_rev
            print(f"  ROUND-TRIP apply_revision: {spec.revision_number} -> {new_rev}  (verified: {ok})")
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic script
            print(f"  ROUND-TRIP FAILED: {exc!r}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        validate(p)
