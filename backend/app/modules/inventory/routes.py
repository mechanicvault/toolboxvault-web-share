"""Inventory module routes. HTTP layer only — logic lives in service.py.

ENTITLEMENTS (billing module): the owner's own list/search/detail
SHOW inactive tools flagged `active: false` (greyed in the UI,
upgrade note) — hiding a person's tools from them would be hostile;
stats and every sharing surface EXCLUDE them. The shared filter is
billing's active_tool_ids — one function, every surface. While
enforcement is off (the launch switch), it returns None and every
behavior is byte-identical to before billing existed."""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.db import get_db
from app.core.deps import CurrentUser, require_module
from app.modules.billing import ai_service, entitlements, wallet
from app.modules.inventory import (
    attachments,
    custom_fields,
    drawer_lookup,
    duplicates,
    history,
    import_routes,
    poster,
    sales,
    schemas,
    search,
    service,
    smart_search,
    thumbs,
)

router = APIRouter()

# Inventory is a FEATURE module (module doctrine, owner 2026-10-18):
# every route below is gated on the module being effective for the
# caller via core's require_module dependency — the operator's
# assignment (seeded defaults: mechanic_technician only) plus the
# global switch. Union semantics live in the assignment: an account
# holding any assigned group passes. The pre-doctrine version of
# this gate was require_account_type("mechanic_technician"); the
# seeded matrix reproduces it exactly. (The module health check
# below stays ungated.)
_inventory_module = require_module("inventory")


@router.get("/health", response_model=dict[str, str])
def module_health() -> dict[str, str]:
    return {"module": "inventory", "status": "ok"}


def _assert_not_duplicate(
    db: Session,
    user: CurrentUser,
    kind: str,
    *,
    brand: str,
    model: str,
    serials: list[str],
    upc: str,
    force: bool,
) -> None:
    """Duplicate detection (wave 4, deterministic): same
    normalized brand+model AND (same serial OR same UPC) refuses
    the create with 409 {code: possible_duplicate} unless the
    caller confirmed with force=true. Brand+model alone never
    blocks — see inventory/duplicates.py."""
    if force:
        return
    found = duplicates.find_duplicates(
        db, user.id, kind, brand=brand, model=model, serials=serials, upc=upc
    )
    if found:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "possible_duplicate",
                "message": "You already have one like this in your vault.",
                "existing": found,
            },
        )


def _as_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


