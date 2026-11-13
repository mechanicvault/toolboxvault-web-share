"""Peer sharing service (core module).

Owner directive 2026-10-17: a person shares their tool LIST with
specific other PEOPLE — a mechanic with the four mechanics on their
crew, a shop owner with their crew — so anyone can search "who has
this tool?" and browse each other's lists for borrowing.

This is a SEPARATE system from tier (consent) sharing in sharing.py:

  - The recipient is a named person, invited by account number or
    email — not a group. The recipient accepts or declines; nothing
    is visible before acceptance. The owner can revoke, the viewer
    can leave; both delete the grant, so access ends immediately.
  - The payload is FIXED and minimal — no per-field config: item
    identity (name, brand, model, category) + photo URLs
    + the owner's display name and account number. Never pricing,
    notes, serials, documents, or custom data. The whitelist lives
    in inventory's service (peer_tool_view); this module only adds
    owner attribution, so leakage would require changing two modules.
  - Items are default-INCLUDED; the owner withholds specific tools
    via exclusions (peer_share_exclusions) that apply to every peer
    viewer at once.

Email invites to addresses without an account wait as
pending-by-email and attach when that email signs up: pending lists
match on invited_email, and accepting stamps the viewer id onto the
grant. An email invite NEVER reveals whether the address has an
account — the invite response is the same shape either way, and a
pending email invite shows the viewer only as the address until the
viewer accepts (accepting is the viewer revealing themselves).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import inbox, models, sharing
from app.modules.core import service as core_service
from app.modules.inventory import service as inventory_service

# The tool-owning world: only these groups can SEND peer invites and
# hold exclusions (routes gate on this). Anyone with an account can
# RECEIVE an invite — a dealer- or insurance-only account that is
# invited simply sees the pending invite; if they later gain a tool
# group, the module appears and the grant works like anyone's.
PEER_OWNER_TYPES: tuple[str, ...] = ("mechanic_technician", "shop_company")

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"


class PeerSharingError(ValueError):
    """Caller turns this into a 4xx."""


class PeerNotFound(PeerSharingError):
    """The grant/account named does not exist (or is not the caller's
    to act on — the two are deliberately indistinguishable)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _person(user: models.User) -> dict:
    """The only identity a peer surface ever shows about a person."""
    return {
        "id": str(user.id),
        "name": user.name,
        "account_number": user.account_number,
    }


def _viewer_is(grant: models.PeerShare, user: models.User) -> bool:
    """Is `user` the person this grant is addressed to? By stamped
    viewer id, or — for a pre-signup email invite not yet stamped —
    by the invited email matching the account's email."""
    if grant.viewer_user_id is not None:
        return grant.viewer_user_id == user.id
    return grant.invited_email is not None and grant.invited_email == user.email


def _addressed_to(user: models.User):
    """SQL condition: grants addressed to `user` (see _viewer_is)."""
    return or_(
        models.PeerShare.viewer_user_id == user.id,
        and_(
            models.PeerShare.viewer_user_id.is_(None),
            models.PeerShare.invited_email == user.email,
        ),
    )


def _outgoing_view(db: Session, grant: models.PeerShare) -> dict:
    """A grant as its OWNER sees it (sharing_with / invite response).

    Viewer identity is disclosed only when the owner already knows
    it: the invite went by account number (invited_email is NULL), or
    the viewer has accepted. A still-pending EMAIL invite shows only
    the address — even to the owner — so the invite flow can never
    be used to probe whether an email has an account.
    """
    viewer = None
    if grant.viewer_user_id is not None and (
        grant.invited_email is None or grant.status == STATUS_ACCEPTED
    ):
        user = db.get(models.User, grant.viewer_user_id)
        if user is not None:
            viewer = _person(user)
    return {
        "id": str(grant.id),
        "status": grant.status,
        "created_at": grant.created_at,
        "responded_at": grant.responded_at,
        "viewer": viewer,
        "invited_email": grant.invited_email,
    }


