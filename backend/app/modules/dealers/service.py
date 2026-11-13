"""Dealers service — companies (directory + private), private agent
records, and preferred-agent links.

Visibility rules (owner, 2026-10-18):
  - Directory companies (owner_id NULL) are visible to everyone.
  - Private companies and private agents belong to their owner —
    nobody else can see, reference (as an item tag / preference),
    or even confirm they exist (404, never 403, so ids don't leak).
  - Platform agents link by EXACT account number lookup only: there
    is no browse/search of users anywhere in this module.
"""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.storage import StorageError, storage
from app.modules.core import models as core_models
from app.modules.dealers import models
from app.modules.dealers.agent_codes import generate_agent_code
from app.modules.inventory import logo_thumbs


class DealerError(ValueError):
    """A user-facing refusal; routes translate it to HTTP.
    status_code defaults to 422 (a rule refusal); services pass
    404 for the doesn't-exist-or-isn't-yours cases so existence
    never leaks through a different answer."""

    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


#: The logo rendition width every logo slot serves. Directory
#: tiles render ~100px and the Home widget strips smaller;
#: 320 is the inventory tile width and leaves retina headroom
#: without shipping harvested originals (multi-MB phone-site
#: PNGs) into slots a tenth their size.
LOGO_VARIANT_WIDTH = 320


def logo_url_for(logo_key: str | None) -> str | None:
    """Mint a read URL for a company's stored logo (platform asset).

    Serves the 320px rendition when one exists — generated
    lazily on first read by inventory.logo_thumbs, the
    alpha-preserving flavor, because the JPEG photo pipeline
    would flatten a transparent logo onto black — and the
    original otherwise (SVG marks, undecodable files, storage
    trouble: today's behavior, exactly). The lookup runs
    against the key the CALLER passes, which at every call
    site is the EFFECTIVE logo key for the viewer: the
    personal-edit overlay re-mints the URL from the edited
    key (see _apply_personal_edit), so an override serves
    its own rendition, never the directory logo's.

    Signing is offline; a missing object surfaces as a broken image
    the client swaps for the text tile."""
    if not logo_key:
        return None
    serve_key = logo_key
    try:
        variant = logo_thumbs.rendition(logo_key, LOGO_VARIANT_WIDTH)
        if variant:
            serve_key = variant
    except Exception:
        serve_key = logo_key  # rendition trouble never breaks a read
    try:
        return storage.presigned_get_url(serve_key)
    except StorageError:
        return None


# ---------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------


def _customer_service_phone(phones: list) -> str:
    """The warranty block's "customer service" line: the entry
    the directory labels Customer Service, else the first listed
    number (Snap-on's customer care rides its corporate line)."""
    return next(
        (p.get("number", "") for p in phones if p.get("label") == "Customer Service"),
        phones[0].get("number", "") if phones else "",
    )


def serialize_company(
    company: models.DealerCompany,
    edit: "models.DealerCompanyPersonalEdit | None" = None,
) -> dict:
    process = company.warranty_process or {}
    phones = list(company.phones or [])
    cs_phone = _customer_service_phone(phones)
    view = {
        "id": company.id,
        "name": company.name,
        "email": company.email,
        "website": company.website,
        "address": company.address,
        "phones": phones,
        "notes": company.notes,
        "is_directory": bool(company.is_directory),
        "is_mine": company.owner_id is not None,
        # Corporate directory data (2026-10-19). ship_to_* stays
        # None unless the brand officially publishes a warranty
        # mail-in address — see models.DealerCompany.
        "kind": company.kind or "manufacturer",
        "warranty_url": company.warranty_url or "",
        "official_flyer_url": company.official_flyer_url or "",
        "warranty_phone": company.warranty_phone,
        "customer_service_phone": cs_phone or None,
        "ship_to_name": company.ship_to_name,
        "ship_to_address": company.ship_to_address,
        "ship_to_scope": company.ship_to_scope,
        "ship_to_scope_note": company.ship_to_scope_note,
        "warranty_process": {
            "gate": process.get("gate"),
            "notes": list(process.get("notes") or []),
        }
        if company.warranty_process is not None
        else None,
        "logo_key": company.logo_key,
        "logo_url": logo_url_for(company.logo_key),
        "logo_tile": company.logo_tile,
        "created_at": company.created_at,
        "updated_at": company.updated_at,
        # The viewer's personal layer (2026-11-05): None unless
        # an edit row was applied over the directory values.
        "personal_edit": None,
    }
    if edit is not None:
        _apply_personal_edit(view, edit)
    return view


# ---------------------------------------------------------------------
# Personal edits (owner, 2026-11-05): a viewer's own details for
# a DIRECTORY dealer — his values win everywhere HE sees that
# dealer; the directory row and everyone else stay untouched.
# ---------------------------------------------------------------------

#: The fields a personal edit may override — the company form's
#: identity/contact subset. The corporate warranty block is
#: researched directory data and is never overlayable.
PERSONAL_EDIT_FIELDS = (
    "name",
    "email",
    "website",
    "address",
    "phones",
    "notes",
    "logo_key",
    "logo_tile",
)


