"""The report column catalog.

Every column a report can carry, in the order the builder offers
them. A column key is either one of these base keys or
"cf:<field definition id>" for one of the owner's own custom fields
(inventory owns the definitions; the catalog resolves them per
owner at request time).

`type` drives formatting (money/date/number render differently in
the table, the CSV and the PDF) and sorting (money sorts as
Decimal, never as text).
"""

BASE_COLUMNS: list[dict] = [
    {"key": "name", "label": "Name", "type": "text"},
    # The app format's signature column (reports alignment,
    # 2026-10-19): the item's FIRST photo as a thumbnail. Its cell
    # VALUE is the photo's filename (that's what CSV carries; the
    # screen/PDF/XLSX render the image itself from the row's photo
    # block). No photo → the value is empty and every surface shows
    # a clean placeholder, never a broken image.
    {"key": "photo", "label": "Photo", "type": "photo"},
    {"key": "kind", "label": "Kind", "type": "text"},
    {"key": "brand", "label": "Brand", "type": "text"},
    {"key": "models", "label": "Model #", "type": "text"},
    {"key": "serials", "label": "Serial #", "type": "text"},
    {"key": "category", "label": "Category", "type": "text"},
    {"key": "location", "label": "Location", "type": "text"},
    {"key": "dealer", "label": "Dealer", "type": "text"},
    {"key": "tags", "label": "Tags", "type": "text"},
    {"key": "quantity", "label": "Qty", "type": "number"},
    {"key": "price_each", "label": "Price each", "type": "money"},
    {"key": "price_total", "label": "Price total", "type": "money"},
    {"key": "msrp", "label": "MSRP (total)", "type": "money"},
    {"key": "replacement", "label": "Replacement (total)", "type": "money"},
    {"key": "purchase_date", "label": "Purchased", "type": "date"},
    {"key": "warranty", "label": "Warranty", "type": "text"},
    # Structured warranty details (gap wave 1, 2026-10-20): who
    # stands behind the warranty + the coverage type label.
    {"key": "warranty_provider", "label": "Warranty provider", "type": "text"},
    {"key": "warranty_type", "label": "Warranty type", "type": "text"},
    # Lost/stolen report record (gap wave 1): the item's most
    # recent report — police report number + the date reported.
    {"key": "police_report_number", "label": "Police report #", "type": "text"},
    {"key": "loss_reported_date", "label": "Reported lost/stolen", "type": "date"},
    # Sold tracking (wave 2, 2026-10-20): the item's latest
    # EFFECTIVE sale from the sale ledger (reversed sales don't
    # count) — blank for items never sold.
    {"key": "sale_price", "label": "Sale price", "type": "money"},
    {"key": "sold_on", "label": "Sold on", "type": "date"},
    {"key": "buyer", "label": "Buyer", "type": "text"},
    {"key": "repair_status", "label": "Repair status", "type": "text"},
    # Consumable re-buy block (audit A7): where the replacement
    # comes from. Tools carry the fields; batteries and set pieces
    # read blank.
    {"key": "rebuy_store", "label": "Re-buy store", "type": "text"},
    {"key": "rebuy_url", "label": "Re-buy website", "type": "text"},
    {"key": "rebuy_sku", "label": "Re-buy SKU", "type": "text"},
    {"key": "rebuy_notes", "label": "Re-buy notes", "type": "text"},
    {"key": "status", "label": "Status", "type": "text"},
    {"key": "set", "label": "Set", "type": "text"},
]

BASE_BY_KEY: dict[str, dict] = {c["key"]: c for c in BASE_COLUMNS}

# The columns a report carries when the caller doesn't choose:
# the identity + valuation core of the vault.
DEFAULT_COLUMNS: list[str] = [
    "name",
    "kind",
    "brand",
    "models",
    "category",
    "quantity",
    "price_total",
    "replacement",
    "status",
]

GROUPINGS = ("none", "category", "dealer", "location", "tag", "kind", "purchase_year")

SETS_MODES = ("summary", "with_core", "full")

CUSTOM_PREFIX = "cf:"


def custom_key(definition_id) -> str:
    return f"{CUSTOM_PREFIX}{definition_id}"
