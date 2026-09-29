"""Legacy .doc -> .docx conversion via LibreOffice headless.

python-docx (and therefore the whole parser/writer) can only read the
post-2007 .docx XML format. A spec still sitting in the old binary .doc
format shows up in the vault as unsupported (see vault.py) until it's
converted. This wraps ``soffice --headless --convert-to docx``, which
preserves tables/formatting/images far better than a plain-text
extractor — the alternative of using Word COM automation (what the org's
existing VBA does) would require Word installed and Windows, which isn't
a fit for a service that should run anywhere.

The original .doc is never deleted or overwritten by this module — the
caller decides what to do with it once the .docx conversion is verified.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class ConversionError(RuntimeError):
    pass


# Where a LibreOffice that travels with Cobalt is kept, relative to
# whichever base directory applies. Kept identical in both layouts so the
# same folder works whether the app is running as the packaged .exe or
# straight from source.
_BUNDLE_SUBDIR = ("libreoffice", "program")
_SOFFICE_NAMES = ("soffice.exe", "soffice")


def _soffice_under(base: Path) -> Path | None:
    for name in _SOFFICE_NAMES:
        candidate = base.joinpath(*_BUNDLE_SUBDIR, name)
        if candidate.is_file():
            return candidate
    return None


def _bundled_soffice_path() -> Path | None:
    """A LibreOffice that travels with Cobalt, rather than one installed.

    Checked in two places, because Cobalt is run two ways and both need to
    work on a machine with nothing installed:

    - as the packaged app, where the build copies LibreOffice inside it and
      `sys._MEIPASS` is the app's own folder (onedir) or the temp
      extraction dir (onefile);
    - from source via packaging/run_cobalt.bat, which is what a managed PC
      that refuses to run an unsigned binary is left with. This used to
      return None immediately in that case, so a bundled LibreOffice was
      invisible to exactly the people most likely to need it.

    Returns None if neither holds; soffice_path() then falls back to PATH.
    """
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        found = _soffice_under(Path(frozen_base))
        if found is not None:
            return found

    # Running from source: <repo>/packaging/libreoffice/program/soffice.exe
    # -- the same folder the build bundles from, so dropping a portable
    # LibreOffice there covers both ways of running.
    repo_root = Path(__file__).resolve().parents[2]
    return _soffice_under(repo_root / "packaging")


def soffice_path() -> str | None:
    """LibreOffice, wherever this machine keeps it.

    Order matters: an explicit override wins, then one that travels with
    Cobalt, then one installed on the machine. The override exists because
    a portable LibreOffice can legitimately live anywhere -- a shared drive,
    a USB stick, a folder IT has already allow-listed.
    """
    override = os.environ.get("COBALT_SOFFICE", "").strip()
    if override:
        candidate = Path(override)
        # Point it at either the executable or the install it lives in.
        if candidate.is_dir():
            found = _soffice_under(candidate) or _soffice_under(candidate.parent)
            return str(found) if found else None
        return str(candidate) if candidate.is_file() else None

    bundled = _bundled_soffice_path()
    if bundled is not None:
        return str(bundled)
    return shutil.which("soffice")


def soffice_available() -> bool:
    return soffice_path() is not None


def convert_doc_to_docx(doc_path: str, dest_path: str | None = None, timeout: int = 60) -> str:
    """Convert a legacy .doc file to .docx. Returns the resulting .docx path.

    ``dest_path`` defaults to the same name/directory as ``doc_path`` with
    a .docx extension. Raises ConversionError if LibreOffice isn't
    available or the conversion fails or produces no output.
    """
    soffice = soffice_path()
    if soffice is None:
        raise ConversionError("LibreOffice ('soffice') is not installed, not on PATH, and not bundled.")

    source = Path(doc_path)
    if not source.exists():
        raise ConversionError(f"Source file does not exist: {doc_path}")

    target = Path(dest_path) if dest_path else source.with_suffix(".docx")
    if target.exists():
        raise ConversionError(f"Destination already exists, refusing to overwrite: {target}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--convert-to",
                "docx:MS Word 2007 XML",
                "--outdir",
                tmp_dir,
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise ConversionError(f"soffice exited {result.returncode}: {result.stderr or result.stdout}")

        converted = Path(tmp_dir) / (source.stem + ".docx")
        if not converted.exists():
            raise ConversionError(
                f"soffice reported success but produced no output file. stdout={result.stdout!r} stderr={result.stderr!r}"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(converted, target)

    return str(target)
