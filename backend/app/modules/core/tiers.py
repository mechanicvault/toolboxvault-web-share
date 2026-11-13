"""Account tiers (owner design, 2026-10-31 — the account structure).

One primary RUNG per account, plus a stackable beta flag:

  god              the topmost power; full access to everything.
                   ONLY the god account itself can edit the god
                   account (admin_routes guards every edit path).
                   The rung is never grantable through the API and
                   never removable — there is no path that leaves
                   the site without its god account.
  moderator_admin  the most power below god. Granted and revoked
                   ONLY by god. Can grant/revoke the moderator rung
                   and the beta upgrade (user management).
  moderator        a normal account plus community moderation
                   (forums + community parts). Granted/revoked by
                   god or a moderator admin.
  normal           a regular account.
  downloads        the limited level (owner order, 2026-11-09):
                   the rung a no-code signup lands on while the
                   teaser gate is up. It reaches ONLY what an
                   operator has explicitly lit for its switchboard
                   key (the Downloads section's member abilities —
                   3D Print Files — plus Help & Support), and
                   nothing else: its applicable keys are exactly
                   {"downloads"}, never "normal". An admin moves
                   an account off it with the ordinary grant
                   machinery (the launch move is a flip to normal).

  beta_tester      NOT a rung — an upgrade flag that can sit on a
                   normal or moderator account (users.beta_tester).
                   Granted/revoked by god or a moderator admin. It
                   buys early access: modules switched on for the
                   beta tier reach flagged accounts before the
                   public (module_control's tier layer).

The community ROLE ladder (user | moderator | community_admin) is
the tiers' shadow on community surfaces, kept in sync by every
write path (service.set_user_tier / set_user_role): god and
moderator_admin read as community_admin, moderator as moderator,
normal and downloads as user — so the forum / messaging / feedback
gates that consume `role` keep exactly the powers the tier
promises, and nobody loses a moderation power they legitimately
had.

Module switchboard tier keys (module_control): the Admin → Modules
switches are named after WHO they light up — "normal",
"moderator", "moderator_admin", "beta", "downloads". A user's
APPLICABLE keys inherit downward: a moderator admin carries the
moderator and normal keys too; a beta flag adds the "beta" key on
top of the rung's own keys. The downloads rung is the ONE
exception to inheritance: it carries its own key alone (inheriting
"normal" would hand it the whole site), and no higher rung
inherits "downloads" (a downloads lighting is for that level
alone). God has no key — god bypasses the tier layer entirely.
"""

# The rungs, lowest to highest. "god" is a valid rung VALUE (the
# backfilled operator account carries it) but is deliberately not
# in GRANTABLE_TIERS: no API path can create or remove it.
TIERS: tuple[str, ...] = (
    "downloads",
    "normal",
    "moderator",
    "moderator_admin",
    "god",
)

# The rungs the grant machinery may set (POST /users/{id}/tier).
GRANTABLE_TIERS: tuple[str, ...] = (
    "downloads",
    "normal",
    "moderator",
    "moderator_admin",
)

# The module switchboard's tier keys (module_tier_access.tier) —
# the audiences a module can be lit for.
TIER_KEYS: tuple[str, ...] = (
    "normal",
    "moderator",
    "moderator_admin",
    "beta",
    "downloads",
)

# Community role each rung carries (the role ladder's fold-in).
ROLE_FOR_TIER: dict[str, str] = {
    "downloads": "user",
    "normal": "user",
    "moderator": "moderator",
    "moderator_admin": "community_admin",
    "god": "community_admin",
}

# The rung each legacy community role maps to (the migration's
# backfill and set_user_role's fold-in share this).
TIER_FOR_ROLE: dict[str, str] = {
    "user": "normal",
    "moderator": "moderator",
    "community_admin": "moderator_admin",
}


# The rungs that waive the GROUP layer (2026-11-09): a downloads
# account holds no account types BY DESIGN — its entitlement is
# read off its tier cells alone, so the account-type pick is not
# its gate anywhere: module_control waives the group test for it,
# the onboarding wizard carries no account-type step for it (and
# its progress writes are not refused for typelessness), the
# self-serve account-type door refuses its picks, and the legacy
# completion gate counts it incomplete on its basics alone. Every
# consumer asks THIS helper — the waiver is stated once, here.
GROUP_WAIVED_TIERS: frozenset[str] = frozenset({"downloads"})


