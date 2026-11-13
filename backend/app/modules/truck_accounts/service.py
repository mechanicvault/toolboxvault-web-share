"""Truck Accounts service — the two-party tab's whole logic.

Flows: an AGENT creates under a dealer COMPANY they
verified-represent (existing customer by exact account
number, or email invite that attaches pre-signup at signup —
the peer-invite pattern, no existence oracle) → customer
accepts by accepting the CURRENT agreement (version + full text
snapshot stored) or declines (account closes) → either party
records charges/payments → both parties are inbox-notified on
every entry with the new balance → the scheduler job sends
due-soon / overdue reminders → either party closes (ledger
frozen, history kept).

Agent revision (2026-10-31): the account's agent holder is the
claims exactly-one shape — dealer_user_id (a platform agent) OR
private_agent_id (the customer's own private record for an
off-platform agent; while set, the customer maintains the tab
himself: he records every entry kind and sets the schedule).
Route changes NEVER move an account — the only way the holder
changes is transfer_account, the customer's deliberate act,
written to truck_account_transfers with name snapshots.

Rules that keep the tab honest:
- Entries are append-only through every surface here; a wrong
  entry is corrected by an ADJUSTMENT entry, never an edit.
- Charges are the DEALER's pen; payments either party may
  record (cash/check at the truck); adjustments either party
  (they notify both sides like everything else).
- The balance is SUM(amount) at read time — never stored.
- next_due_date advances ONLY when a payment lands (one
  cadence cycle from the current due date — settle-oldest, so
  paying early never shortens the runway and paying late works
  the missed count down one settled cycle at a time): the
  reminders key off the date, so it can only remind once.
"""

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.truck_accounts import agreement as agreement_mod
from app.modules.truck_accounts import models

DUE_SOON_DAYS = 3
_CADENCE_DAYS = {"weekly": 7, "biweekly": 14}

# The transfer notification kind. Registered in
# core/notification_prefs.KIND_CATEGORY (truck-accounts
# category); the bell carries it with the account id in data.
KIND_TRUCK_TRANSFERRED = "truck_account_transferred"

# Stage 2 (2026-11-05): the note a self-kept account's opening
# entry carries when the customer didn't write one of his own —
# an opening balance is an increase, and every increase is
# explained (the owner's rule); this is its explanation.
OPENING_BALANCE_NOTE = "Opening balance"

# How many missed due dates the detail read lists individually
# (the COUNT is always exact; a years-stale tab doesn't need a
# thousand rows to say it's behind).
MISSED_DATES_LIST_CAP = 52


class TruckError(ValueError):
    """Caller turns this into a friendly 422."""


class TruckNotFound(TruckError):
    """Missing OR not-the-callers — one answer, no oracle."""


def _money_text(amount, currency: str = "USD") -> str:
    """Notification money text — the ONE formatter (wave 3). A
    truck account's amounts read in the DEALER's currency: the
    dealer sets the tab's terms (v1 semantics)."""
    from app.modules.core import money as core_money

    return core_money.format_money(Decimal(amount), currency)


def _account_currency(db: Session, account: models.TruckAccount) -> str:
    from app.modules.core import money as core_money

    dealer = _user(db, account.dealer_user_id)
    return core_money.normalize_currency(dealer.currency if dealer else "USD")


def _user(db: Session, user_id) -> core_models.User | None:
    if user_id is None:
        return None
    return db.get(core_models.User, uuid.UUID(str(user_id)))


def _display_name(db: Session, account: models.TruckAccount, side: str) -> str:
    """The name one party sees for the OTHER (or their counterparty
    labels): a deleted side reads as its snapshot / 'Former
    member'; a live side reads as their current name."""
    if side == "customer":
        if account.customer_deleted:
            return account.customer_name or "Former member"
        user = _user(db, account.customer_user_id)
        return (user.name if user else None) or account.customer_name or "Customer"
    return agent_display_name(db, account)


# -- the agent + company links (2026-10-31) --------------------------------------


def _agent_profile(db: Session, user_id) -> object | None:
    if user_id is None:
        return None
    from app.modules.dealers import models as dealer_models

    return db.scalar(
        select(dealer_models.AgentProfile).where(
            dealer_models.AgentProfile.user_id == uuid.UUID(str(user_id))
        )
    )


def _platform_agent_name(db: Session, user_id) -> str:
    """A platform agent's display name: their agent profile's
    display name when they set one, else their account name,
    else the snapshot the account carries."""
    profile = _agent_profile(db, user_id)
    if profile is not None and profile.display_name:
        return profile.display_name
    user = _user(db, user_id)
    return (user.name if user else None) or ""


def _private_agent(db: Session, account: models.TruckAccount):
    if account.private_agent_id is None:
        return None
    from app.modules.dealers import models as dealer_models

    return db.get(dealer_models.PrivateAgent, account.private_agent_id)


def agent_display_name(db: Session, account: models.TruckAccount) -> str:
    """The CURRENT agent's name as the customer sees it ("open
    balance with agent Matt"): the private record's name while a
    private agent holds the account; the platform agent's
    display name while one holds it; the issue/transfer snapshot
    when the holder is gone (deleted account or record)."""
    if account.private_agent_id is not None:
        record = _private_agent(db, account)
        if record is not None:
            return record.name
        return account.agent_name_snapshot or "Dealer"
    if account.dealer_deleted:
        return "Former member"
    if account.dealer_user_id is not None:
        return (
            _platform_agent_name(db, account.dealer_user_id)
            or account.agent_name_snapshot
            or "Dealer"
        )
    return account.agent_name_snapshot or "Dealer"


def agent_kind(account: models.TruckAccount) -> str | None:
    """"platform" while a platform agent user holds the account,
    "private" while the customer's private record does, None
    when neither does (a legacy account whose agent is unknown,
    or a holder that went away)."""
    if account.private_agent_id is not None:
        return "private"
    if account.dealer_user_id is not None:
        return "platform"
    return None


def company_display_name(
    db: Session, account: models.TruckAccount, viewer_id=None
) -> str | None:
    """The company the account is under: the live company's name
    while it exists, else the snapshot taken at issue.
    `viewer_id` (personal dealer edits, 2026-11-05): the name
    AS THAT VIEWER SEES IT — his personal layer when he has one.
    Callers resolving a name for a specific reader pass that
    reader; shared or outward-facing reads (a notification to
    the OTHER party, the agent's own surfaces) pass nothing and
    keep the directory name."""
    if account.dealer_company_id is not None:
        from app.modules.dealers import models as dealer_models

        company = db.get(dealer_models.DealerCompany, account.dealer_company_id)
        if company is not None:
            if viewer_id is not None and company.is_directory:
                from app.modules.dealers import service as dealer_service

                return dealer_service.personal_company_name(db, viewer_id, company)
            return company.name
    return account.dealer_company_name or None


def verified_representations(db: Session, user_id) -> list:
    """The (representation, company) pairs this user VERIFIED-
    represents: the only companies an agent may issue truck
    accounts under (representations exist for directory
    companies only)."""
    from app.modules.dealers import models as dealer_models

    rows = db.execute(
        select(
            dealer_models.CompanyRepresentation, dealer_models.DealerCompany
        )
        .join(
            dealer_models.DealerCompany,
            dealer_models.DealerCompany.id
            == dealer_models.CompanyRepresentation.company_id,
        )
        .where(
            dealer_models.CompanyRepresentation.agent_user_id
            == uuid.UUID(str(user_id)),
            dealer_models.CompanyRepresentation.verified.is_(True),
        )
        .order_by(dealer_models.DealerCompany.name)
    ).all()
    return [(rep, company) for rep, company in rows]


def issuable_companies(db: Session, dealer: core_models.User) -> list[dict]:
    """The companies this agent can open truck accounts under
    right now — drives the create form's company picker."""
    return [
        {"company_id": company.id, "company_name": company.name}
        for _rep, company in verified_representations(db, dealer.id)
    ]


# -- balance + entries -------------------------------------------------------------


def balance_of(db: Session, account_id: uuid.UUID) -> Decimal:
    """THE balance rule: the signed sum of the ledger. Computed
    on every read; a test pins it against the entry list so the
    two can never drift."""
    total = db.scalar(
        select(func.coalesce(func.sum(models.TruckEntry.amount), 0)).where(
            models.TruckEntry.account_id == account_id
        )
    )
    return Decimal(total or 0)


def _raise_peak(account: models.TruckAccount, balance: Decimal) -> None:
    """Highest-credit-limit maintenance (owner, 2026-11-05):
    the stored peak moves ONLY up. Every entry write calls
    this with the balance the write left behind; when that
    balance tops every balance the account has stood at, the
    peak rises to it — payments and downward adjustments call
    it too and change nothing, which is the point: the highest
    balance ever owed survives paying it down, and because
    the value is stored (never recomputed from the ledger),
    no later entry edit can rewrite it either."""
    current = account.highest_balance or Decimal("0")
    if balance > current:
        account.highest_balance = balance


def list_entries(db: Session, account: models.TruckAccount) -> list[models.TruckEntry]:
    rows = list(
        db.scalars(
            select(models.TruckEntry).where(
                models.TruckEntry.account_id == account.id
            )
        )
    )
    rows.sort(key=lambda r: (r.entry_date, r.created_at, str(r.id)))
    return rows


def schedule_status(
    db: Session, account: models.TruckAccount, *, today: date | None = None
) -> dict:
    """The account's schedule state, COMPUTED at read time from
    the stored facts (cadence + per-cycle amount + the next due
    date the payment-advance rule maintains) and the balance —
    never stored, so it can never disagree with the ledger.

    Missed payments (stage 2, the owner's rule: "payments missed
    will show as missed"): while the next due date stands in the
    past, every cadence cycle that has come due since it —
    including the standing due date itself — is a payment that
    came due and wasn't paid (a payment landing advances the due
    date one cycle, which is exactly one missed payment settled).
    They are COUNTED and LISTED BY DATE, never silently skipped
    the way the app advanced past them. The amount past due is
    the missed count × the cycle amount, capped at the balance
    actually owed. No schedule (no amount or no due date), a
    closed/invited account, or nothing owed = no missed state.
    """
    today = today or date.today()
    empty = {
        "has_schedule": False,
        "overdue": False,
        "missed_payments": 0,
        "missed_due_dates": [],
        "amount_past_due": Decimal("0"),
        "days_until_due": None,
    }
    if (
        account.status != "active"
        or account.payment_amount is None
        or account.next_due_date is None
    ):
        return empty
    balance = balance_of(db, account.id)
    due = account.next_due_date
    result = dict(empty)
    result["has_schedule"] = True
    result["days_until_due"] = (due - today).days
    if balance <= 0 or due >= today:
        return result
    cycle = _CADENCE_DAYS.get(account.payment_cadence, 7)
    missed = (today - due).days // cycle + 1
    from datetime import timedelta as _td

    result["overdue"] = True
    result["missed_payments"] = missed
    result["missed_due_dates"] = [
        due + _td(days=cycle * k)
        for k in range(min(missed, MISSED_DATES_LIST_CAP))
    ]
    result["amount_past_due"] = min(
        account.payment_amount * missed, balance
    )
    return result


