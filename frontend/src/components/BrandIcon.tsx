import type { CSSProperties } from "react";

import { ArtIcon, type ArtName } from "./ArtIcon";

/**
 * The `brand-icon` face used across the signed-out pages and the
 * empty states (fixed F3-03): a 2.5rem rounded tile in the
 * signed-in user's accent at resting alpha, lifting to full
 * colour on group hover — carrying REAL COLOURED ARTWORK from
 * the central library (REAL ICONS lane, owner 2026-11-05: "if we
 * use icons for something, i want real colored icons, not plain
 * flat clipart"). The tile keeps its accent-tinted seat; the
 * artwork itself is full-colour library art (components/
 * ArtIcon.tsx), the same pieces the rail, Home and search wear,
 * so a concept looks identical everywhere it appears. The
 * `name` keys are the historical face names; each maps to one
 * library piece.
 */

export type BrandIconName =
  | "apps-grid"
  | "briefcase"
  | "chart-up"
  | "check-badge"
  | "chat-green"
  | "cloud-upload"
  | "info"
  | "layers"
  | "refresh"
  | "search"
  | "share-green"
  | "share-nodes"
  | "shield-check";

const FACES: Record<BrandIconName, ArtName> = {
  "apps-grid": "categories",
  briefcase: "dealers",
  "chart-up": "reports",
  "check-badge": "badge",
  "chat-green": "messages",
  "cloud-upload": "backup",
  info: "info",
  layers: "inventory",
  refresh: "repairs",
  search: "search",
  "share-green": "shared",
  "share-nodes": "shared",
  "shield-check": "claims",
};

export function BrandIcon({
  name,
  size = 20,
}: {
  name: string;
  size?: number;
}) {
  const art = FACES[name as BrandIconName] ?? "categories";
  const style = {
    "--brand-icon-size": `${size}px`,
  } as CSSProperties;
  return (
    <span className="tv-brand-icon" style={style} aria-hidden="true">
      <ArtIcon name={art} size={size} />
    </span>
  );
}
