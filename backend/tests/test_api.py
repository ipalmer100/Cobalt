from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cobalt.api import _state, app

from .fixtures.builder import build_sample_spec_docx


@pytest.fixture(autouse=True)
def _reset_vault_state():
    yield
    vault = _state.get("vault")
    if vault is not None:
        vault.close()
    _state["vault"] = None
    _state["sockets"] = []


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_open_and_list_vault(client, tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"), spec_number="SW0001")

    r = client.post("/vault/open", json={"root": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["file_count"] == 1

    r = client.get("/vault")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["spec_number"] == "SW0001"


def test_get_spec_detail(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.get("/spec", params={"path": path})
    assert r.status_code == 200
    body = r.json()
    assert body["spec_number"] == "SW0001"
    assert "Bill of Materials" in body["sections"]


def test_bill_of_materials_view(client, tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.get("/views/Bill of Materials")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 2
    assert {row["Material Type"] for row in rows} == {"Primary", "Secondary"}


def test_write_cell_then_reread(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cell",
        json={"path": path, "section": "Bill of Materials", "row": 1, "col": 2, "value": "New Supplier"},
    )
    assert r.status_code == 200

    r = client.get("/views/Bill of Materials")
    rows = r.json()["rows"]
    primary = next(row for row in rows if row["Material Type"] == "Primary")
    assert primary["Supplier"] == "New Supplier"


def test_apply_revision_endpoint(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, revision="01")
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.post("/spec/revision", json={"path": path, "who": "Isaac", "revision_text": "Test edit."})
    assert r.status_code == 200
    assert r.json()["revision_number"] == "02"

    r = client.get("/vault")
    entries = r.json()["entries"]
    assert entries[0]["revision_number"] == "02"


def test_operations_without_open_vault_return_400(client):
    r = client.get("/vault")
    assert r.status_code == 400


def test_duplicate_spec_endpoint(client, tmp_path):
    source = str(tmp_path / "source.docx")
    build_sample_spec_docx(source, spec_number="SW0001")
    client.post("/vault/open", json={"root": str(tmp_path)})

    dest = str(tmp_path / "new_spec.docx")
    r = client.post(
        "/spec/duplicate",
        json={"source_path": source, "dest_path": dest, "spec_number": "SW0099", "customer": "New Co", "who": "Isaac"},
    )
    assert r.status_code == 200
    assert r.json()["spec_number"] == "SW0099"

    r = client.get("/vault")
    numbers = {e["spec_number"] for e in r.json()["entries"]}
    assert numbers == {"SW0001", "SW0099"}


def test_duplicate_spec_rejects_path_outside_vault(client, tmp_path):
    source = str(tmp_path / "source.docx")
    build_sample_spec_docx(source)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.post(
        "/spec/duplicate",
        json={
            "source_path": source,
            "dest_path": "/tmp/outside_vault_spec.docx",
            "spec_number": "SW0099",
            "customer": "New Co",
            "who": "Isaac",
        },
    )
    assert r.status_code == 400
    assert "inside the open vault" in r.json()["detail"]


def test_create_blank_spec_endpoint(client, tmp_path):
    client.post("/vault/open", json={"root": str(tmp_path)})

    dest = str(tmp_path / "brand_new.docx")
    r = client.post(
        "/spec/create-blank",
        json={"dest_path": dest, "spec_number": "SW0100", "customer": "Fresh Co", "who": "Isaac"},
    )
    assert r.status_code == 200
    assert r.json()["spec_number"] == "SW0100"

    r = client.get("/spec", params={"path": dest})
    assert r.json()["customer"] == "Fresh Co"


def test_views_list_flags_revision_history_as_not_editable(client, tmp_path):
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.get("/views")
    meta = r.json()["views_meta"]
    assert meta["Revision History"]["editable"] is False
    assert meta["Bill of Materials"]["editable"] is True
    assert "Revision #" in meta["Product Description"]["readonly_columns"]


def test_revision_history_view_is_read_only(client, tmp_path):
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.get("/views/Revision History")
    assert r.status_code == 200
    assert r.json()["editable"] is False


def test_cannot_write_cell_into_revision_history(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cell",
        json={"path": path, "section": "Revision History", "row": 1, "col": 3, "value": "Rewritten history"},
    )
    assert r.status_code == 422
    assert "Add Revision" in r.json()["detail"]

    # confirm nothing actually changed on disk
    r = client.get("/spec", params={"path": path})
    records = r.json()["sections"]["Revision History"][0]["rows"]
    assert records[1][3] == "Spec created."


def test_cannot_append_row_to_revision_history(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.post(
        "/spec/row",
        json={"path": path, "section": "Revision History", "values": ["99", "Someone", "01/01/2099", "Snuck in."]},
    )
    assert r.status_code == 422
    assert "Add Revision" in r.json()["detail"]


def test_cannot_write_revision_number_field_directly(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, revision="06")
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/field",
        json={"path": path, "section": "Product Description", "label": "Revision #", "value": "99"},
    )
    assert r.status_code == 422
    assert "Add Revision" in r.json()["detail"]

    r = client.get("/spec", params={"path": path})
    assert r.json()["revision_number"] == "06"


def test_other_product_description_fields_remain_editable(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/field",
        json={"path": path, "section": "Product Description", "label": "Customer", "value": "Renamed Customer"},
    )
    assert r.status_code == 200

    r = client.get("/spec", params={"path": path})
    assert r.json()["customer"] == "Renamed Customer"


def test_apply_revision_still_works_despite_lock(client, tmp_path):
    """The lock only blocks the generic mass-edit paths -- Add Revision
    (which changes both atomically) must keep working."""
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, revision="01")
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.post("/spec/revision", json={"path": path, "who": "Isaac", "revision_text": "Fine."})
    assert r.status_code == 200
    assert r.json()["revision_number"] == "02"


def test_audit_log_records_cell_write_with_before_and_after(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, spec_number="SW0001")
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cell",
        json={
            "path": path,
            "section": "Bill of Materials",
            "row": 1,
            "col": 2,
            "value": "New Supplier",
            "who": "Isaac",
        },
    )
    assert r.status_code == 200

    r = client.get("/audit-log")
    entries = r.json()["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "write_cell"
    assert entry["who"] == "Isaac"
    assert entry["spec_number"] == "SW0001"
    assert entry["old_value"] == "Flex Films"
    assert entry["new_value"] == "New Supplier"


def test_audit_log_records_revision_and_creation_actions(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path, spec_number="SW0001", revision="01")
    client.post("/vault/open", json={"root": str(tmp_path)})

    client.post("/spec/revision", json={"path": path, "who": "Isaac", "revision_text": "Bumped."})
    client.post(
        "/spec/duplicate",
        json={
            "source_path": path,
            "dest_path": str(tmp_path / "new_spec.docx"),
            "spec_number": "SW0099",
            "customer": "New Co",
            "who": "Isaac",
        },
    )

    r = client.get("/audit-log")
    actions = [e["action"] for e in r.json()["entries"]]
    # most recent first
    assert actions == ["duplicate_spec", "apply_revision"]


def test_audit_log_write_does_not_touch_docx_and_is_excluded_from_vault(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    client.put(
        "/spec/cell",
        json={"path": path, "section": "Bill of Materials", "row": 1, "col": 2, "value": "X", "who": "Isaac"},
    )

    assert (tmp_path / ".cobalt" / "audit_log.jsonl").exists()

    # the log file must never show up as a vault entry alongside the real spec
    r = client.get("/vault")
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["path"] == path


def test_audit_log_empty_before_any_writes(client, tmp_path):
    client.post("/vault/open", json={"root": str(tmp_path)})
    r = client.get("/audit-log")
    assert r.json()["entries"] == []


def test_batch_cell_write_spans_multiple_files(client, tmp_path):
    path_a = str(tmp_path / "a.docx")
    path_b = str(tmp_path / "b.docx")
    build_sample_spec_docx(path_a, spec_number="SW0001")
    build_sample_spec_docx(path_b, spec_number="SW0002")
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cells/batch",
        json={
            "edits": [
                {"path": path_a, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "Fill A"},
                {"path": path_b, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "Fill B"},
            ],
            "who": "Isaac",
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    r = client.get("/spec", params={"path": path_a})
    assert r.json()["sections"]["Bill of Materials"][0]["rows"][1][2] == "Fill A"
    r = client.get("/spec", params={"path": path_b})
    assert r.json()["sections"]["Bill of Materials"][0]["rows"][1][2] == "Fill B"


def test_batch_cell_write_field_kind(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cells/batch",
        json={"edits": [{"path": path, "section": "Locations", "kind": "field", "label": "Facility", "value": "New Plant"}], "who": "Isaac"},
    )
    assert r.status_code == 200

    r = client.get("/spec", params={"path": path})
    assert r.json()["sections"]["Locations"][0]["fields"]["Facility"] == "New Plant"


def test_batch_cell_write_rejects_whole_batch_if_any_edit_locked(client, tmp_path):
    path = str(tmp_path / "spec1.docx")
    build_sample_spec_docx(path)
    client.post("/vault/open", json={"root": str(tmp_path)})

    r = client.put(
        "/spec/cells/batch",
        json={
            "edits": [
                {"path": path, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "Should not land"},
                {"path": path, "section": "Revision History", "kind": "record", "row": 1, "col": 3, "value": "Rewritten"},
            ],
            "who": "Isaac",
        },
    )
    assert r.status_code == 422
    assert "Add Revision" in r.json()["detail"]

    # confirm the FIRST (otherwise-valid) edit in the batch did not land either
    r = client.get("/spec", params={"path": path})
    assert r.json()["sections"]["Bill of Materials"][0]["rows"][1][2] == "Flex Films"


def test_batch_cell_write_logs_one_audit_entry_per_file_not_per_cell(client, tmp_path):
    path_a = str(tmp_path / "a.docx")
    path_b = str(tmp_path / "b.docx")
    build_sample_spec_docx(path_a, spec_number="SW0001")
    build_sample_spec_docx(path_b, spec_number="SW0002")
    client.post("/vault/open", json={"root": str(tmp_path)})

    client.put(
        "/spec/cells/batch",
        json={
            "edits": [
                {"path": path_a, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "V1"},
                {"path": path_a, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 3, "value": "V2"},
                {"path": path_b, "section": "Bill of Materials", "kind": "record", "row": 1, "col": 2, "value": "V3"},
            ],
            "who": "Isaac",
        },
    )

    r = client.get("/audit-log")
    entries = r.json()["entries"]
    assert len(entries) == 2  # one per file, not one per cell (3 cells total)
    fill_entries = [e for e in entries if e["action"] == "fill_column"]
    assert len(fill_entries) == 2
    entry_a = next(e for e in fill_entries if e["file_path"] == path_a)
    assert len(entry_a["edits"]) == 2
    assert entry_a["edits"][0]["old_value"] == "Flex Films"
    assert entry_a["edits"][0]["new_value"] == "V1"


def test_browse_starts_on_the_desktop(client, tmp_path, monkeypatch):
    """The picker opens on the Desktop, not on a bare list of drive letters.

    "C:\\" and its forty system folders is where people lose track of where
    they are; the Desktop is the landmark they navigate from, and a synced
    SharePoint library is usually a step or two off it.
    """
    desktop = tmp_path / "Desktop"
    (desktop / "Specs").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    body = client.get("/browse").json()

    assert body["path"] == str(desktop)
    assert [e["name"] for e in body["entries"]] == ["Specs"]
    assert body["parent"] == str(tmp_path)


def test_browse_finds_a_onedrive_redirected_desktop(client, tmp_path, monkeypatch):
    """On a OneDrive-backed profile the real Desktop lives under the
    OneDrive folder rather than directly in the home directory — which is
    exactly the setup these specs are synced on."""
    desktop = tmp_path / "OneDrive - Toppan" / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert client.get("/browse").json()["path"] == str(desktop)


def test_browse_falls_back_to_roots_without_a_desktop(client, tmp_path, monkeypatch):
    """A renamed or redirected Desktop must not leave the picker with
    nowhere to start."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    body = client.get("/browse").json()

    assert body["path"] is None
    assert len(body["entries"]) > 0


def test_browse_lists_subfolders_and_counts_specs(client, tmp_path):
    (tmp_path / "Atkinson Candy").mkdir()
    (tmp_path / "T Marzetti").mkdir()
    (tmp_path / ".hidden").mkdir()
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))

    r = client.get("/browse", params={"path": str(tmp_path)})
    assert r.status_code == 200
    body = r.json()

    assert [e["name"] for e in body["entries"]] == ["Atkinson Candy", "T Marzetti"]
    assert body["spec_count"] == 1
    assert body["parent"] is not None


def test_browse_rejects_a_non_folder(client, tmp_path):
    path = tmp_path / "spec1.docx"
    build_sample_spec_docx(str(path))
    assert client.get("/browse", params={"path": str(path)}).status_code == 404


def test_view_response_carries_the_vault_root(client, tmp_path):
    """The grid shows File Path relative to the vault, which needs the root."""
    build_sample_spec_docx(str(tmp_path / "spec1.docx"))
    client.post("/vault/open", json={"root": str(tmp_path)})

    body = client.get("/views/Bill of Materials").json()
    assert body["root"] == str(tmp_path.resolve())


def test_specs_in_subfolders_are_indexed(client, tmp_path):
    """A SharePoint library is foldered by customer; one pick must cover the
    whole tree, and same-named specs in different folders must both land."""
    nested = tmp_path / "Daisy" / "Pouches"
    nested.mkdir(parents=True)
    build_sample_spec_docx(str(tmp_path / "Daisy" / "HK0071.docx"), spec_number="HK0071")
    build_sample_spec_docx(str(nested / "HK0071.docx"), spec_number="HK0600")

    client.post("/vault/open", json={"root": str(tmp_path)})
    entries = client.get("/vault").json()["entries"]

    assert len(entries) == 2
    assert {e["spec_number"] for e in entries} == {"HK0071", "HK0600"}
