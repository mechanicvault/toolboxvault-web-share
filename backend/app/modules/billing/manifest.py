"""Billing module manifest. INFRASTRUCTURE (always on, like core):
plans, subscriptions, entitlements, redeem codes, the AI credit
wallet. Not a feature module — the operator does not switch the
entitlement engine off; what it *gates* (item limits) is governed
by the enforcement setting inside it.

Not nav-visible: its user surfaces are the Settings sections
(Subscription & billing, AI credits) and the /me + /ai-wallet reads.
"""

from app.modules.billing.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="billing",
    version="0.4.0",
    description="Plan & billing: your plan, payments, and credits.",
    route_prefix="/api/billing",
    router=router,
    always_on=True,
    dependencies=("core",),
    provides=("entitlements",),
)
