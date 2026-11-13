"""Consent sharing service (core module).

The owner's model (2026-10-17): a mechanic's tool list can be shared
with the SHOP group and/or the INSURANCE group — only what the owner
approves, on two axes:

  - FIELDS: per recipient group, the owner toggles the optional
    fields (sharing_catalog.py). Locked identity fields always go
    when an item is shared.
  - ITEMS: per recipient group, the owner picks the tools — all,
    none, or per item (Settings sends the complete set).

Everything here is owner-scoped by construction: every function
takes the caller's id and only ever reads or writes that owner's
rows and tools. Tool data comes through inventory's service
interface (module law) — this module never imports inventory models.

`build_preview` returns the EXACT payload a connected recipient in
the group will later receive: only the locked fields plus the
owner's chosen fields, with unchosen fields ABSENT (not nulled).

RULES (Package C, 2026-10-19): alongside the per-item picks, a
group's config carries scope rules (category | location subtree |
tag | all) that resolve DYNAMICALLY at read time —
resolve_shared_items computes (picks ∪ rule matches) −
exclusions against the vault as it stands, so an item bought
tomorrow into a shared category is shared with no further action.
Rules change WHICH items are shared; the field config still
decides WHICH FIELDS a shared item shows. The matcher
(rule_matched_refs) is the one engine both this module and peer
sharing's withholding rules resolve through.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing import entitlements
from app.modules.core import models
from app.modules.core.sharing_catalog import (
    DEFAULT_SHARED_FIELDS,
    DOCUMENT_KINDS,
    OPTIONAL_FIELDS,
    PHOTO_KINDS,
    RECIPIENT_GROUPS,
    canonical_fields,
)
from app.modules.inventory import service as inventory_service


class SharingError(ValueError):
    """Caller turns this into a 4xx."""


def _require_group(group: str) -> None:
    if group not in RECIPIENT_GROUPS:
        raise SharingError(f"Unknown recipient group: {group}")


def _stored_config(
    db: Session, owner_id: uuid.UUID, group: str
) -> models.ShareConfig | None:
    return db.scalars(
        select(models.ShareConfig).where(
            models.ShareConfig.owner_id == owner_id,
            models.ShareConfig.recipient_group == group,
        )
    ).first()


def _shared_rows(
    db: Session, owner_id: uuid.UUID, group: str
) -> list[models.SharedItem]:
    return list(
        db.scalars(
            select(models.SharedItem)
            .where(
                models.SharedItem.owner_id == owner_id,
                models.SharedItem.recipient_group == group,
            )
            .order_by(models.SharedItem.created_at)
        )
    )


def _rules(
    db: Session, owner_id: uuid.UUID, group: str
) -> list[models.ShareRule]:
    return list(
        db.scalars(
            select(models.ShareRule)
            .where(
                models.ShareRule.owner_id == owner_id,
                models.ShareRule.recipient_group == group,
            )
            .order_by(models.ShareRule.created_at)
        )
    )


def _exclusion_rows(
    db: Session, owner_id: uuid.UUID, group: str
) -> list[models.ShareExclusion]:
    return list(
        db.scalars(
            select(models.ShareExclusion).where(
                models.ShareExclusion.owner_id == owner_id,
                models.ShareExclusion.recipient_group == group,
            )
        )
    )


def _item_ref(row: models.SharedItem) -> dict:
    """A shared row as {kind, id} — the kind says which table the
    id names ('tool' for every pre-battery row)."""
    if row.item_kind == "battery":
        return {"kind": "battery", "id": row.battery_id}
    return {"kind": "tool", "id": row.tool_id}


def group_state(db: Session, owner_id: uuid.UUID, group: str) -> dict:
    """One group's sharing setup for Settings. A group that was never
    configured reports enabled=False with the catalog default fields —
    the pre-checked starting point for a first save."""
    _require_group(group)
    config = _stored_config(db, owner_id, group)
    if config is None:
        enabled, fields = False, list(DEFAULT_SHARED_FIELDS)
    else:
        enabled, fields = config.enabled, canonical_fields(list(config.fields or []))
    rows = _shared_rows(db, owner_id, group)
    refs = [_item_ref(row) for row in rows]
    # RULES (Package C): the resolved picture alongside the picks —
    # rules with their live match counts, the per-item exclusions,
    # and the set that actually resolves as shared right now.
    facts = inventory_service.list_item_sharing_facts(db, owner_id)
    nodes = inventory_service.owned_locations(db, owner_id)
    resolved = resolve_shared_items(db, owner_id, group, facts=facts)
    resolved_keys = {(r["kind"], r["id"]) for r in resolved}
    return {
        "recipient_group": group,
        "enabled": enabled,
        "fields": fields,
        "shared_tool_ids": [r["id"] for r in refs if r["kind"] == "tool"],
        "shared_battery_ids": [r["id"] for r in refs if r["kind"] == "battery"],
        "shared_items": refs,
        # SETS: each shared set's stored answer to "include the addon
        # pieces too?" (asked at selection time). Attached tools and
        # addon pieces follow this choice in the preview payload.
        "set_choices": [
            {"tool_id": row.tool_id, "include_addons": bool(row.include_addons)}
            for row in rows
            if row.item_kind == "tool" and row.tool_id is not None
        ],
        "rules": [
            _rule_view(
                db, owner_id, rule, facts=facts, nodes=nodes, resolved_keys=resolved_keys
            )
            for rule in _rules(db, owner_id, group)
        ],
        "excluded_items": [
            _item_ref(row) for row in _exclusion_rows(db, owner_id, group)
        ],
        "resolved_items": [
            {"kind": r["kind"], "id": r["id"]} for r in resolved
        ],
        "resolved_count": len(resolved),
    }


def get_overview(db: Session, owner_id: uuid.UUID) -> dict:
    """Both groups' configs + the owner's items (tools AND batteries,
    each marked with its kind) with per-group shared flags — the one
    payload Settings → Sharing renders from."""
    groups = [group_state(db, owner_id, g) for g in RECIPIENT_GROUPS]
    shared_by_item: dict[uuid.UUID, list[str]] = {}
    for state in groups:
        for ref in state["shared_items"]:
            shared_by_item.setdefault(ref["id"], []).append(
                state["recipient_group"]
            )
    items = [
        {**identity, "shared_with": shared_by_item.get(identity["id"], [])}
        for identity in inventory_service.list_item_identities(db, owner_id)
    ]
    # RULE PICKERS (Package C): the vocab the rule editor offers —
    # the owner's own categories, tags, and location tree.
    return {
        "groups": groups,
        "items": items,
        "categories": inventory_service.field_suggestions(
            db, owner_id, "category"
        ),
        "tags": [
            {"id": t["id"], "name": t["name"], "item_count": t["item_count"]}
            for t in inventory_service.list_tags(db, owner_id)
        ],
        "locations": inventory_service.list_location_tree(db, owner_id),
    }


def update_config(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    enabled: bool,
    fields: list[str],
) -> dict:
    """Create or replace the group's config. Fields are stored in
    catalog order with anything outside the catalog dropped (the
    schema already refuses unknown values with a 422)."""
    _require_group(group)
    clean = canonical_fields(fields)
    config = _stored_config(db, owner_id, group)
    if config is None:
        config = models.ShareConfig(
            owner_id=owner_id, recipient_group=group, enabled=enabled, fields=clean
        )
        db.add(config)
    else:
        config.enabled = enabled
        config.fields = clean
    db.commit()
    return group_state(db, owner_id, group)


def set_shared_items(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    tool_ids: list[uuid.UUID],
    battery_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
    set_choices: list[dict] | tuple[dict, ...] = (),
) -> dict:
    """Replace the group's shared item set wholesale — tools and
    batteries in one set. Every id must be one of the owner's own
    items of its kind — a foreign id refuses the whole write
    (nothing partial is applied).

    `set_choices` carries the per-set addon answers for THIS write:
    [{tool_id, include_addons}] for shared tools that are sets. A
    set shared without an explicit choice stores False — consent
    sharing is opt-in: the addons stay home unless the owner said
    "include the addon pieces too?"."""
    _require_group(group)
    unique_tools = list(dict.fromkeys(tool_ids))
    unique_batteries = list(dict.fromkeys(battery_ids))
    choices = {
        uuid.UUID(str(choice["tool_id"])): bool(choice.get("include_addons"))
        for choice in set_choices
    }
    owned_tools = inventory_service.get_owned_tools(db, owner_id, unique_tools)
    if len(owned_tools) != len(unique_tools):
        raise SharingError("One or more tools do not belong to you.")
    owned_batteries = inventory_service.get_owned_batteries(
        db, owner_id, unique_batteries
    )
    if len(owned_batteries) != len(unique_batteries):
        raise SharingError("One or more batteries do not belong to you.")
    # ORM deletes, not a bulk DELETE: every removed share row
    # lands in the owner's change journal (audit trail, 2026-10-19).
    for row in (
        db.query(models.SharedItem)
        .filter(
            models.SharedItem.owner_id == owner_id,
            models.SharedItem.recipient_group == group,
        )
        .all()
    ):
        db.delete(row)
    for tool_id in unique_tools:
        db.add(
            models.SharedItem(
                owner_id=owner_id,
                item_kind="tool",
                tool_id=tool_id,
                recipient_group=group,
                include_addons=choices.get(tool_id, False),
            )
        )
    for battery_id in unique_batteries:
        db.add(
            models.SharedItem(
                owner_id=owner_id,
                item_kind="battery",
                battery_id=battery_id,
                recipient_group=group,
            )
        )
    db.commit()
    return group_state(db, owner_id, group)


# -- rules (Package C) ------------------------------------------------------------
#
# A rule stores a SCOPE, never item ids, and matching happens
# against inventory's per-item facts on every read — that is what
# makes resolution dynamic. The per-item picks in shared_items are
# the 'item' scope; RULE_SCOPES are the scopes that live in
# share_rules.

RULE_SCOPES: tuple[str, ...] = ("category", "location", "tag", "all")


def _norm_category(value: str | None) -> str:
    """Category matching is forgiving of case and padding — the
    owner's own vocabulary, matched the way the importer's learned
    matching normalizes (casefold): 'Wrenches' and 'wrenches ' are
    the same shelf."""
    return (value or "").strip().casefold()


def rule_matched_refs(
    db: Session,
    owner_id: uuid.UUID,
    scope: str,
    scope_value: str,
    scope_ref_id: uuid.UUID | None,
    facts: list[dict] | None = None,
    nodes: list | None = None,
) -> list[dict]:
    """The item refs one rule matches RIGHT NOW: [{kind, id}].

    Shared by tier resolution and peer sharing's withholding rules
    (peer_sharing imports this) — one matcher, two directions.
    `facts`/`nodes` may be passed in when resolving many rules at
    once; each is fetched lazily otherwise. A dangling rule (its
    location node or tag was deleted) matches nothing."""
    if facts is None:
        facts = inventory_service.list_item_sharing_facts(db, owner_id)
    if scope == "all":
        return [{"kind": f["kind"], "id": f["id"]} for f in facts]
    if scope == "category":
        target = _norm_category(scope_value)
        if not target:
            return []
        return [
            {"kind": f["kind"], "id": f["id"]}
            for f in facts
            if _norm_category(f["category"]) == target
        ]
    if scope == "location":
        if scope_ref_id is None:
            return []
        if nodes is None:
            nodes = inventory_service.owned_locations(db, owner_id)
        if scope_ref_id not in {n.id for n in nodes}:
            return []  # dangling rule: the node is gone
        subtree = inventory_service.location_subtree_ids(nodes, scope_ref_id)
        return [
            {"kind": f["kind"], "id": f["id"]}
            for f in facts
            if f["location_id"] in subtree
        ]
    if scope == "tag":
        if scope_ref_id is None:
            return []
        return [
            {"kind": f["kind"], "id": f["id"]}
            for f in facts
            if scope_ref_id in f["tag_ids"]
        ]
    return []


def validate_rule_target(
    db: Session,
    owner_id: uuid.UUID,
    scope: str,
    scope_value: str,
    scope_ref_id: uuid.UUID | None,
    *,
    error: type[ValueError] = SharingError,
) -> tuple[str, uuid.UUID | None]:
    """Normalize + ownership-check a rule write. Returns the
    (scope_value, scope_ref_id) to STORE: for location/tag rules
    the value becomes a display snapshot (node path / tag name) so
    the rule still reads sensibly in the list, while the ref id
    does the actual matching. Raises `error` — the calling
    module's own 4xx type — on anything invalid."""
    if scope not in RULE_SCOPES:
        raise error(f"Unknown rule scope '{scope}'.")
    if scope == "all":
        return "", None
    if scope == "category":
        value = (scope_value or "").strip()
        if not value:
            raise error("A category rule needs a category.")
        return value, None
    if scope_ref_id is None:
        raise error(f"A {scope} rule needs a {scope} to point at.")
    if scope == "location":
        node = inventory_service.get_location_node(db, owner_id, scope_ref_id)
        if node is None:
            raise error("That location doesn't belong to you.")
        nodes = inventory_service.owned_locations(db, owner_id)
        return inventory_service.location_path(nodes, node), node.id
    tag = inventory_service.get_tag(db, owner_id, scope_ref_id)
    if tag is None:
        raise error("That tag doesn't belong to you.")
    return tag.name, tag.id


