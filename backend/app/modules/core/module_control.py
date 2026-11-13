"""Module control service (module doctrine, owner 2026-10-18).

The owner controls every feature module: a global on/off switch and
a per-account-group assignment, stored in module_state /
module_access (seeded from the manifests' default_groups) and applied
to every request — no caching beyond the request, no restart.

Effective access for a user to a feature module requires ALL of:

  1. the module's dependency graph is healthy (no unknown dep, no
     cycle — a broken module blocks itself and its dependents);
  2. the module is globally enabled;
  3. every feature module it depends on is itself usable — globally
     enabled and assigned to at least one group (dependency off ⇒
     dependent off: kill inventory and peer discovery goes with it);
  4. at least one of the user's groups is assigned to the module.

Group assignment is evaluated per user; dependency blocking is a
property of the module system, not of the user — a shop account
without the inventory module still uses peer discovery while
inventory is on, exactly as before this system existed. The seeded
defaults reproduce the pre-doctrine access matrix exactly.

Infrastructure (core) is not a feature module and is never gated;
a dependency on it is always satisfied.

Per-user switches (owner 2026-10-24) are a SECOND layer on top of
the operator layer above: a user may turn an entitled feature
module off for THEMSELVES (user_module_prefs; no row = on). The
user layer only ever narrows — it can never grant what the
operator layer denies — and turning a module off cascades
through the feature dependency graph for that user (dealers off
⇒ truck accounts hidden, even though its own switch is on).
Inventory and support are CORE_ALWAYS_ON_MODULES: they carry no
user switch at all.

Tier switches (owner design, 2026-10-31) are a THIRD operator
layer, stored in module_tier_access: per module, one switch per
account-tier key (normal | moderator | moderator_admin | beta —
core/tiers.py). A module reaches an account only when one of the
account's APPLICABLE tier keys is switched on for it (inheritance:
higher rungs carry the lower keys; the beta flag adds the beta
key). Like the user layer, the tier layer cascades through the
dependency graph: a module whose dependency is dark for your tier
is dark for you. When a module has no tier rows at all, every tier
reads the module's global state (migration 0067 seeds exactly
that), so the layer is invisible until god stages a rollout with
it: global on + normal off + moderator_admin on = staff-only
testing of a live module; the parked modules stay dark for every
tier until god lights one. GOD BYPASSES the layer — and every
other layer: the god rung sees and can use every module, parked
or not (a graph-broken module stays unusable even for god: that
gate is code health, not access).

The downloads key (owner order, 2026-11-09) extends the layer
downward: the limited level a no-code signup lands on. Its
accounts carry ONLY the downloads key (no inheritance — see
core/tiers.py), hold no account groups (so effective_for_user
waives the group layer for that rung and the downloads cell is
the entitlement), and read NO fallback: an unseeded module is
dark for the level until an operator lights it. Migration 0096
seeds the level's starting world: prints and support on, every
other feature module off.
"""

import uuid

from sqlalchemy.orm import Session

from app.modules.core import models, tiers
from app.modules.core.account_types import ACCOUNT_TYPES


def _feature_modules() -> dict:
    """The control registry. Imported lazily: registry.py pulls in
    module manifests → routes → deps → this service, so a top-level
    import here would close the cycle."""
    from app.modules.registry import FEATURE_MODULES

    return FEATURE_MODULES


def _manifest(module_id: str, modules: dict | None = None):
    modules = _feature_modules() if modules is None else modules
    return modules[module_id]


# -- dependency graph ---------------------------------------------------


