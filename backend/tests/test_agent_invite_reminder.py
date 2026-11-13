"""Thirty-day agent invite reminders (owner order, 2026-11-07).

A private agent record still unclaimed 30 days after its owner
created it earns the owner ONE inbox reminder to invite the
agent to join the network. Pins:

  - the 30-day clock: day 29 → nothing; day 30 → exactly one
    reminder naming the agent and the dealer, deep-linking to
    the dealer's Agents tab;
  - once-ever: back-to-back sweeps (and a later sweep) still
    total one notification — the record's invite_reminded_at
    stamp is the dedupe, written in the firing commit;
  - claimed before day 30 → never; claimed after firing → no
    second act;
  - deleted before day 30 → nothing, and no residue (the
    marker lives on the record and dies with it);
  - two records for one owner under different dealers → two
    reminders, one per record;
  - the copy lands in the owner's resolved locale (EN + ES);
  - the kind's wiring: dealers module gating (module off hides
    the note), dealers preference category (email twin OFF by
    default — an inbox note, not an email), and the scheduler
    registration (daily JobSpec that runs and ledgers ok).

Aging is done by seeding created_at after creation through the
app's own create path — the clock under test is the record's
own timestamp, exactly what the sweep reads.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.core import inbox, inbox_links, notification_prefs
from app.modules.core import models as core_models
from app.modules.dealers import invite_reminders
from app.modules.dealers import models as dealer_models
from app.modules.dealers import service as dealers_service

MECHANIC = "mechanic_technician"
NOW = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)


def _make_user(db, account_number, email, name, *, locale=None):
    user = core_models.User(
        id=uuid.uuid4(),
        account_number=account_number,
        email=email,
        name=name,
        password_hash="not-a-real-hash",
        account_types=[MECHANIC],
        locale=locale,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner(db):
    return _make_user(db, "TV-M-000701", "invite-owner@example.com", "Owen Owner")


@pytest.fixture()
def agent_user(db):
    return _make_user(db, "TV-M-000702", "invite-agent@example.com", "Andy Agent")


@pytest.fixture()
def matco(db):
    row = dealer_models.DealerCompany(name="Matco Tools", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def snapon(db):
    row = dealer_models.DealerCompany(name="Snap-on", is_directory=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _record(db, owner, company, name, age_days, now=NOW):
    """Create through the app's own path, then seed the age."""
    record = dealers_service.create_private_agent(
        db,
        owner.id,
        {
            "name": name,
            "company_id": company.id if company is not None else None,
        },
    )
    record.created_at = now - timedelta(days=age_days)
    db.commit()
    db.refresh(record)
    return record


def _reminders(db, owner):
    return list(
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == owner.id,
                core_models.Notification.kind == inbox.KIND_AGENT_INVITE_REMINDER,
            )
        )
    )


# -- the clock ------------------------------------------------------------------


def test_day_29_is_quiet_and_day_30_fires(db, owner, matco):
    young = _record(db, owner, matco, "Young Yale", 29)
    ripe = _record(db, owner, matco, "Ripe Ralph", 30)
    sent = invite_reminders.run_agent_invite_reminders(db, now=NOW)
    assert sent == 1
    rows = _reminders(db, owner)
    assert len(rows) == 1
    assert rows[0].data["private_agent_id"] == str(ripe.id)
    assert "Ripe Ralph" in rows[0].title
    assert "Ripe Ralph" in rows[0].body
    assert "Matco Tools" in rows[0].body
    db.refresh(young)
    db.refresh(ripe)
    assert young.invite_reminded_at is None
    # SQLite reads the stamp back naive (the codebase's standing
    # caveat); the instant is the sweep's.
    assert ripe.invite_reminded_at.replace(tzinfo=timezone.utc) == NOW


def test_back_to_back_sweeps_still_one(db, owner, matco):
    _record(db, owner, matco, "Ripe Ralph", 45)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 1
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 0
    later = NOW + timedelta(days=10)
    assert invite_reminders.run_agent_invite_reminders(db, now=later) == 0
    assert len(_reminders(db, owner)) == 1


# -- claimed records --------------------------------------------------------------


def test_claimed_before_day_30_never_reminds(db, owner, matco, agent_user):
    record = _record(db, owner, matco, "Claimed Carl", 31)
    # The state an accepted takeover lands in (takeover.py).
    record.linked_user_id = agent_user.id
    record.link_source = "takeover"
    db.commit()
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 0
    assert _reminders(db, owner) == []


def test_claimed_after_firing_earns_no_second_act(db, owner, matco, agent_user):
    record = _record(db, owner, matco, "Late Larry", 30)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 1
    record.linked_user_id = agent_user.id
    record.link_source = "takeover"
    db.commit()
    later = NOW + timedelta(days=15)
    assert invite_reminders.run_agent_invite_reminders(db, now=later) == 0
    assert len(_reminders(db, owner)) == 1


