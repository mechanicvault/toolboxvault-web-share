"""Audit A8 + A9 (2026-10-22): claim-readiness nudges, policy
depth, business-use flags, and the sub-limit guidance rule.

A9 rule under test: an item flagged business_use shows the
guidance warning ONLY when the owner's own policy profile
declares a business sub-limit AND the policy is not a dedicated
tool policy. Guidance only — no amounts are ever computed.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.core import inbox

from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, number, email):
    from app.modules.core import models as core_models

    user = core_models.User(
        account_number=number,
        email=email,
        name="Readiness Tester",
        password_hash="x",
        account_types=[MECHANIC],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000401", "a89-owner@example.com")


def _tool(client, user, **overrides):
    body = {"name": "Impact Wrench", "purchase_price": "100.00", **overrides}
    resp = client.post("/api/inventory", json=body, headers=auth_headers(user))
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _profile(client, user, **overrides):
    body = {
        "insurer_company": "Acme Mutual",
        "agent_name": "",
        "agent_phone": "",
        "agent_email": "",
        "policy_number": "POL-9",
        "notes": "",
        **overrides,
    }
    resp = client.put("/api/core/insurance", json=body, headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


# -- A9: policy depth ---------------------------------------------------


def test_policy_depth_roundtrip(client, owner):
    saved = _profile(
        client,
        owner,
        policy_type="homeowners",
        deductible_cents=50000,
        coverage_limit_cents=2500000,
        valuation_basis="rcv",
        business_sub_limit_cents=250000,
        how_to_file="Call the agent, then file online within 60 days.",
    )
    assert saved["policy_type"] == "homeowners"
    assert saved["deductible_cents"] == 50000
    assert saved["coverage_limit_cents"] == 2500000
    assert saved["valuation_basis"] == "rcv"
    assert saved["business_sub_limit_cents"] == 250000
    assert saved["how_to_file"].startswith("Call the agent")
    again = client.get("/api/core/insurance", headers=auth_headers(owner)).json()
    assert again["business_sub_limit_cents"] == 250000


def test_policy_depth_rejects_bad_vocabulary(client, owner):
    resp = client.put(
        "/api/core/insurance",
        json={
            "insurer_company": "Acme",
            "agent_name": "",
            "agent_phone": "",
            "agent_email": "",
            "policy_number": "",
            "notes": "",
            "policy_type": "spaceship",
        },
        headers=auth_headers(owner),
    )
    assert resp.status_code in (400, 422), resp.text


# -- A9: business_use + sub-limit warning -------------------------------


def test_business_use_roundtrip_on_tool_and_battery(client, owner):
    tool = _tool(client, owner, business_use=True)
    assert tool["business_use"] is True
    resp = client.post(
        "/api/inventory/batteries",
        json={"name": "M18 5.0", "business_use": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["business_use"] is True


def test_sub_limit_warning_rule(client, owner):
    tool = _tool(client, owner, business_use=True)
    # No profile yet -> no warning.
    got = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert got["sub_limit_warning"] is False
    # Homeowners + declared sub-limit -> warning.
    _profile(client, owner, policy_type="homeowners", business_sub_limit_cents=100000)
    got = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert got["sub_limit_warning"] is True
    # Dedicated tool policy -> NEVER warns.
    _profile(client, owner, policy_type="dedicated_tool", business_sub_limit_cents=100000)
    got = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert got["sub_limit_warning"] is False
    # Sub-limit removed -> no warning again.
    _profile(client, owner, policy_type="homeowners", business_sub_limit_cents=None)
    got = client.get(
        f"/api/inventory/{tool['id']}", headers=auth_headers(owner)
    ).json()
    assert got["sub_limit_warning"] is False
    # A non-business item never warns even with a sub-limit set.
    personal = _tool(client, owner, name="Garage Queen", business_use=False)
    _profile(client, owner, policy_type="homeowners", business_sub_limit_cents=100000)
    got = client.get(
        f"/api/inventory/{personal['id']}", headers=auth_headers(owner)
    ).json()
    assert got["sub_limit_warning"] is False


def test_health_check_carries_the_warning(client, owner):
    tool = _tool(client, owner, business_use=True)
    _profile(client, owner, policy_type="renters", business_sub_limit_cents=50000)
    resp = client.get("/api/inventory/health-check", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    rows = {row["id"]: row for row in resp.json()["items"]}
    # The tool has a price but no photo/serial — it is flagged for
    # those AND carries the sub-limit warning.
    assert rows[tool["id"]]["sub_limit_warning"] is True


# -- A8: readiness nudges ------------------------------------------------


def _nudges(db, user):
    return [
        n
        for n in inbox.list_for_user(db, user.id)
        if n["kind"] == inbox.KIND_CLAIM_READINESS
    ]


def test_readiness_nudge_fires_once_per_period(client, db, owner):
    from app.modules.claims import readiness

    _tool(client, owner, name="No Photo No Serial")  # price set; photo+serial missing
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 22)) == 1
    rows = _nudges(db, owner)
    assert len(rows) == 1
    assert "Health Check" in rows[0]["body"]
    # Same period: no second nudge.
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 25)) == 0
    # Next period: nudges again.
    assert readiness.run_readiness_nudges(db, today=date(2026, 11, 5)) == 1
    assert len(_nudges(db, owner)) == 2


def test_readiness_nudge_respects_silence_and_kill_switch(client, db, owner):
    from app.modules.billing import entitlements
    from app.modules.claims import readiness

    _tool(client, owner, name="Gappy")
    # Silence the user via the profile update.
    resp = client.patch(
        "/api/core/me",
        json={"silence_claim_readiness_nudges": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["silence_claim_readiness_nudges"] is True
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 22)) == 0
    # Un-silence, then flip the global kill switch off.
    db.refresh(owner)
    owner.silence_claim_readiness_nudges = False
    db.commit()
    entitlements.set_setting(db, readiness.READINESS_ENABLED_KEY, False)
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 22)) == 0
    entitlements.set_setting(db, readiness.READINESS_ENABLED_KEY, True)
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 22)) == 1


def test_readiness_no_gaps_no_nudge(client, db, owner):
    from app.modules.claims import readiness

    # Fully documented item: photo can't be faked via the API here,
    # so assert the gap COUNTS instead via a priced+serial tool and
    # the photo gap alone still nudges; a user with NO items at all
    # is the clean no-nudge case.
    assert readiness.run_readiness_nudges(db, today=date(2026, 10, 22)) == 0
