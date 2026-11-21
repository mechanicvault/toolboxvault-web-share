"""Admin thread-delete for the Community Forum (owner directive
2026-10-22: "Admin should have the ability to delete a thread
if i choose").

Pins:
- The gate is the ADMIN tier only: anonymous 401, plain member
  403, plain MODERATOR 403 (tombstoning posts is the moderator's
  ceiling — erasing a conversation is not), community_admin and
  operator pass.
- The delete is HARD and complete: thread row, every post, and
  every report on those posts go in one shot; the public +
  signed-in thread views 404, category listings + counts no
  longer see it, search forgets it, and the moderation queue
  reads cleanly afterwards (no dangling report).
- An audit row (forum.thread_delete) snapshots the title, the
  post count and the category — after the delete, the row is
  the only place the thread's name survives.
- D6-class regression: the thread's author (and a replier)
  deleting their ACCOUNTS after the thread was hard-deleted
  must not error — the tombstone seam finds nothing and the
  journal's dead-owner rule has nothing to trip on. Also the
  mirror image: hard-deleting a thread whose author ALREADY
  deleted their account (Former-member tombstone) works.
- Deleting an unknown (or already-deleted) thread is a 404 in
  the forum's usual style.
- A forum_reply notification that referenced the deleted thread
  still lists fine in the author's inbox (its thread_id rides
  in a JSON blob, no FK — the click lands on the thread 404).
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.forum import models as forum_models
from tests.conftest import auth_headers
from tests.test_forum import _category, _make_user, _reply, _thread

MECHANIC = "mechanic_technician"
SHOP = "shop_company"


@pytest.fixture()
def poster(db):
    return _make_user(
        db, "TV-M-002101", "tdposter@example.com", [MECHANIC], name="Pat Poster"
    )


@pytest.fixture()
def replier(db):
    return _make_user(
        db, "TV-S-002102", "tdreplier@example.com", [SHOP], name="Rae Replier"
    )


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-002103", "tdmod@example.com", [MECHANIC],
        name="Mo Moderator", role="moderator",
    )


@pytest.fixture()
def community_admin(db):
    return _make_user(
        db, "TV-M-002105", "tdcadmin@example.com", [MECHANIC],
        name="Cam CommunityAdmin", role="community_admin",
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-002104", "tdop@example.com", [MECHANIC],
        name="Olive Operator", operator=True,
    )


def _delete(client, user, thread_id):
    headers = auth_headers(user) if user is not None else None
    return client.delete(f"/api/forum/mod/threads/{thread_id}", headers=headers)


# -- the permission ladder ----------------------------------------------------


def test_delete_thread_permission_matrix(
    client, poster, replier, moderator, community_admin, operator
):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])

    assert _delete(client, None, thread["id"]).status_code == 401
    assert _delete(client, replier, thread["id"]).status_code == 403
    # The line Ryan drew: plain moderators do NOT get the eraser.
    assert _delete(client, moderator, thread["id"]).status_code == 403
    # Thread is untouched by the refused attempts.
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 200

    assert _delete(client, community_admin, thread["id"]).status_code == 204
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 404

    second = _thread(client, poster, category["id"], title="Second thread")
    assert _delete(client, operator, second["id"]).status_code == 204


# -- completeness ---------------------------------------------------------------


def test_delete_thread_removes_posts_reports_and_audits(
    client, db, poster, replier, moderator, operator
):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"], title="Doomed thread title")
    _reply(client, replier, thread["id"], body="First reply.")
    second = _reply(client, replier, thread["id"], body="Second reply.")
    assert second.status_code == 201, second.text

    reported = client.post(
        f"/api/forum/posts/{second.json()['id']}/report",
        json={"reason": "Spam"},
        headers=auth_headers(poster),
    )
    assert reported.status_code == 201, reported.text
    queue = client.get("/api/forum/mod/reports", headers=auth_headers(moderator))
    assert len(queue.json()) == 1

    gone = _delete(client, operator, thread["id"])
    assert gone.status_code == 204, gone.text

    # The rows themselves are gone — not tombstoned.
    assert db.get(forum_models.ForumThread, uuid.UUID(thread["id"])) is None
    assert (
        db.scalars(
            select(forum_models.ForumPost).where(
                forum_models.ForumPost.thread_id == uuid.UUID(thread["id"])
            )
        ).all()
        == []
    )
    assert (
        db.scalars(
            select(forum_models.ForumReport).where(
                forum_models.ForumReport.thread_id == uuid.UUID(thread["id"])
            )
        ).all()
        == []
    )

    # Both faces 404; the category forgets it; search forgets it.
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 404
    assert (
        client.get(
            f"/api/forum/threads/{thread['id']}", headers=auth_headers(poster)
        ).status_code
        == 404
    )
    listing = client.get(f"/api/forum/public/categories/{category['id']}/threads")
    assert listing.json() == []
    cats = client.get("/api/forum/public/categories").json()
    row = next(c for c in cats if c["id"] == category["id"])
    assert row["thread_count"] == 0
    assert row["post_count"] == 0
    assert row["last_thread_id"] is None
    found = client.get("/api/forum/public/search?q=Doomed")
    assert found.json() == []

    # The moderation queue reads cleanly — no dangling report.
    queue = client.get("/api/forum/mod/reports", headers=auth_headers(moderator))
    assert queue.status_code == 200
    assert queue.json() == []

    # The author's inbox still lists the forum_reply notification
    # the replies raised (dangling thread_id in its JSON data is
    # inert — the click-through lands on the thread's 404).
    inbox = client.get("/api/core/notifications", headers=auth_headers(poster))
    assert inbox.status_code == 200, inbox.text
    assert any(n["kind"] == "forum_reply" for n in inbox.json())

    # The audit row carries the snapshot.
    audit_rows = db.scalars(
        select(core_models.AuditLog).where(
            core_models.AuditLog.action == "forum.thread_delete"
        )
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_user_id == operator.id
    assert audit_rows[0].target == thread["id"]
    assert audit_rows[0].detail["title"] == "Doomed thread title"
    assert audit_rows[0].detail["posts"] == 3
    assert audit_rows[0].detail["category_id"] == category["id"]


def test_delete_keeps_sibling_thread_and_counts(
    client, poster, operator
):
    category = _category(client, operator)
    keep = _thread(client, poster, category["id"], title="Keep me")
    drop = _thread(client, poster, category["id"], title="Drop me")
    assert _delete(client, operator, drop["id"]).status_code == 204

    cats = client.get("/api/forum/public/categories").json()
    row = next(c for c in cats if c["id"] == category["id"])
    assert row["thread_count"] == 1
    assert row["post_count"] == 1
    assert row["last_thread_id"] == keep["id"]
    assert row["last_thread_title"] == "Keep me"
    assert client.get(f"/api/forum/public/threads/{keep['id']}").status_code == 200


# -- 404s + the D6-class regressions --------------------------------------------


def test_delete_unknown_and_already_deleted_thread_404(
    client, poster, community_admin, operator
):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])

    missing = _delete(client, operator, uuid.uuid4())
    assert missing.status_code == 404
    assert _delete(client, community_admin, thread["id"]).status_code == 204
    again = _delete(client, community_admin, thread["id"])
    assert again.status_code == 404


def test_account_deletion_after_thread_delete_does_not_error(
    client, poster, replier, operator
):
    """The D6 bug class, one step further: the thread is GONE
    (rows deleted, journal entries pointing at dead rows) when
    its author and a replier delete their accounts."""
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _reply(client, replier, thread["id"], body="A reply that will vanish.")

    assert _delete(client, operator, thread["id"]).status_code == 204

    for user in (poster, replier):
        deleted = client.request(
            "DELETE",
            "/api/core/me",
            json={"confirmation": "DELETE"},
            headers=auth_headers(user),
        )
        assert deleted.status_code == 204, deleted.text


def test_delete_thread_of_already_deleted_author(
    client, poster, replier, operator
):
    """The live D6 residue shape: a Former-member thread (author
    gone, posts tombstoned) must still be hard-deletable."""
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _reply(client, replier, thread["id"], body="Reply in a doomed thread.")

    deleted = client.request(
        "DELETE",
        "/api/core/me",
        json={"confirmation": "DELETE"},
        headers=auth_headers(poster),
    )
    assert deleted.status_code == 204, deleted.text
    view = client.get(f"/api/forum/public/threads/{thread['id']}").json()
    assert view["author"]["display_name"] == "Former member"

    assert _delete(client, operator, thread["id"]).status_code == 204
    assert client.get(f"/api/forum/public/threads/{thread['id']}").status_code == 404
