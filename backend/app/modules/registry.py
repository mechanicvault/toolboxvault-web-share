"""Module registry.

Every module declares a manifest (see app/modules/_template/manifest.py).
main.py loads routers from here — one line per module, nothing else.

Dependency rule: a module lists the modules it needs in its manifest. If a
dependency is missing, the registry raises at startup with a plain-language
error instead of failing mysteriously at request time. This is what makes the
dependency graph — and the blast radius of interface changes — visible.

Two registries live here:

- MODULES — the mount registry: infrastructure + feature modules whose
  routers main.py mounts. Core is infrastructure: always on, never gated.
- FEATURE_MODULES — the control registry (module doctrine, owner
  2026-10-18): the user-facing modules the operator can enable/disable
  and assign to account groups via app/modules/core/module_control.py.
  A feature module's dependencies may name infrastructure ("core") —
  always satisfied — or other feature modules. shared_tools' router is
  mounted through core's router (route-order law — see its manifest),
  so it appears here but not in MODULES.
"""

from collections.abc import Iterator

from app.modules.billing.ai_manifest import manifest as ai_manifest
from app.modules.billing.manifest import manifest as billing_manifest
from app.modules.borrowing.manifest import manifest as borrowing_manifest
from app.modules.catalog.manifest import manifest as catalog_manifest
from app.modules.claims.manifest import manifest as claims_manifest
from app.modules.core.manifest import manifest as core_manifest
from app.modules.dealers.manifest import manifest as dealers_manifest
from app.modules.downloads.manifest import manifest as downloads_manifest
from app.modules.feedback.manifest import manifest as feedback_manifest
from app.modules.flyers.manifest import manifest as flyers_manifest
from app.modules.forum.manifest import manifest as forum_manifest
from app.modules.core.shared_tools_manifest import (
    manifest as shared_tools_manifest,
)
from app.modules.disaster_claims.manifest import (
    manifest as disaster_claims_manifest,
)
from app.modules.inventory.manifest import manifest as inventory_manifest
from app.modules.maintenance.manifest import manifest as maintenance_manifest
from app.modules.marketplace.manifest import manifest as marketplace_manifest
from app.modules.messaging.manifest import manifest as messaging_manifest
from app.modules.parts.manifest import manifest as parts_manifest
from app.modules.prints.manifest import manifest as prints_manifest
from app.modules.reports.manifest import manifest as reports_manifest
from app.modules.support.manifest import manifest as support_manifest
from app.modules.tool_expansion.manifest import (
    manifest as tool_expansion_manifest,
)
from app.modules.truck_accounts.manifest import manifest as truck_manifest
from app.modules.types import ModuleManifest
from app.modules.wishlist.manifest import manifest as wishlist_manifest

MODULES: dict[str, ModuleManifest] = {
    core_manifest.name: core_manifest,
    downloads_manifest.name: downloads_manifest,
    inventory_manifest.name: inventory_manifest,
    billing_manifest.name: billing_manifest,
    borrowing_manifest.name: borrowing_manifest,
    dealers_manifest.name: dealers_manifest,
    reports_manifest.name: reports_manifest,
    maintenance_manifest.name: maintenance_manifest,
    claims_manifest.name: claims_manifest,
    disaster_claims_manifest.name: disaster_claims_manifest,
    parts_manifest.name: parts_manifest,
    messaging_manifest.name: messaging_manifest,
    marketplace_manifest.name: marketplace_manifest,
    forum_manifest.name: forum_manifest,
    wishlist_manifest.name: wishlist_manifest,
    truck_manifest.name: truck_manifest,
    feedback_manifest.name: feedback_manifest,
    catalog_manifest.name: catalog_manifest,
    support_manifest.name: support_manifest,
    tool_expansion_manifest.name: tool_expansion_manifest,
    flyers_manifest.name: flyers_manifest,
    prints_manifest.name: prints_manifest,
}

FEATURE_MODULES: dict[str, ModuleManifest] = {
    inventory_manifest.name: inventory_manifest,
    shared_tools_manifest.name: shared_tools_manifest,
    ai_manifest.name: ai_manifest,
    borrowing_manifest.name: borrowing_manifest,
    dealers_manifest.name: dealers_manifest,
    reports_manifest.name: reports_manifest,
    maintenance_manifest.name: maintenance_manifest,
    claims_manifest.name: claims_manifest,
    disaster_claims_manifest.name: disaster_claims_manifest,
    parts_manifest.name: parts_manifest,
    messaging_manifest.name: messaging_manifest,
    marketplace_manifest.name: marketplace_manifest,
    forum_manifest.name: forum_manifest,
    wishlist_manifest.name: wishlist_manifest,
    truck_manifest.name: truck_manifest,
    feedback_manifest.name: feedback_manifest,
    catalog_manifest.name: catalog_manifest,
    support_manifest.name: support_manifest,
    tool_expansion_manifest.name: tool_expansion_manifest,
    flyers_manifest.name: flyers_manifest,
    prints_manifest.name: prints_manifest,
}

# Names a feature module may depend on besides other feature modules.
INFRASTRUCTURE_MODULES: frozenset[str] = frozenset({core_manifest.name})


def iter_enabled_modules() -> Iterator[ModuleManifest]:
    """Yield manifests in dependency-safe order, validating dependencies."""
    seen: set[str] = set()
    for manifest in MODULES.values():
        for dep in manifest.dependencies:
            if dep not in MODULES:
                raise RuntimeError(
                    f"Module '{manifest.name}' requires missing module '{dep}'. "
                    f"Enable '{dep}' first."
                )
        seen.add(manifest.name)
        yield manifest


def validate_feature_modules(
    modules: dict[str, ModuleManifest] | None = None,
) -> list[str]:
    """Validate the FEATURE dependency graph. Returns human-readable
    problems (empty list = healthy):

    - a dependency naming neither a feature module nor infrastructure;
    - a dependency cycle among feature modules.

    Startup calls this and LOGS problems loudly; the control service
    independently marks offending modules (and their dependents)
    blocked. A broken graph must never take the site down — it takes
    the offending modules down, visibly, in the operator matrix.
    """
    modules = FEATURE_MODULES if modules is None else modules
    known = set(modules) | INFRASTRUCTURE_MODULES
    problems: list[str] = []

    for manifest in modules.values():
        for dep in manifest.dependencies:
            if dep not in known:
                problems.append(
                    f"Module '{manifest.name}' requires unknown module '{dep}'."
                )

    # Cycle detection over feature-module edges only (infrastructure
    # is a leaf: it depends on nothing). Standard DFS coloring.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(modules, WHITE)
    reported: set[frozenset[str]] = set()

    def visit(name: str, stack: list[str]) -> None:
        color[name] = GRAY
        stack.append(name)
        for dep in modules[name].dependencies:
            if dep not in modules:
                continue
            if color[dep] == GRAY:
                cycle = stack[stack.index(dep) :] + [dep]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    problems.append(
                        "Dependency cycle: " + " -> ".join(cycle) + "."
                    )
            elif color[dep] == WHITE:
                visit(dep, stack)
        stack.pop()
        color[name] = BLACK

    for name in modules:
        if color[name] == WHITE:
            visit(name, [])
    return problems
