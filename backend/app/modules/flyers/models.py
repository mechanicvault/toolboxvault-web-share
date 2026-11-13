"""Flyers module tables (owner order, 2026-11-05 19:09 #10).

A flyer SOURCE is one dealer's flyer spot: either a dealer
COMPANY speaking for itself, or one AGENT — a platform agent
(a site user with a dealer account) or a private agent record
(one user's own entered agent). Each source owns a stream of
FLYERS: one current flyer plus its history, every flyer a
single PDF (uploaded, fetched from a pasted link, assembled
from phone photos by the scanner, or pulled from the source's
standing web address by the daily job).

Only keys are stored for the PDF and its first-page thumbnail
— bytes live in object storage, URLs are minted at read time,
the platform's standing rule.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

KIND_COMPANY = "company"
KIND_AGENT = "agent"

ORIGIN_LINK = "link"
ORIGIN_UPLOAD = "upload"
ORIGIN_PHOTOS = "photos"
ORIGIN_STANDING = "standing"


class FlyerSource(Base):
    """One flyer spot: a company's, or one agent's.

    Posting rights (checked in service.py on every write;
    tightened by the owner, 2026-11-06 22:15 — only REGISTERED
    dealers and agents post; mechanics are view-only):
      - company source: the company-owning DEALER account, or
        a user with a VERIFIED representation of the company;
      - platform agent source: the registered agent himself,
        for a company he represents;
      - private agent source: NO posting — a private
        (unclaimed) agent record confers no posting rights on
        anyone. The spot stays visible to its owner; only
        posting is gone.

    `visible` is the source's own on/off switch — off means
    connected users see nothing from this source at all.
    `history_visible` decides whether connected users may open
    past flyers or only the current one. `standing_url` is the
    source's set, reliable spot on the web: the daily job pulls
    it and posts whatever it finds as the current flyer,
    deduped by content hash (`standing_hash`).

    `auto_hash` / `auto_checked_at` are the SYSTEM pull's
    dedupe state (2026-11-06): the platform's official flyer
    link for the company (DealerCompany.official_flyer_url)
    posts under the company spot when the spot carries no
    standing address of its own — the poster's own address,
    when set, always wins over the system link.
    """

    __tablename__ = "flyer_sources"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'company' AND agent_user_id IS NULL"
            " AND private_agent_id IS NULL)"
            " OR (kind = 'agent' AND (agent_user_id IS NULL)"
            " <> (private_agent_id IS NULL))",
            name="ck_flyer_sources_shape",
        ),
        # One spot per source identity: a company has ONE
        # company spot; an agent has ONE spot per company.
        Index(
            "uq_flyer_sources_company",
            "company_id",
            unique=True,
            postgresql_where=text("kind = 'company'"),
            sqlite_where=text("kind = 'company'"),
        ),
        Index(
            "uq_flyer_sources_platform_agent",
            "company_id",
            "agent_user_id",
            unique=True,
            postgresql_where=text("agent_user_id IS NOT NULL"),
            sqlite_where=text("agent_user_id IS NOT NULL"),
        ),
        Index(
            "uq_flyer_sources_private_agent",
            "company_id",
            "private_agent_id",
            unique=True,
            postgresql_where=text("private_agent_id IS NOT NULL"),
            sqlite_where=text("private_agent_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dealer_companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    private_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("private_agents.id", ondelete="CASCADE"),
    )
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    history_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    standing_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, default="", server_default=""
    )
    standing_hash: Mapped[str | None] = mapped_column(String(64))
    standing_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    auto_hash: Mapped[str | None] = mapped_column(String(64))
    auto_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Flyer(Base):
    """One posted flyer: a single PDF with a life window.

    Current = starts_on <= today <= ends_on (the newest posted
    wins when windows overlap); when the end date passes the
    flyer comes down everywhere on its own — reads filter on
    the window, nothing needs deleting. Past flyers stay as
    history subject to the source's history_visible switch.
    """

    __tablename__ = "flyers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flyer_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", server_default=""
    )
    pdf_key: Mapped[str] = mapped_column(String(500), nullable=False)
    thumb_key: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    content_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    origin_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, default="", server_default=""
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    posted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FlyerAlertPref(Base):
    """The new-flyer alert's own on/off switch (owner order:
    the notification carries a setting of its own). A row
    exists only where the user flipped away from the default
    (ON); absence reads as on — the NotificationChannelPref
    posture, in the module's own table so the module owns its
    preference end to end.
    """

    __tablename__ = "flyer_alert_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