def rule_label(
    db: Session,
    owner_id: uuid.UUID,
    rule: models.ShareRule | models.PeerShareExclusionRule,
    nodes: list | None = None,
) -> str:
    """The rule's display label, resolved live when the target
    still exists (a renamed node shows its new path) and the
    stored snapshot when it doesn't."""
    if rule.scope == "all":
        return "All inventory"
    if rule.scope == "category":
        return rule.scope_value
    if rule.scope == "location" and rule.scope_ref_id is not None:
        if nodes is None:
            nodes = inventory_service.owned_locations(db, owner_id)
        node = next((n for n in nodes if n.id == rule.scope_ref_id), None)
        if node is not None:
            return inventory_service.location_path(nodes, node)
    if rule.scope == "tag" and rule.scope_ref_id is not None:
        tag = inventory_service.get_tag(db, owner_id, rule.scope_ref_id)
        if tag is not None:
            return tag.name
    return rule.scope_value


def _rule_view(
    db: Session,
    owner_id: uuid.UUID,
    rule: models.ShareRule,
    *,
    facts: list[dict],
    nodes: list,
    resolved_keys: set[tuple[str, uuid.UUID]],
) -> dict:
    matches = rule_matched_refs(
        db,
        owner_id,
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
        "scope_label": rule_label(db, owner_id, rule, nodes),
        "include_addons": bool(rule.include_addons),
        # How many items this rule is ACTUALLY sharing right now:
        # matched and still in the resolved set after exclusions.
        "match_count": sum(
            1 for m in matches if (m["kind"], m["id"]) in resolved_keys
        ),
        "created_at": rule.created_at,
    }


