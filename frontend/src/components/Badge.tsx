import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

interface BadgeProps {
  tone?: BadgeTone;
  /** Small status dot before the label; glows when the theme supports it. */
  dot?: boolean;
  children: ReactNode;
}

/** Status pill. One look for every tag/status in the system. */
export function Badge({ tone = "neutral", dot = false, children }: BadgeProps) {
  return (
    <span className={`tv-badge${tone !== "neutral" ? ` tv-badge--${tone}` : ""}`}>
      {dot && <span className="tv-badge-dot" aria-hidden="true" />}
      {/* The label span is what truncates (F1-06): a bare text node
          as a flex child cannot shrink/ellipsise, so a long pill
          ("Checked out to Mike Kowalski (neighbor)") escaped its
          card. The span carries min-width:0 + ellipsis in CSS. */}
      <span className="tv-badge-label">{children}</span>
    </span>
  );
}
