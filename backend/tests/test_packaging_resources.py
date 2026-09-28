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


def test_the_no_exe_launcher_points_at_the_same_entry_point():
    """run_cobalt.bat is the fallback for a machine that refuses to run a
    freshly-built unsigned binary. It has to start the same application the
    exe does, or it is a second thing to keep working."""
    launcher = (PACKAGING / "run_cobalt.bat").read_text()
    spec = (PACKAGING / "cobalt.spec").read_text()
    assert "cobalt.desktop" in launcher
    assert "cobalt/desktop.py" in spec.replace("\\", "/") or "desktop" in spec

    # It must check its prerequisites rather than failing obscurely: the
    # build venv it runs from, and the built frontend it serves.
    assert ".build-venv" in launcher
    assert "frontend\\dist" in launcher

    # And it must not quietly imply this is a way around the control.
    assert "stopgap" in launcher.lower()


# --- The Windows batch scripts -------------------------------------------
# None of these can be executed on this platform, and a broken one costs
# whoever runs it an afternoon. These check the two things that actually go
# wrong when editing batch: a jump with no label to land on, and a block
# that falls through into the error handler below it because its `goto` was
# lost. The second is not hypothetical -- an edit to the signing step landed
# the "signing failed" message in the middle of the success path, so a
# successful build would have printed an error and a failed one would have
# jumped to the wrong handler.

BATCH_SCRIPTS = ["build_windows_exe.bat", "run_cobalt.bat", "create_shortcut.bat"]


def _lines(name):
    return (PACKAGING / name).read_text().splitlines()


@pytest.mark.parametrize("script", BATCH_SCRIPTS)
def test_every_jump_has_a_label_to_land_on(script):
    import re

    lines = _lines(script)
    labels = {line.strip()[1:].lower() for line in lines if line.strip().startswith(":") and " " not in line.strip()}
    for number, line in enumerate(lines, start=1):
        for target in re.findall(r"goto\s+:?(\w+)", line, flags=re.IGNORECASE):
            if target.lower() == "eof":
                continue
            assert target.lower() in labels, f"{script}:{number} jumps to :{target}, which does not exist"


@pytest.mark.parametrize("script", BATCH_SCRIPTS)
def test_no_block_falls_through_into_an_error_handler(script):
    """A label named :error_* must only be reached deliberately. If the
    statement above one isn't a jump or an exit, the path above runs
    straight into it."""
    lines = [line.strip() for line in _lines(script)]
    for index, line in enumerate(lines):
        if not (line.lower().startswith(":error") and " " not in line):
            continue
        previous = next(
            (
                earlier
                for earlier in reversed(lines[:index])
                if earlier and not earlier.lower().startswith("rem ")
            ),
            "",
        )
        assert previous.lower().startswith(("goto ", "exit ")), (
            f"{script}: {line} can be fallen into -- the line above it is {previous!r}"
        )


def test_error_handlers_stay_below_the_success_path():
    """The check that would actually have caught it.

    Editing this script by matching on "error_pyinstaller" hit the `goto`
    that jumps to the handler rather than the handler itself, which spliced
    an error message into the middle of the success path and left the real
    handler with an empty body. A successful build would have announced a
    failure, and a failed one would have jumped to the wrong handler.

    Both the fall-through rule above and the every-jump-has-a-label rule
    pass on that damage, because the label still existed and was still
    preceded by an `exit`. What it does violate is layout: handlers belong
    below the last `goto :end`, and that one had moved above it.
    """
    lines = _lines("build_windows_exe.bat")
    last_success = max(i for i, line in enumerate(lines) if line.strip().lower() == "goto :end")
    stray = [
        f"line {i + 1}: {line.strip()}"
        for i, line in enumerate(lines)
        if line.strip().lower().startswith(":error") and " " not in line.strip() and i < last_success
    ]
    assert not stray, "error handlers spliced into the success path: " + "; ".join(stray)


def test_the_build_can_sign_but_does_not_require_it():
    """Signing is what makes the exe runnable on a managed machine, but a
    build with no certificate available still has to produce a working app."""
    build = (PACKAGING / "build_windows_exe.bat").read_text()
    assert "COBALT_SIGN_THUMBPRINT" in build
    assert "goto :unsigned" in build, "an unset thumbprint must skip signing, not fail"
    # Timestamped, or every signed copy stops verifying the day the
    # certificate expires.
    assert "/tr " in build and "/td " in build