def _preinstalled_409(exc: ValueError) -> HTTPException:
    """A manager operation refused because the category is a
    preinstalled starter (owner spec 2026-10-25): a 409 carrying
    the machine-readable code `category_preinstalled` — the same
    refusal shape as the star cap's, so the UI branches on the
    code, never the copy."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "category_preinstalled", "message": str(exc)},
    )


def _as_upload_http(exc: ValueError) -> HTTPException:
    """Attachment-flow errors: a missing/foreign record is a 404
    (deep audit F4-03 — every sibling endpoint's shape); everything
    else from the upload flow stays a 422."""
    if isinstance(exc, attachments.RecordNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return _as_422(exc)


def _dealer_visible(db: Session, user: CurrentUser) -> bool:
    """Whether the dealers module is effective for THIS caller. When
    it isn't, dealer tags hide on every inventory payload (the stored
    values are preserved server-side). Computed per request like
    every module-control answer — no caching."""
    from app.modules.core import module_control

    return module_control.effective_for_user(db, "dealers", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester)


def _annotated(db: Session, user: CurrentUser, tools) -> list[dict]:
    """Serialize the owner's tools with their entitlement standing:
    active set None (enforcement off / unlimited / within limit)
    means every tool reads active. The whole page serializes
    against ONE serialize_context prefetch (scale fix, 2026-10-26)
    — the per-row lookups are batched, the payload is unchanged."""
    tools = list(tools)
    active_ids = entitlements.active_tool_ids(db, user.id)
    dealer_visible = _dealer_visible(db, user)
    ctx = service.serialize_context(db, tools=tools, dealer_visible=dealer_visible)
    return [
        service.serialize_tool(
            db,
            t,
            active=active_ids is None or t.id in active_ids,
            dealer_visible=dealer_visible,
            ctx=ctx,
        )
        for t in tools
    ]


def _annotated_batteries(db: Session, user: CurrentUser, batteries) -> list[dict]:
    """The battery twin of _annotated: same entitlement annotation,
    from the battery half of the shared active set."""
    batteries = list(batteries)
    active_ids = entitlements.active_battery_ids(db, user.id)
    dealer_visible = _dealer_visible(db, user)
    ctx = service.serialize_context(
        db, batteries=batteries, dealer_visible=dealer_visible
    )
    return [
        service.serialize_battery(
            db,
            b,
            active=active_ids is None or b.id in active_ids,
            dealer_visible=dealer_visible,
            ctx=ctx,
        )
        for b in batteries
    ]


def _location_filter(
    db: Session, owner_id: uuid.UUID, location_id: uuid.UUID | None
) -> set[uuid.UUID] | None:
    """The subtree id set for a ?location_id= tree filter (Package
    B): the node plus every descendant — filtering by a place shows
    everything under it. A node that isn't the caller's yields an
    empty set (nothing matches), never an error or a leak."""
    if location_id is None:
        return None
    nodes = service.owned_locations(db, owner_id)
    if service.get_location_node(db, owner_id, location_id) is None:
        return set()
    return service.location_subtree_ids(nodes, location_id)


def _create_initial_schedule(
    db: Session,
    user: CurrentUser,
    *,
    item_kind: str,
    item_id: uuid.UUID,
    schedule: schemas.InitialSchedule | None,
) -> None:
    """The item form's optional first maintenance schedule (Package
    B): created through the maintenance module's own service once
    the item exists. The schedule's shape is validated BEFORE the
    item is saved (see the create/update routes), so reaching this
    call means creation should succeed; its errors still surface as
    a friendly 422 rather than a 500."""
    if schedule is None:
        return
    from app.modules.core import module_control
    from app.modules.maintenance import service as maintenance_service

    if not module_control.effective_for_user(
        db, "maintenance", user.account_types, user_id=user.id, tier=user.tier, beta_tester=user.beta_tester
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Maintenance schedules need the Repairs, Warranty & "
                "Maintenance module turned on for your account."
            ),
        )
    try:
        maintenance_service.create_schedule(
            db,
            user,
            item_kind=item_kind,
            item_id=item_id,
            kind=schedule.kind,
            label=schedule.label,
            interval_days=schedule.interval_days,
            due_date=schedule.due_date,
            last_done_at=schedule.last_done_at,
        )
    except maintenance_service.MaintenanceError as exc:
        raise _as_422(exc)


def _validate_initial_schedule(
    schedule: schemas.InitialSchedule | None,
) -> None:
    """Pre-flight the form's schedule BEFORE the item save, so a
    bad schedule (no interval and no due date) fails the whole save
    instead of leaving a saved item with a refused schedule."""
    if schedule is None:
        return
    if schedule.interval_days is None and schedule.due_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Give the maintenance schedule an interval or a due "
                "date — otherwise it can never come due."
            ),
        )


# Sort keys for the paged searches (Package B's menu). The
# pattern keeps a typo'd sort a loud 422, never a silent default.
_SORT_PATTERN = "^(" + "|".join(search.SORT_KEYS) + ")$"


# -- photo renditions (F3-12) ---------------------------------------------
# Capability-URL route, deliberately NOT behind the module gate or a
# bearer token: an <img> tag cannot send Authorization, and the HMAC
# signature (key + width + 7-day expiry, see thumbs.py) is the same
# access model as the presigned GET URLs the payload already carries.
@router.get("/thumb/{width}")
def photo_thumb(
    width: int,
    k: str = Query(default="", max_length=500),
    e: int = Query(default=0),
    s: str = Query(default="", max_length=64),
):
    if not thumbs.verify(k, width, e, s):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    data = thumbs.rendition(k, width)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            # The URL itself expires in 7 days; browsers/CDN may
            # cache the rendition inside that window.
            "Cache-Control": "private, max-age=604800, immutable",
        },
    )


# -- search (before /{tool_id} so "search" isn't parsed as an id) ---------
_STANDING_PATTERN = "^(in_service|broken|in_repair|lost|stolen|sold)$"


def _smart(response: Response, db: Session, user: CurrentUser, q, smart: bool):
    """Smart search (wave 4): parse the query line into the
    filter set; returns the parsed dict or None. The chips ride
    the X-Search-Chips header so the UI can show what was
    understood ("Searching for: …")."""
    if not smart or not q:
        return None
    parsed = smart_search.parse_smart_query(db, user.id, q)
    import json as _json

    response.headers["X-Search-Chips"] = _json.dumps(parsed["chips"])
    return parsed


@router.get("/search", response_model=list[schemas.ToolPublic])
def search_tools(
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = None,
    tag_id: uuid.UUID | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_replacement: Decimal | None = None,
    max_replacement: Decimal | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    location_id: uuid.UUID | None = None,
    standing: str | None = Query(default=None, pattern=_STANDING_PATTERN),
    warranty: str | None = Query(
        default=None,
        pattern="^(in_warranty|expiring_soon|expired|unknown|due)$",
    ),
    dealer_id: uuid.UUID | None = None,
    smart: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None, pattern=_SORT_PATTERN),
    sort_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Server-side sorted + paged over the owner's whole filtered
    set (step-4 fix D2). The full match count rides the
    X-Total-Count header; the body stays the bare list it has
    always been. `standing` filters the standing column exactly;
    `dealer_id` filters the dealer tag exactly (intermingling);
    `smart=true` first runs the deterministic query parser
    (inventory/smart_search.py) — explicit params always win
    over parsed ones."""
    parsed = _smart(response, db, user, q, smart)
    if parsed is not None:
        pf = parsed["filters"]
        q = parsed["text"] or None
        category = category if category is not None else pf["category"]
        standing = standing if standing is not None else pf["standing"]
        location = location if location is not None else pf["location"]
        if tag_id is None and pf["tag_id"]:
            tag_id = uuid.UUID(pf["tag_id"])
        if min_price is None and pf["min_price"]:
            min_price = Decimal(pf["min_price"])
        if max_price is None and pf["max_price"]:
            max_price = Decimal(pf["max_price"])
    tools, total = search.search_tools_paged(
        db,
        user.id,
        q=q,
        category=category,
        min_price=min_price,
        max_price=max_price,
        min_replacement=min_replacement,
        max_replacement=max_replacement,
        date_from=date_from,
        date_to=date_to,
        location=location,
        location_ids=_location_filter(db, user.id, location_id),
        standing=standing,
        warranty=warranty,
        dealer_id=dealer_id,
        limit=limit,
        offset=offset,
        sort=sort,
        sort_dir=sort_dir,
        only_tool_ids=(
            service.tool_ids_with_tag(db, user.id, tag_id)
            if tag_id is not None
            else None
        ),
    )
    response.headers["X-Total-Count"] = str(total)
    return _annotated(db, user, tools)


