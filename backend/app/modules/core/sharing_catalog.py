"""Shareable-field catalog for consent sharing (owner directive
2026-10-17).

A mechanic may share their tool list with the SHOP group and/or the
INSURANCE group — never automatically: the owner approves which
FIELDS go (this catalog) and which ITEMS go (per-item share rows).
Core owns this vocabulary because the sharing surface lives in core;
inventory owns the tool data itself and hands it over through its
service interface.

Field rules:
  - LOCKED_FIELDS are item identity. When an item is shared at all,
    these ALWAYS go — a recipient who can't tell which tool a row
    describes has nothing. They are not toggleable.
  - OPTIONAL_FIELDS are the owner's choice, per recipient group.
  - DEFAULT_SHARED_FIELDS are pre-checked the first time a group is
    enabled — the fields a shop/insurer plausibly needs, nothing
    financial beyond replacement cost, no notes, no purchase data.

`photos` / `documents` are attachment toggles, not tool columns:
photos = attachments of kind "photo"; documents = kinds "document"
and "receipt". `custom_fields` is one toggle for the tool's whole
custom_data dict.
"""

# The only groups a tool list can be shared WITH. (A dealer group
# share target is not part of the owner's model.)
RECIPIENT_GROUPS: tuple[str, ...] = ("shop_company", "insurance")

# Item identity — always shared when the item is shared.
LOCKED_FIELDS: tuple[str, ...] = ("name", "brand", "model", "serial_number")

# Owner-toggleable, per recipient group.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "category",
    "location",
    "purchase_price",
    "purchase_date",
    "msrp",
    "replacement_cost",
    "notes",
    "photos",
    "documents",
    "custom_fields",
)

# Pre-checked when a group is first enabled.
DEFAULT_SHARED_FIELDS: tuple[str, ...] = (
    "category",
    "photos",
    "replacement_cost",
)

# Attachment kinds behind the two attachment toggles.
PHOTO_KINDS: tuple[str, ...] = ("photo",)
DOCUMENT_KINDS: tuple[str, ...] = ("document", "receipt", "manual")


def canonical_fields(fields: list[str]) -> list[str]:
    """The chosen optional fields in catalog order, duplicates
    removed, anything outside OPTIONAL_FIELDS dropped. Storage is
    always canonical so configs compare equal regardless of the
    order a client sent them in."""
    chosen = set(fields)
    return [f for f in OPTIONAL_FIELDS if f in chosen]