def resolve_shared_items(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    *,
    facts: list[dict] | None = None,
) -> list[dict]:
    """The group's effective shared set RIGHT NOW:
    [{kind, id, include_addons}] = (per-item picks ∪ every rule's
    matches) − exclusions, resolved against the live vault.

    Include-addons precedence for a matched SET: an explicit
    per-item PICK's stored choice wins (it is the more specific
    decision); otherwise any matching rule that says include makes
    it so (OR across rules); default is exclude. Picks come first
    in the result (in pick order), then rule-only matches in rule
    order — the preview reads in that order. Refs whose item no
    longer exists are dropped: resolution only ever names live
    items (a deleted item's pick lingers in shared_items until the
    next settings save, exactly as before)."""
    if facts is None:
        facts = inventory_service.list_item_sharing_facts(db, owner_id)
    live = {(f["kind"], f["id"]) for f in facts}
    nodes = inventory_service.owned_locations(db, owner_id)
    resolved: dict[tuple[str, uuid.UUID], bool] = {}
    picked: set[tuple[str, uuid.UUID]] = set()
    for row in _shared_rows(db, owner_id, group):
        ref = _item_ref(row)
        key = (ref["kind"], ref["id"])
        picked.add(key)
        resolved[key] = bool(row.include_addons)
    for rule in _rules(db, owner_id, group):
        for ref in rule_matched_refs(
            db,
            owner_id,
            rule.scope,
            rule.scope_value,
            rule.scope_ref_id,
            facts=facts,
            nodes=nodes,
        ):
            key = (ref["kind"], ref["id"])
            if key in picked:
                continue  # the pick's own stored choice already decided
            resolved[key] = resolved.get(key, False) or bool(rule.include_addons)
    for row in _exclusion_rows(db, owner_id, group):
        ref = _item_ref(row)
        resolved.pop((ref["kind"], ref["id"]), None)
    return [
        {"kind": kind, "id": item_id, "include_addons": addons}
        for (kind, item_id), addons in resolved.items()
        if (kind, item_id) in live
    ]


