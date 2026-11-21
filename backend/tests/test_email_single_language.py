"""Single-language rule (owner order, 2026-11-10, broadened
same day): NOTHING user-facing appears in a language other
than the user's own choice — email, inbox announcements,
every surface. Never both languages stacked in one message.

The one stacked producer was the operator-composed feature
announcement: its stored body was composed EN + "\\n\\n" + ES
and the fan-out handed that one body to every recipient's
inbox (and to the email twin of anyone who opted in). This
file proves:

- a bilingual compose is STORED split (migration 0102's
  parts; the stored title/body are the English rendering) —
  nothing stacked is stored or sent;
- the fan-out gives each recipient ONLY their resolved
  locale's title/body — in their inbox entry AND in any email
  twin (the twin carries the notification's own words);
- the recorded fallback: a compose without a part for a
  recipient's locale gives that recipient the stored (English)
  text — one language, never a stacked pair;
- module-release announcements keep rendering per recipient
  from the release templates, inbox and twin alike;
- the admin compose route accepts and stores the parts.
"""

import uuid

from sqlalchemy import select

from app.modules.core import announcements, models, notification_prefs
from tests.conftest import auth_headers

TITLE = "Your Home, rearranged"
TITLE_ES = "Tu inicio, reorganizado"
BODY_EN = (
    "Your Home dashboard now shows your numbers first, and the "
    "widgets you pick stay where you put them."
)
BODY_ES = (
    "Tu panel de inicio ahora muestra tus números primero, y "
    "los widgets que eliges se quedan donde los pones."
)
STACKED = BODY_EN + "\n\n" + BODY_ES


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


def _opt_in(db, user):
    notification_prefs.set_channel_pref(
        db,
        user.id,
        category=notification_prefs.CATEGORY_ANNOUNCEMENTS,
        channel=notification_prefs.CHANNEL_EMAIL,
        enabled=True,
    )


def _inbox_rows(db, user_id):
    return list(
        db.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user_id,
                models.Notification.kind == "feature_announcement",
            )
        )
    )


def _twin_rows(db):
    return list(
        db.scalars(
            select(models.EmailOutbox).where(
                models.EmailOutbox.kind == "notification_email"
            )
        )
    )


def _members(db):
    en = _make_user(db, "TV-000201", "en@example.com", locale="en")
    es = _make_user(db, "TV-000202", "es@example.com", locale="es")
    _opt_in(db, en)
    _opt_in(db, es)
    return en, es


def test_announcement_is_single_language_per_member_everywhere(db):
    en, es = _members(db)
    row = announcements.queue_announcement(
        db,
        author_id=en.id,
        author_name=en.name,
        title=TITLE,
        body=STACKED,
        link="/",
        title_es=TITLE_ES,
        body_en=BODY_EN,
        body_es=BODY_ES,
    )
    # Nothing stacked is stored: the stored body is the English
    # rendering; the parts ride alongside.
    assert row.body == BODY_EN
    assert row.title_es == TITLE_ES
    assert row.body_es == BODY_ES
    assert announcements.run_pending_announcements(db) == 1

    # INBOX: each member's entry is only their own language.
    en_rows = _inbox_rows(db, en.id)
    es_rows = _inbox_rows(db, es.id)
    assert len(en_rows) == len(es_rows) == 1
    assert (en_rows[0].title, en_rows[0].body) == (TITLE, BODY_EN)
    assert (es_rows[0].title, es_rows[0].body) == (TITLE_ES, BODY_ES)

    # EMAIL twin: the same per-member words, nobody else's.
    twins = {r.recipient: r for r in _twin_rows(db)}
    assert set(twins) == {en.email, es.email}
    en_mail = twins[en.email]
    assert en_mail.subject == TITLE
    assert BODY_EN in en_mail.body
    assert BODY_ES not in en_mail.body
    assert "Hola" not in en_mail.body
    assert en_mail.body.startswith("Hi Test User,")
    es_mail = twins[es.email]
    assert es_mail.subject == TITLE_ES
    assert BODY_ES in es_mail.body
    assert BODY_EN not in es_mail.body
    assert es_mail.body.startswith("Hola Test User,")


def test_missing_locale_part_falls_back_to_the_stored_text(db):
    """The recorded fallback: an announcement composed with no
    Spanish part gives Spanish-set recipients the stored
    (English) rendering — inbox and twin — one language, never
    a stacked pair."""
    en, es = _members(db)
    announcements.queue_announcement(
        db,
        author_id=en.id,
        author_name=en.name,
        title=TITLE,
        body=BODY_EN,
        link=None,
        body_en=BODY_EN,
    )
    assert announcements.run_pending_announcements(db) == 1
    es_rows = _inbox_rows(db, es.id)
    assert (es_rows[0].title, es_rows[0].body) == (TITLE, BODY_EN)
    twins = {r.recipient: r for r in _twin_rows(db)}
    assert twins[es.email].subject == TITLE
    assert BODY_EN in twins[es.email].body


