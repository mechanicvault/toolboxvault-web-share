"""Open signup + the downloads level (owner order, 2026-11-09).

The confirmed model, proven piece by piece:

  * THE RUNG — a downloads account's applicable keys are exactly
    {"downloads"} (no normal inheritance), its stored rung
    resolves as downloads even though its role shadow reads
    "user", and the operator flag still derives god above it.
  * REACH — with migration 0096's seed shape in place as 0097
    amended it (prints + support + feedback lit for downloads,
    everything else dark), the level reaches exactly those
    three modules with NO account groups; my-modules agrees;
    a module route for anything else refuses 403
    module_unavailable; prints member writes (rate, comment)
    succeed; board writes (post, comment, report) succeed —
    the boards joined the level's standing definition by
    Ryan's boards-for-all order (2026-11-09, later the same
    day), as baseline plumbing, not a release event.
  * SETTINGS FOLLOW REACH — the module-owned profile fields
    (wizard_defaults, catalog_contribute) and the sharing writes
    refuse for an account that cannot reach the module, and pass
    for one that can; core profile writes are untouched.
  * THE RELEASE EVENT — an admin's off→on tier flip fires the
    badge merge, the scoped announcement (fan-out reaches only
    the accounts that gained the module, copy localized), and
    the wizard pending row; a flip that gains nobody (globally
    off) and an on→on re-flip fire nothing.
  * THE GRANT DOOR — an admin can move an account onto the
    downloads rung and back to normal (the launch move), and a
    role write never moves a downloads account's rung.
"""

import itertools
import uuid
from datetime import date

import pytest

from app.modules.core import (
    announcements,
    models as core_models,
    module_control,
    nav_badges,
    service,
    tiers,
)
from app.modules.prints import models as prints_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"

_counter = itertools.count(4000)


def _make_user(db, types, *, tier="normal", beta=False, operator=False, locale=""):
    n = next(_counter)
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=f"TV-T-{n:06d}",
        email=f"open-{n}-{uuid.uuid4().hex[:8]}@example.com",
        name=f"Open {n}",
        password_hash="not-a-real-hash",
        account_types=list(types),
        is_operator=operator,
        role=tiers.role_for_tier(tier),
        tier=tier,
        beta_tester=beta,
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _god(db):
    return _make_user(db, [MECHANIC], tier="god", operator=True)


def _seed_downloads_world(db):
    """Migration 0096's seed shape as 0097 amended it, for the
    modules these tests touch: every key explicit — prints,
    support and feedback ON for downloads, the rest OFF; the
    pre-existing keys at their global state (on)."""
    for module_id in (
        "prints",
        "support",
        "feedback",
        "inventory",
        "forum",
        "catalog",
    ):
        for key in ("normal", "moderator", "moderator_admin", "beta"):
            module_control.set_tier_assignment(db, module_id, key, True)
        module_control.set_tier_assignment(
            db,
            module_id,
            "downloads",
            module_id in ("prints", "support", "feedback"),
        )


def _effective(db, user, module_id):
    return module_control.effective_for_user(
        db,
        module_id,
        user.account_types,
        user_id=user.id,
        tier=tiers.resolved_tier(user),
        beta_tester=bool(user.beta_tester),
    )


# --------------------------------------------------------------------- #
# The rung
# --------------------------------------------------------------------- #


def test_downloads_keys_are_exactly_its_own():
    assert tiers.applicable_tier_keys("downloads", False) == frozenset(
        {"downloads"}
    )
    assert tiers.applicable_tier_keys("downloads", True) == frozenset(
        {"downloads", "beta"}
    )
    # And no higher rung inherits the downloads key.
    for rung in ("normal", "moderator", "moderator_admin"):
        assert "downloads" not in tiers.applicable_tier_keys(rung, False)


def test_stored_downloads_rung_resolves_as_downloads(db):
    user = _make_user(db, [], tier="downloads")
    assert user.role == "user"  # the community shadow
    assert tiers.resolved_tier(user) == "downloads"
    # The operator flag still outranks the restriction.
    user.is_operator = True
    assert tiers.resolved_tier(user) == "god"


def test_downloads_key_reads_no_fallback(db):
    # No tier rows anywhere: every pre-existing key reads the
    # global state; downloads reads OFF — opt-in only.
    switches = module_control.tier_switches(db, "inventory")
    assert switches["normal"] is True
    assert switches["downloads"] is False


def test_role_write_never_moves_a_downloads_rung(db):
    user = _make_user(db, [], tier="downloads")
    service.set_user_role(db, user, "user")
    db.refresh(user)
    assert user.tier == "downloads"
    # Even a moderator role write leaves the rung where it was —
    # the rung moves only through the grant machinery.
    service.set_user_role(db, user, "moderator")
    db.refresh(user)
    assert user.tier == "downloads"


