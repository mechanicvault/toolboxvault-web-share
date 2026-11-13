"""Board visibility split (owner busy work #1, 2026-11-10).

Ryan's order: the community forums stay PUBLIC — anyone may
read them. The Bug Reports and Feature Requests boards are NOT
public: reading them (board lists AND individual posts) is for
registered users only, enforced on the server.

Pins:

- every feedback read face refuses anonymous callers with a
  401 — both boards, both posts, on the plain routes AND the
  /public twins — and no post title leaks in any refusal;
- registered members read exactly as before (exact-key
  payloads, both boards, detail + comments), including a
  DOWNLOADS-level account (its filing rights are pinned by
  test_open_signup_downloads_tier; here its reading is);
- the forum's public category list still serves the forum's
  own rooms in full, but the two permanent board rows carry
  NO feedback content for an anonymous audience — no counts,
  no latest-post title/activity — while a member audience
  gets the live counts + latest post as before;
- the forum's public thread list + search keep working
  signed-out (no regression on the public forum).
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.modules.core import models as core_models, tiers
from app.modules.forum import models as forum_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Vis User", tier=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role="user",
    )
    if tier is not None:
        user.tier = tier
        user.role = tiers.role_for_tier(tier)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(db, "TV-M-000901", "vis-poster@example.com", "Pete Poster")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000902", "vis-other@example.com", "Olga Other")


@pytest.fixture()
def downloader(db):
    return _make_user(
        db, "TV-MS-000903", "vis-down@example.com", "Dee Downloads",
        tier="downloads",
    )


def _post(client, user, board="bug", title="App crashes on save", body="Steps..."):
    response = client.post(
        "/api/feedback/posts",
        json={"board": board, "title": title, "body": body},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


READ_URLS = [
    "/api/feedback/boards/bug",
    "/api/feedback/boards/feature",
    "/api/feedback/public/boards/bug",
    "/api/feedback/public/boards/feature",
]


def test_anonymous_reads_refused_on_every_face(client, db, poster):
    bug = _post(client, poster)
    feature = _post(
        client, poster, board="feature", title="Dark mode for reports",
        body="Please",
    )
    urls = READ_URLS + [
        f"/api/feedback/posts/{bug['id']}",
        f"/api/feedback/public/posts/{bug['id']}",
        f"/api/feedback/posts/{feature['id']}",
        f"/api/feedback/public/posts/{feature['id']}",
        "/api/feedback/boards/bug?sort=top",
        "/api/feedback/public/boards/feature?status_filter=open",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 401, url
        assert "App crashes on save" not in response.text
        assert "Dark mode for reports" not in response.text
    # A garbage bearer <redacted> is anonymous too.
    bad = {"Authorization": "Bearer <redacted>"}
    for url in urls:
        response = client.get(url, headers=bad)
        assert response.status_code == 401, url


def test_member_reads_unchanged_exact_keys(client, db, poster, other):
    bug = _post(client, poster)
    _post(client, poster, board="feature", title="Dark mode", body="Please")
    rows = client.get("/api/feedback/boards/bug", headers=auth_headers(other))
    assert rows.status_code == 200
    row = rows.json()[0]
    assert set(row) == {
        "id", "board", "title", "body", "status", "closed", "status_note",
        "urgency", "author", "visibility", "vote_count",
        "comment_count", "voted_by_me", "mine", "created_at",
        "updated_at",
    }
    assert row["mine"] is False
    # The /public twin answers a member identically (the routes
    # stay; only the anonymous payload is gone).
    twin = client.get(
        "/api/feedback/public/boards/bug", headers=auth_headers(other)
    )
    assert twin.status_code == 200
    assert [r["id"] for r in twin.json()] == [bug["id"]]
    detail = client.get(
        f"/api/feedback/posts/{bug['id']}", headers=auth_headers(other)
    )
    assert detail.status_code == 200
    assert set(detail.json()) == set(row) | {"comments"}
    # The author's own read keeps the author flags.
    mine = client.get("/api/feedback/boards/bug", headers=auth_headers(poster))
    assert mine.json()[0]["mine"] is True


def test_downloads_member_reads_the_boards(client, db, poster, downloader):
    bug = _post(client, poster)
    rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(downloader)
    )
    assert rows.status_code == 200
    assert [r["id"] for r in rows.json()] == [bug["id"]]
    detail = client.get(
        f"/api/feedback/posts/{bug['id']}", headers=auth_headers(downloader)
    )
    assert detail.status_code == 200
    assert detail.json()["title"] == "App crashes on save"


# -- the forum board list ------------------------------------------------------


def _category(db, name, system_key=None, sort_order=0):
    row = forum_models.ForumCategory(
        id=uuid.uuid4(),
        name=name,
        description=f"About {name}",
        sort_order=sort_order,
        system_key=system_key,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def rooms(db):
    return {
        "bug": _category(db, "Bug Reports", system_key="bug_reports"),
        "feature": _category(
            db, "Feature Requests", system_key="feature_requests"
        ),
        "plain": _category(db, "Shop Talk"),
    }


def _forum_thread(db, category, author, title="Torque specs thread"):
    now = datetime.now(timezone.utc)
    thread = forum_models.ForumThread(
        id=uuid.uuid4(),
        category_id=category.id,
        author_id=author.id,
        title=title,
        last_post_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(thread)
    db.commit()
    post = forum_models.ForumPost(
        id=uuid.uuid4(),
        thread_id=thread.id,
        author_id=author.id,
        body="What torque for the head bolts?",
        status="visible",
        created_at=now,
        updated_at=now,
    )
    db.add(post)
    db.commit()
    return thread


def test_forum_categories_anonymous_board_rows_carry_no_content(
    client, db, poster, rooms
):
    bug = _post(client, poster)
    client.post(
        f"/api/feedback/posts/{bug['id']}/comments",
        json={"body": "Same here"},
        headers=auth_headers(poster),
    )
    _forum_thread(db, rooms["plain"], poster)

    anonymous = client.get("/api/forum/public/categories").json()
    by_name = {c["name"]: c for c in anonymous}
    for board_name in ("Bug Reports", "Feature Requests"):
        row = by_name[board_name]
        assert row["thread_count"] == 0
        assert row["post_count"] == 0
        assert row["last_thread_id"] is None
        assert row["last_thread_title"] is None
        assert row["last_activity_at"] is None
    # The forum's own rooms are untouched for the same audience.
    plain = by_name["Shop Talk"]
    assert plain["thread_count"] == 1
    assert plain["post_count"] == 1
    assert plain["last_thread_title"] == "Torque specs thread"
    # The optional face with no token blanks the boards too.
    optional = client.get("/api/forum/categories").json()
    assert {c["name"]: c for c in optional}["Bug Reports"][
        "last_thread_title"
    ] is None

    # A member audience gets the boards' live numbers as before:
    # 1 post + 1 comment on the bug board.
    member = client.get(
        "/api/forum/categories", headers=auth_headers(poster)
    ).json()
    bug_row = {c["name"]: c for c in member}["Bug Reports"]
    assert bug_row["thread_count"] == 1
    assert bug_row["post_count"] == 2
    assert bug_row["last_thread_title"] == "App crashes on save"
    assert bug_row["last_thread_id"] == bug["id"]


def test_public_forum_still_public(client, db, poster, rooms):
    thread = _forum_thread(db, rooms["plain"], poster)
    listed = client.get(
        f"/api/forum/public/categories/{rooms['plain'].id}/threads"
    )
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()] == [str(thread.id)]
    found = client.get("/api/forum/public/search", params={"q": "Torque"})
    assert found.status_code == 200
    assert [t["id"] for t in found.json()] == [str(thread.id)]
    detail = client.get(f"/api/forum/public/threads/{thread.id}")
    assert detail.status_code == 200
    # The board rows refuse thread listing for everyone — the
    # boards live on their own pages, as before.
    refused = client.get(
        f"/api/forum/public/categories/{rooms['bug'].id}/threads"
    )
    assert refused.status_code == 404
