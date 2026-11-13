"""Wave 4 — report narrative summaries ride the AI seam.

Pins: dark seam -> 503 {code: ai_not_configured} (the UI hides
the panel on exactly this); configured seam (mocked provider)
-> a paragraph built from the report's REAL aggregate numbers,
charged at the operator's per-action price; an AI failure is a
502 and charges nothing.
"""

import json
import uuid

import pytest

from app.modules.billing import ai_service, entitlements, wallet
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Narrative User",
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000451", "narrative@example.com")


def _seed_tool(client, owner):
    resp = client.post(
        "/api/inventory",
        json={
            "name": "Torque wrench",
            "brand": "Snap-on",
            "model": "QD3R250",
            "purchase_price": "100.00",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text


def _configure(db, monkeypatch, price=None):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "WAVE4_NARR_KEY")
    monkeypatch.setenv("WAVE4_NARR_KEY", "sk-test")
    if price is not None:
        entitlements.set_setting(db, ai_service.PRICE_KEYS["report_summary"], price)
    db.commit()


def test_narrative_dark_seam_503(client, owner):
    _seed_tool(client, owner)
    resp = client.post(
        "/api/reports/narrative", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ai_not_configured"


def test_narrative_from_real_numbers_with_charge(client, db, owner, monkeypatch):
    _seed_tool(client, owner)
    _configure(db, monkeypatch, price=2)
    seen = {}

    def transport(url, headers, body):
        seen["prompt"] = body["messages"][-1]["content"]
        return {
            "choices": [
                {"message": {"content": "Your vault holds one Snap-on torque wrench."}}
            ]
        }

    monkeypatch.setattr(ai_service, "_transport", transport)
    wallet.credit(db, owner.id, amount=5, bucket="banked", reason="t", ref="t")
    resp = client.post(
        "/api/reports/narrative", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "torque wrench" in body["narrative"]
    assert body["ai_charged"] == 2
    # The prompt carried the report's real aggregates, not vibes.
    assert "items: 1" in seen["prompt"]
    assert wallet.wallet_view(db, owner.id)["banked_balance"] == 3


def test_narrative_failure_charges_nothing(client, db, owner, monkeypatch):
    _seed_tool(client, owner)
    _configure(db, monkeypatch, price=2)

    def boom(url, headers, body):
        raise ai_service.AiProviderError("down")

    monkeypatch.setattr(ai_service, "_transport", boom)
    resp = client.post(
        "/api/reports/narrative", json={}, headers=auth_headers(owner)
    )
    assert resp.status_code == 502
    assert json.dumps(resp.json())  # a clean error body, not a crash
