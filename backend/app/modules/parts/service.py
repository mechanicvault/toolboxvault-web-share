"""Used Parts service: locations tree, part records, search, and the
convert-to-tool copy.

SERVICE INTERFACE (stable; bump manifest version on change):
  - locations: list_locations / create_location / update_location /
    delete_location (reassign-or-detach, never a silent orphan)
  - parts: create_part / get_part / list_parts (search + subtree
    filter) / update_part / delete_part / serialize_part
  - convert_to_tool(db, user, part_id) — one-way COPY into Asset
    Inventory through inventory's service interface
  - stats(db, owner_id) -> {"parts_count", "total_units"}
  - export_rows(db, owner_id) — the data export's parts.json

Custom-field values ride the shared engine in inventory's
custom_fields (item_type 'part'): definitions are the owner's own,
validation is identical to tools', and the axis never leaks — 'part'
definitions don't apply to tools, tool definitions don't apply to
parts, and 'both' keeps its original tools+batteries meaning.

Parts do NOT count toward the entitlement item cap (owner-vetoable
judgment call, 2026-10-19): billing's active set reads tools +
batteries only, and nothing in this module consults the cap for
parts themselves. The one place the cap appears is convert_to_tool's
ROUTE, which creates a real tool and so passes through the same
can_add_tool doorway as the inventory create route.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.modules.core import journal
from app.modules.inventory import custom_fields
from app.modules.parts import attachments as part_attachments
from app.modules.parts import models, schemas


class PartError(ValueError):
    """Friendly refusal. Routes -> 422."""


class PartNotFound(PartError):
    """Missing OR someone else's — ids never leak existence. -> 404."""


# -- locations -------------------------------------------------------------


def owned_locations(db: Session, owner_id: uuid.UUID) -> list[models.PartLocation]:
    return list(
        db.scalars(
            select(models.PartLocation)
            .where(models.PartLocation.owner_id == owner_id)
            .order_by(models.PartLocation.name)
        )
    )


def get_location(
    db: Session, owner_id: uuid.UUID, location_id: uuid.UUID
) -> models.PartLocation | None:
    location = db.get(models.PartLocation, location_id)
    if location is None or location.owner_id != owner_id:
        return None
    return location


def _children_map(locations: list[models.PartLocation]) -> dict[uuid.UUID, list[uuid.UUID]]:
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for location in locations:
        if location.parent_id is not None:
            children.setdefault(location.parent_id, []).append(location.id)
    return children


def subtree_ids(
    locations: list[models.PartLocation], root_id: uuid.UUID
) -> set[uuid.UUID]:
    """root + every descendant id, from an already-loaded owner tree."""
    children = _children_map(locations)
    found: set[uuid.UUID] = set()
    stack = [root_id]
    while stack:
        node = stack.pop()
        if node in found:
            continue
        found.add(node)
        stack.extend(children.get(node, []))
    return found


def _is_descendant(
    locations: list[models.PartLocation], node_id: uuid.UUID, candidate_id: uuid.UUID
) -> bool:
    """True when candidate sits in node's subtree (node included) —
    the cycle test for moves and the validity test for reassign
    targets."""
    return candidate_id in subtree_ids(locations, node_id)


def location_path(
    locations: list[models.PartLocation], location: models.PartLocation
) -> str:
    """'Warehouse / Aisle 3 / Bin 12' — root-to-node names."""
    by_id = {loc.id: loc for loc in locations}
    names: list[str] = []
    node: models.PartLocation | None = location
    guard = 0
    while node is not None and guard <= len(locations):
        names.append(node.name)
        node = by_id.get(node.parent_id) if node.parent_id else None
        guard += 1
    return " / ".join(reversed(names))


def serialize_location(
    db: Session,
    owner_id: uuid.UUID,
    location: models.PartLocation,
    locations: list[models.PartLocation] | None = None,
) -> dict:
    locations = owned_locations(db, owner_id) if locations is None else locations
    own = db.scalar(
        select(func.count(models.Part.id)).where(
            models.Part.location_id == location.id,
            models.Part.owner_id == owner_id,
        )
    )
    rollup = db.scalar(
        select(func.count(models.Part.id)).where(
            models.Part.location_id.in_(subtree_ids(locations, location.id)),
            models.Part.owner_id == owner_id,
        )
    )
    return {
        "id": location.id,
        "name": location.name,
        "level": location.level,
        "parent_id": location.parent_id,
        "own_count": int(own or 0),
        "part_count": int(rollup or 0),
        "created_at": location.created_at,
        "updated_at": location.updated_at,
    }


