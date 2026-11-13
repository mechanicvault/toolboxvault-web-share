"""Wave 3 — feedback boards (Bug Reports + Feature Requests).

Ryan's original ruling: two boards, signed-in post, status
tracking, moderated. Reading was public until 2026-11-10 (busy
work #1 — the visibility split now lives in
test_board_visibility.py): the boards are MEMBERS-ONLY reading,
refused to anonymous callers server-side. Pins here:

- member read faces serve EXACT-key payloads with no email
  anywhere; boards are separate; held/removed content never
  leaks to other members' reads;
- posting is open to ANY signed-in account INCLUDING FREE — the
  deliberate deviation from the forum's paid gate (documented in
  the module docstring);
- posting still passes the spam screen + trust budgets (a held
  post is moderated like the forum's);
- upvotes: signed-in, one per user per post, toggle;
- status is set by moderators / community admins / operators
  ONLY, with an optional note, and the poster is notified;
- flat comments notify the poster + earlier commenters
  first-unread style;
- reports land in the moderation queue (dismiss / remove /
  tombstone like the forum); the module's export slice and the
  deletion tombstone ("Former member") round it out.
"""

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
DEALER = "tool_dealer"


def _make_user(db, account_number, email, name="Fb User", role="user", types=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=types or [MECHANIC],
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(db, "TV-M-000701", "fb-poster@example.com", "Pete Poster")


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000702", "fb-other@example.com", "Olga Other")


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000703", "fb-mod@example.com", "Maude Mod", role="moderator"
    )


def _post(client, user, board="bug", title="App crashes on save", body="Steps..."):
    response = client.post(
        "/api/feedback/posts",
        json={"board": board, "title": title, "body": body},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _notifications(db, user_id, kind):
    return list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == user_id,
                core_models.Notification.kind == kind,
            )
        )
    )


# -- member read ------------------------------------------------------------------


def test_member_read_exact_keys_no_email(client, db, poster, other):
    bug = _post(client, poster)
    feature = _post(
        client, poster, board="feature", title="Dark mode for reports",
        body="Please",
    )
    bugs = client.get("/api/feedback/boards/bug", headers=auth_headers(other))
    assert bugs.status_code == 200
    rows = bugs.json()
    assert [r["id"] for r in rows] == [bug["id"]]
    row = rows[0]
    assert set(row) == {
        "id", "board", "title", "body", "status", "closed", "status_note",
        "urgency",
        "author", "visibility", "vote_count", "comment_count",
        "voted_by_me", "mine", "created_at", "updated_at",
    }
    assert set(row["author"]) == {
        "user_id", "display_name", "account_number", "member_since", "role",
    }
    assert "email" not in json.dumps(rows)
    assert row["voted_by_me"] is False  # this member never voted
    assert row["mine"] is False

    features = client.get(
        "/api/feedback/boards/feature", headers=auth_headers(other)
    ).json()
    assert [r["id"] for r in features] == [feature["id"]]

    detail = client.get(
        f"/api/feedback/posts/{bug['id']}", headers=auth_headers(other)
    )
    assert detail.status_code == 200
    assert set(detail.json()) == set(row) | {"comments"}
    # Signed-out users cannot read, post, vote or comment (the
    # full anonymous refusal matrix is test_board_visibility's).
    assert client.get("/api/feedback/boards/bug").status_code == 401
    assert client.post(
        "/api/feedback/posts", json={"board": "bug", "title": "x", "body": "y"}
    ).status_code == 401
    assert client.post(f"/api/feedback/posts/{bug['id']}/vote").status_code == 401


# -- posting: any signed-in account (the deliberate deviation) -----------------------


def test_free_account_can_post(client, db):
    # No subscription rows exist for this user at all — the forum
    # would 402 here; feedback posts on purpose (Ryan's ruling).
    free = _make_user(db, "TV-M-000704", "fb-free@example.com", "Free Fred")
    posted = _post(client, free)
    assert posted["status"] == "open"
    assert posted["author"]["display_name"] == "Free Fred"


