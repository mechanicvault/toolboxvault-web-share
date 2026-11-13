import { useState } from "react";
import { useT } from "../../../i18n/LocaleContext";
import type { DictKey } from "../../../i18n/dictionaries";
import { useAuth } from "../../core";
import type { LocationTreeNode } from "./locationTree";

/**
 * Location tier guidance (Ryan, 2026-10-25): the location tree
 * has a canonical shape — tier 1 the PLACE (Home, Work), tier 2
 * the STORAGE at that place (a toolbox, a cabinet), tier 3 the
 * SPOT inside it (Drawer 1, a shelf, a bin) — and every surface
 * that creates a location teaches it at the moment of creation,
 * so nobody builds the tree wrong and has to redo it.
 *
 * The hint follows the tier being ADDED: it is computed from
 * the chosen parent's depth (no parent = tier 1; a place as
 * parent = tier 2; storage or deeper as parent = tier 3).
 * Copy is dictionary-driven (en + es) per the spec.
 */

export type LocationTier = 1 | 2 | 3;

export function locationTierForParent(
  flat: LocationTreeNode[],
  parentId: string,
): LocationTier {
  if (!parentId) return 1;
  const parent = flat.find((n) => n.id === parentId);
  if (!parent) return 1;
  return parent.depth >= 1 ? 3 : 2;
}

export const TIER_HINT_KEYS: Record<LocationTier, DictKey> = {
  1: "inventory.locationGuide.tier1",
  2: "inventory.locationGuide.tier2",
  3: "inventory.locationGuide.tier3",
};

export const TIER_PLACEHOLDER_KEYS: Record<LocationTier, DictKey> = {
  1: "inventory.locationGuide.placeholder1",
  2: "inventory.locationGuide.placeholder2",
  3: "inventory.locationGuide.placeholder3",
};

/** The one-line tier helper shown above a location NAME field
 *  while a location is being created. Renders nothing when the
 *  tree hasn't loaded (flat is empty and a parent was picked —
 *  the tier can't be known yet). */
export function LocationTierHint({
  flat,
  parentId,
}: {
  flat: LocationTreeNode[];
  parentId: string;
}) {
  const t = useT();
  if (parentId && flat.length === 0) return null;
  const tier = locationTierForParent(flat, parentId);
  return (
    <p
      style={hintStyle}
      data-location-tier={tier}
    >
      {t(TIER_HINT_KEYS[tier])}
    </p>
  );
}

const hintStyle = {
  margin: 0,
  color: "var(--text-muted)",
  fontSize: "0.85rem",
} as const;

const explainerStyle = {
  display: "grid",
  gap: "0.35rem",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.8rem",
  background: "var(--surface-raised, transparent)",
} as const;

/**
 * The location manager's explainer (spec: a short block at the
 * top of the manager showing the pattern once — Work → Toolbox
 * → Drawer 1, "places hold storage; storage holds spots").
 * Dismissible per user: the dismissal is a small UI preference
 * kept in localStorage scoped by account id (the same pattern
 * as the inventory list's per-user prefs); the per-tier helpers
 * in the create forms always stay.
 */
export function LocationGuideExplainer() {
  const t = useT();
  const { user } = useAuth();
  const storageKey = `tv-location-guide-dismissed:${user?.id ?? "anon"}`;
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });
  if (dismissed) return null;
  return (
    <div style={explainerStyle}>
      <strong>{t("inventory.locationGuide.title")}</strong>
      <span aria-hidden="true" style={exampleStyle}>
        {t("inventory.locationGuide.example")}
      </span>
      <p style={hintStyle}>{t("inventory.locationGuide.body")}</p>
      <div>
        <button
          type="button"
          style={dismissStyle}
          onClick={() => {
            setDismissed(true);
            try {
              localStorage.setItem(storageKey, "1");
            } catch {
              /* a private-mode browser just shows it again */
            }
          }}
        >
          {t("inventory.locationGuide.dismiss")}
        </button>
      </div>
    </div>
  );
}

const exampleStyle = {
  color: "var(--accent)",
  fontWeight: 700,
  letterSpacing: "0.02em",
} as const;

const dismissStyle = {
  background: "none",
  border: "none",
  padding: 0,
  color: "var(--accent)",
  cursor: "pointer",
  fontSize: "0.85rem",
  fontWeight: 600,
} as const;