def list_locations(db: Session, owner_id: uuid.UUID) -> list[dict]:
    locations = owned_locations(db, owner_id)
    return [serialize_location(db, owner_id, loc, locations) for loc in locations]


def _check_level(level: str) -> str:
    level = (level or "other").strip().lower()
    if level not in models.LOCATION_LEVELS:
        raise PartError(
            f"Location level must be one of: {', '.join(models.LOCATION_LEVELS)}."
        )
    return level


def create_location(
    db: Session, owner_id: uuid.UUID, payload: schemas.PartLocationCreate
) -> models.PartLocation:
    if payload.parent_id is not None and (
        get_location(db, owner_id, payload.parent_id) is None
    ):
        raise PartNotFound("That parent location isn't yours.")
    location = models.PartLocation(
        owner_id=owner_id,
        name=payload.name.strip(),
        level=_check_level(payload.level),
        parent_id=payload.parent_id,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def update_location(
    db: Session,
    owner_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: schemas.PartLocationUpdate,
) -> models.PartLocation | None:
    location = get_location(db, owner_id, location_id)
    if location is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        location.name = data["name"].strip()
    if "level" in data and data["level"] is not None:
        location.level = _check_level(data["level"])
    if "parent_id" in data:
        new_parent = data["parent_id"]
        if new_parent is not None:
            if get_location(db, owner_id, new_parent) is None:
                raise PartNotFound("That parent location isn't yours.")
            locations = owned_locations(db, owner_id)
            if _is_descendant(locations, location_id, new_parent):
                raise PartError(
                    "A location can't move under itself or one of its "
                    "own sub-locations — that would loop the tree."
                )
        location.parent_id = new_parent
    db.commit()
    db.refresh(location)
    return location


def delete_location(
    db: Session,
    owner_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: schemas.PartLocationDelete,
) -> bool:
    """Delete one node. A node holding parts or children is never
    orphaned silently: the caller must reassign (everything moves
    to the target) or detach (children step up to this node's
    parent, parts become unfiled)."""
    location = get_location(db, owner_id, location_id)
    if location is None:
        return False
    locations = owned_locations(db, owner_id)
    children = [
        loc for loc in locations if loc.parent_id == location_id
    ]
    filed_parts = list(
        db.scalars(
            select(models.Part).where(
                models.Part.location_id == location_id,
                models.Part.owner_id == owner_id,
            )
        )
    )
    if children or filed_parts:
        if payload.reassign_to_id is not None:
            target = get_location(db, owner_id, payload.reassign_to_id)
            if target is None:
                raise PartNotFound("That reassign location isn't yours.")
            if _is_descendant(locations, location_id, target.id):
                raise PartError(
                    "Parts and sub-locations can't move into the "
                    "location being deleted or one of its own "
                    "sub-locations."
                )
            for child in children:
                child.parent_id = target.id
            for part in filed_parts:
                part.location_id = target.id
        elif payload.detach:
            for child in children:
                child.parent_id = location.parent_id
            for part in filed_parts:
                part.location_id = None
        else:
            bits = []
            if filed_parts:
                bits.append(
                    f"{len(filed_parts)} part{'s' if len(filed_parts) != 1 else ''}"
                )
            if children:
                bits.append(
                    f"{len(children)} sub-location{'s' if len(children) != 1 else ''}"
                )
            raise PartError(
                f"“{location.name}” still holds {' and '.join(bits)} — "
                "move them to another location, or detach them, before "
                "deleting it. Nothing was deleted."
            )
    db.delete(location)
    db.commit()
    return True


# -- parts -------------------------------------------------------------------


def _serialize_attachments(part: models.Part) -> list[dict]:
    """Stored attachments keep only keys (+ metadata); read URLs are
    minted at serialize time because presigned URLs expire — the
    same contract as inventory's serializer."""
    view = []
    for item in part.attachments or []:
        if not isinstance(item, dict) or "key" not in item:
            continue
        view.append(
            {
                "key": item["key"],
                "filename": item.get("filename", ""),
                "kind": item.get("kind", ""),
                "content_type": item.get("content_type", ""),
                "size_bytes": item.get("size_bytes", 0),
                "uploaded_at": item.get("uploaded_at"),
                "url": storage.presigned_get_url(item["key"]),
            }
        )
    return view


def serialize_part(
    db: Session,
    part: models.Part,
    locations: list[models.PartLocation] | None = None,
) -> dict:
    from app.modules.parts import pool

    locations = (
        owned_locations(db, part.owner_id) if locations is None else locations
    )
    location_view = None
    if part.location_id is not None:
        node = next((loc for loc in locations if loc.id == part.location_id), None)
        if node is not None:
            location_view = {
                "id": node.id,
                "name": node.name,
                "level": node.level,
                "path": location_path(locations, node),
            }
    settings = pool.settings_for(db, part.owner_id)
    resolved = pool.resolve_visibility(part, settings)
    return {
        "id": part.id,
        "title": part.title,
        "quantity": part.quantity,
        "condition": part.condition,
        "notes": part.notes,
        "location_id": part.location_id,
        "location": location_view,
        "custom_data": part.custom_data,
        "attachments": _serialize_attachments(part),
        "converted_tool_id": part.converted_tool_id,
        # Community pool (2026-10-19): the standard vehicle fields,
        # the raw overrides, and the RESOLVED state — is_public is
        # the live truth (resolved public AND the pool switched on
        # AND the seller currently publishable is a READ-time rule
        # of the pool surface; here it is resolved + pool on).
        "year": part.year,
        "make": part.make,
        "model": part.model,
        "engine": part.engine,
        "category": part.category,
        "asking_price": part.asking_price,
        "public_area_label": part.public_area_label,
        "visibility_override": part.visibility,
        "show_phone_override": part.show_phone_override,
        "visibility": resolved,
        "is_public": bool(resolved == "public" and pool.pool_enabled(db)),
        "created_at": part.created_at,
        "updated_at": part.updated_at,
    }


def get_part(db: Session, owner_id: uuid.UUID, part_id: uuid.UUID) -> models.Part | None:
    part = db.get(models.Part, part_id)
    if part is None or part.owner_id != owner_id:
        return None
    return part


def _validate_location(db: Session, owner_id: uuid.UUID, location_id) -> None:
    if location_id is not None and get_location(db, owner_id, location_id) is None:
        raise PartNotFound("That location isn't yours.")


def create_part(
    db: Session, owner_id: uuid.UUID, payload: schemas.PartCreate
) -> models.Part:
    _validate_location(db, owner_id, payload.location_id)
    data = payload.model_dump()
    data["custom_data"] = custom_fields.validate_custom_data(
        db, owner_id, payload.custom_data, item_type="part"
    )
    part = models.Part(owner_id=owner_id, **data)
    db.add(part)
    db.commit()
    db.refresh(part)
    return part


def update_part(
    db: Session,
    owner_id: uuid.UUID,
    part_id: uuid.UUID,
    payload: schemas.PartUpdate,
) -> models.Part | None:
    part = get_part(db, owner_id, part_id)
    if part is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "location_id" in data:
        _validate_location(db, owner_id, data["location_id"])
    if data.get("custom_data") is not None:
        data["custom_data"] = custom_fields.validate_custom_data(
            db, owner_id, data["custom_data"], item_type="part"
        )
    # Fields where null is an instruction, not an omission: unfile
    # (location_id) and the pool's clearable values/overrides
    # (year, asking_price, public_area_label, visibility,
    # show_phone_override).
    clearable = (
        "location_id",
        "year",
        "asking_price",
        "public_area_label",
        "visibility",
        "show_phone_override",
    )
    for key, value in data.items():
        if value is None and key not in clearable:
            continue  # partial update: null means "leave it"
        setattr(part, key, value)
    db.commit()
    db.refresh(part)
    return part


def delete_part(db: Session, owner_id: uuid.UUID, part_id: uuid.UUID) -> bool:
    part = get_part(db, owner_id, part_id)
    if part is None:
        return False
    # Photos tombstoned for the retention window (audit trail):
    # a restore brings the part back with its pictures.
    journal.retire_record_files(db, owner_id, part, entity_type="part")
    db.delete(part)
    db.commit()
    return True


def _searchable_values(part: models.Part, searchable_ids: set[str]) -> list[str]:
    """The custom values search can see: values of the owner's
    SEARCHABLE 'part' definitions (the tools' search-vector rule,
    applied to the values this record actually carries)."""
    return [
        str(value).lower()
        for key, value in (part.custom_data or {}).items()
        if key in searchable_ids and value is not None
    ]


def list_parts(
    db: Session,
    owner_id: uuid.UUID,
    q: str | None = None,
    location_id: uuid.UUID | None = None,
    condition: str | None = None,
    limit: int = 200,
) -> list[models.Part]:
    """The owner's parts, newest-touched first.

    Search is dialect-free Python (title + notes + condition +
    searchable custom values): every term must hit somewhere — the
    websearch AND semantics the inventory search documents. Part
    counts per owner are shelf-scale, and one code path behaving
    identically on Postgres and SQLite beats a second tsvector
    trigger to keep in sync.

    location_id filters by SUBTREE: filing under 'Warehouse' finds
    everything in its aisles and bins."""
    stmt = (
        select(models.Part)
        .where(models.Part.owner_id == owner_id)
        .order_by(models.Part.updated_at.desc())
    )
    if location_id is not None:
        locations = owned_locations(db, owner_id)
        if get_location(db, owner_id, location_id) is None:
            return []
        stmt = stmt.where(
            models.Part.location_id.in_(subtree_ids(locations, location_id))
        )
    if condition:
        stmt = stmt.where(models.Part.condition == condition)
    cap = max(1, min(limit, 500))
    rows = list(db.scalars(stmt.limit(5000)))
    terms = [t.lower() for t in (q or "").split() if t]
    if terms:
        searchable_ids = {
            str(d.id)
            for d in custom_fields.list_definitions(db, owner_id, "part")
            if d.searchable
        }
        matched = []
        for part in rows:
            haystacks = [
                part.title.lower(),
                (part.notes or "").lower(),
                (part.condition or "").lower(),
                *_searchable_values(part, searchable_ids),
            ]
            if all(any(term in field for field in haystacks) for term in terms):
                matched.append(part)
        rows = matched
    return rows[:cap]


# -- convert to tool ---------------------------------------------------------

# Part-definition name slugs that feed a tool's CORE fields when
# present (the brief's "brand/model/etc. from matching custom fields
# when present"): a spare catalogued with Make/Model/Serial customs
# lands in inventory with those as its brand/model/serial. First
# slug present wins per field.
_CORE_FIELD_SLUGS: dict[str, tuple[str, ...]] = {
    "brand": ("brand", "make"),
    "model": ("model",),
    "serial_number": ("serial_number", "serial"),
    "category": ("category",),
}


def convert_to_tool(db: Session, owner_id: uuid.UUID, part_id: uuid.UUID):
    """One-way COPY of a part into Asset Inventory as a normal tool.

    Through inventory's service interface (create_tool + its attach
    flow) — this module never writes a tool row itself. The part
    REMAINS, stamped with converted_tool_id (its "copied to
    inventory" link).

    Mapping: title -> name, quantity -> quantity, condition ->
    condition, notes -> notes. Custom values map two ways:
    (1) part fields whose NAME SLUG names a tool core field
    (brand/make, model, serial_number/serial, category) feed that
    field; (2) every other value whose slug matches one of the
    owner's TOOL definitions is carried into the tool's custom_data
    under that definition. Photos are copied object-to-object into
    the tool's namespace, then attached through inventory's flow —
    a photo that fails to copy is skipped (its bytes still live on
    the part; nothing is lost).
    """
    from app.modules.inventory import attachments as inventory_attachments
    from app.modules.inventory import schemas as inventory_schemas
    from app.modules.inventory import service as inventory_service

    part = get_part(db, owner_id, part_id)
    if part is None:
        return None

    part_defs = {
        str(d.id): d
        for d in custom_fields.list_definitions(db, owner_id, "part")
    }
    tool_defs_by_slug = {
        d.name: d
        for d in custom_fields.list_definitions(db, owner_id, "tool")
    }
    values_by_slug: dict[str, object] = {}
    for key, value in (part.custom_data or {}).items():
        definition = part_defs.get(str(key))
        if definition is not None and value is not None:
            values_by_slug[definition.name] = value

    core: dict[str, str] = {}
    consumed: set[str] = set()
    for field_name, slugs in _CORE_FIELD_SLUGS.items():
        for slug in slugs:
            if slug in values_by_slug:
                core[field_name] = str(values_by_slug[slug])
                consumed.add(slug)
                break

    tool_custom: dict[str, object] = {}
    for slug, value in values_by_slug.items():
        if slug in consumed:
            continue
        tool_def = tool_defs_by_slug.get(slug)
        if tool_def is not None:
            tool_custom[str(tool_def.id)] = value

    tool = inventory_service.create_tool(
        db,
        owner_id,
        inventory_schemas.ToolCreate(
            name=part.title,
            brand=core.get("brand", ""),
            model=core.get("model", ""),
            serial_number=core.get("serial_number", ""),
            condition=part.condition,
            category=core.get("category", ""),
            notes=part.notes,
            quantity=part.quantity,
            custom_data=tool_custom,
        ),
    )

    for attachment in part.attachments or []:
        if not isinstance(attachment, dict) or attachment.get("kind") != "photo":
            continue
        try:
            dest_key = part_attachments.copy_photo_for_tool(
                owner_id, tool.id, attachment
            )
            inventory_attachments.attach_file(
                db,
                owner_id,
                tool.id,
                inventory_schemas.AttachRequest(
                    key=dest_key, filename=attachment.get("filename", "")
                ),
            )
        except Exception:
            # Best-effort per photo (see docstring): the part keeps
            # its copy, the tool is complete without it.
            continue

    part.converted_tool_id = tool.id
    db.commit()
    db.refresh(part)
    return part, tool


# -- stats + export ------------------------------------------------------------


def stats(db: Session, owner_id: uuid.UUID) -> dict:
    """The home-stat numbers: part entries on the shelf, and the
    total units they stand for."""
    count = db.scalar(
        select(func.count(models.Part.id)).where(models.Part.owner_id == owner_id)
    )
    units = db.scalar(
        select(func.coalesce(func.sum(models.Part.quantity), 0)).where(
            models.Part.owner_id == owner_id
        )
    )
    return {"parts_count": int(count or 0), "total_units": int(units or 0)}


def export_rows(db: Session, owner_id: uuid.UUID) -> dict:
    """The data export's parts.json: the location tree (flat, with
    parent links + paths) and every part, attachments as stored
    metadata (core's export fetches the photo files into the
    archive itself, like tools/batteries)."""
    locations = owned_locations(db, owner_id)
    parts = list(
        db.scalars(
            select(models.Part)
            .where(models.Part.owner_id == owner_id)
            .order_by(models.Part.created_at)
        )
    )
    from app.modules.parts import pool as _pool

    settings = _pool.settings_for(db, owner_id)
    return {
        "pool_settings": (
            {
                "default_visibility": settings.default_visibility,
                "category_visibility": dict(settings.category_visibility or {}),
            }
            if settings is not None
            else None
        ),
        "locations": [
            {
                "id": str(loc.id),
                "name": loc.name,
                "level": loc.level,
                "parent_id": str(loc.parent_id) if loc.parent_id else None,
                "path": location_path(locations, loc),
            }
            for loc in locations
        ],
        "parts": [
            {
                "id": str(part.id),
                "title": part.title,
                "quantity": part.quantity,
                "condition": part.condition,
                "notes": part.notes,
                "location_id": str(part.location_id) if part.location_id else None,
                "location_path": (
                    location_path(
                        locations,
                        next(
                            loc for loc in locations if loc.id == part.location_id
                        ),
                    )
                    if part.location_id is not None
                    else None
                ),
                "custom_data": part.custom_data,
                # Community pool facts (2026-10-19): the standard
                # vehicle fields, category, price, and overrides —
                # a backup that dropped them would unpublish the
                # shelf on restore.
                "year": part.year,
                "make": part.make,
                "model": part.model,
                "engine": part.engine,
                "category": part.category,
                "asking_price": (
                    str(part.asking_price) if part.asking_price is not None else None
                ),
                "public_area_label": part.public_area_label,
                "visibility": part.visibility,
                "show_phone_override": part.show_phone_override,
                "attachments": [
                    {k: v for k, v in item.items()}
                    for item in part.attachments or []
                    if isinstance(item, dict)
                ],
                "converted_tool_id": (
                    str(part.converted_tool_id) if part.converted_tool_id else None
                ),
                "created_at": part.created_at,
                "updated_at": part.updated_at,
            }
            for part in parts
        ],
    }