def test_spam_screen_holds_posts(client, db, poster, other, moderator):
    # bit.ly is on the spam firewall's DEFAULT blocked-domain list
    # (the same screen the forum + messaging use).
    held = client.post(
        "/api/feedback/posts",
        json={
            "board": "bug",
            "title": "Check this",
            "body": "Short link, big prize: https://bit.ly/claim-now",
        },
        headers=auth_headers(poster),
    )
    assert held.status_code == 201
    # Held: invisible on the board to other members, visible to
    # mods + author.
    assert client.get(
        "/api/feedback/boards/bug", headers=auth_headers(other)
    ).json() == []
    mine = client.get("/api/feedback/boards/bug", headers=auth_headers(poster))
    assert len(mine.json()) == 1
    queue = client.get("/api/feedback/mod/held", headers=auth_headers(moderator))
    assert [h["id"] for h in queue.json()] == [held.json()["id"]]
    released = client.post(
        f"/api/feedback/mod/targets/post/{held.json()['id']}/release",
        headers=auth_headers(moderator),
    )
    assert released.status_code == 200
    assert len(client.get(
        "/api/feedback/boards/bug", headers=auth_headers(other)
    ).json()) == 1


# -- votes ---------------------------------------------------------------------------


def test_votes_toggle_one_per_user(client, db, poster, other):
    post = _post(client, poster)
    first = client.post(
        f"/api/feedback/posts/{post['id']}/vote", headers=auth_headers(other)
    )
    assert first.json()["voted_by_me"] is True
    assert first.json()["vote_count"] == 1
    second = client.post(
        f"/api/feedback/posts/{post['id']}/vote", headers=auth_headers(poster)
    )
    assert second.json()["vote_count"] == 2
    # Toggle off.
    again = client.post(
        f"/api/feedback/posts/{post['id']}/vote", headers=auth_headers(other)
    )
    assert again.json()["voted_by_me"] is False
    assert again.json()["vote_count"] == 1


# -- status + notifications -------------------------------------------------------------


def test_status_flow_moderator_only_and_notifies(client, db, poster, other, moderator):
    post = _post(client, poster)
    refused = client.post(
        f"/api/feedback/posts/{post['id']}/status",
        json={"status": "planned"},
        headers=auth_headers(other),
    )
    assert refused.status_code == 403
    changed = client.post(
        f"/api/feedback/posts/{post['id']}/status",
        json={"status": "planned", "note": "On the roadmap"},
        headers=auth_headers(moderator),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "planned"
    assert changed.json()["status_note"] == "On the roadmap"
    notes = _notifications(db, poster.id, "feedback_status_changed")
    assert len(notes) == 1
    # A bogus status is refused.
    bogus = client.post(
        f"/api/feedback/posts/{post['id']}/status",
        json={"status": "shipped-ish"},
        headers=auth_headers(moderator),
    )
    assert bogus.status_code == 422


def test_comments_notify_poster_and_commenters_once(client, db, poster, other):
    post = _post(client, poster)
    third = _make_user(db, "TV-M-000705", "fb-third@example.com", "Tess Third")
    client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Same here"},
        headers=auth_headers(other),
    )
    assert len(_notifications(db, poster.id, "feedback_comment")) == 1
    # A second comment while the first notification is unread does
    # NOT stack a duplicate (first-unread style).
    client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Me too"},
        headers=auth_headers(third),
    )
    assert len(_notifications(db, poster.id, "feedback_comment")) == 1
    # The earlier commenter hears about the newer one.
    assert len(_notifications(db, other.id, "feedback_comment")) == 1
    # The poster commenting on their own post notifies nobody new.
    client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Update from me"},
        headers=auth_headers(poster),
    )
    assert len(_notifications(db, poster.id, "feedback_comment")) == 1

    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert [c["body"] for c in detail["comments"]] == [
        "Same here", "Me too", "Update from me",
    ]


def test_my_posts_filter(client, db, poster, other):
    _post(client, poster)
    _post(client, poster, board="feature", title="Second", body="B")
    _post(client, other, title="Not mine", body="B")
    mine = client.get("/api/feedback/mine", headers=auth_headers(poster))
    assert len(mine.json()) == 2
    bugs_only = client.get(
        "/api/feedback/mine", params={"board": "bug"}, headers=auth_headers(poster)
    )
    assert len(bugs_only.json()) == 1


# -- moderation: reports -------------------------------------------------------------------