def test_admin_can_grant_and_revoke_the_downloads_rung(client, db):
    actor = _god(db)
    target = _make_user(db, [MECHANIC])
    down = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "downloads"},
    )
    assert down.status_code == 200, down.text
    assert down.json()["tier"] == "downloads"
    up = client.post(
        f"/api/admin/users/{target.id}/tier",
        headers=auth_headers(actor),
        json={"tier": "normal"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["tier"] == "normal"


# --------------------------------------------------------------------- #
# Reach
# --------------------------------------------------------------------- #


def test_downloads_level_reach_is_prints_support_and_feedback(client, db):
    _seed_downloads_world(db)
    user = _make_user(db, [], tier="downloads")
    assert _effective(db, user, "prints") is True
    assert _effective(db, user, "support") is True
    assert _effective(db, user, "feedback") is True
    for module_id in ("inventory", "forum", "catalog", "claims", "dealers"):
        assert _effective(db, user, module_id) is False, module_id
    mine = client.get("/api/core/my-modules", headers=auth_headers(user))
    assert mine.status_code == 200
    assert {m["id"] for m in mine.json()} == {"prints", "support", "feedback"}


def test_downloads_user_refused_at_an_unreached_module_route(client, db):
    _seed_downloads_world(db)
    user = _make_user(db, [], tier="downloads")
    refused = client.get("/api/inventory/items", headers=auth_headers(user))
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "module_unavailable"


def test_downloads_user_can_rate_and_comment_on_prints(client, db):
    _seed_downloads_world(db)
    publisher = _make_user(db, [MECHANIC])
    downloader = _make_user(db, [], tier="downloads")
    print_file = prints_models.PrintFile(
        id=uuid.uuid4(),
        publisher_id=publisher.id,
        title="Swivel mount",
        description="",
        category_key="other-shop",
        status="live",
    )
    db.add(print_file)
    db.commit()
    rated = client.post(
        f"/api/prints/files/{print_file.id}/rate",
        headers=auth_headers(downloader),
        json={"stars": 5},
    )
    assert rated.status_code == 200, rated.text
    commented = client.post(
        f"/api/prints/files/{print_file.id}/comments",
        headers=auth_headers(downloader),
        json={"body": "Printed great, thanks."},
    )
    assert commented.status_code == 201, commented.text


def test_downloads_user_can_post_comment_and_report_on_the_boards(client, db):
    """Boards for all (owner order 2026-11-09): the downloads
    level's feedback cell is part of its standing definition
    (migration 0097), so a downloads account files on both
    boards, comments, and flags another member's post — the
    same writes any registered seat has."""
    _seed_downloads_world(db)
    downloader = _make_user(db, [], tier="downloads")
    headers = auth_headers(downloader)

    bug = client.post(
        "/api/feedback/posts",
        headers=headers,
        json={
            "board": "bug",
            "title": "Converter clears its result",
            "body": "Converting twice in a row clears the first result.",
        },
    )
    assert bug.status_code == 201, bug.text
    assert bug.json()["visibility"] == "visible"

    feature = client.post(
        "/api/feedback/posts",
        headers=headers,
        json={
            "board": "feature",
            "title": "A favorites shelf for wallpapers",
            "body": "Let members star wallpapers to find them again.",
        },
    )
    assert feature.status_code == 201, feature.text

    commented = client.post(
        f"/api/feedback/posts/{bug.json()['id']}/comments",
        headers=headers,
        json={"body": "Happens on my phone too, Safari."},
    )
    assert commented.status_code == 201, commented.text

    # Flagging rides the same gate: another member's post,
    # reported with a note, lands in the moderation queue.
    member = _make_user(db, [MECHANIC])
    theirs = client.post(
        "/api/feedback/posts",
        headers=auth_headers(member),
        json={
            "board": "bug",
            "title": "Truck page shows a stale balance",
            "body": "The balance did not move after a payment.",
        },
    )
    assert theirs.status_code == 201, theirs.text
    reported = client.post(
        "/api/feedback/reports",
        headers=headers,
        json={
            "target_kind": "post",
            "target_id": theirs.json()["id"],
            "reason": "Duplicate of my report above.",
        },
    )
    assert reported.status_code == 201, reported.text
    assert reported.json()["status"] == "open"


# --------------------------------------------------------------------- #
# Settings follow reach
# --------------------------------------------------------------------- #


def test_module_owned_profile_fields_follow_reach(client, db):
    _seed_downloads_world(db)
    downloader = _make_user(db, [], tier="downloads")
    headers = auth_headers(downloader)
    refused = client.patch(
        "/api/core/me", headers=headers, json={"wizard_defaults": {"x": 1}}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "module_unavailable"
    assert refused.json()["detail"]["module"] == "inventory"
    refused = client.patch(
        "/api/core/me", headers=headers, json={"catalog_contribute": False}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["module"] == "catalog"
    # Core profile writes are untouched by the rule.
    ok = client.patch("/api/core/me", headers=headers, json={"name": "Renamed"})
    assert ok.status_code == 200, ok.text

    mechanic = _make_user(db, [MECHANIC])
    headers = auth_headers(mechanic)
    assert (
        client.patch(
            "/api/core/me", headers=headers, json={"wizard_defaults": {"x": 1}}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/api/core/me", headers=headers, json={"catalog_contribute": False}
        ).status_code
        == 200
    )


def test_sharing_writes_follow_inventory_reach(client, db):
    _seed_downloads_world(db)
    downloader = _make_user(db, [], tier="downloads")
    refused = client.put(
        "/api/core/sharing/shop_company",
        headers=auth_headers(downloader),
        json={"enabled": True, "fields": []},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "module_unavailable"
    # The read stays open — losing reach never hides a setup.
    read = client.get("/api/core/sharing", headers=auth_headers(downloader))
    assert read.status_code == 200, read.text

    mechanic = _make_user(db, [MECHANIC])
    ok = client.put(
        "/api/core/sharing/shop_company",
        headers=auth_headers(mechanic),
        json={"enabled": True, "fields": []},
    )
    assert ok.status_code == 200, ok.text


# --------------------------------------------------------------------- #
# The release event
# --------------------------------------------------------------------- #


def _flip(client, actor, module_id, tier_key, enabled):
    return client.put(
        f"/api/admin/modules/{module_id}/tiers/{tier_key}",
        headers=auth_headers(actor),
        json={"enabled": enabled},
    )


def test_tier_flip_fires_the_full_release(client, db):
    _seed_downloads_world(db)
    actor = _god(db)
    downloader = _make_user(db, [], tier="downloads")
    spanish = _make_user(db, [], tier="downloads", locale="es")
    bystander = _make_user(db, [MECHANIC])  # normal rung: not the audience

    resp = _flip(client, actor, "forum", "downloads", True)
    assert resp.status_code == 200, resp.text

    # (a) The badge merged into the registry at today's date.
    assert nav_badges.get_nav_badges(db).get("forum") == date.today().isoformat()

    # (b) One scoped announcement, addressed to exactly the
    # accounts that gained the module.
    rows = db.query(core_models.FeatureAnnouncement).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.release_module_id == "forum"
    assert set(row.audience_user_ids) == {str(downloader.id), str(spanish.id)}
    assert row.title == "New feature: Community Forum"
    assert row.link == "/forum"

    # (c) The wizard pending rows.
    pending = {
        r.user_id
        for r in db.query(core_models.OnboardingProgress)
        .filter(core_models.OnboardingProgress.step_key == "module:forum")
        .all()
    }
    assert pending == {downloader.id, spanish.id}

    # The audience's world actually changed.
    assert _effective(db, downloader, "forum") is True
    mine = client.get("/api/core/my-modules", headers=auth_headers(downloader))
    assert "forum" in {m["id"] for m in mine.json()}

    # The fan-out reaches only the gained accounts, each in
    # their own language; the bystander hears nothing.
    sent = announcements.run_pending_announcements(db)
    assert sent == 1
    notes = db.query(core_models.Notification).all()
    by_user = {n.user_id: n for n in notes}
    assert set(by_user) == {downloader.id, spanish.id}
    assert by_user[downloader.id].title == "New feature: Community Forum"
    assert by_user[spanish.id].title == "Función nueva: Foro de la comunidad"
    db.refresh(row)
    assert row.status == "sent" and row.recipient_count == 2


def test_flip_that_gains_nobody_fires_nothing(client, db):
    _seed_downloads_world(db)
    actor = _god(db)
    _make_user(db, [], tier="downloads")
    # Wishlist is globally OFF: lighting its downloads cell
    # opens a door nobody can walk through — no event.
    db.add(core_models.ModuleState(module_id="wishlist", globally_enabled=False))
    db.commit()
    resp = _flip(client, actor, "wishlist", "downloads", True)
    assert resp.status_code == 200, resp.text
    assert db.query(core_models.FeatureAnnouncement).count() == 0
    assert "wishlist" not in nav_badges.get_nav_badges(db)
    assert (
        db.query(core_models.OnboardingProgress)
        .filter(core_models.OnboardingProgress.step_key == "module:wishlist")
        .count()
        == 0
    )


def test_reflip_and_darkening_fire_nothing(client, db):
    _seed_downloads_world(db)
    actor = _god(db)
    _make_user(db, [], tier="downloads")
    assert _flip(client, actor, "forum", "downloads", True).status_code == 200
    assert db.query(core_models.FeatureAnnouncement).count() == 1
    # On -> on again: not a release.
    assert _flip(client, actor, "forum", "downloads", True).status_code == 200
    assert db.query(core_models.FeatureAnnouncement).count() == 1
    # Off: never a release.
    assert _flip(client, actor, "forum", "downloads", False).status_code == 200
    assert db.query(core_models.FeatureAnnouncement).count() == 1
