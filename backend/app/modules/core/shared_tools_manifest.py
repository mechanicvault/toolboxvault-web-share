"""Shared tools (peer sharing) — FEATURE module manifest (module
doctrine, owner 2026-10-18).

The peer-sharing routes physically live in the core module
(peer_sharing_routes.py, mounted on core's router) because their
literal "/sharing/peer/..." paths must register before tier
sharing's "/sharing/{group}" patterns — that route-order law keeps
them there. As a FEATURE, though, peer sharing is its own module:
it has its own operator switch and group assignment, and it depends
on inventory (peer discovery reads the owner's tools through
inventory's service interface — switch inventory off and this
module is blocked).

Tier (consent) sharing is deliberately NOT part of this module: it
is a privacy control in Settings, not a feature, and stays core.
"""

from app.modules.core.peer_sharing_routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="shared_tools",
    version="0.2.0",
    description="Shared tools: let people you trust see your tool list and ask to borrow — you choose exactly which tools they can see.",
    route_prefix="/api/core",
    router=router,
    always_on=False,
    dependencies=("core", "inventory"),
    provides=("peer_tool_discovery",),
    default_groups=("mechanic_technician", "shop_company"),
    nav_label="Shared tools",
    nav_path="/shared-tools",
    nav_order=20,
)
