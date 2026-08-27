"""Creating a new spec — the Obsidian analog of "new note, blank or from
template." Two paths, both landing on the same identity reset:

- ``duplicate_spec``: copy an existing spec (its data tables carry over
  as a starting point — a new spec is often a close variant of one that
  already exists) but reset the identifying fields and start a fresh
  Revision History rather than inheriting the source spec's log.
- ``create_blank_spec``: copy the app's bundled blank template instead of
  an existing spec.

Both refuse to overwrite an existing destination file.
"""

from __future__ import annotations

import shutil
from datetime import date as date_cls
from pathlib import Path

from .docx_sections import PRODUCT_DESCRIPTION, parse_document
from .docx_writer import append_row, clear_records, write_field_value
from .models import Spec

BLANK_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "blank_spec_template.docx"


class CreationError(RuntimeError):
    pass


def _reset_new_spec_identity(path: str, spec_number: str, customer: str, who: str, note: str) -> None:
    today = date_cls.today().strftime("%m/%d/%Y")
    write_field_value(path, PRODUCT_DESCRIPTION, "Spec #", spec_number)
    write_field_value(path, PRODUCT_DESCRIPTION, "Customer", customer)
    write_field_value(path, PRODUCT_DESCRIPTION, "Date of Issue", today)
    write_field_value(path, PRODUCT_DESCRIPTION, "Revision #", "01")
    clear_records(path, "Revision History")
    append_row(path, "Revision History", ["01", who, today, note])


def duplicate_spec(source_path: str, dest_path: str, spec_number: str, customer: str, who: str) -> Spec:
    source = Path(source_path)
    dest = Path(dest_path)
    if not source.exists():
        raise CreationError(f"Source spec does not exist: {source_path}")
    if dest.exists():
        raise CreationError(f"Destination already exists: {dest_path}")

    try:
        origin = parse_document(source_path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear creation error
        raise CreationError(f"Source spec is not readable: {exc}") from exc

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source_path, dest_path)

    note = f"Spec created by duplicating {origin.spec_number or source.name}."
    _reset_new_spec_identity(dest_path, spec_number, customer, who, note)
    return parse_document(dest_path)


def create_blank_spec(dest_path: str, spec_number: str, customer: str, who: str) -> Spec:
    if not BLANK_TEMPLATE_PATH.exists():
        raise CreationError(f"Blank template not found at {BLANK_TEMPLATE_PATH}")
    dest = Path(dest_path)
    if dest.exists():
        raise CreationError(f"Destination already exists: {dest_path}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLANK_TEMPLATE_PATH, dest_path)

    _reset_new_spec_identity(dest_path, spec_number, customer, who, "Spec created from blank template.")
    return parse_document(dest_path)
