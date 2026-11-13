import type { CSSProperties, ReactNode } from "react";

export interface VaultPanelProps {
  /** Mirrors PanelProps.title (text, or rich header content). */
  title?: ReactNode;
  /** Rendered at the right end of the header row (buttons, badges…). */
  actions?: ReactNode;
  children: ReactNode;
  /**
   * Panel API variant, carried for compatibility. Under the VaultPanel
   * frame the manufactured rim IS the design, so variants do not fork
   * the frame: `accent-edge` moves its stripe inside the well; the
   * others render the standard frame.
   */
  variant?: "default" | "raised" | "accent-edge" | "plate";
  className?: string;
  style?: CSSProperties;
  /** Live accent lamps on all four edges (default true). */
  lights?: boolean;
  /** Lamp intensity 0..1 (default 1). */
  lightIntensity?: number;
  /** Extra content padding inside the frame bands, in px (default 14). */
  pad?: number;
}

/**
 * The slim VaultPanel frame (banner-reference system, compact
 * configuration — owner ruling 2026-10-17): continuous slim rim,
 * lamps seated directly on the plain rim, no channel tabs. All frame
 * construction lives in theme/vaultpanel.css + theme/assets/vaultpanel/;
 * the artwork is metal only and every lamp is a live --accent layer.
 * Panel renders through this component under the Steel theme only.
 */
/**
 * The manufactured frame itself: well + edges + corners + live lamps,
 * absolutely stacked inside a `.tv-vp-inner`. Shared by VaultPanel
 * and — under the Steel theme — the Modal, so a dialog and a panel
 * are literally the same frame, not two kits imitating each other.
 * All geometry lives in theme/vaultpanel.css (the --vp-u unit).
 */
export function VaultFrameStack({ lights = true }: { lights?: boolean }) {
  return (
    <div className="tv-vp-stack" aria-hidden="true">
      <div className="tv-vp-layer tv-vp-well" />
      <div className="tv-vp-layer tv-vp-edge-t" />
      <div className="tv-vp-layer tv-vp-edge-b" />
      <div className="tv-vp-layer tv-vp-edge-l" />
      <div className="tv-vp-layer tv-vp-edge-r" />
      <div className="tv-vp-layer tv-vp-corner tv-vp-c-tl" />
      <div className="tv-vp-layer tv-vp-corner tv-vp-c-tr" />
      <div className="tv-vp-layer tv-vp-corner tv-vp-c-bl" />
      <div className="tv-vp-layer tv-vp-corner tv-vp-c-br" />
      {lights && (
        <>
          <div className="tv-vp-lamp tv-vp-lamp-t" />
          <div className="tv-vp-lamp tv-vp-lamp-b" />
          <div className="tv-vp-lamp tv-vp-lamp-l" />
          <div className="tv-vp-lamp tv-vp-lamp-r" />
        </>
      )}
    </div>
  );
}

export function VaultPanel({
  title,
  actions,
  children,
  variant = "default",
  className,
  style,
  lights = true,
  lightIntensity = 1,
  pad,
}: VaultPanelProps) {
  const classes = [
    "tv-vault-panel",
    variant === "raised" ? "tv-panel--raised" : "",
    variant === "accent-edge" ? "tv-panel--accent-edge" : "",
    variant === "plate" ? "tv-panel--plate" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  const innerStyle = {
    "--vp-light": lights ? lightIntensity : 0,
    ...(pad !== undefined ? { "--vp-pad": `${pad}px` } : {}),
  } as CSSProperties;
  return (
    <section className={classes} style={style}>
      <div className="tv-vp-inner" style={innerStyle}>
        <VaultFrameStack lights={lights} />
        <div className="tv-vp-content">
          {(title || actions) && (
            <div className="tv-panel-header">
              {title ? <h2 className="tv-panel-title">{title}</h2> : <span />}
              {actions}
            </div>
          )}
          {children}
        </div>
      </div>
    </section>
  );
}
