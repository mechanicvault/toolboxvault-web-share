"""Maintenance module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults are mechanic + shop —
the groups that own the assets being repaired and maintained.

Depends on core (accounts, the inbox for overdue notifications)
and inventory (items resolve and validate through inventory's
service interface; an item's current repair standing lives on the
inventory record — switch inventory off and maintenance is
blocked with it).

Schedules and upkeep since the repairs ∪ claims merge
(2026-11-04): repairs themselves live in the claims module now
(Ryan's ruling — a repair IS a warranty claim); this module
keeps the schedules, the overdue nudges, and the out-of-service
board that reads the claims-driven standing.
"""

from app.modules.maintenance.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="maintenance",
    version="0.2.0",
    description="Maintenance: service and calibration schedules, due-date tracking, and the out-of-service board (repairs themselves run as claims).",
    route_prefix="/api/maintenance",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("maintenance schedules", "out-of-service board", "warranty tracking"),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Repairs & maintenance",
    nav_path="/maintenance",
    nav_order=35,
)
