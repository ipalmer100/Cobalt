"""The handoff guide names commands, paths and files.

Someone at another plant follows this literally, with no way to tell a
stale instruction from a real problem. These check that everything it
names still exists.
"""

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
GUIDE = (REPO / "HANDOFF.md").read_text()


def test_the_scripts_it_tells_you_to_run_exist():
    for script in ["packaging\\build_windows_exe.bat"]:
        assert script in GUIDE
        assert (REPO / script.replace("\\", "/")).is_file()


@pytest.mark.parametrize(
    "module", ["cobalt.structure_export", "cobalt.revision_audit"]
)
def test_the_command_line_tools_it_names_are_importable(module):
    import importlib

    assert f"python -m {module}" in GUIDE
    assert hasattr(importlib.import_module(module), "main")


def test_the_build_output_folder_is_named_correctly():
    """dist, not build -- the exe in build\\ does not run, and that has
    already cost a day once."""
    assert "packaging\\dist\\Cobalt" in GUIDE
    assert "Not `packaging\\build\\`" in GUIDE


def test_the_state_folder_it_names_matches_the_code():
    from cobalt.section_mappings import MAPPINGS_DIRNAME, MAPPINGS_FILENAME

    assert f"{MAPPINGS_DIRNAME}\\{MAPPINGS_FILENAME}" in GUIDE


def test_the_bundled_libreoffice_path_matches_the_code():
    from cobalt.doc_conversion import _BUNDLE_SUBDIR

    assert "packaging\\" + "\\".join(_BUNDLE_SUBDIR) + "\\soffice.exe" in GUIDE


def test_the_signing_variable_matches_the_build_script():
    build = (REPO / "packaging" / "build_windows_exe.bat").read_text()
    names = set(re.findall(r"COBALT_SIGN_\w+", GUIDE))
    assert names, "the guide should tell you how to sign"
    for name in names:
        assert name in build, f"{name} is not something the build reads"


def test_the_structure_report_fields_it_tells_you_to_read_are_real():
    """It tells the reader to look at three fields by name."""
    from cobalt.structure_export import StructureReport

    report = StructureReport(root="/x").to_json()
    assert "unreadable" in report["vault"]
    assert "legacy_doc_files_skipped" in report["vault"]
    assert "unclassified_headings" in report
    for field in ["unreadable", "legacy_doc_files_skipped", "unclassified_headings"]:
        assert field in GUIDE


def test_the_local_map_filename_matches_what_the_export_writes():
    """The guide says to keep plant-local-map.json back. If the export ever
    names it differently, the reader would send the file that lists their
    own file paths."""
    out = pathlib.Path("plant.json")
    expected = out.with_name(out.stem + "-local-map.json").name
    assert expected in GUIDE


def test_it_does_not_recommend_run_cobalt_bat_as_a_handoff():
    """It exists so the author can keep working on a locked-down machine.
    Sent to a plant it needs Git, Node and Python and a build first."""
    assert "not a distribution mechanism" in GUIDE.lower() or "Not a handoff" in GUIDE