def graph_blocked(modules: dict | None = None) -> dict[str, str]:
    """module_id -> reason for every feature module the GRAPH marks
    unusable: it declares an unknown dependency, sits in a cycle, or
    depends (transitively) on a module that does. Healthy modules
    are absent from the result."""
    from app.modules.registry import INFRASTRUCTURE_MODULES

    modules = _feature_modules() if modules is None else modules
    blocked: dict[str, str] = {}

    for module_id, manifest in modules.items():
        for dep in manifest.dependencies:
            if dep not in modules and dep not in INFRASTRUCTURE_MODULES:
                blocked[module_id] = f"unknown dependency '{dep}'"

    # Cycle membership via DFS coloring (same walk as the registry
    # validator, kept local so the reason names the cycle plainly).
    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(modules, WHITE)

    def visit(name: str, stack: list[str]) -> None:
        color[name] = GRAY
        stack.append(name)
        for dep in modules[name].dependencies:
            if dep not in modules:
                continue
            if color[dep] == GRAY:
                for member in stack[stack.index(dep) :]:
                    blocked.setdefault(member, "dependency cycle")
            elif color[dep] == WHITE:
                visit(dep, stack)
        stack.pop()
        color[name] = BLACK

    for name in modules:
        if color[name] == WHITE:
            visit(name, [])

    # Transitive dependents of a blocked module are blocked by it.
    changed = True
    while changed:
        changed = False
        for module_id, manifest in modules.items():
            if module_id in blocked:
                continue
            for dep in manifest.dependencies:
                if dep in blocked:
                    blocked[module_id] = f"blocked by {dep}"
                    changed = True
                    break
    return blocked


# -- stored switches ------------------------------------------------------


def globally_enabled(db: Session, module_id: str) -> bool:
    """The operator's kill switch. Missing row = enabled (a module
    registered after the last seed still works)."""
    row = db.get(models.ModuleState, module_id)
    return True if row is None else bool(row.globally_enabled)


def assigned_groups(db: Session, module_id: str, modules: dict | None = None) -> set[str]:
    """The groups the operator has assigned to the module. When the
    module has NO assignment rows at all, the manifest's
    default_groups are the assignment (the migration seeds exactly
    those, so the two readings agree wherever the seed has run)."""
    rows = (
        db.query(models.ModuleAccess)
        .filter(models.ModuleAccess.module_id == module_id)
        .all()
    )
    if not rows:
        return set(_manifest(module_id, modules).default_groups)
    return {row.account_group for row in rows if row.enabled}


def tier_switches(db: Session, module_id: str) -> dict[str, bool]:
    """The module's per-tier switches (tiers.TIER_KEYS). When the
    module has NO tier rows at all, every tier reads the module's
    global state — the migration seeds exactly those values, so
    the fallback and the seed agree, and a module registered after
    the last seed behaves as globally on/off for every tier until
    god sets its cells. With rows present, a missing cell is off:
    first write materializes the rest (set_tier_assignment).

    ONE exception (2026-11-09): the downloads key NEVER reads the
    fallback. The downloads level is opt-in only — a module
    reaches it solely through an explicit cell (migration 0096's
    seed, or an admin's flip), so a module registered after the
    last seed is dark for the downloads level until an operator
    lights it on purpose."""
    rows = (
        db.query(models.ModuleTierAccess)
        .filter(models.ModuleTierAccess.module_id == module_id)
        .all()
    )
    if not rows:
        enabled = globally_enabled(db, module_id)
        switches = {key: enabled for key in tiers.TIER_KEYS}
        switches["downloads"] = False
        return switches
    stored = {row.tier: bool(row.enabled) for row in rows}
    return {key: stored.get(key, False) for key in tiers.TIER_KEYS}


def _tier_allowed(db: Session, module_id: str, keys) -> bool:
    """Is this module lit for ANY of the account's applicable tier
    keys? (Inheritance lives in the key set — tiers.py builds it.)"""
    switches = tier_switches(db, module_id)
    return any(switches.get(key, False) for key in keys)


def _fails_tier_layer(module_id: str, keys, modules: dict, db: Session) -> bool:
    """Does the TIER layer hide this module for an account carrying
    these keys? True when the module itself is dark for the
    account's tiers, or any feature module it (transitively)
    depends on is — the same cascade shape as the user layer."""
    if not _tier_allowed(db, module_id, keys):
        return True
    return any(
        not _tier_allowed(db, dep, keys)
        for dep in _transitive_feature_dependencies(module_id, modules)
    )


# -- effectiveness ---------------------------------------------------------


def dependency_blocker(db: Session, module_id: str, modules: dict | None = None) -> str | None:
    """The name of the feature dependency that currently blocks this
    module, or None. A dependency blocks when it is graph-broken,
    globally disabled, or assigned to no group at all (switched off
    everywhere = off)."""
    modules = _feature_modules() if modules is None else modules
    blocked = graph_blocked(modules)
    for dep in modules[module_id].dependencies:
        if dep not in modules:
            continue  # infrastructure: always satisfied
        if dep in blocked:
            return dep
        if not globally_enabled(db, dep):
            return dep
        if not assigned_groups(db, dep, modules):
            return dep
    return None


