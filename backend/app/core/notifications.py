"""Centralized outbound notifications (email today, push later).

Universal infrastructure: modules ask this module to notify a user; they
never talk to an email provider directly.

====================================================================
PROVIDER SEAM — provider is Resend (owner-approved 2026-10-18),
selected by config (app.core.config):

  EMAIL_PROVIDER=dev (default, pre-launch): no network send. The
  message is logged (as the old stub did) AND recorded in the
  email_outbox table with status "logged", so every flow —
  verification, password reset, email change — is fully testable
  and drillable before the owner's Resend account/key exist.

  EMAIL_PROVIDER=resend + RESEND_API_KEY: real delivery via
  Resend's HTTPS API; the outbox row records the outcome
  ("sent" / "failed"). A failed send NEVER raises into the
  request that triggered it — email is a side effect, not a
  reason to fail a signup or a reset request.

  ACTIVATED 2026-10-22: the owner created the Resend account
  under MechanicVault, verified toolboxvault.com (Cloudflare
  autoconfig), and set both GitHub secrets (RESEND_API_KEY +
  EMAIL_PROVIDER=resend); this commit is the trigger deploy
  that syncs them into the server .env and restarts the API
  on the real provider.
====================================================================

Every send goes through the CALLER's database session (the outbox
row is written with the caller's transaction context, so tests and
drills see exactly the messages a request produced). The outbox
table itself is owned by the core module (modules/core/models.py
EmailOutbox) — this seam is its only writer.

THE ONE TEMPLATE (owner order, 2026-11-09): senders pass only
their content; send_email wraps it in the shared format rendered
by app.core.email_template (masthead + greeting + content +
footer, text + HTML parts) and the outbox records the text part.
"""

import base64
import logging

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import email_template, i18n
from app.core.config import settings
from app.modules.core import models

logger = logging.getLogger("app.core.notifications")

RESEND_API_URL = "https://api.resend.com/emails"
_HTTP_TIMEOUT_SECONDS = 10.0

# Outbox `kind` vocabulary (EmailOutbox.kind): the flow that
# produced the message. Tests and drills filter on these.
KIND_VERIFICATION = "verification"
KIND_PASSWORD_RESET = "password_reset"
KIND_EMAIL_CHANGE = "email_change"
KIND_EMAIL_CHANGED_NOTICE = "email_changed_notice"
KIND_BACKUP_ALERT = "backup_alert"
KIND_BACKUP_RECOVERY = "backup_recovery"
KIND_BACKUP_DIGEST = "backup_digest"
KIND_ATTACHMENT_SHARE = "attachment_share"
KIND_REPORT = "report"
KIND_MESSAGE_NOTIFICATION = "message_notification"
KIND_NOTIFICATION_EMAIL = "notification_email"
KIND_GENERIC = "generic"


