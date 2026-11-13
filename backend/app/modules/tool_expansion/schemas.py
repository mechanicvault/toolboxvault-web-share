"""Tool Expansion payloads.

PRIVACY CONTRACT (pinned by test): a suggestion carries ONLY the
suggested piece's name + model number (community spelling), the
match keys the user controls act on, and the VIEWER'S OWN item.
Nothing about any source owner — no id, no name, no serial, no
price, no photo, no note — exists in these shapes, so nothing can
leak by accident.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ExpansionItemRef(BaseModel):
    """The viewer's own item a group of suggestions expands."""

    kind: str  # tool | battery
    id: uuid.UUID
    name: str
    is_set: bool


class ExpansionSuggestion(BaseModel):
    name: str
    model_number: str
    # The match keys (normalized model numbers) the Remove /
    # Report actions act on — numbers, never identities.
    anchor_model: str
    suggested_model: str


class ExpansionGroup(BaseModel):
    item: ExpansionItemRef
    suggestions: list[ExpansionSuggestion]


class ExpansionSuggestions(BaseModel):
    total: int
    groups: list[ExpansionGroup]


class ExpansionTopSuggestion(BaseModel):
    name: str
    model_number: str
    item_name: str


class ExpansionSummary(BaseModel):
    count: int
    top: list[ExpansionTopSuggestion]


class ExpansionCounts(BaseModel):
    counts: dict[str, int]


class ArchivedExpansion(BaseModel):
    """One row of the viewer's own dismissal ledger, read back
    for the Archived matches tab (lane 5, 2026-11-10). Same
    privacy contract as a suggestion: the suggested piece's name
    + model number and the viewer's own item — `item` is None
    when the viewer's item no longer exists (the tombstone), and
    `name` is "" when the match no longer generates anywhere, in
    which case `model_number` is the ledger's stored key."""

    anchor_kind: str  # tool | battery
    anchor_id: uuid.UUID
    item: ExpansionItemRef | None
    name: str
    model_number: str
    # The dismissal key (normalized) the un-archive write acts on.
    suggested_model: str
    archived_at: datetime
    # True when un-archiving puts the match back on the Matches
    # tab today (it still derives and is neither community-killed
    # nor reported by this viewer).
    restorable: bool


class ArchivedExpansions(BaseModel):
    total: int
    entries: list[ArchivedExpansion]


class DismissIn(BaseModel):
    anchor_kind: str = Field(pattern="^(tool|battery)$")
    anchor_id: uuid.UUID
    suggested_model: str = Field(min_length=1, max_length=200)


class ReportIn(BaseModel):
    anchor_model: str = Field(min_length=1, max_length=200)
    suggested_model: str = Field(min_length=1, max_length=200)
