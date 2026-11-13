"""Tools For Sale module manifest. FEATURE module (module
doctrine, owner 2026-10-18): the operator can disable it globally
and assign it to account groups; the seeded defaults are ALL FOUR
groups — the board is the community's marketplace, and every
member may post (subject to the paid-contribution gate) and every
visitor may browse.

Depends on core ONLY — deliberately. Listings SNAPSHOT their
display data (title/brand/model/photo copies) at creation, so a
listing never needs the inventory record to survive; the one
bridge — create-from-inventory — calls inventory's service
interface at request time and degrades to standalone creation
when the item is gone. Messaging threads anchor to listings
through marketplace's service interface (get_public_listing),
never by importing these tables.
"""

from app.modules.marketplace.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="marketplace",
    version="0.2.0",
    description="Tools for sale: buy and sell tools with other members, or post what you're looking for.",
    route_prefix="/api/marketplace",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("sale listings", "wanted listings", "reputation", "ratings"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="Tools for sale",
    nav_path="/marketplace",
    nav_order=25,
)
