"""Shop crew service (core, wave 3, 2026-10-20).

A shop_company-group account (the shop OWNER) invites people into
its crew: by email (pre-signup invites attach when the invitee
shows up, the peer/truck pattern — the response never reveals
whether an address has an account) or by exact account number.
The invitee accepts or declines from their invite inbox; either
side can end an active membership.

THE 30-DAY RULE (owner brief): leaving starts a grace clock on
the membership row (left_at). The departed member is notified at
the leave, at day 25 ("5 days left") and at expiry, driven by
run_grace_notifications (the scheduler's crew job, idempotent via
the row's grace_notices ledger). What the clock protects: a
member whose coverage came from the shop's plan simply resolves
to plain Free afterwards — the entitlement resolver already
computes that naturally, so this service owns ONLY the clock and
the notices. A member who rejoins any shop's crew, or holds
their own paid plan, is "settled" and hears nothing more.

BRACKET TRUTH: crew_summary reads the owner's subscription's
STORED bracket_key (self-declared at checkout) and reports the
active headcount against it with a friendly mismatch note. No
payment enforcement lives here — the bracket stays the owner's
declaration.

DATA GATE: membership alone exposes ZERO inventory. What a crew
member sees of the shop's items is decided solely by tier
sharing (the owner sharing toward the shop_company group through
core.sharing) — pinned by test in test_wave3_crew.py.

THE OTHER DIRECTION (claims-ownership lane, 2026-11-07): the
shop's read-only view of a MEMBER's list (member_tools) rides
the same gate from the other side — the member's own
shop_company-group sharing decides items and fields, membership
only names whose list the shop may ask about. Read-only: no
write path exists on that surface.
"""

import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.core import inbox, models

SHOP_GROUP = "shop_company"
GRACE_DAYS = 30
GRACE_WARNING_DAY = 25


class CrewError(ValueError):
    """A refusal with a user-facing reason (routes answer 422)."""


