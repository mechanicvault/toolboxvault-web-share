"""Support tickets module manifest (2026-10-24). FEATURE module:
the operator can disable it globally and assign it to account
groups; the seeded defaults are ALL FOUR groups (every member may
need help, whatever kind of account they hold).

The Help & Support page's ticket system: members open tickets and
trade messages with the support team; operators answer from the
admin surface (routes.admin_router, mounted at /api/admin).

Depends on core ONLY: the inbox notifications ride core's service
interface at request time, so no sibling's kill switch can touch
the desk.

No nav entry of its own (nav_path=None): Help & Support hangs
off the account/settings surfaces, not the module nav. The
manifest still declares the canonical nav_label as its display
name so label consumers never fall back to the raw id (C-09).
"""

from app.modules.support.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="support",
    version="1.1.0",
    description="Help and support: open a support ticket and talk with the support team.",
    route_prefix="/api/support",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("support tickets", "help and support"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    # Still no nav ENTRY (nav_path None), but the canonical
    # display name is declared so label consumers (module
    # prefs, signup preview) never fall back to the raw id
    # "support" (C-09).
    nav_label="Help & Support",
    nav_path=None,
    nav_order=None,
)