def create_rule(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    *,
    scope: str,
    scope_value: str = "",
    scope_ref_id: uuid.UUID | None = None,
    include_addons: bool = False,
) -> dict:
    """Add a rule to a group — or refresh the include-addons answer
    on the identical existing rule (one rule per scope target per
    group is the model; the write is idempotent by target).
    Returns the group's full state."""
    _require_group(group)
    value, ref_id = validate_rule_target(
        db, owner_id, scope, scope_value, scope_ref_id
    )
    existing = next(
        (
            r
            for r in _rules(db, owner_id, group)
            if r.scope == scope
            and r.scope_ref_id == ref_id
            and _norm_category(r.scope_value) == _norm_category(value)
        ),
        None,
    )
    if existing is not None:
        existing.include_addons = bool(include_addons)
    else:
        db.add(
            models.ShareRule(
                owner_id=owner_id,
                recipient_group=group,
                scope=scope,
                scope_value=value,
                scope_ref_id=ref_id,
                include_addons=bool(include_addons),
            )
        )
    db.commit()
    return group_state(db, owner_id, group)


def _owned_rule(
    db: Session, owner_id: uuid.UUID, group: str, rule_id: uuid.UUID
) -> models.ShareRule:
    rule = db.get(models.ShareRule, rule_id)
    if rule is None or rule.owner_id != owner_id or rule.recipient_group != group:
        raise SharingError("That rule doesn't exist for this group.")
    return rule


