"""The one email template (owner order, 2026-11-09): every send
the seam makes wears the shared format — masthead, greeting,
content, footer (site, socials, notification-settings link) —
in the recipient's language, with a real text part.

Pins:
  - the pure renderer's chrome (EN + ES), greeting by name with
    its no-account fallback, content escaping, and bare-URL
    linkification (the verify/reset action links must be tappable);
  - the seam's behaviour: the outbox records the templated TEXT
    part (subject/kind/status recording unchanged), the Resend
    payload carries text + html, and the greeting/locale resolve
    from the account owning the address;
  - one representative send of each email family comes out
    wrapped — no family bypasses the template.
"""

import itertools
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core import email_template, notifications
from app.core.config import settings
from app.modules.core import models

BASE = "https://toolboxvault.com"
SETTINGS_URL = f"{BASE}/settings/notifications"

_counter = itertools.count(1)


def _make_user(db, *, name="Template Tester", locale="en", country="US"):
    n = next(_counter)
    user = models.User(
        id=uuid.uuid4(),
        account_number=f"TV-ET-{n:06d}",
        email=f"tpl-{n}-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        password_hash="not-a-real-hash",
        locale=locale,
        country=country,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _outbox(db, *, kind=None, recipient=None):
    stmt = select(models.EmailOutbox)
    if kind is not None:
        stmt = stmt.where(models.EmailOutbox.kind == kind)
    if recipient is not None:
        stmt = stmt.where(models.EmailOutbox.recipient == recipient)
    return list(db.scalars(stmt).all())


# -- the renderer -------------------------------------------------------------


def test_render_greets_by_name_and_footers_in_english():
    text, html = email_template.render_email(
        "Your report is ready.", name="Ryan Overby", locale="en", base_url=BASE
    )
    assert text.startswith("Hi Ryan Overby,")
    assert "Your report is ready." in text
    assert f"Toolbox Vault · {BASE}" in text
    assert f"Manage your notification settings: {SETTINGS_URL}" in text
    for label, href, _icon in email_template.SOCIALS:
        assert f"{label}: {href}" in text
        assert f'href="{href}"' in html
    assert f'<img src="{BASE}/email/logo.png"' in html
    assert "Toolbox Vault" in html  # wordmark text rides the masthead
    assert f'href="{SETTINGS_URL}"' in html
    assert "Manage your notification settings" in html


def test_render_falls_back_when_no_name():
    text, _html = email_template.render_email(
        "A file was shared with you.", name=None, locale="en", base_url=BASE
    )
    assert text.startswith("Hi there,")


def test_render_spanish_chrome():
    text, html = email_template.render_email(
        "Su informe está listo.", name="María", locale="es", base_url=BASE
    )
    assert text.startswith("Hola María,")
    assert f"Administre su configuración de notificaciones: {SETTINGS_URL}" in text
    assert "Administre su configuración de notificaciones" in html


def test_render_escapes_content_and_linkifies_urls():
    _text, html = email_template.render_email(
        'Look <script>alert(1)</script> here:\nhttps://example.com/x?y=1',
        name="A",
        locale="en",
        base_url=BASE,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert '<a href="https://example.com/x?y=1"' in html


def test_render_defaults_to_production_origin():
    text, html = email_template.render_email("Hi.", name="A", locale="en", base_url="")
    assert SETTINGS_URL in text
    assert f'<img src="{BASE}/email/logo.png"' in html


# -- the seam -----------------------------------------------------------------


def test_dev_send_wraps_and_records_text_part(db):
    user = _make_user(db, name="Casey Mechanic")
    ok = notifications.send_email(
        db, user.email, "A subject", "Body content here.", kind="generic"
    )
    assert ok is True
    rows = _outbox(db, recipient=user.email)
    assert len(rows) == 1
    row = rows[0]
    assert (row.provider, row.status, row.kind) == ("dev", "logged", "generic")
    assert row.body.startswith("Hi Casey Mechanic,")
    assert "Body content here." in row.body
    assert SETTINGS_URL in row.body


def test_dev_send_to_unknown_address_uses_fallback_greeting(db):
    ok = notifications.send_email(
        db, "agent-with-no-account@example.com", "S", "Content.", kind="generic"
    )
    assert ok is True
    row = _outbox(db, recipient="agent-with-no-account@example.com")[0]
    assert row.body.startswith("Hi there,")


def test_dev_send_resolves_spanish_from_the_account(db):
    user = _make_user(db, name="Lucía", locale="es", country="MX")
    notifications.send_email(db, user.email, "S", "Contenido.", kind="generic")
    row = _outbox(db, recipient=user.email)[0]
    assert row.body.startswith("Hola Lucía,")
    assert "Administre su configuración de notificaciones" in row.body


def test_resend_payload_carries_text_and_html(db, monkeypatch):
    user = _make_user(db, name="Dana")
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["json"] = json
        return httpx.Response(200, json={"id": "re_1"})

    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "rk_test")
    monkeypatch.setattr(notifications.httpx, "post", fake_post)
    ok = notifications.send_email(db, user.email, "S", "Content.", kind="generic")
    assert ok is True
    payload = calls["json"]
    assert payload["text"].startswith("Hi Dana,")
    assert "Toolbox Vault" in payload["html"]
    assert SETTINGS_URL in payload["html"]
    row = _outbox(db, recipient=user.email)[0]
    assert (row.provider, row.status) == ("resend", "sent")
    assert row.body == payload["text"]


# -- every family wears it ------------------------------------------------------

_FAMILIES = [
    ("verification", lambda db, email: notifications.send_verification_email(db, email, "tok123")),
    ("password_reset", lambda db, email: notifications.send_password_reset_email(db, email, "tok123")),
    ("email_change", lambda db, email: notifications.send_email_change_email(db, email, "tok123")),
    # message_notification is pinned separately below: it wears
    # the frame link-free by design, so it has no settings URL.
    (
        "notification_email",
        lambda db, email: notifications.send_notification_email(
            db, email, title="Something happened", body="Details inside."
        ),
    ),
]


@pytest.mark.parametrize("kind,send", _FAMILIES, ids=[k for k, _ in _FAMILIES])
def test_each_family_send_is_wrapped(db, kind, send):
    user = _make_user(db, name="Family Member")
    assert send(db, user.email) is True
    rows = _outbox(db, kind=kind, recipient=user.email)
    assert len(rows) == 1
    body = rows[0].body
    assert body.startswith("Hi Family Member,"), body[:80]
    assert SETTINGS_URL in body


def test_link_free_variant_carries_frame_without_links():
    # The message-notification discipline (2026-10-19): the
    # frame (masthead, greeting, footer band) with NO links,
    # URLs or hosted images in either part.
    text, html = email_template.render_email(
        "Sam sent you a message on Toolbox Vault.",
        name="Bob",
        locale="en",
        base_url=BASE,
        link_free=True,
    )
    assert text.startswith("Hi Bob,")
    assert "http" not in text
    assert text.rstrip().endswith("Toolbox Vault")
    assert "<a " not in html
    assert "<img" not in html
    assert "http" not in html
    assert "Toolbox Vault" in html


def test_message_notification_family_is_link_free(db):
    user = _make_user(db, name="Bob Baker")
    assert (
        notifications.send_message_notification_email(db, user.email, "Alice")
        is True
    )
    rows = _outbox(db, kind="message_notification", recipient=user.email)
    assert len(rows) == 1
    assert rows[0].body.startswith("Hi Bob Baker,")
    assert "http" not in rows[0].body


def test_changed_notice_to_old_address_still_wrapped(db):
    # The recipient address is the account's OLD email — no account
    # resolves under it, so the fallback greeting carries the wrap.
    user = _make_user(db, name="Moved Away")
    assert (
        notifications.send_email_changed_notice(db, "old-address@example.com", user.email)
        is True
    )
    rows = _outbox(db, kind="email_changed_notice", recipient="old-address@example.com")
    assert len(rows) == 1
    assert rows[0].body.startswith("Hi there,")
    assert SETTINGS_URL in rows[0].body
