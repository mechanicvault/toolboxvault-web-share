"""Full-text search over tools and batteries (inventory module).

Backed by the search_vector tsvector columns, maintained by Postgres
triggers (see the Alembic migrations): they cover name, brand, model,
serial number, notes, condition, category, location (plus platform
and chemistry for batteries), and the values (plus labels) of custom
fields marked searchable.

Ryan's acceptance test: searching "apple" must find a tool whose notes are
the only place "apple" appears. Notes are in the vector, so it does.
"""

import uuid
from datetime import date
from decimal import Decimal
from functools import cmp_to_key

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.inventory import models, service


def _set_content_matches(
    db: Session,
    owner_id: uuid.UUID,
    query: str,
    only_tool_ids: set[uuid.UUID] | None = None,
) -> list[models.Tool]:
    """Sets whose CONTENTS match the query: a piece's part number /
    name / serial, or an attached addon tool's name / brand / model
    (item structure package, 2026-10-18 — searching a piece's part
    number finds the SET). Every term must hit somewhere in the set's
    contents (the websearch AND semantics of the main query). The
    returned tools carry `_matched_via` / `_matched_label` marks for
    the serializer. Plain Python over the owner's sets — set counts
    per owner are small, and this path is dialect-free (the tsvector
    path below is Postgres-only)."""
    terms = [t.lower() for t in query.split() if t]
    if not terms:
        return []
    sets = list(
        db.scalars(
            select(models.Tool).where(
                models.Tool.owner_id == owner_id,
                models.Tool.is_set.is_(True),
                models.Tool.attached_to_set_id.is_(None),
                # A retired (replaced) set never surfaces via its
                # contents either (claims two-types, 2026-10-25).
                models.Tool.standing.is_distinct_from(models.STANDING_REPLACED),
            )
        )
    )
    matches: list[models.Tool] = []
    for set_tool in sets:
        if only_tool_ids is not None and set_tool.id not in only_tool_ids:
            continue
        pieces = list(
            db.scalars(
                select(models.SetPiece).where(
                    models.SetPiece.set_id == set_tool.id
                )
            )
        )
        attached = list(
            db.scalars(
                select(models.Tool).where(
                    models.Tool.attached_to_set_id == set_tool.id
                )
            )
        )
        piece_haystacks = [
            (p.name.lower(), (p.part_number or "").lower(), (p.serial_number or "").lower())
            for p in pieces
        ]
        attached_haystacks = [
            (t.name.lower(), (t.brand or "").lower(), (t.model or "").lower())
            for t in attached
        ]

        def _term_hits(term: str, haystacks) -> bool:
            return any(term in field for fields in haystacks for field in fields)

        if not all(
            _term_hits(term, piece_haystacks) or _term_hits(term, attached_haystacks)
            for term in terms
        ):
            continue
        # Mark the FIRST matching member: pieces win over attached
        # tools (a part-number hit is the more specific story).
        mark: tuple[str, str] | None = None
        for piece in pieces:
            fields = (piece.name.lower(), (piece.part_number or "").lower(), (piece.serial_number or "").lower())
            if any(term in field for term in terms for field in fields):
                label = piece.name
                if piece.part_number:
                    label = f"{piece.name} · {piece.part_number}"
                mark = ("piece", label)
                break
        if mark is None:
            for tool in attached:
                fields = (tool.name.lower(), (tool.brand or "").lower(), (tool.model or "").lower())
                if any(term in field for term in terms for field in fields):
                    mark = ("attached", tool.name)
                    break
        if mark is not None:
            set_tool._matched_via, set_tool._matched_label = mark  # noqa: SLF001
            matches.append(set_tool)
    return matches


