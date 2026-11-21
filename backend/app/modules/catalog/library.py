"""The internal tool library (sheet rows 219 + 221) — the
system's own product database, checked before the web walk
and fed by every grounded result.

Read path: `library_result` answers in the grounded layer's
own result shape, so lookup.py merges it like a page read —
except it costs a database query instead of a web search, a
page walk and AI reads. Write path: `record_grounded` upserts
what a real page (or, later, a brand feed / seed catalog)
stated. Recording is bookkeeping next to the user's lookup: a
failure here never fails the lookup itself.

Trust (lookup rebuild Phase 0, 2026-11-20): every record
carries a status — verified / seed / candidate / quarantined
— and trust governs every write. A stored fact is replaced
only by a fact of equal or higher trust, and a set's piece
list is replaced ONLY by a verified list (or into a slot
holding no real part numbers). The pre-rebuild rule — a
"richer" list (more priced pieces) replaces the stored one —
is what let a contaminated walk result certify itself into
the library (the SBUPM246V incident); it is gone.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.catalog import models as catalog_models
from app.modules.catalog.normalize import (
    canonical_brand,
    norm_brand,
    norm_model,
    norm_upc,
)

_FIELDS = (
    "name",
    "brand",
    "model",
    "category",
    "size",
    "msrp",
    "description",
    "upc",
)

# Trust ladder for library records. A write from a lower rung
# never overwrites a higher rung's facts.
_TRUST = {
    "quarantined": 0,
    "candidate": 1,
    "conflict": 1,
    "seed": 2,
    "verified": 3,
}

# Where a write came from decides the status it earns. Only
# two source kinds carry standing of their own: the printed
# catalog seed, and a verified pass (the referee's verdict, an
# admin, or a hand verification). Everything else — a web
# walk, a brand feed — is a candidate until proven.
_STATUS_BY_KIND = {"seed": "seed", "verified": "verified"}


def _status_for_kind(source_kind: str) -> str:
    return _STATUS_BY_KIND.get(source_kind, "candidate")


def _find(
    db: Session, brand: str, model: str, upc: str
) -> catalog_models.CatalogProduct | None:
    brand_key = norm_brand(brand)
    model_key = norm_model(model)
    if brand_key and model_key:
        hit = db.scalars(
            select(catalog_models.CatalogProduct).where(
                catalog_models.CatalogProduct.brand_key == brand_key,
                catalog_models.CatalogProduct.model_key == model_key,
            )
        ).first()
        if hit is not None:
            return hit
    digits = norm_upc(upc)
    if digits:
        hit = db.scalars(
            select(catalog_models.CatalogProduct).where(
                catalog_models.CatalogProduct.upc == digits
            )
        ).first()
        if hit is not None:
            return hit
    if model_key and not brand_key:
        return db.scalars(
            select(catalog_models.CatalogProduct).where(
                catalog_models.CatalogProduct.model_key == model_key
            )
        ).first()
    return None


def _result_shape(product: catalog_models.CatalogProduct) -> dict:
    fields: dict = {}
    for key in _FIELDS:
        value = getattr(product, key, None)
        if value not in (None, ""):
            fields[key] = value
    pieces = [
        {
            "name": piece.name or "",
            "model": piece.model,
            "msrp": piece.msrp,
            "image_url": piece.image_url,
        }
        for piece in product.pieces
    ]
    return {
        "fields": fields,
        "pieces": pieces,
        "piece_count": product.piece_count,
        "photos": list(product.photos or []),
        "specs": dict(product.specs or {}),
        "warranty_type": product.warranty_type,
        "warranty_months": product.warranty_months,
        "warranty_terms": product.warranty_terms,
        "source_name": product.source_name or "Toolbox Vault library",
        "source_url": product.source_url,
        "image_url": product.image_url,
        "status": product.status or "candidate",
        "confirmations": product.confirmations or 0,
        "ai_used": False,
    }


def library_result(
    db: Session, *, brand: str = "", model: str = "", upc: str = ""
) -> dict | None:
    """The library's answer for one product key, in the
    grounded result shape — or None when the library has never
    seen this product."""
    product = _find(db, brand, model, upc)
    if product is None:
        return None
    return _result_shape(product)


def sets_containing(db: Session, piece_model: str) -> list[dict]:
    """Reverse lookup (row 217's data): the library sets whose
    contents include this piece part number."""
    key = norm_model(piece_model)
    if not key:
        return []
    rows = db.scalars(
        select(catalog_models.CatalogProduct)
        .join(catalog_models.CatalogPiece)
        .where(catalog_models.CatalogPiece.model_key == key)
    ).all()
    return [_result_shape(product) for product in rows]


def _upsert(
    db: Session,
    *,
    brand: str,
    model: str,
    fields: dict,
    pieces: list,
    piece_count: int | None,
    photos: list,
    specs: dict,
    warranty_type: str | None,
    warranty_months: int | None,
    warranty_terms: str | None,
    image_url: str | None,
    source_name: str | None,
    source_url: str | None,
    source_kind: str,
) -> bool:
    brand = canonical_brand(fields.get("brand") or brand)
    model = str(fields.get("model") or model or "").strip()
    if not brand or not model:
        return False
    incoming_status = _status_for_kind(source_kind)
    product = _find(db, brand, model, str(fields.get("upc") or ""))
    if product is None:
        product = catalog_models.CatalogProduct(
            brand=brand,
            brand_key=norm_brand(brand),
            model=model,
            model_key=norm_model(model),
            source_kind=source_kind,
            status=incoming_status,
        )
        db.add(product)
        stored_status = incoming_status
    else:
        stored_status = product.status or "candidate"
    # Phase 5 policy — conflicts and corroboration, decided
    # before the trust gate below runs.
    incoming_models = {
        norm_model(str(piece["model"]))
        for piece in (pieces or [])
        if piece.get("model")
    }
    stored_models = {
        norm_model(piece.model)
        for piece in (product.pieces or [])
        if piece.model
    }
    if (
        stored_status == "verified"
        and incoming_status == "verified"
        and incoming_models
        and stored_models
        and incoming_models != stored_models
    ):
        # Two referee-verified runs disagree about a set's
        # contents: neither wins silently. The entry drops to
        # conflict (it stops completing lookups), the stored
        # list stays, and the challenger is filed as evidence
        # for an admin to resolve in the review queue.
        product.status = "conflict"
        from app.modules.catalog import evidence

        evidence.store_evidence(
            db,
            brand=brand,
            model=model,
            url=source_url or "",
            kind="conflict",
            section=None,
            payload={
                "stored_pieces": sorted(stored_models),
                "challenger_pieces": sorted(incoming_models),
            },
        )
        db.commit()
        return True
    promote_two_run = False
    if (
        stored_status == "candidate"
        and incoming_status == "candidate"
        and incoming_models
        and incoming_models == stored_models
        and all(piece.get("msrp") is not None for piece in pieces)
        and len(incoming_models) >= (product.piece_count or piece_count or 0)
    ):
        # Two-run promotion (Phase 5): an independent later
        # run re-sighted the same COMPLETE piece list (count
        # matches the stated count, every piece priced) — the
        # candidate has been corroborated and earns verified.
        product.confirmations = (product.confirmations or 0) + 1
        promote_two_run = product.confirmations >= 1
    # Trust gate (Phase 0): a write may refresh stored facts
    # only at equal or higher trust. A candidate pull can fill
    # a candidate record; it can never rewrite a seed record,
    # and nothing short of a verified pass rewrites a verified
    # one. A fact a pull no longer states is kept, not erased —
    # one page's silence is not a retraction.
    trust_ok = _TRUST[incoming_status] >= _TRUST[stored_status]
    if trust_ok:
        for key in ("name", "category", "size", "description"):
            value = fields.get(key)
            if value not in (None, ""):
                setattr(product, key, str(value)[:400])
        if fields.get("msrp") not in (None, ""):
            try:
                product.msrp = float(fields["msrp"])
            except (TypeError, ValueError):
                pass
        digits = norm_upc(str(fields.get("upc") or ""))
        if digits:
            product.upc = digits
        if photos:
            product.photos = list(photos)[:24]
        if image_url:
            product.image_url = image_url
        elif photos:
            product.image_url = photos[0]
        if specs:
            product.specs = dict(specs)
        if warranty_type:
            product.warranty_type = warranty_type
        if warranty_months:
            product.warranty_months = warranty_months
        if warranty_terms:
            product.warranty_terms = warranty_terms
        if piece_count:
            # The stated count only ever grows: a walk that
            # lists 3 of a 13-piece set must not shrink the
            # known count.
            product.piece_count = max(product.piece_count or 0, piece_count)
    if pieces:
        product.is_set = True
        # Piece-list rule (Phase 0, replaces the richness
        # guard): a stored list is replaced ONLY by a verified
        # list — or, at equal-or-higher trust, into a slot that
        # holds no real part numbers yet (empty, or names with
        # no model on any piece). "Longer / more priced wins"
        # is gone: it is what let a contaminated list certify
        # itself.
        def _modelled(rows) -> int:
            return sum(
                1
                for row in rows
                if (row.get("model") if isinstance(row, dict) else row.model)
            )

        stored_pieces = list(product.pieces or [])
        replace = incoming_status == "verified" or (
            trust_ok
            and (
                not stored_pieces
                or (_modelled(stored_pieces) == 0 and _modelled(pieces) > 0)
            )
        )
        if not replace:
            pieces = []
    if pieces:
        product.pieces = [
            catalog_models.CatalogPiece(
                name=str(piece.get("name") or "")[:400] or None,
                model=(str(piece["model"])[:120] if piece.get("model") else None),
                model_key=(
                    norm_model(str(piece["model"])) if piece.get("model") else None
                ),
                msrp=piece.get("msrp"),
                image_url=piece.get("image_url"),
                position=index,
            )
            for index, piece in enumerate(pieces)
        ]
        if not piece_count:
            product.piece_count = max(product.piece_count or 0, len(pieces))
    if trust_ok:
        if source_name:
            product.source_name = source_name
        if source_url:
            product.source_url = source_url
        product.source_kind = source_kind
    if promote_two_run:
        product.status = "verified"
    elif _TRUST[incoming_status] > _TRUST[stored_status]:
        # Promotion only ever moves up the ladder; a record is
        # never demoted by a later, weaker pull.
        product.status = incoming_status
    db.commit()
    return True


def record_grounded(
    db: Session,
    grounded_result: dict,
    *,
    typed_brand: str = "",
    typed_model: str = "",
    typed_upc: str = "",
    source_kind: str = "web",
) -> bool:
    """Store one grounded result in the library. Never raises
    into the lookup: a failed write rolls back and reports
    False — the user already got their answer."""
    try:
        fields = dict(grounded_result.get("fields") or {})
        if not fields:
            return False
        return _upsert(
            db,
            brand=typed_brand,
            model=typed_model,
            fields=fields,
            pieces=list(grounded_result.get("pieces") or []),
            piece_count=grounded_result.get("piece_count"),
            photos=list(grounded_result.get("photos") or []),
            specs=dict(grounded_result.get("specs") or {}),
            warranty_type=grounded_result.get("warranty_type"),
            warranty_months=grounded_result.get("warranty_months"),
            warranty_terms=grounded_result.get("warranty_terms"),
            image_url=grounded_result.get("image_url"),
            source_name=grounded_result.get("source_name"),
            source_url=grounded_result.get("source_url"),
            source_kind=source_kind,
        )
    except Exception:  # noqa: BLE001 — bookkeeping, see docstring
        db.rollback()
        return False


def import_product(
    db: Session,
    record: dict,
    *,
    source_kind: str = "seed",
    source_name: str | None = None,
    source_url: str | None = None,
) -> bool:
    """The seed path (row 221): one catalog record — the shape
    a dealer catalog file or a brand feed yields — stored
    through the same upsert every pull uses."""
    try:
        fields = {
            key: record.get(key)
            for key in _FIELDS
            if record.get(key) not in (None, "")
        }
        if not fields:
            return False
        return _upsert(
            db,
            brand=str(record.get("brand") or ""),
            model=str(record.get("model") or ""),
            fields=fields,
            pieces=list(record.get("pieces") or []),
            piece_count=record.get("piece_count"),
            photos=list(record.get("photos") or []),
            specs=dict(record.get("specs") or {}),
            warranty_type=record.get("warranty_type"),
            warranty_months=record.get("warranty_months"),
            warranty_terms=record.get("warranty_terms"),
            image_url=record.get("image_url"),
            source_name=source_name or record.get("source_name"),
            source_url=source_url or record.get("source_url"),
            source_kind=source_kind,
        )
    except Exception:  # noqa: BLE001 — a bad seed row skips, never sinks the batch
        db.rollback()
        return False


# -- the review queue (Phase 5) ------------------------------------


def review_queue(db: Session, *, status: str = "") -> list[dict]:
    """Entries an admin should look at: candidates awaiting
    corroboration and conflicts awaiting resolution (or one
    named status), newest first."""
    query = select(catalog_models.CatalogProduct)
    if status:
        query = query.where(catalog_models.CatalogProduct.status == status)
    else:
        query = query.where(
            catalog_models.CatalogProduct.status.in_(("candidate", "conflict"))
        )
    rows = db.scalars(
        query.order_by(catalog_models.CatalogProduct.id).limit(200)
    ).all()
    out = []
    for product in rows:
        shape = _result_shape(product)
        shape["id"] = str(product.id)
        shape["brand"] = product.brand
        shape["model"] = product.model
        shape["source_kind"] = product.source_kind
        out.append(shape)
    return out


def set_status(db: Session, product_id, status: str) -> dict | None:
    """An admin's verdict on one entry: approve (-> verified),
    reject (-> quarantined). Returns the updated shape."""
    import uuid as _uuid

    try:
        parsed = _uuid.UUID(str(product_id))
    except ValueError:
        return None
    product = db.get(catalog_models.CatalogProduct, parsed)
    if product is None:
        return None
    product.status = status
    db.commit()
    shape = _result_shape(product)
    shape["id"] = str(product.id)
    return shape


def resolve_conflict(db: Session, product_id, *, keep: str) -> dict | None:
    """Resolve a conflicted entry: keep the stored list, or
    take the challenger list filed with the conflict evidence.
    Either way the entry returns to verified — an admin has
    now decided which list is true."""
    import uuid as _uuid

    from app.modules.catalog import evidence

    try:
        parsed = _uuid.UUID(str(product_id))
    except ValueError:
        return None
    product = db.get(catalog_models.CatalogProduct, parsed)
    if product is None or product.status != "conflict":
        return None
    if keep == "challenger":
        rows = evidence.evidence_for(db, brand=product.brand, model=product.model)
        conflicts = [r for r in rows if r["kind"] == "conflict"]
        if conflicts:
            challenger = conflicts[-1]["payload"].get("challenger_pieces") or []
            if challenger:
                product.pieces = [
                    catalog_models.CatalogPiece(
                        name=None,
                        model=model_name,
                        model_key=norm_model(model_name),
                        msrp=None,
                        image_url=None,
                        position=index,
                    )
                    for index, model_name in enumerate(challenger)
                ]
    product.status = "verified"
    db.commit()
    shape = _result_shape(product)
    shape["id"] = str(product.id)
    return shape
