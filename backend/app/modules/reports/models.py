"""Reports module tables.

report_configs: the owner's SAVED report configurations (the
original builder system). A config is a complete report spec
(columns, filters, grouping, sets mode, sort) stored as JSON —
running it re-derives the rows from inventory at read time, so a
saved report is never a stale snapshot: it always prices the
vault as it stands today.

Built-in presets ("Full inventory valuation", "Tax — purchases by
year") are NOT rows: they live in service.PRESETS, are served
read-only alongside the saved list, and become rows only when the
owner copies one. That keeps them undeletable and lets their shape
improve with the code instead of freezing in someone's database.

The 2026-11-06 redesign adds three tables beside it (migration
0082):

- report_templates — the new page's saved reports: a report TYPE
  (the catalog in reports/catalog.py) + the settings it was saved
  with + the area it lists in (quick | accounting). Running one
  generates fresh from current data, exactly like a config.
- generated_reports — the History: one row per file the new
  page's flows generated, the file itself in object storage
  under the owner's namespace.
- report_template_seeds — the seed-once marker for the seven
  default templates: a row exists once a user's defaults have
  been seeded, so a deleted default never resurrects.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReportConfig(Base):
    """One saved report configuration, owned by one user."""

    __tablename__ = "report_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Ordered column keys (base catalog keys and "cf:<definition id>"
    # for the owner's custom fields).
    columns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # The filter spec (schemas.ReportFilters shape); {} = unfiltered.
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # none | category | dealer | location | tag | kind | purchase_year
    grouping: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    # summary | with_core | full — how set contents appear as rows.
    sets_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="summary"
    )
    # {"key": <column key>, "direction": "asc" | "desc"}
    sort: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Spec-level DISPLAY options (reports alignment, migration
    # 0032): {"show_row_numbers": bool, "show_summary": bool,
    # "orientation": "landscape" | "portrait"}. A JSON bag so the
    # next display option needs no new column; {} (every pre-0032
    # row) reads as the legacy defaults in the service.
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReportTemplate(Base):
    """One saved report on the redesigned Reports page: a catalog
    report TYPE plus the settings it runs with. The row is the
    user's own — name and description are theirs to edit at save
    time; `is_default` only records that the row arrived as one of
    the seeded defaults (deletion treats it like any other)."""

    __tablename__ = "report_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # A key of reports/catalog.py TYPES.
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    # quick | accounting — where the template lists (the save flow
    # asks; the type's home area is the pre-answer).
    area: Mapped[str] = mapped_column(String(16), nullable=False, default="quick")
    # The type's own settings bag (year / period / format /
    # inventory grouping…), validated per type at save and at run.
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GeneratedReport(Base):
    """One generated file in the owner's History: the bytes live
    in object storage (storage_key, the owner's reports
    namespace); this row is the listable record — name, type,
    format, size, and the settings snapshot that produced it."""

    __tablename__ = "generated_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # The template the run came from, when it did. The template
    # delete path nulls this (the history row and its file are
    # the user's record and survive the template).
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_templates.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # pdf | csv | xlsx
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReportTemplateSeed(Base):
    """Seed-once marker: the row exists once the seven default
    templates have been seeded for this user (lazily, at their
    first templates read). Its presence is what stops a deleted
    default from ever resurrecting."""

    __tablename__ = "report_template_seeds"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    seeded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
