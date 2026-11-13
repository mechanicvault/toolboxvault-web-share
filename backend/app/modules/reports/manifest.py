"""Reports module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults are mechanic + shop —
the groups that own inventory worth reporting on.

Depends on core (accounts) and inventory (the dataset reads assets
through inventory's service interface and billing's shared active
set; switch inventory off and reports is blocked with it).
"""

from app.modules.reports.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="reports",
    version="0.1.0",
    description="Reports: build and save reports of your tools and their values — for insurance, taxes, or a quick stock-take.",
    route_prefix="/api/reports",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("reports", "report exports"),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Reports",
    nav_path="/reports",
    nav_order=50,
)
