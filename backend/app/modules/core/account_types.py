"""Account groups (owner directive 2026-10-17, as corrected the same
day): every user belongs to one or MORE groups — the pick is a SET,
not a single choice. A tool dealer who also turns wrenches is both
`tool_dealer` and `mechanic_technician`; a shop is `shop_company`
and may also deal. Signup requires at least one group — no default,
no skipping, no empty set.

The groups drive what a user sees and can do: each group's home
overview shows its own stats, and modules declare which groups they
serve. Access is a UNION — a module or stat is available when ANY of
the user's groups is in its declared set.

This module is the single home of the group vocabulary: schemas
validate against it, the service formats account numbers from it,
and core's `require_account_type` dependency gates routes with it.
"""

# The four groups, in canonical order. This order is also the
# account-number segment order (M, S, D, I) — see
# service.format_account_number.
ACCOUNT_TYPES: tuple[str, ...] = (
    "mechanic_technician",
    "shop_company",
    "tool_dealer",
    "insurance",
)

# The letter each group contributes to an account number's segment:
# TV-{SEG}-{seq}, e.g. TV-MD-000123 for a mechanic who also deals.
ACCOUNT_TYPE_SEGMENTS: dict[str, str] = {
    "mechanic_technician": "M",
    "shop_company": "S",
    "tool_dealer": "D",
    "insurance": "I",
}


def canonical_order(account_types: list[str]) -> list[str]:
    """The given group set as a list in canonical (ACCOUNT_TYPES)
    order, duplicates removed. Storage is always canonical so sets
    compare equal regardless of the order a client sent them in."""
    chosen = set(account_types)
    return [t for t in ACCOUNT_TYPES if t in chosen]


# The groups a user may pick for THEMSELVES — signup, the one-time
# choose-group prompt, and the Settings group editor. Owner directive
# 2026-10-31: insurance is OFF the self-serve list for now ("keep
# insurance companies off the list for account types, we will add that
# back in later"). The group itself stays in the system, dormant:
# ACCOUNT_TYPES above is untouched, so the data model, the account-
# number segments, the module group-assignment machinery and the
# insurance-claims party path all keep working, and an operator can
# still provision an insurance account through the service layer
# (service.create_user / service.set_account_types accept the full
# vocabulary). To bring insurance back: add "insurance" to this
# tuple and to the frontend mirror (SELF_SERVE_ACCOUNT_TYPES in
# frontend/src/modules/core/accountTypes.ts) — nothing else changes.
SELF_SERVE_ACCOUNT_TYPES: tuple[str, ...] = (
    "mechanic_technician",
    "shop_company",
    "tool_dealer",
)


def resolve_self_serve_set(
    requested: list[str], current: list[str]
) -> list[str]:
    """The group set a self-serve change lands on. The caller's pick
    controls only the SELF_SERVE_ACCOUNT_TYPES groups; any group
    outside that list already on the account (operator-assigned —
    e.g. insurance) is preserved untouched: it can neither be added
    nor removed through a self-serve surface. For a brand-new pick
    (signup, first choose-group) `current` is empty and the result
    is simply the requested self-serve groups."""
    picked = {t for t in requested if t in SELF_SERVE_ACCOUNT_TYPES}
    kept = {t for t in current if t not in SELF_SERVE_ACCOUNT_TYPES}
    return canonical_order(list(picked | kept))
