"""Marvin login lane (owner approval, 2026-11-06 23:26): the
site's assistant gets its OWN account on the Bug Reports /
Feature Requests boards, designated BY ACCOUNT, so a new post
notifies it alongside the admin tiers and it can reply
in-thread asking clarifying questions.

Pins:

- DESIGNATION: the `feedback.assistant_user_id` system setting
  names exactly one account (its user id). That account — a
  plain "user" seat, no tier, no role — receives the same
  feedback_new_post note as god + moderator_admin, with the
  same title and the same post link. The moderator rung stays
  OUT (the owner's word was "admins"); the filer stays out.
- SELF-EXCLUSION: a post BY the designated assistant never
  notifies the assistant itself (the actor exclusion), while
  the admin tiers still hear about it.
- QUIET RESOLUTION: an unset setting, a malformed value, a
  missing account, or an inactive account all resolve to "no
  assistant" — the post still lands and the fan-out behaves
  exactly as it did before the assistant existed.
- THE SEAT WORKS: the note is VISIBLE in the assistant's own
  inbox list (the module-visibility filter must not hide the
  feedback kind from a mechanic-group account), and the
  assistant can open the thread and post a reply comment —
  whose author block carries its plainly-labeled display
  name — and the poster hears about the reply
  (feedback_comment), the loop the whole flow exists for.
"""

import uuid

import pytest
from sqlalchemy import select

from app.modules.billing import entitlements
from app.modules.core import inbox, models as core_models
from app.modules.feedback import service as feedback_service
from tests.conftest import auth_headers

MECHANIC = "mechanic_technician"
ASSISTANT_NAME = "Marvin (Toolbox Vault Assistant)"


def _make_user(
    db,
    account_number,
    email,
    name="Lane User",
    role="user",
    tier=None,
    is_operator=False,
    is_active=True,
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
        is_active=is_active,
    )
    if tier is not None:
        user.tier = tier
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def poster(db):
    return _make_user(db, "TV-M-000901", "marvin-poster@example.com", "Pete Poster")


@pytest.fixture()
def assistant(db):
    return _make_user(
        db, "TV-M-000902", "marvin@toolboxvault.com", ASSISTANT_NAME
    )


@pytest.fixture()
def moderator(db):
    return _make_user(
        db, "TV-M-000903", "marvin-mod@example.com", "Maude Mod",
        role="moderator", tier="moderator",
    )


@pytest.fixture()
def god(db):
    return _make_user(
        db, "TV-M-000905", "marvin-god@example.com", "Gail God",
        role="community_admin", tier="god", is_operator=True,
    )


@pytest.fixture()
def designated(db, assistant):
    """The operator act: name the assistant account in the setting."""
    entitlements.set_setting(
        db, feedback_service.ASSISTANT_USER_ID_SETTING, str(assistant.id)
    )
    return assistant


def _post(client, user, board="bug", title="App crashes on save", body="Steps..."):
    response = client.post(
        "/api/feedback/posts",
        json={"board": board, "title": title, "body": body},
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


# -- designation -------------------------------------------------------------------


def test_designated_assistant_receives_new_post_notes(
    client, db, poster, designated, god, moderator
):
    bug = _post(client, poster, board="bug", title="Sync eats a tool")
    feature = _post(
        client, poster, board="feature", title="Dark mode", body="Please"
    )

    notes = _notes(db, designated.id)
    assert len(notes) == 2
    by_title = {n.title: n for n in notes}
    assert by_title["New bug report: Sync eats a tool"].data == {
        "post_id": bug["id"],
        "board": "bug",
    }
    assert by_title["New feature request: Dark mode"].data == {
        "post_id": feature["id"],
        "board": "feature",
    }
    # The admins still hear about both; the moderator rung and
    # the filer still hear nothing.
    assert len(_notes(db, god.id)) == 2
    assert _notes(db, moderator.id) == []
    assert _notes(db, poster.id) == []


def test_assistant_is_a_plain_seat(db, designated):
    """The designation confers no tier and no role — the account
    is a normal user that happens to be named in a setting."""
    assert designated.role == "user"
    assert designated.is_operator is False
    from app.modules.core import tiers

    assert tiers.resolved_tier(designated) == "normal"


def test_assistants_own_post_never_notifies_itself(
    client, db, designated, god
):
    _post(client, designated, board="bug", title="Assistant checking in")
    assert _notes(db, designated.id) == []
    # ...while the admin audience still hears about it.
    assert len(_notes(db, god.id)) == 1


def test_no_designation_no_assistant_note(client, db, poster, assistant, god):
    _post(client, poster)
    assert _notes(db, assistant.id) == []
    assert len(_notes(db, god.id)) == 1


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        str(uuid.uuid4()),  # well-formed, but no such account
    ],
)
def test_bad_designation_resolves_quietly(client, db, poster, assistant, value):
    entitlements.set_setting(db, feedback_service.ASSISTANT_USER_ID_SETTING, value)
    post = _post(client, poster)
    assert post["title"] == "App crashes on save"
    assert _notes(db, assistant.id) == []