def test_reports_queue_dismiss_and_remove(client, db, poster, other, moderator):
    post = _post(client, poster)
    report = client.post(
        "/api/feedback/reports",
        json={"target_kind": "post", "target_id": post["id"], "reason": "Spam"},
        headers=auth_headers(other),
    )
    assert report.status_code == 201, report.text
    # A duplicate open report from the same reporter is refused.
    dupe = client.post(
        "/api/feedback/reports",
        json={"target_kind": "post", "target_id": post["id"], "reason": "Spam"},
        headers=auth_headers(other),
    )
    assert dupe.status_code == 422
    queue = client.get("/api/feedback/mod/reports", headers=auth_headers(moderator))
    assert len(queue.json()) == 1
    # Plain users can't see the queue.
    assert client.get(
        "/api/feedback/mod/reports", headers=auth_headers(other)
    ).status_code == 403

    removed = client.post(
        f"/api/feedback/mod/targets/post/{post['id']}/remove",
        json={"reason": "Spam"},
        headers=auth_headers(moderator),
    )
    assert removed.status_code == 200
    # The post leaves the board as CONTENT (tombstone shell only,
    # body wiped); the report resolved.
    board_rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(poster)
    ).json()
    assert [r["visibility"] for r in board_rows] == ["removed_mod"]
    assert board_rows[0]["body"] == ""
    queue = client.get("/api/feedback/mod/reports", headers=auth_headers(moderator))
    assert queue.json() == []
    # The author's own view shows the tombstone shell (the forum
    # rule): the row stands, title + body wiped.
    mine = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    )
    assert mine.status_code == 200
    assert mine.json()["visibility"] == "removed_mod"
    assert mine.json()["body"] == ""

    # Dismiss path on a fresh report.
    second = _post(client, poster, title="Another", body="B")
    report2 = client.post(
        "/api/feedback/reports",
        json={"target_kind": "post", "target_id": second["id"], "reason": "Meh"},
        headers=auth_headers(other),
    ).json()
    dismissed = client.post(
        f"/api/feedback/mod/reports/{report2['id']}/dismiss",
        json={"note": "Not a violation"},
        headers=auth_headers(moderator),
    )
    assert dismissed.json()["status"] == "dismissed"
    visible = [
        r
        for r in client.get(
            "/api/feedback/boards/bug", headers=auth_headers(other)
        ).json()
        if r["visibility"] == "visible"
    ]
    assert [r["title"] for r in visible] == ["Another"]


def test_author_can_delete_own_post(client, db, poster, other):
    post = _post(client, poster)
    assert client.delete(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(other)
    ).status_code == 404
    deleted = client.delete(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    )
    assert deleted.status_code == 200
    assert deleted.json()["visibility"] == "removed_author"
    assert deleted.json()["body"] == ""
    # The tombstone row still stands on the board (forum rule).
    rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(poster)
    ).json()
    assert [r["visibility"] for r in rows] == ["removed_author"]


# -- export + deletion tombstone -------------------------------------------------------------


def test_export_and_deletion_tombstone(client, db, poster, other):
    post = _post(client, poster)
    client.post(
        f"/api/feedback/posts/{post['id']}/vote", headers=auth_headers(other)
    )
    client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Watching this"},
        headers=auth_headers(poster),
    )
    exported = client.get("/api/core/export", headers=auth_headers(poster))
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = archive.namelist()
        payload = json.loads(archive.read("feedback.json"))
    assert "feedback.json" in names
    assert [p["title"] for p in payload["posts"]] == ["App crashes on save"]
    assert [c["body"] for c in payload["comments"]] == ["Watching this"]

    # Deleting the account tombstones the author as Former member
    # and wipes the bodies — the post shell stays on the board
    # (the forum rule: boards never break).
    from app.modules.core import service as core_service

    core_service.delete_account(db, poster)
    rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(other)
    ).json()
    assert len(rows) == 1
    assert rows[0]["author"]["display_name"] == "Former member"
    assert rows[0]["author"]["account_number"] == ""
    assert rows[0]["body"] == ""
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(other)
    ).json()
    assert detail["comments"][0]["body"] == ""
    assert detail["comments"][0]["author"]["display_name"] == "Former member"


def test_module_gate_hides_boards_when_disabled(client, db, poster):
    _post(client, poster)
    operator = _make_user(
        db, "TV-M-000706", "fb-op@example.com", "Opal Op", types=[MECHANIC]
    )
    operator.is_operator = True
    db.commit()
    toggled = client.put(
        "/api/admin/modules/feedback/global",
        json={"enabled": False},
        headers=auth_headers(operator),
    )
    assert toggled.status_code == 200, toggled.text
    # The auth gate runs before the module switch: a signed-out
    # caller gets the 401 and learns nothing about the module's
    # state; a member gets the switch's 404.
    assert client.get("/api/feedback/public/boards/bug").status_code == 401
    assert client.get(
        "/api/feedback/boards/bug", headers=auth_headers(poster)
    ).status_code == 404
