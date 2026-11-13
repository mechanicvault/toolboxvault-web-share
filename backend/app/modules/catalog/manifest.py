"""Community catalog module manifest (wave 4, 2026-10-20).

FEATURE module: the derived community product catalog, the
layered lookup chain behind Quick Add (community -> barcode
database -> AI assist), AI item identification, and the Locate
User Manual search/import service (its routes live on the
inventory items it serves; the machinery lives here).

Depends on core + inventory — the catalog is derived FROM
inventory's records and means nothing without them. Default
groups mirror every other inventory rider (mechanic + shop):
the groups that keep inventories. No nav entry: the catalog
has no page of its own — it surfaces inside the inventory
forms (Quick Add), item pages (Locate User Manual), and
Settings -> Sharing (the contribution switch).
"""

from app.modules.catalog.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="catalog",
    version="1.0.0",
    description="Product lookup: shared tool details that help Quick Add fill in a tool for you.",
    route_prefix="/api/catalog",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("community product catalog", "product lookup", "quick add", "manual lookup"),
    default_groups=("mechanic_technician", "shop_company"),
    # No nav entry (nav_path stays None), but the canonical
    # display name rides along so label consumers (module
    # prefs, signup preview) never fall back to the raw id
    # "catalog" (C-09).
    nav_label="Product catalog",
)