def _incoming_view(db: Session, grant: models.PeerShare) -> dict:
    """A grant as its VIEWER sees it (shared_with_me / pending_for_me):
    who is sharing with me. The owner's identity is the point of the
    surface, so it is always shown."""
    owner = db.get(models.User, grant.owner_id)
    return {
        "id": str(grant.id),
        "status": grant.status,
        "created_at": grant.created_at,
        "responded_at": grant.responded_at,
        "owner": _person(owner) if owner is not None else None,
    }


# -- invites -------------------------------------------------------------------


def _find_grant(
    db: Session,
    owner_id: uuid.UUID,
    *,
    viewer_user_id: uuid.UUID | None = None,
    invited_email: str | None = None,
) -> models.PeerShare | None:
    stmt = select(models.PeerShare).where(models.PeerShare.owner_id == owner_id)
    if viewer_user_id is not None:
        stmt = stmt.where(models.PeerShare.viewer_user_id == viewer_user_id)
    elif invited_email is not None:
        stmt = stmt.where(models.PeerShare.invited_email == invited_email)
    else:
        return None
    return db.scalars(stmt).first()


def invite(
    db: Session,
    owner: models.User,
    *,
    account_number: str | None = None,
    email: str | None = None,
) -> dict:
    """Invite one person to see the owner's list. Idempotent: inviting
    someone who already has a grant (pending or accepted) returns the
    existing grant unchanged — one grant per (owner, viewer).

    Returns the outgoing view. Email invites return the SAME view
    whether or not the address has an account (viewer stays None
    until acceptance either way).
    """
    if bool(account_number) == bool(email):
        raise PeerSharingError("Invite by account number or by email — not both.")

    if account_number:
        target = core_service.get_user_by_account_number(db, account_number)
        if target is None:
            raise PeerNotFound("No account with that number.")
        if target.id == owner.id:
            raise PeerSharingError("You can't invite yourself.")
        existing = _find_grant(db, owner.id, viewer_user_id=target.id)
        if existing is None:
            # The owner may have invited this person by email before
            # learning their number — merge onto that grant instead
            # of opening a second one.
            existing = _find_grant(db, owner.id, invited_email=target.email)
            if existing is not None and existing.viewer_user_id is None:
                existing.viewer_user_id = target.id
                db.commit()
                db.refresh(existing)
        if existing is not None:
            return _outgoing_view(db, existing)
        grant = models.PeerShare(
            owner_id=owner.id, viewer_user_id=target.id, status=STATUS_PENDING
        )
        db.add(grant)
        db.flush()  # materialize grant.id for the notification payload
        # Cross-party event: the invitee's inbox hears about it in the
        # same commit (inbox.py — no notification for a merge/repeat,
        # only for a genuinely new grant).
        inbox.peer_invite_received(
            db, owner=owner, invitee_id=target.id, grant_id=grant.id
        )
        db.commit()
        db.refresh(grant)
        return _outgoing_view(db, grant)

    address = (email or "").strip().lower()
    if address == owner.email:
        raise PeerSharingError("You can't invite yourself.")
    existing = _find_grant(db, owner.id, invited_email=address)
    if existing is not None:
        return _outgoing_view(db, existing)
    target = core_service.get_user_by_email(db, address)
    if target is not None:
        existing = _find_grant(db, owner.id, viewer_user_id=target.id)
        if existing is not None:
            return _outgoing_view(db, existing)
    grant = models.PeerShare(
        owner_id=owner.id,
        viewer_user_id=target.id if target is not None else None,
        invited_email=address,
        status=STATUS_PENDING,
    )
    db.add(grant)
    if target is not None:
        # The address has an account: their inbox hears about the
        # invite now. A pre-signup invite (target None) notifies
        # nobody — there is no inbox yet; the pending list is the
        # surface when they join.
        db.flush()
        inbox.peer_invite_received(
            db, owner=owner, invitee_id=target.id, grant_id=grant.id
        )
    db.commit()
    db.refresh(grant)
    return _outgoing_view(db, grant)