class CrewNotFound(CrewError):
    """The membership doesn't exist — or isn't the caller's."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _token() -> str:
    return secrets.token_urlsafe(32)


def _require_shop_owner(user: models.User) -> None:
    if SHOP_GROUP not in (user.account_types or []):
        raise CrewError(
            "Crew is a shop feature — your account doesn't include "
            "the Shop / Company group."
        )


def _user(db: Session, user_id: uuid.UUID | None) -> models.User | None:
    if user_id is None:
        return None
    return db.get(models.User, user_id)


def _display(db: Session, user_id: uuid.UUID | None, fallback: str = "") -> str:
    user = _user(db, user_id)
    if user is None:
        return fallback
    return user.name or user.email or fallback


# -- invites --------------------------------------------------------------------


def attach_pending_invites(db: Session, user: models.User) -> int:
    """The pre-signup attach (peer-invite pattern): email invites
    addressed to the user's mailbox claim onto their account the
    first time they look. Email match is the claim — the invite
    was ADDRESSED to that mailbox. Called lazily from the read
    routes; returns how many attached."""
    rows = list(
        db.scalars(
            select(models.ShopMembership).where(
                models.ShopMembership.employee_user_id.is_(None),
                func.lower(models.ShopMembership.invite_email)
                == (user.email or "").lower(),
                models.ShopMembership.status == "invited",
            )
        )
    )
    for row in rows:
        row.employee_user_id = user.id
        inbox.create_notification(
            db,
            user.id,
            kind=inbox.KIND_CREW_INVITE,
            title="You're invited to join a shop crew",
            body=(
                f"{_display(db, row.shop_user_id, 'A shop')} invited you to "
                f"join their crew"
                + (f" as {row.role_label}" if row.role_label else "")
                + ". Accept or decline it in Settings → My shop."
            ),
            data={"membership_id": str(row.id)},
            commit=False,
        )
    if rows:
        db.commit()
    return len(rows)


def _existing_open(
    db: Session, shop_user_id: uuid.UUID, *, email: str = "", employee_id=None
) -> models.ShopMembership | None:
    """An invited/active membership for this person at this shop."""
    stmt = select(models.ShopMembership).where(
        models.ShopMembership.shop_user_id == shop_user_id,
        models.ShopMembership.status.in_(("invited", "active")),
    )
    if employee_id is not None:
        stmt = stmt.where(models.ShopMembership.employee_user_id == employee_id)
    elif email:
        stmt = stmt.where(
            func.lower(models.ShopMembership.invite_email) == email.lower()
        )
    else:
        return None
    return db.scalars(stmt).first()


def invite_by_email(
    db: Session, shop: models.User, email: str, role_label: str = ""
) -> models.ShopMembership:
    """Invite by email. No existence oracle: the response is the
    same whether or not the address already has an account (the
    row attaches now or at signup)."""
    _require_shop_owner(shop)
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise CrewError("Enter the email address to invite.")
    if email == (shop.email or "").lower():
        raise CrewError("You're the shop owner — you don't need an invite.")
    existing = _existing_open(db, shop.id, email=email)
    if existing is not None:
        if existing.status == "active":
            raise CrewError("That person is already in your crew.")
        return existing  # a pending invite stands (idempotent re-invite)
    account = db.scalar(
        select(models.User).where(func.lower(models.User.email) == email)
    )
    row = models.ShopMembership(
        shop_user_id=shop.id,
        employee_user_id=account.id if account else None,
        invite_email=email,
        invite_token=_token(),
        role_label=(role_label or "").strip(),
        status="invited",
    )
    db.add(row)
    db.flush()
    if account is not None:
        inbox.create_notification(
            db,
            account.id,
            kind=inbox.KIND_CREW_INVITE,
            title="You're invited to join a shop crew",
            body=(
                f"{shop.name or 'A shop'} invited you to join their crew"
                + (f" as {row.role_label}" if row.role_label else "")
                + ". Accept or decline it in Settings → My shop."
            ),
            data={"membership_id": str(row.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def invite_by_account_number(
    db: Session, shop: models.User, account_number: str, role_label: str = ""
) -> models.ShopMembership:
    _require_shop_owner(shop)
    number = (account_number or "").strip()
    target = db.scalar(
        select(models.User).where(models.User.account_number == number)
    )
    if target is None:
        raise CrewError("No account carries that account number.")
    if target.id == shop.id:
        raise CrewError("You're the shop owner — you don't need an invite.")
    existing = _existing_open(db, shop.id, employee_id=target.id)
    if existing is not None:
        if existing.status == "active":
            raise CrewError("That person is already in your crew.")
        return existing
    row = models.ShopMembership(
        shop_user_id=shop.id,
        employee_user_id=target.id,
        invite_email=target.email or "",
        invite_token=_token(),
        role_label=(role_label or "").strip(),
        status="invited",
    )
    db.add(row)
    db.flush()
    inbox.create_notification(
        db,
        target.id,
        kind=inbox.KIND_CREW_INVITE,
        title="You're invited to join a shop crew",
        body=(
            f"{shop.name or 'A shop'} invited you to join their crew"
            + (f" as {row.role_label}" if row.role_label else "")
            + ". Accept or decline it in Settings → My shop."
        ),
        data={"membership_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


# -- reads ------------------------------------------------------------------------


def membership_view(db: Session, row: models.ShopMembership) -> dict:
    employee = _user(db, row.employee_user_id)
    shop = _user(db, row.shop_user_id)
    view = {
        "id": row.id,
        "shop_user_id": row.shop_user_id,
        "shop_name": (shop.name if shop else "") or "Former shop",
        "employee_user_id": row.employee_user_id,
        "employee_name": (employee.name if employee else "") or "",
        "employee_email": (employee.email if employee else "") or row.invite_email,
        "employee_account_number": employee.account_number if employee else "",
        "invite_email": row.invite_email,
        "role_label": row.role_label,
        "status": row.status,
        "invited_at": row.invited_at,
        "accepted_at": row.accepted_at,
        "left_at": row.left_at,
    }
    if row.status == "left" and row.left_at is not None:
        elapsed = (date.today() - _aware(row.left_at).date()).days
        view["grace_days_left"] = max(0, GRACE_DAYS - elapsed)
    else:
        view["grace_days_left"] = None
    return view


def roster(db: Session, shop: models.User) -> list[models.ShopMembership]:
    """The owner's crew page list: pending invites + active
    members first, then recent departures (their grace countdown
    is the owner's business too)."""
    _require_shop_owner(shop)
    rows = list(
        db.scalars(
            select(models.ShopMembership)
            .where(models.ShopMembership.shop_user_id == shop.id)
            .order_by(models.ShopMembership.created_at.desc())
        )
    )
    rank = {"active": 0, "invited": 1, "left": 2, "declined": 3}
    return sorted(rows, key=lambda r: (rank.get(r.status, 9),))


def my_invites(db: Session, user: models.User) -> list[models.ShopMembership]:
    attach_pending_invites(db, user)
    return list(
        db.scalars(
            select(models.ShopMembership)
            .where(
                models.ShopMembership.employee_user_id == user.id,
                models.ShopMembership.status == "invited",
            )
            .order_by(models.ShopMembership.invited_at.desc())
        )
    )


def my_shops(db: Session, user: models.User) -> list[models.ShopMembership]:
    """The employee's "My shop" list: active memberships, plus
    departed ones still inside their 30-day grace window (the
    countdown surface)."""
    attach_pending_invites(db, user)
    rows = list(
        db.scalars(
            select(models.ShopMembership)
            .where(
                models.ShopMembership.employee_user_id == user.id,
                models.ShopMembership.status.in_(("active", "left")),
            )
            .order_by(models.ShopMembership.created_at.desc())
        )
    )
    out = []
    for row in rows:
        if row.status == "left" and row.left_at is not None:
            elapsed = (date.today() - _aware(row.left_at).date()).days
            if elapsed > GRACE_DAYS:
                continue
        out.append(row)
    return out


# -- lifecycle ---------------------------------------------------------------------


def _membership_or_404(
    db: Session, membership_id: uuid.UUID
) -> models.ShopMembership:
    row = db.get(models.ShopMembership, membership_id)
    if row is None:
        raise CrewNotFound("That crew membership doesn't exist.")
    return row


def respond(
    db: Session, user: models.User, membership_id: uuid.UUID, accept: bool
) -> models.ShopMembership:
    attach_pending_invites(db, user)
    row = _membership_or_404(db, membership_id)
    if row.employee_user_id != user.id or row.status != "invited":
        raise CrewNotFound("That crew invite isn't waiting for you.")
    shop_name = _display(db, row.shop_user_id, "The shop")
    if accept:
        row.status = "active"
        row.accepted_at = _now()
        inbox.create_notification(
            db,
            row.shop_user_id,
            kind=inbox.KIND_CREW_ACCEPTED,
            title="Crew invite accepted",
            body=f"{user.name or user.email} joined your crew"
            + (f" as {row.role_label}." if row.role_label else "."),
            data={"membership_id": str(row.id)},
            commit=False,
        )
    else:
        row.status = "declined"
        inbox.create_notification(
            db,
            row.shop_user_id,
            kind=inbox.KIND_CREW_DECLINED,
            title="Crew invite declined",
            body=f"{user.name or user.email} declined the crew invite from {shop_name}.",
            data={"membership_id": str(row.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def _mark_left(db: Session, row: models.ShopMembership) -> None:
    row.status = "left"
    row.left_at = _now()
    row.grace_notices = {}


def remove_member(
    db: Session, shop: models.User, membership_id: uuid.UUID
) -> models.ShopMembership:
    """The owner removes a member (or revokes a pending invite).
    Active members enter the 30-day grace; the member hears the
    clock started."""
    _require_shop_owner(shop)
    row = _membership_or_404(db, membership_id)
    if row.shop_user_id != shop.id or row.status not in ("invited", "active"):
        raise CrewNotFound("That person isn't in your crew.")
    was_active = row.status == "active"
    _mark_left(db, row)
    if was_active and row.employee_user_id is not None:
        inbox.create_notification(
            db,
            row.employee_user_id,
            kind=inbox.KIND_CREW_LEFT,
            title="You were removed from a shop crew",
            body=(
                f"{shop.name or 'The shop'} removed you from their crew. "
                f"If your coverage came from the shop's plan, you keep it "
                f"for {GRACE_DAYS} days — rejoin a crew or start your own "
                "plan before then and nothing changes."
            ),
            data={"membership_id": str(row.id)},
            commit=False,
        )
    db.commit()
    db.refresh(row)
    return row


def leave_shop(
    db: Session, user: models.User, membership_id: uuid.UUID
) -> models.ShopMembership:
    """The member leaves voluntarily — same grace clock, both
    sides notified."""
    row = _membership_or_404(db, membership_id)
    if row.employee_user_id != user.id or row.status != "active":
        raise CrewNotFound("That crew membership isn't yours to leave.")
    _mark_left(db, row)
    shop_name = _display(db, row.shop_user_id, "The shop")
    inbox.create_notification(
        db,
        user.id,
        kind=inbox.KIND_CREW_LEFT,
        title="You left a shop crew",
        body=(
            f"You left {shop_name}'s crew. If your coverage came from "
            f"the shop's plan, you keep it for {GRACE_DAYS} days — "
            "rejoin a crew or start your own plan before then and "
            "nothing changes."
        ),
        data={"membership_id": str(row.id)},
        commit=False,
    )
    inbox.create_notification(
        db,
        row.shop_user_id,
        kind=inbox.KIND_CREW_LEFT,
        title="A crew member left",
        body=f"{user.name or user.email} left your crew.",
        data={"membership_id": str(row.id)},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return row


# -- bracket truth -------------------------------------------------------------------


def member_tools(
    db: Session, shop: models.User, member_user_id: uuid.UUID
) -> dict:
    """One ACTIVE crew member's tool list as the shop may see it:
    READ-ONLY, and only what the member shares with the shop
    group (claims-ownership lane, 2026-11-07 — Ryan's model: the
    shop sees an employee's list read-only, for the shop's own
    reporting / insurance).

    The gate is the member's own consent sharing (core.sharing):
    membership alone still exposes nothing. The payload is the
    member's shop_company-group preview — the exact projection
    the insurer directory reads for its group — items and fields
    exactly as the member chose them. Sharing off (or never
    configured) reads as an empty list with sharing_enabled
    False, never an error: the shop learns the member isn't
    sharing, nothing more. A user with no ACTIVE membership
    under this shop is a 404 — the shop has no window into a
    stranger's vault, member or not."""
    _require_shop_owner(shop)
    row = db.scalars(
        select(models.ShopMembership).where(
            models.ShopMembership.shop_user_id == shop.id,
            models.ShopMembership.employee_user_id == member_user_id,
            models.ShopMembership.status == "active",
        )
    ).first()
    member = _user(db, member_user_id)
    if row is None or member is None:
        raise CrewNotFound(
            "That person isn't an active member of your crew."
        )
    from app.modules.core import sharing

    state = sharing.group_state(db, member_user_id, SHOP_GROUP)
    sharing_enabled = bool(state["enabled"])
    items = (
        sharing.build_preview(db, member_user_id, SHOP_GROUP)
        if sharing_enabled
        else []
    )
    return {
        "member_user_id": member_user_id,
        "member_name": member.name or "",
        "member_account_number": member.account_number,
        # Cross-user surface money rule: amounts render in the
        # OWNER's currency — the member's, here.
        "member_currency": member.currency,
        "sharing_enabled": sharing_enabled,
        "items": items,
    }


def crew_summary(db: Session, shop: models.User) -> dict:
    """Active headcount vs the subscription's STORED bracket
    (billing's BusinessBracket rows name what the bracket covers).
    A note appears only when the truth and the declaration
    disagree — friendly, never an enforcement."""
    _require_shop_owner(shop)
    active_count = int(
        db.scalar(
            select(func.count(models.ShopMembership.id)).where(
                models.ShopMembership.shop_user_id == shop.id,
                models.ShopMembership.status == "active",
            )
        )
        or 0
    )
    invited_count = int(
        db.scalar(
            select(func.count(models.ShopMembership.id)).where(
                models.ShopMembership.shop_user_id == shop.id,
                models.ShopMembership.status == "invited",
            )
        )
        or 0
    )
    from app.modules.billing import entitlements
    from app.modules.billing import models as billing_models

    bracket = None
    note = ""
    sub = entitlements.get_subscription(db, shop.id)
    if sub is not None and sub.bracket_key:
        row = db.scalars(
            select(billing_models.BusinessBracket).where(
                billing_models.BusinessBracket.bracket_key == sub.bracket_key
            )
        ).first()
        up_to = row.up_to_employees if row is not None else None
        bracket = {
            "plan_key": sub.plan_key,
            "bracket_key": sub.bracket_key,
            "up_to_employees": up_to,
            "label": (
                f"up to {up_to} employees" if up_to else "unlimited employees"
            ),
        }
        if up_to is not None and active_count > up_to:
            note = (
                f"Your crew has {active_count} active members, but your "
                f"plan's bracket covers {bracket['label']}. Update your "
                "bracket in Plan & billing so it matches your crew — "
                "nothing is enforced automatically."
            )
    return {
        "active_count": active_count,
        "invited_count": invited_count,
        "bracket": bracket,
        "bracket_note": note,
    }


# -- the 30-day job ---------------------------------------------------------------------


def _settled(db: Session, row: models.ShopMembership) -> bool:
    """A departed member needs no more clock notices when they
    have rejoined ANY crew or hold their own paid plan."""
    if row.employee_user_id is None:
        return True
    active = db.scalar(
        select(func.count(models.ShopMembership.id)).where(
            models.ShopMembership.employee_user_id == row.employee_user_id,
            models.ShopMembership.status == "active",
        )
    )
    if active:
        return True
    from app.modules.billing import entitlements

    return entitlements.resolve_entitlement(db, row.employee_user_id).is_paid


def run_grace_notifications(db: Session, today: date | None = None) -> dict:
    """The crew job's seam (idempotent): day-25 and expiry
    notices for departed members who haven't settled elsewhere.
    The row's grace_notices ledger is the memory — a re-run
    sends nothing twice."""
    today = today or date.today()
    sent = {"day25": 0, "expired": 0}
    rows = list(
        db.scalars(
            select(models.ShopMembership).where(
                models.ShopMembership.status == "left",
                models.ShopMembership.left_at.is_not(None),
                models.ShopMembership.employee_user_id.is_not(None),
                models.ShopMembership.accepted_at.is_not(None),
            )
        )
    )
    for row in rows:
        elapsed = (today - _aware(row.left_at).date()).days
        notices = dict(row.grace_notices or {})
        changed = False
        if elapsed >= GRACE_DAYS and "expired" not in notices:
            if not _settled(db, row):
                inbox.create_notification(
                    db,
                    row.employee_user_id,
                    kind=inbox.KIND_CREW_GRACE_EXPIRED,
                    title="Your shop coverage window has closed",
                    body=(
                        f"{GRACE_DAYS} days have passed since you left "
                        f"{_display(db, row.shop_user_id, 'the shop')}'s "
                        "crew, so your account now runs on the Free "
                        "plan. Your inventory is untouched — upgrade "
                        "any time to pick your coverage back up."
                    ),
                    data={"membership_id": str(row.id)},
                    commit=False,
                )
                sent["expired"] += 1
            notices["expired"] = today.isoformat()
            changed = True
        elif elapsed >= GRACE_WARNING_DAY and "day25" not in notices:
            if not _settled(db, row):
                inbox.create_notification(
                    db,
                    row.employee_user_id,
                    kind=inbox.KIND_CREW_GRACE_ENDING,
                    title="5 days left on your shop coverage window",
                    body=(
                        f"You left {_display(db, row.shop_user_id, 'the shop')}'s "
                        f"crew {elapsed} days ago. In "
                        f"{GRACE_DAYS - elapsed} days your account moves "
                        "to the Free plan unless you rejoin a crew or "
                        "start your own plan."
                    ),
                    data={"membership_id": str(row.id)},
                    commit=False,
                )
                sent["day25"] += 1
            notices["day25"] = today.isoformat()
            changed = True
        if changed:
            row.grace_notices = notices
    db.commit()
    return sent


# -- export + deletion seam ------------------------------------------------------------


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The export's crew section: shops I own (my roster) + crews
    I belong to — each side reads its own facts."""
    owned = list(
        db.scalars(
            select(models.ShopMembership)
            .where(models.ShopMembership.shop_user_id == owner_id)
            .order_by(models.ShopMembership.created_at)
        )
    )
    member = list(
        db.scalars(
            select(models.ShopMembership)
            .where(models.ShopMembership.employee_user_id == owner_id)
            .order_by(models.ShopMembership.created_at)
        )
    )
    return {
        "my_shop_roster": [membership_view(db, r) for r in owned],
        "my_crews": [membership_view(db, r) for r in member],
    }
