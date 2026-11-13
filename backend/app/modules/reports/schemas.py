"""Reports module request/response shapes.

A report SPEC (columns + filters + grouping + sets mode + sort) is
the one currency of the module: the run endpoint takes one, the
export/email endpoints take one, and a saved config IS one with a
name. Presets are specs too.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class ReportFilters(BaseModel):
    """Every filter is optional; an empty spec is the whole vault."""

    q: str = Field(default="", max_length=200)
    # tool | battery — asset-level; set members follow their set.
    kind: str | None = Field(default=None, pattern="^(tool|battery)$")
    category: str | None = Field(default=None, max_length=200)
    # (No condition filter — the field was retired in Package B.
    # Saved filters carrying one still load: the key is ignored.)
    dealer_id: uuid.UUID | None = None
    # A tag NAME from the owner's own vocabulary.
    tag: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    # Judged against each asset's price TOTAL (sets: their full
    # member-inclusive total — the set is one asset worth that much).
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    date_from: date | None = None
    date_to: date | None = None
    # in_warranty | expiring_soon | expired | unknown — judged
    # against each asset's COMPUTED standing (tools carry warranty
    # terms since the maintenance build; one shared computation).
    warranty: str | None = Field(
        default=None,
        pattern="^(in_warranty|expiring_soon|expired|unknown)$",
    )
    only_sets: bool = False
    only_checked_out: bool = False


class SortSpec(BaseModel):
    key: str = "name"
    direction: str = Field(default="asc", pattern="^(asc|desc)$")


class ReportSpec(BaseModel):
    columns: list[str] | None = None  # None → DEFAULT_COLUMNS
    filters: ReportFilters = Field(default_factory=ReportFilters)
    grouping: str = Field(default="none", max_length=30)
    sets_mode: str = Field(default="summary", max_length=20)
    sort: SortSpec = Field(default_factory=SortSpec)
    # Display options (reports alignment, 2026-10-19) — the app
    # format's furniture. The defaults ARE the legacy behavior plus
    # the new summary block: a spec saved before these existed
    # (stored configs carry them in the options bag, migration
    # 0032) runs exactly as it did, with the summary added.
    # Row numbers are the app's "#" pseudo-column: a display
    # overlay, not a data column, so they live here, not in
    # `columns`.
    show_row_numbers: bool = False
    show_summary: bool = True
    # PDF page orientation; the app-style preset is portrait.
    orientation: str = Field(default="landscape", pattern="^(landscape|portrait)$")


class RunRequest(ReportSpec):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class ExportRequest(ReportSpec):
    pass


class EmailRequest(ReportSpec):
    format: str = Field(pattern="^(csv|xlsx|pdf)$")
    # Blank → the owner's own account email.
    recipient: EmailStr | None = None
    # Names the report in the subject/filename when present.
    report_name: str | None = Field(default=None, max_length=200)


class ConfigWrite(BaseModel):
    """Create/replace a saved configuration (a named spec)."""

    name: str = Field(min_length=1, max_length=200)
    spec: ReportSpec


