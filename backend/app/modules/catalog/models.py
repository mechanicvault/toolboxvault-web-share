"""Catalog library tables — the system's OWN tool database
(sheet rows 219 + 221, Ryan 2026-11-20).

Ryan's direction: the system builds its own internal tool
library from imports — tools, sets and add-ons — so the quick
lookup pulls from it first and the AI web scrape is needed
less as the library grows. Every successful grounded import
is stored here; the lookup checks here before it walks the
web; dealer catalogs Ryan obtains seed it (row 221), and
fresh pulls keep it current.

PUBLIC MANUFACTURER FACTS ONLY: name, brand, part number,
price, photos, specs, warranty, set contents. Never a user's
private data (serials, purchase prices, notes, their photos).

CatalogProduct: one row per product, keyed by
(brand_key, model_key) — the normalized brand + part number.
CatalogPiece: one row per piece of a set product, with its
own part number keyed for the reverse lookup (a piece's part
number finds the sets it belongs to — sheet row 217).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class CatalogProduct(Base):
    __tablename__ = "catalog_products"
    __table_args__ = (
        UniqueConstraint(
            "brand_key", "model_key", name="uq_catalog_product_brand_model"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    brand_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    model_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    upc: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    msrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    specs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warranty_type: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    warranty_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    warranty_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_set: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    piece_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Where these facts came from: the page or feed the system
    # actually opened (the grounding rule), or the seed catalog.
    source_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="web"
    )
    # Trust status (lookup rebuild Phase 0, 2026-11-20): what
    # this record is allowed to claim. verified = passed the
    # referee (or an admin / hand verification); seed = printed
    # dealer catalog data; candidate = an unproven pull (web
    # walk or feed) that may fill a lookup but never certify
    # itself; quarantined = rejected, never shown. A piece list
    # is only ever replaced by a verified one.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="candidate"
    )
    # Rebuild Phase 5: how many independent later runs have
    # re-sighted this entry with the same complete piece list
    # — the corroboration count behind two-run promotion.
    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    pieces: Mapped[list["CatalogPiece"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="CatalogPiece.position",
    )


class CatalogPiece(Base):
    __tablename__ = "catalog_pieces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    msrp: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    product: Mapped[CatalogProduct] = relationship(back_populates="pieces")


class CatalogEvidence(Base):
    """One observation from a lookup run (rebuild Phase 1):
    a recorded data response, a page map, a section read —
    scrubbed at the door (see evidence.scrub), keyed by the
    brand + part number being looked up, so runs are
    replayable offline and every fact in a proposal can point
    back at what was actually seen."""

    __tablename__ = "catalog_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    section: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CatalogLookupJob(Base):
    """One background lookup (rebuild Phase 4): a quick lookup
    that can't answer completely starts (or joins) a job for
    the part number; the job runs the full lookup and stores
    the public result, which the wizard polls and applies
    while the user is still inputting (row 223 — a saved
    record is never touched). One live job per part number:
    a second user asking for the same part joins the same
    job, because the result is catalog data, not user data."""

    __tablename__ = "catalog_lookup_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(
        String(120), nullable=False, index=True
    )
    upc: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    brand: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