# -- overview --------------------------------------------------------------------


def _excluded_tool_ids(db: Session, owner_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(models.PeerShareExclusion.tool_id)
            .where(
                models.PeerShareExclusion.owner_id == owner_id,
                models.PeerShareExclusion.item_kind == "tool",
                models.PeerShareExclusion.tool_id.is_not(None),
            )
            .order_by(models.PeerShareExclusion.created_at)
        )
    )


def _excluded_battery_ids(db: Session, owner_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(models.PeerShareExclusion.battery_id)
            .where(
                models.PeerShareExclusion.owner_id == owner_id,
                models.PeerShareExclusion.item_kind == "battery",
                models.PeerShareExclusion.battery_id.is_not(None),
            )
            .order_by(models.PeerShareExclusion.created_at)
        )
    )


def get_overview(db: Session, user: models.User) -> dict:
    """Everything the peer surfaces render: grants I've made (with
    statuses), accepted grants to me, invites awaiting my decision,
    my exclusions, and my tools (for the exclusions picker)."""
    sharing_with = db.scalars(
        select(models.PeerShare)
        .where(models.PeerShare.owner_id == user.id)
        .order_by(models.PeerShare.created_at)
    )
    addressed = db.scalars(
        select(models.PeerShare)
        .where(_addressed_to(user))
        .order_by(models.PeerShare.created_at)
    )
    shared_with_me, pending_for_me = [], []
    for grant in addressed:
        if grant.status == STATUS_ACCEPTED:
            shared_with_me.append(_incoming_view(db, grant))
        elif grant.status == STATUS_PENDING:
            pending_for_me.append(_incoming_view(db, grant))
    return {
        "sharing_with": [_outgoing_view(db, g) for g in sharing_with],
        "shared_with_me": shared_with_me,
        "pending_for_me": pending_for_me,
        "excluded_tool_ids": _excluded_tool_ids(db, user.id),
        "excluded_battery_ids": _excluded_battery_ids(db, user.id),
        "my_tools": inventory_service.list_tool_identities(db, user.id),
        "my_batteries": inventory_service.list_battery_identities(db, user.id),
        # SETS: each of my sets with its effective addon choice —
        # the "include addon pieces?" toggles for the peer list.
        "set_choices": peer_set_choices(db, user),
        # RULES (Package C): scope-level withholdings + the vocab
        # their editor points at (same shapes as the tier editor).
        "exclusion_rules": exclusion_rule_views(db, user),
        "categories": inventory_service.field_suggestions(db, user.id, "category"),
        "tags": [
            {"id": t["id"], "name": t["name"], "item_count": t["item_count"]}
            for t in inventory_service.list_tags(db, user.id)
        ],
        "locations": inventory_service.list_location_tree(db, user.id),
    }


# -- grant actions -----------------------------------------------------------------


def _grant_or_404(db: Session, grant_id: uuid.UUID) -> models.PeerShare:
    grant = db.get(models.PeerShare, grant_id)
    if grant is None:
        raise PeerNotFound("That invite doesn't exist.")
    return grant


def accept(db: Session, user: models.User, grant_id: uuid.UUID) -> None:
    """Accept an invite addressed to me. Stamps my id onto the grant
    (this is the moment a pre-signup email invite attaches to the
    account for good)."""
    grant = _grant_or_404(db, grant_id)
    if grant.status != STATUS_PENDING or not _viewer_is(grant, user):
        raise PeerNotFound("That invite doesn't exist.")
    grant.status = STATUS_ACCEPTED
    grant.responded_at = _now()
    grant.viewer_user_id = user.id
    # Cross-party event: the owner's inbox hears about it in the
    # same commit.
    inbox.peer_invite_accepted(
        db, invitee=user, owner_id=grant.owner_id, grant_id=grant.id
    )
    db.commit()