# -- unified asset search (All view): tools + batteries, each row
#    marked with its item_kind --------------------------------------
@router.get("/search/all", response_model=list[schemas.AssetSearchItem])
def search_all_assets(
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = None,
    tag_id: uuid.UUID | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    # The kind-specific filters of the retired Tools / Batteries
    # views (owner spec 2026-10-25: the views went away, their
    # filters didn't) — each narrows its own kind inside the
    # merged stream, the way the extended price range already
    # judges each kind on its own totals.
    platform: str | None = None,
    min_replacement: Decimal | None = None,
    max_replacement: Decimal | None = None,
    location: str | None = None,
    location_id: uuid.UUID | None = None,
    standing: str | None = Query(default=None, pattern=_STANDING_PATTERN),
    warranty: str | None = Query(
        default=None,
        pattern="^(in_warranty|expiring_soon|expired|unknown|due)$",
    ),
    dealer_id: uuid.UUID | None = None,
    smart: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None, pattern=_SORT_PATTERN),
    sort_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """One stream over BOTH asset kinds — the inventory page's All
    view. Each record keeps its own public shape and gains an
    `item_kind` mark ('tool' | 'battery'). Ordering + paging run
    over the MERGED set on the server (step-4 fix D2): per-kind
    (id, sort-key) pairs merge under the one convention, then the
    page's rows are fetched and serialized. `min_price` /
    `max_price` here judge the EXTENDED total (price x quantity,
    sets at their bundle total) — the figure the rows display."""
    parsed = _smart(response, db, user, q, smart)
    if parsed is not None:
        pf = parsed["filters"]
        q = parsed["text"] or None
        category = category if category is not None else pf["category"]
        standing = standing if standing is not None else pf["standing"]
        location = location if location is not None else pf["location"]
        if tag_id is None and pf["tag_id"]:
            tag_id = uuid.UUID(pf["tag_id"])
        if min_price is None and pf["min_price"]:
            min_price = Decimal(pf["min_price"])
        if max_price is None and pf["max_price"]:
            max_price = Decimal(pf["max_price"])
    location_ids = _location_filter(db, user.id, location_id)
    tool_pairs, marks = search.tool_pairs(
        db,
        user.id,
        q=q,
        category=category,
        min_replacement=min_replacement,
        max_replacement=max_replacement,
        location=location,
        location_ids=location_ids,
        standing=standing,
        dealer_id=dealer_id,
        sort=sort,
        sort_dir=sort_dir,
        warranty=warranty,
        only_tool_ids=(
            service.tool_ids_with_tag(db, user.id, tag_id)
            if tag_id is not None
            else None
        ),
        extended_price_range=(min_price, max_price)
        if (min_price is not None or max_price is not None)
        else None,
    )
    battery_pairs_list = search.battery_pairs(
        db,
        user.id,
        q=q,
        platform=platform,
        category=category,
        location=location,
        location_ids=location_ids,
        standing=standing,
        dealer_id=dealer_id,
        sort=sort,
        sort_dir=sort_dir,
        warranty=warranty,
        only_battery_ids=(
            service.battery_ids_with_tag(db, user.id, tag_id)
            if tag_id is not None
            else None
        ),
        extended_price_range=(min_price, max_price)
        if (min_price is not None or max_price is not None)
        else None,
        seq_base=len(tool_pairs),
    )
    descending = search.sort_descending(sort, sort_dir)
    page_ids, total = search.merge_pairs(
        tool_pairs + battery_pairs_list, descending, offset, limit
    )
    response.headers["X-Total-Count"] = str(total)
    # Split the page by kind using the pair sources (an id belongs
    # to exactly one kind's pair list).
    tool_ids = {row_id for _k, _s, row_id in tool_pairs}
    batteries_by_id = {
        b.id: b
        for b in search.fetch_in_order(
            db,
            search.models.Battery,
            [i for i in page_ids if i not in tool_ids],
        )
    }
    tools_by_id = {
        t.id: t
        for t in search.fetch_in_order(
            db,
            search.models.Tool,
            [i for i in page_ids if i in tool_ids],
        )
    }
    for row_id, marked in marks.items():
        if row_id in tools_by_id:
            tools_by_id[row_id]._matched_via = marked._matched_via  # noqa: SLF001
            tools_by_id[row_id]._matched_label = marked._matched_label  # noqa: SLF001
    # The page serializes in TWO batched calls (scale fix,
    # 2026-10-26) — this loop used to annotate one row at a time,
    # re-deriving the entitlement active set and every per-row
    # lookup for every row on the page.
    views: dict[uuid.UUID, dict] = {}
    for view in _annotated(db, user, list(tools_by_id.values())):
        views[view["id"]] = {**view, "item_kind": "tool"}
    for view in _annotated_batteries(db, user, list(batteries_by_id.values())):
        views[view["id"]] = {**view, "item_kind": "battery"}
    return [views[row_id] for row_id in page_ids if row_id in views]


