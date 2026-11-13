"""Borrowing service: the check-out ledger (conversion + upgrade of
the app's lending behavior — feature map row 28).

The app kept lending embedded in tool records (`current_checkout` /
`checkout_history`); here every lend is a row in `checkouts`, rows
are never deleted, and the table is the history. The blueprint's
upgrades ride along: due dates exist, and the borrower can be a
linked account (a peer counterparty) or a manual name/contact.

STATE MACHINE
    requested ──owner approves──▶ checked_out ──either party──▶ returned
    requested ──owner declines──▶ declined            (terminal)
    requested ──borrower cancels─▶ cancelled          (terminal)

Owner-initiated checkouts enter at checked_out directly (no request
dance — the owner is handing the item over in person).

INVARIANTS
- One ACTIVE row (requested | checked_out) per item, enforced in
  this service for a friendly error and by a partial unique index
  in the database as the race-proof backstop.
- Entitlement: an item outside the owner's ACTIVE SET (billing's
  shared filter, enforcement on) cannot START a lend — neither an
  owner checkout nor a peer request. A lend already running is
  never trapped by the plan changing underneath it: approval and
  return never consult the active set, so `returned` is always
  reachable.
- Repair standing (maintenance module): an item that is broken or
  in repair cannot START a lend either — owner checkout, peer
  request, and approval all refuse — but an item that breaks WHILE
  out is simply marked broken in place; the return path never
  consults the standing, so it can always come back.
- Returned-by choice (v1, deliberate): EITHER party may mark a
  checkout returned — the owner, or the linked borrower — and the
  row records who did it (`returned_by`). There is no second
  confirmation step: it keeps the flow to one tap for in-person
  hand-backs, and the ledger + the other party's inbox notification
  keep it auditable. A manual (unlinked) borrower has no account,
  so only the owner can mark those returned.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import vcard
from app.modules.billing import entitlements
from app.modules.borrowing import models
from app.modules.core import inbox
from app.modules.core import models as core_models
from app.modules.core import peer_sharing
from app.modules.inventory import history as inventory_history
from app.modules.inventory import service as inventory_service


class BorrowingError(ValueError):
    """Caller turns this into a 4xx."""


class BorrowingNotFound(BorrowingError):
    """The checkout/item named does not exist (or is not the
    caller's to see or act on — deliberately indistinguishable)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a DB timestamp to tz-aware UTC (SQLite returns naive)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# -- item resolution ---------------------------------------------------------


def _owned_item(db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID):
    """The owner's item (tool or battery) or None. Goes through
    inventory's service interface — borrowing never touches
    inventory's tables."""
    if item_kind == "tool":
        return inventory_service.get_tool(db, owner_id, item_id)
    if item_kind == "battery":
        return inventory_service.get_battery(db, owner_id, item_id)
    raise BorrowingError("Items are tools or batteries.")


def _item_is_active(db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID) -> bool:
    """Billing's shared active set: None = unrestricted."""
    if item_kind == "tool":
        active = entitlements.active_tool_ids(db, owner_id)
    else:
        active = entitlements.active_battery_ids(db, owner_id)
    return active is None or item_id in active


def active_checkout(
    db: Session, item_kind: str, item_id: uuid.UUID
) -> models.Checkout | None:
    """The item's one active lend (requested or checked_out), if any."""
    return db.scalars(
        select(models.Checkout).where(
            models.Checkout.item_kind == item_kind,
            models.Checkout.item_id == item_id,
            models.Checkout.state.in_(models.ACTIVE_STATES),
        )
    ).first()


def active_checkout_keys(
    db: Session, owner_id: uuid.UUID
) -> set[tuple[str, uuid.UUID]]:
    """Every (item_kind, item_id) the owner currently has out on an
    active lend, in ONE query — the batch twin of active_checkout
    for whole-vault consumers (reports at scale, step-4 fix D5)."""
    return {
        (kind, item_id)
        for kind, item_id in db.execute(
            select(models.Checkout.item_kind, models.Checkout.item_id).where(
                models.Checkout.owner_id == owner_id,
                models.Checkout.state.in_(models.ACTIVE_STATES),
            )
        )
    }


def _require_no_active(db: Session, item_kind: str, item_id: uuid.UUID, item_name: str) -> None:
    existing = active_checkout(db, item_kind, item_id)
    if existing is not None:
        if existing.state == models.STATE_REQUESTED:
            raise BorrowingError(
                f"{item_name} already has a borrow request waiting for a decision."
            )
        raise BorrowingError(f"{item_name} is already checked out.")


def _require_in_service(item, *, peer_facing: bool = False) -> None:
    """Repair standing (maintenance module, 2026-10-19): an item
    that is broken or out being repaired cannot START a lend —
    owner checkout, peer request, and request approval all pass
    through here. The standing lives on the inventory record, so
    this reads it without importing the maintenance module (the
    gate holds even if that module's UI is switched off; the
    standing simply can't change then). A lend already running is
    never trapped: returns don't consult this, and an item that
    breaks while out is marked broken in place (the repair record
    notes it was checked out) — the hand-back closes the lend."""
    # Standing (Package B): tools/batteries carry `standing` — the
    # authority, including lost/stolen, which refuse a lend too.
    # Set pieces have no standing; their repair_state speaks.
    state = getattr(item, "standing", None) or getattr(
        item, "repair_state", "in_service"
    )
    if state == "in_service":
        return
    if peer_facing:
        raise BorrowingError(
            "That item is out of service right now, so it can't be borrowed."
        )
    label = {
        "broken": "broken",
        "in_repair": "out for repair",
        "lost": "marked lost",
        "stolen": "marked stolen",
        "sold": "sold",
    }.get(state, "out of service")
    raise BorrowingError(
        f"{item.name} is {label} right now — it can't be lent out until it's back in service."
    )


# -- serialization -------------------------------------------------------------


def is_overdue(row: models.Checkout, now: datetime | None = None) -> bool:
    """Checked out and past its due moment. The boundary is strict:
    due exactly now is not yet overdue."""
    if row.state != models.STATE_CHECKED_OUT or row.due_at is None:
        return False
    return _aware(row.due_at) < (now or _now())


def checkout_view(
    row: models.Checkout,
    *,
    now: datetime | None = None,
    owner_name: str | None = None,
) -> dict:
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        # Resolved by the caller (batch in overview, the acting user
        # in single-row responses) — the ledger stores ids, and the
        # "Borrowed by me" surface needs a face for the owner.
        "owner_name": owner_name,
        "item_kind": row.item_kind,
        "item_id": row.item_id,
        "item_name": row.item_name,
        # Set lends: sibling rows of one bundle share this id (null
        # for ordinary single-item lends).
        "group_id": row.group_id,
        "borrower_user_id": row.borrower_user_id,
        "borrower_name": row.borrower_name,
        "borrower_contact": row.borrower_contact,
        # The address-book link (gap wave 1): which contact this
        # lend was made from, so the roll-up can gather history.
        "borrower_contact_id": row.borrower_contact_id,
        "state": row.state,
        "requested_at": row.requested_at,
        "decided_at": row.decided_at,
        "checked_out_at": row.checked_out_at,
        "due_at": row.due_at,
        "returned_at": row.returned_at,
        "returned_by": row.returned_by,
        "notes": row.notes,
        "overdue": is_overdue(row, now),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _history_order(stmt):
    # Newest first, DETERMINISTICALLY: created_at ties (SQLite's
    # now() has second resolution; same-transaction inserts share a
    # timestamp even on Postgres) break on seq — the monotonic
    # insertion counter (migration 0023) — never on the random id.
    # id remains only as a final, unreachable-in-practice tiebreak
    # so the emitted order is total.
    return stmt.order_by(
        models.Checkout.created_at.desc(),
        models.Checkout.seq.desc(),
        models.Checkout.id.desc(),
    )


# -- creation: owner-initiated checkout -----------------------------------------


def _set_addon_tools(db: Session, item, include_addons: bool):
    """The attached addon tools a set lend covers, via inventory's
    shared member resolution — empty for non-sets (batteries never
    are) or when the owner didn't include addons. Pieces ride inside
    the set physically; only attached TOOLS need ledger rows of
    their own (they're the lendable units)."""
    if getattr(item, "is_set", False) and include_addons:
        members = inventory_service.resolve_set_members(db, item, True)
        return list(members["attached_tools"])
    return []


def create_checkout(
    db: Session,
    owner: core_models.User,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    borrower_user_id: uuid.UUID | None = None,
    borrower_name: str | None = None,
    borrower_contact: str = "",
    borrower_contact_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    notes: str = "",
    include_addons: bool = False,
) -> models.Checkout:
    """The owner lends one of their items, effective immediately.

    The borrower is a linked counterparty (borrower_user_id — name
    snapshotted from their account) or a manual name/contact. A
    linked borrower's inbox hears about returns later; there is no
    "you've been lent" notification for owner-initiated lends since
    the handover is in person by construction.

    SETS (item structure package): checking out a set ASKS "include
    the addon pieces too?" — with include_addons, one sibling row is
    created per attached addon tool, all sharing one group_id with
    the set's row (pieces ride inside the set; attached tools are
    the extra physical units). The whole bundle is validated before
    any row is written, and returning any row returns the bundle.
    """
    item = _owned_item(db, owner.id, item_kind, item_id)
    if item is None:
        raise BorrowingNotFound("That item isn't in your vault.")
    if not _item_is_active(db, owner.id, item_kind, item_id):
        raise BorrowingError(
            f"{item.name} is inactive — it's over your plan's item limit, "
            "so it can't be checked out."
        )
    _require_no_active(db, item_kind, item_id, item.name)
    _require_in_service(item)
    addon_tools = (
        _set_addon_tools(db, item, include_addons) if item_kind == "tool" else []
    )
    for addon in addon_tools:
        _require_no_active(db, "tool", addon.id, addon.name)
        _require_in_service(addon)

    if borrower_user_id is not None:
        if borrower_user_id == owner.id:
            raise BorrowingError("You can't lend an item to yourself.")
        borrower = db.get(core_models.User, borrower_user_id)
        counterparty_ids = {
            p["id"] for p in peer_sharing.accepted_counterparties(db, owner)
        }
        if borrower is None or str(borrower_user_id) not in counterparty_ids:
            raise BorrowingError(
                "That person isn't linked to you — invite them under "
                "Sharing first, or lend by name instead."
            )
        name = borrower.name
        contact = borrower_contact or ""
    else:
        # Address book (gap wave 1): picking a contact prefills
        # the manual name/contact from the book — explicitly typed
        # values still win — and stamps the contact link on the
        # ledger row so the roll-up can gather this lend.
        book_contact = None
        if borrower_contact_id is not None:
            book_contact = get_borrower_contact(db, owner, borrower_contact_id)
            if book_contact is None:
                raise BorrowingError(
                    "That borrower isn't in your address book."
                )
        name = (borrower_name or "").strip()
        if not name and book_contact is not None:
            name = book_contact.name
        if not name:
            raise BorrowingError("Who is borrowing it? Pick a person or type a name.")
        contact = borrower_contact or (
            book_contact.contact if book_contact is not None else ""
        )

    now = _now()
    group_id = uuid.uuid4() if addon_tools else None
    row = models.Checkout(
        owner_id=owner.id,
        item_kind=item_kind,
        item_id=item_id,
        item_name=item.name,
        group_id=group_id,
        borrower_user_id=borrower_user_id,
        borrower_name=name,
        borrower_contact=contact,
        borrower_contact_id=borrower_contact_id
        if borrower_user_id is None
        else None,
        state=models.STATE_CHECKED_OUT,
        requested_at=now,
        decided_at=now,
        checked_out_at=now,
        due_at=due_at,
        notes=notes or "",
    )
    db.add(row)
    for addon in addon_tools:
        db.add(
            models.Checkout(
                owner_id=owner.id,
                item_kind="tool",
                item_id=addon.id,
                item_name=addon.name,
                group_id=group_id,
                borrower_user_id=borrower_user_id,
                borrower_name=name,
                borrower_contact=contact,
                borrower_contact_id=row.borrower_contact_id,
                state=models.STATE_CHECKED_OUT,
                requested_at=now,
                decided_at=now,
                checked_out_at=now,
                due_at=due_at,
                notes=notes or "",
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if addon_tools:
            raise BorrowingError(
                "One of the set's items is already checked out."
            ) from None
        raise BorrowingError(f"{item.name} is already checked out.") from None
    db.refresh(row)
    return row


# -- creation: peer request -------------------------------------------------------


def request_borrow(
    db: Session,
    requester: core_models.User,
    *,
    owner_id: uuid.UUID,
    item_kind: str,
    item_id: uuid.UUID,
    due_at: datetime | None = None,
    notes: str = "",
) -> models.Checkout:
    """A viewer with an accepted grant asks to borrow an item.

    The gates, in order: an accepted grant must exist (else the
    owner is a stranger — 404); the item must be on the owner's
    PEER-VISIBLE list (not withheld via exclusions, not entitlement-
    inactive — same list the viewer browsed); and no active lend may
    exist for it. The owner is notified in this commit.
    """
    if item_kind not in models.ITEM_KINDS:
        raise BorrowingError("Items are tools or batteries.")
    if owner_id == requester.id:
        raise BorrowingNotFound("That item isn't shared with you.")
    # list_for_viewer raises PeerNotFound (404) without a grant and
    # applies exclusions + the entitlement filter for us — the exact
    # list the requester was looking at.
    try:
        listing = peer_sharing.list_for_viewer(db, requester, owner_id)
    except peer_sharing.PeerSharingError as exc:
        raise BorrowingNotFound(str(exc)) from exc
    visible = {
        (item.get("kind", "tool"), item["id"]) for item in listing["items"]
    }
    if (item_kind, str(item_id)) not in visible:
        raise BorrowingNotFound("That item isn't shared with you.")

    owner = db.get(core_models.User, owner_id)
    item = _owned_item(db, owner_id, item_kind, item_id)
    if owner is None or item is None:
        raise BorrowingNotFound("That item isn't shared with you.")
    _require_no_active(db, item_kind, item_id, item.name)
    _require_in_service(item, peer_facing=True)

    row = models.Checkout(
        owner_id=owner_id,
        item_kind=item_kind,
        item_id=item_id,
        item_name=item.name,
        borrower_user_id=requester.id,
        borrower_name=requester.name,
        borrower_contact="",
        state=models.STATE_REQUESTED,
        requested_at=_now(),
        due_at=due_at,
        notes=notes or "",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BorrowingError(f"{item.name} is already checked out.") from None
    inbox.borrow_requested(
        db,
        checkout_id=row.id,
        owner_id=owner_id,
        requester_name=requester.name,
        item_kind=item_kind,
        item_id=item_id,
        item_name=item.name,
    )
    db.commit()
    db.refresh(row)
    return row


# -- transitions -------------------------------------------------------------------


def _row_or_404(db: Session, checkout_id: uuid.UUID) -> models.Checkout:
    row = db.get(models.Checkout, checkout_id)
    if row is None:
        raise BorrowingNotFound("That lend doesn't exist.")
    return row


def decide(
    db: Session, owner: core_models.User, checkout_id: uuid.UUID, *, approve: bool
) -> models.Checkout:
    """The owner answers a pending request. Approval is a state
    stamp (times set, borrower notified); declining is terminal.
    Only the owner decides, and only from `requested` — a repeated
    decision is an error, never a duplicate notification."""
    row = _row_or_404(db, checkout_id)
    if row.owner_id != owner.id:
        raise BorrowingNotFound("That lend doesn't exist.")
    if row.state != models.STATE_REQUESTED:
        raise BorrowingError("That request was already answered.")
    now = _now()
    row.decided_at = now
    if approve:
        # An item that broke after the request arrived can't go
        # out: approval is a lend START, so the repair gate applies
        # here too (before anything mutates — the request stays
        # pending for the owner to answer once it's fixed).
        decided_item = _owned_item(db, owner.id, row.item_kind, row.item_id)
        if decided_item is not None:
            _require_in_service(decided_item)
        # SETS: the request names the set; approving covers the set
        # plus its addons per the OWNER's stored peer choice (the
        # "include addon pieces?" answer for the crew list). If any
        # covered addon is already out, the approval refuses BEFORE
        # anything mutates — the request stays pending.
        if row.item_kind == "tool":
            item = _owned_item(db, owner.id, "tool", row.item_id)
            if item is not None and getattr(item, "is_set", False):
                include = peer_sharing.set_include_addons(db, owner.id, item.id)
                addon_tools = _set_addon_tools(db, item, include)
                for addon in addon_tools:
                    _require_no_active(db, "tool", addon.id, addon.name)
                    _require_in_service(addon)
                if addon_tools:
                    group_id = row.group_id or uuid.uuid4()
                    row.group_id = group_id
                    for addon in addon_tools:
                        db.add(
                            models.Checkout(
                                owner_id=owner.id,
                                item_kind="tool",
                                item_id=addon.id,
                                item_name=addon.name,
                                group_id=group_id,
                                borrower_user_id=row.borrower_user_id,
                                borrower_name=row.borrower_name,
                                borrower_contact=row.borrower_contact,
                                state=models.STATE_CHECKED_OUT,
                                requested_at=row.requested_at,
                                decided_at=now,
                                checked_out_at=now,
                                due_at=row.due_at,
                                notes=row.notes,
                            )
                        )
        row.state = models.STATE_CHECKED_OUT
        row.checked_out_at = now
        if row.borrower_user_id is not None:
            inbox.borrow_approved(
                db,
                checkout_id=row.id,
                borrower_id=row.borrower_user_id,
                owner_name=owner.name,
                item_kind=row.item_kind,
                item_id=row.item_id,
                item_name=row.item_name,
            )
    else:
        row.state = models.STATE_DECLINED
        if row.borrower_user_id is not None:
            inbox.borrow_declined(
                db,
                checkout_id=row.id,
                borrower_id=row.borrower_user_id,
                owner_name=owner.name,
                item_kind=row.item_kind,
                item_id=row.item_id,
                item_name=row.item_name,
            )
    db.commit()
    db.refresh(row)
    return row


def cancel_request(
    db: Session, borrower: core_models.User, checkout_id: uuid.UUID
) -> models.Checkout:
    """The borrower withdraws their own pending request (terminal).
    Only from `requested`, only by the linked borrower."""
    row = _row_or_404(db, checkout_id)
    if row.borrower_user_id != borrower.id:
        raise BorrowingNotFound("That lend doesn't exist.")
    if row.state != models.STATE_REQUESTED:
        raise BorrowingError("That request is no longer waiting — it can't be cancelled.")
    row.state = models.STATE_CANCELLED
    row.decided_at = _now()
    inbox.borrow_request_cancelled(
        db,
        checkout_id=row.id,
        owner_id=row.owner_id,
        requester_name=borrower.name,
        item_kind=row.item_kind,
        item_id=row.item_id,
        item_name=row.item_name,
    )
    db.commit()
    db.refresh(row)
    return row


def mark_returned(
    db: Session, user: core_models.User, checkout_id: uuid.UUID
) -> models.Checkout:
    """Mark a checked-out item returned. EITHER party may do it —
    the owner, or the linked borrower — and `returned_by` records
    who (the v1 rule, documented in the module docstring). No
    entitlement check lives here on purpose: a lend that started
    while the item was active can always be closed, even if the
    item has since gone over the plan limit. The other party is
    notified when there is one (manual borrowers have no inbox)."""
    row = _row_or_404(db, checkout_id)
    is_owner = row.owner_id == user.id
    is_borrower = row.borrower_user_id is not None and row.borrower_user_id == user.id
    if not (is_owner or is_borrower):
        raise BorrowingNotFound("That lend doesn't exist.")
    if row.state != models.STATE_CHECKED_OUT:
        raise BorrowingError("That item isn't checked out.")
    returned_at = _now()
    row.state = models.STATE_RETURNED
    row.returned_at = returned_at
    row.returned_by = "owner" if is_owner else "borrower"
    if row.group_id is not None:
        # A set lend returns as a bundle: every still-out sibling in
        # the group closes with the same stamp (one notification —
        # the one below for the acted row — covers the hand-back).
        siblings = db.scalars(
            select(models.Checkout).where(
                models.Checkout.group_id == row.group_id,
                models.Checkout.owner_id == row.owner_id,
                models.Checkout.state == models.STATE_CHECKED_OUT,
                models.Checkout.id != row.id,
            )
        )
        for sibling in siblings:
            sibling.state = models.STATE_RETURNED
            sibling.returned_at = returned_at
            sibling.returned_by = row.returned_by
    if is_owner and row.borrower_user_id is not None:
        inbox.borrow_returned(
            db,
            checkout_id=row.id,
            notify_user_id=row.borrower_user_id,
            actor_name=user.name,
            actor_is_owner=True,
            item_kind=row.item_kind,
            item_id=row.item_id,
            item_name=row.item_name,
        )
    elif is_borrower:
        inbox.borrow_returned(
            db,
            checkout_id=row.id,
            notify_user_id=row.owner_id,
            actor_name=user.name,
            actor_is_owner=False,
            item_kind=row.item_kind,
            item_id=row.item_id,
            item_name=row.item_name,
        )
    db.commit()
    db.refresh(row)
    return row


# -- reads -------------------------------------------------------------------------


def counterparties(db: Session, user: core_models.User) -> list[dict]:
    """The borrower picker: people linked by an accepted peer grant
    in either direction (core's peer-sharing interface)."""
    return peer_sharing.accepted_counterparties(db, user)


def overview(db: Session, user: core_models.User, *, now: datetime | None = None) -> dict:
    """The Borrowing page in one read: my pending decisions, my
    outgoing requests, what's out, what I hold, and recent history,
    plus the counts the header badges and the home stat use."""
    now = now or _now()

    def rows_where(*conditions) -> list[models.Checkout]:
        return list(db.scalars(_history_order(select(models.Checkout).where(*conditions))))

    requests_for_me = rows_where(
        models.Checkout.owner_id == user.id,
        models.Checkout.state == models.STATE_REQUESTED,
    )
    my_requests = rows_where(
        models.Checkout.borrower_user_id == user.id,
        models.Checkout.state == models.STATE_REQUESTED,
    )
    lent_out = rows_where(
        models.Checkout.owner_id == user.id,
        models.Checkout.state == models.STATE_CHECKED_OUT,
    )
    borrowed_by_me = rows_where(
        models.Checkout.borrower_user_id == user.id,
        models.Checkout.state == models.STATE_CHECKED_OUT,
    )
    history = rows_where(
        or_(
            models.Checkout.owner_id == user.id,
            models.Checkout.borrower_user_id == user.id,
        ),
        models.Checkout.state.in_(
            (models.STATE_RETURNED, models.STATE_DECLINED, models.STATE_CANCELLED)
        ),
    )[:50]
    overdue = [r for r in lent_out + borrowed_by_me if is_overdue(r, now)]
    all_rows = requests_for_me + my_requests + lent_out + borrowed_by_me + history
    owner_names: dict[uuid.UUID, str] = {}
    for owner_id in {r.owner_id for r in all_rows}:
        account = db.get(core_models.User, owner_id)
        if account is not None:
            owner_names[owner_id] = account.name

    def view(r: models.Checkout) -> dict:
        return checkout_view(r, now=now, owner_name=owner_names.get(r.owner_id))

    return {
        "requests_for_me": [view(r) for r in requests_for_me],
        "my_requests": [view(r) for r in my_requests],
        "lent_out": [view(r) for r in lent_out],
        "borrowed_by_me": [view(r) for r in borrowed_by_me],
        "history": [view(r) for r in history],
        "counts": {
            "pending_requests": len(requests_for_me),
            "checked_out": len(lent_out),
            "borrowed": len(borrowed_by_me),
            "overdue": len(overdue),
        },
    }


def stats(db: Session, user_id: uuid.UUID) -> dict:
    """The home-stat numbers: how many of MY items are out right
    now, and how many items I currently hold from other members
    (Phase 3 panel stat "Borrowed by me" — peer checkouts where
    I am the linked borrower)."""
    count = db.scalar(
        select(func.count(models.Checkout.id)).where(
            models.Checkout.owner_id == user_id,
            models.Checkout.state == models.STATE_CHECKED_OUT,
        )
    )
    borrowed = db.scalar(
        select(func.count(models.Checkout.id)).where(
            models.Checkout.borrower_user_id == user_id,
            models.Checkout.state == models.STATE_CHECKED_OUT,
        )
    )
    return {
        "checked_out_count": int(count or 0),
        "borrowed_by_me_count": int(borrowed or 0),
    }


def export_borrower_contacts(db: Session, user_id: uuid.UUID) -> list[dict]:
    """The address book itself — the data export's borrowers.json
    (gap wave 1)."""
    rows = db.scalars(
        select(models.BorrowerContact)
        .where(models.BorrowerContact.owner_id == user_id)
        .order_by(models.BorrowerContact.name)
    ).all()
    return [serialize_borrower_contact(db, row) for row in rows]


def export_rows(db: Session, user_id: uuid.UUID) -> list[dict]:
    """Every lend the user is a party to (as owner or as linked
    borrower), newest first — the data export's borrowing.json."""
    rows = db.scalars(
        _history_order(
            select(models.Checkout).where(
                or_(
                    models.Checkout.owner_id == user_id,
                    models.Checkout.borrower_user_id == user_id,
                )
            )
        )
    )
    return [checkout_view(r) for r in rows]


def item_lending(
    db: Session, owner: core_models.User, item_kind: str, item_id: uuid.UUID
) -> dict:
    """One item's lending standing for its detail page: the current
    active lend (the status chip) + the full history, newest first.
    Owner-only — the ledger belongs to the item's owner."""
    item = _owned_item(db, owner.id, item_kind, item_id)
    if item is None:
        raise BorrowingNotFound("That item isn't in your vault.")
    current = active_checkout(db, item_kind, item_id)
    history = list(
        db.scalars(
            _history_order(
                select(models.Checkout).where(
                    models.Checkout.item_kind == item_kind,
                    models.Checkout.item_id == item_id,
                    models.Checkout.owner_id == owner.id,
                )
            )
        )
    )
    return {
        "item_kind": item_kind,
        "item_id": item_id,
        "current": (
            checkout_view(current, owner_name=owner.name)
            if current is not None
            else None
        ),
        "history": [checkout_view(r, owner_name=owner.name) for r in history],
    }


# -- borrower address book (gap wave 1, 2026-10-20) ------------------------------
#
# Reusable borrower contacts: the check-out flow picks a person
# instead of re-typing them, each contact carries a roll-up over
# the ledger (current holds / total lends / full history), and an
# overdue lend gets a polite pre-written Nudge. Deleting a
# contact NEVER touches the ledger — lends keep their snapshots
# and the borrower_contact_id link simply stops resolving.


def _contact_counts(db: Session, contact_id: uuid.UUID) -> tuple[int, int]:
    """(current holds, total lends) for one contact, straight
    from the ledger: holds = rows out right now; lends = every
    row that ever became a lend (out now or returned)."""
    rows = db.scalars(
        select(models.Checkout).where(
            models.Checkout.borrower_contact_id == contact_id
        )
    ).all()
    holds = sum(1 for r in rows if r.state == models.STATE_CHECKED_OUT)
    lends = sum(
        1
        for r in rows
        if r.state in (models.STATE_CHECKED_OUT, models.STATE_RETURNED)
    )
    return holds, lends


def serialize_borrower_contact(db: Session, row: models.BorrowerContact) -> dict:
    holds, lends = _contact_counts(db, row.id)
    return {
        "id": row.id,
        "name": row.name,
        "contact": row.contact,
        "notes": row.notes,
        "linked_user_id": row.linked_user_id,
        "current_holds": holds,
        "total_lends": lends,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_borrower_contacts(
    db: Session, owner: core_models.User
) -> list[models.BorrowerContact]:
    return list(
        db.scalars(
            select(models.BorrowerContact)
            .where(models.BorrowerContact.owner_id == owner.id)
            .order_by(models.BorrowerContact.name)
        )
    )


def get_borrower_contact(
    db: Session, owner: core_models.User, contact_id: uuid.UUID
) -> models.BorrowerContact | None:
    row = db.get(models.BorrowerContact, contact_id)
    if row is None or row.owner_id != owner.id:
        return None
    return row


def create_borrower_contact(
    db: Session, owner: core_models.User, data: dict
) -> models.BorrowerContact:
    name = (data.get("name") or "").strip()
    if not name:
        raise BorrowingError("A borrower needs a name.")
    linked = data.get("linked_user_id")
    if linked is not None:
        target = db.get(core_models.User, linked)
        if target is None or not target.is_active:
            raise BorrowingError("That account isn't available to link.")
    row = models.BorrowerContact(
        owner_id=owner.id,
        name=name,
        contact=(data.get("contact") or "")[:300],
        notes=data.get("notes") or "",
        linked_user_id=linked,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_borrower_contact(
    db: Session, owner: core_models.User, contact_id: uuid.UUID, data: dict
) -> models.BorrowerContact | None:
    row = get_borrower_contact(db, owner, contact_id)
    if row is None:
        return None
    if "name" in data and data["name"] is not None:
        cleaned = data["name"].strip()
        if not cleaned:
            raise BorrowingError("A borrower needs a name.")
        row.name = cleaned
    if "contact" in data and data["contact"] is not None:
        row.contact = data["contact"][:300]
    if "notes" in data and data["notes"] is not None:
        row.notes = data["notes"]
    if "linked_user_id" in data:
        linked = data["linked_user_id"]
        if linked is not None:
            target = db.get(core_models.User, linked)
            if target is None or not target.is_active:
                raise BorrowingError("That account isn't available to link.")
        row.linked_user_id = linked
    db.commit()
    db.refresh(row)
    return row


def delete_borrower_contact(
    db: Session, owner: core_models.User, contact_id: uuid.UUID
) -> bool:
    """Delete the BOOK entry only. The ledger is never touched:
    lends keep their name/contact snapshots (the whole point of
    snapshotting), and their borrower_contact_id simply stops
    resolving to a live contact."""
    row = get_borrower_contact(db, owner, contact_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def borrower_rollup(
    db: Session, owner: core_models.User, contact_id: uuid.UUID
) -> dict | None:
    """One contact's lending picture: what's out with them right
    now, and their full history from the ledger (newest first)."""
    row = get_borrower_contact(db, owner, contact_id)
    if row is None:
        return None
    lends = list(
        db.scalars(
            _history_order(
                select(models.Checkout).where(
                    models.Checkout.owner_id == owner.id,
                    models.Checkout.borrower_contact_id == contact_id,
                )
            )
        )
    )
    return {
        "contact": serialize_borrower_contact(db, row),
        "current": [
            checkout_view(r) for r in lends if r.state == models.STATE_CHECKED_OUT
        ],
        "history": [checkout_view(r) for r in lends],
    }


# -- contact cards: vCard export / import (contact cards lane, 2026-11-07) ----
#
# The address book speaks vCard through app.core.vcard (the one
# format implementation). Export is a straight read of the
# owner's own rows. Import NEVER writes blind: the preview call
# parses the uploaded file and flags likely duplicates against
# the book; only the rows the owner confirms come back to the
# import call, which re-validates each one through the ordinary
# create path. Nothing is merged and nothing is doubled silently.


def borrower_contact_card(row: models.BorrowerContact) -> str:
    """One borrower's vCard. The book's free-text contact field
    is split best-effort (the format library's split): emails
    and phone runs become real TEL/EMAIL lines; any descriptive
    remainder ("the guy at the marina") rides in the NOTE under
    the owner's own notes, so no typed information is dropped."""
    phones, emails, leftover = vcard.split_contact_text(row.contact)
    note_parts = []
    if row.notes.strip():
        note_parts.append(row.notes.strip())
    if leftover:
        note_parts.append(leftover)
    return vcard.build_vcard(
        name=row.name,
        phones=phones,
        emails=emails,
        note="\n\n".join(note_parts),
    )


def export_borrower_cards(db: Session, owner: core_models.User) -> str:
    """The whole address book as one .vcf file body."""
    rows = list_borrower_contacts(db, owner)
    return vcard.build_vcard_file([borrower_contact_card(r) for r in rows])


def _phone_key(phone: str) -> str:
    """Digits-only phone identity, compared on the last 10
    digits when both sides carry that many (a leading country
    code must not defeat the match)."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-10:] if len(digits) > 10 else digits


def _contact_keys(
    name: str, phones: list[str], emails: list[str]
) -> tuple[str, set[str], set[str]]:
    name_key = " ".join((name or "").split()).casefold()
    phone_keys = {_phone_key(p) for p in phones if _phone_key(p)}
    email_keys = {e.strip().casefold() for e in emails if e.strip()}
    return name_key, phone_keys, email_keys


def _book_keys(
    db: Session, owner: core_models.User
) -> list[tuple[models.BorrowerContact, tuple[str, set[str], set[str]]]]:
    keyed = []
    for row in list_borrower_contacts(db, owner):
        phones, emails, _leftover = vcard.split_contact_text(row.contact)
        keyed.append((row, _contact_keys(row.name, phones, emails)))
    return keyed


def _card_draft(card: dict) -> dict:
    """A parsed card -> the book's shape: name, the free-text
    contact (phones then emails, comma-joined), notes (the
    card's ORG has no field of its own in the book, so it is
    preserved as a labeled line at the head of the notes —
    visible in the preview, never silently dropped)."""
    contact = ", ".join([*card.get("phones", []), *card.get("emails", [])])
    note_parts = []
    org = (card.get("org") or "").strip()
    if org:
        note_parts.append(f"Organization: {org}")
    note = (card.get("note") or "").strip()
    if note:
        note_parts.append(note)
    return {
        "name": (card.get("name") or "").strip()[:300],
        "contact": contact[:300],
        "notes": "\n\n".join(note_parts)[:5000],
    }


def preview_borrower_import(
    db: Session, owner: core_models.User, cards: list[dict]
) -> dict:
    """The import preview: one row per readable card (with its
    likely-duplicate flag against the CURRENT book) plus one
    soft error per unreadable card. Creates nothing.

    A card is a LIKELY DUPLICATE when its name matches a book
    entry's name AND they share a phone or an email — the
    owner's call per row from here; the preview only flags."""
    book = _book_keys(db, owner)
    rows: list[dict] = []
    errors: list[dict] = []
    for index, card in enumerate(cards):
        if card.get("error"):
            errors.append(
                {
                    "index": index,
                    "message": (
                        "This card has no name on it, so it can't be added."
                        if card["error"] == "no_name"
                        else "This card couldn't be read."
                    ),
                }
            )
            continue
        draft = _card_draft(card)
        name_key, phone_keys, email_keys = _contact_keys(
            draft["name"],
            card.get("phones", []),
            card.get("emails", []),
        )
        duplicate_of = None
        for row, (b_name, b_phones, b_emails) in book:
            if name_key != b_name:
                continue
            if (phone_keys & b_phones) or (email_keys & b_emails):
                duplicate_of = row.name
                break
        rows.append(
            {
                "index": index,
                **draft,
                "duplicate": duplicate_of is not None,
                "duplicate_of": duplicate_of,
            }
        )
    return {"rows": rows, "errors": errors, "total_cards": len(cards)}


def import_borrower_contacts(
    db: Session, owner: core_models.User, rows: list[dict]
) -> list[models.BorrowerContact]:
    """Create exactly the confirmed rows, each through the
    ordinary create path (same validation as typing them in).
    A row that fails validation is skipped, never fatal to the
    batch — the caller reports who actually landed."""
    created = []
    for row in rows:
        try:
            created.append(
                create_borrower_contact(
                    db,
                    owner,
                    {
                        "name": row.get("name") or "",
                        "contact": row.get("contact") or "",
                        "notes": row.get("notes") or "",
                    },
                )
            )
        except BorrowingError:
            continue
    return created


def build_nudge_message(checkout: models.Checkout) -> str:
    """The pre-written polite reminder for one lend — friendly,
    specific (item + due date), and editable by the owner before
    it goes anywhere (the UI shows it as copy-text when it can't
    be delivered in-app)."""
    if checkout.due_at is not None:
        due = _aware(checkout.due_at).strftime("%B %d")
        when = (
            f"it was due back on {due}"
            if is_overdue(checkout)
            else f"it's due back on {due}"
        )
    else:
        when = "there's no due date on it"
    return (
        f"Hi {checkout.borrower_name} — friendly reminder about the "
        f"{checkout.item_name} you borrowed from me: {when}. "
        "Could you let me know when you can get it back to me? Thanks!"
    )


def _messaging_reaches(
    db: Session, owner: core_models.User, borrower_id: uuid.UUID
) -> bool:
    """True only when the messaging module is live for BOTH the
    owner sending and the borrower receiving (the operator
    switchboard, group assignment, and each user's own module
    switches). A parked messaging module must never receive
    writes it cannot show — a thread written while parked is a
    delivery to nowhere and a bell that 403s — and a borrower
    who can't use messaging would never see the delivery
    either; both cases fall back to copy-text below."""
    from app.modules.core import module_control

    if not module_control.effective_for_user(
        db, "messaging", owner.account_types, user_id=owner.id
    ):
        return False
    borrower = db.get(core_models.User, borrower_id)
    if borrower is None:
        return False
    return module_control.effective_for_user(
        db, "messaging", borrower.account_types, user_id=borrower.id
    )


def deliver_nudge(
    db: Session, owner: core_models.User, checkout: models.Checkout
) -> dict:
    """Send the nudge for one of the owner's lends. When the
    borrower is a linked platform user (the checkout's own linked
    borrower, or the address-book contact's account link), it
    goes through the messaging module as a normal conversation
    message; otherwise — or if messaging is parked / not live
    for one of the parties, or messaging refuses (spam budget,
    blocks) — it comes back as copy-text for the owner to send
    however they reach the person. Never raises for delivery
    problems: the copy is always usable."""
    if checkout.owner_id != owner.id:
        raise BorrowingNotFound("That lend isn't yours.")
    if checkout.state != models.STATE_CHECKED_OUT:
        raise BorrowingError("That item isn't out on a lend right now.")
    message = build_nudge_message(checkout)
    linked_id = checkout.borrower_user_id
    if linked_id is None and checkout.borrower_contact_id is not None:
        contact = get_borrower_contact(db, owner, checkout.borrower_contact_id)
        if contact is not None:
            linked_id = contact.linked_user_id
    if linked_id is not None and linked_id != owner.id:
        if not _messaging_reaches(db, owner, linked_id):
            # Messaging can't carry this nudge right now: do NOT
            # write into its tables. The owner gets the copy-text,
            # exactly as for an unlinked borrower.
            return {"message": message, "delivered_via": "copy", "thread_id": None}
        try:
            from app.modules.messaging import service as messaging_service

            thread = messaging_service.open_thread(
                db, owner, linked_id, message
            )
            return {
                "message": message,
                "delivered_via": "message",
                "thread_id": thread.id,
            }
        except messaging_service.MessagingError:
            # Messaging refused (spam budget, a block, a missing
            # account) — the owner still gets the copy to send
            # themselves.
            db.rollback()
    return {"message": message, "delivered_via": "copy", "thread_id": None}


# -- asset history provider (registered into inventory's feed) -----------------


def history_events(
    db: Session, owner_id: uuid.UUID, item_kind: str, item_id: uuid.UUID
) -> list[inventory_history.HistoryEvent]:
    """Asset-history provider: this item's lends. Only lends
    that actually went out (checked_out_at set) and their
    returns enter the story — a declined or cancelled request
    was never part of the item's life. Set lends ride their own
    rows (one per covered tool), so a set's page shows the set
    row's lend and an addon's page shows its own."""
    rows = db.scalars(
        select(models.Checkout)
        .where(
            models.Checkout.owner_id == owner_id,
            models.Checkout.item_kind == item_kind,
            models.Checkout.item_id == item_id,
        )
        .order_by(models.Checkout.created_at)
    )
    events: list[inventory_history.HistoryEvent] = []
    for row in rows:
        if row.checked_out_at is not None:
            detail_parts = []
            if row.due_at is not None:
                due = inventory_history.aware(row.due_at)
                detail_parts.append(f"Due back {due.date().isoformat()}")
            events.append(
                inventory_history.HistoryEvent(
                    ts=row.checked_out_at,
                    kind="lent",
                    title=(
                        f"Lent to {row.borrower_name}"
                        if row.borrower_name
                        else "Lent out"
                    ),
                    detail=" · ".join(detail_parts),
                )
            )
        if row.returned_at is not None:
            events.append(
                inventory_history.HistoryEvent(
                    ts=row.returned_at,
                    kind="returned",
                    title="Returned",
                    detail=(
                        f"From {row.borrower_name}" if row.borrower_name else ""
                    ),
                )
            )
    return events


inventory_history.register_history_provider("borrowing", history_events)