def group_layer_waived(tier: str | None) -> bool:
    """True when the rung's accounts hold no account groups by
    design (see GROUP_WAIVED_TIERS). Unknown/empty rungs are not
    waived — they use the group layer like normal accounts."""
    return (tier or "") in GROUP_WAIVED_TIERS


def role_for_tier(tier: str | None) -> str:
    """The community role a rung carries; unknown/empty rungs read
    as a plain user."""
    return ROLE_FOR_TIER.get(tier or "", "user")


def tier_for_role(role: str | None) -> str:
    """The rung a legacy community role maps to; unknown roles read
    as the normal rung."""
    return TIER_FOR_ROLE.get(role or "", "normal")


def derive_tier(is_operator: bool, role: str | None) -> str:
    """The rung an account row carries, derived from the pre-tier
    facts. This IS the migration's backfill rule, shared so any
    account whose tier column was never written (a row created
    mid-deploy) still resolves: operator ⇒ god; community_admin ⇒
    moderator_admin; moderator ⇒ moderator; else normal."""
    if is_operator:
        return "god"
    return tier_for_role(role)


# Rung height, for the higher-of-two-writings resolution below.
_RUNG_ORDER = {
    "downloads": 0,
    "normal": 1,
    "moderator": 2,
    "moderator_admin": 3,
    "god": 4,
}


def resolved_tier(user) -> str:
    """The account's rung: the HIGHER of the stored tier and the
    rung the legacy facts (operator flag + community role) imply.
    The service setters keep the two writings in sync, so on real
    accounts they always agree; they can disagree only where
    something wrote one side of the ladder alone (a fixture that
    sets `role` on a fresh row, whose tier column defaults to
    "normal"). The fold-in doctrine — nobody loses a power they
    legitimately had — says the higher reading is the account's:
    an account the role ladder calls a moderator IS a moderator.
    Anything carrying id-less test doubles without the attributes
    resolves to the normal rung.

    ONE exception (2026-11-09): the stored downloads rung is a
    deliberate RESTRICTION, not a power, and its role shadow is
    "user" — which the legacy fold-in reads as normal. Letting
    the higher reading win there would silently promote every
    downloads account to the full site, so a stored downloads
    rung resolves as downloads. The operator flag still outranks
    it: an operator-flagged account derives god above, by the
    same fold-in as ever (flagging an account as operator is an
    admin act that means to hand over the keys)."""
    implied = derive_tier(
        bool(getattr(user, "is_operator", False)),
        getattr(user, "role", None),
    )
    stored = getattr(user, "tier", None)
    if stored not in TIERS:
        return implied
    if stored == "downloads" and implied != "god":
        return "downloads"
    return stored if _RUNG_ORDER[stored] >= _RUNG_ORDER[implied] else implied


def is_god(user) -> bool:
    """True when the account carries the god rung (by storage or
    by derivation — an operator-flagged account resolves to god
    and gets god's ACCESS: the module bypass, the admin gates)."""
    return resolved_tier(user) == "god"


def is_god_account(user) -> bool:
    """True when the account IS the god account — the identity,
    not the access: the stored rung is "god" (the account the
    migration crowned; in production, exactly one). God
    PROTECTION (admin_routes' edit guard) follows this test: the
    operator flag can be granted to another account and that
    account gains god-rung access, but the crown — the account
    only itself may edit — does not move with the flag."""
    return getattr(user, "tier", None) == "god"


def applicable_tier_keys(tier: str | None, beta_tester: bool) -> frozenset[str]:
    """The switchboard keys whose enablements reach an account with
    this rung + beta flag (inheritance: higher rungs carry the
    lower keys; beta adds its key on top of any rung below god).

    The downloads rung (2026-11-09) inherits NOTHING: its keys are
    exactly {"downloads"} (+ beta if flagged). Carrying "normal"
    would hand the limited level every module lit for the public,
    which is precisely what the rung exists to prevent."""
    if tier == "downloads":
        keys = {"downloads"}
        if beta_tester:
            keys.add("beta")
        return frozenset(keys)
    keys = {"normal"}
    if tier == "moderator":
        keys.add("moderator")
    elif tier == "moderator_admin":
        keys.update({"moderator", "moderator_admin"})
    if beta_tester:
        keys.add("beta")
    return frozenset(keys)