def decline(db: Session, user: models.User, grant_id: uuid.UUID) -> None:
    """Decline an invite addressed to me: the grant is deleted, so
    nothing lingers and the owner may invite again later."""
    grant = _grant_or_404(db, grant_id)
    if grant.status != STATUS_PENDING or not _viewer_is(grant, user):
        raise PeerNotFound("That invite doesn't exist.")
    # Notify the owner BEFORE the grant row goes (same commit): a
    # decline is exactly the event the owner is waiting to hear.
    inbox.peer_invite_declined(
        db, invitee=user, owner_id=grant.owner_id, grant_id=grant.id
    )
    db.delete(grant)
    db.commit()


def revoke(db: Session, user: models.User, grant_id: uuid.UUID) -> None:
    """The owner ends a grant (pending or accepted), effective
    immediately: the row is deleted, so every viewer read for this
    owner comes back empty from the next request on."""
    grant = _grant_or_404(db, grant_id)
    if grant.owner_id != user.id:
        raise PeerNotFound("That invite doesn't exist.")
    db.delete(grant)
    db.commit()


def leave(db: Session, user: models.User, grant_id: uuid.UUID) -> None:
    """The viewer removes an accepted share from their own side.
    Same immediate effect as a revoke, initiated by the viewer."""
    grant = _grant_or_404(db, grant_id)
    if grant.status != STATUS_ACCEPTED or not _viewer_is(grant, user):
        raise PeerNotFound("That invite doesn't exist.")
    db.delete(grant)
    db.commit()


# -- exclusions --------------------------------------------------------------------


