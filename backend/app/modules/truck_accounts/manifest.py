"""Truck Accounts module manifest (wave 2, 2026-10-20). FEATURE
module — dealer-run tabs between a tool-truck dealer and their
customers: invite/accept on a versioned agreement, a signed
ledger both parties can record against, balance derived from
the ledger, due reminders from the jobs service, and a DARK
Stripe Connect seam for online payments (dealers paid directly;
the platform never holds money).

Depends on core + dealers: the dealer side of the tab IS the
dealer portal's world (agent profiles carry the Connect seam's
columns; the dealer dashboard hosts this module's sections), so
the module honestly depends on it. Customers reach it with the
mechanic/shop groups; dealers with the dealer group.
"""

from app.modules.truck_accounts.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="truck_accounts",
    version="1.0.0",
    description="Truck accounts: running tabs with your tool-truck dealer — charges, payments, and what you owe, in one shared list.",
    route_prefix="/api/truck-accounts",
    router=router,
    always_on=False,
    dependencies=("core", "dealers"),
    provides=("truck_accounts",),
    default_groups=("mechanic_technician", "shop_company", "tool_dealer"),
    nav_label="Truck accounts",
    nav_path="/truck-accounts",
    nav_order=56,
)