def usable_anywhere(db: Session, module_id: str, modules: dict | None = None) -> bool:
    """Could the PUBLIC use this module right now? The public-surface
    reading of the operator layer (the anonymous landing page asks
    exactly this before advertising a free-access surface): healthy
    graph, global switch on, assigned to at least one group, no
    feature dependency blocking it — and, since the tier layer
    (2026-10-31), lit for the NORMAL tier: public presence IS the
    normal tier, so a module lit only for staff or beta testers
    never leaks onto the landing. Per-user switches don't exist
    for the public, so they play no part here."""
    modules = _feature_modules() if modules is None else modules
    if module_id not in modules:
        return False
    if module_id in graph_blocked(modules):
        return False
    if not globally_enabled(db, module_id):
        return False
    if not assigned_groups(db, module_id, modules):
        return False
    if not tier_switches(db, module_id)["normal"]:
        return False
    return dependency_blocker(db, module_id, modules) is None


def dependency_status(db: Session, module_id: str, modules: dict | None = None) -> str:
    """Operator-facing dependency health for one module: "ok", the
    graph reason ("dependency cycle", "unknown dependency 'x'"), or
    "blocked by <dep>"."""
    modules = _feature_modules() if modules is None else modules
    blocked = graph_blocked(modules)
    if module_id in blocked:
        return blocked[module_id]
    blocker = dependency_blocker(db, module_id, modules)
    return "ok" if blocker is None else f"blocked by {blocker}"


# Feature modules a user can never switch off: the product cannot
# run without inventory's core, and a user must always be able to
# reach Help & Support. Writes guard these (set_user_module_pref
# refuses them); reads defend too — a stray disabling row for one
# of them, however it got there, is ignored everywhere below.
CORE_ALWAYS_ON_MODULES = frozenset({"inventory", "support"})


def user_disabled_module_ids(db: Session, user_id) -> set[str]:
    """The feature modules this user has switched off for
    themselves (their user_module_prefs rows with enabled=False).
    No row for a module = on. Always-on modules are filtered out
    defensively: they can never be in a disabled set."""
    if user_id is None:
        return set()
    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            return set()
    rows = (
        db.query(models.UserModulePref)
        .filter(
            models.UserModulePref.user_id == user_id,
            models.UserModulePref.enabled.is_(False),
        )
        .all()
    )
    return {
        row.module_id
        for row in rows
        if row.module_id not in CORE_ALWAYS_ON_MODULES
    }


