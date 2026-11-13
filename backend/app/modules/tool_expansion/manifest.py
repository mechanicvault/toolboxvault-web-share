"""Tool Expansion module manifest (owner spec 2026-10-25).

FEATURE module: known addons for the tools and sets a user
already owns, learned across the whole user base by model-number
matching (the first working installment of the ecosystem vision).
Suggestions are derived from live inventory at read time and are
anonymous by construction — only a suggested piece's name + model
number ever crosses between users.

Depends on core + inventory: the matches ARE inventory records
(the user's own items anchor them; contributors' sets feed them),
so the module is meaningless without inventory. Default groups
mirror every other inventory rider (mechanic + shop): the groups
that keep inventories.
"""

from app.modules.tool_expansion.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="tool_expansion",
    version="1.0.0",
    description="Tool Expansion: known addons for the tools and sets you already own, found by matching model numbers across the community's sets.",
    route_prefix="/api/tool-expansion",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("tool expansion suggestions",),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Tool Expansion",
    nav_path="/tool-expansion",
    nav_order=18,
)