def get_personal_edit(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> "models.DealerCompanyPersonalEdit | None":
    return (
        db.query(models.DealerCompanyPersonalEdit)
        .filter(
            models.DealerCompanyPersonalEdit.user_id == user_id,
            models.DealerCompanyPersonalEdit.company_id == company_id,
        )
        .first()
    )


def personal_edits_for(
    db: Session, user_id: uuid.UUID | None, company_ids
) -> "dict[uuid.UUID, models.DealerCompanyPersonalEdit]":
    """Batch overlay load for list reads: {(company id): edit}
    for the companies this viewer has edited. One query for the
    whole page — never one per row."""
    ids = {cid for cid in company_ids if cid is not None}
    if user_id is None or not ids:
        return {}
    rows = (
        db.query(models.DealerCompanyPersonalEdit)
        .filter(
            models.DealerCompanyPersonalEdit.user_id == user_id,
            models.DealerCompanyPersonalEdit.company_id.in_(ids),
        )
        .all()
    )
    return {row.company_id: row for row in rows}


def personal_edit_values(edit: "models.DealerCompanyPersonalEdit") -> dict:
    """{field: value} for the fields this edit actually
    overrides (a NULL column = no override; for the logo pair
    an override of "" is a real one — the user cleared it)."""
    return {
        field: getattr(edit, field)
        for field in PERSONAL_EDIT_FIELDS
        if getattr(edit, field) is not None
    }


def _apply_personal_edit(view: dict, edit: "models.DealerCompanyPersonalEdit") -> None:
    values = personal_edit_values(edit)
    for field, value in values.items():
        if field == "phones":
            phones = [dict(p) for p in value]
            view["phones"] = phones
            view["customer_service_phone"] = (
                _customer_service_phone(phones) or None
            )
        elif field == "logo_key":
            view["logo_key"] = value or None
            view["logo_url"] = logo_url_for(view["logo_key"])
        elif field == "logo_tile":
            view["logo_tile"] = value or None
        else:
            view[field] = value
    view["personal_edit"] = {"fields": sorted(values)}


def serialize_company_for_viewer(
    db: Session,
    company: models.DealerCompany,
    viewer_id: uuid.UUID | None,
    *,
    edit: "models.DealerCompanyPersonalEdit | None" = None,
) -> dict:
    """serialize_company with the viewer's personal layer
    applied (directory companies only — a private company is
    its owner's own record and takes the direct edit instead).
    `edit` may be pre-loaded by batch callers; otherwise it is
    looked up here. viewer None = the raw directory view."""
    if edit is None and viewer_id is not None and company.is_directory:
        edit = get_personal_edit(db, viewer_id, company.id)
    return serialize_company(company, edit=edit)


def personal_company_name(
    db: Session, user_id: uuid.UUID | None, company: models.DealerCompany | None
) -> str:
    """A company's name AS THIS USER SEES IT — the name the
    cross-module dealer-name reads (item pages, claims, truck
    surfaces) resolve through, so a personal rename follows the
    dealer everywhere in his own view. Raw name for own
    companies, other perspectives, and no override."""
    if company is None:
        return ""
    if user_id is None or not company.is_directory:
        return company.name
    edit = get_personal_edit(db, user_id, company.id)
    if edit is not None and edit.name:
        return edit.name
    return company.name


def personal_name_map(
    db: Session, user_id: uuid.UUID | None, company_ids
) -> dict:
    """{company id: the name THIS user sees} — only for the
    companies he actually renamed (batch companion to
    personal_company_name for map-shaped reads)."""
    ids = {cid for cid in company_ids if cid is not None}
    if user_id is None or not ids:
        return {}
    rows = (
        db.query(models.DealerCompanyPersonalEdit)
        .filter(
            models.DealerCompanyPersonalEdit.user_id == user_id,
            models.DealerCompanyPersonalEdit.company_id.in_(ids),
            models.DealerCompanyPersonalEdit.name.isnot(None),
        )
        .all()
    )
    return {row.company_id: row.name for row in rows if row.name}


def personal_logo_map(
    db: Session, user_id: uuid.UUID | None, company_ids
) -> dict:
    """{company id: the logo key THIS user sees} — only for
    the companies whose logo he actually overrode (batch
    companion to personal_name_map for map-shaped reads
    that mint logo URLs per row, e.g. near-you). Unlike
    names, a logo override of "" is a REAL override (the
    user cleared it), so it maps to None: the answer is
    "no logo for this viewer", never "fall back to the
    directory's"."""
    ids: set[uuid.UUID] = set()
    for cid in company_ids:
        if cid is None:
            continue
        try:
            ids.add(uuid.UUID(str(cid)))
        except (ValueError, TypeError):
            continue
    if user_id is None or not ids:
        return {}
    rows = (
        db.query(models.DealerCompanyPersonalEdit)
        .filter(
            models.DealerCompanyPersonalEdit.user_id == user_id,
            models.DealerCompanyPersonalEdit.company_id.in_(ids),
            models.DealerCompanyPersonalEdit.logo_key.isnot(None),
        )
        .all()
    )
    return {row.company_id: row.logo_key or None for row in rows}


def _phones_key(phones) -> list:
    return [
        (str(p.get("label", "")), str(p.get("number", "")))
        for p in (phones or [])
    ]


def save_personal_edit(
    db: Session,
    user_id: uuid.UUID,
    company: models.DealerCompany,
    data: dict,
) -> "models.DealerCompanyPersonalEdit | None":
    """Save the viewer's personal details for a DIRECTORY
    company. `data` is the personal-fields payload; it merges
    over the directory record and runs through the company
    form's own cleaner, so validation (name required, kind /
    ship-to rules on the merged record, phone shaping) is the
    same code the direct edit answers to. Only fields that
    DIFFER from the directory values are stored; a field saved
    back to the directory value drops its override, and when
    nothing differs any more the edit row goes away entirely
    (returns None)."""
    if not company.is_directory:
        raise DealerError(
            "This is your own company — Edit company there saves "
            "the record itself, so there's no separate personal copy."
        )
    merged = {
        **serialize_company(company),
        **{k: data[k] for k in PERSONAL_EDIT_FIELDS if k in data},
    }
    cleaned = _clean_company_fields(merged)
    if not cleaned["name"]:
        raise DealerError("A company needs a name.")
    overrides: dict = {}
    for field in PERSONAL_EDIT_FIELDS:
        new = cleaned[field]
        old = getattr(company, field)
        if field == "phones":
            if _phones_key(new) != _phones_key(old):
                overrides[field] = new
        elif field in ("logo_key", "logo_tile"):
            # Blank is a value here: clearing the logo is an
            # override of "" ("show me no logo"), distinct from
            # no override at all.
            if (new or "") != (old or ""):
                overrides[field] = new if new else ""
        elif new != old:
            overrides[field] = new
    row = get_personal_edit(db, user_id, company.id)
    if not overrides:
        if row is not None:
            db.delete(row)
            db.commit()
        return None
    if row is None:
        row = models.DealerCompanyPersonalEdit(
            user_id=user_id, company_id=company.id
        )
        db.add(row)
    for field in PERSONAL_EDIT_FIELDS:
        setattr(row, field, overrides.get(field))
    db.commit()
    db.refresh(row)
    return row


def clear_personal_edit(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> bool:
    """Reset: drop the viewer's personal layer for a company —
    he sees the directory details again. True when a row went."""
    row = get_personal_edit(db, user_id, company_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def serialize_personal_edit(
    db: Session, edit: "models.DealerCompanyPersonalEdit"
) -> dict:
    """The export shape: the raw override values plus the
    directory company's current name for orientation."""
    company = db.get(models.DealerCompany, edit.company_id)
    return {
        "company_id": edit.company_id,
        "directory_name": company.name if company is not None else "",
        "overrides": personal_edit_values(edit),
        "created_at": edit.created_at,
        "updated_at": edit.updated_at,
    }


def visible_company(db: Session, user_id: uuid.UUID, company_id: uuid.UUID):
    """The company if THIS user may see it (directory or their own),
    else None."""
    company = db.get(models.DealerCompany, company_id)
    if company is None:
        return None
    if company.is_directory or company.owner_id == user_id:
        return company
    return None


def list_companies(
    db: Session, user_id: uuid.UUID, q: str | None = None
) -> list[models.DealerCompany]:
    query = db.query(models.DealerCompany).filter(
        (models.DealerCompany.is_directory.is_(True))
        | (models.DealerCompany.owner_id == user_id)
    )
    if q:
        query = query.filter(models.DealerCompany.name.ilike(f"%{q.strip()}%"))
    # Directory first, alphabetical inside each half.
    rows = (
        query.order_by(
            models.DealerCompany.is_directory.desc(), models.DealerCompany.name.asc()
        )
        .all()
    )
    if q and q.strip():
        # Personal edits (2026-11-05): a dealer the viewer
        # renamed for himself must answer to HIS name in his
        # search too — merge in the directory companies whose
        # personal name for this viewer matches, then restore
        # the directory-first / alphabetical order.
        needle = f"%{q.strip()}%"
        edited_ids = [
            row.company_id
            for row in db.query(models.DealerCompanyPersonalEdit)
            .filter(
                models.DealerCompanyPersonalEdit.user_id == user_id,
                models.DealerCompanyPersonalEdit.name.ilike(needle),
            )
            .all()
        ]
        have = {c.id for c in rows}
        extra = [
            company
            for company_id in edited_ids
            if company_id not in have
            for company in [visible_company(db, user_id, company_id)]
            if company is not None
        ]
        if extra:
            rows = sorted(
                [*rows, *extra],
                key=lambda c: (not c.is_directory, c.name.lower()),
            )
    return rows


def _clean_warranty_process(raw) -> dict | None:
    """Normalize the warranty process payload: a gate string (the
    required first step when there is no mail-in address) plus a
    list of short process facts. Empty in, None out — a company
    with no warranty data carries no process block at all."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DealerError("Warranty process must be an object.")
    gate = str(raw.get("gate") or "").strip() or None
    notes = [str(n).strip() for n in (raw.get("notes") or []) if str(n).strip()]
    if gate is None and not notes:
        return None
    return {"gate": gate, "notes": notes}


def _clean_logo_tile(raw) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value not in ("dark", "light"):
        raise DealerError("Logo tile must be 'dark' or 'light'.")
    return value


def _clean_company_fields(data: dict) -> dict:
    phones = []
    for entry in data.get("phones") or []:
        label = str(entry.get("label", "")).strip()
        number = str(entry.get("number", "")).strip()
        if label and number:
            phones.append({"label": label, "number": number})

    def _opt_text(key: str) -> str | None:
        value = data.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    scope = _opt_text("ship_to_scope")
    if scope is not None and scope not in ("general", "scoped"):
        raise DealerError("Ship-to scope must be 'general' or 'scoped'.")
    kind = str(data.get("kind") or "manufacturer").strip()
    if kind not in ("manufacturer", "retailer"):
        raise DealerError("Company kind must be 'manufacturer' or 'retailer'.")
    return {
        "name": str(data.get("name", "")).strip(),
        "email": str(data.get("email", "")).strip(),
        "website": str(data.get("website", "")).strip(),
        "address": str(data.get("address", "")).strip(),
        "phones": phones,
        "notes": str(data.get("notes", "")).strip(),
        "kind": kind,
        "warranty_url": str(data.get("warranty_url") or "").strip(),
        "official_flyer_url": str(
            data.get("official_flyer_url") or ""
        ).strip(),
        "warranty_phone": _opt_text("warranty_phone"),
        "ship_to_name": _opt_text("ship_to_name"),
        "ship_to_address": _opt_text("ship_to_address"),
        "ship_to_scope": scope,
        "ship_to_scope_note": _opt_text("ship_to_scope_note"),
        "warranty_process": _clean_warranty_process(data.get("warranty_process")),
        "logo_key": _opt_text("logo_key"),
        "logo_tile": _clean_logo_tile(data.get("logo_tile")),
    }


def create_company(
    db: Session, *, owner_id: uuid.UUID | None, data: dict
) -> models.DealerCompany:
    fields = _clean_company_fields(data)
    if not fields["name"]:
        raise DealerError("A company needs a name.")
    company = models.DealerCompany(
        owner_id=owner_id,
        is_directory=owner_id is None,
        **fields,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def update_company(
    db: Session, company: models.DealerCompany, data: dict
) -> models.DealerCompany:
    fields = _clean_company_fields({**serialize_company(company), **data})
    if not fields["name"]:
        raise DealerError("A company needs a name.")
    for key, value in fields.items():
        setattr(company, key, value)
    db.commit()
    db.refresh(company)
    return company


def delete_company(db: Session, company: models.DealerCompany) -> None:
    # Audit trail (2026-10-19): the references the FK would have
    # nulled/cascaded silently are cleared as ORM writes first, so
    # each one lands in the owner's change journal and a restore
    # of the company brings them back with it — the owner's own
    # preference rows, their agents' company links, and their
    # items' dealer tags (inventory models via the lazy import,
    # core's cascade discipline). The FK behaviors (preferences
    # CASCADE, tags SET NULL) remain the backstop for anything
    # owned by somebody else.
    if company.owner_id is not None:
        owner_id = company.owner_id
        for row in (
            db.query(models.PreferredAgent)
            .filter(
                models.PreferredAgent.user_id == owner_id,
                models.PreferredAgent.company_id == company.id,
            )
            .all()
        ):
            db.delete(row)
        for agent in (
            db.query(models.PrivateAgent)
            .filter(
                models.PrivateAgent.owner_id == owner_id,
                models.PrivateAgent.company_id == company.id,
            )
            .all()
        ):
            agent.company_id = None
        from app.modules.inventory import models as inventory_models

        for record_model in (inventory_models.Tool, inventory_models.Battery):
            for record in (
                db.query(record_model)
                .filter(
                    record_model.owner_id == owner_id,
                    record_model.dealer_company_id == company.id,
                )
                .all()
            ):
                record.dealer_company_id = None
    db.delete(company)
    db.commit()


def get_own_private_company(db: Session, user_id: uuid.UUID, company_id: uuid.UUID):
    company = db.get(models.DealerCompany, company_id)
    if company is None or company.is_directory or company.owner_id != user_id:
        return None
    return company


def get_directory_company(db: Session, company_id: uuid.UUID):
    company = db.get(models.DealerCompany, company_id)
    if company is None or not company.is_directory:
        return None
    return company


# ---------------------------------------------------------------------
# Private agents
# ---------------------------------------------------------------------


def serialize_private_agent(db: Session, agent: models.PrivateAgent) -> dict:
    company = db.get(models.DealerCompany, agent.company_id) if agent.company_id else None
    return {
        "id": agent.id,
        "company_id": agent.company_id,
        "company_name": personal_company_name(db, agent.owner_id, company),
        "name": agent.name,
        "phone": agent.phone,
        "email": agent.email,
        "notes": agent.notes,
        # The record fields (stage 1, 2026-11-04): route area,
        # the route schedule triple, and the tenure pair.
        "location": agent.location or "",
        "route_frequency": agent.route_frequency,
        "route_day_of_week": agent.route_day_of_week,
        "route_anchor_date": agent.route_anchor_date,
        "started_at": agent.started_at,
        "ended_at": agent.ended_at,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }


def list_private_agents(db: Session, user_id: uuid.UUID) -> list[models.PrivateAgent]:
    return (
        db.query(models.PrivateAgent)
        .filter(models.PrivateAgent.owner_id == user_id)
        .order_by(models.PrivateAgent.name.asc())
        .all()
    )


def get_own_private_agent(db: Session, user_id: uuid.UUID, agent_id: uuid.UUID):
    agent = db.get(models.PrivateAgent, agent_id)
    if agent is None or agent.owner_id != user_id:
        return None
    return agent


def _resolve_agent_company(db: Session, user_id: uuid.UUID, company_id):
    """Validate an agent/preference company reference: the company
    must be visible to the user (directory or their own private)."""
    if company_id is None:
        return None
    company = visible_company(db, user_id, company_id)
    if company is None:
        raise DealerError("That company isn't available to your account.")
    return company


def _as_date(value) -> date | None:
    """Normalize a payload date: date/datetime/ISO string/None
    all land as a plain date (tenure and route anchors are
    day-granular)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise DealerError("That date doesn't read — use YYYY-MM-DD.")


def _clean_route_fields(data: dict) -> dict:
    """The route schedule triple from a payload (stage 1). The
    frequency words are AgentProfile's own (weekly / biweekly /
    monthly); "" / "na" / None all mean no route — the triple
    clears together, so a record never carries half a schedule
    pointing nowhere. A real frequency may still be partial
    (weekday or anchor missing): next-visit then honestly
    computes to nothing until the facts are complete."""
    from app.modules.dealers.route_days import ROUTE_FREQUENCIES

    raw = data.get("route_frequency")
    frequency = str(raw).strip().lower() if raw is not None else None
    if frequency in ("", "na", "n/a", "none"):
        frequency = None
    if frequency is not None and frequency not in ROUTE_FREQUENCIES:
        raise DealerError(
            "Route frequency must be Weekly, Bi-weekly, Monthly, or N/A."
        )
    if frequency is None:
        return {
            "route_frequency": None,
            "route_day_of_week": None,
            "route_anchor_date": None,
        }
    weekday = data.get("route_day_of_week")
    if weekday is not None:
        try:
            weekday = int(weekday)
        except (TypeError, ValueError):
            raise DealerError("Route day must be a weekday (Monday–Sunday).")
        if not 0 <= weekday <= 6:
            raise DealerError("Route day must be a weekday (Monday–Sunday).")
    return {
        "route_frequency": frequency,
        "route_day_of_week": weekday,
        "route_anchor_date": _as_date(data.get("route_anchor_date")),
    }


def create_private_agent(db: Session, user_id: uuid.UUID, data: dict) -> models.PrivateAgent:
    name = str(data.get("name", "")).strip()
    if not name:
        raise DealerError("An agent needs a name.")
    company = _resolve_agent_company(db, user_id, data.get("company_id"))
    # The record's agent code (2026-11-03): minted here with an
    # existence check; the model default covers direct-ORM paths.
    code = generate_agent_code()
    while (
        db.query(models.PrivateAgent.id)
        .filter(models.PrivateAgent.agent_code == code)
        .first()
        is not None
    ):
        code = generate_agent_code()
    route = (
        _clean_route_fields(data)
        if any(
            key in data
            for key in ("route_frequency", "route_day_of_week", "route_anchor_date")
        )
        else {
            "route_frequency": None,
            "route_day_of_week": None,
            "route_anchor_date": None,
        }
    )
    agent = models.PrivateAgent(
        owner_id=user_id,
        company_id=company.id if company else None,
        name=name,
        phone=str(data.get("phone", "")).strip(),
        email=str(data.get("email", "")).strip(),
        notes=str(data.get("notes", "")).strip(),
        location=str(data.get("location", "") or "").strip(),
        # Tenure (stage 1): he starts the day the record is
        # entered unless the owner types the real start date.
        started_at=_as_date(data.get("started_at")) or date.today(),
        ended_at=_as_date(data.get("ended_at")),
        agent_code=code,
        **route,
    )
    db.add(agent)
    db.flush()
    if company is not None:
        # A record for a company joins that company's roster in
        # the same motion — and the connection is flagged
        # automatically when the user has no preferred agent
        # for the company yet (owner model, 2026-11-04;
        # multi-preferred connect rule, 2026-11-05).
        _ensure_connection(db, user_id, company.id, private_agent_id=agent.id)
    db.commit()
    db.refresh(agent)
    return agent


def update_private_agent(
    db: Session, user_id: uuid.UUID, agent: models.PrivateAgent, data: dict
) -> models.PrivateAgent:
    if "name" in data:
        name = str(data["name"] or "").strip()
        if not name:
            raise DealerError("An agent needs a name.")
        agent.name = name
    company_changed = False
    if "company_id" in data:
        company = _resolve_agent_company(db, user_id, data["company_id"])
        new_company_id = company.id if company else None
        company_changed = new_company_id != agent.company_id
        agent.company_id = new_company_id
    for key in ("phone", "email", "notes", "location"):
        if key in data:
            setattr(agent, key, str(data[key] or "").strip())
    if any(
        key in data
        for key in ("route_frequency", "route_day_of_week", "route_anchor_date")
    ):
        # Partial edits merge over the record's current schedule
        # (only the frequency can clear the triple — setting it
        # to N/A means "no route").
        route_input = {
            "route_frequency": data.get("route_frequency", agent.route_frequency),
            "route_day_of_week": data.get(
                "route_day_of_week", agent.route_day_of_week
            ),
            "route_anchor_date": data.get(
                "route_anchor_date", agent.route_anchor_date
            ),
        }
        for key, value in _clean_route_fields(route_input).items():
            setattr(agent, key, value)
    for key in ("started_at", "ended_at"):
        if key in data:
            setattr(agent, key, _as_date(data[key]))
    db.flush()
    if company_changed and agent.company_id is not None:
        # Moving a record onto a company puts him on that
        # company's roster (flagged on the same connect rule
        # as a fresh add when nobody there is preferred yet).
        _ensure_connection(
            db, user_id, agent.company_id, private_agent_id=agent.id
        )
    db.commit()
    db.refresh(agent)
    return agent


def delete_private_agent(db: Session, agent: models.PrivateAgent) -> None:
    """Delete one of the owner's private agent records (stage 1,
    2026-11-04). The rules, in the owner's words:

    - A record a real agent has TAKEN OVER or been linked to
      (linked_user_id set) can no longer be deleted — it is that
      agent's working seat now. Refused with the plain reason.
    - Everything attached STAYS PUT: his claims keep his name
      (snapshotted onto them before the record goes — the FK
      then SET NULLs the pointer) and keep rendering under the
      dealer; truck accounts keep their own name snapshot.
      Nothing follows anybody anywhere.
    - If he was one of the preferred, nothing is promoted in
      his place (multi-preferred): the other starred agents
      keep their stars, and the display default re-resolves
      on its own.
    - The agent code dies with the record.
    """
    if agent.linked_user_id is not None:
        raise DealerError(
            "This agent record belongs to a working agent now, so "
            "it can't be deleted. His name stays on your claims "
            "and accounts either way."
        )
    from app.modules.claims import service as claims_service

    # His name lands on his claims and their pointer clears
    # BEFORE the record goes (the claims FK's SET NULL is the
    # backstop, not the mechanism).
    claims_service.detach_claims_from_private_agent(db, agent.id, agent.name)
    # Connection rows pointing at the record are removed as ORM
    # deletes first (journaled — a restore brings them back);
    # the FK CASCADE remains the backstop.
    rows = (
        db.query(models.PreferredAgent)
        .filter(models.PreferredAgent.private_agent_id == agent.id)
        .all()
    )
    for row in rows:
        db.delete(row)
    db.delete(agent)
    db.commit()


# ---------------------------------------------------------------------
# Connections + preferred flags (stage 1, 2026-11-04;
# multi-preferred, owner ruling 2026-11-05)
# ---------------------------------------------------------------------
#
# A PreferredAgent row is a CONNECTION (see the model docstring):
# the roster is every row for (user, company) plus the user's
# own unconnected private records for the company. ANY number
# of rows may carry the preferred flag — starring is per agent
# and independent (set_agent_preferred is the only writer of
# the flag besides connection creation), and there is no
# switch anymore: claims stay seated with the agent who holds
# them, and claim-level re-pointing (claims.set_claim_agent)
# is the one place a seat ever changes hands.
#
# Tenure tracks the CONNECTION, never the star:
#
#   _ensure_connection  a row exists; its creation stamps the
#                       platform row's tenure start, and the
#                       row is flagged automatically ONLY when
#                       the user has no preferred agent for the
#                       company yet;
#   flag changes        never stamp tenure, never move claims;
#   removal             deletes the row — no promotion: the
#                       display default simply re-resolves to
#                       the earliest remaining flagged row
#                       (preferred_row_for / agent_on_record).
def _connection_row(
    db: Session,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
) -> models.PreferredAgent | None:
    return (
        db.query(models.PreferredAgent)
        .filter(
            models.PreferredAgent.user_id == user_id,
            models.PreferredAgent.company_id == company_id,
            models.PreferredAgent.agent_user_id == agent_user_id,
            models.PreferredAgent.private_agent_id == private_agent_id,
        )
        .first()
    )


def preferred_row_for(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> models.PreferredAgent | None:
    """The singular connection row for (user, company): the
    earliest FLAGGED row (multi-preferred: several may be
    flagged; the earliest is the singular resolution), else —
    for data written before the flag or left flagless by an
    account deletion — the earliest row, else None. Mirrors
    claims.agent_on_record's resolution exactly. SUMMARY
    displays read preferred_summary_view instead, which
    classifies none / one / many before naming anyone
    (owner ruling 2026-11-06)."""
    rows = list_preferred(db, user_id, company_id)
    for row in rows:
        if row.is_preferred:
            return row
    return rows[0] if rows else None


def _apply_connection_start(db: Session, row: models.PreferredAgent) -> None:
    """Tenure stamp for a CONNECTION being created (multi-
    preferred: tenure tracks the connection, never the star):
    a platform row's tenure starts today. A private record's
    pair is the record's own data — set when the record is
    created, edited by the owner in the record form — and a
    connection never rewrites it. There is no matching "end"
    stamp: disconnecting deletes the row, and a private
    record's end date is the owner's to type, exactly like its
    start."""
    if row.private_agent_id is None and row.tenure_started_at is None:
        row.tenure_started_at = date.today()


def _ensure_connection(
    db: Session,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
) -> tuple[models.PreferredAgent, bool]:
    """The connection row for this agent, created when missing.
    A NEW connection is flagged preferred automatically ONLY
    when the user has no preferred agent for the company yet
    (the owner's connect rule, 2026-11-05) — with one already
    starred, a new connection joins the roster unstarred and
    the user stars him himself if he wants. Creation also
    stamps the connection's tenure start. Flush only —
    callers commit."""
    existing = _connection_row(
        db,
        user_id,
        company_id,
        agent_user_id=agent_user_id,
        private_agent_id=private_agent_id,
    )
    if existing is not None:
        return existing, False
    row = models.PreferredAgent(
        user_id=user_id,
        company_id=company_id,
        agent_user_id=agent_user_id,
        private_agent_id=private_agent_id,
    )
    has_preferred = (
        db.query(models.PreferredAgent.id)
        .filter(
            models.PreferredAgent.user_id == user_id,
            models.PreferredAgent.company_id == company_id,
            models.PreferredAgent.is_preferred.is_(True),
        )
        .first()
        is not None
    )
    row.is_preferred = not has_preferred
    db.add(row)
    db.flush()
    _apply_connection_start(db, row)
    db.flush()
    return row, True


# ---------------------------------------------------------------------
# Preferred agents
# ---------------------------------------------------------------------


def serialize_preferred(db: Session, row: models.PreferredAgent) -> dict:
    company = db.get(models.DealerCompany, row.company_id)
    view: dict = {
        "id": row.id,
        "company_id": row.company_id,
        "company_name": personal_company_name(db, row.user_id, company),
        "kind": "platform" if row.agent_user_id else "private",
        "agent_user_id": row.agent_user_id,
        "private_agent_id": row.private_agent_id,
        "name": "",
        "phone": "",
        "email": "",
        "account_number": None,
        # The flag + the tenure pair (multi-preferred: any
        # number of rows may carry the flag). For a
        # private row the tenure reads off the RECORD (its own
        # started_at / ended_at); for a platform row off the
        # connection (tenure is per-customer there).
        "is_preferred": bool(row.is_preferred),
        "tenure_started_at": row.tenure_started_at,
        "tenure_ended_at": row.tenure_ended_at,
        "created_at": row.created_at,
        # His next route day, computed from his route schedule
        # exactly as the roster computes it (route_days.
        # next_route_visit) — the directory list row shows it
        # when ONE agent's facts stand in for the dealer's
        # (owner, 2026-11-06). None when he has no complete
        # schedule on record.
        "next_visit": None,
    }
    if row.private_agent_id:
        agent = db.get(models.PrivateAgent, row.private_agent_id)
        if agent is not None:
            from app.modules.dealers.route_days import next_route_visit

            view.update(
                name=agent.name,
                phone=agent.phone,
                email=agent.email,
                tenure_started_at=agent.started_at,
                tenure_ended_at=agent.ended_at,
                next_visit=next_route_visit(
                    agent.route_frequency,
                    agent.route_day_of_week,
                    agent.route_anchor_date,
                ),
            )
    elif row.agent_user_id:
        user = db.get(core_models.User, row.agent_user_id)
        if user is not None:
            view.update(name=user.name, account_number=user.account_number)
        # The agent's phone on record is his profile's — the
        # same fact the roster shows for him (_platform_facts).
        # Surfaces that put ONE contact number on the preferred
        # agent's row (the directory list) read it from here, so
        # a platform agent's number must ride this view too,
        # not just a private record's.
        from app.modules.dealers import portal

        profile = portal.get_profile(db, row.agent_user_id)
        if profile is not None and profile.phone:
            view.update(phone=profile.phone)
        # His email and next route day ride the same profile
        # facts the roster reads (_platform_facts): the
        # directory row stands ONE agent's contact facts in
        # the dealer's place, so a platform agent's email and
        # route day must ride this view too, not just a
        # private record's.
        from app.modules.dealers.route_days import next_route_visit

        facts = _platform_facts(db, row.agent_user_id)
        view.update(
            email=facts["email"],
            next_visit=next_route_visit(
                facts["route_frequency"],
                facts["route_day_of_week"],
                facts["route_anchor_date"],
            ),
        )
    return view


def list_preferred(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID | None = None
) -> list[models.PreferredAgent]:
    query = db.query(models.PreferredAgent).filter(
        models.PreferredAgent.user_id == user_id
    )
    if company_id is not None:
        query = query.filter(models.PreferredAgent.company_id == company_id)
    return query.order_by(
        models.PreferredAgent.created_at.asc(), models.PreferredAgent.id.asc()
    ).all()


def preferred_summary_view(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> dict:
    """The preferred-agent SUMMARY for (user, company) — the
    one resolver every SUMMARY display of "the viewer's
    preferred agent" reads (owner ruling 2026-11-06):

      - MORE THAN ONE row flagged → {"state": "many"}: the
        display names nobody — it shows "Multiple Agents"
        linking to the dealer's Agents tab, and any contact
        fact falls back to the dealer's own;
      - exactly one flagged → {"state": "one", agent: him};
      - none flagged → the standing pre-flag behavior,
        byte-for-byte: the earliest connection row as "one",
        or {"state": "none"} when the user has no agent for
        the company at all.

    FUNCTIONAL defaults are NOT this: a new claim's pre-picked
    agent and the wizard's charge agent keep resolving to the
    earliest flagged row (claims.agent_on_record) — those are
    working defaults the user can change, not displays."""
    rows = list_preferred(db, user_id, company_id)
    flagged = [row for row in rows if row.is_preferred]
    if len(flagged) >= 2:
        return {"state": "many", "agent": None}
    row = preferred_row_for(db, user_id, company_id)
    if row is None:
        return {"state": "none", "agent": None}
    return {"state": "one", "agent": serialize_preferred(db, row)}


def add_preferred(
    db: Session,
    user_id: uuid.UUID,
    *,
    company_id: uuid.UUID,
    private_agent_id: uuid.UUID | None = None,
    agent_account_number: str | None = None,
) -> models.PreferredAgent:
    company = visible_company(db, user_id, company_id)
    if company is None:
        raise DealerError("That company isn't available to your account.")
    agent_user_id = None
    if private_agent_id is not None:
        agent = get_own_private_agent(db, user_id, private_agent_id)
        if agent is None:
            raise DealerError("That agent record isn't yours.")
        if agent.company_id is not None and agent.company_id != company.id:
            raise DealerError(
                "That agent record belongs to a different company — "
                "pick the company on the agent record first."
            )
    elif agent_account_number:
        # Exact account-number lookup ONLY — the one door to platform
        # agents. No search, no enumeration.
        target = (
            db.query(core_models.User)
            .filter(
                core_models.User.account_number
                == agent_account_number.strip().upper()
            )
            .first()
        )
        if target is None:
            raise DealerError(
                "No account with that account number — check it and try again."
            )
        if target.id == user_id:
            raise DealerError("You can't be your own preferred agent.")
        agent_user_id = target.id
    else:
        raise DealerError("Pick an agent record or enter an account number.")

    # Connecting is all this does: the row joins the roster,
    # flagged when the user has no preferred agent for the
    # company yet. It NEVER moves claims and never touches
    # another agent's flag — starring is set_agent_preferred's
    # per-agent act.
    row, _created = _ensure_connection(
        db,
        user_id,
        company.id,
        agent_user_id=agent_user_id,
        private_agent_id=private_agent_id,
    )
    db.commit()
    db.refresh(row)
    return row


def remove_preferred(db: Session, user_id: uuid.UUID, row_id: uuid.UUID) -> bool:
    """Disconnect one connection row. Claims seated with that
    agent STAY seated with him (seats never move silently) —
    disconnecting is about the roster, not the work. If the row
    was flagged, nothing is promoted in its place (multi-
    preferred): the display default re-resolves to the
    earliest remaining flagged row, or to the plain fallback
    when none remain."""
    row = db.get(models.PreferredAgent, row_id)
    if row is None or row.user_id != user_id:
        return False
    db.delete(row)
    db.commit()
    return True


# ---------------------------------------------------------------------
# The roster + the agent record (stage 1, 2026-11-04)
# ---------------------------------------------------------------------


def _platform_facts(db: Session, agent_user_id: uuid.UUID) -> dict:
    """A platform agent as the roster/record shows him: his
    agent profile's public facts (display name, contact, service
    area = his route area, his route schedule from the profile),
    falling back to the account name when he has no profile."""
    from app.modules.dealers import portal

    user = db.get(core_models.User, agent_user_id)
    profile = portal.get_profile(db, agent_user_id)
    facts = {
        "name": user.name if user is not None else "",
        "phone": "",
        "email": "",
        "account_number": user.account_number if user is not None else None,
        "location": "",
        "route_frequency": None,
        "route_day_of_week": None,
        "route_anchor_date": None,
    }
    if profile is not None:
        if profile.display_name:
            facts["name"] = profile.display_name
        facts["phone"] = profile.phone or ""
        facts["email"] = profile.contact_email or ""
        facts["location"] = profile.service_area or ""
        facts["route_frequency"] = profile.route_frequency
        facts["route_day_of_week"] = profile.route_day_of_week
        facts["route_anchor_date"] = profile.route_anchor_date
    return facts


def _roster_entry(
    *,
    kind: str,
    connection_id: uuid.UUID | None,
    private_agent_id: uuid.UUID | None,
    agent_user_id: uuid.UUID | None,
    name: str,
    phone: str,
    email: str,
    account_number: str | None,
    location: str,
    route_frequency,
    route_day_of_week,
    route_anchor_date,
    started_at,
    ended_at,
    is_preferred: bool,
    sort_stamp,
    claimed_by_name: str | None = None,
    claimed_by_account_number: str | None = None,
) -> dict:
    from app.modules.dealers.route_days import next_route_visit

    return {
        "key": (
            f"private:{private_agent_id}"
            if kind == "private"
            else f"platform:{agent_user_id}"
        ),
        "kind": kind,
        "connection_id": connection_id,
        "private_agent_id": private_agent_id,
        "agent_user_id": agent_user_id,
        "name": name,
        "phone": phone,
        "email": email,
        "account_number": account_number,
        "location": location or "",
        "route_frequency": route_frequency,
        "route_day_of_week": route_day_of_week,
        "route_anchor_date": route_anchor_date,
        "next_visit": next_route_visit(
            route_frequency, route_day_of_week, route_anchor_date
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "is_preferred": is_preferred,
        "claimed_by_name": claimed_by_name,
        "claimed_by_account_number": claimed_by_account_number,
        "_sort": sort_stamp,
    }


def company_roster(
    db: Session, user_id: uuid.UUID, company: models.DealerCompany
) -> list[dict]:
    """THE ROSTER for one company (stage 1): every agent the
    viewer has for this dealer —

    (a) his own private agent records for the company (never
        archived ones: an archived record's seat is its platform
        row), each carrying its connection row when one exists;
    (b) the platform agents he is CONNECTED with for the company
        (a connection row — typed account number, one-tap card
        add, or the private -> platform switch). Registered
        agents he never connected with are NOT here; being
        listed publicly is Stage 3's find-an-agent, not this.

    A claimed (taken-over) record appears once, as its private
    entry — the record is the seat. Preferred agents (multi-
    preferred: EVERY flagged row wears its star) sort first in
    roster order; when connections exist but none is flagged,
    the earliest heals the flag on read, as data predating the
    flag resolves everywhere else."""
    rows = list_preferred(db, user_id, company.id)
    records = (
        db.query(models.PrivateAgent)
        .filter(
            models.PrivateAgent.owner_id == user_id,
            models.PrivateAgent.company_id == company.id,
            models.PrivateAgent.archived.is_(False),
        )
        .order_by(
            models.PrivateAgent.created_at.asc(), models.PrivateAgent.id.asc()
        )
        .all()
    )
    # Heal the flag on read when connections exist but none is
    # flagged (possible after an agent's account deletion removed
    # the flagged row): the earliest connection takes a star —
    # the same resolution every other surface already applies.
    if rows and not any(row.is_preferred for row in rows):
        rows[0].is_preferred = True
        db.commit()
    flagged_ids = {row.id for row in rows if row.is_preferred}

    entries: list[dict] = []
    by_private: dict[uuid.UUID, dict] = {}
    for record in records:
        claimed_name = None
        claimed_number = None
        if record.link_source == "takeover" and record.linked_user_id:
            linked = db.get(core_models.User, record.linked_user_id)
            if linked is not None:
                claimed_name = _platform_facts(db, linked.id)["name"]
                claimed_number = linked.account_number
        entry = _roster_entry(
            kind="private",
            connection_id=None,
            private_agent_id=record.id,
            agent_user_id=None,
            name=record.name,
            phone=record.phone,
            email=record.email,
            account_number=None,
            location=record.location or "",
            route_frequency=record.route_frequency,
            route_day_of_week=record.route_day_of_week,
            route_anchor_date=record.route_anchor_date,
            started_at=record.started_at,
            ended_at=record.ended_at,
            is_preferred=False,
            sort_stamp=record.created_at,
            claimed_by_name=claimed_name,
            claimed_by_account_number=claimed_number,
        )
        by_private[record.id] = entry
        entries.append(entry)
    for row in rows:
        if row.private_agent_id is not None:
            entry = by_private.get(row.private_agent_id)
            if entry is None:
                continue  # archived/foreign record — not a roster seat
            entry["connection_id"] = row.id
            entry["is_preferred"] = row.id in flagged_ids
            entry["_sort"] = min(entry["_sort"], row.created_at)
            continue
        facts = _platform_facts(db, row.agent_user_id)
        entries.append(
            _roster_entry(
                kind="platform",
                connection_id=row.id,
                private_agent_id=None,
                agent_user_id=row.agent_user_id,
                name=facts["name"],
                phone=facts["phone"],
                email=facts["email"],
                account_number=facts["account_number"],
                location=facts["location"],
                route_frequency=facts["route_frequency"],
                route_day_of_week=facts["route_day_of_week"],
                route_anchor_date=facts["route_anchor_date"],
                started_at=row.tenure_started_at,
                ended_at=row.tenure_ended_at,
                is_preferred=row.id in flagged_ids,
                sort_stamp=row.created_at,
            )
        )
    entries.sort(key=lambda e: (not e["is_preferred"], e["_sort"]))
    for entry in entries:
        entry.pop("_sort", None)
    return entries


def _roster_claim_view(db: Session, claim) -> dict:
    from app.modules.claims import models as claim_models
    from app.modules.claims import service as claims_service

    lines = claims_service._lines(db, claim.id)
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "status": claim.status,
        # Open = in flight and not closed (the closed layer,
        # claims overhaul 2026-11-06: a claim closed from an open
        # status keeps that status, so the layer decides).
        "is_open": (
            claim.status in claim_models.WARRANTY_OPEN_STATUSES
            and claim.closed_at is None
        ),
        "item_name": (
            claims_service._line_display_name(lines[0]) if lines else ""
        ),
        "created_at": claim.created_at,
    }


def _truck_slot(
    db: Session,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    agent_user_id: uuid.UUID | None = None,
    private_agent_id: uuid.UUID | None = None,
) -> list[dict]:
    """The agent record's truck-account summary slot (stage 1:
    the facts Stage 2's per-agent truck surfaces will build
    on). The viewer's own accounts under this company HELD by
    this agent — the holder pointer is the seat, exactly as
    truck_accounts resolves it. Empty list = no account with
    this agent; the page says so plainly, no filler."""
    from sqlalchemy import select

    from app.modules.truck_accounts import models as truck_models
    from app.modules.truck_accounts import service as truck_service

    query = select(truck_models.TruckAccount).where(
        truck_models.TruckAccount.customer_user_id == user_id,
        truck_models.TruckAccount.dealer_company_id == company_id,
        truck_models.TruckAccount.customer_deleted.is_(False),
    )
    if private_agent_id is not None:
        query = query.where(
            truck_models.TruckAccount.private_agent_id == private_agent_id
        )
    elif agent_user_id is not None:
        query = query.where(
            truck_models.TruckAccount.dealer_user_id == agent_user_id
        )
    else:
        return []
    return [
        {
            "id": account.id,
            "status": account.status,
            "balance": str(truck_service.balance_of(db, account.id)),
            "agent_name": truck_service.agent_display_name(db, account),
            # Stage 2 fills the slot in: the schedule facts the
            # record shows beside the balance — next due, and the
            # missed state (count + past-due amount) when behind.
            "next_due_date": (
                account.next_due_date.isoformat()
                if account.next_due_date
                else None
            ),
            "payment_amount": (
                str(account.payment_amount)
                if account.payment_amount is not None
                else None
            ),
            "missed_payments": truck_service.schedule_status(db, account)[
                "missed_payments"
            ],
            "amount_past_due": str(
                truck_service.schedule_status(db, account)["amount_past_due"]
            ),
        }
        for account in db.scalars(query)
    ]


def roster_agent_detail(
    db: Session,
    user: core_models.User,
    company: models.DealerCompany,
    *,
    kind: str,
    ref_id: uuid.UUID,
) -> dict:
    """One agent's full record, opened from the roster (stage
    1): the private record in full (owner's view — code and
    takeover state included) or the platform agent's facts, his
    claims seated with the viewer (open + history, each a link
    target), the truck-account slot, tenure, and the delete
    verdict for private records."""
    from app.modules.claims import service as claims_service
    from app.modules.dealers import portal

    entries = company_roster(db, user.id, company)
    entry = next(
        (
            e
            for e in entries
            if e["kind"] == kind
            and (
                e["private_agent_id"] == ref_id
                if kind == "private"
                else e["agent_user_id"] == ref_id
            )
        ),
        None,
    )
    if entry is None:
        raise DealerError("That agent isn't on this roster.", status_code=404)
    detail: dict = {
        "entry": entry,
        "record": None,
        "notes": "",
        "claims": [],
        "truck_accounts": [],
        "can_delete": False,
        "delete_block_reason": None,
    }
    if kind == "private":
        record = get_own_private_agent(db, user.id, ref_id)
        if record is None:  # roster said he exists; race-safe 404
            raise DealerError(
                "That agent isn't on this roster.", status_code=404
            )
        detail["record"] = portal.serialize_private_agent_linked(db, record)
        detail["notes"] = record.notes
        detail["claims"] = [
            _roster_claim_view(db, claim)
            for claim in claims_service.claims_seated_with_agent(
                db, user.id, private_agent_id=record.id, company_id=company.id
            )
        ]
        detail["truck_accounts"] = _truck_slot(
            db, user.id, company.id, private_agent_id=record.id
        )
        if record.linked_user_id is not None:
            detail["delete_block_reason"] = (
                "This record belongs to a working agent now, so it "
                "can't be deleted. His name stays on your claims "
                "and accounts either way."
            )
        else:
            detail["can_delete"] = True
    else:
        detail["claims"] = [
            _roster_claim_view(db, claim)
            for claim in claims_service.claims_seated_with_agent(
                db, user.id, agent_user_id=ref_id, company_id=company.id
            )
        ]
        detail["truck_accounts"] = _truck_slot(
            db, user.id, company.id, agent_user_id=ref_id
        )
    return detail


def agent_card_facts(
    db: Session,
    user_id: uuid.UUID,
    company: models.DealerCompany,
    *,
    kind: str,
    ref_id: uuid.UUID,
) -> dict | None:
    """The vCard facts for ONE roster agent (contact cards
    lane, 2026-11-07): the same authorization as the agent
    record view — the agent must sit on the CALLER's roster for
    a company the caller can see — returning only what a
    contact card carries: name, phone, email, the company as
    the caller sees it (personal edits included), and a note
    (the private record's own notes, plus the route area — a
    vCard has no honest field for a free-text route area, so
    it rides in the note where the owner can read it).
    None when the agent isn't on the roster."""
    entries = company_roster(db, user_id, company)
    entry = next(
        (
            e
            for e in entries
            if e["kind"] == kind
            and (
                e["private_agent_id"] == ref_id
                if kind == "private"
                else e["agent_user_id"] == ref_id
            )
        ),
        None,
    )
    if entry is None:
        return None
    note_parts: list[str] = []
    if kind == "private":
        record = get_own_private_agent(db, user_id, ref_id)
        if record is not None and record.notes.strip():
            note_parts.append(record.notes.strip())
    location = (entry.get("location") or "").strip()
    if location:
        note_parts.append(f"Route area: {location}")
    return {
        "name": entry["name"],
        "phones": [entry["phone"]] if entry.get("phone") else [],
        "emails": [entry["email"]] if entry.get("email") else [],
        "org": personal_company_name(db, user_id, company),
        "note": "\n\n".join(note_parts),
    }


# ---------------------------------------------------------------------
# Contact cards: vCard import into PRIVATE agents (agent card
# import lane, 2026-11-07)
#
# The mirror of agent_card_facts: a .vcf (one card or many)
# becomes the caller's OWN private agent records — never a
# platform agent. Registered agents come into being only
# through signup + the code-claim flow, which import never
# touches: no import path sets linked/claimed/verified state,
# and the confirm creates through create_private_agent, the
# ordinary path, so an imported record is indistinguishable
# from a typed one. Import NEVER writes blind: the preview
# parses, suggests a dealer per card, flags likely duplicates;
# only the rows the owner confirms come back to the import
# call. Nothing is merged and nothing is doubled silently.
# ---------------------------------------------------------------------

_ROUTE_AREA_LINE_RE = re.compile(
    r"^\s*route\s+area\s*:\s*(.+?)\s*$", re.IGNORECASE
)


def _split_agent_note(note: str) -> tuple[str, str]:
    """(notes, route area) from a card's NOTE: the export puts
    the route area on its own labeled line ("Route area: …"),
    so the import pulls that line back OUT into the record's
    location field; everything else stays notes. Blank seams
    the extraction leaves behind collapse back down."""
    location = ""
    kept: list[str] = []
    for line in (note or "").split("\n"):
        match = _ROUTE_AREA_LINE_RE.match(line)
        if match:
            if not location:
                location = match.group(1).strip()
            continue
        kept.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text, location


def _agent_card_draft(card: dict) -> dict:
    """A parsed card -> the agent record's shape. The first
    phone / first email take the record's own fields; any
    extras are preserved in the notes as labeled lines (the
    export's own convention — information is never dropped,
    it is labeled and kept)."""
    phones = [str(p).strip() for p in card.get("phones", []) if str(p).strip()]
    emails = [str(e).strip() for e in card.get("emails", []) if str(e).strip()]
    notes, location = _split_agent_note(str(card.get("note") or ""))
    note_parts = [notes] if notes else []
    for extra in phones[1:]:
        note_parts.append(f"Other phone: {extra}")
    for extra in emails[1:]:
        note_parts.append(f"Other email: {extra}")
    return {
        "name": str(card.get("name") or "").strip()[:300],
        "phone": (phones[0] if phones else "")[:100],
        "email": (emails[0] if emails else "")[:320],
        "location": location[:300],
        "notes": "\n\n".join(note_parts)[:5000],
        "org": str(card.get("org") or "").strip(),
    }


def _collapsed_name_key(name: str) -> str:
    """Name identity for suggestions + duplicates: whitespace
    collapsed, case folded (the borrower book's rule)."""
    return " ".join((name or "").split()).casefold()


def _agent_book_keys(
    db: Session, user_id: uuid.UUID
) -> dict[uuid.UUID, list[tuple[models.PrivateAgent, tuple[str, set[str], set[str]]]]]:
    """The caller's private records grouped BY DEALER, keyed
    for duplicate checks. Dealerless records sit under no
    dealer and can never make an import row a duplicate."""
    from app.modules.borrowing.service import _contact_keys

    book: dict[uuid.UUID, list] = {}
    for agent in list_private_agents(db, user_id):
        if agent.company_id is None:
            continue
        keys = _contact_keys(
            agent.name,
            [agent.phone] if agent.phone else [],
            [agent.email] if agent.email else [],
        )
        book.setdefault(agent.company_id, []).append((agent, keys))
    return book


def suggest_company_for_org(
    db: Session, user_id: uuid.UUID, org: str
) -> models.DealerCompany | None:
    """The dealer a card's ORG suggests: an exact name match
    (whitespace-collapsed, case-insensitive) against the
    companies this user can see — matched on BOTH the raw name
    and the name the user sees (a personal rename), so a card
    he exported himself, which carries his own name for the
    dealer, still matches. When several companies match, one
    he already has agents or connections with wins; otherwise
    list order (directory first, alphabetical) decides."""
    needle = _collapsed_name_key(org)
    if not needle:
        return None
    companies = list_companies(db, user_id)
    renames = personal_name_map(db, user_id, [c.id for c in companies])
    roster_ids = {
        a.company_id for a in list_private_agents(db, user_id) if a.company_id
    } | {
        row.company_id
        for row in db.query(models.PreferredAgent.company_id)
        .filter(models.PreferredAgent.user_id == user_id)
        .all()
    }
    matches = [
        company
        for company in companies
        if needle
        in {
            _collapsed_name_key(company.name),
            _collapsed_name_key(renames.get(company.id, company.name)),
        }
    ]
    if not matches:
        return None
    matches.sort(key=lambda c: 0 if c.id in roster_ids else 1)
    return matches[0]


def preview_agent_import(
    db: Session, user_id: uuid.UUID, cards: list[dict]
) -> dict:
    """The import preview: one row per readable card — the
    record it WOULD create, the dealer its ORG suggests, and
    its likely duplicates against the caller's own book,
    scoped per dealer — plus one soft error per unreadable
    card. Creates nothing.

    A card is a LIKELY DUPLICATE of a record under a dealer
    when its name matches that record's name AND they share a
    phone or an email (the borrower book's rule, scoped per
    dealer: the same person under two dealers is two records,
    not a duplicate). Platform agents never take part — the
    check reads the caller's private records only, and import
    never touches a registered agent."""
    from app.modules.borrowing.service import _contact_keys

    book = _agent_book_keys(db, user_id)
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
        draft = _agent_card_draft(card)
        name_key, phone_keys, email_keys = _contact_keys(
            draft["name"],
            card.get("phones", []),
            card.get("emails", []),
        )
        duplicates: list[dict] = []
        for company_id, keyed in book.items():
            for agent, (a_name, a_phones, a_emails) in keyed:
                if name_key != a_name:
                    continue
                if (phone_keys & a_phones) or (email_keys & a_emails):
                    company = db.get(models.DealerCompany, company_id)
                    duplicates.append(
                        {
                            "company_id": company_id,
                            "company_name": (
                                personal_company_name(db, user_id, company)
                                if company is not None
                                else ""
                            ),
                            "duplicate_of": agent.name,
                        }
                    )
                    break
        suggested = suggest_company_for_org(db, user_id, draft["org"])
        suggested_dup = next(
            (
                d
                for d in duplicates
                if suggested is not None and d["company_id"] == suggested.id
            ),
            None,
        )
        rows.append(
            {
                "index": index,
                **draft,
                "suggested_company_id": suggested.id if suggested else None,
                "suggested_company_name": (
                    personal_company_name(db, user_id, suggested)
                    if suggested is not None
                    else None
                ),
                "duplicate": suggested_dup is not None,
                "duplicate_of": (
                    suggested_dup["duplicate_of"] if suggested_dup else None
                ),
                "duplicates": duplicates,
            }
        )
    return {"rows": rows, "errors": errors, "total_cards": len(cards)}


def import_agents(
    db: Session, user_id: uuid.UUID, rows: list[dict]
) -> list[models.PrivateAgent]:
    """Create exactly the confirmed rows, each through the
    ordinary private-agent create path (same validation, same
    roster connection, same agent code). A row that fails —
    a dealer the caller can't see, a blank name — is skipped,
    never fatal to the batch; the caller reports who landed."""
    created = []
    for row in rows:
        try:
            created.append(
                create_private_agent(
                    db,
                    user_id,
                    {
                        "name": row.get("name") or "",
                        "company_id": row.get("company_id"),
                        "phone": row.get("phone") or "",
                        "email": row.get("email") or "",
                        "notes": row.get("notes") or "",
                        "location": row.get("location") or "",
                    },
                )
            )
        except DealerError:
            continue
    return created


def _resolve_flag_target(
    db: Session,
    user_id: uuid.UUID,
    company: models.DealerCompany,
    *,
    private_agent_id: uuid.UUID | None,
    agent_user_id: uuid.UUID | None,
) -> tuple[models.PreferredAgent | None, str]:
    """(connection row, display name) for a flag target. A
    private target without a row gets one created by
    set_agent_preferred; a platform target must already be
    connected (connecting is the add flows' job, with their
    own doors)."""
    if private_agent_id is not None:
        record = get_own_private_agent(db, user_id, private_agent_id)
        if record is None:
            raise DealerError("That agent record isn't yours.")
        if record.company_id is not None and record.company_id != company.id:
            raise DealerError(
                "That agent record belongs to a different company."
            )
        row = _connection_row(
            db, user_id, company.id, private_agent_id=private_agent_id
        )
        return row, record.name
    if agent_user_id is not None:
        row = _connection_row(
            db, user_id, company.id, agent_user_id=agent_user_id
        )
        return row, _platform_facts(db, agent_user_id)["name"]
    raise DealerError("Pick the agent to mark or unmark as preferred.")


def set_agent_preferred(
    db: Session,
    user: core_models.User,
    *,
    company_id: uuid.UUID,
    private_agent_id: uuid.UUID | None = None,
    agent_user_id: uuid.UUID | None = None,
    is_preferred: bool,
) -> models.PreferredAgent:
    """Star or unstar ONE roster agent (multi-preferred, owner
    ruling 2026-11-05). The flag is per agent and independent:
    starring one agent never unstars another, there is no
    switch and no prompt, claims stay seated with the agent
    who holds them, and tenure — which tracks the connection,
    not the star — is never stamped by a flag change. Starring
    a private record that has no connection row yet creates
    the row (the same roster join every add flow performs)."""
    company = visible_company(db, user.id, company_id)
    if company is None:
        raise DealerError("That company isn't available to your account.")
    target_row, _name = _resolve_flag_target(
        db,
        user.id,
        company,
        private_agent_id=private_agent_id,
        agent_user_id=agent_user_id,
    )
    if target_row is None:
        if private_agent_id is not None:
            target_row, _created = _ensure_connection(
                db, user.id, company.id, private_agent_id=private_agent_id
            )
        else:
            raise DealerError(
                "Add that agent to your agents for this company first."
            )
    target_row.is_preferred = bool(is_preferred)
    db.commit()
    db.refresh(target_row)
    return target_row
# ---------------------------------------------------------------------
# Dealer intermingling (2026-10-25): the viewer's own records for
# one company — items bought from it, honest stats, their claims.
# ---------------------------------------------------------------------


def _records_money(value) -> Decimal:
    """Exact 2dp money, the codebase convention (SQLite SUM dust
    never reaches a page)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def company_my_records(
    db: Session, user_id: uuid.UUID, company: models.DealerCompany, *, claims_on: bool
) -> dict:
    """Everything the company page shows about the VIEWER's own
    history with this company:

    - items: their top-level tools (sets at their bundle totals,
      attached addons ride inside their set — the inventory list's
      own population) and batteries tagged with this company;
    - stats: items count, total spent (the recorded purchase
      totals of exactly those items — an item with no recorded
      price adds nothing, and nothing is ever estimated), the
      recorded replacement value (None when no item carries one —
      a $0 there would be a lie), the last purchase date, and the
      claim counts when claims ride along;
    - claims: their claims touching this dealer through the items'
      tags, split current/history — ONLY when the claims module
      is effective for the viewer (claims_on); otherwise None and
      the page shows no claims areas at all.
    """
    from sqlalchemy import select

    from app.modules.inventory import models as inv_models
    from app.modules.inventory import service as inv_service

    tools = list(
        db.scalars(
            select(inv_models.Tool).where(
                inv_models.Tool.owner_id == user_id,
                inv_models.Tool.dealer_company_id == company.id,
                inv_models.Tool.attached_to_set_id.is_(None),
            )
        )
    )
    batteries = list(
        db.scalars(
            select(inv_models.Battery).where(
                inv_models.Battery.owner_id == user_id,
                inv_models.Battery.dealer_company_id == company.id,
            )
        )
    )

    items: list[dict] = []
    total_spent = Decimal("0")
    replacement_sum = Decimal("0")
    replacement_seen = False
    last_purchase = None

    def _absorb(spent, replacement, purchase_date):
        nonlocal total_spent, replacement_sum, replacement_seen, last_purchase
        if spent is not None:
            total_spent += spent
        if replacement is not None:
            replacement_sum += replacement
            replacement_seen = True
        if purchase_date is not None and (
            last_purchase is None or purchase_date > last_purchase
        ):
            last_purchase = purchase_date

    for tool in tools:
        if tool.is_set:
            members = inv_service.resolve_set_members(
                db, tool, include_addons=True
            )
            priced = (
                tool.purchase_price is not None
                or any(p.price is not None for p in members["addon_pieces"])
                or any(
                    t.purchase_price is not None for t in members["attached_tools"]
                )
            )
            repl_recorded = tool.replacement_cost is not None or any(
                t.replacement_cost is not None for t in members["attached_tools"]
            )
            spent = members["price_total"] if priced else None
            replacement = members["replacement_total"] if repl_recorded else None
        else:
            qty = tool.quantity or 1
            spent = (
                tool.purchase_price * qty if tool.purchase_price is not None else None
            )
            replacement = (
                tool.replacement_cost * qty
                if tool.replacement_cost is not None
                else None
            )
        _absorb(spent, replacement, tool.purchase_date)
        items.append(
            {
                "id": tool.id,
                "item_kind": "tool",
                "name": tool.name,
                "brand": tool.brand or "",
                "model": tool.model or "",
                # The claim picker's search reads serials too
                # (2026-11-03): the tool's serial list, flattened.
                "serial": ", ".join(
                    str(s) for s in (tool.serial_numbers or []) if str(s).strip()
                ),
                "standing": tool.standing or "",
                "quantity": tool.quantity or 1,
                "is_set": bool(tool.is_set),
                "purchase_date": tool.purchase_date,
                "spent": _records_money(spent) if spent is not None else None,
                "photo": inv_service.primary_photo_thumb(tool),
                "_created": tool.created_at,
            }
        )
    for battery in batteries:
        qty = battery.quantity or 1
        spent = (
            battery.purchase_price * qty
            if battery.purchase_price is not None
            else None
        )
        replacement = (
            battery.replacement_cost * qty
            if battery.replacement_cost is not None
            else None
        )
        _absorb(spent, replacement, battery.purchase_date)
        items.append(
            {
                "id": battery.id,
                "item_kind": "battery",
                "name": battery.name,
                "brand": battery.brand or "",
                "model": battery.model or "",
                "serial": battery.serial_number or "",
                "standing": battery.standing or "",
                "quantity": qty,
                "is_set": False,
                "purchase_date": battery.purchase_date,
                "spent": _records_money(spent) if spent is not None else None,
                "photo": inv_service.primary_photo_thumb(battery),
                "_created": battery.created_at,
            }
        )
    # Newest purchase first; undated items after, newest added first.
    items.sort(
        key=lambda row: (
            row["purchase_date"] is not None,
            row["purchase_date"],
            row["_created"],
        ),
        reverse=True,
    )
    for row in items:
        row.pop("_created", None)

    claims_block = None
    open_claims: int | None = None
    total_claims: int | None = None
    if claims_on:
        from app.modules.claims import service as claims_service

        owner = db.get(core_models.User, user_id)
        if owner is None:
            # The visitor stand-in (Sweep D5, "View as visitor"):
            # the modeled member has no account row and no claim
            # can carry their id, so the claims read below
            # resolves their set — empty — through the same path
            # a real member's read runs. Any OTHER missing owner
            # keeps the defensive None block it has today.
            from app.modules.core import visitor_preview

            if user_id == visitor_preview.VISITOR_ID:
                owner = visitor_preview.visitor_viewer()
        if owner is not None:
            split = claims_service.claims_for_dealer(db, owner, company.id)
            claims_block = split
            open_claims = len(split["current"])
            total_claims = open_claims + len(split["history"])

    return {
        "items": items,
        "stats": {
            "items_count": len(items),
            "total_spent": _records_money(total_spent),
            "replacement_value": (
                _records_money(replacement_sum) if replacement_seen else None
            ),
            "last_purchase_date": last_purchase,
            "open_claims": open_claims,
            "total_claims": total_claims,
        },
        "claims": claims_block,
    }


# ---------------------------------------------------------------------
# My dealer list (owner directive, 2026-10-31): per-user
# customization of the PREFILLED pick list a user chooses a dealer
# from when entering one. The list is an overlay on the platform
# directory, never a copy:
#
#   pick list = (directory companies MINUS the user's hidden rows)
#               + the user's private companies (their records)
#               + the user's unspent list entries (templates)
#
# Because removals are remembered per directory entry, a brand the
# operator adds to the directory later shows up for every user who
# never hid it. List edits NEVER touch dealer records: hiding is
# not deleting, and removing an entry leaves any company it
# created standing in My companies.
# ---------------------------------------------------------------------

# The fields a list entry carries — exactly the Add Dealer
# wizard's basics step (the creation form for a private company
# minus the corporate warranty fieldset, which is operator
# research data and never part of a user's own entry).
_LIST_ENTRY_FIELDS = ("name", "kind", "email", "website", "address", "phones", "notes")


def _clean_list_entry_fields(data: dict) -> dict:
    cleaned = _clean_company_fields(data)
    return {key: cleaned[key] for key in _LIST_ENTRY_FIELDS}


def hidden_company_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        db.query(models.DealerListHidden.company_id)
        .filter(models.DealerListHidden.user_id == user_id)
        .all()
    )
    return {row[0] for row in rows}


def serialize_list_entry(db: Session, entry: models.DealerListEntry) -> dict:
    created = (
        db.get(models.DealerCompany, entry.created_company_id)
        if entry.created_company_id
        else None
    )
    return {
        "id": entry.id,
        "name": entry.name,
        "kind": entry.kind or "manufacturer",
        "email": entry.email,
        "website": entry.website,
        "address": entry.address,
        "phones": list(entry.phones or []),
        "notes": entry.notes,
        "created_company_id": created.id if created else None,
        "created_company_name": created.name if created else "",
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def list_list_entries(
    db: Session, user_id: uuid.UUID
) -> list[models.DealerListEntry]:
    return (
        db.query(models.DealerListEntry)
        .filter(models.DealerListEntry.user_id == user_id)
        .order_by(models.DealerListEntry.name.asc())
        .all()
    )


def get_own_list_entry(db: Session, user_id: uuid.UUID, entry_id: uuid.UUID):
    entry = db.get(models.DealerListEntry, entry_id)
    if entry is None or entry.user_id != user_id:
        return None
    return entry


def pick_list(db: Session, user_id: uuid.UUID) -> dict:
    """The dealer-entry pick list for this user: the directory
    minus their hidden brands, their private companies, and their
    unspent list entries. Spent entries (created_company_id set)
    stay out — the company they made is in the list already."""
    hidden = hidden_company_ids(db, user_id)
    companies = [
        company
        for company in list_companies(db, user_id)
        if not (company.is_directory and company.id in hidden)
    ]
    entries = [
        entry
        for entry in list_list_entries(db, user_id)
        if entry.created_company_id is None
    ]
    return {"companies": companies, "entries": entries}


def dealer_list_settings(db: Session, user_id: uuid.UUID) -> dict:
    """The management view: the FULL directory with each brand's
    hidden flag for this user, plus all of their list entries
    (spent ones included, so a restore/explainer can show them)."""
    hidden = hidden_company_ids(db, user_id)
    directory = (
        db.query(models.DealerCompany)
        .filter(models.DealerCompany.is_directory.is_(True))
        .order_by(models.DealerCompany.name.asc())
        .all()
    )
    return {
        "directory": [
            {"company": company, "hidden": company.id in hidden}
            for company in directory
        ],
        "entries": list_list_entries(db, user_id),
    }


def hide_directory_company(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    company = get_directory_company(db, company_id)
    if company is None:
        raise DealerError("That company isn't in the directory.", status_code=404)
    existing = (
        db.query(models.DealerListHidden)
        .filter(
            models.DealerListHidden.user_id == user_id,
            models.DealerListHidden.company_id == company.id,
        )
        .first()
    )
    if existing is None:
        db.add(
            models.DealerListHidden(user_id=user_id, company_id=company.id)
        )
        db.commit()


def unhide_directory_company(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    row = (
        db.query(models.DealerListHidden)
        .filter(
            models.DealerListHidden.user_id == user_id,
            models.DealerListHidden.company_id == company_id,
        )
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()


def create_list_entry(
    db: Session, user_id: uuid.UUID, data: dict
) -> models.DealerListEntry:
    fields = _clean_list_entry_fields(data)
    if not fields["name"]:
        raise DealerError("A list entry needs a name.")
    entry = models.DealerListEntry(user_id=user_id, **fields)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_list_entry(
    db: Session, entry: models.DealerListEntry, data: dict
) -> models.DealerListEntry:
    if entry.created_company_id is not None:
        raise DealerError(
            "This entry is already in your companies — edit it there instead."
        )
    fields = _clean_list_entry_fields(data)
    if not fields["name"]:
        raise DealerError("A list entry needs a name.")
    for key, value in fields.items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry


def delete_list_entry(db: Session, entry: models.DealerListEntry) -> None:
    # ONLY the entry goes. A company it created is a dealer record
    # of the user's and is never touched by list edits.
    db.delete(entry)
    db.commit()


def use_list_entry(
    db: Session, user_id: uuid.UUID, entry: models.DealerListEntry
) -> models.DealerCompany:
    """Pick an entry: mint the user's private company from its
    fields (once) and return it. Picking again returns the same
    company — an entry never duplicates its dealer."""
    if entry.created_company_id is not None:
        existing = get_own_private_company(db, user_id, entry.created_company_id)
        if existing is not None:
            return existing
    data = {key: getattr(entry, key) for key in _LIST_ENTRY_FIELDS}
    data.update(
        {
            "warranty_url": "",
            "warranty_phone": None,
            "ship_to_name": None,
            "ship_to_address": None,
            "ship_to_scope": None,
            "ship_to_scope_note": None,
            "warranty_process": None,
            "logo_key": None,
            "logo_tile": None,
        }
    )
    company = create_company(db, owner_id=user_id, data=data)
    entry.created_company_id = company.id
    db.commit()
    db.refresh(entry)
    return company


def restore_dealer_list(db: Session, user_id: uuid.UUID) -> dict:
    """Back to the shipped defaults: every hidden row and every
    custom entry of this user's goes. Dealer records (including
    companies their entries created) are untouched."""
    hidden_deleted = (
        db.query(models.DealerListHidden)
        .filter(models.DealerListHidden.user_id == user_id)
        .delete(synchronize_session=False)
    )
    entries_deleted = (
        db.query(models.DealerListEntry)
        .filter(models.DealerListEntry.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"hidden_removed": hidden_deleted, "entries_removed": entries_deleted}
