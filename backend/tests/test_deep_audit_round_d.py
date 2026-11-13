"""Deep audit Round D (backend + security) regression tests.

F4-02: inventory money fields reject negatives (422), like Parts/Claims.
F4-03: inventory strings/decimals are bounded by their columns — a
       5,000-char name or 30-digit price is a 422, never a 500; and a
       missing record on the upload routes is a 404, not a 422.
F4-06: uploaded bytes are content-sniffed at attach — the declared
       content type must match the file's magic bytes.
F4-07: presigned download URLs default to a 1-hour lifetime.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.core.storage import (
    EXPORT_FALLBACK_TTL_SECONDS,
    PRESIGNED_GET_TTL_SECONDS,
    StoredObject,
    content_matches_declared,
    storage,
)
from app.modules.inventory import schemas as inv_schemas
from tests.conftest import auth_headers

@pytest.fixture(autouse=True)
def _mechanic_user(db, user_a):
    # Inventory routes are mechanic-gated; grant the group (same
    # pattern as test_inventory_stats).
    user_a.account_types = ["mechanic_technician"]
    db.commit()


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
HTML_BYTES = b"<html><script>alert(1)</script></html>"


# -- F4-02: negative money is refused ------------------------------------


def test_tool_create_rejects_negative_money(client, user_a):
    for field in ("purchase_price", "replacement_cost", "msrp"):
        resp = client.post(
            "/api/inventory",
            json={"name": "Wrench", field: "-50.00"},
            headers=auth_headers(user_a),
        )
        assert resp.status_code == 422, (field, resp.text)


def test_battery_create_rejects_negative_money(client, user_a):
    resp = client.post(
        "/api/inventory/batteries",
        json={"name": "Battery", "purchase_price": "-1"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_tool_update_rejects_negative_money(client, user_a):
    created = client.post(
        "/api/inventory",
        json={"name": "Wrench", "purchase_price": "10.00"},
        headers=auth_headers(user_a),
    )
    assert created.status_code in (200, 201), created.text
    tool_id = created.json()["id"]
    resp = client.put(
        f"/api/inventory/{tool_id}",
        json={"msrp": "-999"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_set_piece_price_rejects_negative():
    with pytest.raises(ValidationError):
        inv_schemas.SetPieceCreate(name="Socket", price="-5")


def test_sale_price_rejects_negative_and_overflow():
    with pytest.raises(ValidationError):
        inv_schemas.MarkSoldRequest(sale_price="-1")
    with pytest.raises(ValidationError):
        inv_schemas.MarkSoldRequest(sale_price="9" * 30)


# -- F4-03: oversize input is a 422, never a 500 --------------------------


def test_tool_create_rejects_5000_char_name(client, user_a):
    resp = client.post(
        "/api/inventory",
        json={"name": "x" * 5000},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_tool_create_rejects_30_digit_price(client, user_a):
    resp = client.post(
        "/api/inventory",
        json={"name": "Wrench", "purchase_price": "9" * 30},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_battery_rejects_out_of_range_voltage(client, user_a):
    resp = client.post(
        "/api/inventory/batteries",
        json={"name": "Battery", "voltage": "12345.67"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text


def test_tool_create_accepts_column_maxima(client, user_a):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "n" * 300,
            "brand": "b" * 200,
            "purchase_price": "9999999999.99",
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code in (200, 201), resp.text


def test_upload_url_for_missing_tool_is_404(client, user_a):
    resp = client.post(
        f"/api/inventory/{uuid.uuid4()}/upload-url",
        json={
            "filename": "photo.png",
            "content_type": "image/png",
            "kind": "photo",
            "size_bytes": 100,
        },
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 404, resp.text


# -- F4-06: content sniffing ----------------------------------------------


@pytest.mark.parametrize(
    "content_type,prefix,ok",
    [
        ("image/png", PNG_BYTES, True),
        ("image/png", HTML_BYTES, False),
        ("image/png", JPEG_BYTES, False),
        ("image/jpeg", JPEG_BYTES, True),
        ("image/jpeg", PNG_BYTES, False),
        ("image/webp", b"RIFF\x24\x00\x00\x00WEBPVP8 ", True),
        ("image/webp", PNG_BYTES, False),
        ("application/pdf", b"%PDF-1.7\n" + b"\x00" * 8, True),
        ("application/pdf", HTML_BYTES, False),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04" + b"\x00" * 8,
            True,
        ),
        ("application/msword", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8, True),
        ("application/msword", HTML_BYTES, False),
        ("text/plain", b"hello world\nplain notes\n", True),
        ("text/plain", b"MZ\x90\x00\x03\x00\x00\x00", False),
        ("application/octet-stream", PNG_BYTES, False),  # fail closed
        ("image/png", b"", False),
    ],
)
def test_content_matches_declared(content_type, prefix, ok):
    assert content_matches_declared(content_type, prefix) is ok


def _create_tool(client, user) -> str:
    resp = client.post(
        "/api/inventory",
        json={"name": "Camera-ready wrench"},
        headers=auth_headers(user),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _stub_storage(monkeypatch, *, content_type: str, prefix: bytes):
    def fake_head(key):
        return StoredObject(key=key, size_bytes=len(prefix) + 100,
                            content_type=content_type)

    monkeypatch.setattr(storage, "head", fake_head)
    monkeypatch.setattr(storage, "fetch_prefix", lambda key, length=512: prefix)


def test_attach_rejects_html_bytes_declared_as_png(client, user_a, monkeypatch):
    tool_id = _create_tool(client, user_a)
    key = f"{user_a.id}/tools/{tool_id}/photo/abc-photo.png"
    _stub_storage(monkeypatch, content_type="image/png", prefix=HTML_BYTES)
    resp = client.post(
        f"/api/inventory/{tool_id}/attachments",
        json={"key": key, "filename": "photo.png"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 422, resp.text
    assert "don't match" in resp.json()["detail"]


def test_attach_accepts_real_png_bytes(client, user_a, monkeypatch):
    tool_id = _create_tool(client, user_a)
    key = f"{user_a.id}/tools/{tool_id}/photo/abc-photo.png"
    _stub_storage(monkeypatch, content_type="image/png", prefix=PNG_BYTES)
    resp = client.post(
        f"/api/inventory/{tool_id}/attachments",
        json={"key": key, "filename": "photo.png"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_type"] == "image/png"


# -- F4-07: presigned lifetime ---------------------------------------------


def test_presigned_get_default_ttl_is_one_hour(monkeypatch):
    captured = {}

    class _StubClient:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            captured["expires"] = ExpiresIn
            return "https://files.example/stub"

    monkeypatch.setattr(storage, "_public_client", _StubClient())
    storage.presigned_get_url("some/key.png")
    assert captured["expires"] == PRESIGNED_GET_TTL_SECONDS == 3600
    # The export fallback is the one explicit, scoped exception.
    storage.presigned_get_url("some/key.png", expires_in=EXPORT_FALLBACK_TTL_SECONDS)
    assert captured["expires"] == 86400