def _transitive_feature_dependencies(
    module_id: str, modules: dict
) -> list[str]:
    """Every feature module `module_id` depends on, directly or
    transitively, in dependency-walk order (infrastructure deps
    are leaves and never listed)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    stack = list(modules[module_id].dependencies)
    while stack:
        dep = stack.pop(0)
        if dep not in modules or dep in seen_set:
            continue
        seen_set.add(dep)
        seen.append(dep)
        stack.extend(modules[dep].dependencies)
    return seen


def _fails_user_layer(module_id: str, disabled: set[str], modules: dict) -> bool:
    """Does the USER layer hide this module? True when the user
    switched the module itself off, or switched off any feature
    module it (transitively) depends on."""
    if module_id in disabled:
        return True
    return any(
        dep in disabled
        for dep in _transitive_feature_dependencies(module_id, modules)
    )


def effective_for_user(
    db: Session,
    module_id: str,
    user_groups,
    modules: dict | None = None,
    user_id=None,
    tier: str | None = None,
    beta_tester: bool = False,
) -> bool:
    """The one gate every surface consults (require_module, nav,
    stats): is this module usable by an account holding these
    groups right now? When `user_id` is given, the per-user layer
    applies on top of the operator layer: the module must also
    survive the user's own switches (its own switch on, and no
    feature dependency switched off).

    The TIER layer (2026-10-31) applies whenever the caller passes
    the account's rung (`tier`) — every user-context caller does.
    Callers resolving access for a not-yet-existing or anonymous
    account omit it and get the normal rung, no beta. The god rung
    bypasses every access layer (global, group, tier, per-user):
    god sees and can use all modules, parked or not. The graph
    gate above the bypass is code health, not access, and binds
    god too."""
    modules = _feature_modules() if modules is None else modules
    if module_id not in modules:
        return False
    if module_id in graph_blocked(modules):
        return False
    if tier == "god":
        return True
    if not globally_enabled(db, module_id):
        return False
    if dependency_blocker(db, module_id, modules) is not None:
        return False
    # A group-waived rung (tiers.group_layer_waived — the
    # downloads rung, 2026-11-09) holds no account groups by
    # design — its accounts have not picked a type (the pick
    # belongs to a later release), so the group layer cannot be
    # its gate. For a waived rung the group test is skipped and
    # the TIER cell below is the whole entitlement: for the
    # downloads rung, the tier key is the group. Every other
    # layer (global, graph, dependencies, tier, per-user)
    # applies exactly as for any account.
    if not tiers.group_layer_waived(tier) and not bool(
        assigned_groups(db, module_id, modules) & set(user_groups)
    ):
        return False
    keys = tiers.applicable_tier_keys(tier or "normal", beta_tester)
    if _fails_tier_layer(module_id, keys, modules, db):
        return False
    if user_id is not None:
        disabled = user_disabled_module_ids(db, user_id)
        if _fails_user_layer(module_id, disabled, modules):
            return False
    return True


def visible_module_ids(
    db: Session,
    user_id,
    user_groups,
    tier: str | None = None,
    beta_tester: bool = False,
) -> set[str]:
    """Every feature module id passing effective_for_user WITH the
    user layer — the set the caller can actually see and use. The
    tier layer applies when the caller passes the account's rung."""
    modules = _feature_modules()
    return {
        module_id
        for module_id in modules
        if effective_for_user(
            db,
            module_id,
            user_groups,
            modules,
            user_id=user_id,
            tier=tier,
            beta_tester=beta_tester,
        )
    }


def _nav(manifest) -> dict | None:
    if manifest.nav_path is None:
        return None
    return {
        "label": manifest.nav_label,
        "path": manifest.nav_path,
        "order": manifest.nav_order,
    }


def effective_modules(
    db: Session,
    user_groups,
    user_id=None,
    tier: str | None = None,
    beta_tester: bool = False,
) -> list[dict]:
    """GET /api/core/my-modules payload: the caller's effective
    feature modules with the nav metadata the shell renders. When
    `user_id` is given, the per-user layer applies too — modules
    the user switched off (or that hang off one) drop out."""
    modules = _feature_modules()
    result = []
    for module_id, manifest in modules.items():
        if effective_for_user(
            db,
            module_id,
            user_groups,
            modules,
            user_id=user_id,
            tier=tier,
            beta_tester=beta_tester,
        ):
            result.append(
                {
                    "id": module_id,
                    "name": manifest.name,
                    "description": manifest.description,
                    "provides": list(manifest.provides),
                    "depends_on": list(manifest.dependencies),
                    "nav": _nav(manifest),
                }
            )
    result.sort(key=lambda m: (m["nav"] or {}).get("order") or 0)
    return result


# -- per-user switches ---------------------------------------------------


def user_module_prefs(db: Session, user) -> list[dict]:
    """GET /api/core/my-module-prefs payload: every feature module
    that is OPERATOR-effective for the user's groups (regardless
    of the user layer), with the user's own switch state on it.

    `user_enabled` is the user's own switch; `visible` is whether
    the module actually shows for them right now (switch on AND
    no switched-off dependency); `blocked_by` names the first
    DIRECT feature dependency that fails the user layer while
    this module's own switch is on — the reason a module can be
    on yet invisible (dealers off ⇒ truck accounts blocked)."""
    modules = _feature_modules()
    user_groups = user.account_types
    user_tier = tiers.resolved_tier(user)
    user_beta = bool(getattr(user, "beta_tester", False))
    disabled = user_disabled_module_ids(db, user.id)
    result = []
    for module_id, manifest in modules.items():
        if not effective_for_user(
            db, module_id, user_groups, modules, tier=user_tier, beta_tester=user_beta
        ):
            continue
        user_enabled = module_id not in disabled
        blocked_by = None
        if user_enabled:
            for dep in manifest.dependencies:
                if dep not in modules:
                    continue
                if _fails_user_layer(dep, disabled, modules):
                    blocked_by = dep
                    break
        result.append(
            {
                "id": module_id,
                "name": manifest.name,
                "label": manifest.nav_label or manifest.name,
                "description": manifest.description,
                "nav": _nav(manifest),
                "switchable": module_id not in CORE_ALWAYS_ON_MODULES,
                "user_enabled": user_enabled,
                "visible": effective_for_user(
                    db,
                    module_id,
                    user_groups,
                    modules,
                    user_id=user.id,
                    tier=user_tier,
                    beta_tester=user_beta,
                ),
                "blocked_by": blocked_by,
            }
        )
    result.sort(key=lambda m: (m["nav"] or {}).get("order") or 0)
    return result


