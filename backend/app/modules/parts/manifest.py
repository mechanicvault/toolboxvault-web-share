"""Used Parts module manifest. FEATURE module (module doctrine,
owner 2026-10-18): the operator can disable it globally and assign
it to account groups; the seeded defaults are mechanic + shop — the
groups that keep spares (blueprint §18, owner's spec 2026-10-04).

Depends on core ONLY — deliberately. The location tree and the
parts stand alone: switch Asset Inventory off and the shelf still
works. The one bridge, "Add to Asset Inventory as a tool", calls
inventory's service interface at request time (and is gated on
inventory being effective for the caller, in the route) — a
runtime interop, not a dependency: parts is never BLOCKED by
inventory's state.
"""

from app.modules.parts.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="parts",
    version="0.2.0",
    description="My Parts: your spare parts, filed your way — and Community Parts, where members share what they have on the shelf.",
    route_prefix="/api/parts",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("my parts", "part locations"),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="My Parts",
    nav_path="/parts",
    nav_order=15,
)
