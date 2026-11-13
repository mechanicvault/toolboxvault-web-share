/**
 * Account groups — the frontend mirror of the backend vocabulary
 * (backend/app/modules/core/account_types.py). A user belongs to a
 * SET of groups (multi-select): the pick is forced at signup (at
 * least one), access and overview stats are the UNION of the set,
 * and the account number's segment is the set's letters in the
 * canonical order below (M, S, D, I).
 */
export type AccountType =
  | "mechanic_technician"
  | "shop_company"
  | "tool_dealer"
  | "insurance";

export interface AccountTypeOption {
  value: AccountType;
  label: string;
  /** One line: who this group is for (signup picker cards). */
  description: string;
}

/** Canonical order — also the account-number segment order. */
export const ACCOUNT_TYPE_OPTIONS: AccountTypeOption[] = [
  {
    value: "mechanic_technician",
    label: "Mechanic / Technician",
    description: "You turn the wrenches — your tools, your claims, your records.",
  },
  {
    value: "shop_company",
    label: "Shop / Company",
    description:
      "You run a shop or crew — employees, shared tools, shop-wide oversight.",
  },
  {
    value: "tool_dealer",
    label: "Tool Dealer",
    description:
      "You sell the tools — customer accounts, truck accounts, and balances.",
  },
  {
    value: "insurance",
    label: "Insurance Agent / Company",
    description: "You handle coverage and claims for Toolbox Vault customers.",
  },
];

export const ALL_ACCOUNT_TYPES: AccountType[] = ACCOUNT_TYPE_OPTIONS.map(
  (o) => o.value,
);

/**
 * The groups a user may pick for THEMSELVES — the signup picker, the
 * choose-group prompt, and the Settings group editor. Mirror of the
 * backend's SELF_SERVE_ACCOUNT_TYPES (account_types.py). Owner
 * directive 2026-10-31: insurance is OFF the self-serve list for now.
 * The group itself stays fully in the system above (labels, module
 * assignment, the claims party path) — only the pick list shrinks.
 * To bring insurance back: add "insurance" here and to the backend
 * tuple — nothing else changes.
 */
export const SELF_SERVE_ACCOUNT_TYPES: AccountType[] = [
  "mechanic_technician",
  "shop_company",
  "tool_dealer",
];

export const SELF_SERVE_ACCOUNT_TYPE_OPTIONS: AccountTypeOption[] =
  ACCOUNT_TYPE_OPTIONS.filter((o) =>
    SELF_SERVE_ACCOUNT_TYPES.includes(o.value),
  );

export function accountTypeLabel(type: AccountType): string {
  return ACCOUNT_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type;
}

/** "Mechanic / Technician + Tool Dealer" — for profile displays. */
export function accountTypeSummary(types: readonly AccountType[]): string {
  return types.map(accountTypeLabel).join(" + ");
}

/**
 * Group-waived rungs (the frontend mirror of backend
 * tiers.group_layer_waived): the downloads level's accounts
 * hold no account types BY DESIGN — their entitlement is read
 * off their tier cells, never off groups. For such an account
 * the account-type pick is not a wizard step (its copy lays out
 * the whole hidden site), not a gate (the server refuses its
 * picks and never requires them), and not a lock on the rest
 * of the pass; group-gated surfaces (home blocks, the
 * choose-group prompt) key on this one predicate too, so a
 * future waived rung gets the same bare-minimum treatment the
 * day it exists.
 */
export function groupLayerWaived(user: { tier: string }): boolean {
  return user.tier === "downloads";
}

/**
 * Staff rungs (owner order, 2026-11-09): the accounts that run
 * the site — god, moderator_admin, moderator. The beta flag is
 * NOT a rung and never makes an account staff. Chrome that is
 * staff-only (today: the header's Testing link) keys on this
 * one predicate; everyone else — normal, the downloads level,
 * beta-flagged accounts — never sees it.
 */
export function staffTier(user: { tier: string }): boolean {
  return (
    user.tier === "god" ||
    user.tier === "moderator_admin" ||
    user.tier === "moderator"
  );
}
