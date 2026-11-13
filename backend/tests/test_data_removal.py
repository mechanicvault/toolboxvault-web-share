"""Audit A11 (2026-10-22): per-category data removal.

Pick a category -> type its name -> just that category goes,
through the owning modules' own delete/close paths. Filed
claims and open-claim items refuse with reasons; the account
and everything else stay intact; every removal is audited.
"""

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models

from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, number, email, types=None):
    user = core_models.User(
        account_number=number,
        email=email,
        name="Removal Tester",
        password_hash="x",
        account_types=types or [MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000601", "a11-owner@example.com")


def _summaries(client, user):
    resp = client.get("/api/core/data-removal", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return {row["key"]: row for row in resp.json()}


def _remove(client, user, category, confirmation=None):
    return client.post(
        "/api/core/data-removal",
        json={"category": category, "confirmation": confirmation or category},
        headers=auth_headers(user),
    )


def _tool(client, user, name="Wrench"):
    resp = client.post(
        "/api/inventory", json={"name": name}, headers=auth_headers(user)
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_inventory_removal_happy_path_and_audit(client, db, owner):
    _tool(client, owner, "One")
    _tool(client, owner, "Two")
    assert _summaries(client, owner)["inventory"]["count"] == 2
    resp = _remove(client, owner, "inventory")
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == {"tools": 2, "batteries": 0}
    assert _summaries(client, owner)["inventory"]["count"] == 0
    # The account itself is untouched.
    me = client.get("/api/core/me", headers=auth_headers(owner))
    assert me.status_code == 200
    audits = db.scalars(
        select(core_models.AuditLog).where(
            core_models.AuditLog.action == "data_removal"
        )
    ).all()
    assert len(audits) == 1
    assert audits[0].target == "inventory"
    assert audits[0].detail["removed"]["tools"] == 2


def test_confirmation_must_match_the_category(client, owner):
    _tool(client, owner)
    resp = _remove(client, owner, "inventory", confirmation="delete it")
    assert resp.status_code == 422, resp.text
    assert _summaries(client, owner)["inventory"]["count"] == 1


def test_inventory_refused_while_an_item_is_on_an_open_claim(client, db, owner):
    from app.modules.claims import service as claims_service

    tool = _tool(client, owner, "Claimed Wrench")
    claim = claims_service.create_claim(db, owner)
    from decimal import Decimal

    claims_service.add_line(
        db,
        owner,
        claim.id,
        target_kind="tool",
        target_id=_uuid(tool["id"]),
        value_basis="entered",
        amount=Decimal("50"),
    )
    claims_service.transition(db, owner, claim.id, "filed")
    summary = _summaries(client, owner)["inventory"]
    assert summary["blocked_reason"]  # visible before typing anything
    resp = _remove(client, owner, "inventory")
    assert resp.status_code == 409, resp.text
    assert _summaries(client, owner)["inventory"]["count"] == 1  # intact


def _uuid(text):
    import uuid

    return uuid.UUID(text)


def test_claim_drafts_removed_filed_claims_untouched(client, db, owner):
    from app.modules.claims import service as claims_service

    draft = claims_service.create_claim(db, owner)
    filed = claims_service.create_claim(db, owner)
    claims_service.transition(db, owner, filed.id, "filed")
    summary = _summaries(client, owner)["claim-drafts"]
    assert summary["count"] == 1
    assert "1 filed claim" in summary["note"]
    resp = _remove(client, owner, "claim-drafts")
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == {"claim_drafts": 1}
    assert _summaries(client, owner)["claim-drafts"]["count"] == 0
    # The filed claim still exists.
    got = client.get(f"/api/disaster-claims/{filed.id}", headers=auth_headers(owner))
    assert got.status_code == 200


def test_wishlist_and_parts_removal(client, db, owner):
    from app.modules.parts import service as parts_service
    from app.modules.wishlist import service as wishlist_service

    from app.modules.parts import schemas as parts_schemas
    from app.modules.wishlist import schemas as wishlist_schemas

    parts_service.create_part(
        db, owner.id, parts_schemas.PartCreate(title="Spare Bit")
    )
    wishlist_service.create_item(
        db, owner.id, wishlist_schemas.WishlistItemCreate(title="Dream Torque Wrench")
    )
    assert _summaries(client, owner)["parts"]["count"] == 1
    assert _summaries(client, owner)["wishlist"]["count"] == 1
    assert _remove(client, owner, "parts").status_code == 200
    assert _remove(client, owner, "wishlist").status_code == 200
    assert _summaries(client, owner)["parts"]["count"] == 0
    assert _summaries(client, owner)["wishlist"]["count"] == 0


def _seed_category_tiers(db):
    """The open-signup tier shape for the category modules:
    normal keys ON, downloads key OFF (migration 0096/0097)."""
    from app.modules.core import module_control

    for module_id in (
        "inventory",
        "parts",
        "claims",
        "marketplace",
        "forum",
        "wishlist",
        "truck_accounts",
    ):
        for key in ("normal", "moderator", "moderator_admin", "beta"):
            module_control.set_tier_assignment(db, module_id, key, True)
        module_control.set_tier_assignment(db, module_id, "downloads", False)


def test_full_account_picker_names_every_category(client, db, owner):
    """Chrome reach audit (2026-11-09): the no-change promise —
    a full account's removal picker is exactly the static list,
    in order."""
    _seed_category_tiers(db)
    resp = client.get("/api/core/data-removal", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert [row["key"] for row in resp.json()] == [
        "inventory",
        "parts",
        "claim-drafts",
        "marketplace",
        "forum",
        "wishlist",
        "truck-accounts",
    ]


def test_downloads_rung_picker_is_empty_and_removal_refused(client, db):
    """Chrome reach audit (2026-11-09): Export & delete stays in
    a downloads account's menu (its data-rights door), but the
    per-category picker must not enumerate modules the rung
    cannot reach — and the removal door refuses them as
    unknown categories."""
    from app.modules.core import tiers

    _seed_category_tiers(db)
    downloader = core_models.User(
        account_number="TV-DL-000601",
        email="chrome-rung@example.com",
        name="Rung Tester",
        password_hash="x",
        account_types=[],
        tier="downloads",
        role=tiers.role_for_tier("downloads"),
    )
    db.add(downloader)
    db.commit()
    db.refresh(downloader)

    resp = client.get(
        "/api/core/data-removal", headers=auth_headers(downloader)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    resp = _remove(client, downloader, "inventory")
    assert resp.status_code == 422, resp.text


def test_truck_accounts_close_not_erase(client, db, owner):
    from app.modules.truck_accounts import models as truck_models

    dealer = _make_user(db, "TV-D-000601", "a11-dealer@example.com", ["tool_dealer"])
    account = truck_models.TruckAccount(
        dealer_user_id=dealer.id,
        customer_user_id=owner.id,
        status="open",
        invite_token="a11-test-token",
    )
    db.add(account)
    db.commit()
    assert _summaries(client, owner)["truck-accounts"]["count"] == 1
    resp = _remove(client, owner, "truck-accounts")
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"] == {"truck_accounts_closed": 1}
    db.refresh(account)
    assert account.status == "closed"  # closed — the row (ledger) stays
    assert _summaries(client, owner)["truck-accounts"]["count"] == 0
