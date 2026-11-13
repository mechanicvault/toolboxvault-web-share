"""Wishlist module tables (wave 2, 2026-10-20).

One table: the owner's want-list. A wishlist item is a PLAN, not
an asset — it never counts toward the entitlement item cap (the
cap counts tools + batteries through billing's active set, which
never reads this table), and it becomes an asset only through the
explicit Convert-to-Tool copy, exactly the Used Parts posture.

The dealer tag mirrors inventory's: `dealer_company_id` names a
company the owner can see (directory or their own private one),
validated through inventory's service; SET NULL if the company
goes. `converted_tool_id` records the copy the same way parts do
— a link, not a move: the wishlist row stays, stamped purchased,
pointing at the tool it became.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PRIORITIES = ("low", "normal", "high")
STATUSES = ("wanted", "purchased")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Where the owner saw it (a product page, a truck catalog…) —
    # a plain link, never fetched by the server.
    link_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # What the owner hopes to pay; the PURCHASED price lands in
    # purchased_price when the item is marked bought.
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # low | normal | high (PRIORITIES).
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default="normal"
    )
    dealer_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Photo references, same shape as Part.attachments — storage
    # keys namespaced {owner}/wishlist/{id}/photo/...
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # wanted | purchased (STATUSES). Purchased facts ride along:
    # what was actually paid and when — the values Convert carries
    # into the new tool's purchase_price / purchase_date.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="wanted"
    )
    purchased_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    purchased_on: Mapped[date | None] = mapped_column(Date)

    converted_tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tools.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
