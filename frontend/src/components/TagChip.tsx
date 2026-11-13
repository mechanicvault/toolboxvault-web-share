import type { CSSProperties } from "react";

/** The fixed tag palette (gap wave 1) — mirrors the backend's
 *  TAG_COLORS in inventory/service.py; the hexes live in the
 *  theme layer (--tag-* in tokens.css). */
export const TAG_COLORS = [
  "amber",
  "red",
  "orange",
  "yellow",
  "green",
  "blue",
  "purple",
  "pink",
  "slate",
  "gray",
] as const;

export type TagColor = (typeof TAG_COLORS)[number];

/** A tag rendered with its color: a pill with a colored dot.
 *  Unknown/legacy color names fall back to amber (the default). */
export function TagChip({
  name,
  color,
  selected = false,
}: {
  name: string;
  color?: string | null;
  selected?: boolean;
}) {
  const known = (TAG_COLORS as readonly string[]).includes(color ?? "")
    ? (color as string)
    : "amber";
  const style = { "--tag-color": `var(--tag-${known})` } as CSSProperties;
  return (
    <span
      className={`tv-tag-chip${selected ? " tv-tag-chip--selected" : ""}`}
      style={style}
    >
      <span className="tv-tag-chip-dot" aria-hidden="true" />
      {/* The label span is what truncates, exactly like the
          Badge's (F1-06): a bare text node as a flex child
          cannot shrink/ellipsise. When it does truncate, the
          pill tooltip (components/PillTip.tsx) carries the
          full name on hover. */}
      <span className="tv-tag-chip-label">{name}</span>
    </span>
  );
}
