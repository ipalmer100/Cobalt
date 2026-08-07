import threading
import time

import specwrite.vault as vault_mod
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


def test_full_index_above_parallel_threshold_matches_sequential(tmp_path):
    """A vault larger than _PARALLEL_INDEX_THRESHOLD is indexed across
    worker processes instead of one file at a time (see vault.py's
    _full_index_parallel) -- confirm that path actually runs (not silently
    falling back to sequential) and produces the same result a plain
    file-by-file index would, including a mix of good, bad, and legacy
    .doc files surviving the process-boundary round trip intact."""
    n = vault_mod._PARALLEL_INDEX_THRESHOLD + 5
    for i in range(n):
        build_sample_spec_docx(str(tmp_path / f"good{i:03d}.docx"), spec_number=f"SW{i:04d}")
    (tmp_path / "legacy.doc").write_bytes(b"pretend legacy binary content")
    (tmp_path / "corrupt.docx").write_bytes(b"not a real zip/docx at all")

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        entries = {e.path.rsplit("/", 1)[-1]: e for e in vault.entries()}

        assert len(entries) == n + 2
        good_specs = {e.spec.spec_number for name, e in entries.items() if name.startswith("good")}
        assert good_specs == {f"SW{i:04d}" for i in range(n)}

        assert entries["legacy.doc"].supported is False
        assert "doc" in entries["legacy.doc"].error.lower()

        assert entries["corrupt.docx"].supported is False
        assert entries["corrupt.docx"].error  # some parse error surfaced, not a crash
    finally:
        vault.close()


def test_debounce_burst_does_not_spawn_a_thread_per_event(tmp_path):
    """A bulk drop of many files into an already-open vault (a migration,
    a network-drive resync) used to spawn a brand-new OS thread per
    debounced file-change event -- confirm a burst of thousands of events
    for distinct paths is handled by the fixed scheduler + worker-pool
    threads instead of the thread count scaling with the burst size."""
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))
    vault = Vault(str(tmp_path))
    try:
        vault.open()
        before = threading.active_count()

        for i in range(3000):
            vault._schedule_refresh(f"/fake/path/{i}.docx")

        after_burst = threading.active_count()
        # a handful of fixed threads (scheduler + worker pool), not one per event
        assert after_burst - before < 20, f"thread count grew by {after_burst - before} for a 3000-event burst"

        # the scheduler drains its debounce map over time rather than
        # leaking the (path -> fire_at) entries forever
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and vault._pending:
            time.sleep(0.1)
        assert vault._pending == {}
    finally:
        vault.close()


def test_parallel_index_below_threshold_stays_sequential(monkeypatch, tmp_path):
    """Below the threshold, spinning up a whole process pool would cost
    more than it saves -- confirm the small-vault path really does stay
    sequential rather than always paying pool-startup overhead."""
    called = []
    monkeypatch.setattr(
        vault_mod.Vault,
        "_full_index_parallel",
        lambda self, paths: called.append(paths),
    )
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        assert called == []  # the parallel path was never invoked
        assert len(vault.entries()) == 1
    finally:
        vault.close()