def test_inactive_designated_account_resolves_quietly(client, db, poster):
    inactive = _make_user(
        db, "TV-M-000907", "marvin-inactive@example.com", "Ina Inactive",
        is_active=False,
    )
    entitlements.set_setting(
        db, feedback_service.ASSISTANT_USER_ID_SETTING, str(inactive.id)
    )
    _post(client, poster)
    assert _notes(db, inactive.id) == []


def test_designated_assistant_helper(db, designated):
    found = feedback_service.designated_assistant(db)
    assert found is not None and found.id == designated.id


# -- the seat works end to end -------------------------------------------------------


def test_note_is_visible_in_the_assistants_inbox(client, db, poster, designated):
    post = _post(client, poster, title="Inbox-visible note")
    response = client.get(
        "/api/core/notifications", headers=auth_headers(designated)
    )
    assert response.status_code == 200, response.text
    mine = [
        n for n in response.json() if n["kind"] == inbox.KIND_FEEDBACK_NEW_POST
    ]
    assert len(mine) == 1
    assert mine[0]["title"] == "New bug report: Inbox-visible note"
    assert mine[0]["link"] == f"/feedback/post/{post['id']}"
    assert mine[0]["read"] is False


def test_full_flow_with_a_real_password_login(client, db, poster, monkeypatch):
    """The production shape, over HTTP only: the assistant
    account is created through the real account-creation path
    with a real (fragment-built) password, designated, and
    then — using nothing but its login — reads the new-post
    note from its inbox, opens the thread, replies, and marks
    the note read. A wrong password is refused."""
    import itertools

    from app.modules.core import service as core_service

    # service.create_user needs Postgres nextval() for the
    # account number; SQLite has no sequences, so stub the
    # counter (the established pattern — see
    # test_signup_basics.py / test_account_settings.py). Every
    # other step of the creation path runs for real.
    counter = itertools.count(902000)
    monkeypatch.setattr(
        core_service,
        "_next_account_number",
        lambda _db: f"TV-{next(counter):06d}",
    )

    password = "".join(["Mv7", "!kQ2", "zX9p", "L4wR", "8sN3"])
    account = core_service.create_user(
        db,
        "marvin@toolboxvault.com",
        ASSISTANT_NAME,
        password,
        [MECHANIC],
    )
    # The operator marks the assistant's address verified at
    # creation (no mailbox sits behind it; no mail is sent).
    account.email_verified = True
    db.commit()
    entitlements.set_setting(
        db, feedback_service.ASSISTANT_USER_ID_SETTING, str(account.id)
    )

    post = _post(client, poster, title="Login-flow check")

    refused = client.post(
        "/api/core/login",
        json={"email": "marvin@toolboxvault.com", "password": "wrong-password"},
    )
    assert refused.status_code == 401

    logged_in = client.post(
        "/api/core/login",
        json={"email": "marvin@toolboxvault.com", "password": password},
    )
    assert logged_in.status_code == 200, logged_in.text
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}

    inbox_page = client.get("/api/core/notifications", headers=headers)
    assert inbox_page.status_code == 200
    notes = [
        n for n in inbox_page.json() if n["kind"] == inbox.KIND_FEEDBACK_NEW_POST
    ]
    assert len(notes) == 1 and notes[0]["read"] is False

    detail = client.get(f"/api/feedback/posts/{post['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["title"] == "Login-flow check"

    reply = client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={"body": "Thanks for posting — what did you expect to happen?"},
        headers=headers,
    )
    assert reply.status_code == 201, reply.text

    marked = client.post(
        f"/api/core/notifications/{notes[0]['id']}/read", headers=headers
    )
    assert marked.status_code == 204
    after = client.get("/api/core/notifications", headers=headers).json()
    assert [n for n in after if n["id"] == notes[0]["id"]][0]["read"] is True


def test_assistant_can_reply_and_poster_hears_about_it(
    client, db, poster, designated
):
    post = _post(client, poster, title="Prints a blank page")
    response = client.post(
        f"/api/feedback/posts/{post['id']}/comments",
        json={
            "body": (
                "Hi Pete — Marvin here, the site's assistant. "
                "Could you tell me what you were printing, and "
                "what you expected to come out?"
            )
        },
        headers=auth_headers(designated),
    )
    assert response.status_code == 201, response.text
    comment = response.json()
    assert comment["visibility"] == "visible"
    assert comment["author"]["display_name"] == ASSISTANT_NAME
    assert comment["author"]["role"] == "user"

    # The assistant reads the post back the way the watcher does:
    # its own signed-in session (the boards are members-only
    # reading since 2026-11-10; the assistant is a member).
    detail = client.get(
        f"/api/feedback/posts/{post['id']}", headers=auth_headers(designated)
    ).json()
    assert [c["id"] for c in detail["comments"]] == [comment["id"]]

    # The poster hears about the reply — the conversation loop.
    heard = _notes(db, poster.id, kind=inbox.KIND_FEEDBACK_COMMENT)
    assert len(heard) == 1
    assert heard[0].data["post_id"] == post["id"]
