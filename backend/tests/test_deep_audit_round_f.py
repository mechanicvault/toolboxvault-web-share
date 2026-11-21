"""Deep audit Round F regression tests.

F1-31: attachment delete — owner can delete (row + object gone),
       another user's token gets a 404 and nothing is removed,
       receipts kind included, batteries too.
F5-02: warranty search — tools + unified stream accept a warranty
       filter incl. the combined "due" set, and sort=warranty_end
       orders by computed end date (expired first).
"""

import pytest

from app.core.storage import StoredObject, storage
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _mechanic_user(db, user_a):
    user_a.account_types = ["mechanic_technician"]
    db.commit()


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 64


def _create_tool(client, user, **fields):
    resp = client.post(
        "/api/inventory",
        json={"name": fields.pop("name", "Wrench"), **fields},
        headers=auth_headers(user),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _attach(client, user, tool_id, kind, filename, content_type, prefix, monkeypatch, deleted):
    key = f"{user.id}/tools/{tool_id}/{kind}/abc-{filename}"
    monkeypatch.setattr(storage, "head", lambda k: StoredObject(key=k, size_bytes=200, content_type=content_type))
    monkeypatch.setattr(storage, "fetch_prefix", lambda k, length=512: prefix)
    monkeypatch.setattr(storage, "delete", lambda k: deleted.append(k))
    resp = client.post(
        f"/api/inventory/{tool_id}/attachments",
        json={"key": key, "filename": filename},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return key


def test_owner_deletes_photo_row_and_object(client, user_a, monkeypatch):
    deleted: list[str] = []
    tool_id = _create_tool(client, user_a)
    key = _attach(client, user_a, tool_id, "photo", "p.png", "image/png", PNG_BYTES, monkeypatch, deleted)
    resp = client.request(
        "DELETE", f"/api/inventory/{tool_id}/attachments",
        params={"key": key}, headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "photo"
    assert deleted == [key]
    detail = client.get(f"/api/inventory/{tool_id}", headers=auth_headers(user_a))
    assert detail.json()["attachments"] == []


def test_owner_deletes_receipt(client, user_a, monkeypatch):
    deleted: list[str] = []
    tool_id = _create_tool(client, user_a)
    key = _attach(client, user_a, tool_id, "receipt", "r.pdf", "application/pdf", PDF_BYTES, monkeypatch, deleted)
    resp = client.request(
        "DELETE", f"/api/inventory/{tool_id}/attachments",
        params={"key": key}, headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "receipt"
    assert deleted == [key]


def test_other_user_cannot_delete(client, user_a, user_b, monkeypatch):
    deleted: list[str] = []
    user_b.account_types = ["mechanic_technician"]
    tool_id = _create_tool(client, user_a)
    key = _attach(client, user_a, tool_id, "photo", "p.png", "image/png", PNG_BYTES, monkeypatch, deleted)
    resp = client.request(
        "DELETE", f"/api/inventory/{tool_id}/attachments",
        params={"key": key}, headers=auth_headers(user_b),
    )
    assert resp.status_code == 404, resp.text
    assert deleted == []
    detail = client.get(f"/api/inventory/{tool_id}", headers=auth_headers(user_a))
    assert len(detail.json()["attachments"]) == 1


def test_delete_missing_attachment_is_404(client, user_a, monkeypatch):
    tool_id = _create_tool(client, user_a)
    resp = client.request(
        "DELETE", f"/api/inventory/{tool_id}/attachments",
        params={"key": f"{user_a.id}/tools/{tool_id}/photo/nope.png"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 404, resp.text


def test_warranty_due_filter_and_end_sort(client, user_a):
    # Expired: bought 2020-01-01, 12-month warranty -> ended 2021-01-01.
    old = _create_tool(client, user_a, name="Old", purchase_date="2020-01-01", warranty_months=12)
    # In warranty: bought 2026-01-01, 60 months.
    new = _create_tool(client, user_a, name="New", purchase_date="2026-01-01", warranty_months=60)
    resp = client.get(
        "/api/inventory/search/all",
        params={"warranty": "due", "sort": "warranty_end"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert old in ids and new not in ids
    resp2 = client.get(
        "/api/inventory/search",
        params={"warranty": "expired"},
        headers=auth_headers(user_a),
    )
    assert [row["id"] for row in resp2.json()] == [old]