# -- reads ---------------------------------------------------------------------------


def get_account(
    db: Session, user_id: uuid.UUID, account_id: uuid.UUID
) -> models.TruckAccount | None:
    account = db.get(models.TruckAccount, account_id)
    if account is None:
        return None
    if user_id in (account.dealer_user_id, account.customer_user_id):
        return account
    if takeover_holder_user_id(db, account) == user_id:
        return account
    return None


def role_of(account: models.TruckAccount, user_id: uuid.UUID) -> str | None:
    if user_id == account.dealer_user_id and not account.dealer_deleted:
        return "dealer"
    if user_id == account.customer_user_id and not account.customer_deleted:
        return "customer"
    return None


def takeover_holder_user_id(
    db: Session, account: models.TruckAccount
) -> uuid.UUID | None:
    """The platform agent who has TAKEN OVER the private record
    holding this account (agent takeover, 2026-11-03), else None.
    The account's holder stays the record — claims doctrine: the
    record is the working seat — and the seat resolves through
    the record's live takeover link. The moment the link is
    severed (the agent's account deleted, say) this returns None
    and the account is the customer's private tab again, data
    untouched."""
    if account.private_agent_id is None:
        return None
    record = _private_agent(db, account)
    if record is None or record.archived or record.link_source != "takeover":
        return None
    return record.linked_user_id


def effective_role(
    db: Session, account: models.TruckAccount, user_id: uuid.UUID
) -> str | None:
    """role_of, plus the takeover seat: an agent who claimed the
    holding record stands in the dealer seat for this account."""
    role = role_of(account, user_id)
    if role is not None:
        return role
    if (
        not account.dealer_deleted
        and takeover_holder_user_id(db, account) == user_id
    ):
        return "dealer"
    return None


def accounts_for_user(
    db: Session, user_id: uuid.UUID
) -> list[models.TruckAccount]:
    rows = list(
        db.scalars(
            select(models.TruckAccount).where(
                (models.TruckAccount.dealer_user_id == user_id)
                | (models.TruckAccount.customer_user_id == user_id)
            )
        )
    )
    # Accounts held by private records this user has taken over
    # ride along — the agent works them from the same list.
    from app.modules.dealers import models as dealer_models

    claimed_record_ids = list(
        db.scalars(
            select(dealer_models.PrivateAgent.id).where(
                dealer_models.PrivateAgent.linked_user_id == user_id,
                dealer_models.PrivateAgent.link_source == "takeover",
            )
        )
    )
    if claimed_record_ids:
        seen = {a.id for a in rows}
        rows.extend(
            a
            for a in db.scalars(
                select(models.TruckAccount).where(
                    models.TruckAccount.private_agent_id.in_(claimed_record_ids)
                )
            )
            if a.id not in seen
        )
    rows.sort(key=lambda a: a.created_at, reverse=True)
    return rows


