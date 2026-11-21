import type { ReactNode } from "react";

import { ArtIcon, type ArtName } from "./ArtIcon";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  /** Optional decorative icon/glyph rendered above the title.
   *  Prefer `art` — a hand-written glyph here reads as flat
   *  clipart, which the real-icons rule bans for depictions. */
  icon?: ReactNode;
  /** The shared library artwork for what belongs here (Sweep
   *  A1, 2026-11-11): a FULL rendered icon from ArtIcon, never
   *  flat clipart. Renders at the Inventory zero state's seat
   *  size unless `icon` is also given (the explicit node wins). */
  art?: ArtName;
}

/**
 * The ONE shared "nothing here yet" kit (Sweep A1, 2026-11-11,
 * promoting Inventory's production zero state — the sweep's
 * model, lane 11 — to the pattern every empty surface uses):
 *
 *   - one piece of full rendered artwork (`art`),
 *   - a short title naming the empty thing,
 *   - ONE directing sentence in plain words (`description`) —
 *     what belongs here / why it is empty / who can fill it,
 *   - ONE labelled action button (`action`) — the door out of
 *     the dead end, when an honest door exists for this seat.
 *
 * A bare title alone ("state a fact and stop") is the dead end
 * this kit replaces; callers that render one must say why in
 * their lane notes. One look everywhere.
 */
export function EmptyState({ title, description, action, icon, art }: EmptyStateProps) {
  const artIcon = icon ?? (art ? <ArtIcon name={art} size={52} /> : null);
  return (
    <div className="tv-empty">
      {artIcon && <div className="tv-empty-icon" aria-hidden="true">{artIcon}</div>}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="tv-empty-action">{action}</div>}
    </div>
  );
}