def update_rule(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    rule_id: uuid.UUID,
    *,
    include_addons: bool | None = None,
    scope_value: str | None = None,
) -> dict:
    """Edit a rule in place: the include-addons answer (any scope)
    and — for category rules — the category text. Retargeting a
    location/tag rule is delete + create (the UI does exactly
    that), which keeps every stored rule's target ownership-checked
    at write time. Returns the group's full state."""
    _require_group(group)
    rule = _owned_rule(db, owner_id, group, rule_id)
    if include_addons is not None:
        rule.include_addons = bool(include_addons)
    if scope_value is not None:
        if rule.scope != "category":
            raise SharingError("Only a category rule's value can be edited.")
        value, _ = validate_rule_target(db, owner_id, "category", scope_value, None)
        rule.scope_value = value
    db.commit()
    return group_state(db, owner_id, group)


def delete_rule(
    db: Session, owner_id: uuid.UUID, group: str, rule_id: uuid.UUID
) -> dict:
    """Remove one rule (ORM delete so the journal captures it).
    Items it was sharing simply stop resolving — nothing else is
    touched. Returns the group's full state."""
    _require_group(group)
    rule = _owned_rule(db, owner_id, group, rule_id)
    db.delete(rule)
    db.commit()
    return group_state(db, owner_id, group)


def set_exclusions(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    tool_ids: list[uuid.UUID],
    battery_ids: list[uuid.UUID],
) -> dict:
    """Replace a group's per-item exclusions wholesale — the same
    contract as set_shared_items: every id must name one of the
    caller's own items (a foreign id refuses the whole write) and
    ORM deletes keep the journal honest. Returns group state."""
    _require_group(group)
    owned_tools = inventory_service.get_owned_tools(db, owner_id, tool_ids)
    if len(owned_tools) != len(set(tool_ids)):
        raise SharingError("One of those tools isn't yours to exclude.")
    owned_batteries = inventory_service.get_owned_batteries(db, owner_id, battery_ids)
    if len(owned_batteries) != len(set(battery_ids)):
        raise SharingError("One of those batteries isn't yours to exclude.")
    for row in _exclusion_rows(db, owner_id, group):
        db.delete(row)
    for tool in owned_tools:
        db.add(
            models.ShareExclusion(
                owner_id=owner_id,
                item_kind="tool",
                tool_id=tool.id,
                recipient_group=group,
            )
        )
    for battery in owned_batteries:
        db.add(
            models.ShareExclusion(
                owner_id=owner_id,
                item_kind="battery",
                battery_id=battery.id,
                recipient_group=group,
            )
        )
    db.commit()
    return group_state(db, owner_id, group)


