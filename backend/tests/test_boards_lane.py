"""Boards lane (owner orders, 2026-11-06 22:40–22:58): the
Bug Reports + Feature Requests boards upgrade.

Pins:

- URGENCY: a post carries the filer's urgency (low | medium |
  high, default medium) in every payload; the filer picks it
  at submission and has NO edit path afterwards (a member
  token gets 403 from the urgency route — the route is
  moderator-gated); moderators / community_admins /
  operators can move it; a bogus value is a 422.
- SORT: board lists sort newest-first by default and
  most-upvoted first with sort=top (ties fall back to
  newest); an unknown sort is a 422. Applies to both boards,
  both read faces, and /mine.
- ADMIN NOTIFICATIONS: creating a post fans a
  feedback_new_post note titled "New bug report: {title}" /
  "New feature request: {title}" out to god +
  moderator_admin accounts ONLY — moderators and normal
  users hear nothing, the filer never hears about their own
  post, and the kind's email twin defaults OFF (community
  category).
- BOARD ORDER: the forum category list reads Bug Reports,
  Feature Requests, General, then the rest in operator
  order — whatever the stored sort_order values say.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import inbox, models as core_models, notification_prefs
from app.modules.forum import models as forum_models
from app.modules.forum import service as forum_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(
    db,
    account_number,
    email,
    name="Boards User",
    role="user",
    tier=None,
    is_operator=False,
):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role=role,
        is_operator=is_operator,
    )
    if tier is not None:
        user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(db, "TV-M-000801", "boards-poster@example.com", "Pete Poster")


@pytest.fixture()
def voter(db):
    return _make_user(db, "TV-M-000802", "boards-voter@example.com", "Vera Voter")


@pytest.fixture()
def third(db):
    return _make_user(db, "TV-M-000806", "boards-third@example.com", "Theo Third")


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000803", "boards-mod@example.com", "Maude Mod",
        role="moderator", tier="moderator",
    )


@pytest.fixture()
def mod_admin(db):
    return _make_user(
        db, "TV-M-000804", "boards-modadmin@example.com", "Adam Admin",
        role="community_admin", tier="moderator_admin",
    )


@pytest.fixture()
def god(db):
    return _make_user(
        db, "TV-M-000805", "boards-god@example.com", "Gail God",
        role="community_admin", tier="god", is_operator=True,
    )


def _post(client, user, board="bug", title="App crashes on save", body="Steps...", **extra):
    response = client.post(
        "/api/feedback/posts",
        json={"board": board, "title": title, "body": body, **extra},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _notes(db, user_id, kind=inbox.KIND_FEEDBACK_NEW_POST):
    return list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == user_id,
                core_models.Notification.kind == kind,
            )
        )
    )


# -- urgency ----------------------------------------------------------------------


def test_urgency_defaults_to_medium_and_rides_every_payload(client, db, poster):
    post = _post(client, poster)
    assert post["urgency"] == "medium"
    # Member reads (the boards are members-only reading since
    # 2026-11-10 — the public twins refuse anonymously).
    listed = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(poster)
    ).json()
    assert listed[0]["urgency"] == "medium"
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert detail["urgency"] == "medium"


def test_urgency_chosen_at_filing(client, db, poster):
    post = _post(client, poster, urgency="high")
    assert post["urgency"] == "high"
    low = _post(
        client, poster, board="feature", title="Dark mode", body="Please",
        urgency="low",
    )
    assert low["urgency"] == "low"


def test_urgency_bogus_value_refused(client, db, poster):
    response = client.post(
        "/api/feedback/posts",
        json={"board": "bug", "title": "x", "body": "y", "urgency": "whenever"},
        headers=auth_headers(poster),
    )
    assert response.status_code == 422


def test_filer_cannot_edit_urgency_after_submission(client, db, poster):
    post = _post(client, poster, urgency="low")
    # The poster is a plain member: the urgency route is the
    # moderator ladder's, so the filer's own token is refused.
    response = client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "high"},
        headers=auth_headers(poster),
    )
    assert response.status_code == 403
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert detail["urgency"] == "low"


def test_moderator_and_admin_can_edit_urgency(client, db, poster, moderator, mod_admin, god):
    post = _post(client, poster)
    by_mod = client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "high"},
        headers=auth_headers(moderator),
    )
    assert by_mod.status_code == 200, by_mod.text
    assert by_mod.json()["urgency"] == "high"
    by_admin = client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "low"},
        headers=auth_headers(mod_admin),
    )
    assert by_admin.status_code == 200
    assert by_admin.json()["urgency"] == "low"
    by_god = client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "medium"},
        headers=auth_headers(god),
    )
    assert by_god.status_code == 200
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert detail["urgency"] == "medium"
    # A bogus value from a moderator is still a 422.
    bogus = client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "critical"},
        headers=auth_headers(moderator),
    )
    assert bogus.status_code == 422


def test_urgency_edit_is_quiet_for_the_poster(client, db, poster, moderator):
    post = _post(client, poster)
    client.post(
        f"/api/feedback/posts/{post['id']}/urgency",
        json={"urgency": "high"},
        headers=auth_headers(moderator),
    )
    db.expire_all()
    assert _notes(db, poster.id, kind=inbox.KIND_FEEDBACK_STATUS) == []
    assert _notes(db, poster.id) == []


# -- most-upvoted sort --------------------------------------------------------------


def test_sort_top_orders_by_votes_then_newest(client, db, poster, voter, third):
    # The firewall's new-account budget is 2 posts an hour, so
    # the cast spreads across three authors.
    quiet = _post(client, poster, title="Quiet one", body="...")
    also_mine = _post(client, poster, title="Also mine", body="...")
    loud = _post(client, voter, title="Loud one", body="...")
    _post(client, third, title="Newest one", body="...")
    client.post(f"/api/feedback/posts/{loud['id']}/vote", headers=auth_headers(poster))
    client.post(f"/api/feedback/posts/{loud['id']}/vote", headers=auth_headers(third))
    client.post(f"/api/feedback/posts/{quiet['id']}/vote", headers=auth_headers(voter))
    client.post(f"/api/feedback/posts/{also_mine['id']}/vote", headers=auth_headers(third))

    default = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(voter)
    ).json()
    assert [r["title"] for r in default] == [
        "Newest one", "Loud one", "Also mine", "Quiet one",
    ]

    topped = client.get(
        "/api/feedback/boards/bug?sort=top", headers=auth_headers(voter)
    ).json()
    assert [r["title"] for r in topped] == [
        "Loud one", "Also mine", "Quiet one", "Newest one",
    ]
    assert [r["vote_count"] for r in topped] == [2, 1, 1, 0]

    # The /public twin serves a member the same sort (the routes
    # stay; only the anonymous payload is gone).
    twinned = client.get(
        "/api/feedback/public/boards/bug?sort=top",
        headers=auth_headers(third),
    ).json()
    assert [r["title"] for r in twinned] == [
        "Loud one", "Also mine", "Quiet one", "Newest one",
    ]

    # /mine honors it too (the poster's pair, tie broken newest-first).
    mine = client.get(
        "/api/feedback/mine?board=bug&sort=top", headers=auth_headers(poster)
    ).json()
    assert [r["title"] for r in mine] == ["Also mine", "Quiet one"]


def test_sort_unknown_value_refused(client, db, poster):
    _post(client, poster)
    response = client.get(
        "/api/feedback/boards/bug?sort=oldest", headers=auth_headers(poster)
    )
    assert response.status_code == 422


def test_sort_top_is_per_board(client, db, poster, voter):
    bug = _post(client, poster, title="Bug with a fan", body="...")
    _post(client, poster, board="feature", title="Feature nobody voted", body="...")
    client.post(f"/api/feedback/posts/{bug['id']}/vote", headers=auth_headers(voter))
    features = client.get(
        "/api/feedback/boards/feature?sort=top", headers=auth_headers(poster)
    ).json()
    assert [r["title"] for r in features] == ["Feature nobody voted"]


# -- admin notifications --------------------------------------------------------------


def test_new_post_notifies_admin_tiers_only(client, db, poster, voter, moderator, mod_admin, god):
    post = _post(client, poster, title="Checkout button misaligned")
    db.expire_all()
    god_notes = _notes(db, god.id)
    assert len(god_notes) == 1
    assert god_notes[0].title == "New bug report: Checkout button misaligned"
    assert god_notes[0].data["post_id"] == post["id"]
    assert god_notes[0].data["board"] == "bug"
    admin_notes = _notes(db, mod_admin.id)
    assert len(admin_notes) == 1
    # The moderator rung and plain members are NOT in the audience.
    assert _notes(db, moderator.id) == []
    assert _notes(db, voter.id) == []
    # The filer never hears about their own post.
    assert _notes(db, poster.id) == []


def test_new_feature_post_notification_title(client, db, poster, god):
    _post(client, poster, board="feature", title="Dark mode for reports", body="Please")
    db.expire_all()
    notes = _notes(db, god.id)
    assert len(notes) == 1
    assert notes[0].title == "New feature request: Dark mode for reports"


def test_admin_who_posts_does_not_notify_themselves(client, db, god, mod_admin):
    _post(client, god, title="God files a bug", body="...")
    db.expire_all()
    assert _notes(db, god.id) == []
    assert len(_notes(db, mod_admin.id)) == 1


def test_new_post_kind_email_twin_defaults_off(db, god):
    # The kind rides the community category, whose email
    # default is off — the alert is an inbox/bell note unless
    # an admin opts into email twins.
    assert (
        notification_prefs.category_for_kind(inbox.KIND_FEEDBACK_NEW_POST)
        == notification_prefs.CATEGORY_COMMUNITY
    )
    assert (
        notification_prefs.email_enabled_for_kind(
            db, god.id, inbox.KIND_FEEDBACK_NEW_POST
        )
        is False
    )


def test_new_post_notification_links_to_the_post(client, db, poster, god):
    post = _post(client, poster, title="Link me", body="...")
    inbox_rows = client.get(
        "/api/core/notifications", headers=auth_headers(god)
    ).json()
    mine = [r for r in inbox_rows if r["kind"] == inbox.KIND_FEEDBACK_NEW_POST]
    assert len(mine) == 1
    assert mine[0]["link"] == f"/feedback/post/{post['id']}"


# -- board order ----------------------------------------------------------------------


def _category(db, name, sort_order, system_key=None, category_id=None):
    row = forum_models.ForumCategory(
        id=category_id or uuid.uuid4(),
        name=name,
        description=f"About {name}",
        sort_order=sort_order,
        system_key=system_key,
        is_active=True,
    )
    db.add(row)
    db.commit()
    return row


def test_board_order_boards_then_general_then_rest(db):
    # Adversarial operator order: the general room sorts
    # FIRST by sort_order and the boards LAST — the owner's
    # order still wins on the reading surface.
    _category(db, "Tool Talk", 5)
    _category(
        db, "General Discussion", 1,
        category_id=forum_service.GENERAL_CATEGORY_ID,
    )
    _category(db, "Feature Requests", 90, system_key="feature_requests")
    _category(db, "Bug Reports", 80, system_key="bug_reports")
    _category(db, "Shop Talk", 3)
    names = [c["name"] for c in forum_service.list_categories(db)]
    assert names == [
        "Bug Reports",
        "Feature Requests",
        "General Discussion",
        "Shop Talk",
        "Tool Talk",
    ]


def test_board_order_without_boards_keeps_operator_order(db):
    _category(db, "Tool Talk", 20)
    _category(db, "Shop Talk", 10)
    names = [c["name"] for c in forum_service.list_categories(db)]
    assert names == ["Shop Talk", "Tool Talk"]
