"""Downloads module manifest. ALWAYS ON — the public lead magnet:
the /downloads page's subscriber list and free-sheet generator.
Its routes are deliberately unauthenticated (anonymous public
surface, like core's visitor counter); nothing here is a user
feature, so it is not a FEATURE_MODULE (never operator-gated).
"""

from app.modules.downloads.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="downloads",
    version="1.0.0",
    description="Downloads page: the free documents shelf (catalog + counts), the tool-inventory sheet, update-list signups, unsubscribes.",
    route_prefix="/api/downloads",
    router=router,
    always_on=True,
    dependencies=("core",),
)
