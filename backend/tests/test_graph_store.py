"""The SharePoint backend, against a fake that reproduces Graph's real
contract (eTags/412, paging, delta, 429 + Retry-After, 409 on create).

Graph itself is unreachable from this environment, so these tests pin the
behaviours that would otherwise only surface against a live tenant.
"""

import pytest

from specwrite.docx_sections import parse_bytes
from specwrite.docx_writer import _resolve_table, apply_to_bytes, write_record_cell
from specwrite.graph_store import GraphClient, GraphStore, StaticToken, resolve_drive_from_site
from specwrite.storage import ConflictError, StoreError

from .fakes.fake_graph import FakeGraph, upload_session_opener
from .fixtures.builder import build_sample_spec_docx


def _spec_bytes(tmp_path, name="spec.docx", spec_number="SW0001") -> bytes:
    path = tmp_path / name
    build_sample_spec_docx(str(path), spec_number=spec_number)
    return path.read_bytes()


def _store(fake, **kwargs) -> GraphStore:
    client = GraphClient(StaticToken("t"), opener=fake.opener, sleep=lambda _: None)
    return GraphStore(client, fake.drive_id, label="Test library", **kwargs)


def test_lists_specs_with_their_folders(tmp_path):
    fake = FakeGraph()
    data = _spec_bytes(tmp_path)
    fake.add("EG1419.docx", data, folder="Atkinson Candy")
    fake.add("HK0071.docx", data, folder="Daisy/Pouches")
    fake.add("root.docx", data)

    items = sorted(_store(fake).list_specs(), key=lambda i: i.display_path)

    assert [i.display_path for i in items] == [
        "Atkinson Candy/EG1419.docx",
        "Daisy/Pouches/HK0071.docx",
        "root.docx",
    ]
    assert all(i.key.startswith("item-") for i in items)  # ids, not paths


def test_skips_lock_files_and_non_specs(tmp_path):
    fake = FakeGraph()
    data = _spec_bytes(tmp_path)
    fake.add("real.docx", data)
    fake.add("~$real.docx", b"lock")
    fake.add("notes.txt", b"text")

    assert [i.name for i in _store(fake).list_specs()] == ["real.docx"]


def test_walks_every_page_of_a_large_library(tmp_path):
    """A library past one page must not be silently truncated."""
    fake = FakeGraph(page_size=10)
    data = _spec_bytes(tmp_path)
    for i in range(35):
        fake.add(f"spec{i:03d}.docx", data)

    assert len(list(_store(fake).list_specs())) == 35


def test_read_returns_parseable_bytes_and_an_etag(tmp_path):
    fake = FakeGraph()
    item = fake.add("EG1419.docx", _spec_bytes(tmp_path))
    store = _store(fake)

    data, etag = store.read(item.key)

    assert parse_bytes(item.key, data).spec_number == "SW0001"
    assert etag == "etag-1"


def test_edit_round_trip_downloads_edits_and_uploads(tmp_path):
    """The full cloud write path: no file ever touches a disk."""
    fake = FakeGraph()
    item = fake.add("EG1419.docx", _spec_bytes(tmp_path))
    store = _store(fake)

    data, etag = store.read(item.key)
    edited = apply_to_bytes(
        data, lambda doc: write_record_cell(_resolve_table(doc, "Bill of Materials"), 1, 2, "Terphane")
    )
    new_etag = store.write(item.key, edited, etag)

    assert new_etag != etag
    stored, _ = store.read(item.key)
    assert parse_bytes(item.key, stored).primary("Bill of Materials").records()[0]["Supplier"] == "Terphane"


def test_write_refuses_when_someone_edited_it_in_word(tmp_path):
    """The behaviour a filesystem cannot give us: a stale precondition is
    rejected rather than overwriting a colleague's save."""
    fake = FakeGraph()
    item = fake.add("EG1419.docx", _spec_bytes(tmp_path))
    store = _store(fake)
    data, stale_etag = store.read(item.key)

    fake.touch(item.key)  # someone saves it in Word

    with pytest.raises(ConflictError):
        store.write(item.key, data, stale_etag)


def test_write_without_a_precondition_still_succeeds(tmp_path):
    fake = FakeGraph()
    item = fake.add("EG1419.docx", _spec_bytes(tmp_path))
    store = _store(fake)
    data, _ = store.read(item.key)

    fake.touch(item.key)

    store.write(item.key, data, None)  # unconditional by choice


def test_throttling_is_retried_and_honours_retry_after(tmp_path):
    """429 is routine while indexing thousands of specs, not a failure."""
    fake = FakeGraph()
    item = fake.add("EG1419.docx", _spec_bytes(tmp_path))
    fake.inject_failures = [429, 429]
    delays: list[float] = []
    client = GraphClient(StaticToken("t"), opener=fake.opener, sleep=delays.append)
    store = GraphStore(client, fake.drive_id)

    data, _ = store.read(item.key)

    assert parse_bytes(item.key, data).spec_number == "SW0001"
    assert delays == [0.0, 0.0]  # took Retry-After from the response


