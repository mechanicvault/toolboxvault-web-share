"""Thirty-day agent invite reminders (owner order, 2026-11-07).

A private agent record is a name a user typed in for an agent
who isn't on Toolbox Vault yet. The record carries an agent
code precisely so the owner can hand it over: when the real
agent signs up, enters the code and the owner accepts, the
record becomes his working seat. When a record has sat
UNCLAIMED for 30 days, its owner gets ONE inbox reminder to
make that invitation.

Posture:

  - ONE reminder per record, ever. The dedupe is the record's
    own invite_reminded_at stamp, written in the same commit
    as the notification — the claims backorder reminder's
    pattern (backorder_last_reminded_at). Re-runs, scheduler
    restarts and back-to-back sweeps are no-ops by
    construction; an owner deleting the inbox note cannot
    resurrect a second one; and a record deleted before day
    30 takes the marker with it — no residue anywhere.
  - "Unclaimed" is the record's own state: linked_user_id NULL
    (no registered agent has claimed it through the code
    hand-over or been linked to it) and not archived. A record
    claimed before day 30 never earns the reminder; one
    claimed after it fired earns no second act — the stamp
    already sits. The clock is the record's created_at.
  - The note names the agent and his dealer and deep-links
    (inbox_links, F_DEALER_COMPANY) to the dealer's Agents
    tab, where the code and the copyable invite message live.
  - Copy is written in the OWNER's resolved locale
    (app.core.i18n.resolve_locale — the one locale rule the
    report chrome and the account emails also resolve by).
    Inbox rows store a single title/body string; a sweep
    creating a note for one known owner is where that owner's
    locale is knowable at write time.

The scheduler job (app/scripts/run_agent_invite_jobs.py) runs
this daily; it is quiet when nothing qualifies.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import i18n
from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.dealers import models

REMINDER_AGE_DAYS = 30

_COPY = {
    "en": {
        "title": "Invite {agent} to join Toolbox Vault",
        "body_dealer": (
            "{agent} at {dealer} still isn't on Toolbox Vault — "
            "this record has been in your book for 30 days. Invite "
            "him to sign up and hand him your agent code: when he "
            "enters it and you accept, this record becomes his, "
            "and he can work your claims and truck account with "
            "you. You'll find the code and a ready-to-send invite "
            "message on {dealer}'s Agents tab."
        ),
        "body_no_dealer": (
            "{agent} still isn't on Toolbox Vault — this record "
            "has been in your book for 30 days. Invite him to "
            "sign up and hand him your agent code: when he "
            "enters it and you accept, this record becomes his, "
            "and he can work your claims and truck account with "
            "you. You'll find the code and a ready-to-send invite "
            "message with his record in your agents."
        ),
    },
    "es": {
        "title": "Invita a {agent} a unirse a Toolbox Vault",
        "body_dealer": (
            "{agent}, de {dealer}, todavía no está en Toolbox "
            "Vault — este registro lleva 30 días en tu lista. "
            "Invítalo a registrarse y entrégale tu código de "
            "agente: cuando lo ingrese y lo aceptes, este "
            "registro será suyo y podrá trabajar tus reclamos y "
            "tu cuenta de camión contigo. El código y un mensaje "
            "de invitación listo para enviar están en la pestaña "
            "Agentes de {dealer}."
        ),
        "body_no_dealer": (
            "{agent} todavía no está en Toolbox Vault — este "
            "registro lleva 30 días en tu lista. Invítalo a "
            "registrarse y entrégale tu código de agente: cuando "
            "lo ingrese y lo aceptes, este registro será suyo y "
            "podrá trabajar tus reclamos y tu cuenta de camión "
            "contigo. El código y un mensaje de invitación listo "
            "para enviar están junto a su registro en tus "
            "agentes."
        ),
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_agent_invite_reminders(
    db: Session, now: datetime | None = None
) -> int:
    """Send the 30-day invite reminder for every private agent
    record that qualifies right now: at least REMINDER_AGE_DAYS
    old, still unclaimed (never linked to a registered agent),
    not archived, and never reminded. Each fired record is
    stamped in the same commit as its notification. Returns how
    many reminders were sent."""
    now = now or _now()
    cutoff = now - timedelta(days=REMINDER_AGE_DAYS)
    records = db.scalars(
        select(models.PrivateAgent).where(
            models.PrivateAgent.linked_user_id.is_(None),
            models.PrivateAgent.archived.is_(False),
            models.PrivateAgent.invite_reminded_at.is_(None),
            models.PrivateAgent.created_at <= cutoff,
        )
    ).all()
    reminded = 0
    for record in records:
        owner = db.get(core_models.User, record.owner_id)
        if owner is None:
            continue
        company = (
            db.get(models.DealerCompany, record.company_id)
            if record.company_id is not None
            else None
        )
        copy = _COPY[i18n.resolve_locale(owner)]
        if company is not None:
            body = copy["body_dealer"].format(
                agent=record.name, dealer=company.name
            )
        else:
            body = copy["body_no_dealer"].format(agent=record.name)
        inbox.create_notification(
            db,
            record.owner_id,
            kind=inbox.KIND_AGENT_INVITE_REMINDER,
            title=copy["title"].format(agent=record.name),
            body=body,
            data={
                "private_agent_id": str(record.id),
                "company_id": (
                    str(record.company_id) if record.company_id else ""
                ),
            },
            commit=False,
        )
        record.invite_reminded_at = now
        reminded += 1
    db.commit()
    return reminded