def _dealer_name_map(db: Session, company_ids, owner_id=None) -> dict:
    """{company_id: lowercase name} for the dealer filter/sort —
    resolved in ONE query off dealer_companies (the lazy-import
    pattern inventory uses for the dealers module). None ids and
    ids of deleted companies simply don't appear; an empty name
    folds to None so the row sorts with the untagged.
    `owner_id` (personal dealer edits, 2026-11-05): the names
    resolve through THAT user's personal layer — inventory
    search is owner-scoped, so dealer sort order speaks his
    names for his dealers."""
    wanted = {cid for cid in company_ids if cid is not None}
    if not wanted:
        return {}
    from app.modules.dealers import models as dealer_models

    rows = db.execute(
        select(dealer_models.DealerCompany.id, dealer_models.DealerCompany.name).where(
            dealer_models.DealerCompany.id.in_(wanted)
        )
    )
    names = {
        cid: ((name or "").strip().lower() or None) for cid, name in rows
    }
    if owner_id is not None:
        from app.modules.dealers import service as dealer_service

        for cid, name in dealer_service.personal_name_map(
            db, owner_id, wanted
        ).items():
            names[cid] = name.strip().lower() or None
    return names


def search_tools(
    db: Session,
    owner_id: uuid.UUID,
    q: str | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_replacement: Decimal | None = None,
    max_replacement: Decimal | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    location_ids: set[uuid.UUID] | None = None,
    standing: str | None = None,
    dealer_id: uuid.UUID | None = None,
    limit: int = 50,
    only_tool_ids: set[uuid.UUID] | None = None,
) -> list[models.Tool]:
    # Attached addon tools are never top-level results — they live
    # inside their set (which itself is findable by their identity
    # through _set_content_matches).
    stmt = select(models.Tool).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
        # REPLACED items (claims two-types) are retired: never in
        # lists or search. Unconditional — no filter can ask for
        # the standing (it is not in the routes' standing pattern).
        models.Tool.standing.is_distinct_from(models.STANDING_REPLACED),
    )

    if only_tool_ids is not None:
        # Entitlement active set (billing computes; the route passes
        # it in): restrict to these tools. The owner's own list view
        # passes None and annotates instead — see routes.
        stmt = stmt.where(models.Tool.id.in_(only_tool_ids))

    has_query = bool(q and q.strip())
    if has_query and db.bind is not None and db.bind.dialect.name == "postgresql":
        ts_query = func.websearch_to_tsquery("english", q.strip())
        stmt = (
            stmt.where(models.Tool.search_vector.op("@@")(ts_query))
            .order_by(func.ts_rank_cd(models.Tool.search_vector, ts_query).desc())
        )
    else:
        stmt = stmt.order_by(models.Tool.updated_at.desc())

    if category:
        stmt = stmt.where(models.Tool.category == category)
    if standing:
        stmt = stmt.where(models.Tool.standing == standing)
    if dealer_id is not None:
        # Dealer filter (intermingling, 2026-10-25): the dealer
        # TAG is the canonical link — an exact company id match.
        stmt = stmt.where(models.Tool.dealer_company_id == dealer_id)
    if location:
        # Case-insensitive exact match on the free-text location —
        # the bin-label QR lands here (/inventory?location=…), and
        # the value always comes from the owner's own vocabulary.
        stmt = stmt.where(
            func.lower(models.Tool.location) == location.strip().lower()
        )
    if location_ids is not None:
        # Tree filter (Package B): the picked node plus its whole
        # subtree — filtering by a place shows everything under it.
        stmt = stmt.where(models.Tool.location_id.in_(location_ids))
    if min_price is not None:
        stmt = stmt.where(models.Tool.purchase_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(models.Tool.purchase_price <= max_price)
    if min_replacement is not None:
        stmt = stmt.where(models.Tool.replacement_cost >= min_replacement)
    if max_replacement is not None:
        stmt = stmt.where(models.Tool.replacement_cost <= max_replacement)
    if date_from is not None:
        stmt = stmt.where(models.Tool.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(models.Tool.purchase_date <= date_to)

    cap = max(1, min(limit, 200))
    if has_query and not (
        db.bind is not None and db.bind.dialect.name == "postgresql"
    ):
        # The tsvector path is Postgres-only. On the SQLite test
        # database there is no vector to rank by; the set-content
        # matches below are dialect-free and still run, so a query
        # returns exactly the sets it finds through their contents.
        results = []
    else:
        results = list(db.scalars(stmt.limit(cap)))
    if has_query:
        seen = {tool.id for tool in results}
        for set_tool in _set_content_matches(db, owner_id, q.strip(), only_tool_ids):
            if set_tool.id in seen:
                continue
            if category and set_tool.category != category:
                continue
            if standing and set_tool.standing != standing:
                continue
            if location and set_tool.location.strip().lower() != location.strip().lower():
                continue
            if location_ids is not None and set_tool.location_id not in location_ids:
                continue
            if dealer_id is not None and set_tool.dealer_company_id != dealer_id:
                continue
            results.append(set_tool)
    return results[:cap]


def _warranty_matches(status_value: str, wanted: str) -> bool:
    """One warranty filter test: an exact status, or "due" — the
    combined expired + expiring-soon set behind the Home counters
    (deep audit F5-02)."""
    if wanted == "due":
        return status_value in ("expired", "expiring_soon")
    return status_value == wanted


def search_batteries(
    db: Session,
    owner_id: uuid.UUID,
    q: str | None = None,
    platform: str | None = None,
    warranty: str | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    location_ids: set[uuid.UUID] | None = None,
    standing: str | None = None,
    dealer_id: uuid.UUID | None = None,
    limit: int = 50,
    only_battery_ids: set[uuid.UUID] | None = None,
) -> list[models.Battery]:
    """The battery twin of search_tools, over batteries.search_vector,
    plus the two battery-native filters: `platform` (case-insensitive
    exact match on the free-text platform, e.g. 'M18') and `warranty`
    (the COMPUTED status — filtering happens in Python after the SQL
    narrowing, because the status is derived, never a column)."""
    stmt = select(models.Battery).where(
        models.Battery.owner_id == owner_id,
        # REPLACED items are retired (see the tool twin above).
        models.Battery.standing.is_distinct_from(models.STANDING_REPLACED),
    )

    if only_battery_ids is not None:
        stmt = stmt.where(models.Battery.id.in_(only_battery_ids))

    if q and q.strip():
        ts_query = func.websearch_to_tsquery("english", q.strip())
        stmt = (
            stmt.where(models.Battery.search_vector.op("@@")(ts_query))
            .order_by(func.ts_rank_cd(models.Battery.search_vector, ts_query).desc())
        )
    else:
        stmt = stmt.order_by(models.Battery.updated_at.desc())

    if platform:
        stmt = stmt.where(
            func.lower(models.Battery.platform) == platform.strip().lower()
        )
    if category:
        stmt = stmt.where(models.Battery.category == category)
    if standing:
        stmt = stmt.where(models.Battery.standing == standing)
    if dealer_id is not None:
        stmt = stmt.where(models.Battery.dealer_company_id == dealer_id)
    if location:
        stmt = stmt.where(
            func.lower(models.Battery.location) == location.strip().lower()
        )
    if location_ids is not None:
        stmt = stmt.where(models.Battery.location_id.in_(location_ids))
    if min_price is not None:
        stmt = stmt.where(models.Battery.purchase_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(models.Battery.purchase_price <= max_price)
    if date_from is not None:
        stmt = stmt.where(models.Battery.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(models.Battery.purchase_date <= date_to)

    cap = max(1, min(limit, 200))
    if warranty:
        # Derived-status filter: pull a bounded superset, filter,
        # then slice. Vaults are per-owner and small; the cap keeps
        # a pathological account from loading unbounded rows.
        rows = list(db.scalars(stmt.limit(1000)))
        rows = [b for b in rows if service.warranty_status(b) == warranty]
        return rows[:cap]
    return list(db.scalars(stmt.limit(cap)))

# -- server-side sort + paging (step-4 fix round, defect D2) -----------
#
# Package B sorted CLIENT-side over a 100-item window: at vault
# scale the window made most of the vault unreachable by browsing
# or sorting (campaign lane 2: the $99,999 tool could never be
# reached). The paged searches below order the owner's WHOLE
# filtered set on the server and return one page plus the total.
#
# The sort keys are Package B's menu, with Package B's direction
# convention: value sorts (name, brand, category, location,
# purchase date, price) run ASCENDING, recency sorts (date added,
# recently updated) run NEWEST FIRST, and missing values always
# trail. `sort_dir` ("asc" | "desc") overrides the convention when
# a caller wants the other direction explicitly. Price is the
# EXTENDED total (unit price x quantity; for a set, its full
# price_total — own price + addon pieces + attached tools, the
# exact figure the serializer reports).
#
# Mechanics: for the full filtered set only ids + sort keys are
# pulled (two columns per row — cheap at vault scale); the merge
# happens in Python over those pairs; the page's full rows are
# fetched afterwards, so serialization cost stays per-page.

SORT_KEYS = (
    "featured",
    "name",
    "brand",
    "dealer",
    "category",
    "location",
    "purchase_date",
    "price",
    "created_at",
    "updated_at",
    "warranty_end",
)
_RECENCY_KEYS = ("created_at", "updated_at")
_GONE_PIECE_STATUSES = ("sold", "removed")


def sort_descending(sort: str | None, sort_dir: str | None) -> bool:
    if sort_dir == "desc":
        return True
    if sort_dir == "asc":
        return False
    if sort is None:
        # No sort specified: the list default is date added,
        # newest first (owner spec 2026-10-25); a text query
        # still ranks by relevance first (the key below).
        return True
    # "featured" (F1-04): its key is a (has_photo, updated_at) tuple
    # and descending puts photo items first, newest first inside
    # each group — the inventory page's DEFAULT order only; every
    # user-picked sort keeps its own convention untouched.
    return sort in _RECENCY_KEYS or sort == "featured"


def _compare_keys(a, b, descending: bool) -> int:
    """One comparison under the sort convention: missing values
    (None) always trail, whichever direction runs."""
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if a == b:
        return 0
    result = -1 if a < b else 1
    return -result if descending else result


def merge_pairs(pairs, descending: bool, offset: int, limit: int):
    """Order (key, seq, row_id) triples under the convention and
    cut one page. `seq` is the per-source order (SQL order for main
    results, discovery order for set-content matches, tools before
    batteries in the unified stream) and breaks key ties, so
    paging is stable end to end. Returns (page_ids_in_order, total)."""

    def compare(left, right):
        result = _compare_keys(left[0], right[0], descending)
        if result:
            return result
        return (left[1] > right[1]) - (left[1] < right[1])

    ordered = sorted(pairs, key=cmp_to_key(compare))
    total = len(ordered)
    return [row_id for _k, _s, row_id in ordered[offset : offset + limit]], total


def fetch_in_order(db: Session, model, page_ids: list[uuid.UUID]) -> list:
    """Full ORM rows for one page of ids, in the page's order."""
    if not page_ids:
        return []
    rows = {
        row.id: row
        for row in db.scalars(select(model).where(model.id.in_(page_ids)))
    }
    return [rows[row_id] for row_id in page_ids if row_id in rows]


def _tool_extended_price_expression():
    """SQL for a tool's extended total: unit price x quantity, or
    for a set the full bundle total (own price x quantity + priced
    addon pieces not sold/removed + attached tools' totals) —
    `_set_totals` in SQL. A non-set with no price stays NULL (the
    client convention: priceless sorts last)."""
    tool = models.Tool
    attached = aliased(models.Tool)
    addon_sum = (
        select(func.coalesce(func.sum(models.SetPiece.price), Decimal("0")))
        .where(
            models.SetPiece.set_id == tool.id,
            models.SetPiece.kind == "addon",
            models.SetPiece.status.notin_(_GONE_PIECE_STATUSES),
        )
        .correlate(tool)
        .scalar_subquery()
    )
    attached_sum = (
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(attached.purchase_price, Decimal("0"))
                    * func.coalesce(attached.quantity, 1)
                ),
                Decimal("0"),
            )
        )
        .where(attached.attached_to_set_id == tool.id)
        .correlate(tool)
        .scalar_subquery()
    )
    own = func.coalesce(tool.purchase_price, Decimal("0")) * func.coalesce(
        tool.quantity, 1
    )
    return case(
        (tool.is_set.is_(True), own + addon_sum + attached_sum),
        else_=tool.purchase_price * func.coalesce(tool.quantity, 1),
    )


def _key_expression(model, sort: str | None, ts_query=None):  # noqa: ANN001
    """The SQL expression one sort key reads for a Tool/Battery
    row. Text keys are lowercased with empty text folded to NULL
    (Package B treated "" like missing: it sorts last). sort=None
    is the default order: full-text rank when a query drives it,
    else DATE ADDED, newest first (owner spec 2026-10-25 — was
    newest-touched/updated_at before)."""
    if sort == "price":
        if model is models.Tool:
            return _tool_extended_price_expression()
        return model.purchase_price * func.coalesce(model.quantity, 1)
    if sort in ("name", "brand", "category", "location"):
        column = getattr(model, sort)
        return func.nullif(func.lower(func.coalesce(column, "")), "")
    if sort == "purchase_date":
        return model.purchase_date
    if sort == "created_at":
        return model.created_at
    if sort == "updated_at":
        return model.updated_at
    if sort == "featured":
        # The pairs builders special-case this key (they also read
        # the attachments column); this expression only keeps any
        # other caller sane.
        return model.updated_at
    if sort == "dealer":
        # The pairs builders special-case this key too (the name
        # lives on dealer_companies, resolved in one batch query);
        # this only keeps any other caller sane.
        return model.created_at
    if ts_query is not None:
        return func.ts_rank_cd(model.search_vector, ts_query)
    return model.created_at


def _has_photo(record) -> bool:
    return any(
        isinstance(a, dict) and a.get("kind") == "photo"
        for a in (record.attachments or [])
    )


def _featured_key(record):
    """(has_photo, updated_at) — compared descending by merge_pairs,
    so photo items lead and recency orders inside each group."""
    return (1 if _has_photo(record) else 0, record.updated_at)


def _python_key_tool(db: Session, tool: models.Tool, sort: str | None):
    """The sort key of one tool computed in Python — used for the
    set-content matches, which the SQL path never sees."""
    if sort is None:
        return None  # legacy order: content matches trail (as before)
    if sort == "featured":
        return _featured_key(tool)
    if sort in ("name", "brand", "category", "location"):
        value = (getattr(tool, sort) or "").lower()
        return value or None
    if sort == "dealer":
        name = service.dealer_company_name(
            db, tool.dealer_company_id, perspective_id=tool.owner_id
        )
        return (name or "").strip().lower() or None
    if sort == "purchase_date":
        return tool.purchase_date
    if sort == "warranty_end":
        return service.warranty_end_date_of(tool)
    if sort == "price":
        if tool.is_set:
            members = service.resolve_set_members(db, tool, include_addons=True)
            return members["price_total"]
        if tool.purchase_price is None:
            return None
        return tool.purchase_price * (tool.quantity or 1)
    return getattr(tool, sort)


def _python_key_battery(
    battery: models.Battery, sort: str | None, dealer_names: dict | None = None
):
    if sort is None:
        return None
    if sort == "featured":
        return _featured_key(battery)
    if sort in ("name", "brand", "category", "location"):
        value = (getattr(battery, sort) or "").lower()
        return value or None
    if sort == "dealer":
        # Names are resolved by the caller in one batch query
        # (battery rows carry no db handle here).
        if dealer_names is None or battery.dealer_company_id is None:
            return None
        return dealer_names.get(battery.dealer_company_id)
    if sort == "purchase_date":
        return battery.purchase_date
    if sort == "warranty_end":
        return service.warranty_end_date_of(battery)
    if sort == "price":
        if battery.purchase_price is None:
            return None
        return battery.purchase_price * (battery.quantity or 1)
    return getattr(battery, sort)


def tool_pairs(
    db: Session,
    owner_id: uuid.UUID,
    q: str | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    min_replacement: Decimal | None = None,
    max_replacement: Decimal | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    location_ids: set[uuid.UUID] | None = None,
    standing: str | None = None,
    dealer_id: uuid.UUID | None = None,
    sort: str | None = None,
    sort_dir: str | None = None,
    only_tool_ids: set[uuid.UUID] | None = None,
    extended_price_range: tuple[Decimal | None, Decimal | None] | None = None,
    seq_base: int = 0,
    warranty: str | None = None,
):
    """(pairs, marks) for the owner's filtered tools: pairs are
    (sort_key, seq, tool_id) over the WHOLE filtered set; marks
    maps set-content-matched tool ids to their marked rows (the
    serializer reads `_matched_via` / `_matched_label` off them).
    The WHERE half is search_tools' own — one filter truth."""
    stmt = select(models.Tool).where(
        models.Tool.owner_id == owner_id,
        models.Tool.attached_to_set_id.is_(None),
        # REPLACED items are retired (see search_tools).
        models.Tool.standing.is_distinct_from(models.STANDING_REPLACED),
    )
    if only_tool_ids is not None:
        stmt = stmt.where(models.Tool.id.in_(only_tool_ids))
    has_query = bool(q and q.strip())
    ts_query = None
    if has_query and db.bind is not None and db.bind.dialect.name == "postgresql":
        ts_query = func.websearch_to_tsquery("english", q.strip())
        stmt = stmt.where(models.Tool.search_vector.op("@@")(ts_query))
    if category:
        stmt = stmt.where(models.Tool.category == category)
    if standing:
        # The standing column IS the authority (Package B): exact
        # match, no derivation. Added for smart search (wave 4).
        stmt = stmt.where(models.Tool.standing == standing)
    if dealer_id is not None:
        stmt = stmt.where(models.Tool.dealer_company_id == dealer_id)
    if location:
        stmt = stmt.where(
            func.lower(models.Tool.location) == location.strip().lower()
        )
    if location_ids is not None:
        stmt = stmt.where(models.Tool.location_id.in_(location_ids))
    if min_price is not None:
        stmt = stmt.where(models.Tool.purchase_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(models.Tool.purchase_price <= max_price)
    if min_replacement is not None:
        stmt = stmt.where(models.Tool.replacement_cost >= min_replacement)
    if max_replacement is not None:
        stmt = stmt.where(models.Tool.replacement_cost <= max_replacement)
    if date_from is not None:
        stmt = stmt.where(models.Tool.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(models.Tool.purchase_date <= date_to)
    if extended_price_range is not None:
        price_expr = _tool_extended_price_expression()
        lo, hi = extended_price_range
        if lo is not None:
            stmt = stmt.where(price_expr >= lo)
        if hi is not None:
            stmt = stmt.where(price_expr <= hi)

    descending = sort_descending(sort, sort_dir)
    pairs: list[tuple[object, int, uuid.UUID]] = []
    if warranty or sort == "warranty_end":
        # Derived warranty standing/end (F5-02): computed in Python
        # over a bounded superset, like the battery path below.
        # "due" is the combined Home-counter view: expired OR
        # expiring soon.
        rows = list(db.scalars(stmt.limit(1000)))
        if warranty:
            rows = [
                r
                for r in rows
                if _warranty_matches(service.tool_warranty_status(r), warranty)
            ]
        return (
            [
                (_python_key_tool(db, r, sort or "warranty_end"), seq_base + seq, r.id)
                for seq, r in enumerate(rows)
            ],
            {},
        )
    if not (has_query and ts_query is None):
        # Off Postgres a text query has no vector to match (the
        # legacy path returns only set-content matches there too).
        if sort == "featured":
            # Photo-ness lives in the attachments JSON, so the key
            # is computed in Python over (id, updated_at, attachments).
            feat_stmt = stmt.with_only_columns(
                models.Tool.id, models.Tool.updated_at, models.Tool.attachments
            ).order_by(models.Tool.updated_at.desc())
            for seq, (row_id, updated, atts) in enumerate(db.execute(feat_stmt)):
                has = any(
                    isinstance(a, dict) and a.get("kind") == "photo"
                    for a in (atts or [])
                )
                pairs.append(((1 if has else 0, updated), seq_base + seq, row_id))
        elif sort == "dealer":
            # The dealer's NAME lives on dealer_companies: pull the
            # filtered set's tags and resolve the names in one
            # query. Untagged items fold to None and trail (the
            # sort convention); same-dealer ties run newest first,
            # like the featured branch's inner order.
            tag_stmt = stmt.with_only_columns(
                models.Tool.id, models.Tool.dealer_company_id
            ).order_by(models.Tool.created_at.desc())
            tag_rows = list(db.execute(tag_stmt))
            names = _dealer_name_map(db, [cid for _rid, cid in tag_rows], owner_id)
            for seq, (row_id, company_id) in enumerate(tag_rows):
                pairs.append((names.get(company_id), seq_base + seq, row_id))
        else:
            key_expr = _key_expression(models.Tool, sort, ts_query)
            key_stmt = stmt.with_only_columns(models.Tool.id, key_expr.label("k"))
            key_stmt = key_stmt.order_by(
                key_expr.desc() if descending else key_expr.asc()
            )
            for seq, (row_id, key) in enumerate(db.execute(key_stmt)):
                pairs.append((key, seq_base + seq, row_id))
    marks: dict[uuid.UUID, models.Tool] = {}
    if has_query:
        seen = {row_id for _k, _s, row_id in pairs}
        for set_tool in _set_content_matches(db, owner_id, q.strip(), only_tool_ids):
            if set_tool.id in seen:
                continue
            if category and set_tool.category != category:
                continue
            if standing and set_tool.standing != standing:
                continue
            if location and set_tool.location.strip().lower() != location.strip().lower():
                continue
            if location_ids is not None and set_tool.location_id not in location_ids:
                continue
            if dealer_id is not None and set_tool.dealer_company_id != dealer_id:
                continue
            marks[set_tool.id] = set_tool
            key = _python_key_tool(db, set_tool, sort)
            pairs.append((key, seq_base + len(pairs), set_tool.id))
    return pairs, marks


def search_tools_paged(
    db: Session,
    owner_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    **filters,
) -> tuple[list[models.Tool], int]:
    """search_tools with server-side ordering + offset paging over
    the whole filtered set. Returns (page_rows, total_count)."""
    pairs, marks = tool_pairs(db, owner_id, **filters)
    descending = sort_descending(filters.get("sort"), filters.get("sort_dir"))
    page_ids, total = merge_pairs(pairs, descending, offset, limit)
    rows = fetch_in_order(db, models.Tool, page_ids)
    for row in rows:
        marked = marks.get(row.id)
        if marked is not None:
            row._matched_via = marked._matched_via  # noqa: SLF001
            row._matched_label = marked._matched_label  # noqa: SLF001
    return rows, total


def battery_pairs(
    db: Session,
    owner_id: uuid.UUID,
    q: str | None = None,
    platform: str | None = None,
    warranty: str | None = None,
    category: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    location: str | None = None,
    location_ids: set[uuid.UUID] | None = None,
    standing: str | None = None,
    dealer_id: uuid.UUID | None = None,
    sort: str | None = None,
    sort_dir: str | None = None,
    only_battery_ids: set[uuid.UUID] | None = None,
    extended_price_range: tuple[Decimal | None, Decimal | None] | None = None,
    seq_base: int = 0,
):
    """(pairs) for the owner's filtered batteries — battery_pairs
    is tool_pairs' twin. The warranty filter stays the
    derived-status Python filter over the same bounded superset
    the legacy path uses (the status is computed, never a column)."""
    stmt = select(models.Battery).where(
        models.Battery.owner_id == owner_id,
        # REPLACED items are retired (see search_tools).
        models.Battery.standing.is_distinct_from(models.STANDING_REPLACED),
    )
    if only_battery_ids is not None:
        stmt = stmt.where(models.Battery.id.in_(only_battery_ids))
    has_query = bool(q and q.strip())
    ts_query = None
    if has_query and db.bind is not None and db.bind.dialect.name == "postgresql":
        ts_query = func.websearch_to_tsquery("english", q.strip())
        stmt = stmt.where(models.Battery.search_vector.op("@@")(ts_query))
    if platform:
        stmt = stmt.where(
            func.lower(models.Battery.platform) == platform.strip().lower()
        )
    if category:
        stmt = stmt.where(models.Battery.category == category)
    if standing:
        stmt = stmt.where(models.Battery.standing == standing)
    if dealer_id is not None:
        stmt = stmt.where(models.Battery.dealer_company_id == dealer_id)
    if location:
        stmt = stmt.where(
            func.lower(models.Battery.location) == location.strip().lower()
        )
    if location_ids is not None:
        stmt = stmt.where(models.Battery.location_id.in_(location_ids))
    if min_price is not None:
        stmt = stmt.where(models.Battery.purchase_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(models.Battery.purchase_price <= max_price)
    if date_from is not None:
        stmt = stmt.where(models.Battery.purchase_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(models.Battery.purchase_date <= date_to)
    if extended_price_range is not None:
        price_expr = models.Battery.purchase_price * func.coalesce(
            models.Battery.quantity, 1
        )
        lo, hi = extended_price_range
        if lo is not None:
            stmt = stmt.where(price_expr >= lo)
        if hi is not None:
            stmt = stmt.where(price_expr <= hi)

    descending = sort_descending(sort, sort_dir)
    if warranty or sort == "warranty_end":
        rows = list(db.scalars(stmt.limit(1000)))
        if warranty:
            rows = [
                b
                for b in rows
                if _warranty_matches(service.warranty_status(b), warranty)
            ]
        dealer_names = (
            _dealer_name_map(db, [b.dealer_company_id for b in rows], owner_id)
            if sort == "dealer"
            else None
        )
        return [
            (
                _python_key_battery(b, sort or "warranty_end", dealer_names),
                seq_base + seq,
                b.id,
            )
            for seq, b in enumerate(rows)
        ]
    pairs: list[tuple[object, int, uuid.UUID]] = []
    if not (has_query and ts_query is None):
        if sort == "featured":
            feat_stmt = stmt.with_only_columns(
                models.Battery.id, models.Battery.updated_at, models.Battery.attachments
            ).order_by(models.Battery.updated_at.desc())
            for seq, (row_id, updated, atts) in enumerate(db.execute(feat_stmt)):
                has = any(
                    isinstance(a, dict) and a.get("kind") == "photo"
                    for a in (atts or [])
                )
                pairs.append(((1 if has else 0, updated), seq_base + seq, row_id))
            return pairs
        if sort == "dealer":
            # Tool pairs' twin: names resolved in one batch query;
            # untagged batteries trail; ties run newest first.
            tag_stmt = stmt.with_only_columns(
                models.Battery.id, models.Battery.dealer_company_id
            ).order_by(models.Battery.created_at.desc())
            tag_rows = list(db.execute(tag_stmt))
            names = _dealer_name_map(db, [cid for _rid, cid in tag_rows], owner_id)
            for seq, (row_id, company_id) in enumerate(tag_rows):
                pairs.append((names.get(company_id), seq_base + seq, row_id))
            return pairs
        key_expr = _key_expression(models.Battery, sort, ts_query)
        key_stmt = stmt.with_only_columns(models.Battery.id, key_expr.label("k"))
        key_stmt = key_stmt.order_by(
            key_expr.desc() if descending else key_expr.asc()
        )
        for seq, (row_id, key) in enumerate(db.execute(key_stmt)):
            pairs.append((key, seq_base + seq, row_id))
    return pairs


def search_batteries_paged(
    db: Session,
    owner_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    **filters,
) -> tuple[list[models.Battery], int]:
    """search_batteries with server-side ordering + offset paging.
    Returns (page_rows, total_count)."""
    pairs = battery_pairs(db, owner_id, **filters)
    descending = sort_descending(filters.get("sort"), filters.get("sort_dir"))
    page_ids, total = merge_pairs(pairs, descending, offset, limit)
    return fetch_in_order(db, models.Battery, page_ids), total
