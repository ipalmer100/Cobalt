"""Flag specs whose revision numbering doesn't hold together.

A spec states its revision in two places that must agree: the Revision #
field in Product Description, and the last row of its Revision History
table. When they drift, the document no longer establishes which version it
is -- which is the one thing the revision history is for.

Two ways they drift:

- An earlier version of this app derived the next revision number from the
  last row of Revision History without checking whether that row carried a
  number. A spec whose table ends in a blank row (somebody pressed Tab once
  too often) was therefore revised from 4 to "01", and the stated revision
  and the history parted company. Specs revised by that build need finding.
- Editing in Word, by hand, for years before any of this existed.

Report only. Renumbering a regulated document is a decision for the person
who owns the spec, not something to do silently on their behalf -- so every
finding carries what each source says and what the numbering would continue
from, and stops there.

Also runnable directly against a folder, for checking an archive without
opening the app:

    python -m cobalt.revision_audit "C:\\path\\to\\specs"
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .docx_sections import parse_document
from .models import Spec

REVISION_HISTORY = "Revision History"

_TRAILING_DIGITS = re.compile(r"(\d+)$")

# Ordered worst-first: a spec that can't say what revision it is matters
# more than one with a cosmetic blank row.
SEVERITY = {
    "stated_missing": 0,
    "history_missing": 1,
    "mismatch": 2,
    "out_of_sequence": 3,
    "trailing_blank": 4,
}


@dataclass
class Finding:
    path: str
    spec_number: str
    kind: str
    detail: str
    stated: str = ""
    history_last: str = ""
    continues_from: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "spec_number": self.spec_number,
            "kind": self.kind,
            "detail": self.detail,
            "stated": self.stated,
            "history_last": self.history_last,
            "continues_from": self.continues_from,
        }


@dataclass
class AuditResult:
    checked: int = 0
    unreadable: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "clean": self.checked - len({f.path for f in self.findings}),
            "unreadable": self.unreadable,
            "findings": [f.to_dict() for f in self.findings],
        }


def numeric(value: str) -> int:
    """The trailing integer in a revision string, or -1 if there isn't one.
    Matches how the writer reads revision numbers, so what this reports and
    what a save would do can't disagree."""
    match = _TRAILING_DIGITS.search((value or "").strip())
    return int(match.group(1)) if match else -1


def check_spec(spec: Spec) -> list[Finding]:
    """Every revision-numbering problem in one spec."""
    findings: list[Finding] = []
    path = spec.file_path
    number = spec.spec_number or Path(path).stem
    stated = (spec.revision_number or "").strip()

    tables = spec.tables.get(REVISION_HISTORY) or []
    if not tables:
        findings.append(
            Finding(path, number, "history_missing", "No Revision History table found.", stated=stated)
        )
        return findings

    history = tables[0]
    data_rows = history.rows[history.header_index + 1 :]
    numbered = [(i, r[0].strip()) for i, r in enumerate(data_rows) if r and numeric(r[0]) >= 0]

    if not stated:
        findings.append(
            Finding(
                path,
                number,
                "stated_missing",
                "Product Description has no Revision # value, so the spec doesn't state its own revision.",
                history_last=numbered[-1][1] if numbered else "",
            )
        )

    if not numbered:
        findings.append(
            Finding(
                path,
                number,
                "history_missing",
                "Revision History has no rows carrying a revision number.",
                stated=stated,
            )
        )
        return findings

    history_last = numbered[-1][1]

    # The condition that caused the bad renumbering: a wholly blank final
    # row, which the old writer read as the previous revision.
    if data_rows and all(not cell.strip() for cell in data_rows[-1]):
        findings.append(
            Finding(
                path,
                number,
                "trailing_blank",
                "Revision History ends in a wholly blank row.",
                stated=stated,
                history_last=history_last,
            )
        )

    # The highest number the spec has ever carried, wherever it appears. A
    # spec renumbered down to "01" reads as consistent -- both places say
    # "01" -- so no mismatch fires, and this is the only thing that tells
    # whoever fixes it that 4 was already issued.
    highest = max([*[v for _, v in numbered], stated], key=numeric)

    # Numbers that go backwards or repeat: the signature of a spec already
    # damaged by the old behaviour, or of two people revising in parallel.
    previous_value, previous_row = None, None
    for row_index, value in numbered:
        current = numeric(value)
        if previous_value is not None and current <= previous_value:
            findings.append(
                Finding(
                    path,
                    number,
                    "out_of_sequence",
                    f'Revision History row {row_index + 1} is "{value}" after "{previous_row}" — '
                    f"the numbering {'repeats' if current == previous_value else 'goes backwards'}.",
                    stated=stated,
                    history_last=history_last,
                    continues_from=highest,
                )
            )
        previous_value, previous_row = current, value

    if stated and numeric(stated) != numeric(history_last):
        findings.append(
            Finding(
                path,
                number,
                "mismatch",
                f'Product Description says revision "{stated}" but the last Revision History '
                f'row says "{history_last}".',
                stated=stated,
                history_last=history_last,
                continues_from=highest,
            )
        )

    return findings


def audit_specs(specs: list[Spec]) -> AuditResult:
    result = AuditResult(checked=len(specs))
    for spec in specs:
        result.findings.extend(check_spec(spec))
    result.findings.sort(key=lambda f: (SEVERITY.get(f.kind, 99), f.spec_number, f.path))
    return result


def audit_folder(root: str) -> AuditResult:
    """Walk a folder of .docx specs and check each one. Used by the CLI;
    the app audits its already-parsed vault instead of re-reading it."""
    result = AuditResult()
    for path in sorted(Path(root).rglob("*.docx")):
        if path.name.startswith(("~$", ".")):
            continue
        result.checked += 1
        try:
            spec = parse_document(str(path))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            result.unreadable.append({"path": str(path), "error": str(exc)})
            continue
        result.findings.extend(check_spec(spec))
    result.findings.sort(key=lambda f: (SEVERITY.get(f.kind, 99), f.spec_number, f.path))
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__)
        return 2
    result = audit_folder(args[0])

    for entry in result.unreadable:
        print(f"UNREADABLE  {entry['path']}\n            {entry['error']}")

    for finding in result.findings:
        print(f"{finding.kind.upper():<16} {finding.spec_number:<10} {Path(finding.path).name}")
        print(f"                 {finding.detail}")
        if finding.continues_from:
            print(f"                 Next revision would continue from \"{finding.continues_from}\".")

    print()
    print(f"checked {result.checked} spec(s); {len({f.path for f in result.findings})} with findings", end="")
    print(f"; {len(result.unreadable)} unreadable" if result.unreadable else "")
    return 1 if (result.findings or result.unreadable) else 0


if __name__ == "__main__":
    raise SystemExit(main())