def test_gives_up_with_a_clear_error_after_repeated_failures(tmp_path):
    fake = FakeGraph()
    fake.add("EG1419.docx", _spec_bytes(tmp_path))
    fake.inject_failures = [503] * 10
    client = GraphClient(StaticToken("t"), opener=fake.opener, sleep=lambda _: None, max_attempts=3)

    with pytest.raises(StoreError, match="SharePoint request failed"):
        GraphStore(client, fake.drive_id).read("item-1")


def test_create_refuses_to_overwrite_an_existing_spec(tmp_path):
    fake = FakeGraph()
    data = _spec_bytes(tmp_path)
    fake.add("EG1419.docx", data, folder="Atkinson Candy")
    store = _store(fake)

    created = store.create("T Marzetti", "EG1500.docx", data)
    assert created.display_path == "T Marzetti/EG1500.docx"

    with pytest.raises(StoreError, match="already exists"):
        store.create("Atkinson Candy", "EG1419.docx", data)


def test_delta_reports_only_what_changed(tmp_path):
    """What stands in for a file watcher: after the first listing, a poll
    returns just the specs that moved."""
    fake = FakeGraph()
    data = _spec_bytes(tmp_path)
    a = fake.add("a.docx", data)
    fake.add("b.docx", data)
    store = _store(fake)

    store.list_specs()  # establishes the delta token
    assert store.changes() == []

    fake.touch(a.key)
    fake.record_change(a.key)

    assert store.changes() == [a.key]


def test_read_many_fetches_concurrently_and_survives_a_bad_item(tmp_path):
    fake = FakeGraph()
    data = _spec_bytes(tmp_path)
    keys = [fake.add(f"s{i}.docx", data).key for i in range(6)]
    store = _store(fake, fetch_concurrency=4)

    results = dict((k, b) for k, b, _ in store.read_many(keys + ["item-missing"]))

    assert len(results) == 7
    assert all(results[k] is not None for k in keys)
    assert results["item-missing"] is None


def test_large_spec_uses_an_upload_session(tmp_path):
    """Specs are normally small, but the chunked path must actually work."""
    fake = FakeGraph()
    item = fake.add("big.docx", b"x" * 10)
    client = GraphClient(StaticToken("t"), opener=upload_session_opener(fake), sleep=lambda _: None)
    store = GraphStore(client, fake.drive_id)

    payload = b"y" * (9 * 1024 * 1024)  # over the simple-upload limit
    store.write(item.key, payload, "etag-1")

    assert fake.items[item.key].content == payload
    assert sum(1 for m, u in fake.requests if u.startswith("https://upload.example/")) == 2


def test_resolves_a_drive_from_a_site_url():
    """People have a site URL, not a drive id."""
    class SiteFake(FakeGraph):
        def _route(self, method, path, request):  # noqa: ANN001
            import json as _json
            from .fakes.fake_graph import _Response

            if path.startswith("/sites/") and ":" in path and "/drives" not in path:
                return _Response(_json.dumps({"id": "site-1", "displayName": "Packaging"}).encode())
            if path == "/sites/site-1/drives":
                return _Response(
                    _json.dumps({"value": [{"id": "drive-9", "name": "Specs"}, {"id": "drive-8", "name": "Other"}]}).encode()
                )
            return super()._route(method, path, request)

    fake = SiteFake()
    client = GraphClient(StaticToken("t"), opener=fake.opener, sleep=lambda _: None)

    drive_id, label = resolve_drive_from_site(client, "contoso.sharepoint.com", "/sites/Packaging", "Specs")

    assert drive_id == "drive-9"
    assert label == "Packaging / Specs"


def test_unknown_library_name_lists_the_options():
    class SiteFake(FakeGraph):
        def _route(self, method, path, request):  # noqa: ANN001
            import json as _json
            from .fakes.fake_graph import _Response

            if path.startswith("/sites/") and ":" in path and "/drives" not in path:
                return _Response(_json.dumps({"id": "site-1", "displayName": "Packaging"}).encode())
            if path == "/sites/site-1/drives":
                return _Response(_json.dumps({"value": [{"id": "d1", "name": "Documents"}]}).encode())
            return super()._route(method, path, request)

    fake = SiteFake()
    client = GraphClient(StaticToken("t"), opener=fake.opener, sleep=lambda _: None)

    with pytest.raises(StoreError, match="Available: Documents"):
        resolve_drive_from_site(client, "contoso.sharepoint.com", "/sites/Packaging", "Nope")
