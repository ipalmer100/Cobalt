"""The storage layer that lets the same spec logic run against a local
folder or a SharePoint library."""

import time

import pytest

from cobalt.docx_sections import parse_bytes
from cobalt.storage import ConflictError, LocalStore, StoreError

from .fixtures.builder import build_sample_spec_docx


def test_lists_specs_including_subfolders(tmp_path):
    """A SharePoint library is foldered by customer, so one root has to cover
    the whole tree."""
    (tmp_path / "Atkinson Candy").mkdir()
    (tmp_path / "Daisy" / "Pouches").mkdir(parents=True)
    build_sample_spec_docx(str(tmp_path / "root.docx"))
    build_sample_spec_docx(str(tmp_path / "Atkinson Candy" / "a.docx"))
    build_sample_spec_docx(str(tmp_path / "Daisy" / "Pouches" / "b.docx"))

    items = sorted(LocalStore(str(tmp_path)).list_specs(), key=lambda i: i.display_path)

    assert [i.display_path for i in items] == [
        "Atkinson Candy/a.docx",
        "Daisy/Pouches/b.docx",
        "root.docx",
    ]


def test_skips_lock_files_and_dotfolders(tmp_path):
    build_sample_spec_docx(str(tmp_path / "real.docx"))
    (tmp_path / "~$real.docx").write_bytes(b"word lock file")
    (tmp_path / ".cobalt").mkdir()
    build_sample_spec_docx(str(tmp_path / ".cobalt" / "hidden.docx"))
    (tmp_path / "notes.txt").write_text("not a spec")

    names = [i.name for i in LocalStore(str(tmp_path)).list_specs()]

    assert names == ["real.docx"]


def test_read_write_round_trip_through_bytes(tmp_path):
    """The store only ever moves bytes -- no path reaches the parser."""
    build_sample_spec_docx(str(tmp_path / "spec.docx"))
    store = LocalStore(str(tmp_path))
    item = next(iter(store.list_specs()))

    data, etag = store.read(item.key)
    assert parse_bytes(item.key, data).spec_number == "SW0001"
    assert etag

    new_etag = store.write(item.key, data, etag)
    assert new_etag  # a write produces a fresh version marker


def test_write_refuses_when_the_document_changed_underneath(tmp_path):
    """The whole point of carrying an eTag: someone editing the same spec in
    Word must not be silently overwritten."""
    build_sample_spec_docx(str(tmp_path / "spec.docx"))
    store = LocalStore(str(tmp_path))
    item = next(iter(store.list_specs()))
    data, stale_etag = store.read(item.key)

    # Someone else saves the file after we read it.
    time.sleep(0.01)
    store.write(item.key, data + b"", None)

    with pytest.raises(ConflictError) as excinfo:
        store.write(item.key, data, stale_etag)
    assert "changed by someone else" in str(excinfo.value)


def test_write_without_an_etag_is_unconditional(tmp_path):
    """Deliberate escape hatch, for writes that aren't editing existing
    content (creating a spec, finishing a conversion)."""
    build_sample_spec_docx(str(tmp_path / "spec.docx"))
    store = LocalStore(str(tmp_path))
    item = next(iter(store.list_specs()))
    data, _ = store.read(item.key)

    store.write(item.key, data, None)  # no precondition, no conflict


def test_create_adds_a_spec_and_refuses_to_clobber(tmp_path):
    build_sample_spec_docx(str(tmp_path / "source.docx"))
    store = LocalStore(str(tmp_path))
    data, _ = store.read(str(tmp_path / "source.docx"))

    created = store.create("T Marzetti", "new.docx", data)

    assert created.display_path == "T Marzetti/new.docx"
    assert parse_bytes(created.key, store.read(created.key)[0]).spec_number == "SW0001"
    with pytest.raises(StoreError):
        store.create("T Marzetti", "new.docx", data)


def test_read_of_a_missing_key_is_a_store_error(tmp_path):
    with pytest.raises(StoreError):
        LocalStore(str(tmp_path)).read(str(tmp_path / "nope.docx"))


def test_read_many_reports_unreadable_without_failing_the_batch(tmp_path):
    """One corrupt file in a 15,000-file library must not sink the index."""
    build_sample_spec_docx(str(tmp_path / "good.docx"))
    store = LocalStore(str(tmp_path))
    good = str(tmp_path / "good.docx")
    missing = str(tmp_path / "gone.docx")

    results = {key: data for key, data, _ in store.read_many([good, missing])}

    assert results[good] is not None
    assert results[missing] is None


def test_watch_coalesces_a_burst_into_one_callback(tmp_path):
    """Saving in Word emits a flurry of events for one logical edit; a
    migration emits thousands. Both should mean one reindex."""
    build_sample_spec_docx(str(tmp_path / "spec.docx"))
    store = LocalStore(str(tmp_path))
    batches: list[list[str]] = []

    stop = store.watch(batches.append)
    try:
        for _ in range(5):
            (tmp_path / "spec.docx").touch()
            time.sleep(0.02)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not batches:
            time.sleep(0.05)
    finally:
        stop()

    assert batches, "no change was reported"
    assert len(batches) <= 2  # coalesced, not one per event
    assert any("spec.docx" in key for key in batches[0])
