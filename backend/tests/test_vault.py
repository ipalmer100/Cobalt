import threading
import time
from pathlib import Path

import cobalt.vault as vault_mod
from cobalt.doc_conversion import ConversionError
from cobalt.docx_writer import apply_revision
from cobalt.vault import Vault

from .fixtures.builder import build_sample_spec_docx


def _wait_for(predicate, timeout=5, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


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


def test_doc_auto_converts_to_docx_in_the_background(monkeypatch, tmp_path):
    """A .doc file needs no manual action -- the vault converts it to a
    same-named .docx on its own, without blocking vault.open(), and the
    .doc itself stops being tracked once that .docx exists."""
    doc_path = tmp_path / "spec1.doc"
    doc_path.write_bytes(b"pretend legacy binary content")

    def fake_convert(source, dest=None, timeout=60):
        # a small delay so the test can observe the pending state before
        # it resolves, without depending on real LibreOffice being present
        time.sleep(0.2)
        target = dest or str(Path(source).with_suffix(".docx"))
        build_sample_spec_docx(target, spec_number="CONVERTED")
        return target

    monkeypatch.setattr(vault_mod, "convert_doc_to_docx", fake_convert)

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        # vault.open() returns without waiting on the conversion -- the .doc
        # shows a pending placeholder, not an error, right after it.
        pending = vault.get(str(doc_path))
        assert pending is not None
        assert pending.supported is False
        assert pending.error == vault_mod._CONVERTING_MESSAGE

        docx_path = str(doc_path.with_suffix(".docx"))
        assert _wait_for(lambda: vault.get(docx_path) is not None and vault.get(docx_path).spec is not None)
        converted = vault.get(docx_path)
        assert converted.spec.spec_number == "CONVERTED"

        # the original .doc is no longer tracked once its .docx exists
        assert vault.get(str(doc_path)) is None
        assert str(doc_path) not in {e.path for e in vault.entries()}
    finally:
        vault.close()


def test_doc_conversion_failure_surfaces_as_an_error_entry(monkeypatch, tmp_path):
    doc_path = tmp_path / "broken.doc"
    doc_path.write_bytes(b"garbage")

    def fake_convert(source, dest=None, timeout=60):
        raise ConversionError("soffice exploded")

    monkeypatch.setattr(vault_mod, "convert_doc_to_docx", fake_convert)

    def _no_longer_pending():
        entry = vault.get(str(doc_path))
        return entry is not None and entry.error != vault_mod._CONVERTING_MESSAGE

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        assert _wait_for(_no_longer_pending)
        entry = vault.get(str(doc_path))
        assert entry.supported is False
        assert "soffice exploded" in entry.error
    finally:
        vault.close()


def test_doc_with_existing_docx_sibling_is_never_converted_or_shown(monkeypatch, tmp_path):
    """A .doc that already has a same-named .docx (converted on a previous
    run, or just a coincidental duplicate) is treated as already handled:
    never shown, never sent through conversion again."""
    build_sample_spec_docx(str(tmp_path / "spec1.docx"), spec_number="ALREADY")
    (tmp_path / "spec1.doc").write_bytes(b"old legacy copy, ignore me")

    calls = []
    monkeypatch.setattr(vault_mod, "convert_doc_to_docx", lambda *a, **k: calls.append(a))

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        time.sleep(0.3)  # give an (incorrect) background conversion a chance to fire
        assert calls == []
        paths = {e.path for e in vault.entries()}
        assert str(tmp_path / "spec1.doc") not in paths
        assert str(tmp_path / "spec1.docx") in paths
    finally:
        vault.close()


def test_enqueue_conversion_does_not_duplicate_in_flight_paths(tmp_path):
    vault = Vault(str(tmp_path))
    vault._conversions_in_flight.add("/fake/a.doc")
    vault._enqueue_conversion("/fake/a.doc")
    assert vault._conversion_queue.qsize() == 0  # already in flight, not re-queued

    vault._enqueue_conversion("/fake/b.doc")
    assert vault._conversion_queue.qsize() == 1


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


def test_full_index_above_parallel_threshold_matches_sequential(monkeypatch, tmp_path):
    """A vault larger than _PARALLEL_INDEX_THRESHOLD is indexed across
    worker processes instead of one file at a time (see vault.py's
    _full_index_parallel) -- confirm that path actually runs (not silently
    falling back to sequential) and produces the same result a plain
    file-by-file index would, including a mix of good, bad, and legacy
    .doc files surviving the process-boundary round trip intact (the .doc
    branch of _build_entry runs the same way whether dispatched to a
    worker process or run in-process; only the actual conversion --
    handled separately by the main process's background thread, never
    inside a worker -- is mocked here)."""
    n = vault_mod._PARALLEL_INDEX_THRESHOLD + 5
    for i in range(n):
        build_sample_spec_docx(str(tmp_path / f"good{i:03d}.docx"), spec_number=f"SW{i:04d}")
    (tmp_path / "legacy.doc").write_bytes(b"pretend legacy binary content")
    (tmp_path / "corrupt.docx").write_bytes(b"not a real zip/docx at all")

    monkeypatch.setattr(
        vault_mod,
        "convert_doc_to_docx",
        lambda *a, **k: (_ for _ in ()).throw(ConversionError("no libreoffice in this test")),
    )

    def _legacy_doc_no_longer_pending():
        entry = vault.get(str(tmp_path / "legacy.doc"))
        return entry is not None and entry.error != vault_mod._CONVERTING_MESSAGE

    vault = Vault(str(tmp_path))
    try:
        vault.open()
        assert _wait_for(_legacy_doc_no_longer_pending)
        entries = {e.path.rsplit("/", 1)[-1]: e for e in vault.entries()}

        assert len(entries) == n + 2
        good_specs = {e.spec.spec_number for name, e in entries.items() if name.startswith("good")}
        assert good_specs == {f"SW{i:04d}" for i in range(n)}

        assert entries["legacy.doc"].supported is False
        assert "no libreoffice in this test" in entries["legacy.doc"].error

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