def serialize_account(
    db: Session, account: models.TruckAccount, viewer_id: uuid.UUID
) -> dict:
    from app.modules.truck_accounts import truck_payments

    dealer = _user(db, account.dealer_user_id)
    customer = _user(db, account.customer_user_id)
    balance = balance_of(db, account.id)
    # The dealer's-page truck rows (dealer page pass,
    # 2026-11-06) show where the account STARTED next to where
    # it stands: the balance starts at zero, so the starting
    # balance is the signed amount of the ledger's first entry
    # (an opening balance where one was entered, the first
    # charge otherwise); an account with no entries started
    # — and stands — at zero.
    entries = list_entries(db, account)
    starting_balance = entries[0].amount if entries else Decimal("0")
    # The takeover seat (2026-11-03): while a claimed private
    # record holds the account, its agent is the working dealer —
    # the role, the maintained-by flag and online-payment
    # readiness all resolve to them.
    holder_id = takeover_holder_user_id(db, account)
    schedule = schedule_status(db, account)
    return {
        "id": account.id,
        "dealer_user_id": account.dealer_user_id,
        "dealer_name": (
            None if account.dealer_deleted
            else (dealer.name if dealer else None)
        ),
        "dealer_account_number": (
            dealer.account_number if dealer and not account.dealer_deleted
            else None
        ),
        # The agent + company face (2026-10-31): who holds the
        # dealer side AS AN AGENT and under which company the
        # account nests. agent_name is the name the customer
        # reads ("open balance with agent Matt").
        "dealer_company_id": account.dealer_company_id,
        "dealer_company_name": company_display_name(db, account, viewer_id),
        "agent_name": agent_display_name(db, account),
        "agent_kind": agent_kind(account),
        # Stage 2: the private record holding the account (the
        # customer's deep link back to the agent record), who
        # keeps the ledger, the stored pay-through-the-site
        # choice, and the computed missed-payment state.
        "private_agent_id": account.private_agent_id,
        "ledger_keeper": account.ledger_keeper,
        "payment_mode": account.payment_mode,
        "missed_payments": schedule["missed_payments"],
        "amount_past_due": schedule["amount_past_due"],
        "credit_limit": account.credit_limit,
        "credit_available": (
            account.credit_limit - balance
            if account.credit_limit is not None
            else None
        ),
        # True while the CUSTOMER maintains the tab himself: a
        # self-kept account (stage 2's ledger_keeper), or no
        # platform agent holding it (a private agent record —
        # unclaimed — or a tab with no agent). A takeover-claimed
        # record's agent holds an agent-kept account.
        "customer_maintained": (
            account.ledger_keeper == "customer"
            or (account.dealer_user_id is None and holder_id is None)
        ),
        "customer_user_id": account.customer_user_id,
        "customer_name": _display_name(db, account, "customer"),
        "customer_account_number": (
            customer.account_number
            if customer and not account.customer_deleted
            else None
        ),
        "customer_email": account.customer_email,
        "status": account.status,
        "payment_cadence": account.payment_cadence,
        "payment_amount": account.payment_amount,
        "next_due_date": account.next_due_date,
        "balance": balance,
        "starting_balance": starting_balance,
        # The highest credit limit (0080): the stored peak —
        # the highest balance this account has ever stood at.
        "highest_balance": account.highest_balance or Decimal("0"),
        "agreement_version": account.agreement_version,
        "agreement_accepted_at": account.agreement_accepted_at,
        "my_role": effective_role(db, account, viewer_id),
        "pay_online_available": truck_payments.dealer_connect_ready(
            db, account.dealer_user_id or holder_id
        ),
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _entry_item(db: Session, entry: models.TruckEntry) -> tuple[str | None, str | None]:
    """Resolve a charge's item link (stage 2): the item's name
    + kind ("tool" | "set" | "battery") so the ledger can link
    through to the item itself — every tool charge names WHICH
    tool raised the balance (the owner's rule). The link id is
    a plain stored id with no kind of its own, so resolution
    asks the inventory tables; a deleted item resolves to
    (None, None) and the row stands on its note alone."""
    if entry.item_link_id is None:
        return None, None
    from app.modules.inventory import models as inv_models

    tool = db.get(inv_models.Tool, entry.item_link_id)
    if tool is not None:
        return tool.name, ("set" if tool.is_set else "tool")
    battery = db.get(inv_models.Battery, entry.item_link_id)
    if battery is not None:
        return battery.name, "battery"
    return None, None


def serialize_entry(db: Session, entry: models.TruckEntry) -> dict:
    recorder = _user(db, entry.recorded_by)
    item_name, item_kind = _entry_item(db, entry)
    return {
        "id": entry.id,
        "account_id": entry.account_id,
        "kind": entry.kind,
        "amount": entry.amount,
        "note": entry.note,
        "item_link_id": entry.item_link_id,
        "item_name": item_name,
        "item_kind": item_kind,
        "entry_date": entry.entry_date,
        "source": entry.source,
        "recorded_by": entry.recorded_by,
        "recorded_by_name": recorder.name if recorder else None,
        "created_at": entry.created_at,
    }


def account_detail(
    db: Session, account: models.TruckAccount, viewer_id: uuid.UUID
) -> dict:
    view = serialize_account(db, account, viewer_id)
    preview = None
    if account.status == "invited" and effective_role(db, account, viewer_id) in (
        "customer",
        "dealer",
    ):
        preview = agreement_mod.render_agreement(
            db,
            dealer_name=_display_name(db, account, "dealer"),
            cadence=account.payment_cadence,
            payment_amount=account.payment_amount,
            currency=_account_currency(db, account),
        )
    return {
        "account": view,
        "entries": [serialize_entry(db, e) for e in list_entries(db, account)],
        "agreement_preview": preview,
        # Stage 2: the computed schedule state (missed payments
        # listed by date) and the payment-request conversation —
        # both parties' record, like the ledger itself.
        "schedule": schedule_status(db, account),
        "payment_requests": [
            serialize_payment_request(db, r)
            for r in list_payment_requests(db, account)
        ],
        # The transfer history + (for the customer) the agents
        # this account could move to — the account's history is
        # both parties' record; the options are the customer's
        # choices only.
        "transfers": [
            serialize_transfer(db, row) for row in list_transfers(db, account)
        ],
        "transfer_options": (
            transfer_options(db, account)
            if effective_role(db, account, viewer_id) == "customer"
            else []
        ),
    }


# -- transfers (2026-10-31) --------------------------------------------------------


def list_transfers(
    db: Session, account: models.TruckAccount
) -> list[models.TruckAccountTransfer]:
    rows = list(
        db.scalars(
            select(models.TruckAccountTransfer).where(
                models.TruckAccountTransfer.account_id == account.id
            )
        )
    )
    rows.sort(key=lambda r: (r.created_at, str(r.id)))
    return rows


def serialize_transfer(
    db: Session, row: models.TruckAccountTransfer
) -> dict:
    return {
        "id": row.id,
        "from_agent_name": row.from_agent_name,
        "to_agent_name": row.to_agent_name,
        "from_agent_kind": (
            "private"
            if row.from_private_agent_id is not None
            else ("platform" if row.from_agent_user_id is not None else None)
        ),
        "to_agent_kind": (
            "private"
            if row.to_private_agent_id is not None
            else ("platform" if row.to_agent_user_id is not None else None)
        ),
        "created_at": row.created_at,
    }


def transfer_options(db: Session, account: models.TruckAccount) -> list[dict]:
    """The agents the CUSTOMER could transfer this account to:
    every OTHER platform user who verified-represents the
    account's company, plus the customer's own live private
    agent records for that company. Empty while the account has
    no company (a legacy account nests nowhere, so there is no
    'same dealer' to transfer within) or is closed."""
    if account.dealer_company_id is None or account.status == "closed":
        return []
    from app.modules.dealers import models as dealer_models

    options: list[dict] = []
    reps = db.execute(
        select(
            dealer_models.CompanyRepresentation, dealer_models.DealerCompany
        )
        .join(
            dealer_models.DealerCompany,
            dealer_models.DealerCompany.id
            == dealer_models.CompanyRepresentation.company_id,
        )
        .where(
            dealer_models.CompanyRepresentation.company_id
            == account.dealer_company_id,
            dealer_models.CompanyRepresentation.verified.is_(True),
        )
    ).all()
    for rep, _company in reps:
        if rep.agent_user_id == account.dealer_user_id:
            continue
        options.append(
            {
                "kind": "platform",
                "agent_user_id": rep.agent_user_id,
                "private_agent_id": None,
                "name": _platform_agent_name(db, rep.agent_user_id)
                or "Agent",
            }
        )
    if account.customer_user_id is not None:
        records = list(
            db.scalars(
                select(dealer_models.PrivateAgent).where(
                    dealer_models.PrivateAgent.owner_id
                    == account.customer_user_id,
                    dealer_models.PrivateAgent.company_id
                    == account.dealer_company_id,
                    dealer_models.PrivateAgent.archived.is_(False),
                )
            )
        )
        for record in records:
            if record.id == account.private_agent_id:
                continue
            options.append(
                {
                    "kind": "private",
                    "agent_user_id": None,
                    "private_agent_id": record.id,
                    "name": record.name,
                }
            )
    options.sort(key=lambda o: o["name"].lower())
    return options


def transfer_account(
    db: Session,
    customer: core_models.User,
    account: models.TruckAccount,
    *,
    to_agent_user_id: uuid.UUID | None = None,
    to_private_agent_id: uuid.UUID | None = None,
) -> models.TruckAccount:
    """The customer's deliberate move of his account to a new
    agent of the SAME dealer company. Balances, schedule and
    history carry over untouched; the old holder loses the
    dealer seat the moment the transfer lands; the move is
    written to the transfer history with name snapshots, and
    both platform holders (old and new) are inbox-notified."""
    if role_of(account, customer.id) != "customer":
        raise TruckError("Only the customer can transfer this account.")
    if account.status == "closed":
        raise TruckError("This account is closed — it can't be transferred.")
    if account.dealer_company_id is None:
        raise TruckError(
            "This account isn't under a dealer company yet, so "
            "there's no new agent of the same dealer to move it to."
        )
    if bool(to_agent_user_id) == bool(to_private_agent_id):
        raise TruckError("Pick exactly one new agent for the transfer.")

    from_name = agent_display_name(db, account)
    from_user_id = account.dealer_user_id
    from_private_id = account.private_agent_id

    new_user_id: uuid.UUID | None = None
    new_private_id: uuid.UUID | None = None
    new_name = ""
    if to_agent_user_id is not None:
        target = uuid.UUID(str(to_agent_user_id))
        if target == account.dealer_user_id:
            raise TruckError("That agent already holds this account.")
        allowed = {
            opt["agent_user_id"]
            for opt in transfer_options(db, account)
            if opt["kind"] == "platform"
        }
        if target not in allowed:
            raise TruckError(
                "That agent doesn't represent this dealer — pick "
                "one of the company's agents."
            )
        new_user_id = target
        new_name = _platform_agent_name(db, target) or "Agent"
    else:
        target_private = uuid.UUID(str(to_private_agent_id))
        if target_private == account.private_agent_id:
            raise TruckError("That agent already holds this account.")
        allowed_private = {
            opt["private_agent_id"]
            for opt in transfer_options(db, account)
            if opt["kind"] == "private"
        }
        if target_private not in allowed_private:
            raise TruckError(
                "That record isn't one of your agents for this "
                "dealer — pick from your agents for the company."
            )
        from app.modules.dealers import models as dealer_models

        record = db.get(dealer_models.PrivateAgent, target_private)
        new_private_id = target_private
        new_name = record.name if record is not None else "Agent"

    account.dealer_user_id = new_user_id
    account.private_agent_id = new_private_id
    account.dealer_deleted = False
    account.agent_name_snapshot = new_name
    db.add(
        models.TruckAccountTransfer(
            account_id=account.id,
            from_agent_user_id=from_user_id,
            from_private_agent_id=from_private_id,
            from_agent_name=from_name,
            to_agent_user_id=new_user_id,
            to_private_agent_id=new_private_id,
            to_agent_name=new_name,
            transferred_by=customer.id,
        )
    )
    db.flush()
    company_name = company_display_name(db, account) or "your dealer"
    if from_user_id is not None and from_user_id != customer.id:
        inbox.create_notification(
            db,
            from_user_id,
            kind=KIND_TRUCK_TRANSFERRED,
            title="Truck account transferred",
            body=(
                f"{account.customer_name or 'A customer'} moved their "
                f"{company_name} truck account to {new_name}. The "
                "balance and history went with it."
            ),
            data={"account_id": str(account.id)},
            commit=False,
        )
    if new_user_id is not None:
        inbox.create_notification(
            db,
            new_user_id,
            kind=KIND_TRUCK_TRANSFERRED,
            title="Truck account transferred to you",
            body=(
                f"{account.customer_name or 'A customer'} moved their "
                f"{company_name} truck account to you, with a balance "
                f"of {_money_text(balance_of(db, account.id), _account_currency(db, account))}."
            ),
            data={"account_id": str(account.id)},
            commit=False,
        )
    db.commit()
    db.refresh(account)
    return account


# -- payment requests (stage 2, 2026-11-05) ---------------------------------------
#
# On a CUSTOMER-KEPT account with a platform agent on the other
# seat, the agent's write path for money is a REQUEST: he asks,
# the customer approves or declines. Approval writes the
# payment entry itself (source "agent_request" — the ledger
# shows it was requested-by-agent and customer-confirmed);
# declining closes the request with an optional note. No money
# moves anywhere — the entry records the payment the customer
# confirms he made, exactly like a hand-recorded payment.


def list_payment_requests(
    db: Session, account: models.TruckAccount
) -> list[models.TruckPaymentRequest]:
    rows = list(
        db.scalars(
            select(models.TruckPaymentRequest).where(
                models.TruckPaymentRequest.account_id == account.id
            )
        )
    )
    rows.sort(key=lambda r: (r.created_at, str(r.id)))
    return rows


def serialize_payment_request(
    db: Session, row: models.TruckPaymentRequest
) -> dict:
    requester = _user(db, row.requested_by)
    decider = _user(db, row.decided_by)
    return {
        "id": row.id,
        "account_id": row.account_id,
        "requested_by": row.requested_by,
        "requested_by_name": requester.name if requester else None,
        "amount": row.amount,
        "note": row.note,
        "status": row.status,
        "entry_id": row.entry_id,
        "decided_by": row.decided_by,
        "decided_by_name": decider.name if decider else None,
        "decided_at": row.decided_at,
        "decision_note": row.decision_note,
        "created_at": row.created_at,
    }


def _request_or_404(
    db: Session, account: models.TruckAccount, request_id
) -> models.TruckPaymentRequest:
    row = db.get(models.TruckPaymentRequest, uuid.UUID(str(request_id)))
    if row is None or row.account_id != account.id:
        raise TruckNotFound("That payment request doesn't exist.")
    return row


def request_payment(
    db: Session,
    agent: core_models.User,
    account: models.TruckAccount,
    *,
    amount: Decimal,
    note: str = "",
) -> models.TruckPaymentRequest:
    """The agent asks the customer for a payment on a shared,
    customer-kept account. One open request per account: a
    second ask while one is unanswered is refused, so the
    customer always faces exactly one decision at a time."""
    if effective_role(db, account, agent.id) != "dealer":
        raise TruckNotFound("That truck account doesn't exist.")
    if account.ledger_keeper != "customer":
        raise TruckError(
            "Payment requests are for accounts the customer keeps "
            "himself — on this account you record entries directly."
        )
    if account.status == "closed":
        raise TruckError("This account is closed — its ledger is frozen.")
    if account.status != "active":
        raise TruckError("This account isn't active yet.")
    amount = Decimal(amount)
    if amount <= 0:
        raise TruckError("A payment request must be more than zero.")
    pending = [
        r for r in list_payment_requests(db, account) if r.status == "pending"
    ]
    if pending:
        raise TruckError(
            "A payment request is already waiting on this account — "
            "the customer answers one at a time."
        )
    row = models.TruckPaymentRequest(
        account_id=account.id,
        requested_by=agent.id,
        amount=amount,
        note=(note or "").strip(),
    )
    db.add(row)
    db.flush()
    if account.customer_user_id is not None and not account.customer_deleted:
        # The notification speaks to the CUSTOMER — his name for
        # the dealer (personal edits, 2026-11-05).
        company_name = (
            company_display_name(db, account, account.customer_user_id)
            or "your dealer"
        )
        inbox.create_notification(
            db,
            account.customer_user_id,
            kind=inbox.KIND_TRUCK_PAYMENT_REQUESTED,
            title="Payment requested",
            body=(
                f"{agent_display_name(db, account)} ({company_name}) "
                f"requested a payment of "
                f"{_money_text(amount, _account_currency(db, account))} "
                "on your truck account. Approve it to record the "
                "payment, or decline it."
            ),
            data={"account_id": str(account.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def decide_payment_request(
    db: Session,
    customer: core_models.User,
    account: models.TruckAccount,
    request_id,
    *,
    approve: bool,
    note: str = "",
) -> models.TruckPaymentRequest:
    """The customer's answer. Approval IS the payment: it posts
    the ledger entry through the same add_entry path a hand-
    recorded payment takes (due date advances, both sides
    notified), marked source "agent_request", and the request
    row points at it. Declining writes no entry — just the
    decision and its note, told to the agent."""
    if role_of(account, customer.id) != "customer":
        raise TruckNotFound("That truck account doesn't exist.")
    row = _request_or_404(db, account, request_id)
    if row.status != "pending":
        raise TruckError("That payment request was already answered.")
    row.status = "approved" if approve else "declined"
    row.decided_by = customer.id
    row.decided_at = datetime.now(timezone.utc)
    row.decision_note = (note or "").strip()
    db.flush()
    entry = None
    if approve:
        entry = add_entry(
            db,
            customer,
            account,
            kind="payment",
            amount=row.amount,
            note=row.note
            or f"Payment requested by {agent_display_name(db, account)}",
            source="agent_request",
        )
        row.entry_id = entry.id
        db.flush()
    agent_id = account.dealer_user_id or takeover_holder_user_id(db, account)
    if agent_id is not None and not account.dealer_deleted:
        amount_text = _money_text(row.amount, _account_currency(db, account))
        if approve:
            inbox.create_notification(
                db,
                agent_id,
                kind=inbox.KIND_TRUCK_PAYMENT_REQUEST_APPROVED,
                title="Payment request approved",
                body=(
                    f"{_display_name(db, account, 'customer')} approved "
                    f"your payment request of {amount_text} and recorded "
                    "the payment on the truck account."
                ),
                data={"account_id": str(account.id)},
                commit=False,
            )
        else:
            inbox.create_notification(
                db,
                agent_id,
                kind=inbox.KIND_TRUCK_PAYMENT_REQUEST_DECLINED,
                title="Payment request declined",
                body=(
                    f"{_display_name(db, account, 'customer')} declined "
                    f"your payment request of {amount_text}."
                    + (
                        f" Their note: {row.decision_note}"
                        if row.decision_note
                        else ""
                    )
                ),
                data={"account_id": str(account.id)},
                commit=False,
            )
    db.commit()
    db.refresh(row)
    return row


def set_payment_mode(
    db: Session,
    customer: core_models.User,
    account: models.TruckAccount,
    *,
    payment_mode: str,
) -> models.TruckAccount:
    """The customer's pay-through-the-site choice on his own
    account: "automatic" or "manual". A stored preference only —
    it takes effect when payment processing connects (the
    Connect seam stays dark); flipping it moves no money and
    changes no schedule."""
    if role_of(account, customer.id) != "customer":
        raise TruckNotFound("That truck account doesn't exist.")
    if payment_mode not in models.PAYMENT_MODES:
        raise TruckError("Payment mode must be automatic or manual.")
    if account.status == "closed":
        raise TruckError("This account is closed.")
    account.payment_mode = payment_mode
    db.commit()
    db.refresh(account)
    return account


# -- creation: dealer opens an account ----------------------------------------------


def _default_due(cadence: str, from_date: date | None = None) -> date:
    start = from_date or date.today()
    return start + timedelta(days=_CADENCE_DAYS.get(cadence, 7))


def create_account(
    db: Session,
    dealer: core_models.User,
    *,
    customer_account_number: str = "",
    customer_email: str = "",
    payment_cadence: str = "weekly",
    payment_amount: Decimal | None = None,
    next_due_date: date | None = None,
    dealer_company_id: uuid.UUID | None = None,
    credit_limit: Decimal | None = None,
) -> models.TruckAccount:
    if payment_cadence not in models.CADENCES:
        raise TruckError("Payment cadence must be weekly or biweekly.")
    if credit_limit is not None and credit_limit < 0:
        raise TruckError("A credit limit can't be negative.")
    # The issuer is an AGENT acting under a company (2026-10-31):
    # the account is opened under one of the companies the agent
    # VERIFIED-represents — the only companies it can nest under.
    # Unstated + exactly one verified company defaults to it;
    # unstated + several asks for the pick; none at all refuses
    # with the way to fix it.
    reps = verified_representations(db, dealer.id)
    company = None
    if dealer_company_id is not None:
        for _rep, candidate in reps:
            if candidate.id == uuid.UUID(str(dealer_company_id)):
                company = candidate
                break
        if company is None:
            raise TruckError(
                "You can only open truck accounts under a company "
                "you're a verified agent for."
            )
    elif len(reps) == 1:
        company = reps[0][1]
    elif len(reps) > 1:
        raise TruckError(
            "Pick the company this account is under — you "
            "represent more than one."
        )
    else:
        raise TruckError(
            "Opening a truck account needs a verified company: "
            "claim your company in the dealer directory and have "
            "the representation verified first."
        )
    number = (customer_account_number or "").strip()
    email = (customer_email or "").strip().lower()
    if bool(number) == bool(email):
        raise TruckError(
            "Give the customer's account number OR their email — "
            "exactly one."
        )
    customer: core_models.User | None = None
    if number:
        # Exact account-number match (the peer-invite rule, via
        # core's own lookup): a wrong number is a plain refusal,
        # never a search and never an existence oracle.
        from app.modules.core import service as core_service

        customer = core_service.get_user_by_account_number(db, number)
        if customer is None:
            raise TruckError(
                "No account carries that number — check it and try "
                "again, or invite them by email instead."
            )
        if customer.id == dealer.id:
            raise TruckError("You can't open a truck account with yourself.")
    account = models.TruckAccount(
        dealer_user_id=dealer.id,
        dealer_company_id=company.id,
        dealer_company_name=company.name,
        agent_name_snapshot=_platform_agent_name(db, dealer.id) or dealer.name or "",
        credit_limit=credit_limit,
        customer_user_id=customer.id if customer else None,
        customer_email=(customer.email if customer else email),
        customer_name=(customer.name if customer else ""),
        status="invited",
        invite_token=secrets.token_urlsafe(32),
        payment_cadence=payment_cadence,
        payment_amount=payment_amount,
        next_due_date=next_due_date or _default_due(payment_cadence),
    )
    db.add(account)
    db.flush()
    if customer is not None:
        inbox.truck_invite_received(
            db,
            customer_id=customer.id,
            account_id=account.id,
            dealer_name=dealer.name or "Your dealer",
        )
    db.commit()
    db.refresh(account)
    return account


def attach_pending_invites(db: Session, user: core_models.User) -> int:
    """The pre-signup attach (peer-invite pattern): accounts
    invited to this user's email attach to their account. Email
    match is the claim — the invite was ADDRESSED to that
    mailbox, and signup verified control of it through the
    email/OAuth flow. Called lazily from the read routes (the
    peer-sharing posture: invites resolve when the user shows
    up, no signup-hook coupling). Returns how many attached."""
    rows = list(
        db.scalars(
            select(models.TruckAccount).where(
                models.TruckAccount.customer_user_id.is_(None),
                func.lower(models.TruckAccount.customer_email)
                == (user.email or "").lower(),
                models.TruckAccount.status == "invited",
            )
        )
    )
    for account in rows:
        account.customer_user_id = user.id
        account.customer_name = user.name or account.customer_name
        inbox.truck_invite_received(
            db,
            customer_id=user.id,
            account_id=account.id,
            dealer_name=_display_name(db, account, "dealer"),
        )
    if rows:
        db.commit()
    return len(rows)


# -- acceptance ---------------------------------------------------------------------


def accept_account(
    db: Session,
    customer: core_models.User,
    account: models.TruckAccount,
    *,
    agreement_version: str,
) -> models.TruckAccount:
    if role_of(account, customer.id) != "customer":
        raise TruckError("Only the invited customer can accept this account.")
    if account.status != "invited":
        raise TruckError("This account is no longer awaiting acceptance.")
    if agreement_version != agreement_mod.AGREEMENT_VERSION:
        raise TruckError(
            "The agreement was updated — review the current text "
            "and accept again."
        )
    text = agreement_mod.render_agreement(
        db,
        dealer_name=_display_name(db, account, "dealer"),
        cadence=account.payment_cadence,
        payment_amount=account.payment_amount,
        currency=_account_currency(db, account),
    )
    account.agreement_version = agreement_mod.AGREEMENT_VERSION
    account.agreement_text_snapshot = text
    account.agreement_accepted_at = datetime.now(timezone.utc)
    account.customer_name = customer.name or account.customer_name
    account.status = "active"
    if not account.dealer_deleted and account.dealer_user_id is not None:
        inbox.truck_account_accepted(
            db,
            dealer_id=account.dealer_user_id,
            account_id=account.id,
            customer_name=account.customer_name or "Your customer",
        )
    db.commit()
    db.refresh(account)
    return account


def decline_account(
    db: Session, customer: core_models.User, account: models.TruckAccount
) -> models.TruckAccount:
    if role_of(account, customer.id) != "customer":
        raise TruckError("Only the invited customer can decline this account.")
    if account.status != "invited":
        raise TruckError("This account is no longer awaiting acceptance.")
    account.status = "closed"
    if not account.dealer_deleted and account.dealer_user_id is not None:
        inbox.truck_account_declined(
            db,
            dealer_id=account.dealer_user_id,
            account_id=account.id,
            customer_name=account.customer_name or "The customer",
        )
    db.commit()
    db.refresh(account)
    return account


def close_account(
    db: Session, user: core_models.User, account: models.TruckAccount
) -> models.TruckAccount:
    role = effective_role(db, account, user.id)
    if role is None:
        raise TruckNotFound("That truck account doesn't exist.")
    if account.status == "closed":
        raise TruckError("This account is already closed.")
    account.status = "closed"
    other_id = (
        account.customer_user_id
        if role == "dealer"
        else (account.dealer_user_id or takeover_holder_user_id(db, account))
    )
    other_deleted = (
        account.customer_deleted if role == "dealer"
        else account.dealer_deleted
    )
    if other_id is not None and not other_deleted:
        inbox.truck_account_closed(
            db,
            account_id=account.id,
            notify_user_id=other_id,
            other_name=(
                _display_name(db, account, "customer") if role == "dealer"
                else _display_name(db, account, "dealer")
            ),
        )
    db.commit()
    db.refresh(account)
    return account


# -- entries --------------------------------------------------------------------------


def _advance_due_after_payment(account: models.TruckAccount, paid_on: date) -> None:
    """A payment advances the next due date ONE cadence cycle
    from the CURRENT due date — it settles the oldest
    outstanding cycle. Paying early therefore never shortens
    the runway (the new date is a full cycle past the old one),
    and paying LATE works the missed count down one payment at
    a time instead of silently forgiving the cycles in between
    (stage 2's missed-payment rule: a due date passed unpaid
    SHOWS as missed until a payment settles that cycle). The
    reminders job keys off this date, so a due date can only
    remind once — the date moves when paid. (Stage 2 narrowed
    the wave-2 rule, which jumped a late payment's due date
    past the payment date and erased the intervening missed
    cycles from the schedule's view; the balance always kept
    them, the schedule now does too.)"""
    step = timedelta(days=_CADENCE_DAYS.get(account.payment_cadence, 7))
    base = account.next_due_date or paid_on
    account.next_due_date = base + step


def is_maintainer(db: Session, account: models.TruckAccount, user_id) -> bool:
    """The customer keeps this ledger himself (stage 2 names the
    two shapes that have always meant it, plus the new one):
      - the account is CUSTOMER-KEPT (ledger_keeper "customer")
        — he opened it from his own seat and records every
        kind, even while a platform agent holds the other seat;
      - or NO platform agent holds the account at all (a
        private record does — unclaimed — or a self-opened tab
        has no agent): there is no dealer seat on the platform,
        the pre-stage-2 customer-maintained shape.
    A takeover-claimed record's agent IS a platform holder, so
    an agent-kept account under a claimed record is maintained
    by the agent, exactly as before."""
    if role_of(account, user_id) != "customer":
        return False
    if account.ledger_keeper == "customer":
        return True
    return (
        account.dealer_user_id is None
        and takeover_holder_user_id(db, account) is None
    )


def add_entry(
    db: Session,
    user: core_models.User,
    account: models.TruckAccount,
    *,
    kind: str,
    amount: Decimal,
    note: str = "",
    item_link_id: uuid.UUID | None = None,
    entry_date: date | None = None,
    source: str = "manual",
) -> models.TruckEntry:
    role = effective_role(db, account, user.id)
    if role is None:
        raise TruckNotFound("That truck account doesn't exist.")
    if account.status == "closed":
        raise TruckError(
            "This account is closed — its ledger is frozen."
        )
    if account.status != "active":
        raise TruckError(
            "The customer hasn't accepted the agreement yet — "
            "entries open once the account is active."
        )
    if kind not in models.ENTRY_KINDS:
        raise TruckError(f"Unknown entry kind: {kind}")
    amount = Decimal(amount)
    # While the CUSTOMER maintains the tab (is_maintainer — a
    # self-kept account, or no platform agent holding it) he
    # records every kind, charges included: they are his record
    # of what the off-platform agent — or the tab itself —
    # charged him. Once an agent holds the dealer seat of an
    # agent-kept account, charges are the dealer's pen again.
    holder_id = takeover_holder_user_id(db, account)
    maintainer = is_maintainer(db, account, user.id)
    if kind == "charge":
        if role != "dealer" and not maintainer:
            raise TruckError("Only the dealer records charges.")
        if role == "dealer" and account.ledger_keeper == "customer":
            # A customer-kept tab is the customer's books: the
            # agent's money path is a payment REQUEST (or
            # recording a payment he received) — charges are
            # the keeper's pen, so the ledger he keeps can
            # never grow behind his back.
            raise TruckError(
                "The customer keeps this account's ledger — record "
                "a payment you received, or request a payment "
                "instead of charging it."
            )
        if amount <= 0:
            raise TruckError("A charge must be a positive amount.")
        signed = amount
    elif kind == "payment":
        if amount <= 0:
            raise TruckError("A payment must be a positive amount.")
        signed = -amount
    else:  # adjustment — either party, signed as entered
        if amount == 0:
            raise TruckError("An adjustment of zero changes nothing.")
        signed = amount
    # Every increase is explained (owner, 2026-11-04): an entry
    # that RAISES the balance must say why — a tool charge is
    # explained by the tool it links to; anything else needs a
    # note. Applies to both seats and both keeper modes: an
    # unexplained increase is exactly what this ledger exists to
    # prevent. (The wizard's charge always carries its item
    # link, so it satisfies the rule by construction.)
    note = (note or "").strip()
    if signed > 0 and item_link_id is None and not note:
        raise TruckError(
            "An entry that raises the balance needs a note saying "
            "what it's for — every increase on the tab is explained."
        )
    entry = models.TruckEntry(
        account_id=account.id,
        # The working dealer: the platform holder, else the agent
        # who claimed the holding record (a plain column — the
        # journal reads it as-is, and it outlives either account).
        dealer_user_id=account.dealer_user_id or holder_id,
        kind=kind,
        amount=signed,
        note=note,
        item_link_id=item_link_id,
        entry_date=entry_date or date.today(),
        source=source,
        recorded_by=user.id,
    )
    db.add(entry)
    db.flush()
    if kind == "payment":
        _advance_due_after_payment(account, entry.entry_date)
    balance = balance_of(db, account.id)
    _raise_peak(account, balance)
    inbox.truck_entry_posted(
        db,
        account_id=account.id,
        kind=kind,
        amount_text=_money_text(abs(signed), _account_currency(db, account)),
        balance_text=_money_text(balance, _account_currency(db, account)),
        dealer_id=(
            (account.dealer_user_id or holder_id)
            if not account.dealer_deleted
            else None
        ),
        customer_id=(
            account.customer_user_id if not account.customer_deleted else None
        ),
        dealer_name=_display_name(db, account, "dealer"),
        customer_name=_display_name(db, account, "customer"),
        by_customer=(role == "customer"),
    )
    db.commit()
    db.refresh(entry)
    return entry


def update_schedule(
    db: Session,
    user: core_models.User,
    account: models.TruckAccount,
    *,
    payment_cadence: str | None = None,
    payment_amount: Decimal | None = None,
    next_due_date: date | None = None,
) -> models.TruckAccount:
    # The dealer sets the schedule — or the customer himself
    # while he maintains the tab (is_maintainer: a self-kept
    # account, or no platform agent holding it). A claimed
    # record's agent IS the dealer seat here.
    role = effective_role(db, account, user.id)
    if role != "dealer" and not is_maintainer(db, account, user.id):
        raise TruckError("Only the dealer sets the payment schedule.")
    if account.status == "closed":
        raise TruckError("This account is closed — its ledger is frozen.")
    if payment_cadence is not None:
        if payment_cadence not in models.CADENCES:
            raise TruckError("Payment cadence must be weekly or biweekly.")
        account.payment_cadence = payment_cadence
    if payment_amount is not None:
        account.payment_amount = payment_amount
    if next_due_date is not None:
        account.next_due_date = next_due_date
    db.commit()
    db.refresh(account)
    return account


# -- creation: the CUSTOMER opens a self-kept account (stage 2, 2026-11-05) --------
#
# The mechanic's seat (owner, 2026-11-04): the customer opens a
# truck account against ANY agent on his roster for a dealer —
# his own entered record, or a registered agent he is CONNECTED
# with — with an opening balance HE enters, and keeps the
# ledger himself. No agreement gate (the 2026-10-31 ruling: a
# self-opened tab is the user's own record of what he owes) and
# NO verified-representation requirement (that rule governs an
# agent issuing credit under a company, not a customer keeping
# his own books). The account is ACTIVE immediately,
# ledger_keeper "customer"; while the agent is a platform user
# (directly, or later via a takeover of the holding record) the
# same account is the shared tab both seats see.


def _open_account_for_holder(
    db: Session,
    customer_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None,
    private_agent_id: uuid.UUID | None,
) -> models.TruckAccount | None:
    """The customer's non-closed account under this company held
    by exactly this agent — the duplicate guard's read (one live
    tab per agent; a closed one never blocks a fresh start)."""
    rows = _customer_company_accounts(db, customer_id, company_id)
    for account in rows:
        if account.status == "closed":
            continue
        if (
            account.dealer_user_id == agent_user_id
            and account.private_agent_id == private_agent_id
        ):
            return account
    return None


def self_open_companies(db: Session, customer: core_models.User) -> list[dict]:
    """The companies the customer could open a self-kept account
    under: every company where he HAS a roster agent — a
    connection row (stage 1) or one of his own agent records.
    A company with no agent of his offers no one to owe."""
    from app.modules.dealers import models as dealer_models
    from app.modules.dealers import service as dealer_service

    company_ids: set[uuid.UUID] = set()
    for row in db.scalars(
        select(dealer_models.PreferredAgent.company_id).where(
            dealer_models.PreferredAgent.user_id == customer.id
        )
    ):
        if row is not None:
            company_ids.add(row)
    for row in db.scalars(
        select(dealer_models.PrivateAgent.company_id).where(
            dealer_models.PrivateAgent.owner_id == customer.id,
            dealer_models.PrivateAgent.archived.is_(False),
            dealer_models.PrivateAgent.company_id.is_not(None),
        )
    ):
        company_ids.add(row)
    companies = []
    for company_id in company_ids:
        company = db.get(dealer_models.DealerCompany, company_id)
        if company is not None:
            companies.append(
                {
                    "company_id": company.id,
                    # The customer's own name for the dealer
                    # (personal edits, 2026-11-05).
                    "company_name": dealer_service.personal_company_name(
                        db, customer.id, company
                    ),
                }
            )
    companies.sort(key=lambda c: c["company_name"].lower())
    return companies


def self_open_targets(
    db: Session, customer: core_models.User, company_id
) -> list[dict]:
    """The roster agents the customer can open a self-kept
    account with for one company: his own live records for it +
    the platform agents he is CONNECTED with for it (stage 1's
    roster rule — unconnected registered agents never appear),
    each flagged with the preferred mark and whether a live
    account with that agent already exists."""
    from app.modules.dealers import models as dealer_models

    company = _company_or_error(db, customer, company_id)
    targets: list[dict] = []
    records = list(
        db.scalars(
            select(dealer_models.PrivateAgent).where(
                dealer_models.PrivateAgent.owner_id == customer.id,
                dealer_models.PrivateAgent.company_id == company.id,
                dealer_models.PrivateAgent.archived.is_(False),
            )
        )
    )
    connections = list(
        db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == customer.id,
                dealer_models.PreferredAgent.company_id == company.id,
            )
        )
    )
    preferred_private = {
        row.private_agent_id for row in connections if row.is_preferred
    }
    preferred_platform = {
        row.agent_user_id for row in connections if row.is_preferred
    }
    for record in records:
        targets.append(
            {
                "kind": "private",
                "agent_user_id": None,
                "private_agent_id": record.id,
                "name": record.name,
                "is_preferred": record.id in preferred_private,
                "has_open_account": _open_account_for_holder(
                    db, customer.id, company.id,
                    agent_user_id=None, private_agent_id=record.id,
                )
                is not None,
            }
        )
    seen_platform: set[uuid.UUID] = set()
    for row in connections:
        if row.agent_user_id is None or row.agent_user_id in seen_platform:
            continue
        seen_platform.add(row.agent_user_id)
        targets.append(
            {
                "kind": "platform",
                "agent_user_id": row.agent_user_id,
                "private_agent_id": None,
                "name": _platform_agent_name(db, row.agent_user_id) or "Agent",
                "is_preferred": row.agent_user_id in preferred_platform,
                "has_open_account": _open_account_for_holder(
                    db, customer.id, company.id,
                    agent_user_id=row.agent_user_id, private_agent_id=None,
                )
                is not None,
            }
        )
    targets.sort(key=lambda o: (not o["is_preferred"], o["name"].lower()))
    return targets


def open_customer_account(
    db: Session,
    customer: core_models.User,
    *,
    company_id,
    private_agent_id: uuid.UUID | None = None,
    agent_user_id: uuid.UUID | None = None,
    opening_balance: Decimal = Decimal("0"),
    opening_note: str = "",
    payment_cadence: str = "weekly",
    payment_amount: Decimal | None = None,
    next_due_date: date | None = None,
    payment_mode: str = "manual",
) -> models.TruckAccount:
    """Open a SELF-KEPT truck account from the customer's seat
    (see the section header). The opening balance, when the
    customer enters one, is the account's first entry — a charge
    carrying his note, or the standing "Opening balance"
    explanation when he wrote none: the balance is never an
    unexplained number."""
    if payment_cadence not in models.CADENCES:
        raise TruckError("Payment cadence must be weekly or biweekly.")
    if payment_mode not in models.PAYMENT_MODES:
        raise TruckError("Payment mode must be automatic or manual.")
    if payment_amount is not None and payment_amount <= 0:
        raise TruckError("A payment amount must be more than zero.")
    opening_balance = Decimal(opening_balance)
    if opening_balance < 0:
        raise TruckError("An opening balance can't be negative.")
    if bool(private_agent_id) == bool(agent_user_id):
        raise TruckError("Pick the agent this account is with.")
    company = _company_or_error(db, customer, company_id)

    from app.modules.dealers import models as dealer_models

    holder_user_id: uuid.UUID | None = None
    holder_private_id: uuid.UUID | None = None
    holder_name = ""
    if private_agent_id is not None:
        record = db.get(
            dealer_models.PrivateAgent, uuid.UUID(str(private_agent_id))
        )
        if (
            record is None
            or record.owner_id != customer.id
            or record.archived
            or (
                record.company_id is not None
                and record.company_id != company.id
            )
        ):
            raise TruckError(
                "That agent record isn't one of yours for this dealer."
            )
        holder_private_id = record.id
        holder_name = record.name
    else:
        target_user_id = uuid.UUID(str(agent_user_id))
        if target_user_id == customer.id:
            raise TruckError("You can't open a truck account with yourself.")
        connected = db.scalar(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == customer.id,
                dealer_models.PreferredAgent.company_id == company.id,
                dealer_models.PreferredAgent.agent_user_id == target_user_id,
            )
        )
        if connected is None:
            raise TruckError(
                "That agent isn't on your roster for this dealer — "
                "connect with them first, then open the account."
            )
        holder_user_id = target_user_id
        holder_name = _platform_agent_name(db, target_user_id) or "Agent"

    existing = _open_account_for_holder(
        db, customer.id, company.id,
        agent_user_id=holder_user_id, private_agent_id=holder_private_id,
    )
    if existing is not None:
        raise TruckError(
            f"You already have a truck account with {holder_name} at "
            f"{company.name} — that one is your tab with them."
        )

    account = models.TruckAccount(
        dealer_user_id=holder_user_id,
        private_agent_id=holder_private_id,
        dealer_company_id=company.id,
        dealer_company_name=company.name,
        agent_name_snapshot=holder_name,
        credit_limit=None,
        customer_user_id=customer.id,
        customer_email=customer.email or "",
        customer_name=customer.name or "",
        status="active",
        invite_token=secrets.token_urlsafe(32),
        payment_cadence=payment_cadence,
        payment_amount=payment_amount,
        next_due_date=(
            next_due_date
            if next_due_date is not None
            else (_default_due(payment_cadence) if payment_amount else None)
        ),
        ledger_keeper="customer",
        payment_mode=payment_mode,
    )
    db.add(account)
    db.flush()
    if opening_balance > 0:
        entry = models.TruckEntry(
            account_id=account.id,
            dealer_user_id=account.dealer_user_id,
            kind="charge",
            amount=opening_balance,
            note=(opening_note or "").strip() or OPENING_BALANCE_NOTE,
            item_link_id=None,
            entry_date=date.today(),
            source="manual",
            recorded_by=customer.id,
        )
        db.add(entry)
        db.flush()
        # The opening balance is the account's first standing
        # balance — the peak starts there (owner's example:
        # open at $100 and the highest credit limit is $100).
        _raise_peak(account, balance_of(db, account.id))
        # The both-sides-notified rule rides along: a platform
        # agent holding the other seat hears about the opening
        # entry with the balance, like any charge.
        inbox.truck_entry_posted(
            db,
            account_id=account.id,
            kind="charge",
            amount_text=_money_text(
                opening_balance, _account_currency(db, account)
            ),
            balance_text=_money_text(
                balance_of(db, account.id), _account_currency(db, account)
            ),
            dealer_id=(
                account.dealer_user_id if not account.dealer_deleted else None
            ),
            customer_id=(
                account.customer_user_id
                if not account.customer_deleted
                else None
            ),
            dealer_name=_display_name(db, account, "dealer"),
            customer_name=_display_name(db, account, "customer"),
            by_customer=True,
        )
    db.commit()
    db.refresh(account)
    return account


# -- the wizard charge at item entry (2026-10-31) --------------------------------------
#
# Owner's model: entering a tool (or battery) in the Add wizard,
# the buyer may put any portion of the purchase price on his
# truck account with that dealer. An ACTIVE account with the
# dealer company takes the charge; with none, the wizard opens
# one on the spot — NO agreement step (the owner's ruling: a
# self-opened tab is the user's own record of what he owes; the
# agreement gate stays on dealer-issued accounts only). The
# charge NEVER commits here: the inventory create owns the
# transaction, so the item and the charge land together or not
# at all.


def _company_or_error(db: Session, customer: core_models.User, company_id):
    """The wizard may only work under a company the customer can
    tag an item with (the inventory rule): a directory company
    or his own private company."""
    from app.modules.dealers import models as dealer_models

    company = db.get(dealer_models.DealerCompany, uuid.UUID(str(company_id)))
    if company is None or not (
        company.is_directory or company.owner_id == customer.id
    ):
        raise TruckError("That dealer company isn't available to you.")
    return company


def _customer_company_accounts(
    db: Session, customer_id: uuid.UUID, company_id: uuid.UUID
) -> list[models.TruckAccount]:
    return list(
        db.scalars(
            select(models.TruckAccount).where(
                models.TruckAccount.customer_user_id == customer_id,
                models.TruckAccount.dealer_company_id == company_id,
                models.TruckAccount.customer_deleted.is_(False),
            )
        )
    )


def _agent_on_record(db: Session, customer_id: uuid.UUID, company_id):
    """(agent_user_id, private_agent_id) — the customer's agent
    on record for the company, the claims resolution (the
    display default: the earliest preferred-agent row), or
    None when he has none."""
    from app.modules.claims import service as claims_service

    return claims_service.agent_on_record(db, customer_id, company_id)


def _holder_name(
    db: Session, agent_user_id, private_agent_id
) -> str | None:
    """The display name of a would-be / new account holder."""
    if agent_user_id is not None:
        return _platform_agent_name(db, agent_user_id) or None
    if private_agent_id is not None:
        from app.modules.dealers import models as dealer_models

        record = db.get(dealer_models.PrivateAgent, private_agent_id)
        return record.name if record is not None else None
    return None


def _holder_accounts(
    db: Session,
    customer_id: uuid.UUID,
    company_id: uuid.UUID,
    pair: tuple | None = ...,
) -> tuple[tuple | None, list[models.TruckAccount]]:
    """The wizard's charge targets for one holder: WITH an agent
    (the display default, or the agent the customer PICKED in
    the wizard — multi-preferred, 2026-11-05), the targets are
    HIS active accounts under the company — the charge lands on
    that agent's tab, never on another agent's just because one
    exists, and when he holds none the caller opens one under
    him. With NO agent on record there is no per-agent
    distinction to protect: the targets are ALL the customer's
    active accounts under the company (the 2026-10-31 behavior
    — an agent-issued tab he accepted IS his tab with that
    dealer), and the self-open fallback is the holder-less
    company tab (both holder fields NULL — the no-agent fit).
    Returns (pair, accounts); pair is None exactly in the
    no-agent case. pair=... (the default) resolves the display
    default; an explicit pair is used as given."""
    rows = _customer_company_accounts(db, customer_id, company_id)
    active = [a for a in rows if a.status == "active"]
    if pair is ...:
        pair = _agent_on_record(db, customer_id, company_id)
    if pair is None:
        return None, active
    return pair, [
        a
        for a in active
        if a.dealer_user_id == pair[0] and a.private_agent_id == pair[1]
    ]


def _preferred_holder_accounts(
    db: Session, customer_id: uuid.UUID, company_id: uuid.UUID
) -> tuple[tuple | None, list[models.TruckAccount]]:
    """_holder_accounts at the display default (kept as the
    named seam other readers already use)."""
    return _holder_accounts(db, customer_id, company_id)


def wizard_context(
    db: Session, customer: core_models.User, company_id
) -> dict:
    """What the Add wizard needs to ask the truck question for
    one dealer company: the customer's ACTIVE accounts with his
    DISPLAY-DEFAULT agent for it (the charge targets — an
    account with a different agent is never a target), whether
    an unaccepted invite is also waiting (surfaced in the wizard
    copy, never a block), and — when that agent has no active
    account — the agent a self-opened tab would land under, so
    the wizard can say whose tab it starts.

    Multi-preferred (2026-11-05): `agents` carries EVERY agent
    on the customer's roster for the company (the claims
    picker's universe — his connection rows, roster order),
    each with his own active accounts, so the wizard can offer
    a pick when he has more than one: the charge then targets
    the CHOSEN agent and a self-opened tab lands under him.
    The top-level fields stay the display default's view, so a
    one-agent customer sees exactly what he always saw. With
    no agent on record at all, `agents` is empty and the
    top-level accounts are every active account under the
    company (the no-agent behavior)."""
    from app.modules.claims import service as claims_service

    company = _company_or_error(db, customer, company_id)
    attach_pending_invites(db, customer)
    rows = _customer_company_accounts(db, customer.id, company.id)
    pair, active = _preferred_holder_accounts(db, customer.id, company.id)
    new_agent_name = None
    if not active and pair is not None:
        new_agent_name = _holder_name(db, pair[0], pair[1])
    agents = []
    for agent_pair in claims_service.preferred_agents_for(
        db, customer.id, company.id
    ):
        _p, agent_active = _holder_accounts(
            db, customer.id, company.id, agent_pair
        )
        agents.append(
            {
                "agent_user_id": agent_pair[0],
                "private_agent_id": agent_pair[1],
                "name": _holder_name(db, agent_pair[0], agent_pair[1]) or "",
                "is_preferred": _pair_is_preferred(
                    db, customer.id, company.id, agent_pair
                ),
                "is_default": pair is not None and agent_pair == pair,
                "active_accounts": [
                    {
                        "id": a.id,
                        "agent_name": agent_display_name(db, a),
                        "balance": balance_of(db, a.id),
                    }
                    for a in agent_active
                ],
            }
        )
    return {
        "company_id": company.id,
        "company_name": company.name,
        "active_accounts": [
            {
                "id": a.id,
                "agent_name": agent_display_name(db, a),
                "balance": balance_of(db, a.id),
            }
            for a in active
        ],
        "invited_exists": any(a.status == "invited" for a in rows),
        "new_account_agent_name": new_agent_name,
        "agents": agents,
    }


def _pair_is_preferred(
    db: Session,
    customer_id: uuid.UUID,
    company_id: uuid.UUID,
    pair: tuple,
) -> bool:
    """Whether this roster pair's connection row carries the
    preferred flag (multi-preferred: any number may)."""
    from app.modules.dealers import models as dealer_models

    row = db.scalars(
        select(dealer_models.PreferredAgent).where(
            dealer_models.PreferredAgent.user_id == customer_id,
            dealer_models.PreferredAgent.company_id == company_id,
            dealer_models.PreferredAgent.agent_user_id == pair[0],
            dealer_models.PreferredAgent.private_agent_id == pair[1],
        )
    ).first()
    return bool(row is not None and row.is_preferred)


def open_self_tab(
    db: Session, customer: core_models.User, company, pair: tuple | None = ...
) -> models.TruckAccount:
    """Open a truck account BY the customer, for the customer —
    active immediately, no agreement (the owner's ruling). The
    holder is the customer's agent on record for the company:
    the platform agent when the record names one, his private
    agent record when it names that, and — with no agent of any
    kind on record — NO holder at all: the account stays
    company-linked and customer-maintained (dealer_user_id and
    private_agent_id both NULL; the customer is the only seat,
    which the maintainer rules already read as his tab to keep).
    Stage 2: the tab is CUSTOMER-KEPT (ledger_keeper) — he
    opened it, he keeps its books, whichever agent holds the
    other seat. An explicit pair (the wizard's chosen agent,
    multi-preferred) lands the tab under THAT agent instead of
    the display default. Flush only — the caller owns the
    commit."""
    if pair is ...:
        pair = _agent_on_record(db, customer.id, company.id)
    agent_user_id = pair[0] if pair else None
    private_agent_id = pair[1] if pair else None
    account = models.TruckAccount(
        dealer_user_id=agent_user_id,
        private_agent_id=private_agent_id,
        dealer_company_id=company.id,
        dealer_company_name=company.name,
        agent_name_snapshot=(
            _holder_name(db, agent_user_id, private_agent_id) or ""
        ),
        customer_user_id=customer.id,
        customer_email=customer.email or "",
        customer_name=customer.name or "",
        status="active",
        invite_token=secrets.token_urlsafe(32),
        payment_cadence="weekly",
        payment_amount=None,
        next_due_date=None,
        credit_limit=None,
        ledger_keeper="customer",
    )
    db.add(account)
    db.flush()
    return account


def charge_at_item_entry(
    db: Session,
    customer: core_models.User,
    *,
    company_id,
    amount: Decimal,
    note: str,
    item_link_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
) -> models.TruckEntry:
    """Post the wizard's charge for a just-entered item: onto
    the ACTIVE account the customer's agent for the item's
    dealer holds — the DISPLAY-DEFAULT preferred agent, or the
    agent the customer picked in the wizard (multi-preferred;
    stage 2 re-aim — an account with a DIFFERENT agent is
    never charged by the wizard; it isn't the tab this purchase
    belongs to), or onto a self-opened tab under that agent
    when he has none — the tool's
    charge is the new tab's first entry. With no agent on record
    at all, the targets are all his active accounts under the
    company (the 2026-10-31 behavior — an accepted agent-issued
    tab IS his tab with that dealer), and only when he has none
    does the self-open create the holder-less company tab (the
    no-agent fit, kept as the last resort). A charge records
    even past a set credit line — it is the record of a real
    purchase, never a block. Flush only — the caller's
    transaction commits item + charge together, and the standard
    entry notification folds into that same commit (a
    platform-agent holder gets the usual notice; a customer-held
    tab notifies nobody external)."""
    company = _company_or_error(db, customer, company_id)
    amount = Decimal(amount)
    if amount <= 0:
        raise TruckError("The truck account amount must be more than zero.")
    # The wizard's agent pick (multi-preferred): an explicit
    # agent re-aims the charge at THAT agent's tab (validated
    # against the customer's roster for the company — the same
    # universe the claim picker offers); no pick = the display
    # default's tab, exactly as before.
    chosen_pair: tuple | None = ...
    if agent_user_id is not None or private_agent_id is not None:
        from app.modules.claims import service as claims_service

        chosen_pair = (
            uuid.UUID(str(agent_user_id)) if agent_user_id else None,
            uuid.UUID(str(private_agent_id)) if private_agent_id else None,
        )
        if chosen_pair not in claims_service.preferred_agents_for(
            db, customer.id, company.id
        ):
            raise TruckError(
                "That agent isn't one of your agents for this dealer."
            )
    _pair, active = _holder_accounts(db, customer.id, company.id, chosen_pair)
    target: models.TruckAccount | None = None
    if account_id is not None:
        target = next(
            (a for a in active if a.id == uuid.UUID(str(account_id))), None
        )
        if target is None:
            raise TruckError(
                "That truck account isn't one of your active "
                "accounts for this charge with this dealer."
            )
    elif len(active) == 1:
        target = active[0]
    elif len(active) > 1:
        raise TruckError(
            "You have more than one active truck account this "
            "charge could land on — pick which one it goes on."
        )
    else:
        target = open_self_tab(db, customer, company, chosen_pair)
    entry = models.TruckEntry(
        account_id=target.id,
        dealer_user_id=target.dealer_user_id,
        kind="charge",
        amount=amount,
        note=(note or "").strip(),
        item_link_id=item_link_id,
        entry_date=date.today(),
        source="manual",
        recorded_by=customer.id,
    )
    db.add(entry)
    db.flush()
    balance = balance_of(db, target.id)
    _raise_peak(target, balance)
    inbox.truck_entry_posted(
        db,
        account_id=target.id,
        kind="charge",
        amount_text=_money_text(amount, _account_currency(db, target)),
        balance_text=_money_text(balance, _account_currency(db, target)),
        dealer_id=(
            target.dealer_user_id if not target.dealer_deleted else None
        ),
        customer_id=(
            target.customer_user_id if not target.customer_deleted else None
        ),
        dealer_name=_display_name(db, target, "dealer"),
        customer_name=_display_name(db, target, "customer"),
        by_customer=True,
    )
    return entry


# -- reminders job ----------------------------------------------------------------------


def run_due_reminders(db: Session, *, today: date | None = None) -> dict:
    """The scheduler job's work: for every ACTIVE account with a
    balance owed and a payment schedule —
      - due within DUE_SOON_DAYS (and not past): the CUSTOMER
        gets a due-soon note;
      - past due: the CUSTOMER gets an overdue note and the
        DEALER gets an overdue note for the account.
    Idempotent per due date: the job stamps a system setting with
    the last (account, due date) pairs it reminded, so a second
    run on the same due date sends nothing twice — and when a
    payment lands the due date advances, arming the next cycle.
    """
    from app.modules.billing import entitlements

    today = today or date.today()
    marker_key = "truck_accounts.reminded"
    reminded = set(entitlements.get_setting(db, marker_key, []) or [])
    sent = {"due_soon": 0, "overdue_customer": 0, "overdue_dealer": 0}
    accounts = list(
        db.scalars(
            select(models.TruckAccount).where(
                models.TruckAccount.status == "active",
                models.TruckAccount.next_due_date.is_not(None),
                models.TruckAccount.payment_amount.is_not(None),
            )
        )
    )
    for account in accounts:
        if balance_of(db, account.id) <= 0:
            continue
        due = account.next_due_date
        stamp = f"{account.id}:{due.isoformat()}"
        amount_text = _money_text(
            account.payment_amount, _account_currency(db, account)
        )
        balance_text = _money_text(
            balance_of(db, account.id), _account_currency(db, account)
        )
        if due < today:
            if f"overdue:{stamp}" in reminded:
                continue
            if account.customer_user_id and not account.customer_deleted:
                inbox.truck_payment_overdue(
                    db,
                    user_id=account.customer_user_id,
                    account_id=account.id,
                    other_name=_display_name(db, account, "dealer"),
                    amount_text=amount_text,
                    balance_text=balance_text,
                    audience="customer",
                )
                sent["overdue_customer"] += 1
            if not account.dealer_deleted and account.dealer_user_id is not None:
                inbox.truck_payment_overdue(
                    db,
                    user_id=account.dealer_user_id,
                    account_id=account.id,
                    other_name=_display_name(db, account, "customer"),
                    amount_text=amount_text,
                    balance_text=balance_text,
                    audience="dealer",
                )
                sent["overdue_dealer"] += 1
            reminded.add(f"overdue:{stamp}")
        elif due <= today + timedelta(days=DUE_SOON_DAYS):
            if f"due:{stamp}" in reminded:
                continue
            if account.customer_user_id and not account.customer_deleted:
                inbox.truck_payment_due(
                    db,
                    customer_id=account.customer_user_id,
                    account_id=account.id,
                    dealer_name=_display_name(db, account, "dealer"),
                    amount_text=amount_text,
                    due_text=(
                        "today" if due == today
                        else f"on {due.strftime('%b %d')}"
                    ),
                )
                sent["due_soon"] += 1
            reminded.add(f"due:{stamp}")
    # Prune stamps for due dates more than a month past — the
    # marker must not grow forever (a stamp's date is its suffix).
    cutoff = (today - timedelta(days=31)).isoformat()
    reminded = {
        s for s in reminded if s.rsplit(":", 1)[-1] >= cutoff
    }
    entitlements.set_setting(db, marker_key, sorted(reminded))
    db.commit()
    return sent


# -- dashboard + export -------------------------------------------------------------------


def dealer_dashboard(db: Session, dealer_id: uuid.UUID) -> dict:
    """The dealer dashboard's Truck Accounts + Payments sections
    (one summary feeds both): open accounts + total outstanding,
    and the week's payment picture — due within 7 days and the
    overdue list."""
    today = date.today()
    week_end = today + timedelta(days=7)
    accounts = [
        a
        for a in accounts_for_user(db, dealer_id)
        if a.dealer_user_id == dealer_id and not a.dealer_deleted
    ]
    open_accounts = [
        a for a in accounts if a.status in ("invited", "active")
    ]
    total_outstanding = Decimal("0")
    due_this_week: list[dict] = []
    overdue: list[dict] = []
    for account in accounts:
        if account.status != "active":
            continue
        balance = balance_of(db, account.id)
        if balance > 0:
            total_outstanding += balance
        if account.next_due_date is None or balance <= 0:
            continue
        row = {
            "account_id": str(account.id),
            "customer_name": _display_name(db, account, "customer"),
            "amount": (
                str(account.payment_amount)
                if account.payment_amount is not None
                else None
            ),
            "balance": str(balance),
            "next_due_date": account.next_due_date.isoformat(),
        }
        if account.next_due_date < today:
            overdue.append(row)
        elif account.next_due_date <= week_end:
            due_this_week.append(row)
    return {
        "open_accounts": len(open_accounts),
        "total_outstanding": total_outstanding,
        "due_this_week": due_this_week,
        "overdue": overdue,
    }


def status_summary(db: Session, user_id: uuid.UUID) -> dict:
    """The dealers page header's truck facts (2026-10-31; the
    facts-row shape is 2026-11-10): the viewer's truck-account
    picture — open accounts + total balance on EACH side of the
    tab, the payments recorded in the current calendar week
    across those open accounts, and the next route visits of
    the agents in the viewer's world: their preferred platform
    agents (from the agents' own route schedules) and the
    viewer's own route when they run one."""
    accounts = accounts_for_user(db, user_id)
    as_customer = [
        a
        for a in accounts
        if a.customer_user_id == user_id and a.status != "closed"
    ]
    as_dealer = [
        a
        for a in accounts
        if a.dealer_user_id == user_id and a.status != "closed"
    ]
    # This week's payments (2026-11-10): payment entries dated
    # in the current MONDAY-START calendar week, on the entry's
    # recorded date, across the viewer's OPEN accounts on both
    # sides (the module has no calendar-week bucket elsewhere —
    # its due windows are rolling 7-day lookaheads — so the
    # calendar week is defined here). Payments are stored
    # NEGATIVE in the signed ledger, so the week's total is the
    # negated sum: the money that moved, stated positive.
    # Charges and adjustments never count.
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    open_ids = {a.id for a in as_customer} | {a.id for a in as_dealer}
    payments_this_week = Decimal("0")
    if open_ids:
        week_sum = db.scalar(
            select(
                func.coalesce(func.sum(models.TruckEntry.amount), 0)
            ).where(
                models.TruckEntry.account_id.in_(open_ids),
                models.TruckEntry.kind == "payment",
                models.TruckEntry.entry_date >= week_start,
                models.TruckEntry.entry_date <= week_end,
            )
        )
        payments_this_week = -Decimal(week_sum or 0)
    route_visits: list[dict] = []
    from app.modules.dealers import models as dealer_models
    from app.modules.dealers import route_days
    from app.modules.dealers import service as dealer_service

    prefs = list(
        db.scalars(
            select(dealer_models.PreferredAgent).where(
                dealer_models.PreferredAgent.user_id == user_id,
                dealer_models.PreferredAgent.agent_user_id.is_not(None),
                dealer_models.PreferredAgent.agent_user_id != user_id,
            )
        )
    )
    seen_agents: set = set()
    for pref in prefs:
        if pref.agent_user_id in seen_agents:
            continue
        seen_agents.add(pref.agent_user_id)
        profile = _agent_profile(db, pref.agent_user_id)
        if profile is None:
            continue
        nxt = route_days.route_next_visit_for(profile)
        if nxt is None:
            continue
        company = db.get(dealer_models.DealerCompany, pref.company_id)
        route_visits.append(
            {
                "agent_name": (
                    profile.display_name
                    or _platform_agent_name(db, pref.agent_user_id)
                    or "Your agent"
                ),
                # The viewer's own name for the agent's company
                # (personal edits, 2026-11-05).
                "company_name": (
                    dealer_service.personal_company_name(db, user_id, company)
                    if company is not None
                    else ""
                ),
                "next_visit": nxt,
                "frequency": profile.route_frequency,
            }
        )
    own_profile = _agent_profile(db, user_id)
    if own_profile is not None:
        nxt = route_days.route_next_visit_for(own_profile)
        if nxt is not None:
            own_company = ""
            reps = verified_representations(db, user_id)
            if reps:
                own_company = reps[0][1].name
            route_visits.append(
                {
                    "agent_name": "You",
                    "company_name": own_company,
                    "next_visit": nxt,
                    "frequency": own_profile.route_frequency,
                }
            )
    route_visits.sort(key=lambda v: v["next_visit"])
    return {
        "customer_open_accounts": len(as_customer),
        "customer_total_balance": sum(
            (balance_of(db, a.id) for a in as_customer), Decimal("0")
        ),
        "dealer_open_accounts": len(as_dealer),
        "dealer_total_outstanding": sum(
            (balance_of(db, a.id) for a in as_dealer), Decimal("0")
        ),
        "payments_this_week": payments_this_week,
        "route_visits": route_visits[:5],
    }


def export_rows(db: Session, user_id: uuid.UUID) -> list[dict]:
    """The data export's truck_accounts.json — ROLE-SHAPED: a
    customer sees their accounts as a customer; a dealer sees
    theirs as the dealer; the entries ride along whole either
    way (the ledger is both parties' record)."""
    out = []
    for account in accounts_for_user(db, user_id):
        role = effective_role(db, account, user_id)
        schedule = schedule_status(db, account)
        out.append(
            {
                "id": str(account.id),
                "my_role": role,
                "dealer_name": _display_name(db, account, "dealer"),
                # His name for the dealer only in HIS customer
                # seat (personal edits, 2026-11-05); the dealer
                # seat of the same export keeps the directory name.
                "dealer_company_name": company_display_name(
                    db, account, user_id if role == "customer" else None
                ),
                "agent_name": agent_display_name(db, account),
                "agent_kind": agent_kind(account),
                "credit_limit": (
                    str(account.credit_limit)
                    if account.credit_limit is not None
                    else None
                ),
                "transfers": [
                    {
                        "from_agent_name": row.from_agent_name,
                        "to_agent_name": row.to_agent_name,
                        "created_at": (
                            row.created_at.isoformat() if row.created_at else None
                        ),
                    }
                    for row in list_transfers(db, account)
                ],
                "customer_name": _display_name(db, account, "customer"),
                "customer_email": (
                    account.customer_email if role == "dealer" else None
                ),
                "status": account.status,
                "payment_cadence": account.payment_cadence,
                "payment_amount": (
                    str(account.payment_amount)
                    if account.payment_amount is not None
                    else None
                ),
                "next_due_date": (
                    account.next_due_date.isoformat()
                    if account.next_due_date
                    else None
                ),
                "balance": str(balance_of(db, account.id)),
                "highest_balance": str(
                    account.highest_balance or Decimal("0")
                ),
                # Stage 2 facts ride along: who keeps the
                # ledger, the stored payment choice, and the
                # computed schedule state — the Reports statement
                # reads them off this same export shape.
                "ledger_keeper": account.ledger_keeper,
                "payment_mode": account.payment_mode,
                "schedule": {
                    "missed_payments": schedule["missed_payments"],
                    "amount_past_due": str(schedule["amount_past_due"]),
                },
                "agreement_version": account.agreement_version,
                "agreement_accepted_at": (
                    account.agreement_accepted_at.isoformat()
                    if account.agreement_accepted_at
                    else None
                ),
                "agreement_text_snapshot": account.agreement_text_snapshot,
                "entries": [
                    {
                        "id": str(e.id),
                        "kind": e.kind,
                        "amount": str(e.amount),
                        "note": e.note,
                        "item_link_id": (
                            str(e.item_link_id) if e.item_link_id else None
                        ),
                        "item_name": _entry_item(db, e)[0],
                        "entry_date": e.entry_date.isoformat(),
                        "source": e.source,
                        "created_at": (
                            e.created_at.isoformat() if e.created_at else None
                        ),
                    }
                    for e in list_entries(db, account)
                ],
                "created_at": (
                    account.created_at.isoformat() if account.created_at else None
                ),
            }
        )
    return out


# The auto-notes the add-item wizard writes on a truck charge
# ("Tool entered: {name}" / "Battery entered: {name}" —
# inventory._apply_truck_charge). On the account page the note
# is the entry's explanation and stays; in a REPORT's name cell
# it is a mere echo of the item name and never prints.
_WIZARD_NOTE_PREFIXES = ("Tool entered: ", "Battery entered: ")


def report_entry_name(item_name: str | None, note: str | None) -> str:
    """A truck ledger row's NAME for the printed reports (the
    name rule, Ryan 2026-11-06): the clean name ONLY — the
    linked item's name when the entry names one; otherwise the
    entry's own note, which is the name the keeper gave the
    entry (an opening balance, a cash payment), with the
    wizard's auto-note prefix folded away should one ever ride
    an unlinked entry. No running-balance annotation and no
    source explanation ride the name — the running balance is
    the ledger table's own BALANCE column now."""
    if item_name:
        return item_name
    text = (note or "").strip()
    for prefix in _WIZARD_NOTE_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


# -- the per-account statement (stage 2, 2026-11-05) ---------------------------------


def _statement_parties(
    db: Session, account: models.TruckAccount, viewer: core_models.User
) -> dict:
    """The statement header's DEALER / AGENT blocks (owner
    markup, 2026-11-06): the company as the viewer sees it
    (personal layer included) with the company's own phone —
    the customer-service pick the directory shows — and the
    agent of record with HIS public contact facts: a private
    record's own phone/email, or a platform agent's profile
    phone/contact email (the account's private email/phone
    never stand in for an agent's public ones). A fact that
    doesn't exist is simply absent — the frame omits its
    label rather than printing it empty."""
    from app.modules.dealers import models as dealer_models
    from app.modules.dealers import service as dealer_service

    company_name = company_display_name(db, account, viewer.id) or "Dealer"
    company_phone = ""
    if account.dealer_company_id is not None:
        company = db.get(dealer_models.DealerCompany, account.dealer_company_id)
        if company is not None:
            view = dealer_service.serialize_company_for_viewer(
                db, company, viewer.id
            )
            company_name = view.get("name") or company_name
            company_phone = view.get("customer_service_phone") or ""
    agent_name = agent_display_name(db, account)
    agent_phone = ""
    agent_email = ""
    record = _private_agent(db, account)
    if record is not None:
        agent_phone = record.phone or ""
        agent_email = record.email or ""
    elif account.dealer_user_id is not None and not account.dealer_deleted:
        profile = _agent_profile(db, account.dealer_user_id)
        if profile is not None:
            agent_phone = profile.phone or ""
            agent_email = profile.contact_email or ""
    return {
        "dealer": {"name": company_name, "phone": company_phone},
        "agent": {
            "name": agent_name,
            "phone": agent_phone,
            "email": agent_email,
        },
    }


def statement_report(
    db: Session, account: models.TruckAccount, viewer: core_models.User
) -> dict:
    """ONE account's statement in the activity-report shape the
    Reports renderers consume (reports.activity.render_activity)
    — the truck module builds the dataset, the site's document
    machinery renders the PDF/CSV, so a downloaded statement can
    never disagree with the ledger it came from. Rows ride in
    LEDGER ORDER (date, then recorded order — a statement is a
    running account, not a sort), each carrying its running
    balance in its own "balance" field — the ledger table's
    BALANCE column, the same after-each-entry balance the
    account page shows (Ryan, 2026-11-06) — and a NAME that is
    the clean name only (report_entry_name). The section dict
    is built by hand rather than via activity._section for that
    reason: _section re-sorts rows alphabetically within a
    date, which would scramble a same-day charge/payment pair."""
    from app.modules.core import money as core_money

    currency = _account_currency(db, account)
    # The statement is generated FOR the viewer — it carries the
    # company name as he sees it (personal edits, 2026-11-05),
    # matching his account page.
    company_name = company_display_name(db, account, viewer.id) or "Dealer"
    agent_name = agent_display_name(db, account)
    entries = list_entries(db, account)
    rows = []
    running = Decimal("0")
    total_charges = Decimal("0")
    total_payments = Decimal("0")
    for entry in entries:
        running += entry.amount
        if entry.kind == "charge":
            total_charges += entry.amount
        elif entry.kind == "payment":
            total_payments += -entry.amount
        item_name, _kind = _entry_item(db, entry)
        rows.append(
            {
                "date": entry.entry_date.isoformat(),
                "item": entry.kind.capitalize(),
                # The NAME cell (name rule, Ryan 2026-11-06):
                # the clean name only — the composition that
                # used to ride here (item name · the entry's
                # note · "requested by agent…" · "balance $X")
                # is gone; the balance is the row's own column.
                "detail": report_entry_name(item_name, entry.note),
                "amount": str(entry.amount),
                "balance": str(running),
            }
        )
    balance = balance_of(db, account.id)
    return {
        "kind": "truck_statement",
        # Owner markup (2026-11-06): the title is the document's
        # alone — no dealer suffix (the header box names the
        # dealer and the agent now) — and the account summary
        # line under the box is gone: its facts (company, agent,
        # customer) are the header box's, and the schedule /
        # missed-payment state lives on the account page. The
        # subtitle slot stays, empty, and the renderer skips an
        # empty subtitle.
        "title": "Truck account statement",
        "subtitle": "",
        "currency": core_money.normalize_currency(currency),
        "prepared_for": {
            "name": viewer.name or "",
            "email": viewer.email or "",
            "phone": viewer.phone or "",
            "address": viewer.postal_address or "",
        },
        "parties": _statement_parties(db, account, viewer),
        # The truck-ledger presentation (owner markup,
        # 2026-11-06): navy totals band, the ledger table's
        # DATE/TYPE/NAME/AMOUNT/BALANCE header row in place of
        # the dealer—agent section band (the section footer
        # keeps the label's total line) — the website's own
        # ledger shape, running balance included (Ryan,
        # 2026-11-06 22:34). The balance owed parks at the
        # band's right end in bold white (report standard,
        # 2026-11-06: red on navy was tried at the owner's
        # direction and rejected by him as unreadable).
        "totals_band": "navy",
        "ledger_table": True,
        "section_band": False,
        "sections": [
            {
                "key": f"account-{account.id}",
                "label": f"{company_name} — {agent_name}",
                "rows": rows,
                "total": str(balance),
                "count": len(rows),
            }
        ],
        "totals": [
            {"label": "Total charges", "amount": str(total_charges)},
            {"label": "Total payments", "amount": str(total_payments)},
            {
                "label": "Balance owed",
                "amount": str(balance),
                "park": "right",
            },
        ],
    }