def test_archived_record_never_reminds(db, owner, matco):
    record = _record(db, owner, matco, "Archived Ann", 40)
    record.archived = True
    db.commit()
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 0
    assert _reminders(db, owner) == []


# -- deletion leaves nothing -------------------------------------------------------


def test_deleted_before_day_30_leaves_no_residue(db, owner, matco):
    record = _record(db, owner, matco, "Deleted Dan", 10)
    dealers_service.delete_private_agent(db, record)
    assert db.get(dealer_models.PrivateAgent, record.id) is None
    at_day_31 = record.created_at + timedelta(days=31)
    assert invite_reminders.run_agent_invite_reminders(db, now=at_day_31) == 0
    assert _reminders(db, owner) == []
    # No notification of any kind was minted for the owner.
    assert (
        db.scalars(
            select(core_models.Notification).where(
                core_models.Notification.user_id == owner.id
            )
        ).all()
        == []
    )


# -- one per record ------------------------------------------------------------------


def test_two_records_two_dealers_two_reminders(db, owner, matco, snapon):
    _record(db, owner, matco, "Matco Mike", 31)
    _record(db, owner, snapon, "Snap Sue", 60)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 2
    rows = _reminders(db, owner)
    assert len(rows) == 2
    bodies = {row.data["private_agent_id"]: row.body for row in rows}
    assert any("Matco Mike" in b and "Matco Tools" in b for b in bodies.values())
    assert any("Snap Sue" in b and "Snap-on" in b for b in bodies.values())
    links = inbox_links.resolve_links(db, owner, rows)
    assert set(links.values()) == {
        f"/dealers/{matco.id}#agents",
        f"/dealers/{snapon.id}#agents",
    }


def test_record_without_a_dealer_still_reminds_and_lands_on_dealers(
    db, owner
):
    _record(db, owner, None, "Solo Sam", 31)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 1
    rows = _reminders(db, owner)
    assert len(rows) == 1
    assert "Solo Sam" in rows[0].body
    links = inbox_links.resolve_links(db, owner, rows)
    assert links[rows[0].id] == "/dealers"


# -- locale ---------------------------------------------------------------------------


def test_spanish_owner_reads_spanish(db, matco):
    es_owner = _make_user(
        db, "TV-M-000703", "invite-es@example.com", "Elena Dueña", locale="es"
    )
    _record(db, es_owner, matco, "Agente Andrés", 31)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 1
    rows = _reminders(db, es_owner)
    assert len(rows) == 1
    assert rows[0].title == "Invita a Agente Andrés a unirse a Toolbox Vault"
    assert "todavía no está en Toolbox Vault" in rows[0].body
    assert "Matco Tools" in rows[0].body


# -- wiring ------------------------------------------------------------------------------


def test_kind_wiring_module_category_and_email_default(db, owner):
    kind = inbox.KIND_AGENT_INVITE_REMINDER
    assert inbox.KIND_MODULE[kind] == "dealers"
    assert (
        notification_prefs.category_for_kind(kind)
        == notification_prefs.CATEGORY_DEALERS
    )
    # The dealers category's email default is OFF: the reminder
    # is an inbox note, not an email, unless the owner opted in.
    assert notification_prefs.email_enabled_for_kind(db, owner.id, kind) is False
    assert inbox_links.KIND_LINKS[kind] == (
        inbox_links.F_DEALER_COMPANY,
        "/dealers",
    )


def test_dealers_module_off_hides_the_reminder(db, owner, matco):
    _record(db, owner, matco, "Hidden Hank", 31)
    assert invite_reminders.run_agent_invite_reminders(db, now=NOW) == 1
    # The inbox list is read on the real clock (the row's own
    # created_at is the insert instant, not the sweep's `now`).
    visible = inbox.list_for_user(db, owner.id)
    assert [v["kind"] for v in visible] == [inbox.KIND_AGENT_INVITE_REMINDER]
    db.add(
        core_models.UserModulePref(
            user_id=owner.id, module_id="dealers", enabled=False
        )
    )
    db.commit()
    hidden = inbox.list_for_user(db, owner.id)
    assert hidden == []


def test_scheduler_registration_runs_and_ledgers(db):
    from app.scripts import run_agent_invite_jobs, scheduler

    by_name = {spec.name: spec for spec in scheduler.JOBS}
    spec = by_name["agent-invite-reminders"]
    assert spec.module == "app.scripts.run_agent_invite_jobs"
    assert spec.interval_minutes == 1440
    assert run_agent_invite_jobs.run(db) == "agent invite reminders: 0 sent"
    row = scheduler.run_job(db, spec)
    assert row.status == "ok"
    assert "0 sent" in row.detail["summary"]
