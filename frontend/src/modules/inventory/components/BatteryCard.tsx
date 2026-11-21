import { Badge } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { type Battery, type WarrantyStatus } from "../types";

/**
 * Battery display helpers shared by the list rows and the
 * battery page: the warranty chip and the spec-chip line.
 * (This file once also carried the battery TILE component; the
 * tiles view was removed outright — owner, 2026-11-05 — and
 * only the helpers other surfaces still use remain.)
 */

export const WARRANTY_TONES: Record<
  WarrantyStatus,
  "success" | "warning" | "danger" | "neutral"
> = {
  in_warranty: "success",
  expiring_soon: "warning",
  expired: "danger",
  unknown: "neutral",
};

/** The warranty chip: color carries the standing (token tones —
 *  green in warranty, amber expiring, red expired). */
export function WarrantyBadge({ battery }: { battery: Battery }) {
  const t = useT();
  return (
    <Badge tone={WARRANTY_TONES[battery.warranty_status]} dot>
      {t(`inventory.warranty.${battery.warranty_status}` as never)}
    </Badge>
  );
}

/** The battery spec chips: platform · voltage · capacity, e.g.
 *  "M18" / "18V" / "5.0 Ah" — only the facts the battery carries,
 *  each ONCE (F1-16): when the platform already states the voltage
 *  ("20V MAX", "14.4V") the separate voltage chip is a duplicate
 *  and is dropped. */
export function batterySpecChips(battery: Battery): string[] {
  const chips: string[] = [];
  if (battery.platform) chips.push(battery.platform);
  if (battery.voltage) {
    const voltage = `${Number(battery.voltage)}V`;
    const platform = (battery.platform || "").toUpperCase();
    if (!platform.startsWith(voltage.toUpperCase())) chips.push(voltage);
  }
  if (battery.capacity_ah) chips.push(`${Number(battery.capacity_ah)} Ah`);
  if (battery.chemistry) chips.push(battery.chemistry);
  return chips;
}