def sharing_summary(db: Session, user: models.User) -> dict:
    """The at-a-glance sharing picture for the Shared Tools page
    (Package C): per recipient group — sharing on/off and how many
    items resolve as shared RIGHT NOW — plus peer grant counts.
    Read-only; every number comes from the same resolution the
    recipient read path uses, so the panel can never promise more
    than a recipient would actually see (minus the entitlement
    active-set, which only ever removes lapsed items)."""
    groups = []
    for group in RECIPIENT_GROUPS:
        config = _stored_config(db, user.id, group)
        groups.append(
            {
                "recipient_group": group,
                "enabled": bool(config is not None and config.enabled),
                "shared_count": len(resolve_shared_items(db, user.id, group)),
                "rule_count": len(_rules(db, user.id, group)),
            }
        )
    grants = list(
        db.scalars(
            select(models.PeerShare).where(models.PeerShare.owner_id == user.id)
        )
    )
    received = list(
        db.scalars(
            select(models.PeerShare).where(
                (models.PeerShare.viewer_user_id == user.id)
                | (
                    models.PeerShare.viewer_user_id.is_(None)
                    & (models.PeerShare.invited_email == user.email)
                )
            )
        )
    )
    return {
        "groups": groups,
        "peer": {
            "given_accepted": sum(1 for g in grants if g.status == "accepted"),
            "given_pending": sum(1 for g in grants if g.status == "pending"),
            "received_accepted": sum(1 for g in received if g.status == "accepted"),
            "received_pending": sum(1 for g in received if g.status == "pending"),
        },
    }


def _project(tool_view: dict, fields: list[str]) -> dict:
    """One shared tool as the recipient receives it: identity always,
    then each chosen optional field — and nothing else. Money is a
    decimal string and dates ISO, matching the rest of the API."""
    out: dict = {
        "id": str(tool_view["id"]),
        "name": tool_view["name"],
        "brand": tool_view["brand"],
        "model": tool_view["model"],
        "serial_number": tool_view["serial_number"],
    }
    attachments = tool_view.get("attachments") or []
    for field in OPTIONAL_FIELDS:
        if field not in fields:
            continue
        if field == "photos":
            urls = [a["url"] for a in attachments if a.get("kind") in PHOTO_KINDS]
            out["photos"] = {"count": len(urls), "urls": urls}
        elif field == "documents":
            urls = [
                a["url"] for a in attachments if a.get("kind") in DOCUMENT_KINDS
            ]
            out["documents"] = {"count": len(urls), "urls": urls}
        elif field == "custom_fields":
            out["custom_fields"] = tool_view.get("custom_data") or {}
        else:
            value = tool_view.get(field)
            if isinstance(value, Decimal):
                value = str(value)
            elif isinstance(value, date):
                value = value.isoformat()
            out[field] = value
    return out


def build_preview(
    db: Session, owner_id: uuid.UUID, group: str
) -> list[dict]:
    """build_preview_page over the whole set (the original
    contract — kept for the recipient-payload consumers/tests)."""
    page, _total = build_preview_page(db, owner_id, group, limit=None)
    return page


