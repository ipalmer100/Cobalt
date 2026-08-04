import threading
import time

from specwrite.docx_writer import apply_revision
from specwrite.vault import Vault

from .fixtures.builder import build_sample_spec_docx


def test_open_indexes_existing_files(tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"), spec_number="SW0001")
    build_sample_spec_docx(str(tmp_path / "spec2.docx"), spec_number="SW0002")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        entries = {e.spec.spec_number: e for e in vault.entries() if e.spec}
        assert set(entries) == {"SW0001", "SW0002"}
    finally:
        vault.close()


def test_legacy_doc_is_flagged_unsupported(tmp_path):
    (tmp_path / "old_spec.doc").write_bytes(b"not a real doc file")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        entries = vault.entries()
        assert len(entries) == 1
        assert entries[0].supported is False
        assert "doc" in entries[0].error.lower()
    finally:
        vault.close()


def test_lock_files_are_ignored(tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))
    (tmp_path / "~$spec1.docx").write_bytes(b"word lock file")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        assert len(vault.entries()) == 1
    finally:
        vault.close()


def test_external_edit_triggers_live_refresh(tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, revision="01")

    vault = Vault(str(tmp_path))
    changed = threading.Event()
    vault.subscribe(lambda p: changed.set())

    try:
        vault.open()
        assert vault.get(path).spec.revision_number == "01"

        apply_revision(path, who="External Editor", revision_text="Edited outside the app.")

        assert changed.wait(timeout=5), "vault did not notice the external file change in time"
        # debounce can coalesce multiple fs events; give the final refresh a moment to land
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            entry = vault.get(path)
            if entry.spec and entry.spec.revision_number == "02":
                break
            time.sleep(0.1)
        assert vault.get(path).spec.revision_number == "02"
    finally:
        vault.close()
