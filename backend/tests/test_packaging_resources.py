"""The Windows resources compiled into Cobalt.exe.

Neither can be exercised by a build on this platform, and both fail the
Windows build if malformed -- an afternoon lost to a typo nobody can see.
So they are checked structurally here instead: the manifest as XML, and the
version resource against PyInstaller's own constructor signatures.
"""

import ast
import pathlib
import xml.dom.minidom

import pytest

PACKAGING = pathlib.Path(__file__).resolve().parents[2] / "packaging"
MANIFEST = PACKAGING / "cobalt.manifest"
VERSION_INFO = PACKAGING / "version_info.txt"


def test_the_manifest_is_well_formed_xml():
    """A double hyphen inside an XML comment is illegal and silently makes
    the whole manifest unparseable. It has bitten this project once already,
    in the app icon."""
    xml.dom.minidom.parse(str(MANIFEST))


def test_the_manifest_asks_for_no_elevation():
    """The whole reason it exists: stop Windows guessing that an unsigned
    binary might be an installer and demanding an admin password."""
    doc = xml.dom.minidom.parse(str(MANIFEST))
    level = doc.getElementsByTagName("requestedExecutionLevel")[0]
    assert level.getAttribute("level") == "asInvoker"
    assert level.getAttribute("uiAccess") == "false"


def test_the_version_resource_matches_pyinstallers_signatures():
    """PyInstaller's versioninfo module can't be imported off Windows, so
    its source is read and our file checked against the real constructors."""
    import PyInstaller.utils.win32 as w32

    source = pathlib.Path(w32.__file__).parent.joinpath("versioninfo.py").read_text()
    signatures = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    names = {a.arg for a in item.args.args if a.arg != "self"}
                    names |= {a.arg for a in item.args.kwonlyargs}
                    signatures[node.name] = (names, item.args.kwarg is not None)

    tree = ast.parse(VERSION_INFO.read_text())
    expression = next(n for n in tree.body if isinstance(n, ast.Expr))
    for call in (n for n in ast.walk(expression) if isinstance(n, ast.Call)):
        name = getattr(call.func, "id", None)
        if name is None:
            continue
        assert name in signatures, f"{name} is not a PyInstaller version-resource class"
        allowed, takes_kwargs = signatures[name]
        for keyword in call.keywords:
            if keyword.arg and not takes_kwargs:
                assert keyword.arg in allowed, f"{name}() has no parameter {keyword.arg!r}"


def test_the_spec_file_wires_both_resources_in():
    spec = (PACKAGING / "cobalt.spec").read_text()
    assert "cobalt.manifest" in spec
    assert "version_info.txt" in spec


@pytest.mark.parametrize("field", ["CompanyName", "FileDescription", "ProductName", "OriginalFilename"])
def test_the_version_resource_names_a_publisher(field):
    """An executable with no publisher information is the worst case for
    Windows' reputation checks, and leaves IT nothing to write an allow-list
    rule against."""
    assert field in VERSION_INFO.read_text()