def test_announcement_without_parts_gives_everyone_the_stored_words(db):
    en, es = _members(db)
    announcements.queue_announcement(
        db,
        author_id=en.id,
        author_name=en.name,
        title="Scheduled maintenance",
        body="The site will be down briefly on Sunday night.",
        link=None,
    )
    assert announcements.run_pending_announcements(db) == 1
    for user in (en, es):
        rows = _inbox_rows(db, user.id)
        assert (rows[0].title, rows[0].body) == (
            "Scheduled maintenance",
            "The site will be down briefly on Sunday night.",
        )
    twins = {r.recipient: r for r in _twin_rows(db)}
    assert set(twins) == {en.email, es.email}
    for mail in twins.values():
        assert mail.subject == "Scheduled maintenance"
        assert "The site will be down briefly on Sunday night." in mail.body


def test_release_announcement_matches_the_recipient_everywhere(db):
    en, es = _members(db)
    stored_title, stored_body = announcements.release_copy("prints", "en")
    announcements.queue_announcement(
        db,
        author_id=en.id,
        author_name=en.name,
        title=stored_title,
        body=stored_body,
        link=None,
        release_module_id="prints",
        audience_user_ids=[str(en.id), str(es.id)],
    )
    assert announcements.run_pending_announcements(db) == 1

    es_title, es_body = announcements.release_copy("prints", "es")
    en_title, en_body = announcements.release_copy("prints", "en")
    assert (_inbox_rows(db, es.id)[0].title, _inbox_rows(db, es.id)[0].body) == (
        es_title,
        es_body,
    )
    assert (_inbox_rows(db, en.id)[0].title, _inbox_rows(db, en.id)[0].body) == (
        en_title,
        en_body,
    )
    twins = {r.recipient: r for r in _twin_rows(db)}
    assert twins[es.email].subject == es_title
    assert es_body in twins[es.email].body
    assert en_body not in twins[es.email].body
    assert twins[en.email].subject == en_title
    assert en_body in twins[en.email].body
    assert es_body not in twins[en.email].body


def test_recipient_copy_for_fallbacks():
    class _User:
        def __init__(self, locale):
            self.locale = locale
            self.country = ""

    row = models.FeatureAnnouncement(
        title="Title", body="English body", title_es=None,
        body_en="English body", body_es="Cuerpo",
    )
    # Spanish title falls back to the stored title; the
    # Spanish body part wins for Spanish recipients.
    assert announcements.recipient_copy_for(row, _User("es")) == (
        "Title",
        "Cuerpo",
    )
    # English renders the stored (English) rendering.
    assert announcements.recipient_copy_for(row, _User("en")) == (
        "Title",
        "English body",
    )
    row.title_es = "Título"
    assert announcements.recipient_copy_for(row, _User("es")) == (
        "Título",
        "Cuerpo",
    )
    row.body_es = None
    assert announcements.recipient_copy_for(row, _User("es")) == (
        "Título",
        "English body",
    )


def test_queue_announcement_normalizes_blank_parts(db):
    author = _make_user(db, "TV-000203", "author@example.com")
    row = announcements.queue_announcement(
        db,
        author_id=author.id,
        author_name=author.name,
        title="T",
        body="B",
        link=None,
        title_es="   ",
        body_en="",
        body_es="  Cuerpo  ",
    )
    assert row.title_es is None
    assert row.body_en is None
    assert row.body_es == "Cuerpo"
    # No body_en composed: the stored body keeps the compose text.
    assert row.body == "B"
    view = announcements.announcement_view(row)
    assert view["title_es"] is None
    assert view["body_es"] == "Cuerpo"


def test_admin_compose_route_accepts_and_stores_parts(client, db):
    operator = _make_user(
        db, "TV-000204", "op@example.com", is_operator=True, tier="god"
    )
    resp = client.post(
        "/api/admin/announcements",
        json={
            "title": TITLE,
            "body": BODY_EN,
            "body_en": BODY_EN,
            "title_es": TITLE_ES,
            "body_es": BODY_ES,
        },
        headers=auth_headers(operator),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["body"] == BODY_EN
    assert created["title_es"] == TITLE_ES
    assert created["body_en"] == BODY_EN
    assert created["body_es"] == BODY_ES
    history = client.get(
        "/api/admin/announcements", headers=auth_headers(operator)
    ).json()
    assert history[0]["body_es"] == BODY_ES
