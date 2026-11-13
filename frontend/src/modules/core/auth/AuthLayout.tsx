import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Panel } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";

/** Shared shell for the auth pages: one centered panel, one look.
 *  `wide` swaps the standard 440px column for the 880px shell used
 *  by the pages carrying the group picker (signup, choose-group);
 *  login and the callback keep the standard column.
 *  No in-page logo (owner ruling 2026-10-17: it ate screen space) —
 *  the panel heading is the top element; the brand lives in the
 *  app header and the favicon.
 *  Rail Steel Phase 4 (2026-10-24): the panel is the vault panel
 *  (grain, bevel, corner bolts — themes/railsteel.css, scoped to
 *  .tv-auth-panel); the footer/back/legal lines ride the shared
 *  .tv-auth-* classes there, no inline styles. */
export function AuthLayout({
  title,
  children,
  footer,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const t = useT();
  return (
    <div className={`tv-auth-shell${wide ? " tv-auth-shell--wide" : ""}`}>
      <Panel title={title} className="tv-auth-panel">
        {children}
        {footer && (
          <p className="tv-auth-foot-note">
            {footer}
          </p>
        )}
      </Panel>
      <p className="tv-auth-back">
        <Link to="/" className="tv-auth-back-link">
          {t("auth.backHome")}
        </Link>
      </p>
      <p className="tv-auth-legal">
        <Link to="/terms" className="tv-auth-legal-link">
          {t("auth.terms")}
        </Link>
        <span className="tv-auth-legal-sep">{"  ·  "}</span>
        <Link to="/privacy" className="tv-auth-legal-link">
          {t("auth.privacy")}
        </Link>
      </p>
    </div>
  );
}
