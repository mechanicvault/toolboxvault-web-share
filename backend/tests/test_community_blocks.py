"""Community moderation (admin lane, owner ruling 2026-11-06
23:45): flags with notes, three-tier flag notifications, and
per-feature blocks.

Pins:

- FLAG → NOTIFY: a forum flag and a boards flag each fan a
  community_flag note out to moderators, moderator admins AND
  god (deliberately wider than the boards' admins-only
  new-post alert); the flagger hears nothing; a normal member
  hears nothing. The note carries the flagger's notes.
- BLOCK GATE: imposing or lifting a block takes a god or
  moderator_admin seat (route AND service); a moderator gets
  refused. God-rung accounts can't be blocked; nobody blocks
  themselves; a second active block on the same feature is
  refused; blocks resolve by exact account number too.
- ENFORCEMENT: a member blocked from the forums can't start a
  thread or reply there (422 with the plain-words refusal +
  the support-ticket road back) but CAN still post on the
  boards — blocks are per-feature; blocked from the boards,
  the reverse. The blocked member's inbox carries the notice
  naming the feature and the reinstatement road.
- LIFT: lifting restores posting, tells the member, and keeps
  the row (lifted, never deleted).
- PARKED PARTS: the machinery reserves the community_parts
  feature key but this lane touches no parts data — the parts
  tables don't even exist in the block flow.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import inbox, models as core_models
from app.modules.forum import blocks, models as forum_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(
    db,
    account_number,
    email,
    name="Blocks User",
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
def god(db):
    return _make_user(
        db, "TV-M-000951", "cb-god@example.com", "Gail God",
        role="community_admin", tier="god", is_operator=True,
    )


@pytest.fixture()
def mod_admin(db):
    return _make_user(
        db, "TV-M-000952", "cb-modadmin@example.com", "Adam Admin",
        role="community_admin", tier="moderator_admin",
    )


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000953", "cb-mod@example.com", "Maude Mod",
        role="moderator", tier="moderator",
    )


@pytest.fixture()
def poster(db):
    return _make_user(
        db, "TV-M-000954", "cb-poster@example.com", "Pete Poster"
    )


@pytest.fixture()
def pest(db):
    return _make_user(
        db, "TV-M-000955", "cb-pest@example.com", "Paul Pest"
    )


def _notes(db, user_id, kind):
    return list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == user_id,
                core_models.Notification.kind == kind,
            )
        )
    )


def _category(client, operator):
    response = client.post(
        "/api/forum/admin/categories",
        json={"name": "General Discussion", "description": "", "sort_order": 0},
        headers=auth_headers(operator),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _thread(client, user, category_id, title="Torque talk"):
    response = client.post(
        "/api/forum/threads",
        json={
            "category_id": category_id,
            "title": title,
            "body": "Opening post body.",
        },
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _board_post(client, user, title="Board post"):
    response = client.post(
        "/api/feedback/posts",
        json={"board": "bug", "title": title, "body": "Details here."},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- flag → notify -------------------------------------------------------


def test_forum_flag_notifies_whole_team(
    client, db, god, mod_admin, moderator, poster, pest
):
    category = _category(client, god)
    thread = _thread(client, pest, category["id"])
    post_id = thread["posts"][0]["id"]
    flagged = client.post(
        f"/api/forum/posts/{post_id}/report",
        json={"reason": "Spam — same link five times."},
        headers=auth_headers(poster),
    )
    assert flagged.status_code == 201, flagged.text
    for seat in (god, mod_admin, moderator):
        notes = _notes(db, seat.id, inbox.KIND_COMMUNITY_FLAG)
        assert len(notes) == 1, seat.account_number
        assert "Spam — same link five times." in notes[0].body
    assert _notes(db, poster.id, inbox.KIND_COMMUNITY_FLAG) == []
    assert _notes(db, pest.id, inbox.KIND_COMMUNITY_FLAG) == []


def test_board_flag_notifies_whole_team(
    client, db, god, mod_admin, moderator, poster, pest
):
    post = _board_post(client, pest)
    flagged = client.post(
        "/api/feedback/reports",
        json={
            "target_kind": "post",
            "target_id": post["id"],
            "reason": "Abuse in the comments.",
        },
        headers=auth_headers(poster),
    )
    assert flagged.status_code == 201, flagged.text
    for seat in (god, mod_admin, moderator):
        notes = _notes(db, seat.id, inbox.KIND_COMMUNITY_FLAG)
        assert len(notes) == 1, seat.account_number


# -- the block gate -------------------------------------------------------


def test_block_gate_seats(client, db, god, mod_admin, moderator, pest):
    # A moderator canNOT impose a block (route gate + service gate).
    refused = client.post(
        "/api/forum/mod/blocks",
        json={
            "user_id": str(pest.id),
            "feature": "forums",
            "reason": "Spam.",
        },
        headers=auth_headers(moderator),
    )
    assert refused.status_code == 403, refused.text
    with pytest.raises(blocks.BlockError):
        blocks.block_user(
            db, moderator, user_id=pest.id, feature="forums", reason="Spam."
        )
    # Moderator admin and god both can.
    made = client.post(
        "/api/forum/mod/blocks",
        json={
            "user_id": str(pest.id),
            "feature": "forums",
            "reason": "Repeated spam after a warning.",
        },
        headers=auth_headers(mod_admin),
    )
    assert made.status_code == 200, made.text
    assert made.json()["active"] is True


def test_block_refusals(client, db, god, mod_admin, pest):
    with pytest.raises(blocks.BlockError):
        blocks.block_user(
            db, god, user_id=god.id, feature="forums", reason="Self."
        )
    with pytest.raises(blocks.BlockError):
        blocks.block_user(
            db, mod_admin, user_id=god.id, feature="forums", reason="God."
        )
    with pytest.raises(blocks.BlockNotFound):
        blocks.block_user(
            db, god, account_number="TV-M-999999",
            feature="forums", reason="Ghost.",
        )
    blocks.block_user(
        db, god, user_id=pest.id, feature="forums", reason="Spam."
    )
    with pytest.raises(blocks.BlockError):
        blocks.block_user(
            db, god, user_id=pest.id, feature="forums", reason="Again."
        )
    # By exact account number works too (a second feature).
    view = blocks.block_user(
        db, god, account_number=pest.account_number,
        feature="feedback_boards", reason="Abuse.",
    )
    assert view["user_id"] == pest.id


# -- enforcement + notice + lift ------------------------------------------


def test_block_enforces_per_feature_and_lift_restores(
    client, db, god, mod_admin, moderator, poster, pest
):
    category = _category(client, god)
    thread = _thread(client, poster, category["id"])

    blocks.block_user(
        db, god, user_id=pest.id, feature="forums",
        reason="Flooding threads with spam links.",
    )
    # The notice names the feature and the road back.
    notes = _notes(db, pest.id, inbox.KIND_COMMUNITY_BLOCKED)
    assert len(notes) == 1
    assert "the community forums" in notes[0].title
    assert "support ticket" in notes[0].body

    # Forums writes refuse with the plain-words message...
    refused_thread = client.post(
        "/api/forum/threads",
        json={
            "category_id": category["id"],
            "title": "More spam",
            "body": "Buy now.",
        },
        headers=auth_headers(pest),
    )
    assert refused_thread.status_code == 422, refused_thread.text
    assert "support ticket" in refused_thread.text
    refused_reply = client.post(
        f"/api/forum/threads/{thread['id']}/replies",
        json={"body": "Spam reply."},
        headers=auth_headers(pest),
    )
    assert refused_reply.status_code == 422, refused_reply.text

    # ...but the boards are a different feature — still open.
    board_post = _board_post(client, pest, title="Pest on the boards")
    assert board_post["title"] == "Pest on the boards"

    # The queue reads the block; a moderator can SEE it.
    queue = client.get(
        "/api/forum/mod/blocks", headers=auth_headers(moderator)
    )
    assert queue.status_code == 200, queue.text
    assert len(queue.json()) == 1
    block_id = queue.json()[0]["id"]

    # The member can read their own standing.
    mine = client.get(
        "/api/forum/mod/my-blocks", headers=auth_headers(pest)
    )
    assert mine.status_code == 200
    assert len(mine.json()) == 1

    # A moderator cannot lift; a moderator admin can.
    mod_lift = client.post(
        f"/api/forum/mod/blocks/{block_id}/lift",
        headers=auth_headers(moderator),
    )
    assert mod_lift.status_code == 403, mod_lift.text
    lifted = client.post(
        f"/api/forum/mod/blocks/{block_id}/lift",
        headers=auth_headers(mod_admin),
    )
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["active"] is False

    # The row survives (lifted, never deleted), the member is
    # told, and posting works again.
    row = db.get(forum_models.CommunityBlock, uuid.UUID(block_id))
    assert row is not None and row.lifted_at is not None
    assert _notes(db, pest.id, inbox.KIND_COMMUNITY_UNBLOCKED)
    again = _thread(client, pest, category["id"], title="Pest returns")
    assert again["title"] == "Pest returns"


def test_board_block_enforces_boards_only(
    client, db, god, pest
):
    blocks.block_user(
        db, god, user_id=pest.id, feature="feedback_boards",
        reason="Abuse on the boards.",
    )
    refused = client.post(
        "/api/feedback/posts",
        json={"board": "bug", "title": "Nope", "body": "Trying anyway."},
        headers=auth_headers(pest),
    )
    assert refused.status_code == 422, refused.text
    assert "support ticket" in refused.text
    # Forums still open to them.
    category = _category(client, god)
    thread = _thread(client, pest, category["id"])
    assert thread["title"]


def test_community_parts_key_reserved_only(db, god, pest):
    # The vocabulary carries the parked module's key (machinery
    # ready to adopt), and blocking on it writes no parts data —
    # the block row is the only artifact.
    assert "community_parts" in blocks.FEATURES
    view = blocks.block_user(
        db, god, user_id=pest.id, feature="community_parts",
        reason="Pre-emptive test row.",
    )
    assert view["feature"] == "community_parts"
