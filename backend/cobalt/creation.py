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

from .docx_sections import PRODUCT_DESCRIPTION, SPEC_NUMBER_LABELS, parse_document
from .docx_writer import append_row, clear_records, write_field_value
from .models import Spec

BLANK_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "blank_spec_template.docx"


class CreationError(RuntimeError):
    pass


def _spec_number_label(pd_fields: dict[str, str]) -> str | None:
    """Which label *this* document uses for our own spec number.

    Not every spec says "Spec #". Ones written before the Sonoco->Toppan
    rename say "Sonoco Spec #", and a post-rename spec could say "Toppan
    Spec #" -- the reader has always known that, and the writer did not.
    Writing to a hardcoded "Spec #" simply found nothing on those specs and
    reported success, so duplicating one produced a new document still
    carrying the source's spec number: a spec claiming to be another spec.
    Mirrors the reader's resolution so the two cannot disagree.
    """
    for label in SPEC_NUMBER_LABELS:
        if label in pd_fields:
            return label
    for label in pd_fields:
        lowered = label.strip().lower()
        # "Customer Spec #" is the customer's number, not ours.
        if lowered.endswith("spec #") and not lowered.startswith("customer"):
            return label
    return None


def _reset_new_spec_identity(path: str, spec_number: str, customer: str, who: str, note: str) -> None:
    today = date_cls.today().strftime("%m/%d/%Y")

    pd_fields = parse_document(path).primary(PRODUCT_DESCRIPTION).fields()
    label = _spec_number_label(pd_fields)
    if label is None:
        raise CreationError(
            "Product Description has no spec-number field, so the new spec cannot be "
            "given its own number. Add a \"Spec #:\" field to the source document first."
        )

    # Identity, not decoration: a new spec that silently kept the source's
    # number or customer is worse than one that was never created.
    for field, value in ((label, spec_number), ("Customer", customer)):
        if not write_field_value(path, PRODUCT_DESCRIPTION, field, value):
            raise CreationError(f'Could not set "{field}" on the new spec.')

    # Cosmetic by comparison -- absent on some templates, and not worth
    # refusing to create a spec over.
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
