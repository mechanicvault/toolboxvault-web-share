import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Panel } from "./Panel";

export interface StatCardProps {
  /** Small caps label in the head row, above the value, e.g. "Total items". */
  label: string;
  /** Pre-formatted display value, e.g. "704" or "$146,625". */
  value: string;
  /** Glyph rendered in the framed chip at the LEFT of the label (see icons.tsx). */
  icon?: ReactNode;
  /** Deep audit F5-01: when set, the WHOLE card is a link to the
   *  stat's natural destination (keyboard reachable, hover lift
   *  via .tv-stat-link). */
  href?: string;
  /** Rail Steel Phase 2c: the ONE hero tile in the overview row —
   *  the worn accent plate with end bolts (the preview's accent
   *  stat). At most one registered stat carries it; everything
   *  else about the card (label, value, href) is unchanged. */
  accent?: boolean;
  /** Icon ink tone (Home + Header program): the glyph chip's
   *  color family — a theme token, never a literal. */
  tone?: string;
  /** New Home stats widget (2026-11-10): this card wants the
   *  viewer's eyes (a warning/danger fact with a real count) —
   *  in the grid's glow mode its accent glow burns warmer. */
  alert?: boolean;
}

/**
 * One dashboard stat plate: a head row (icon chip at the LEFT,
 * caps label beside it) with the big value below it — the
 * owner's order 2026-11-03 ("the name at the top with the
 * value below that", icon to the left of the title). Corner
 * screw dots on the face. Renders through Panel, so Steel
 * wears the VaultPanel plate frame and every other theme its
 * classic panel — one component, no forked frame system.
 */
export function StatCard({ label, value, icon, href, accent, tone, alert }: StatCardProps) {
  const body = (
    <Panel className={`tv-stat-card${accent ? " tv-stat-card--accent" : ""}`}>
      <div className="tv-stat-body">
        <div className="tv-stat-head">
          {icon && (
            <span className="tv-stat-icon" data-tone={tone} aria-hidden="true">
              {icon}
            </span>
          )}
          <div className="tv-stat-label">{label}</div>
        </div>
        <div className="tv-stat-value">{value}</div>
      </div>
    </Panel>
  );
  if (href) {
    return (
      <Link
        to={href}
        className="tv-stat-link"
        data-alert={alert || undefined}
        aria-label={`${label}: ${value}`}
      >
        {body}
      </Link>
    );
  }
  return body;
}
