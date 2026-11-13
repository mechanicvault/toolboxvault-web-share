"""Feature announcements (release machinery, owner rule
2026-11-08): the Admin composer, the all-user fan-out job, and
the history.

Proves:
- the composer gate is god + moderator_admin (the user-manager
  rung) — a normal user, a plain moderator, and an anonymous
  caller are all refused;
- composing queues (never sends inline), and the fan-out job
  delivers ONE inbox notification to every ACTIVE account —
  across tiers and account-type groups — and none to a
  deactivated account;
- the history row flips to sent with the recipient count and
  timestamp, and a second job run sends nothing again;
- there is no edit/delete/re-send path (405s);
- a link must be an in-app path (an external URL is refused),
  and the inbox resolves the composer's link (or Home when
  none was set);
- the email twin stays silent by default (the announcements
  category's email default is OFF) and honors a user's opt-in.
"""

import uuid

from sqlalchemy import select

from app.modules.core import announcements, models, notification_prefs
from tests.conftest import auth_headers


def _make_user(db, account_number, email, **flags):
    user = models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=flags.pop("name", "Test User"),
        password_hash="not-a-real-hash",
        **flags,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _announcement_rows(db, user_id):
    return list(
        db.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user_id,
                models.Notification.kind == "feature_announcement",
            )
        )
    )


def test_composer_gate_is_god_and_moderator_admin(client, db, user_a):
    payload = {"title": "New: Reports", "body": "Build a report."}
    # Anonymous: 401.
    assert client.post("/api/admin/announcements", json=payload).status_code == 401
    # A normal user: 403.
    resp = client.post(
        "/api/admin/announcements", json=payload, headers=auth_headers(user_a)
    )
    assert resp.status_code == 403
    # A plain moderator (below moderator_admin): 403.
    moderator = _make_user(
        db, "TV-000101", "mod@example.com", tier="moderator", role="moderator"
    )
    resp = client.post(
        "/api/admin/announcements", json=payload, headers=auth_headers(moderator)
    )
    assert resp.status_code == 403
    # The history is gated the same way.
    assert client.get("/api/admin/announcements", headers=auth_headers(user_a)).status_code == 403


def test_moderator_admin_and_operator_can_compose(client, db):
    mod_admin = _make_user(
        db, "TV-000102", "ma@example.com", tier="moderator_admin"
    )
    operator = _make_user(
        db, "TV-000103", "op@example.com", is_operator=True, tier="god"
    )
    for author in (mod_admin, operator):
        resp = client.post(
            "/api/admin/announcements",
            json={"title": "New: Reports", "body": "Build a report.", "link": "/reports"},
            headers=auth_headers(author),
        )
        assert resp.status_code == 201, resp.text
        view = resp.json()
        assert view["status"] == "queued"
        assert view["recipient_count"] is None
        assert view["created_by_name"] == author.name
    history = client.get(
        "/api/admin/announcements", headers=auth_headers(operator)
    )
    assert history.status_code == 200
    assert len(history.json()) == 2
    # Composing writes an audit row per announcement.
    audits = list(
        db.scalars(
            select(models.AuditLog).where(
                models.AuditLog.action == "announcement.create"
            )
        )
    )
    assert len(audits) == 2


def test_compose_validates_fields(client, db):
    operator = _make_user(db, "TV-000104", "op2@example.com", is_operator=True)
    headers = auth_headers(operator)
    # Blank title / body.
    assert client.post("/api/admin/announcements", json={"title": "  ", "body": "x"}, headers=headers).status_code == 422
    assert client.post("/api/admin/announcements", json={"title": "x", "body": ""}, headers=headers).status_code == 422
    # An external link is refused — announcements never send
    # users off the site.
    for bad in ("https://evil.example.com/x", "//evil.example.com", "reports"):
        resp = client.post(
            "/api/admin/announcements",
            json={"title": "x", "body": "y", "link": bad},
            headers=headers,
        )
        assert resp.status_code == 422, bad
    # A blank link reads as no link.
    resp = client.post(
        "/api/admin/announcements",
        json={"title": "x", "body": "y", "link": "  "},
        headers=headers,
    )
    assert resp.status_code == 201 and resp.json()["link"] is None


