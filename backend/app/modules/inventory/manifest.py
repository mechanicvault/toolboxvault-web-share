"""Inventory module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults reproduce the original
mechanic-only gate.

Depends on core (ownership, auth). Other modules (borrowing, claims,
reports) consume inventory data through service.py functions only.
Peer sharing declares its dependency on this module — switch
inventory off and peer discovery goes with it.
"""

from app.modules.inventory.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="inventory",
    version="0.9.0",
    description="Inventory: your tools, batteries, and sets — with photos, documents, and costs, all searchable in one place.",
    route_prefix="/api/inventory",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("assets", "inventory stats", "spreadsheet import"),
    default_groups=("mechanic_technician",),
    nav_label="Inventory",
    nav_path="/inventory",
    nav_order=10,
)