def build_preview_page(
    db: Session,
    owner_id: uuid.UUID,
    group: str,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """The exact payload a connected recipient in `group` receives:
    the owner's shared items for that group, fields filtered by the
    group's config. Sharing off (or never configured) = empty list —
    the recipient receives nothing.

    Batteries share under the SAME field rules as tools. Their
    entries carry kind='battery' so a recipient can tell the kinds
    apart; tool entries are UNCHANGED (no kind key) — the tool
    payload shape is pinned by the consent contract the recipients
    already consume.

    Paging (step-4 fix D4): resolution still runs over the whole
    set — picks ∪ rules − exclusions and the active-set filter are
    set-level correctness, never paged — but SERIALIZATION (the
    expensive half: per-row tags, attachments, presigned URLs) now
    covers only the requested page. Returns (page, total); with
    limit=None the page is the whole set (the pre-D4 behavior)."""
    _require_group(group)
    config = _stored_config(db, owner_id, group)
    if config is None or not config.enabled:
        return [], 0
    fields = canonical_fields(list(config.fields or []))
    # Entitlement standing (billing): inactive assets never leave on
    # a sharing surface — the shared active-set filter decides, one
    # half per kind.
    active_tools = entitlements.active_tool_ids(db, owner_id)
    active_batteries = entitlements.active_battery_ids(db, owner_id)
    # RULES (Package C): the recipient set is the RESOLVED set —
    # picks ∪ rule matches − exclusions — computed live, so a tool
    # bought into a shared category yesterday is already here and a
    # tool moved out is already gone. Each entry carries its
    # resolved include-addons answer for sets. The cheap pass below
    # (active filter + BULK existence — two id queries, never a
    # per-ref lookup: at 10k resolved refs the lookups alone cost
    # seconds) decides the total; only the page's rows are loaded
    # for serialization.
    resolved = resolve_shared_items(db, owner_id, group)
    tool_ids = [r["id"] for r in resolved if r["kind"] != "battery"]
    battery_ids = [r["id"] for r in resolved if r["kind"] == "battery"]
    existing_tools = inventory_service.existing_tool_ids(db, owner_id, tool_ids)
    existing_batteries = inventory_service.existing_battery_ids(
        db, owner_id, battery_ids
    )
    visible_refs: list[dict] = []
    for ref in resolved:
        if ref["kind"] == "battery":
            if active_batteries is not None and ref["id"] not in active_batteries:
                continue
            if ref["id"] not in existing_batteries:
                continue  # deleted between sharing and preview; skip quietly
        else:
            if active_tools is not None and ref["id"] not in active_tools:
                continue
            if ref["id"] not in existing_tools:
                continue  # deleted between sharing and preview; skip quietly
        visible_refs.append(ref)
    total = len(visible_refs)
    page_refs = (
        visible_refs[offset:]
        if limit is None
        else visible_refs[offset : offset + limit]
    )
    preview = []
    for ref in page_refs:
        item = (
            inventory_service.get_battery(db, owner_id, ref["id"])
            if ref["kind"] == "battery"
            else inventory_service.get_tool(db, owner_id, ref["id"])
        )
        if item is None:
            continue  # deleted mid-request; the total was honest at read time
        if ref["kind"] == "battery":
            view = inventory_service.serialize_battery(db, item)
            preview.append({**_project(view, fields), "kind": "battery"})
        else:
            entry = _project(inventory_service.serialize_tool(db, item), fields)
            if item.is_set:
                # SETS: the shared set carries its resolved addon
                # choice; members resolve through inventory's shared
                # service (attached tools follow the choice).
                entry["set"] = _set_preview(
                    db, item, bool(ref["include_addons"]), fields
                )
            preview.append(entry)
    return preview, total


def _piece_identity(piece) -> dict:
    """A set piece as a sharing recipient sees it: identity only —
    pieces carry no price/notes surface in sharing (core pieces have
    no price at all; addon prices are the owner's business)."""
    return {
        "name": piece.name,
        "part_number": piece.part_number,
        "serial_number": piece.serial_number,
        "status": piece.status,
    }


def _set_preview(db: Session, tool, include_addons: bool, fields: list[str]) -> dict:
    members = inventory_service.resolve_set_members(db, tool, include_addons)
    return {
        "include_addons": include_addons,
        "core_pieces": [_piece_identity(p) for p in members["core_pieces"]],
        "addon_pieces": [_piece_identity(p) for p in members["addon_pieces"]],
        "attached_tools": [
            _project(inventory_service.serialize_tool(db, t), fields)
            for t in members["attached_tools"]
        ],
    }
