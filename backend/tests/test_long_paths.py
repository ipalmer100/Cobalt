"""Paths longer than Windows will open by default.

Three specs in the division survey were reported as corrupt. They are not:
their folders are deep, the full path passes 260 characters, and Windows
refuses to open it. zipfile.is_zipfile catches the resulting OSError and
returns False, so python-docx reports "Package not found" -- which reads
as "this is not a Word file" and sent the first diagnosis the wrong way.
"""

import os
import pathlib

import pytest

from cobalt import paths
from cobalt.paths import MAX_PATH, exceeds_max_path, long_path


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: True)


def test_the_real_case_measures_over_the_limit():
    """The path that actually failed, reassembled from its parts."""
    real = "\\".join(
        [
            r"C:\Users\157619\Desktop\Specs",
            "Edinburgh Flexible Plant Documentation - Customer Specifications",
            "Hearthside Food Solution (Previously Standard Candy Company) Master Specification",
            "48g. Matte OPP - 48g. MPET - 2.0 mil LLDPE",
            "MI1119 - Hearthside Food Sol. (Stan. Candy) - W.W. 5.25 x C.O. 5.75 - Rev 3.docx",
        ]
    )
    assert exceeds_max_path(real), len(real)
    # ...while every individual name is far inside the 255-character limit
    # for a name, which is why nobody looking at it in Explorer sees it.
    assert all(len(part) < 255 for part in real.split("\\"))


def test_the_prefix_is_added_on_windows(on_windows, monkeypatch):
    monkeypatch.setattr(os.path, "abspath", lambda p: p)
    assert long_path(r"C:\Specs\deep\file.docx") == "\\\\?\\" + r"C:\Specs\deep\file.docx"


def test_a_unc_path_gets_the_unc_form(on_windows, monkeypatch):
    """\\\\server\\share takes a different prefix, and loses its leading pair."""
    monkeypatch.setattr(os.path, "abspath", lambda p: p)
    assert long_path(r"\\server\share\Specs\a.docx") == "\\\\?\\UNC\\" + r"server\share\Specs\a.docx"


def test_it_is_not_applied_twice(on_windows, monkeypatch):
    monkeypatch.setattr(os.path, "abspath", lambda p: p)
    once = long_path(r"C:\Specs\a.docx")
    assert long_path(once) == once


def test_nothing_changes_off_windows():
    """Every other platform has no such limit, and the prefix is not a
    valid path there -- applying it would break what already works."""
    assert long_path("/home/user/Specs/a.docx") == "/home/user/Specs/a.docx"


def test_a_short_path_is_prefixed_too(on_windows, monkeypatch):
    """Applied unconditionally rather than only past the limit: a path that
    is short today is long after someone renames a folder, and a prefix
    that is always there cannot be forgotten."""
    monkeypatch.setattr(os.path, "abspath", lambda p: p)
    assert long_path(r"C:\a.docx").startswith("\\\\?\\")


def test_a_long_path_round_trips_through_read_and_write(tmp_path):
    """End to end on this platform: a path well past 260 characters is
    parsed, written to, and read back."""
    from cobalt.docx_sections import parse_document
    from cobalt.docx_writer import write_field_value
    from tests.fixtures.builder import build_sample_spec_docx

    deep = tmp_path
    for part in (
        "Edinburgh Flexible Plant Documentation - Customer Specifications",
        "Hearthside Food Solution (Previously Standard Candy Company) Master Specification",
        "48g. Matte OPP - 48g. MPET - 2.0 mil LLDPE Structure Detail",
    ):
        deep = deep / part
    deep.mkdir(parents=True)
    path = deep / "MI1119 - Hearthside Food Sol. (Stan. Candy) - W.W. 5.25 x C.O. 5.75 - Rev 3.docx"
    assert len(str(path)) > MAX_PATH, len(str(path))

    build_sample_spec_docx(str(path), spec_number="MI1119")
    spec = parse_document(str(path))
    assert spec.spec_number == "MI1119"

    # ...and writing to it works too, which is the half that would corrupt
    # a document rather than merely failing to show it.
    assert write_field_value(str(path), "Product Description", "Customer", "HEARTHSIDE")
    assert parse_document(str(path)).customer == "HEARTHSIDE"


def test_the_export_counts_over_length_paths(tmp_path):
    """So a whole library can be checked at once, rather than one
    mysterious 'corrupt' file at a time."""
    import json

    from cobalt.structure_export import export_folder
    from tests.fixtures.builder import build_sample_spec_docx

    vault = tmp_path / "Specs"
    shallow = vault / "Elk Grove"
    shallow.mkdir(parents=True)
    build_sample_spec_docx(str(shallow / "EG1000.docx"))

    deep = vault / ("Edinburgh " + "x" * 90) / ("Hearthside " + "y" * 90)
    deep.mkdir(parents=True)
    build_sample_spec_docx(str(deep / ("MI1119 " + "z" * 60 + ".docx")))

    report, _ = export_folder(str(vault), by_plant=True)
    data = report.to_json()
    assert data["vault"]["paths_over_windows_limit"] == 1
    assert data["vault"]["windows_path_limit"] == MAX_PATH
    assert data["vault"]["longest_path"] > MAX_PATH

    by_name = {p["plant"]: p for p in data["plants"]}
    assert by_name["Elk Grove"]["paths_over_windows_limit"] == 0
    edinburgh = next(k for k in by_name if k.startswith("Edinburgh"))
    assert by_name[edinburgh]["paths_over_windows_limit"] == 1

    # Still no customer names: the count says how many, never which.
    assert "Hearthside" not in json.dumps(data)
