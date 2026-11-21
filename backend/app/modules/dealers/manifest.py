from app.modules.types import ModuleManifest

from . import routes

manifest = ModuleManifest(
    name="dealers",
    version="0.2.0",
    description="Dealer directory: find tool dealers and agents, and save the ones you deal with.",
    route_prefix="/api/dealers",
    router=routes.router,
    always_on=False,
    dependencies=("core",),
    provides=("dealer directory", "preferred agents", "agent profiles"),
    default_groups=(
        "mechanic_technician",
        "shop_company",
        "tool_dealer",
        "insurance",
    ),
    nav_label="Dealer directory",
    nav_path="/dealers",
    nav_order=40,
)
