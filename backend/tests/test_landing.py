"""Public landing page (landing build, 2026-10-20).

Pins:
- The anonymous endpoint answers with NO auth and exposes ONLY
  the landing-public shape: seeded app-anchor prices for Pro,
  empty Business figures, trial switch OFF, empty store URLs,
  and the free item limit read from the plan catalog (change the
  catalog row and the page's number follows — never hardcoded).
- Admin -> Settings carries the landing block with the seeded
  defaults folded in; a PUT writes one audit row per changed key
  (the panel's standing pattern) and the public endpoint reflects
  the edit immediately — including the store-URL round trip
  (set -> appears -> cleared -> gone) the live smoke repeats.
- The landing keys are operator-only like every other setting.
"""

import uuid

import pytest

from app.core.security import hash_password
from app.modules.billing import models as billing_models
from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _seed_plans(db, free_limit=20):
    db.add_all(
        [
            billing_models.Plan(
                plan_key="free", name="Free", item_limit=free_limit,
                ai_monthly_credits=0, is_paid=False, sort_order=0,
            ),
            billing_models.Plan(
                plan_key="pro", name="Pro", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=1,
            ),
            billing_models.Plan(
                plan_key="business", name="Business", item_limit=None,
                ai_monthly_credits=0, is_paid=True, sort_order=2,
            ),
        ]
    )
    db.commit()


def _make_user(db, email, *, operator=False):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-M-{uuid.uuid4().hex[:6].upper()}",
        email=email,
        name="Landing User",
        password_hash=hash_password("landing-pass"),
        password_login_enabled=True,
        account_types=[MECHANIC],
        is_operator=operator,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def operator(db):
    _seed_plans(db)
    return _make_user(db, "op@example.com", operator=True)


@pytest.fixture()
def target(db):
    return _make_user(db, "target@example.com")


def _audit_count(client, operator, target_key):
    resp = client.get(
        "/api/admin/audit",
        params={"action": "setting.update", "limit": 200},
        headers=auth_headers(operator),
    )
    assert resp.status_code == 200
    return sum(
        1 for row in resp.json()["items"] if row["target"] == target_key
    )


# -- the anonymous endpoint ----------------------------------------------------


def test_landing_public_defaults_no_auth(db, client, operator):
    # No Authorization header at all — the page is for strangers.
    resp = client.get("/api/core/landing")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "pro_monthly_price": "7.99",
        "pro_yearly_price": "79.99",
        "business_monthly_price": "",
        "business_yearly_price": "",
        "self_serve_trial_enabled": False,
        "trial_copy": "",
        "app_store_url": "",
        "play_store_url": "",
        "free_item_limit": 20,
        # Teaser build (2026-10-26): the anonymous shape also
        # carries the front door's one boolean — never the code.
        "teaser_mode": False,
        # And the teaser trailer's URLs: empty unless the teaser
        # is on AND the operator has set a video.
        "teaser_video_url": "",
        "teaser_poster_url": "",
        # Free-access card gates (2026-10-31): both modules are
        # live by default, so the landing may advertise them.
        "marketplace_enabled": True,
        "community_parts_enabled": True,
    }


def test_landing_card_gates_follow_the_switchboard(db, client, operator):
    # Park Tools For Sale + My Parts (Community Parts rides the
    # parts module) through the operator control, exactly as
    # Admin -> Modules does, and the anonymous landing stops
    # advertising them; switch back on and the cards may return.
    for module_id in ("marketplace", "parts"):
        resp = client.put(
            f"/api/admin/modules/{module_id}/global",
            json={"enabled": False},
            headers=auth_headers(operator),
        )
        assert resp.status_code == 200, resp.text
    body = client.get("/api/core/landing").json()
    assert body["marketplace_enabled"] is False
    assert body["community_parts_enabled"] is False
    for module_id in ("marketplace", "parts"):
        resp = client.put(
            f"/api/admin/modules/{module_id}/global",
            json={"enabled": True},
            headers=auth_headers(operator),
        )
        assert resp.status_code == 200, resp.text
    body = client.get("/api/core/landing").json()
    assert body["marketplace_enabled"] is True
    assert body["community_parts_enabled"] is True


def test_landing_free_limit_follows_the_catalog(db, client):
    _seed_plans(db, free_limit=35)
    assert client.get("/api/core/landing").json()["free_item_limit"] == 35


def test_landing_free_limit_without_a_catalog_row(db, client):
    # A bare database (no plans seeded) still answers — the
    # documented fallback — instead of 500ing the public page.
    assert client.get("/api/core/landing").json()["free_item_limit"] == 20


# -- admin settings ----------------------------------------------------------


def test_admin_settings_view_carries_landing_defaults(db, client, operator):
    view = client.get(
        "/api/admin/settings", headers=auth_headers(operator)
    ).json()
    assert view["landing"] == {
        "pro_monthly_price": "7.99",
        "pro_yearly_price": "79.99",
        "business_monthly_price": "",
        "business_yearly_price": "",
        "self_serve_trial_enabled": False,
        "trial_copy": "",
        "app_store_url": "",
        "play_store_url": "",
    }


def test_landing_settings_roundtrip_and_audit(db, client, operator):
    updated = client.put(
        "/api/admin/settings",
        json={
            "landing_pro_monthly_price": "9.99",
            "landing_business_monthly_price": "49",
            "landing_self_serve_trial_enabled": True,
            "landing_trial_copy": "Try Pro free for 14 days.",
            "landing_app_store_url": "https://apps.apple.com/example",
        },
        headers=auth_headers(operator),
    )
    assert updated.status_code == 200
    landing = updated.json()["landing"]
    assert landing["pro_monthly_price"] == "9.99"
    assert landing["pro_yearly_price"] == "79.99"  # untouched -> default
    assert landing["business_monthly_price"] == "49"
    assert landing["self_serve_trial_enabled"] is True
    assert landing["trial_copy"] == "Try Pro free for 14 days."
    # One audit row per changed key, none for untouched keys.
    assert _audit_count(client, operator, "landing.pro_monthly_price") == 1
    assert _audit_count(client, operator, "landing.app_store_url") == 1
    assert _audit_count(client, operator, "landing.play_store_url") == 0
    # And the anonymous page tells the new truth immediately.
    public = client.get("/api/core/landing").json()
    assert public["pro_monthly_price"] == "9.99"
    assert public["self_serve_trial_enabled"] is True
    assert public["app_store_url"] == "https://apps.apple.com/example"


def test_landing_store_url_clear_hides_the_block(db, client, operator):
    client.put(
        "/api/admin/settings",
        json={"landing_play_store_url": "https://play.google.com/example"},
        headers=auth_headers(operator),
    )
    assert (
        client.get("/api/core/landing").json()["play_store_url"]
        == "https://play.google.com/example"
    )
    cleared = client.put(
        "/api/admin/settings",
        json={"landing_play_store_url": ""},
        headers=auth_headers(operator),
    )
    assert cleared.status_code == 200
    assert client.get("/api/core/landing").json()["play_store_url"] == ""


def test_landing_settings_require_operator(client, target):
    resp = client.put(
        "/api/admin/settings",
        json={"landing_pro_monthly_price": "0.01"},
        headers=auth_headers(target),
    )
    assert resp.status_code == 403
