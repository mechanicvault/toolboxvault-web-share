import type { ReactNode } from "react";

import { useTheme } from "../theme/ThemeContext";
import { VaultPanel } from "./VaultPanel";

export interface PanelProps {
  /** Plain text, or rich content (e.g. a Link) for card headers
   *  that navigate. Rendered inside the header's <h2>. */
  title?: ReactNode;
  /** Rendered at the right end of the header row (buttons, badges…). */
  actions?: ReactNode;
  children: ReactNode;
  /**
   * Explicit visual variant — never a forked copy of this component.
   * `plate` gets the riveted nameplate header (the Steel showpiece look;
   * degrades to a plain header in other themes).
   */
  variant?: "default" | "raised" | "accent-edge" | "plate";
  className?: string;
  style?: React.CSSProperties;
}

/** Standard panel/card. All modules render boxed content through this. */
export function Panel(props: PanelProps) {
  const { theme } = useTheme();
  /* Retired Steel (theme id exactly "steel") rendered through the
   * VaultPanel frame. Rail Steel (the single shipping theme since
   * the 2026-10-23 conversion) takes the classic .tv-panel
   * rendering below, restyled by tokens + themes/railsteel.css —
   * the branch stays for a possible revival of the retired id. */
  if ((theme as string) === "steel") {
    return <VaultPanel {...props} />;
  }
  const { title, actions, children, variant = "default", className, style } = props;
  const classes = [
    "tv-panel",
    variant === "raised" ? "tv-panel--raised" : "",
    variant === "accent-edge" ? "tv-panel--accent-edge" : "",
    variant === "plate" ? "tv-panel--plate" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <section className={classes} style={style}>
      {(title || actions) && (
        <div className="tv-panel-header">
          {title ? <h2 className="tv-panel-title">{title}</h2> : <span />}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
