import pytest
from fastapi.testclient import TestClient

from specwrite.api import _state, app

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
