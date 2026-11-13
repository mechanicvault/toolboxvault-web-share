import { PinIcon } from "../../../components/icons";
import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";

/**
 * The item header's location column (owner layout correction,
 * 2026-11-02): the header is three columns — photo, main facts,
 * and the location as its own column — and this is the third.
 * The item's tier path is broken into its tiers with the site's
 * own tier labels (place / storage / spot, the canonical tree
 * shape of 2026-10-25; deeper than the third tier stays "spot",
 * the same rule the tree builder teaches). The plate is
 * deliberately quiet — a recessed surface, a hairline edge, the
 * pin in the live accent — so it stands out a little, not loud.
 * Renders nothing when the item has no location recorded: the
 * column collapses to the Actions menu alone, no dash noise.
 */
const TIER_KEYS: DictKey[] = [
  "inventory.locationTier.place",
  "inventory.locationTier.storage",
  "inventory.locationTier.spot",
];

export function ItemLocationColumn({ location }: { location: string }) {
  const t = useT();
  const segments = (location || "")
    .split(" / ")
    .map((s) => s.trim())
    .filter(Boolean);
  if (segments.length === 0) return null;
  return (
    <aside className="tv-item-loc" aria-label={t("inventory.location")}>
      <p className="tv-item-loc-head">
        <PinIcon size={15} />
        <span>{t("inventory.location")}</span>
      </p>
      <dl className="tv-item-loc-tiers">
        {segments.map((seg, i) => (
          <div className="tv-item-loc-tier" key={`${i}-${seg}`}>
            <dt>{t(TIER_KEYS[Math.min(i, TIER_KEYS.length - 1)])}</dt>
            <dd>{seg}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
