import { useLocation } from "react-router-dom";
import { useT } from "../i18n/LocaleContext";
import { ArtIcon } from "./ArtIcon";

/**
 * Site-wide UNDER CONSTRUCTION strip (owner ruling 2026-10-18):
 * a finishing-status notice that rides at the top of every
 * page. Mounted once by AppShell above the header, so it covers
 * every page, every layout, every theme — the auth pages
 * included.
 *
 * NO dismiss control, on purpose: this is not a cookie notice.
 * It comes down on launch day, as a code change.
 *
 * Copy expansion (owner order, 2026-11-10): the banner also
 * warns that the site is CONSTANTLY changing while we build —
 * over the next few weeks pages and features may change,
 * sometimes without warning — so a change like the Home
 * dashboard reset never lands on a user unexplained. Copy only:
 * same component, same placement, same always-on behavior; the
 * text rides the dictionary like the rest of the site.
 *
 * Registration doors stand the banner down (sweep fix 10-F11):
 * the sign-up page itself ("You can sign up free right now")
 * and the doors that complete a registration (email
 * verification, email-change confirmation, the social sign-in
 * callback) carry their own welcome, so on those routes the
 * banner renders nothing; everywhere else — sign-in, password
 * reset, and every signed-in surface included — it stands.
 *
 * Copy correction (owner order, 2026-11-12): open signup has
 * been live since 2026-11-09, so the body no longer tells
 * anyone not to register and no longer warns that accounts
 * and data may be reset. The banner is a finishing-status
 * notice now — the site is still being polished — not a
 * registration deterrent.
 */
const REGISTRATION_PATHS: ReadonlySet<string> = new Set([
  "/signup",
  "/verify-email",
  "/confirm-email-change",
  "/auth/callback",
]);

export function ConstructionBanner() {
  const t = useT();
  const { pathname } = useLocation();
  if (REGISTRATION_PATHS.has(pathname)) return null;
  return (
    <div className="tv-construction-banner" role="note" aria-label="Site status">
      <span className="tv-construction-banner-icon" aria-hidden="true">
        <ArtIcon name="warning" size={20} />
      </span>
      <p className="tv-construction-banner-text">
        <strong>{t("shell.construction.title")}</strong>
        {` — ${t("shell.construction.body")} ${t("shell.construction.changes")}`}
      </p>
    </div>
  );
}
