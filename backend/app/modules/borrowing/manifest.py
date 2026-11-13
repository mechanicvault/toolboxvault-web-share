"""Borrowing module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults are mechanic + shop —
the same groups that hold peer sharing, since borrowing grows out
of those grants.

Depends on core (accounts, peer grants, the inbox) and inventory
(items resolve and validate through inventory's service interface —
switch inventory off and borrowing is blocked with it).
"""

from app.modules.borrowing.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="borrowing",
    version="0.2.0",
    description="Borrowing: see what's out, who has it, and when it's due back — plus your full lending history.",
    route_prefix="/api/borrowing",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("checkouts", "lending history"),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Borrowing",
    nav_path="/borrowing",
    nav_order=30,
)