def set_exclusions(
    db: Session,
    owner: models.User,
    tool_ids: list[uuid.UUID],
    battery_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Replace the owner's peer exclusions wholesale — tools and
    batteries in one set. Every id must be one of the owner's own
    items of its kind — a foreign id refuses the whole write
    (nothing partial is applied), same rule as tier sharing.
    Returns (excluded tool ids, excluded battery ids)."""
    unique_tools = list(dict.fromkeys(tool_ids))
    owned_tools = inventory_service.get_owned_tools(db, owner.id, unique_tools)
    if len(owned_tools) != len(unique_tools):
        raise PeerSharingError("One or more tools do not belong to you.")
    unique_batteries = list(dict.fromkeys(battery_ids))
    owned_batteries = inventory_service.get_owned_batteries(
        db, owner.id, unique_batteries
    )
    if len(owned_batteries) != len(unique_batteries):
        raise PeerSharingError("One or more batteries do not belong to you.")
    # ORM deletes, not a bulk DELETE: every removed exclusion
    # lands in the owner's change journal (audit trail, 2026-10-19).
    for row in (
        db.query(models.PeerShareExclusion)
        .filter(models.PeerShareExclusion.owner_id == owner.id)
        .all()
    ):
        db.delete(row)
    for tool_id in unique_tools:
        db.add(
            models.PeerShareExclusion(
                owner_id=owner.id, item_kind="tool", tool_id=tool_id
            )
        )
    for battery_id in unique_batteries:
        db.add(
            models.PeerShareExclusion(
                owner_id=owner.id, item_kind="battery", battery_id=battery_id
            )
        )
    db.commit()
    return _excluded_tool_ids(db, owner.id), _excluded_battery_ids(db, owner.id)


# -- exclusion rules (Package C) ---------------------------------------------------
#
# The tier rule model (sharing.py) generalized to peer sharing.
# Peer's model is the INVERSE of tier's — default-include minus
# withholdings — so the same scopes generalize as WITHHOLDING
# rules: everything in this category / location subtree / tag
# never reaches the crew list, resolved dynamically through the
# one matcher (sharing.rule_matched_refs), so an item filed
# tomorrow into a withheld toolbox is withheld with no action.
# 'all' is deliberately absent: withholding everything is what
# revoking the grant is for. The payload whitelist is untouched —
# rules change WHICH items appear, never what an item shows.

PEER_RULE_SCOPES: tuple[str, ...] = ("category", "location", "tag")


def _exclusion_rule_rows(
    db: Session, owner_id: uuid.UUID
) -> list[models.PeerShareExclusionRule]:
    return list(
        db.scalars(
            select(models.PeerShareExclusionRule)
            .where(models.PeerShareExclusionRule.owner_id == owner_id)
            .order_by(models.PeerShareExclusionRule.created_at)
        )
    )


def rule_withheld_ids(
    db: Session, owner_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """(tool ids, battery ids) the owner's rules withhold RIGHT
    NOW — the dynamic half of the peer exclusion set, unioned with
    the per-item exclusions on every viewer read."""
    facts = inventory_service.list_item_sharing_facts(db, owner_id)
    nodes = inventory_service.owned_locations(db, owner_id)
    tools: set[uuid.UUID] = set()
    batteries: set[uuid.UUID] = set()
    for rule in _exclusion_rule_rows(db, owner_id):
        for ref in sharing.rule_matched_refs(
            db,
            owner_id,
            rule.scope,
            rule.scope_value,
            rule.scope_ref_id,
            facts=facts,
            nodes=nodes,
        ):
            (tools if ref["kind"] == "tool" else batteries).add(ref["id"])
    return tools, batteries


def _exclusion_rule_view(
    db: Session,
    owner: models.User,
    rule: models.PeerShareExclusionRule,
    *,
    facts: list[dict],
    nodes: list,
) -> dict:
    matches = sharing.rule_matched_refs(
        db,
        owner.id,
        rule.scope,
        rule.scope_value,
        rule.scope_ref_id,
        facts=facts,
        nodes=nodes,
    )
    return {
        "id": rule.id,
        "scope": rule.scope,
        "scope_value": rule.scope_value,
        "scope_ref_id": rule.scope_ref_id,
        "scope_label": sharing.rule_label(db, owner.id, rule, nodes),
        # Items this rule is withholding right now (matched —
        # whether or not a per-item exclusion also covers them).
        "match_count": len(matches),
        "created_at": rule.created_at,
    }


def exclusion_rule_views(db: Session, owner: models.User) -> list[dict]:
    facts = inventory_service.list_item_sharing_facts(db, owner.id)
    nodes = inventory_service.owned_locations(db, owner.id)
    return [
        _exclusion_rule_view(db, owner, rule, facts=facts, nodes=nodes)
        for rule in _exclusion_rule_rows(db, owner.id)
    ]


def create_exclusion_rule(
    db: Session,
    owner: models.User,
    *,
    scope: str,
    scope_value: str = "",
    scope_ref_id: uuid.UUID | None = None,
) -> dict:
    """Add a withholding rule (idempotent by target — re-adding
    the same scope target returns the existing rule). Returns the
    rule's view."""
    if scope not in PEER_RULE_SCOPES:
        raise PeerSharingError(f"Unknown rule scope '{scope}'.")
    value, ref_id = sharing.validate_rule_target(
        db, owner.id, scope, scope_value, scope_ref_id, error=PeerSharingError
    )
    existing = next(
        (
            r
            for r in _exclusion_rule_rows(db, owner.id)
            if r.scope == scope
            and r.scope_ref_id == ref_id
            and sharing._norm_category(r.scope_value)
            == sharing._norm_category(value)
        ),
        None,
    )
    if existing is None:
        existing = models.PeerShareExclusionRule(
            owner_id=owner.id,
            scope=scope,
            scope_value=value,
            scope_ref_id=ref_id,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    facts = inventory_service.list_item_sharing_facts(db, owner.id)
    nodes = inventory_service.owned_locations(db, owner.id)
    return _exclusion_rule_view(db, owner, existing, facts=facts, nodes=nodes)


def delete_exclusion_rule(
    db: Session, owner: models.User, rule_id: uuid.UUID
) -> None:
    """Remove one withholding rule (ORM delete — journaled). Its
    items become peer-visible again on the next read."""
    rule = db.get(models.PeerShareExclusionRule, rule_id)
    if rule is None or rule.owner_id != owner.id:
        raise PeerNotFound("That rule doesn't exist.")
    db.delete(rule)
    db.commit()


def _piece_identity(piece) -> dict:
    """A set piece in the peer payload: identity fields only (name,
    part number, serial) — the same whitelist discipline as the tool
    payload. No price (core pieces have none; addon prices are the
    owner's business), no notes, no documents."""
    return {
        "name": piece.name,
        "part_number": piece.part_number,
        "serial_number": piece.serial_number,
    }


def set_include_addons(db: Session, owner_id: uuid.UUID, set_tool_id: uuid.UUID) -> bool:
    """The owner's stored peer choice for one set — "include the
    addon pieces too?". DEFAULTS TRUE (peer philosophy: the crew
    list includes unless the owner decided otherwise); a stored row
    is the owner's explicit answer. Borrowing's set-checkout
    approval reads the same answer through here."""
    row = db.scalars(
        select(models.PeerSetChoice).where(
            models.PeerSetChoice.owner_id == owner_id,
            models.PeerSetChoice.set_tool_id == set_tool_id,
        )
    ).first()
    return True if row is None else bool(row.include_addons)


def set_peer_set_choice(
    db: Session, user: models.User, tool_id: uuid.UUID, include_addons: bool
) -> bool:
    """Store the owner's addon choice for one of their sets (the
    Settings → Sharing → People toggle). The tool must be the
    owner's own set — anything else is a refusal."""
    tool = inventory_service.get_tool(db, user.id, tool_id)
    if tool is None or not tool.is_set:
        raise PeerSharingError("That set does not belong to you.")
    row = db.scalars(
        select(models.PeerSetChoice).where(
            models.PeerSetChoice.owner_id == user.id,
            models.PeerSetChoice.set_tool_id == tool_id,
        )
    ).first()
    if row is None:
        db.add(
            models.PeerSetChoice(
                owner_id=user.id,
                set_tool_id=tool_id,
                include_addons=include_addons,
            )
        )
    else:
        row.include_addons = include_addons
    db.commit()
    return include_addons


def peer_set_choices(db: Session, user: models.User) -> list[dict]:
    """Every set the owner has, with its EFFECTIVE addon choice
    (stored row or the default) — the Settings toggle list."""
    out = []
    for identity in inventory_service.list_tool_identities(db, user.id):
        if not identity.get("is_set"):
            continue
        out.append(
            {
                "tool_id": identity["id"],
                "name": identity["name"],
                "include_addons": set_include_addons(db, user.id, identity["id"]),
            }
        )
    return out


# -- viewer reads --------------------------------------------------------------------


def _accepted_grant(
    db: Session, viewer: models.User, owner_id: uuid.UUID
) -> models.PeerShare | None:
    return db.scalars(
        select(models.PeerShare).where(
            models.PeerShare.owner_id == owner_id,
            models.PeerShare.status == STATUS_ACCEPTED,
            _addressed_to(viewer),
        )
    ).first()


def _peer_tool_entry(
    db: Session, owner: models.User, tool, attribution: dict
) -> dict:
    """One tool's peer entry. SETS ride as one entry carrying their
    members (item structure package): core pieces always (identity
    only — the peer whitelist discipline), addons per the owner's
    stored choice (default: included — the crew list never silently
    hides part of a set). Attached tools appear ONLY inside their
    set's entry, never as top-level entries."""
    entry = {**inventory_service.peer_tool_view(tool), "owner": attribution}
    if tool.is_set:
        include = set_include_addons(db, owner.id, tool.id)
        members = inventory_service.resolve_set_members(db, tool, include)
        entry["is_set"] = True
        entry["set"] = {
            "include_addons": include,
            "core_pieces": [_piece_identity(p) for p in members["core_pieces"]],
            "addon_pieces": [_piece_identity(p) for p in members["addon_pieces"]],
            "attached_tools": [
                inventory_service.peer_tool_view(t)
                for t in members["attached_tools"]
            ],
        }
    return entry


def _peer_items(
    db: Session,
    owner: models.User,
    excluded_tools: set[uuid.UUID],
    excluded_batteries: set[uuid.UUID] | None = None,
) -> list[dict]:
    """An owner's visible list: every item (tools, then batteries)
    minus exclusions and minus entitlement-inactive items (billing's
    shared filter — peers never see what the owner's plan doesn't
    cover), each in the fixed peer payload with the owner's
    attribution attached. Batteries ride the same whitelist via
    inventory's peer_battery_view (kind='battery' marks them)."""
    attribution = _person(owner)
    # RULES (Package C): scope withholdings union with the per-item
    # exclusions — a rule-matched item is as invisible as a picked
    # one, resolved live on this read.
    rule_tools, rule_batteries = rule_withheld_ids(db, owner.id)
    excluded_tools = excluded_tools | rule_tools
    excluded_batteries = (excluded_batteries or set()) | rule_batteries
    active_ids = entitlements.active_tool_ids(db, owner.id)
    items = []
    for tool in inventory_service.list_tools(db, owner.id):
        if tool.id in excluded_tools:
            continue
        if tool.standing in ("sold", "replaced"):
            continue  # sold items left the vault (wave 2) — never shared
        if active_ids is not None and tool.id not in active_ids:
            continue
        items.append(_peer_tool_entry(db, owner, tool, attribution))
    active_batteries = entitlements.active_battery_ids(db, owner.id)
    for battery in inventory_service.list_batteries(db, owner.id):
        if battery.id in excluded_batteries:
            continue
        if battery.standing in ("sold", "replaced"):
            continue  # sold items left the vault (wave 2) — never shared
        if active_batteries is not None and battery.id not in active_batteries:
            continue
        items.append(
            {**inventory_service.peer_battery_view(battery), "owner": attribution}
        )
    return items


def list_for_viewer(
    db: Session, viewer: models.User, owner_id: uuid.UUID
) -> dict:
    """One owner's list as `viewer` may see it. Requires an accepted
    grant; without one the owner is indistinguishable from a stranger
    (404, not 403 — there is nothing here for you)."""
    if _accepted_grant(db, viewer, owner_id) is None:
        raise PeerNotFound("That list isn't shared with you.")
    owner = db.get(models.User, owner_id)
    if owner is None:
        raise PeerNotFound("That list isn't shared with you.")
    excluded = set(_excluded_tool_ids(db, owner_id))
    excluded_batteries = set(_excluded_battery_ids(db, owner_id))
    return {
        "owner": _person(owner),
        "items": _peer_items(db, owner, excluded, excluded_batteries),
    }


def search_for_viewer(db: Session, viewer: models.User, query: str) -> list[dict]:
    """Search across EVERY owner who shares with me. Deliberate
    search: an empty query returns nothing (browsing is per-person,
    via list_for_viewer). Matches only the peer-payload fields
    (inventory.search_peer_tools), exclusions applied per owner."""
    if not query or not query.strip():
        return []
    grants = db.scalars(
        select(models.PeerShare).where(
            models.PeerShare.status == STATUS_ACCEPTED,
            _addressed_to(viewer),
        )
    )
    owner_ids = list(dict.fromkeys(g.owner_id for g in grants))
    if not owner_ids:
        return []
    # Per-item exclusions UNION the owner's withholding rules
    # (Package C) — search withholds exactly what the list does.
    withheld_by_owner = {
        owner_id: rule_withheld_ids(db, owner_id) for owner_id in owner_ids
    }
    excluded_by_owner = {
        owner_id: set(_excluded_tool_ids(db, owner_id))
        | withheld_by_owner[owner_id][0]
        for owner_id in owner_ids
    }
    excluded_batteries_by_owner = {
        owner_id: set(_excluded_battery_ids(db, owner_id))
        | withheld_by_owner[owner_id][1]
        for owner_id in owner_ids
    }
    # Entitlement standing (billing): an owner's inactive items are
    # excluded from peer search exactly as from their peer list.
    active_by_owner = {
        owner_id: entitlements.active_tool_ids(db, owner_id) for owner_id in owner_ids
    }
    active_batteries_by_owner = {
        owner_id: entitlements.active_battery_ids(db, owner_id)
        for owner_id in owner_ids
    }
    owners = {
        user.id: user
        for user in db.scalars(
            select(models.User).where(models.User.id.in_(owner_ids))
        )
    }
    results = []
    for tool in inventory_service.search_peer_tools(db, owner_ids, query):
        if tool.id in excluded_by_owner.get(tool.owner_id, set()):
            continue
        active_ids = active_by_owner.get(tool.owner_id)
        if active_ids is not None and tool.id not in active_ids:
            continue
        owner = owners.get(tool.owner_id)
        if owner is None:
            continue
        results.append(_peer_tool_entry(db, owner, tool, _person(owner)))
    for battery in inventory_service.search_peer_batteries(db, owner_ids, query):
        if battery.id in excluded_batteries_by_owner.get(battery.owner_id, set()):
            continue
        active_ids = active_batteries_by_owner.get(battery.owner_id)
        if active_ids is not None and battery.id not in active_ids:
            continue
        owner = owners.get(battery.owner_id)
        if owner is None:
            continue
        results.append(
            {
                **inventory_service.peer_battery_view(battery),
                "owner": _person(owner),
            }
        )
    return results


# -- cross-module interface (consumed by the borrowing module) -----------------
#
# Borrowing builds its people-picker and its request gate on these:
# it never imports the grant models or the private helpers above.


def has_accepted_grant(
    db: Session, viewer: models.User, owner_id: uuid.UUID
) -> bool:
    """True when `owner_id`'s list is shared with `viewer` under an
    accepted grant — the borrowing request gate (a requester must be
    able to SEE the list before they can ask for an item on it)."""
    return _accepted_grant(db, viewer, owner_id) is not None


def accepted_counterparties(db: Session, user: models.User) -> list[dict]:
    """The people linked to `user` by an accepted grant in EITHER
    direction (they share with me, or I share with them), as person
    dicts (id / name / account_number), deduped, in name order.
    Borrowing's borrower picker: these are the account-holders an
    owner can lend to by name instead of by free text."""
    people: dict[uuid.UUID, models.User] = {}

    # Grants I made that were accepted: the viewer is my counterparty.
    outgoing = db.scalars(
        select(models.PeerShare).where(
            models.PeerShare.owner_id == user.id,
            models.PeerShare.status == STATUS_ACCEPTED,
            models.PeerShare.viewer_user_id.is_not(None),
        )
    )
    for grant in outgoing:
        other = db.get(models.User, grant.viewer_user_id)
        if other is not None:
            people[other.id] = other

    # Grants addressed to me that I accepted: the owner is.
    incoming = db.scalars(
        select(models.PeerShare).where(
            models.PeerShare.status == STATUS_ACCEPTED,
            _addressed_to(user),
        )
    )
    for grant in incoming:
        other = db.get(models.User, grant.owner_id)
        if other is not None:
            people[other.id] = other

    people.pop(user.id, None)
    return [_person(p) for p in sorted(people.values(), key=lambda p: p.name)]
