"""Wave 4 — the layered lookup chain + the AI seam.

Pins:
  - provider order community -> barcode -> AI, first hit wins
    per field, later layers only supplement;
  - every field is source-labeled;
  - dark layers are skipped silently (no UPC key configured =
    the UPC transport is never called; no AI config = the AI
    transport is never called);
  - the wallet is charged ONLY when the AI call actually runs,
    at the operator's per-action price; a failing AI layer
    charges nothing and the chain still answers;
  - /identify is AI-or-nothing: dark seam -> 503
    {code: ai_not_configured}; /catalog/ai-status reports the
    posture with no key material;
  - the admin settings roundtrip covers the prices + the
    lookup layer config.
"""

import uuid

import pytest

from app.modules.billing import ai_service, entitlements
from app.modules.catalog import lookup
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, types=(MECHANIC,), operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name="Lookup User",
        password_hash="not-a-real-hash",
        account_types=list(types),
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def seeker(db):
    return _make_user(db, "TV-M-000411", "seeker@example.com")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000412", "other@example.com")


@pytest.fixture()
def operator(db):
    return _make_user(db, "TV-M-000419", "op2@example.com", operator=True)


def _add_tool(client, user, **overrides):
    payload = {
        "name": "Torque wrench",
        "brand": "Snap-on",
        "model": "QD3R250",
        "category": "Torque",
        "size": "1/2 in drive",
        "msrp": "289.95",
    }
    payload.update(overrides)
    resp = client.post("/api/inventory", json=payload, headers=auth_headers(user))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _configure_ai(db, monkeypatch, price_lookup=None):
    entitlements.set_setting(db, ai_service.PROVIDER_KEY, "openai")
    entitlements.set_setting(db, ai_service.MODEL_KEY, "test-model")
    entitlements.set_setting(db, ai_service.API_KEY_REF_KEY, "WAVE4_TEST_AI_KEY")
    monkeypatch.setenv("WAVE4_TEST_AI_KEY", "sk-test-not-real")
    if price_lookup is not None:
        entitlements.set_setting(db, ai_service.PRICE_KEYS["lookup"], price_lookup)
    db.commit()


def _fake_ai_transport(payload):
    """Chat stub for the AI-assist layer. Search calls (the
    grounded layer rides the same AI door and probes first
    whenever the seam is lit) get a citation-less Responses
    body — the search ran and cited nothing to fetch — and are
    recorded apart, so `calls` still counts assist dials."""

    def transport(url, headers, body, timeout=None):
        if url.endswith("/responses"):
            transport.search_calls.append((url, body))
            return {"output": []}
        transport.calls.append((url, body))
        return {"choices": [{"message": {"content": __import__("json").dumps(payload)}}]}

    transport.calls = []
    transport.search_calls = []
    return transport


def test_chain_community_first_and_labels(client, seeker, other):
    _add_tool(client, seeker)
    _add_tool(client, other)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Snap-on", "model": "QD3R250"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"] == ["community"]
    assert body["fields"]["category"] == {
        "value": "Torque",
        "source": "community",
        "detail": "2 owners agree",
        "supporters": 2,
    }
    assert body["ai_charged"] == 0


def test_chain_dark_layers_never_called(client, db, seeker, monkeypatch):
    called = []
    monkeypatch.setattr(
        lookup, "_upc_transport", lambda *a, **k: called.append("upc") or {}
    )
    monkeypatch.setattr(
        ai_service, "_transport", lambda *a, **k: called.append("ai") or {}
    )
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Unknown", "model": "ZZ-9", "upc": "012345678905"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    assert resp.json()["fields"] == {}
    assert called == []  # both outside layers are dark: never dialed


