"""Wishlist module manifest (wave 2, 2026-10-20). FEATURE
module: the operator can disable it globally and assign it to
account groups; seeded defaults are mechanic + shop — the groups
that own tools and plan purchases.

Depends on core + inventory: the want-list's whole point is its
exit ramp into the vault (Convert to Tool rides inventory's
service interface, and the dealer tag validates through it), so
unlike Used Parts — whose bridge is a runtime interop — the
wishlist is honestly DEPENDENT: switch Asset Inventory off and
the wishlist is blocked with it.
"""

from app.modules.types import ModuleManifest
from app.modules.wishlist.routes import router

manifest = ModuleManifest(
    name="wishlist",
    version="1.0.0",
    description="Wishlist: the tools you plan to buy — save the link and the price you're aiming for, then move them into Inventory when you buy.",
    route_prefix="/api/wishlist",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("wishlist",),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Wishlist",
    nav_path="/wishlist",
    nav_order=17,
)