# -- vault statistics (also before /{tool_id}) -----------------------------
@router.get("/stats", response_model=schemas.InventoryStats)
def inventory_stats(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    # Stats describe ACTIVE assets only: an over-limit vault's totals
    # reflect what the plan covers (the shared billing filter).
    return service.get_inventory_stats(
        db,
        user.id,
        only_tool_ids=entitlements.active_tool_ids(db, user.id),
        only_battery_ids=entitlements.active_battery_ids(db, user.id),
    )


# -- custom field definitions (also before /{tool_id}: the literal segment
#    "field-definitions" would otherwise be parsed as a tool id) -----------
@router.get(
    "/field-definitions",
    response_model=list[schemas.FieldDefinitionPublic],
)
def list_field_definitions(
    item_type: str = "tool",
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    return custom_fields.list_definitions(db, user.id, item_type)


@router.post(
    "/field-definitions",
    response_model=schemas.FieldDefinitionPublic,
    status_code=201,
)
def create_field_definition(
    payload: schemas.FieldDefinitionCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return custom_fields.create_definition(db, user.id, payload)
    except custom_fields.FieldValidationError as exc:
        raise _as_422(exc)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"A field named '{payload.name}' already exists for '{payload.item_type}'",
        )


@router.put(
    "/field-definitions/{definition_id}",
    response_model=schemas.FieldDefinitionPublic,
)
def update_field_definition(
    definition_id: uuid.UUID,
    payload: schemas.FieldDefinitionUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        definition = custom_fields.update_definition(db, user.id, definition_id, payload)
    except custom_fields.FieldValidationError as exc:
        raise _as_422(exc)
    if definition is None:
        raise HTTPException(status_code=404, detail="Field definition not found")
    return definition


@router.delete("/field-definitions/{definition_id}", status_code=204)
def delete_field_definition(
    definition_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if not custom_fields.delete_definition(db, user.id, definition_id):
        raise HTTPException(status_code=404, detail="Field definition not found")


# -- tags + locations (literal segments, before /{tool_id}) ---------------
@router.get("/tags", response_model=list[schemas.TagPublic])
def list_tags(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    return service.list_tags(db, user.id)


@router.post("/tags", response_model=schemas.TagPublic, status_code=201)
def create_tag(
    payload: schemas.TagCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        tag = service.create_tag(db, user.id, payload.name, payload.color)
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    return service.serialize_tag(tag, item_count=0)


@router.put("/tags/{tag_id}", response_model=schemas.TagPublic)
def update_tag(
    tag_id: uuid.UUID,
    payload: schemas.TagUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        tag = service.update_tag(
            db, user.id, tag_id, name=payload.name, color=payload.color
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    counts = {row["id"]: row["item_count"] for row in service.list_tags(db, user.id)}
    return service.serialize_tag(tag, counts.get(tag.id, 0))


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(
    tag_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if not service.delete_tag(db, user.id, tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")


@router.get("/locations", response_model=list[str])
def list_locations(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The owner's previously used locations — the form autocomplete
    vocabulary (location itself stays free text)."""
    return service.list_locations(db, user.id)


# -- location tree (Package B; literal segments, before /{tool_id}) --------
@router.get("/location-tree", response_model=list[schemas.LocationNodePublic])
def list_location_tree(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The owner's whole inventory location tree, flat with parent
    links + paths + item counts (the client nests it)."""
    return service.list_location_tree(db, user.id)


@router.post(
    "/location-tree", response_model=schemas.LocationNodePublic, status_code=201
)
def create_location_node(
    payload: schemas.LocationNodeCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        node = service.create_location_node(
            db,
            user.id,
            name=payload.name.strip(),
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
            parent_layout_id=payload.parent_layout_id,
            drawer_index=payload.drawer_index,
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    nodes = service.owned_locations(db, user.id)
    counts = service._location_item_counts(db, user.id)
    return service.serialize_location_node(
        db, user.id, node, nodes=nodes, counts=counts
    )


@router.post(
    "/location-tree/drawer-lookup", response_model=schemas.DrawerLookupResponse
)
def drawer_lookup_route(
    payload: schemas.DrawerLookupRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """AI drawer lookup: the factory drawer configurations for
    the toolbox make + model entered in the lookup's own box
    (or read off a pasted product-page link). Grounded answers
    come from a real product page when one can be found;
    otherwise AI recall answers, flagged unverified. Answers
    the lookup ONLY — picking a configuration and creating the
    drawers is a separate confirm step riding the plain create
    route above. Error mapping mirrors the catalog module's AI
    surfaces exactly (the dark-seam contract: 503
    ai_not_configured, 502 ai_provider_error, 402
    insufficient_credits)."""
    try:
        return drawer_lookup.lookup_drawers(
            db,
            user.id,
            payload.model.strip() or payload.query.strip(),
            link=payload.link.strip(),
        )
    except ai_service.AiNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ai_not_configured",
                "message": "AI features aren't switched on for this site yet.",
            },
        ) from exc
    except ai_service.AiProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_provider_error", "message": str(exc)},
        ) from exc
    except wallet.InsufficientCredits as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "insufficient_credits",
                "message": "Your AI credit balance doesn't cover this action.",
            },
        ) from exc


@router.put(
    "/location-tree/{location_id}", response_model=schemas.LocationNodePublic
)
def update_location_node(
    location_id: uuid.UUID,
    payload: schemas.LocationNodeUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    try:
        node = service.update_location_node(
            db,
            user.id,
            location_id,
            name=fields["name"].strip() if fields.get("name") else None,
            parent_id=fields["parent_id"] if "parent_id" in fields else ...,
            sort_order=fields.get("sort_order"),
            parent_layout_id=(
                fields["parent_layout_id"] if "parent_layout_id" in fields else ...
            ),
            drawer_index=(
                fields["drawer_index"] if "drawer_index" in fields else ...
            ),
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if node is None:
        raise HTTPException(status_code=404, detail="Location not found")
    nodes = service.owned_locations(db, user.id)
    counts = service._location_item_counts(db, user.id)
    return service.serialize_location_node(
        db, user.id, node, nodes=nodes, counts=counts
    )


@router.delete("/location-tree/{location_id}", status_code=204)
def delete_location_node(
    location_id: uuid.UUID,
    payload: schemas.LocationNodeDelete | None = None,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    payload = payload or schemas.LocationNodeDelete()
    try:
        deleted = service.delete_location_node(
            db,
            user.id,
            location_id,
            reassign_to_id=payload.reassign_to_id,
            detach=payload.detach,
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Location not found")


# -- field suggestions (Package B; self-learning form fields) ---------------
@router.get("/suggestions", response_model=list[str])
def field_suggestions(
    field: str = Query(pattern="^(brand|category|size|tag)$"),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The caller's own distinct values for a form field — the
    type-ahead vocabulary. Owner-scoped in the service."""
    try:
        return service.field_suggestions(db, user.id, field)
    except service.ToolValidationError as exc:
        raise _as_422(exc)


# -- bulk edit (Package B) ----------------------------------------------------
@router.post("/bulk", response_model=schemas.BulkResult)
def bulk_apply(
    payload: schemas.BulkRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """One bulk operation over an explicit selection. A foreign id
    in the selection refuses the whole operation (service rule)."""
    try:
        return service.bulk_apply(
            db,
            user.id,
            items=[(ref.kind, ref.id) for ref in payload.items],
            action=payload.action,
            params=payload.params,
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)


# -- QR bin labels (blueprint §18; literal segments, still before
#    /{tool_id}) -------------------------------------------------------
@router.get("/labels", response_model=schemas.LabelSelectionPublic)
def label_selection(
    items: str = Query(default="", max_length=20000),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Resolve a print selection (`tool:<uuid>,battery:<uuid>,…`)
    into label rows. Owner-scoped in the service: refs that aren't
    the caller's items come back only as the `skipped` count."""
    labels, skipped = service.resolve_label_items(db, user.id, items)
    return {"labels": labels, "skipped": skipped}


@router.get("/labels/locations", response_model=list[schemas.LocationLabelPublic])
def label_locations(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Bin labels: the owner's distinct locations with the number
    of top-level items stored at each."""
    return service.location_label_counts(db, user.id)


def _email_attachment(
    db: Session,
    user: CurrentUser,
    item_id: uuid.UUID,
    collection: str,
    item_name: str,
    payload: schemas.AttachmentEmailRequest,
) -> dict:
    """Shared "Email this file" plumbing for tools, batteries and
    set pieces: owner-scoped in the attachments service, rate
    limited there too (429 with Retry-After when exhausted)."""
    try:
        return attachments.send_attachment_email(
            db,
            user.id,
            item_id,
            collection,
            key=payload.key,
            recipient=payload.recipient,
            sender_name=user.name,
            item_name=item_name,
        )
    except attachments.EmailRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


# -- importer (literal "import" segment — included BEFORE the
#    /{tool_id} routes so it can never be parsed as a tool id) ------
router.include_router(import_routes.router)

# Locate User Manual (wave 4): the endpoints live on the items
# they serve, so they mount here — the machinery + the doorway
# (catalog module) live in catalog.manual_routes.
from app.modules.catalog.manual_routes import router as _manual_router  # noqa: E402

router.include_router(_manual_router)


# -- batteries (before /{tool_id} AND before /batteries/{battery_id}
#    ordering matters for the same reason as field-definitions) --------
@router.get("/batteries/search", response_model=list[schemas.BatteryPublic])
def search_batteries(
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    platform: str | None = None,
    warranty: str | None = Query(
        default=None, pattern="^(in_warranty|expiring_soon|expired|unknown|due)$"
    ),
    category: str | None = None,
    tag_id: uuid.UUID | None = None,
    location: str | None = None,
    location_id: uuid.UUID | None = None,
    standing: str | None = Query(default=None, pattern=_STANDING_PATTERN),
    dealer_id: uuid.UUID | None = None,
    smart: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None, pattern=_SORT_PATTERN),
    sort_dir: str | None = Query(default=None, pattern="^(asc|desc)$"),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    parsed = _smart(response, db, user, q, smart)
    if parsed is not None:
        pf = parsed["filters"]
        q = parsed["text"] or None
        category = category if category is not None else pf["category"]
        standing = standing if standing is not None else pf["standing"]
        location = location if location is not None else pf["location"]
        if tag_id is None and pf["tag_id"]:
            tag_id = uuid.UUID(pf["tag_id"])
    batteries, total = search.search_batteries_paged(
        db,
        user.id,
        q=q,
        platform=platform,
        warranty=warranty,
        category=category,
        location=location,
        location_ids=_location_filter(db, user.id, location_id),
        standing=standing,
        dealer_id=dealer_id,
        limit=limit,
        offset=offset,
        sort=sort,
        sort_dir=sort_dir,
        only_battery_ids=(
            service.battery_ids_with_tag(db, user.id, tag_id)
            if tag_id is not None
            else None
        ),
    )
    response.headers["X-Total-Count"] = str(total)
    return _annotated_batteries(db, user, batteries)


@router.post("/batteries", response_model=schemas.BatteryPublic, status_code=201)
def create_battery(
    payload: schemas.BatteryCreate,
    force: bool = Query(default=False),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    # Same create doorway as tools: the plan's item limit counts
    # ASSETS (tools + batteries) — see billing.entitlements.
    if not entitlements.can_add_tool(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "item_limit_reached",
                "message": (
                    "You've reached your plan's item limit. Upgrade to add "
                    "more items — your existing items stay safe and visible."
                ),
            },
        )
    _assert_not_duplicate(
        db,
        user,
        "battery",
        brand=payload.brand,
        model=payload.model,
        serials=[payload.serial_number] if payload.serial_number else [],
        upc=payload.upc,
        force=force,
    )
    _validate_initial_schedule(payload.initial_schedule)
    try:
        battery = service.create_battery(db, user.id, payload)
    except (
        custom_fields.FieldValidationError,
        service.BatteryValidationError,
        service.ToolValidationError,
    ) as exc:
        raise _as_422(exc)
    _create_initial_schedule(
        db, user, item_kind="battery", item_id=battery.id,
        schedule=payload.initial_schedule,
    )
    db.refresh(battery)
    return service.serialize_battery(
        db, battery, dealer_visible=_dealer_visible(db, user)
    )


@router.get("/batteries", response_model=list[schemas.BatteryPublic])
def list_batteries(
    response: Response,
    in_tool: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The owner's batteries, paged (step-4 fix D3: this endpoint
    used to return the whole vault; the two frontend callers that
    already asked ?limit=200 are now actually honored). Default
    page is the 200 those callers always assumed; the full count
    rides X-Total-Count. `?in_tool=<tool id>` narrows to the
    batteries currently sitting in that tool (tool detail page)."""
    batteries, total = service.list_batteries_page(
        db, user.id, in_tool_id=in_tool, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return _annotated_batteries(db, user, batteries)


@router.get("/batteries/{battery_id}", response_model=schemas.BatteryPublic)
def get_battery(
    battery_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    battery = service.get_battery(db, user.id, battery_id)
    if battery is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    active_ids = entitlements.active_battery_ids(db, user.id)
    return service.serialize_battery(
        db,
        battery,
        active=active_ids is None or battery.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.put("/batteries/{battery_id}", response_model=schemas.BatteryPublic)
def update_battery(
    battery_id: uuid.UUID,
    payload: schemas.BatteryUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    _validate_initial_schedule(payload.initial_schedule)
    try:
        battery = service.update_battery(db, user.id, battery_id, payload)
    except (
        custom_fields.FieldValidationError,
        service.BatteryValidationError,
        service.ToolValidationError,
    ) as exc:
        raise _as_422(exc)
    if battery is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    _create_initial_schedule(
        db, user, item_kind="battery", item_id=battery.id,
        schedule=payload.initial_schedule,
    )
    db.refresh(battery)
    return service.serialize_battery(
        db, battery, dealer_visible=_dealer_visible(db, user)
    )


@router.delete("/batteries/{battery_id}", status_code=204)
def delete_battery(
    battery_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_battery(db, user.id, battery_id)
    except service.ToolValidationError as exc:
        # A delete guard (claims) refuses with friendly copy.
        raise _as_422(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Battery not found")


@router.post(
    "/batteries/{battery_id}/upload-url", response_model=schemas.UploadUrlResponse
)
def get_battery_upload_url(
    battery_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(
            db, user.id, battery_id, payload, collection="batteries"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post("/batteries/{battery_id}/attachments", response_model=dict)
def attach_battery_file(
    battery_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(
            db, user.id, battery_id, payload, collection="batteries"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.delete("/batteries/{battery_id}/attachments", response_model=dict)
def delete_battery_attachment(
    battery_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=1000),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.delete_attachment(
            db, user.id, battery_id, key, collection="batteries"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post(
    "/batteries/{battery_id}/attachments/email",
    response_model=schemas.AttachmentEmailResponse,
)
def email_battery_attachment(
    battery_id: uuid.UUID,
    payload: schemas.AttachmentEmailRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    battery = service.get_battery(db, user.id, battery_id)
    if battery is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    return _email_attachment(db, user, battery_id, "batteries", battery.name, payload)


# -- categories: the manager (gap wave 1, 2026-10-20) -------------------------
#
# Owner-scoped category control: list with counts, create,
# rename (cascades onto every item), merge, delete-detach. Tag
# CRUD above already carries colors; the manager surface sits
# next to these routes in the UI (Inventory → Categories & tags).


@router.get("/categories", response_model=list[schemas.CategoryPublic])
def list_categories(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    return service.list_categories(db, user.id)


@router.post(
    "/categories",
    response_model=schemas.CategoryPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: schemas.CategoryCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return service.create_category(
            db, user.id, payload.name, starred=payload.starred
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)


@router.post("/categories/star", response_model=schemas.CategoryPublic)
def star_category(
    payload: schemas.CategoryStar,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Star / unstar a category (owner spec 2026-10-24). The
    cap refusal is a 409 carrying the machine-readable code
    `star_limit_reached` — the UI branches on the code (never
    the message) and answers with the limit tooltip."""
    try:
        return service.set_category_star(
            db, user.id, payload.name, payload.starred
        )
    except service.StarLimitReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "star_limit_reached", "message": str(exc)},
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)


@router.post("/categories/rename", response_model=schemas.CategoryPublic)
def rename_category(
    payload: schemas.CategoryRename,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return service.rename_category(
            db, user.id, payload.old_name, payload.new_name
        )
    except service.PreinstalledCategoryError as exc:
        raise _preinstalled_409(exc)
    except service.ToolValidationError as exc:
        raise _as_422(exc)


@router.post(
    "/categories/merge", response_model=schemas.CategoryMergeResult
)
def merge_categories(
    payload: schemas.CategoryMerge,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return service.merge_categories(
            db, user.id, payload.source_name, payload.target_name
        )
    except service.PreinstalledCategoryError as exc:
        raise _preinstalled_409(exc)
    except service.ToolValidationError as exc:
        raise _as_422(exc)


@router.post(
    "/categories/delete", response_model=schemas.CategoryDeleteResult
)
def delete_category(
    payload: schemas.CategoryDelete,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Detach: items become uncategorized — items are never
    deleted by the manager. The UI confirms with the count."""
    try:
        return service.delete_category(db, user.id, payload.name)
    except service.PreinstalledCategoryError as exc:
        raise _preinstalled_409(exc)
    except service.ToolValidationError as exc:
        raise _as_422(exc)


# -- health check (gap wave 1, 2026-10-20) -------------------------------------


@router.get("/health-check", response_model=schemas.HealthCheckPublic)
def health_check(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Claim-readiness scan: ACTIVE items missing a model number,
    serial number, photo, or purchase date (set pieces surface
    under their set by the serial rule)."""
    return service.health_check(db, user.id)


@router.get("/health-check-due", response_model=schemas.HealthCheckDuePublic)
def health_check_due(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Health checks due (dashboard widget, widget wave 2,
    2026-11-10): the health check above, read for Home — the
    scan's own total/counts/items verbatim, each flagged item
    carrying its primary photo's thumbnail URLs for the widget
    rows. Always 200: nothing flagged is the quiet state in the
    payload (total 0), never an error. The inventory module
    gate is the reach: a seat without inventory (the downloads
    level included) gets 403 module_unavailable and is never
    offered the widget."""
    return service.health_check_due(db, user.id)


@router.post(
    "/health-check/photo-ignore",
    response_model=schemas.HealthPhotoIgnorePublic,
)
def health_check_photo_ignore(
    payload: schemas.HealthPhotoIgnoreRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Ignore (or un-ignore) ONE item's missing photo in the
    health check (sweep E3, busy-work #5): per item, photo only,
    reversible from the same Health Check page. The scan and the
    Health checks due count both read the same flag, so the two
    can never disagree. 404 when the item is not the caller's."""
    result = service.set_health_photo_ignore(
        db, user.id, payload.kind, payload.item_id, payload.ignored
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result


@router.post(
    "/health-check/photo-ignore-all",
    response_model=schemas.HealthPhotoIgnoreAllPublic,
)
def health_check_photo_ignore_all(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Ignore ALL of the caller's currently-flagged missing
    photos in one action (owner order, 2026-11-12 — the Health
    Check page's "Ignore all missing photos" button). Exactly
    the per-item ignore applied to every affected item at once:
    the same flag, set atomically, owner-scoped by the scan
    itself. Answers how many items were newly ignored."""
    return service.ignore_all_missing_photos(db, user.id)


# -- sold tracking (wave 2, 2026-10-20) ------------------------------------------------
#
# The sale ledger lives in sales.py; these routes are the thin
# HTTP layer. Mark sold answers with the refreshed ITEM (the
# detail page re-renders standing + active state from it), the
# ledger reads answer with records, and Undo answers with the
# reversal record it wrote.


@router.post("/tools/{tool_id}/mark-sold", response_model=schemas.ToolPublic)
def mark_tool_sold(
    tool_id: uuid.UUID,
    payload: schemas.MarkSoldRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if service.get_tool(db, user.id, tool_id) is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    try:
        sales.mark_sold(
            db, user.id, "tool", tool_id,
            quantity_sold=payload.quantity_sold,
            buyer_name=payload.buyer_name,
            buyer_contact=payload.buyer_contact,
            sale_price=payload.sale_price,
            sold_on=payload.sold_on,
            note=payload.note,
        )
    except sales.SaleError as exc:
        raise _as_422(exc)
    tool = service.get_tool(db, user.id, tool_id)
    active_ids = entitlements.active_tool_ids(db, user.id)
    return service.serialize_tool(
        db, tool,
        active=active_ids is None or tool.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.post(
    "/batteries/{battery_id}/mark-sold", response_model=schemas.BatteryPublic
)
def mark_battery_sold(
    battery_id: uuid.UUID,
    payload: schemas.MarkSoldRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if service.get_battery(db, user.id, battery_id) is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    try:
        sales.mark_sold(
            db, user.id, "battery", battery_id,
            quantity_sold=payload.quantity_sold,
            buyer_name=payload.buyer_name,
            buyer_contact=payload.buyer_contact,
            sale_price=payload.sale_price,
            sold_on=payload.sold_on,
            note=payload.note,
        )
    except sales.SaleError as exc:
        raise _as_422(exc)
    battery = service.get_battery(db, user.id, battery_id)
    active_ids = entitlements.active_battery_ids(db, user.id)
    return service.serialize_battery(
        db, battery,
        active=active_ids is None or battery.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.post(
    "/sets/{set_id}/pieces/{piece_id}/mark-sold",
    response_model=schemas.SaleRecordPublic,
    status_code=status.HTTP_201_CREATED,
)
def mark_piece_sold(
    set_id: uuid.UUID,
    piece_id: uuid.UUID,
    payload: schemas.MarkSoldRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if service.get_tool(db, user.id, set_id) is None:
        raise HTTPException(status_code=404, detail="Set not found")
    piece = service.get_set_piece(db, user.id, piece_id)
    if piece is None or piece.set_id != set_id:
        raise HTTPException(status_code=404, detail="Piece not found")
    try:
        record = sales.mark_sold(
            db, user.id, "piece", piece_id,
            buyer_name=payload.buyer_name,
            buyer_contact=payload.buyer_contact,
            sale_price=payload.sale_price,
            sold_on=payload.sold_on,
            note=payload.note,
        )
    except sales.SaleError as exc:
        raise _as_422(exc)
    return sales.sale_view(db, user.id, record)


@router.get("/sales", response_model=list[schemas.SaleRecordPublic])
def list_sales(
    item_id: uuid.UUID | None = None,
    limit: int = 500,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    rows = sales.list_sales(db, user.id, item_id=item_id, limit=limit)
    reversed_ids = sales._reversed_ids(db, user.id)
    out = []
    for row in rows:
        view = sales.serialize_sale_record(row)
        view["reversed"] = row.id in reversed_ids
        out.append(view)
    return out


@router.get("/sales/totals", response_model=schemas.SalesTotalsPublic)
def sales_totals(
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    return sales.sales_totals(db, user.id)


@router.post(
    "/sales/{record_id}/undo", response_model=schemas.SaleRecordPublic,
    status_code=status.HTTP_201_CREATED,
)
def undo_sale(
    record_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        reversal = sales.undo_sale(db, user.id, record_id)
    except sales.SaleError as exc:
        # A missing/foreign record reads as a refusal here (the
        # ledger's ids are the caller's own from their Sold view).
        raise _as_422(exc)
    return sales.sale_view(db, user.id, reversal)


@router.post("/sales/poster")
def sales_poster(
    payload: schemas.PosterRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The printable for-sale poster PDF: one page per picked
    item. Ownership is enforced by the renderer's service
    getters (a foreign id renders nothing) — and a pick list of
    only foreign ids is a 422, never an empty PDF."""
    from app.modules.core import models as core_models

    picks = []
    for pick in payload.items:
        record = (
            service.get_tool(db, user.id, pick.item_id)
            if pick.item_kind == "tool"
            else service.get_battery(db, user.id, pick.item_id)
        )
        if record is None:
            raise HTTPException(
                status_code=422, detail="One of those items isn't yours."
            )
        picks.append(
            {
                "item_kind": pick.item_kind,
                "item_id": pick.item_id,
                "price": pick.price,
                "listing_url": pick.listing_url,
            }
        )
    owner = db.get(core_models.User, user.id)
    content = poster.render_poster(db, owner, picks)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="for-sale-poster.pdf"'
        },
    )



# -- tools ---------------------------------------------------------------
@router.post("", response_model=schemas.ToolPublic, status_code=201)
def create_tool(
    payload: schemas.ToolCreate,
    force: bool = Query(default=False),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    # The create doorway: with enforcement on, an account at its
    # plan limit cannot add another tool. The structured code lets
    # the client show the upgrade prompt, not a raw error.
    if not entitlements.can_add_tool(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "item_limit_reached",
                "message": (
                    "You've reached your plan's item limit. Upgrade to add "
                    "more tools — your existing tools stay safe and visible."
                ),
            },
        )
    _assert_not_duplicate(
        db,
        user,
        "tool",
        brand=payload.brand,
        model=(payload.model_numbers[0] if payload.model_numbers else payload.model),
        serials=(
            list(payload.serial_numbers or [])
            + ([payload.serial_number] if payload.serial_number else [])
        ),
        upc=payload.upc,
        force=force,
    )
    _validate_initial_schedule(payload.initial_schedule)
    try:
        tool = service.create_tool(db, user.id, payload)
    except (
        custom_fields.FieldValidationError,
        service.ToolValidationError,
    ) as exc:
        raise _as_422(exc)
    _create_initial_schedule(
        db, user, item_kind="tool", item_id=tool.id,
        schedule=payload.initial_schedule,
    )
    db.refresh(tool)
    return service.serialize_tool(db, tool, dealer_visible=_dealer_visible(db, user))


@router.get("", response_model=list[schemas.ToolPublic])
def list_tools(
    response: Response,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """The owner's tools, paged (step-4 fix D3 — same shape as the
    battery list: default page 200, X-Total-Count carries the
    whole count)."""
    tools, total = service.list_tools_page(
        db, user.id, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return _annotated(db, user, tools)


@router.get("/{tool_id}", response_model=schemas.ToolPublic)
def get_tool(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    tool = service.get_tool(db, user.id, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    active_ids = entitlements.active_tool_ids(db, user.id)
    return service.serialize_tool(
        db,
        tool,
        active=active_ids is None or tool.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.put("/{tool_id}", response_model=schemas.ToolPublic)
def update_tool(
    tool_id: uuid.UUID,
    payload: schemas.ToolUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    _validate_initial_schedule(payload.initial_schedule)
    try:
        tool = service.update_tool(db, user.id, tool_id, payload)
    except (
        custom_fields.FieldValidationError,
        service.ToolValidationError,
    ) as exc:
        raise _as_422(exc)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    _create_initial_schedule(
        db, user, item_kind="tool", item_id=tool.id,
        schedule=payload.initial_schedule,
    )
    db.refresh(tool)
    return service.serialize_tool(db, tool, dealer_visible=_dealer_visible(db, user))


@router.delete("/{tool_id}", status_code=204)
def delete_tool(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_tool(db, user.id, tool_id)
    except service.ToolValidationError as exc:
        # A delete guard (claims) refuses with friendly copy.
        raise _as_422(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")


# -- uploads -------------------------------------------------------------
@router.post("/{tool_id}/upload-url", response_model=schemas.UploadUrlResponse)
def get_upload_url(
    tool_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(db, user.id, tool_id, payload)
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post("/{tool_id}/attachments", response_model=dict)
def attach_file(
    tool_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(db, user.id, tool_id, payload)
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.delete("/{tool_id}/attachments", response_model=dict)
def delete_tool_attachment(
    tool_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=1000),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Delete ONE attachment (F1-31): row + stored object, owner-scoped."""
    try:
        return attachments.delete_attachment(db, user.id, tool_id, key)
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post(
    "/{tool_id}/attachments/email", response_model=schemas.AttachmentEmailResponse
)
def email_tool_attachment(
    tool_id: uuid.UUID,
    payload: schemas.AttachmentEmailRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    tool = service.get_tool(db, user.id, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _email_attachment(db, user, tool_id, "tools", tool.name, payload)


# -- set pieces + set attachment -------------------------------------------
@router.post(
    "/{tool_id}/pieces",
    response_model=schemas.SetPiecePublic,
    status_code=201,
)
def add_set_piece(
    tool_id: uuid.UUID,
    payload: schemas.SetPieceCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        piece = service.add_set_piece(db, user.id, tool_id, payload)
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    return service.serialize_set_piece(piece)


@router.put("/pieces/{piece_id}", response_model=schemas.SetPiecePublic)
def update_set_piece(
    piece_id: uuid.UUID,
    payload: schemas.SetPieceUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        piece = service.update_set_piece(db, user.id, piece_id, payload)
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if piece is None:
        raise HTTPException(status_code=404, detail="Set piece not found")
    return service.serialize_set_piece(piece)


@router.delete("/pieces/{piece_id}", status_code=204)
def delete_set_piece(
    piece_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        deleted = service.delete_set_piece(db, user.id, piece_id)
    except service.ToolValidationError as exc:
        # A delete guard (claims) refuses with friendly copy.
        raise _as_422(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Set piece not found")


@router.post("/pieces/{piece_id}/upload-url", response_model=schemas.UploadUrlResponse)
def get_piece_upload_url(
    piece_id: uuid.UUID,
    payload: schemas.UploadUrlRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.issue_upload_url(
            db, user.id, piece_id, payload, collection="pieces"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post("/pieces/{piece_id}/attachments", response_model=dict)
def attach_piece_file(
    piece_id: uuid.UUID,
    payload: schemas.AttachRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.attach_file(
            db, user.id, piece_id, payload, collection="pieces"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.delete("/pieces/{piece_id}/attachments", response_model=dict)
def delete_piece_attachment(
    piece_id: uuid.UUID,
    key: str = Query(min_length=1, max_length=1000),
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        return attachments.delete_attachment(
            db, user.id, piece_id, key, collection="pieces"
        )
    except attachments.UploadError as exc:
        raise _as_upload_http(exc)


@router.post(
    "/pieces/{piece_id}/attachments/email",
    response_model=schemas.AttachmentEmailResponse,
)
def email_piece_attachment(
    piece_id: uuid.UUID,
    payload: schemas.AttachmentEmailRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    piece = service.get_set_piece(db, user.id, piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Set piece not found")
    return _email_attachment(db, user, piece_id, "pieces", piece.name, payload)


@router.post("/{tool_id}/attach-to-set", response_model=schemas.ToolPublic)
def attach_tool_to_set(
    tool_id: uuid.UUID,
    payload: schemas.AttachToSetRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        tool = service.attach_tool_to_set(db, user.id, payload.set_id, tool_id)
    except service.ToolNotFoundError:
        # Cross-owner (or missing) set/tool: the house non-leaking
        # 404, byte-identical for foreign and random ids (E-02).
        raise HTTPException(status_code=404, detail="Tool not found")
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    return service.serialize_tool(db, tool, dealer_visible=_dealer_visible(db, user))


@router.post("/{tool_id}/detach", response_model=schemas.ToolPublic)
def detach_tool(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        tool = service.detach_tool(db, user.id, tool_id)
    except service.ToolValidationError as exc:
        # A delete guard (claims) refuses: a claimed set can't be
        # taken apart while its claim is open.
        raise _as_422(exc)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return service.serialize_tool(db, tool, dealer_visible=_dealer_visible(db, user))



# -- lost/stolen report records (gap wave 1, 2026-10-20) ------------------------


@router.get(
    "/{item_kind}/{item_id}/loss-reports",
    response_model=list[schemas.LossReportPublic],
)
def list_loss_reports(
    item_kind: str,
    item_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    item = service._loss_item(db, user.id, item_kind, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    # Each report carries its own documents: the item's attachments
    # stamped with that report's id, serialized once here (fresh
    # read URLs) and grouped by report.
    documents_by_report: dict[str, list[dict]] = {}
    for doc in service._serialize_attachments(item):
        report_id = doc.get("loss_report_id")
        if report_id:
            documents_by_report.setdefault(report_id, []).append(doc)
    return [
        service.serialize_loss_report(
            row, documents=documents_by_report.get(str(row.id), [])
        )
        for row in service.list_loss_reports(db, user.id, item_kind, item_id)
    ]


@router.post(
    "/{item_kind}/{item_id}/loss-reports",
    response_model=schemas.LossReportPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_loss_report(
    item_kind: str,
    item_id: uuid.UUID,
    payload: schemas.LossReportCreate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Mark the item lost/stolen AND open its report record in
    one step (the details are skippable — an empty report still
    opens and can be filled in from the detail panel)."""
    try:
        row = service.create_loss_report(
            db, user.id, item_kind, item_id, payload.model_dump()
        )
    except service.ToolValidationError as exc:
        if "isn't available" in str(exc):
            raise HTTPException(status_code=404, detail="Item not found")
        raise _as_422(exc)
    return service.serialize_loss_report(row)


@router.put(
    "/loss-reports/{report_id}", response_model=schemas.LossReportPublic
)
def update_loss_report(
    report_id: uuid.UUID,
    payload: schemas.LossReportUpdate,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    row = service.update_loss_report(
        db, user.id, report_id, payload.model_dump(exclude_unset=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return service.serialize_loss_report(row)


@router.post(
    "/loss-reports/{report_id}/recover",
    response_model=schemas.LossReportPublic,
)
def recover_loss_report(
    report_id: uuid.UUID,
    payload: schemas.LossReportRecover,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    """Mark recovered: the item returns to service and the report
    closes — kept as history, never deleted."""
    try:
        row = service.recover_loss_report(
            db, user.id, report_id, payload.recovered_date
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return service.serialize_loss_report(row)


# -- asset history + replaced marker (2026-10-20) --------------------------------
#
# The timeline feed merges every module's registered history
# providers (app/modules/inventory/history.py) — inventory owns
# the endpoint because the item pages do; the providers own the
# events. Owner-scoped like everything here: a foreign id is a
# 404, never an existence leak.


@router.get(
    "/tools/{tool_id}/history", response_model=schemas.ItemHistoryPublic
)
def tool_history(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if service.get_tool(db, user.id, tool_id) is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return {
        "item_kind": "tool",
        "item_id": tool_id,
        "events": history.item_history(db, user.id, "tool", tool_id),
    }


@router.get(
    "/batteries/{battery_id}/history",
    response_model=schemas.ItemHistoryPublic,
)
def battery_history(
    battery_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    if service.get_battery(db, user.id, battery_id) is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    return {
        "item_kind": "battery",
        "item_id": battery_id,
        "events": history.item_history(db, user.id, "battery", battery_id),
    }


@router.post("/tools/{tool_id}/replaced", response_model=schemas.ToolPublic)
def mark_tool_replaced(
    tool_id: uuid.UUID,
    payload: schemas.MarkReplacedRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        tool = service.mark_replaced(
            db,
            user.id,
            "tool",
            tool_id,
            on_date=payload.replaced_on,
            replaced_by_item_id=payload.replaced_by_item_id,
            note=payload.note,
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    active_ids = entitlements.active_tool_ids(db, user.id)
    return service.serialize_tool(
        db,
        tool,
        active=active_ids is None or tool.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.delete("/tools/{tool_id}/replaced", response_model=schemas.ToolPublic)
def clear_tool_replaced(
    tool_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    tool = service.clear_replaced(db, user.id, "tool", tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    active_ids = entitlements.active_tool_ids(db, user.id)
    return service.serialize_tool(
        db,
        tool,
        active=active_ids is None or tool.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.post(
    "/batteries/{battery_id}/replaced", response_model=schemas.BatteryPublic
)
def mark_battery_replaced(
    battery_id: uuid.UUID,
    payload: schemas.MarkReplacedRequest,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    try:
        battery = service.mark_replaced(
            db,
            user.id,
            "battery",
            battery_id,
            on_date=payload.replaced_on,
            replaced_by_item_id=payload.replaced_by_item_id,
            note=payload.note,
        )
    except service.ToolValidationError as exc:
        raise _as_422(exc)
    if battery is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    active_ids = entitlements.active_battery_ids(db, user.id)
    return service.serialize_battery(
        db,
        battery,
        active=active_ids is None or battery.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )


@router.delete(
    "/batteries/{battery_id}/replaced", response_model=schemas.BatteryPublic
)
def clear_battery_replaced(
    battery_id: uuid.UUID,
    user: CurrentUser = Depends(_inventory_module),
    db: Session = Depends(get_db),
):
    battery = service.clear_replaced(db, user.id, "battery", battery_id)
    if battery is None:
        raise HTTPException(status_code=404, detail="Battery not found")
    active_ids = entitlements.active_battery_ids(db, user.id)
    return service.serialize_battery(
        db,
        battery,
        active=active_ids is None or battery.id in active_ids,
        dealer_visible=_dealer_visible(db, user),
    )