def test_no_edit_or_resend_path(client, db):
    operator = _make_user(db, "TV-000105", "op3@example.com", is_operator=True)
    headers = auth_headers(operator)
    created = client.post(
        "/api/admin/announcements",
        json={"title": "x", "body": "y"},
        headers=headers,
    ).json()
    url = f"/api/admin/announcements/{created['id']}"
    # No route exists for any of these verbs on an announcement:
    # 404 (no path) / 405 (path without the verb) both prove
    # there is no edit, delete or re-send path.
    assert client.put(url, json={"title": "z", "body": "y"}, headers=headers).status_code in (404, 405)
    assert client.patch(url, json={"title": "z"}, headers=headers).status_code in (404, 405)
    assert client.delete(url, headers=headers).status_code in (404, 405)


def test_fanout_reaches_every_active_account_once(client, db):
    operator = _make_user(
        db, "TV-000106", "op4@example.com", is_operator=True, tier="god"
    )
    mechanic = _make_user(db, "TV-000107", "mech@example.com", account_types=["mechanic_technician"])
    dealer = _make_user(db, "TV-000108", "dealer@example.com", account_types=["tool_dealer"])
    mod_admin = _make_user(db, "TV-000109", "ma2@example.com", tier="moderator_admin")
    deactivated = _make_user(db, "TV-000110", "gone@example.com", is_active=False)

    created = client.post(
        "/api/admin/announcements",
        json={
            "title": "New: Build & save reports",
            "body": "Reports can now be built with custom columns and saved as templates.",
            "link": "/reports",
        },
        headers=auth_headers(operator),
    ).json()

    sent = announcements.run_pending_announcements(db)
    assert sent == 1

    actives = (operator, mechanic, dealer, mod_admin)
    for user in actives:
        rows = _announcement_rows(db, user.id)
        assert len(rows) == 1, user.email
        assert rows[0].title == "New: Build & save reports"
        assert rows[0].read_at is None
        assert rows[0].data["link"] == "/reports"
        assert rows[0].data["announcement_id"] == created["id"]
    assert _announcement_rows(db, deactivated.id) == []

    history = client.get(
        "/api/admin/announcements", headers=auth_headers(operator)
    ).json()
    row = history[0]
    assert row["status"] == "sent"
    assert row["recipient_count"] == len(actives)
    assert row["sent_at"] is not None

    # A second run is a no-op: nobody is announced twice.
    assert announcements.run_pending_announcements(db) == 0
    for user in actives:
        assert len(_announcement_rows(db, user.id)) == 1


def test_inbox_resolves_announcement_link(client, db, user_a):
    announcements.queue_announcement(
        db,
        author_id=user_a.id,
        author_name=user_a.name,
        title="New: Flyers",
        body="Dealer agents can showcase their flyers.",
        link="/flyers",
    )
    announcements.queue_announcement(
        db,
        author_id=user_a.id,
        author_name=user_a.name,
        title="News",
        body="No link on this one.",
        link=None,
    )
    assert announcements.run_pending_announcements(db) == 2
    resp = client.get(
        "/api/core/notifications", headers=auth_headers(user_a)
    )
    assert resp.status_code == 200, resp.text
    by_title = {item["title"]: item for item in resp.json()}
    assert by_title["New: Flyers"]["kind"] == "feature_announcement"
    assert by_title["New: Flyers"]["link"] == "/flyers"
    # No composer link: the click lands on Home, never a dead end.
    assert by_title["News"]["link"] == "/"


def test_email_twin_silent_by_default_honors_opt_in(client, db, user_a, user_b):
    # user_b opts INTO announcement emails; user_a keeps the
    # default (off).
    notification_prefs.set_channel_pref(
        db,
        user_b.id,
        category=notification_prefs.CATEGORY_ANNOUNCEMENTS,
        channel=notification_prefs.CHANNEL_EMAIL,
        enabled=True,
    )
    announcements.queue_announcement(
        db,
        author_id=user_a.id,
        author_name=user_a.name,
        title="New: Widgets",
        body="A new dashboard widget is available.",
        link=None,
    )
    assert announcements.run_pending_announcements(db) == 1
    outbox = list(
        db.scalars(
            select(models.EmailOutbox).where(
                models.EmailOutbox.kind == "notification_email"
            )
        )
    )
    recipients = {row.recipient for row in outbox}
    assert user_b.email in recipients
    assert user_a.email not in recipients
