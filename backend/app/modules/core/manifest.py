"""Core module manifest. ALWAYS ON — auth, users, profiles, settings.

Every other module depends on this one (directly or transitively).
"""

from app.modules.core.routes import router
from app.modules.types import ModuleManifest

manifest = ModuleManifest(
    name="core",
    version="0.12.0",
    description="Your account: profile, settings, sign-in security, and your data.",
    route_prefix="/api/core",
    router=router,
    always_on=True,
    dependencies=(),
)
