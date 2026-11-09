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

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKAGING = REPO / "packaging"
INSTALLER = REPO / "install_cobalt.bat"
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

BATCH_SCRIPTS = {
    "build_windows_exe.bat": PACKAGING / "build_windows_exe.bat",
    "run_cobalt.bat": PACKAGING / "run_cobalt.bat",
    "create_shortcut.bat": PACKAGING / "create_shortcut.bat",
    # At the repo root rather than in packaging/, because it is the one
    # file a user downloads on its own and it has to be the first thing
    # visible on the GitHub page.
    "install_cobalt.bat": INSTALLER,
}


def _lines(name):
    return BATCH_SCRIPTS[name].read_text().splitlines()


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


# --- The browser-only installer ------------------------------------------
# install_cobalt.bat is the one file a user downloads by itself, from a
# GitHub page, and double-clicks. Nothing around it can be assumed: no
# clone, no repo, no terminal, and no second chance to read an error
# message that scrolled past before the window closed.


def test_the_installer_downloads_the_repository_it_lives_in():
    """A hardcoded owner/repo in a file people download and keep is the one
    thing in it that silently rots -- it would quietly install someone
    else's project, or nothing at all."""
    text = INSTALLER.read_text()
    assert "ipalmer100/Cobalt" in text
    assert "codeload.github.com" in text, "needs a direct zip URL, not a git clone"
    assert "git clone" not in text, "the whole point is that Git is not required"


def test_the_installer_builds_the_environment_the_launcher_expects():
    """It sets up what run_cobalt.bat then starts. If the two disagree about
    where the virtualenv lives, the install finishes and the shortcut fails
    -- the worst order for those two events."""
    installer = INSTALLER.read_text()
    launcher = (PACKAGING / "run_cobalt.bat").read_text()
    build = (PACKAGING / "build_windows_exe.bat").read_text()

    assert "packaging\\.build-venv" in installer
    assert "packaging\\.build-venv" in launcher
    # Same stamp file the build writes, so a venv made by either is
    # recognised (and rebuilt if the folder moved) by the other.
    assert ".built-at" in installer and ".built-at" in build
    # And the frontend run_cobalt.bat refuses to start without.
    assert "npm run build" in installer


def test_the_installer_does_not_claim_to_build_the_exe():
    """The packaged executable is still built by build_windows_exe.bat on a
    Windows machine. Someone who ran this and expected an .exe would go
    looking for one that was never made."""
    text = INSTALLER.read_text()
    assert "build_windows_exe.bat" in text, "it has to say where the exe comes from"
    assert "pyinstaller" not in text.lower()


@pytest.mark.parametrize("marker", ["exit /b 1", "goto :end"])
def test_every_way_out_of_the_installer_waits_for_the_user(marker):
    """Double-clicked from Explorer, the console window closes the instant
    the script ends. Without a pause before each exit the user sees a window
    flash and nothing else -- including on every failure path, which are the
    ones that have something to say."""
    lines = [line.strip().lower() for line in _lines("install_cobalt.bat")]
    for index, line in enumerate(lines):
        if line != marker:
            continue
        earlier = [l for l in lines[:index] if l and not l.startswith("rem ")]
        assert earlier and earlier[-1] == "pause", (
            f"'{marker}' at line {index + 1} is not preceded by a pause; "
            f"the line above it is {earlier[-1] if earlier else '(nothing)'!r}"
        )


def test_the_installer_checks_prerequisites_before_downloading():
    """Forty megabytes and a four-minute npm install are a long way to go to
    find out Python is missing."""
    lines = [line.strip().lower() for line in _lines("install_cobalt.bat")]
    first_check = min(i for i, line in enumerate(lines) if line.startswith("where py "))
    first_download = min(i for i, line in enumerate(lines) if "codeload.github.com" in line)
    assert first_check < first_download


def test_the_installer_keeps_a_bundled_libreoffice_across_updates():
    """Not in the download, 400 MB, and put there by hand so .doc
    conversion works on a machine with nothing installed. An update that
    deletes it costs someone an afternoon they already spent."""
    text = INSTALLER.read_text()
    assert "packaging\\libreoffice" in text
    assert "KEEP_LO" in text


def test_the_installer_looks_for_the_folder_github_actually_produces():
    """A codeload zip unpacks to <repo>-<branch>, so the folder the script
    then moves into place is derived from the same two values as the URL.
    Verified by hand against the real download: the zip's single top-level
    folder is Cobalt-main. Spelling it out anywhere else means a rename
    breaks the install after the download rather than before it."""
    text = INSTALLER.read_text()
    assert 'set "REPO=ipalmer100/Cobalt"' in text
    assert 'set "BRANCH=main"' in text
    repo_name = "ipalmer100/Cobalt".split("/")[1]
    assert f'set "SRC=%WORK%\\{repo_name}-%BRANCH%"' in text


# --- Publishing the built app --------------------------------------------


def test_the_build_leaves_one_file_ready_to_attach_to_a_release():
    """A GitHub release takes files, not folders, and the exe does not run
    moved out of its folder on its own. "Zip the whole folder" was an
    instruction that had to be followed correctly every time by someone with
    no way to tell they had got it wrong, so the build does it."""
    build = (PACKAGING / "build_windows_exe.bat").read_text()
    assert "Cobalt-windows.zip" in build
    # The folder, not the exe: unzipping has to produce the arrangement
    # that runs.
    assert "--format zip Cobalt" in build
    # And the zip is checked, because a writer that produced the wrong
    # format still exits 0.
    assert ":verify_zip" in build and "ZipFile" in build


def test_the_release_asset_name_carries_no_version():
    """releases/latest/download/<name> only resolves if <name> is the same
    on every release. A version in the filename means every link already
    sent out points at an old release forever."""
    build = (PACKAGING / "build_windows_exe.bat").read_text()
    import re

    for name in re.findall(r"Cobalt[\w.-]*\.zip", build):
        assert not re.search(r"\d+\.\d+", name), f"{name} pins a version into the asset name"


def test_the_built_app_cannot_be_committed_by_accident():
    """57 MB of binary per release, and Git keeps every version forever.
    Ignored rather than merely discouraged -- which also means `git add
    packaging/dist` appears to work and silently does nothing, so the
    reason is written down where someone confused by that will find it."""
    ignore = (REPO / ".gitignore").read_text()
    assert "packaging/dist/" in ignore
    assert "packaging/build/" in ignore
    # Read as one line: Markdown wraps, so a phrase being checked for can
    # fall across a line break and still be present to a reader.
    guide = " ".join((REPO / "RELEASING.md").read_text().split())
    assert "silently does nothing" in guide, "the surprising part has to be explained"


def test_the_release_guide_covers_both_assets_and_signing():
    """The two files serve different people, and a release missing either
    one breaks a link that has already been emailed."""
    guide = " ".join((REPO / "RELEASING.md").read_text().split())
    for asset in ("Cobalt-windows.zip", "install_cobalt.bat"):
        assert asset in guide
        assert f"releases/latest/download/{asset}" in guide
    # Signing is a certificate decision, not a code change, and the
    # certificate belongs to the company rather than to a person.
    assert "COBALT_SIGN_THUMBPRINT" in guide
    assert "not to a person" in guide