def _record_outbox(
    db: Session,
    *,
    to: str,
    subject: str,
    body: str,
    kind: str,
    provider: str,
    status: str,
) -> None:
    """Append the outbox row. Best-effort by design: a broken
    outbox write must never fail the send it records — but it is
    logged loudly, because pre-launch the outbox IS the drill
    record and a silent gap would hide a broken flow."""
    try:
        db.add(
            models.EmailOutbox(
                recipient=to,
                subject=subject,
                body=body,
                kind=kind,
                provider=provider,
                status=status,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record email outbox row (to=%s kind=%s)", to, kind)


def _resolve_recipient(db: Session, to: str) -> tuple[str | None, str]:
    """Best-effort (display name, locale) for the template's
    greeting + chrome, resolved from the account that owns the
    recipient address. An address with no account behind it (a
    typed share address, a dealer agent) resolves to (None, "en")
    and the template's fallback greeting carries it. A lookup
    problem must never break a send: log it and fall back."""
    try:
        user = db.scalars(
            select(models.User).where(
                func.lower(models.User.email) == (to or "").strip().lower()
            )
        ).first()
    except Exception:
        logger.exception("recipient lookup failed (to=%s)", to)
        return None, "en"
    if user is None:
        return None, "en"
    return (user.name or "").strip() or None, i18n.resolve_locale(user)


def _send_via_resend(
    to: str,
    subject: str,
    body: str,
    attachment: tuple[str, bytes] | None = None,
    *,
    html: str | None = None,
) -> bool:
    """One Resend send. Returns the outcome; never raises. The API
    key travels in the Authorization header only — it is never
    logged and never part of the outbox row.

    `attachment` is (filename, content bytes): Resend takes the file
    base64-encoded in the JSON payload. The bytes are read from the
    storage service by the caller (owner-scoped there) and are never
    persisted by this seam — the outbox row records the filename and
    size only."""
    payload: dict = {
        "from": settings.email_from,
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html is not None:
        payload["html"] = html
    if attachment is not None:
        filename, content = attachment
        payload["attachments"] = [
            {
                "filename": filename,
                "content": base64.b64encode(content).decode("ascii"),
            }
        ]
    try:
        response = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.exception("Resend send failed in transport (to=%s)", to)
        return False
    if response.status_code >= 300:
        logger.error(
            "Resend send rejected: HTTP %s (to=%s): %s",
            response.status_code,
            to,
            response.text[:500],
        )
        return False
    return True


def send_email(
    db: Session,
    to: str,
    subject: str,
    body: str,
    *,
    kind: str = KIND_GENERIC,
    attachment: tuple[str, bytes] | None = None,
    recipient_name: str | None = None,
    locale: str | None = None,
    link_free: bool = False,
) -> bool:
    """Send one email through the configured provider and record it
    in the outbox. Returns True when the message was accepted (or,
    in dev mode, logged). Never raises for a delivery failure.

    EVERY send wears the one template (app.core.email_template,
    owner order 2026-11-09): `body` is the content block; the seam
    wraps it in the masthead/greeting/footer and produces the text
    + HTML parts here, so no sender can bypass the format. The
    outbox records the text part — the sent text, as it always has.
    `recipient_name`/`locale` let a caller that knows the user say
    so; otherwise the seam resolves both from the account owning
    the address (see _resolve_recipient).

    With `attachment` ((filename, bytes) — the "Email this file"
    action), the recorded body gains an attachment note (name +
    size): the drill book proves the file rode along without
    storing the bytes themselves."""
    if attachment is not None:
        filename, content = attachment
        body = (
            f"{body}\n\n[Attachment: {filename} — {len(content)} bytes, "
            "sent with this message]"
        )
    if recipient_name is None or locale is None:
        resolved_name, resolved_locale = _resolve_recipient(db, to)
        if recipient_name is None:
            recipient_name = resolved_name
        if locale is None:
            locale = resolved_locale
    text_body, html_body = email_template.render_email(
        body,
        name=recipient_name,
        locale=locale or "en",
        base_url=settings.app_base_url,
        link_free=link_free,
    )
    provider = (settings.email_provider or "dev").strip().lower()
    if provider == "resend":
        if not settings.resend_api_key:
            # Provider chosen but keyless: a misconfiguration, not
            # a dev send. Record it as a failure so the drill book
            # shows the truth instead of a pretend "logged".
            logger.error(
                "EMAIL_PROVIDER=resend but RESEND_API_KEY is empty; "
                "not sending (to=%s subject=%s)",
                to,
                subject,
            )
            _record_outbox(
                db, to=to, subject=subject, body=text_body, kind=kind,
                provider="resend", status="failed",
            )
            return False
        sent = _send_via_resend(to, subject, text_body, attachment, html=html_body)
        _record_outbox(
            db, to=to, subject=subject, body=text_body, kind=kind,
            provider="resend", status="sent" if sent else "failed",
        )
        return sent
    logger.info(
        "EMAIL (dev provider — logged, not delivered)\n  to: %s\n  subject: %s\n  body: %s",
        to,
        subject,
        text_body,
    )
    _record_outbox(
        db, to=to, subject=subject, body=text_body, kind=kind,
        provider="dev", status="logged",
    )
    return True


def _link(path: str, plain_token: str) -> str:
    base = settings.app_base_url.rstrip("/")
    return f"{base}{path}?token={plain_token}"


def send_verification_email(
    db: Session, email: str, plain_token: str, locale: str = "en"
) -> bool:
    """Send the signup email-verification link for `plain_token`.

    The plain token travels only inside this link; the database stores
    its hash (see app.core.security.generate_opaque_token).
    """
    link = _link("/verify-email", plain_token)
    if locale == "es":
        subject = "Verifique su correo electrónico de Toolbox Vault"
        body = (
            "Le damos la bienvenida a Toolbox Vault.\n\n"
            "Confirme que esta dirección de correo electrónico le "
            "pertenece abriendo el siguiente enlace:\n"
            f"{link}\n\n"
            f"El enlace vence en {settings.email_verification_expire_hours} horas. "
            "Si usted no se registró, ignore este mensaje."
        )
    else:
        subject = "Verify your Toolbox Vault email"
        body = (
            "Welcome to Toolbox Vault.\n\n"
            "Confirm this email address belongs to you by opening:\n"
            f"{link}\n\n"
            f"The link expires in {settings.email_verification_expire_hours} hours. "
            "If you didn't sign up, ignore this."
        )
    return send_email(db, to=email, subject=subject, body=body, kind=KIND_VERIFICATION, locale=locale)


def send_password_reset_email(
    db: Session, email: str, plain_token: str, locale: str = "en"
) -> bool:
    """Send the password-reset link for `plain_token` (hash-only in
    the database, like every one-time token here)."""
    link = _link("/reset-password", plain_token)
    if locale == "es":
        subject = "Restablezca su contraseña de Toolbox Vault"
        body = (
            "Alguien solicitó restablecer la contraseña de esta "
            "cuenta de Toolbox Vault.\n\n"
            "Establezca una contraseña nueva abriendo el siguiente "
            "enlace:\n"
            f"{link}\n\n"
            f"El enlace funciona una sola vez y vence en "
            f"{settings.password_reset_expire_hours} hora(s). "
            "Si usted no lo solicitó, ignore este mensaje: su "
            "contraseña no cambiará."
        )
    else:
        subject = "Reset your Toolbox Vault password"
        body = (
            "Someone asked to reset the password for this Toolbox Vault "
            "account.\n\n"
            "Set a new password by opening:\n"
            f"{link}\n\n"
            f"The link works once and expires in "
            f"{settings.password_reset_expire_hours} hour(s). "
            "If you didn't ask for this, ignore this email — your "
            "password stays as it is."
        )
    return send_email(db, to=email, subject=subject, body=body, kind=KIND_PASSWORD_RESET, locale=locale)


def send_email_change_email(
    db: Session, new_email: str, plain_token: str, locale: str = "en"
) -> bool:
    """Send the email-change confirmation link TO THE NEW address —
    proving control of the new inbox is the whole point of the flow."""
    link = _link("/confirm-email-change", plain_token)
    if locale == "es":
        subject = "Confirme su nueva dirección de correo de Toolbox Vault"
        body = (
            "Usted solicitó usar esta dirección como el correo "
            "electrónico de su cuenta de Toolbox Vault.\n\n"
            "Confirme el cambio abriendo el siguiente enlace:\n"
            f"{link}\n\n"
            f"El enlace funciona una sola vez y vence en "
            f"{settings.email_change_expire_hours} hora(s). "
            "Si usted no lo solicitó, ignore este mensaje: no "
            "cambiará nada."
        )
    else:
        subject = "Confirm your new Toolbox Vault email address"
        body = (
            "You asked to make this the email address on your Toolbox "
            "Vault account.\n\n"
            "Confirm the change by opening:\n"
            f"{link}\n\n"
            f"The link works once and expires in "
            f"{settings.email_change_expire_hours} hour(s). "
            "If you didn't ask for this, ignore this email — nothing "
            "changes."
        )
    return send_email(db, to=new_email, subject=subject, body=body, kind=KIND_EMAIL_CHANGE, locale=locale)


def send_message_notification_email(
    db: Session, email: str, sender_name: str, locale: str = "en"
) -> bool:
    """Tell a message recipient there's something to read
    (messaging module, 2026-10-19). Deliberately content-free: NO
    message text and NO links of any kind — the email announces,
    the signed-in site is where reading happens. A mail client
    (or a forwarded inbox) must never become a side channel into
    a private conversation.

    Template carve-out (2026-11-09): this family wears the one
    template's FRAME via link_free=True — masthead band, greeting,
    footer band — with every link/URL/hosted image removed,
    because the template's linked footer is exactly what this
    family's no-links discipline forbids. It is the one named
    exception in the email-template lane's INDEX."""
    if locale == "es":
        subject = "Tiene un mensaje nuevo en Toolbox Vault"
        body = (
            f"{sender_name} le envió un mensaje en Toolbox Vault.\n\n"
            "Inicie sesión en su cuenta de Toolbox Vault para leerlo "
            "y responder. Si no esperaba un mensaje de esta persona, "
            "puede bloquearla desde la misma conversación: el bloqueo "
            "es silencioso y permanente hasta que usted lo deshaga."
        )
    else:
        subject = "You have a new message on Toolbox Vault"
        body = (
            f"{sender_name} sent you a message on Toolbox Vault.\n\n"
            "Sign in to your Toolbox Vault account to read it and "
            "reply. If you weren't expecting a message from this "
            "person, you can block them from inside the "
            "conversation — blocking is silent and permanent "
            "until you undo it."
        )
    return send_email(db, to=email, subject=subject, body=body, kind=KIND_MESSAGE_NOTIFICATION, locale=locale, link_free=True)


def send_notification_email(
    db: Session,
    email: str,
    *,
    title: str,
    body: str,
    locale: str = "en",
) -> bool:
    """The email twin of an in-app notification (owner item 12,
    2026-10-24): the inbox creation path calls this when the
    recipient's category preference has email on. The copy is
    the notification's own title/body — the same words the bell
    shows — plus one footer line saying why it arrived and
    where to turn it off. Content discipline matches the
    message-notification email: the email announces; reading
    and acting happen signed-in on the site."""
    if locale == "es":
        footer = (
            "Recibe este correo porque los avisos por correo de "
            "esta categoría están activados en su cuenta. "
            "Cámbielo en Ajustes → Notificaciones."
        )
    else:
        footer = (
            "You're getting this email because email alerts for "
            "this kind of notification are on in your account. "
            "Change it any time in Settings → Notifications."
        )
    return send_email(
        db,
        to=email,
        subject=title,
        body=f"{body}\n\n{footer}",
        kind=KIND_NOTIFICATION_EMAIL,
        locale=locale,
    )


def send_email_changed_notice(
    db: Session, old_email: str, new_email: str, locale: str = "en"
) -> bool:
    """Tell the OLD address that the account's email moved — the
    tripwire that makes a hijacked change visible to its owner."""
    if locale == "es":
        subject = "Se cambió el correo electrónico de su cuenta de Toolbox Vault"
        body = (
            "El correo electrónico de su cuenta de Toolbox Vault "
            f"acaba de cambiarse a {new_email}.\n\n"
            "A partir de ahora, iniciará sesión con la dirección "
            "nueva.\n\n"
            "Si usted no hizo este cambio, comuníquese con soporte "
            "de inmediato: es posible que otra persona haya tomado "
            "control de su cuenta."
        )
    else:
        subject = "Your Toolbox Vault email address was changed"
        body = (
            "The email address on your Toolbox Vault account was just "
            f"changed to {new_email}.\n\n"
            "From now on you sign in with the new address.\n\n"
            "If you didn't make this change, contact support right "
            "away — your account may have been taken over."
        )
    return send_email(
        db, to=old_email, subject=subject, body=body, kind=KIND_EMAIL_CHANGED_NOTICE,
        locale=locale,
    )

# 2026-10-22 (late): trigger deploy — sync MechanicVault GOOGLE_CLIENT_ID/SECRET + BACKUP_SA_KEY_B64 + BACKUP_DRIVE_FOLDER_ID secrets to the server.
