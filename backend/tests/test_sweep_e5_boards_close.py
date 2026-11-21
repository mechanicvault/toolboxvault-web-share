"""Sweep E5 — boards close-on-decision (busy-work #7, 2026-11-12).

Ryan's spec: on the Bug Reports and Feature Requests boards,
marking a post done OR declined closes it in the SAME action (no
separate close step); the poster sees it's closed; comments lock
on closed posts (thread stays readable); reopening (status back
to an active one) un-closes in the same action; the board
assistant watcher sees `closed` plainly in the payloads it reads.

Representation (lane decision, recorded in the lane INDEX):
closure is DERIVED from status — done/declined are the only
closed statuses — via models.is_closed, the one test every read
surface shares. No stored flag, no migration, nothing to drift.

Pins here:
- `closed` (boolean, that exact name) rides the post payload on
  BOTH watcher read faces — GET /api/feedback/boards/<board> and
  GET /api/feedback/posts/<id> — plus /mine and the export slice;
- done closes a bug post and declined closes a feature post in
  the set_status action itself; every active status reads open;
- a comment on a closed post is refused with the plain reason,
  whoever writes it, while the thread stays readable;
- reopening (back to in_progress) un-closes everywhere and
  comments flow again;
- the poster's status note says the post is closed when it is —
  in the poster's own language only (EN + ES pins).
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.core import models as core_models
from app.modules.feedback import service as feedback_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"


def _make_user(db, account_number, email, name="Fb User", role="user", locale=""):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        role=role,
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(db, "TV-M-000801", "e5-poster@example.com", "Pete Poster")


@pytest.fixture()
def poster_es(db):
    return _make_user(
        db, "TV-M-000804", "e5-poster-es@example.com", "Pablo Cartel", locale="es"
    )


@pytest.fixture()
def other(db):
    return _make_user(db, "TV-M-000802", "e5-other@example.com", "Olga Other")


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000803", "e5-mod@example.com", "Maude Mod", role="moderator"
    )


def _post(client, user, board="bug", title="App crashes on save", body="Steps..."):
    response = client.post(
        "/api/feedback/posts",
        json={"board": board, "title": title, "body": body},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_status(client, moderator, post_id, status, note=""):
    response = client.post(
        f"/api/feedback/posts/{post_id}/status",
        json={"status": status, "note": note},
        headers=auth_headers(moderator),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _comment(client, user, post_id, body="Me too — same crash."):
    return client.post(
        f"/api/feedback/posts/{post_id}/comments",
        json={"body": body},
        headers=auth_headers(user),
    )


def _status_notes(db, user_id):
    return list(
        db.scalars(
            select(core_models.Notification)
            .where(
                core_models.Notification.user_id == user_id,
                core_models.Notification.kind == "feedback_status_changed",
            )
            .order_by(core_models.Notification.created_at)
        )
    )


# -- the watcher contract: `closed` on both read faces -------------------------


def test_closed_field_present_open_post_both_faces(client, poster, other):
    post = _post(client, poster)
    assert post["closed"] is False

    rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(other)
    ).json()
    assert rows[0]["closed"] is False

    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(other)
    ).json()
    assert detail["closed"] is False

    mine = client.get(
        "/api/feedback/mine", headers=auth_headers(poster)
    ).json()
    assert mine[0]["closed"] is False


@pytest.mark.parametrize(
    "status,closed",
    [
        ("open", False),
        ("acknowledged", False),
        ("planned", False),
        ("in_progress", False),
        ("done", True),
        ("declined", True),
    ],
)
def test_closed_derives_from_status(client, poster, moderator, status, closed):
    post = _post(client, poster)
    updated = _set_status(client, moderator, post["id"], status)
    assert updated["closed"] is closed
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert detail["closed"] is closed


# -- close in the same action, on both boards ----------------------------------


def test_done_closes_bug_post_and_locks_comments(client, db, poster, other, moderator):
    post = _post(client, poster)
    ok = _comment(client, other, post["id"])
    assert ok.status_code == 201, ok.text

    updated = _set_status(client, moderator, post["id"], "done", note="Fixed in 2.4.")
    assert updated["status"] == "done"
    assert updated["closed"] is True

    # The poster sees it closed on the list + detail faces.
    rows = client.get(
        "/api/feedback/boards/bug", headers=auth_headers(poster)
    ).json()
    assert rows[0]["closed"] is True
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(poster)
    ).json()
    assert detail["closed"] is True
    # The thread stays readable after the lock.
    assert [c["body"] for c in detail["comments"]] == ["Me too — same crash."]

    # A second member's comment is refused with the plain reason…
    refused = _comment(client, other, post["id"], body="Still broken for me.")
    assert refused.status_code == 422, refused.text
    assert "closed" in refused.json()["detail"]
    # …and so is the poster's and even a moderator's — reopening
    # is the one way back in.
    assert _comment(client, poster, post["id"]).status_code == 422
    assert _comment(client, moderator, post["id"]).status_code == 422

    # The poster's inbox note says the post is closed.
    notes = _status_notes(db, poster.id)
    assert len(notes) == 1
    assert "is now done" in notes[0].body
    assert "This post is closed." in notes[0].body


def test_declined_closes_feature_post(client, db, poster, moderator):
    post = _post(client, poster, board="feature", title="Dark mode", body="Please")
    updated = _set_status(client, moderator, post["id"], "declined")
    assert updated["closed"] is True
    rows = client.get(
        "/api/feedback/boards/feature", headers=auth_headers(poster)
    ).json()
    assert rows[0]["closed"] is True
    notes = _status_notes(db, poster.id)
    assert "is now declined" in notes[0].body
    assert "This post is closed." in notes[0].body


# -- reopening un-closes in the same action -------------------------------------


def test_reopen_uncloses_everywhere(client, db, poster, other, moderator):
    post = _post(client, poster)
    _set_status(client, moderator, post["id"], "done")
    reopened = _set_status(client, moderator, post["id"], "in_progress")
    assert reopened["closed"] is False

    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(other)
    ).json()
    assert detail["closed"] is False
    # Comments flow again.
    assert _comment(client, other, post["id"]).status_code == 201

    notes = _status_notes(db, poster.id)
    assert len(notes) == 2
    assert "This post is closed." in notes[0].body
    assert "is now in progress" in notes[1].body
    assert "This post is open again." in notes[1].body


def test_active_status_moves_never_say_closed(client, db, poster, moderator):
    post = _post(client, poster)
    _set_status(client, moderator, post["id"], "acknowledged")
    notes = _status_notes(db, poster.id)
    assert "closed" not in notes[0].body
    assert "open again" not in notes[0].body


# -- the poster's own language ---------------------------------------------------


def test_status_note_spanish_poster_closed_wording(client, db, poster_es, moderator):
    post = _post(client, poster_es, board="feature", title="Modo oscuro", body="Por favor")
    _set_status(client, moderator, post["id"], "declined")
    notes = _status_notes(db, poster_es.id)
    assert len(notes) == 1
    assert notes[0].title == "Tu publicación fue actualizada"
    assert "ahora está rechazado" in notes[0].body
    assert "Esta publicación está cerrada." in notes[0].body
    # Single language: no English tail rides along.
    assert "closed" not in notes[0].body


# -- the export slice agrees ------------------------------------------------------


def test_export_rows_carry_closed(client, db, poster, moderator):
    post = _post(client, poster)
    _set_status(client, moderator, post["id"], "done")
    rows = feedback_service.export_rows(db, poster.id)
    assert rows["posts"][0]["closed"] is True
