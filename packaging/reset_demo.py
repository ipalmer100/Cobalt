"""Restore a demo folder to a known state.

Rehearsing a demo changes it. After one run-through the audit log is full of
your practice edits, the exception queue's decisions are already made, and
-- most easily missed -- any legacy ``.doc`` has already been converted, so
the auto-conversion moment cannot happen again. Run this between run-throughs
and on the morning of the pitch.

It works on a *copy*: point ``--source`` at a pristine folder of specs you
keep untouched, and ``--demo`` at the folder you actually open in Cobalt.
The source is only ever read.

    python reset_demo.py --source "C:\\Demo\\master" --demo "C:\\Demo\\live"

Add ``--list`` to see what it would do without touching anything.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SPEC_SUFFIXES = (".docx", ".doc")
STATE_DIRNAME = ".cobalt"


def _specs_under(root: Path) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in SPEC_SUFFIXES
        and not p.name.startswith(("~$", "."))
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    ]


def _converted_siblings(specs: list[Path]) -> list[Path]:
    """The .docx files Cobalt generated from a .doc.

    These have to go, or the conversion never happens again: the app treats
    "a .docx sibling already exists" as the record of "already converted".
    """
    doc_files = {p for p in specs if p.suffix.lower() == ".doc"}
    return [p.with_suffix(".docx") for p in doc_files if p.with_suffix(".docx").exists()]


def reset(source: Path, demo: Path, dry_run: bool = False) -> int:
    if not source.is_dir():
        print(f"Source folder not found: {source}", file=sys.stderr)
        return 2
    if source.resolve() == demo.resolve():
        print("Source and demo folders must be different -- the source is the pristine copy.", file=sys.stderr)
        return 2

    master = _specs_under(source)
    if not master:
        print(f"No spec files (.doc/.docx) found under {source}", file=sys.stderr)
        return 2

    print(f"Source : {source}   ({len(master)} spec files)")
    print(f"Demo   : {demo}")

    if demo.exists():
        stale = _specs_under(demo)
        generated = _converted_siblings(stale)
        state = demo / STATE_DIRNAME
        print()
        print("Will clear from the demo folder:")
        print(f"  {len(stale)} spec file(s)")
        if generated:
            print(f"  {len(generated)} .docx generated from a .doc "
                  "(so the conversion demo works again):")
            for path in generated:
                print(f"      {path.relative_to(demo)}")
        if state.exists():
            print(f"  {STATE_DIRNAME}/ (audit log + exception-queue decisions)")

    print()
    if dry_run:
        print("--list given, nothing changed.")
        return 0

    if demo.exists():
        shutil.rmtree(demo)
    demo.mkdir(parents=True)

    copied = 0
    for path in master:
        target = demo / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1

    doc_count = sum(1 for p in master if p.suffix.lower() == ".doc")
    print(f"Reset complete: {copied} spec file(s) copied.")
    if doc_count:
        print(f"  {doc_count} legacy .doc file(s) ready to auto-convert on open.")
    print("  Audit log and exception-queue decisions cleared.")
    print()
    print(f"Open this folder in Cobalt:  {demo}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore a Cobalt demo folder to a known state.",
        epilog="The source folder is only ever read from; the demo folder is replaced.",
    )
    parser.add_argument("--source", required=True, help="pristine folder of specs (read-only)")
    parser.add_argument("--demo", required=True, help="folder you open in Cobalt (replaced)")
    parser.add_argument("--list", action="store_true", dest="dry_run",
                        help="show what would change, without changing it")
    args = parser.parse_args()
    return reset(Path(args.source).expanduser(), Path(args.demo).expanduser(), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
