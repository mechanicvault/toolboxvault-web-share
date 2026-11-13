"""Wishlist (Wave 2, 2026-10-20): CRUD + search, module gating,
the mark-purchased -> convert-to-tool flow (pattern mirrors Parts
Convert), export + journal presence."""

from __future__ import annotations

import uuid
import zipfile
import io

import pytest

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, account_types, name="Wish User"):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=list(account_types),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000801", "wish@example.com", (MECHANIC,))


@pytest.fixture()
def dealer(db):
    return _make_user(db, "TV-D-000801", "wishdealer@example.com", (DEALER,))


def _add(client, user, **over):
    body = {"title": "Milwaukee M18 impact"}
    body.update(over)
    resp = client.post("/api/wishlist/items", json=body, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_stats_counts_wanted_only(client, owner):
    # Phase 3 panel stat: still-wanted items only; a purchased
    # item leaves the count.
    item = _add(client, owner)
    _add(client, owner, title="Tekton socket rail")
    stats = client.get("/api/wishlist/stats", headers=auth_headers(owner)).json()
    assert stats == {"items_count": 2}
    resp = client.post(
        f"/api/wishlist/items/{item['id']}/mark-purchased",
        json={"purchased_price": "199.00", "purchased_on": "2026-10-24"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    stats = client.get("/api/wishlist/stats", headers=auth_headers(owner)).json()
    assert stats == {"items_count": 1}


def test_crud_and_search(client, owner):
    item = _add(client, owner, target_price="249.00", priority="high",
                notes="Wait for a sale")
    assert item["status"] == "wanted"
    assert item["priority"] == "high"
    _add(client, owner, title="Tekton socket rail")
    hits = client.get("/api/wishlist/items?q=socket", headers=auth_headers(owner)).json()
    assert [h["title"] for h in hits] == ["Tekton socket rail"]
    updated = client.put(
        f"/api/wishlist/items/{item['id']}",
        json={"priority": "low"},
        headers=auth_headers(owner),
    )
    assert updated.json()["priority"] == "low"
    assert client.delete(
        f"/api/wishlist/items/{item['id']}", headers=auth_headers(owner)
    ).status_code == 204
    assert client.get("/api/wishlist/items", headers=auth_headers(owner)).json() == [
        h for h in client.get("/api/wishlist/items", headers=auth_headers(owner)).json()
        if h["title"] == "Tekton socket rail"
    ]


def test_title_required_and_owner_scoped(client, owner, dealer):
    assert client.post(
        "/api/wishlist/items", json={"title": "  "}, headers=auth_headers(owner)
    ).status_code == 422
    item = _add(client, owner)
    # Another user can't see or touch it.
    assert client.get(
        f"/api/wishlist/items/{item['id']}", headers=auth_headers(dealer)
    ).status_code in (403, 404)


def test_module_gate_dealer_denied(client, dealer):
    resp = client.get("/api/wishlist/items", headers=auth_headers(dealer))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "module_unavailable"


def test_mark_purchased_requires_price_and_date(client, owner):
    item = _add(client, owner)
    resp = client.post(
        f"/api/wishlist/items/{item['id']}/mark-purchased",
        json={"purchased_price": "", "purchased_on": None},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 422
    done = client.post(
        f"/api/wishlist/items/{item['id']}/mark-purchased",
        json={"purchased_price": "199.50", "purchased_on": "2026-10-01"},
        headers=auth_headers(owner),
    )
    assert done.status_code == 200
    assert done.json()["status"] == "purchased"
    assert done.json()["purchased_price"] == "199.50"


def test_convert_creates_tool_and_links(client, owner):
    item = _add(client, owner)
    # Convert before purchase is refused.
    resp = client.post(
        f"/api/wishlist/items/{item['id']}/convert", headers=auth_headers(owner)
    )
    assert resp.status_code == 422
    client.post(
        f"/api/wishlist/items/{item['id']}/mark-purchased",
        json={"purchased_price": "210.00", "purchased_on": "2026-10-02"},
        headers=auth_headers(owner),
    )
    converted = client.post(
        f"/api/wishlist/items/{item['id']}/convert", headers=auth_headers(owner)
    )
    assert converted.status_code == 200, converted.text
    body = converted.json()
    assert body["item"]["converted_tool_id"]
    tool = client.get(
        f"/api/inventory/{body['item']['converted_tool_id']}", headers=auth_headers(owner)
    ).json()
    assert tool["name"] == "Milwaukee M18 impact"
    assert tool["purchase_price"] == "210.00"
    assert tool["purchase_date"] == "2026-10-02"
    # Converting twice is refused.
    assert client.post(
        f"/api/wishlist/items/{item['id']}/convert", headers=auth_headers(owner)
    ).status_code == 422


def test_export_contains_wishlist_json(client, owner):
    _add(client, owner, title="Export me")
    resp = client.get("/api/core/export", headers=auth_headers(owner))
    assert resp.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    names = archive.namelist()
    assert "wishlist.json" in names
    rows = __import__("json").loads(archive.read("wishlist.json"))
    assert [r["title"] for r in rows] == ["Export me"]


def test_journal_records_wishlist_item(client, db, owner):
    item = _add(client, owner)
    rows = (
        db.query(core_models.ChangeJournal)
        .filter_by(entity_type="wishlist_item", entity_id=uuid.UUID(item["id"]))
        .all()
    )
    assert rows, "wishlist create must be journaled"
