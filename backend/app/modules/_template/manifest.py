"""COPY-PASTE TEMPLATE — manifest.py.

How to add a module:
  1. Copy backend/app/modules/_template/ -> backend/app/modules/<your_name>/
  2. Rename things from "template" to your module name.
  3. Declare dependencies: names of other modules whose SERVICE functions
     you call (never their models/routes — see service.py).
  4. Add one import + one dict entry in backend/app/modules/registry.py.

The manifest is the module's contract with the system. Bump `version`
whenever you change a service-interface signature.

NOTE: import ModuleManifest from app.modules.types (not from registry) to
avoid an import cycle.
"""

from app.modules._template.routes import router
from app.modules.types import ModuleManifest


manifest = ModuleManifest(
    name="template",
    version="0.1.0",
    description="Copy-paste starter. Replace with your module's description.",
    route_prefix="/api/template",
    router=router,
    always_on=False,  # True only for core modules that can never be disabled.
    dependencies=("core",),  # modules whose service.py functions you call.
)