def set_user_module_pref(db: Session, user, module_id: str, enabled: bool) -> dict:
    """Flip the CALLER's own switch for one module (upsert).
    Raises KeyError for an unknown module, ValueError with
    "module_always_on" for an always-on module, and PermissionError
    when the module isn't operator-effective for the user's
    groups — a user can never switch (on or off) a module their
    account doesn't entitle. Returns the module's prefs entry."""
    modules = _feature_modules()
    if module_id not in modules:
        raise KeyError(module_id)
    if not user.account_types:
        # No account type, no module picking (owner ruling
        # 2026-11-07): entitlement is read off the account's
        # groups, so an account that hasn't picked any has
        # nothing to switch. The group-overlap check below
        # already refuses a typeless non-god account with this
        # same PermissionError; naming it here makes the refusal
        # explicit and uniform — the god bypass inside
        # effective_for_user would otherwise wave even a
        # typeless account through.
        raise PermissionError(module_id)
    if module_id in CORE_ALWAYS_ON_MODULES:
        raise ValueError("module_always_on")
    if not effective_for_user(
        db,
        module_id,
        user.account_types,
        modules,
        tier=tiers.resolved_tier(user),
        beta_tester=bool(getattr(user, "beta_tester", False)),
    ):
        raise PermissionError(module_id)
    row = (
        db.query(models.UserModulePref)
        .filter(
            models.UserModulePref.user_id == user.id,
            models.UserModulePref.module_id == module_id,
        )
        .one_or_none()
    )
    if row is None:
        row = models.UserModulePref(
            user_id=user.id, module_id=module_id, enabled=enabled
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.commit()
    return next(m for m in user_module_prefs(db, user) if m["id"] == module_id)


def module_options(db: Session, groups) -> list[dict]:
    """The public signup preview: the modules operator-effective
    for a group set, with the switchable flag (always-on modules
    ride along, marked not switchable). No user layer — nobody
    has switched anything yet."""
    modules = _feature_modules()
    result = []
    for module_id, manifest in modules.items():
        if effective_for_user(db, module_id, groups, modules):
            result.append(
                {
                    "id": module_id,
                    "name": manifest.name,
                    "label": manifest.nav_label or manifest.name,
                    "description": manifest.description,
                    "nav": _nav(manifest),
                    "switchable": module_id not in CORE_ALWAYS_ON_MODULES,
                }
            )
    result.sort(key=lambda m: (m["nav"] or {}).get("order") or 0)
    return result


def apply_signup_module_choices(db: Session, user, disabled_ids) -> None:
    """Apply a new account's signup module choices: one disabled
    pref row per requested id that is a known feature module, not
    always-on, and operator-effective for the new user's groups.
    Everything else is silently ignored, and this helper NEVER
    raises — signup must not fail over a module choice."""
    try:
        if not disabled_ids:
            return
        modules = _feature_modules()
        seen: set[str] = set()
        changed = False
        for module_id in disabled_ids:
            if not isinstance(module_id, str) or module_id in seen:
                continue
            seen.add(module_id)
            if module_id not in modules:
                continue
            if module_id in CORE_ALWAYS_ON_MODULES:
                continue
            if not effective_for_user(
                db,
                module_id,
                user.account_types,
                modules,
                tier=tiers.resolved_tier(user),
                beta_tester=bool(getattr(user, "beta_tester", False)),
            ):
                continue
            row = (
                db.query(models.UserModulePref)
                .filter(
                    models.UserModulePref.user_id == user.id,
                    models.UserModulePref.module_id == module_id,
                )
                .one_or_none()
            )
            if row is None:
                db.add(
                    models.UserModulePref(
                        user_id=user.id, module_id=module_id, enabled=False
                    )
                )
            else:
                row.enabled = False
            changed = True
        if changed:
            db.commit()
    except Exception:
        db.rollback()


# -- operator surface ------------------------------------------------------


def admin_matrix(db: Session) -> list[dict]:
    """GET /api/admin/modules payload: every feature module with its
    manifest, both switch layers, and dependency health — the whole
    control picture in one read."""
    modules = _feature_modules()
    matrix = []
    for module_id, manifest in modules.items():
        rows = {
            row.account_group: bool(row.enabled)
            for row in db.query(models.ModuleAccess)
            .filter(models.ModuleAccess.module_id == module_id)
            .all()
        }
        if rows:
            groups = {g: rows.get(g, False) for g in ACCOUNT_TYPES}
        else:
            defaults = set(manifest.default_groups)
            groups = {g: g in defaults for g in ACCOUNT_TYPES}
        matrix.append(
            {
                "id": module_id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "provides": list(manifest.provides),
                "depends_on": list(manifest.dependencies),
                "default_groups": list(manifest.default_groups),
                "nav": _nav(manifest),
                "globally_enabled": globally_enabled(db, module_id),
                "groups": groups,
                "tiers": tier_switches(db, module_id),
                "dependency_status": dependency_status(db, module_id, modules),
            }
        )
    matrix.sort(key=lambda m: (m["nav"] or {}).get("order") or 0)
    return matrix


def set_global_enabled(db: Session, module_id: str, enabled: bool) -> dict:
    """Flip the kill switch (upsert). Raises KeyError for an unknown
    module — the route turns that into a 404."""
    _manifest(module_id)
    row = db.get(models.ModuleState, module_id)
    if row is None:
        row = models.ModuleState(module_id=module_id, globally_enabled=enabled)
        db.add(row)
    else:
        row.globally_enabled = enabled
    db.commit()
    return next(m for m in admin_matrix(db) if m["id"] == module_id)


def set_group_assignment(
    db: Session, module_id: str, group: str, enabled: bool
) -> dict:
    """Assign/unassign one group (upsert the cell). Raises KeyError
    for an unknown module, ValueError for an unknown group.

    First write materializes the module's other cells from its
    defaults, so a single toggle can never silently drop the groups
    the operator didn't touch (the no-rows fallback would otherwise
    stop applying the moment one row exists)."""
    manifest = _manifest(module_id)
    if group not in ACCOUNT_TYPES:
        raise ValueError(f"Unknown account group: {group}")
    existing = {
        row.account_group: row
        for row in db.query(models.ModuleAccess)
        .filter(models.ModuleAccess.module_id == module_id)
        .all()
    }
    if not existing:
        defaults = set(manifest.default_groups)
        for g in ACCOUNT_TYPES:
            existing[g] = models.ModuleAccess(
                module_id=module_id, account_group=g, enabled=g in defaults
            )
            db.add(existing[g])
    existing[group].enabled = enabled
    db.commit()
    return next(m for m in admin_matrix(db) if m["id"] == module_id)


def set_tier_assignment(
    db: Session, module_id: str, tier: str, enabled: bool
) -> dict:
    """Light or darken one tier for one module (upsert the cell) —
    the staged-rollout switch. Raises KeyError for an unknown
    module, ValueError for an unknown tier key.

    First write materializes the module's other cells from their
    current effective values (the global-state fallback), so a
    single toggle can never silently change the tiers the
    operator didn't touch."""
    _manifest(module_id)
    if tier not in tiers.TIER_KEYS:
        raise ValueError(f"Unknown tier: {tier}")
    existing = {
        row.tier: row
        for row in db.query(models.ModuleTierAccess)
        .filter(models.ModuleTierAccess.module_id == module_id)
        .all()
    }
    if not existing:
        current = tier_switches(db, module_id)
        for key in tiers.TIER_KEYS:
            existing[key] = models.ModuleTierAccess(
                module_id=module_id, tier=key, enabled=current[key]
            )
            db.add(existing[key])
    existing[tier].enabled = enabled
    db.commit()
    return next(m for m in admin_matrix(db) if m["id"] == module_id)
