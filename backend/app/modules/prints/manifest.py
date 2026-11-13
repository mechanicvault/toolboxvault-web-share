"""3D Print Files module manifest. FEATURE module (module
doctrine, owner 2026-10-18): the operator can disable it
globally and assign it to account groups; the seeded defaults
are ALL FOUR groups — the shelf is a community surface like
the forum, every member may publish, and reading is public
(signed-out visitors browse and download print files through
the same routes, the forum's posture).

Depends on core ONLY. It consumes the suite's shared machinery
through service interfaces at request time: the community
blocks + moderation-team flag notifications (forum/core), and
the storage service for the file bytes.

Nav: the module contributes NO rail item — its door is the
Downloads page's 3D Print Files tab (owner order 2026-11-08:
the tab directs to the module's own page, like Help's How-to
Videos door). The nav metadata below names the page for the
module-control surfaces (prefs, signup options); the frontend
registry carries the routes with showInNav off.
"""

from app.modules.prints.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="prints",
    version="1.0.0",
    description="3D Print Files: free community print files for the shop — publish, version, rate, and download.",
    route_prefix="/api/prints",
    router=router,
    always_on=False,
    dependencies=("core",),
    provides=("3d print files", "print file versions", "print ratings", "print comments"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="3D Print Files",
    nav_path="/3dprints",
    nav_order=104,
)
