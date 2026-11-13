"""Shared module-system types.

The ModuleManifest dataclass lives here — not in registry.py — so module
manifests can import it without creating an import cycle. registry.py and
every module's manifest.py import from this module.
"""

from dataclasses import dataclass, field

from fastapi import APIRouter


@dataclass(frozen=True)
class ModuleManifest:
    """What a module declares about itself."""

    name: str  # unique id, e.g. "inventory"
    version: str  # module's own version; bump on service-interface changes
    description: str
    route_prefix: str  # e.g. "/api/inventory"
    router: APIRouter
    always_on: bool  # core modules can't be disabled by users
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    # -- Feature-module contract (module doctrine, owner 2026-10-18) ------
    # A FEATURE module is a user-facing capability the operator can
    # enable/disable and assign to account groups (see
    # app/modules/core/module_control.py). Infrastructure modules
    # (core) leave these empty and are never gated.
    #
    # What this module is the source of truth for — the capabilities
    # other modules consume through its service interface, e.g.
    # inventory provides ("assets", "asset inventory stats").
    provides: tuple[str, ...] = field(default_factory=tuple)
    # Account groups (app/modules/core/account_types.py vocabulary)
    # the module serves until the operator changes the assignment.
    # The migration seeds module_access from this; the service also
    # falls back to it when a module has no assignment rows at all.
    default_groups: tuple[str, ...] = field(default_factory=tuple)
    # Nav metadata mirrored by the frontend registry: the entry the
    # module contributes to the menu when it is effective for a user.
    nav_label: str | None = None
    nav_path: str | None = None
    nav_order: int | None = None
