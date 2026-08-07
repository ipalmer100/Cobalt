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

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class ConversionError(RuntimeError):
    pass


def _bundled_soffice_path() -> Path | None:
    """The packaged desktop app can optionally bundle a full LibreOffice
    install under `<app>/libreoffice/` (see packaging/specwrite.spec and
    packaging/build_windows_exe.bat) so .doc conversion works with nothing
    else installed on the machine running the app. `sys._MEIPASS` is the
    right base dir for this in both PyInstaller layouts: the temp
    extraction dir in onefile mode, or the app's own folder in onedir
    mode. Absent when running from source or when the build didn't bundle
    LibreOffice -- soffice_path() falls back to PATH in that case."""
    frozen_base = getattr(sys, "_MEIPASS", None)
    if not frozen_base:
        return None
    for name in ("soffice.exe", "soffice"):
        candidate = Path(frozen_base) / "libreoffice" / "program" / name
        if candidate.is_file():
            return candidate
    return None


def soffice_path() -> str | None:
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
