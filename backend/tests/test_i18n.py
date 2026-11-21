"""Audit A17 (2026-10-22): locale plumbing.

Pins: users.locale round-trips through PATCH /me and
normalizes unknown values to unset; resolve_locale follows
preference -> Spanish-speaking country -> English; the
transactional emails render in Spanish for an es user; the
activity report chrome (CSV headers + prepared-for line)
localizes while the owner's data stays untouched.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.core import i18n, notifications
from app.modules.core import models as core_models
from app.modules.inventory import models as inventory_models
from app.modules.reports import activity
from tests.conftest import auth_headers


def _make_user(db, number, email, **kw):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=number,
        email=email,
        name="Locale User",
        password_hash="x",
        account_types=["mechanic_technician"],
        **kw,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_locale_patch_round_trip_and_normalization(client, db):
    user = _make_user(db, "TV-M-000801", "a17-me@example.com")
    headers = auth_headers(user)
    resp = client.patch("/api/core/me", json={"locale": "es"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["locale"] == "es"
    resp = client.patch("/api/core/me", json={"locale": "fr"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["locale"] == ""  # unshipped locale -> unset


def test_resolve_locale_rules(db):
    es_user = _make_user(db, "TV-M-000802", "a17-es@example.com", locale="es")
    mx_user = _make_user(db, "TV-M-000803", "a17-mx@example.com", country="MX")
    us_user = _make_user(db, "TV-M-000804", "a17-us@example.com", country="US")
    pref_wins = _make_user(
        db, "TV-M-000805", "a17-pref@example.com", locale="en", country="MX"
    )
    assert i18n.resolve_locale(es_user) == "es"
    assert i18n.resolve_locale(mx_user) == "es"  # country default
    assert i18n.resolve_locale(us_user) == "en"
    assert i18n.resolve_locale(pref_wins) == "en"  # preference beats country


def test_transactional_email_spanish(db, monkeypatch):
    sent = {}

    def fake_send(db_, to, subject, body, *, kind="generic", attachment=None,
                  recipient_name=None, locale=None, link_free=False):
        sent.update(subject=subject, body=body)
        return True

    monkeypatch.setattr(notifications, "send_email", fake_send)
    notifications.send_verification_email(db, "x@example.com", "tok", locale="es")
    assert "Verifique su correo" in sent["subject"]
    assert "Le damos la bienvenida" in sent["body"]
    notifications.send_password_reset_email(db, "x@example.com", "tok", locale="es")
    assert "Restablezca su contraseña" in sent["subject"]
    notifications.send_password_reset_email(db, "x@example.com", "tok")
    assert sent["subject"] == "Reset your Toolbox Vault password"


def test_activity_chrome_spanish(db):
    owner = _make_user(db, "TV-M-000806", "a17-rpt@example.com", locale="es")
    tool = inventory_models.Tool(
        owner_id=owner.id, name="Llave", model="", serial_number="",
        purchase_price=Decimal("10"), purchase_date=date(2026, 1, 1),
        business_use=True,
    )
    db.add(tool)
    db.commit()
    report = activity.build_tax_year(db, owner, 2026)
    csv_bytes = activity.render_activity(report, "csv", owner)
    text = csv_bytes.decode("utf-8")
    assert "Preparado para" in text
    assert "Sección" in text and "Fecha" in text
    pdf_bytes = activity.render_activity(report, "pdf", owner)
    assert pdf_bytes.startswith(b"%PDF")
    # The English default is untouched for an en owner.
    en_owner = _make_user(db, "TV-M-000807", "a17-en@example.com")
    text_en = activity.render_activity(report, "csv", en_owner).decode("utf-8")
    assert "Prepared for" in text_en
