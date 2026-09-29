"""Finding LibreOffice, which decides whether legacy .doc files convert.

Only .doc files need it; a library that is entirely .docx needs nothing.
But where Cobalt looks matters for a handoff to another plant, because the
answer used to depend on *how* Cobalt was started: the packaged .exe could
carry LibreOffice inside it, and running from source could not see that
copy at all -- which is exactly the situation on a managed PC that refuses
to run an unsigned binary.
"""

import os
import pathlib

import pytest

from cobalt import doc_conversion

REPO = pathlib.Path(doc_conversion.__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_ambient_override(monkeypatch):
    monkeypatch.delenv("COBALT_SOFFICE", raising=False)


def _make_install(base: pathlib.Path, name: str = "soffice.exe") -> pathlib.Path:
    program = base / "libreoffice" / "program"
    program.mkdir(parents=True, exist_ok=True)
    executable = program / name
    executable.write_text("")
    return executable


def test_a_copy_in_the_packaging_folder_is_found_when_running_from_source(tmp_path, monkeypatch):
    """The gap this closes. run_cobalt.bat is what a locked-down machine is
    left with, and a bundled LibreOffice used to be invisible to it."""
    monkeypatch.delattr(doc_conversion.sys, "_MEIPASS", raising=False)
    fake_repo = tmp_path / "Cobalt"
    executable = _make_install(fake_repo / "packaging")

    monkeypatch.setattr(
        doc_conversion, "__file__", str(fake_repo / "backend" / "cobalt" / "doc_conversion.py")
    )
    assert doc_conversion._bundled_soffice_path() == executable


def test_the_packaged_app_still_finds_its_own_copy(tmp_path, monkeypatch):
    executable = _make_install(tmp_path)
    monkeypatch.setattr(doc_conversion.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert doc_conversion._bundled_soffice_path() == executable


def test_both_layouts_look_in_the_same_place_within_their_base():
    """One folder name, so the same portable copy serves the exe and the
    source run. If these drifted apart, bundling would work for one and
    silently not the other."""
    assert doc_conversion._BUNDLE_SUBDIR == ("libreoffice", "program")


def test_an_explicit_override_wins(tmp_path, monkeypatch):
    """A portable copy can live on a shared drive, or in a folder IT has
    already allow-listed."""
    elsewhere = tmp_path / "tools" / "soffice.exe"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("")
    monkeypatch.setenv("COBALT_SOFFICE", str(elsewhere))
    assert doc_conversion.soffice_path() == str(elsewhere)


def test_the_override_accepts_the_install_folder_too(tmp_path, monkeypatch):
    executable = _make_install(tmp_path)
    monkeypatch.setenv("COBALT_SOFFICE", str(tmp_path / "libreoffice"))
    assert doc_conversion.soffice_path() == str(executable)


def test_an_override_pointing_at_nothing_does_not_silently_fall_back(tmp_path, monkeypatch):
    """Naming a path that isn't there is a mistake worth surfacing, not
    papering over with whatever happens to be on PATH."""
    monkeypatch.setenv("COBALT_SOFFICE", str(tmp_path / "missing" / "soffice.exe"))
    assert doc_conversion.soffice_path() is None


def test_falls_back_to_an_installed_copy(monkeypatch):
    monkeypatch.delattr(doc_conversion.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(doc_conversion, "_bundled_soffice_path", lambda: None)
    monkeypatch.setattr(doc_conversion.shutil, "which", lambda name: "/usr/bin/soffice")
    assert doc_conversion.soffice_path() == "/usr/bin/soffice"


def test_nothing_anywhere_reports_nothing(monkeypatch):
    monkeypatch.setattr(doc_conversion, "_bundled_soffice_path", lambda: None)
    monkeypatch.setattr(doc_conversion.shutil, "which", lambda name: None)
    assert doc_conversion.soffice_path() is None
    assert not doc_conversion.soffice_available()


def test_the_real_repo_has_no_bundled_copy_committed():
    """Several hundred MB of third-party binaries do not belong in git --
    .gitignore keeps them out, and this notices if that ever stops working."""
    assert not (REPO / "packaging" / "libreoffice").exists() or (
        "packaging/libreoffice/" in (REPO / ".gitignore").read_text()
    )


def test_the_folder_local_copy_is_the_one_actually_run(tmp_path, monkeypatch):
    """Resolving the path is only half of it -- this runs a conversion and
    checks the binary that got executed was the one in the folder, not
    whatever happens to be installed."""
    monkeypatch.delattr(doc_conversion.sys, "_MEIPASS", raising=False)

    fake_repo = tmp_path / "Cobalt"
    program = fake_repo / "packaging" / "libreoffice" / "program"
    program.mkdir(parents=True)
    receipt = tmp_path / "it-ran.txt"

    # Stands in for soffice: records that it was called, and produces the
    # .docx in the --outdir it was given, the way the real one does.
    stub = program / "soffice"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" > "{receipt}"\n'
        'while [ "$1" != "--outdir" ]; do shift; done\n'
        'outdir="$2"; src="$3"\n'
        'base=$(basename "$src" .doc)\n'
        'cp "$src" "$outdir/$base.docx"\n'
    )
    stub.chmod(0o755)

    monkeypatch.setattr(
        doc_conversion, "__file__", str(fake_repo / "backend" / "cobalt" / "doc_conversion.py")
    )
    # Nothing installed on this machine, which is the whole scenario.
    monkeypatch.setattr(doc_conversion.shutil, "which", lambda name: None)

    legacy = tmp_path / "EG1166.doc"
    legacy.write_bytes(b"pretend legacy document")

    produced = doc_conversion.convert_doc_to_docx(str(legacy))

    assert pathlib.Path(produced) == legacy.with_suffix(".docx")
    assert pathlib.Path(produced).read_bytes() == b"pretend legacy document"
    assert receipt.exists(), "the bundled soffice was never executed"
    assert "--headless" in receipt.read_text()