def test_chain_barcode_layer_supplements(client, db, seeker, monkeypatch):
    entitlements.set_setting(db, lookup.lookup_config.UPC_PROVIDER_KEY, "upcitemdb")
    entitlements.set_setting(
        db, lookup.lookup_config.UPC_API_KEY_REF_KEY, "WAVE4_TEST_UPC_KEY"
    )
    monkeypatch.setenv("WAVE4_TEST_UPC_KEY", "upc-key-not-real")
    db.commit()

    def fake_upc(url, headers, params):
        assert params["upc"] == "028399123456"
        return {
            "items": [
                {
                    "title": "Milwaukee M18 FUEL Impact",
                    "brand": "Milwaukee",
                    "model": "2967-20",
                    "category": "Hardware > Power Tools > Impacts",
                    "highest_recorded_price": 299.0,
                }
            ]
        }

    monkeypatch.setattr(lookup, "_upc_transport", fake_upc)
    resp = client.get(
        "/api/catalog/lookup",
        params={"upc": "028399123456"},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    assert body["fields"]["name"]["source"] == "barcode"
    assert body["fields"]["category"]["value"] == "Impacts"
    assert body["fields"]["msrp"]["value"] == 299.0


def test_chain_ai_supplements_and_charges_once(
    client, db, seeker, other, monkeypatch
):
    _configure_ai(db, monkeypatch, price_lookup=3)
    # Community covers category only (size/msrp disagreed away).
    _add_tool(client, seeker, size="", msrp=None)
    _add_tool(client, other, size="", msrp=None)
    transport = _fake_ai_transport(
        {"category": "AI-WRONG", "size": "3/8 in drive", "msrp": 310}
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    # Fund the wallet so the charge can land.
    from app.modules.billing import wallet

    wallet.credit(db, seeker.id, amount=10, bucket="banked", reason="test", ref="t")
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Snap-on", "model": " QD3R250 ".strip()},
        headers=auth_headers(seeker),
    )
    body = resp.json()
    # First hit wins: community keeps category; AI supplements size/msrp.
    assert body["fields"]["category"]["source"] == "community"
    assert body["fields"]["size"] == {
        "value": "3/8 in drive",
        "source": "ai",
        "detail": "AI suggestion — check it",
    }
    assert body["ai_charged"] == 3
    assert len(transport.calls) == 1
    view = wallet.wallet_view(db, seeker.id)
    assert view["banked_balance"] == 7


def test_chain_ai_failure_is_skipped_and_free(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch, price_lookup=5)

    def boom(url, headers, body, timeout=None):
        raise ai_service.AiProviderError("down")

    monkeypatch.setattr(ai_service, "_transport", boom)
    resp = client.get(
        "/api/catalog/lookup",
        params={"brand": "Nope", "model": "Nada"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    assert resp.json()["fields"] == {}
    assert resp.json()["ai_charged"] == 0


def test_identify_dark_seam_503(client, seeker):
    status_resp = client.get(
        "/api/catalog/ai-status", headers=auth_headers(seeker)
    )
    assert status_resp.json()["configured"] is False
    resp = client.post(
        "/api/catalog/identify",
        json={"text": "red cordless impact wrench, fuel line"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ai_not_configured"


def test_identify_with_mocked_provider(client, db, seeker, monkeypatch):
    _configure_ai(db, monkeypatch)
    transport = _fake_ai_transport(
        {
            "name": "M18 FUEL Impact Wrench",
            "brand": "Milwaukee",
            "model": "2967-20",
            "category": "Impact Wrenches",
        }
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    resp = client.post(
        "/api/catalog/identify",
        json={"text": "Milwaukee M18 Fuel half inch impact 2967-20"},
        headers=auth_headers(seeker),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"]["brand"]["value"] == "Milwaukee"
    assert body["fields"]["brand"]["detail"] == "AI suggestion — check it"
    status_resp = client.get(
        "/api/catalog/ai-status", headers=auth_headers(seeker)
    )
    view = status_resp.json()
    assert view["configured"] is True
    assert "sk-test" not in str(view)  # the key never leaves the server


def test_admin_settings_roundtrip_prices_and_lookup(client, db, operator):
    resp = client.put(
        "/api/admin/settings",
        json={
            "ai_price_lookup": 3,
            "ai_price_identify": 5,
            "lookup_upc_provider": "upcitemdb",
            "lookup_upc_api_key_ref": "UPCITEMDB_KEY",
        },
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai"]["prices"]["lookup"] == 3
    assert body["ai"]["prices"]["identify"] == 5
    assert body["lookup"]["upc_provider"] == "upcitemdb"
    # No manual-search settings exist anymore: web search rides
    # the AI seam (owner's one-vendor decision, 2026-10-25), so
    # the lookup view must not offer a search key slot.
    assert "manual_search_provider" not in body["lookup"]
    assert "manual_search_api_key_ref" not in body["lookup"]
    assert ai_service.price_for(db, "lookup") == 3
    assert ai_service.price_for(db, "report_summary") == 0
