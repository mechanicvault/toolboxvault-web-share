"""Forum favorites (widget options Wave 3, owner design
2026-11-02, Decision 2 — favorites as a real forum feature).

Pins:
- A member stars a forum thread OR a permanent board's post
  (the boards' posts are feedback rows — one favorites list
  holds both kinds); the star answers the target's LIVE face
  (title, board name, reply count, last activity).
- Starring is idempotent (one row per member + target);
  unstarring is idempotent too (no row = a successful no-op).
- Favorites are PRIVATE: another member's list never shows
  them, and their unstar can't touch my rows.
- Reads resolve live and drop invisible targets SILENTLY (the
  row stays; the door closes): a hard-deleted thread, a thread
  in an archived category, a held thread for anyone but its
  author/moderators, and board posts while the feedback module
  is globally off all vanish from the list without an error —
  and a removed (tombstoned) board post still resolves, like
  its page does.
- Starring something you cannot see is the surface's own 404
  (ids never leak); a kind that isn't a thread or a post is a
  friendly 422.
- The endpoints ride the forum module gate (403
  module_unavailable when the forum is globally off) and the
  forum kill switch (404) — but NOT the paid gate.
- Account deletion takes the member's favorites with it
  (tombstone_author).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.billing import entitlements
from app.modules.core import module_control
from app.modules.forum import models as forum_models
from app.modules.forum import service as forum_service
from tests.conftest import auth_headers
from tests.test_forum import _category, _make_user, _reply, _thread

MECHANIC = "mechanic_technician"
SHOP = "shop_company"

FAVORITE_KEYS = {
    "kind", "target_id", "title", "board_name", "reply_count",
    "last_activity_at", "starred_at",
}


@pytest.fixture()
def poster(db):
    return _make_user(
        db, "TV-M-002101", "favposter@example.com", [MECHANIC], name="Pat Poster"
    )


@pytest.fixture()
def replier(db):
    return _make_user(
        db, "TV-S-002102", "favreplier@example.com", [SHOP], name="Rae Replier"
    )


@pytest.fixture()
def operator(db):
    return _make_user(
        db, "TV-M-002104", "favop@example.com", [MECHANIC],
        name="Olive Operator", operator=True,
    )


def _star(client, user, kind, target_id, expect=201):
    response = client.post(
        "/api/forum/favorites",
        json={"kind": kind, "target_id": str(target_id)},
        headers=auth_headers(user),
    )
    assert response.status_code == expect, response.text
    return response


def _list(client, user):
    response = client.get("/api/forum/favorites", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def _unstar(client, user, kind, target_id, expect=204):
    response = client.delete(
        f"/api/forum/favorites/{kind}/{target_id}", headers=auth_headers(user)
    )
    assert response.status_code == expect, response.text
    return response


def _board_post(client, user, board="bug", **fields):
    payload = {
        "board": board,
        "title": fields.pop("title", "The app ate my receipt photo"),
        "body": fields.pop("body", "Steps to reproduce inside."),
    }
    payload.update(fields)
    response = client.post(
        "/api/feedback/posts", json=payload, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fav_rows(db, user_id):
    return int(
        db.scalar(
            select(func.count(forum_models.ForumFavorite.id)).where(
                forum_models.ForumFavorite.user_id == user_id
            )
        )
        or 0
    )


# -- the basic star / list / unstar cycle --------------------------------------


def test_star_thread_answers_live_face_and_lists(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    starred = _star(client, poster, "thread", thread["id"]).json()
    assert set(starred.keys()) == FAVORITE_KEYS
    assert starred["kind"] == "thread"
    assert starred["target_id"] == thread["id"]
    assert starred["title"] == thread["title"]
    assert starred["board_name"] == category["name"]
    assert starred["reply_count"] == 0

    mine = _list(client, poster)
    assert [row["target_id"] for row in mine] == [thread["id"]]


def test_star_is_idempotent_one_row(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    _star(client, poster, "thread", thread["id"])
    assert _fav_rows(db, poster.id) == 1
    assert len(_list(client, poster)) == 1


def test_unstar_and_unstar_again_is_a_no_op(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    _unstar(client, poster, "thread", thread["id"])
    assert _list(client, poster) == []
    assert _fav_rows(db, poster.id) == 0
    _unstar(client, poster, "thread", thread["id"])  # again: still 204


def test_reply_count_and_activity_are_live(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, replier, "thread", thread["id"])
    assert _list(client, replier)[0]["reply_count"] == 0
    reply = _reply(client, poster, thread["id"])
    assert reply.status_code == 201, reply.text
    assert _list(client, replier)[0]["reply_count"] == 1


def test_list_orders_by_most_recent_activity(
    client, db, poster, replier, operator
):
    category = _category(client, operator)
    older = _thread(client, poster, category["id"], title="Older thread")
    newer = _thread(client, poster, category["id"], title="Newer thread")
    _star(client, poster, "thread", older["id"])
    _star(client, poster, "thread", newer["id"])
    assert [r["target_id"] for r in _list(client, poster)] == [
        newer["id"],
        older["id"],
    ]
    # A fresh reply moves the older thread to the front.
    reply = _reply(client, replier, older["id"])
    assert reply.status_code == 201, reply.text
    assert [r["target_id"] for r in _list(client, poster)] == [
        older["id"],
        newer["id"],
    ]


# -- privacy -------------------------------------------------------------------


def test_favorites_are_private_to_the_member(client, db, poster, replier, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    assert _list(client, replier) == []
    # Someone else's unstar cannot touch my star.
    _unstar(client, replier, "thread", thread["id"])
    assert len(_list(client, poster)) == 1


# -- the boards' posts -----------------------------------------------------------


def test_star_board_post(client, db, poster, replier):
    post = _board_post(client, poster)
    starred = _star(client, replier, "post", post["id"]).json()
    assert set(starred.keys()) == FAVORITE_KEYS
    assert starred["kind"] == "post"
    assert starred["title"] == post["title"]
    assert starred["board_name"] == "Bug Reports"
    assert starred["reply_count"] == 0

    comment = client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Same here."},
        headers=auth_headers(poster),
    )
    assert comment.status_code == 201, comment.text
    assert _list(client, replier)[0]["reply_count"] == 1


def test_removed_board_post_still_resolves(client, db, poster):
    post = _board_post(client, poster)
    _star(client, poster, "post", post["id"])
    removed = client.delete(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    )
    assert removed.status_code == 200, removed.text
    # The post's page renders as a tombstone carrying the title —
    # the favorite resolves the same way, never a broken row.
    mine = _list(client, poster)
    assert [row["target_id"] for row in mine] == [post["id"]]
    assert mine[0]["title"] == post["title"]


def test_held_board_post_stars_only_for_its_author(client, db, poster, replier):
    post = _board_post(
        client,
        poster,
        title="Easy money",
        body="Visit https://bit.ly/easy-money now",
    )
    assert post["visibility"] == "held"
    _star(client, replier, "post", post["id"], expect=404)
    _star(client, poster, "post", post["id"])
    assert [r["target_id"] for r in _list(client, poster)] == [post["id"]]
    assert _list(client, replier) == []


# -- silent drops: the door closes, the row stays --------------------------------


def test_deleted_thread_drops_out_but_row_stays(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    deleted = client.delete(
        f"/api/forum/mod/threads/{thread['id']}", headers=auth_headers(operator)
    )
    assert deleted.status_code == 204, deleted.text
    assert _list(client, poster) == []
    assert _fav_rows(db, poster.id) == 1  # the star itself survives


def test_archived_category_drops_its_threads(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    archived = client.put(
        f"/api/forum/admin/categories/{category['id']}",
        json={"is_active": False},
        headers=auth_headers(operator),
    )
    assert archived.status_code == 200, archived.text
    assert _list(client, poster) == []


def test_held_thread_invisible_to_everyone_but_author(
    client, db, poster, replier, operator
):
    category = _category(client, operator)
    held = _thread(
        client,
        poster,
        category["id"],
        title="Easy money",
        body="Visit https://bit.ly/easy-money now",
    )
    assert held["held"] is True
    _star(client, replier, "thread", held["id"], expect=404)
    _star(client, poster, "thread", held["id"])
    assert [r["target_id"] for r in _list(client, poster)] == [held["id"]]


def test_feedback_switch_off_drops_board_posts_only(
    client, db, poster, operator
):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    post = _board_post(client, poster)
    _star(client, poster, "thread", thread["id"])
    _star(client, poster, "post", post["id"])
    module_control.set_global_enabled(db, "feedback", False)
    mine = _list(client, poster)
    assert [row["target_id"] for row in mine] == [thread["id"]]
    # And starring a board post while its module is off is a 404.
    other = _board_post_offline(db, poster)
    _star(client, poster, "post", other, expect=404)


def _board_post_offline(db, author):
    """A feedback post made straight in the session (the API is
    switched off in this test, so the row is built by hand)."""
    from app.modules.feedback import models as feedback_models

    row = feedback_models.FeedbackPost(
        id=uuid.uuid4(), board="bug", author_id=author.id,
        title="Offline-made post", body="body",
    )
    db.add(row)
    db.commit()
    return row.id


# -- refusals + gates -------------------------------------------------------------


def test_star_missing_targets_404_and_bad_kind_422(client, db, poster):
    _star(client, poster, "thread", uuid.uuid4(), expect=404)
    _star(client, poster, "post", uuid.uuid4(), expect=404)
    _star(client, poster, "bogus", uuid.uuid4(), expect=422)
    _unstar(client, poster, "bogus", uuid.uuid4(), expect=422)


def test_module_gate_and_kill_switch(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    # Kill switch: the forum's own setting off -> 404, like every
    # other forum surface.
    entitlements.set_setting(db, forum_service.FORUM_ENABLED_KEY, False)
    response = client.get("/api/forum/favorites", headers=auth_headers(poster))
    assert response.status_code == 404, response.text
    entitlements.set_setting(db, forum_service.FORUM_ENABLED_KEY, True)
    # Module globally off -> the require_module gate's 403.
    module_control.set_global_enabled(db, "forum", False)
    response = client.get("/api/forum/favorites", headers=auth_headers(poster))
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "module_unavailable"
    response = client.post(
        "/api/forum/favorites",
        json={"kind": "thread", "target_id": thread["id"]},
        headers=auth_headers(poster),
    )
    assert response.status_code == 403, response.text


def test_anonymous_gets_no_favorites(client, db, poster, operator):
    response = client.get("/api/forum/favorites")
    assert response.status_code == 401, response.text


# -- account deletion ---------------------------------------------------------------


def test_account_deletion_takes_favorites_with_it(client, db, poster, operator):
    category = _category(client, operator)
    thread = _thread(client, poster, category["id"])
    _star(client, poster, "thread", thread["id"])
    assert _fav_rows(db, poster.id) == 1
    forum_service.tombstone_author(db, poster.id)
    db.commit()
    assert _fav_rows(db, poster.id) == 0
