import { useEffect, useState } from "react";

import { useT } from "../i18n/LocaleContext";
import { fetchLandingConfig, type LandingConfig } from "../modules/core/landing";

const DISMISS_KEY = "tv-appbar-dismissed";
const PHONE_QUERY = "(max-width: 760px)";

/**
 * The phone app bar (owner 2026-10-24, item 10): at phone
 * widths a slim bar at the very top of the page offers both
 * app-store links — the same operator-set URLs the landing
 * page's store block uses, rendered only while the settings
 * carry them (no invented links) — with the owner's note that
 * the site works on a phone but the free app is a much better
 * experience. Signed in and signed out alike (AppShell mounts
 * it in both branches, above the construction banner).
 *
 * Marvin's call (flagged in the delivery report): the bar is
 * CLOSABLE and the close is remembered on this device
 * (localStorage) — it is a pointer to the app, not a warning.
 * The construction banner below it stays non-dismissible and
 * separate, exactly as before.
 */
export function AppStoreBar() {
  const t = useT();
  const [dismissed, setDismissed] = useState<boolean>(
    () => typeof localStorage !== "undefined" && localStorage.getItem(DISMISS_KEY) === "1",
  );
  const [isPhone, setIsPhone] = useState<boolean>(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(PHONE_QUERY).matches,
  );
  const [config, setConfig] = useState<LandingConfig | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(PHONE_QUERY);
    const onChange = (event: MediaQueryListEvent) => setIsPhone(event.matches);
    setIsPhone(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!isPhone || dismissed) return;
    let live = true;
    void fetchLandingConfig().then((loaded) => {
      if (live) setConfig(loaded);
    });
    return () => {
      live = false;
    };
  }, [isPhone, dismissed]);

  if (!isPhone || dismissed || !config) return null;
  const appStore = config.app_store_url.trim();
  const playStore = config.play_store_url.trim();
  if (!appStore && !playStore) return null;

  return (
    <div className="tv-appbar" role="region" aria-label={t("landing.appbar.note")}>
      <span className="tv-appbar-note">{t("landing.appbar.note")}</span>
      <span className="tv-appbar-links">
        {appStore && (
          <a className="tv-appbar-link" href={appStore} target="_blank" rel="noreferrer">
            {t("landing.appbar.appStore")}
          </a>
        )}
        {playStore && (
          <a className="tv-appbar-link" href={playStore} target="_blank" rel="noreferrer">
            {t("landing.appbar.googlePlay")}
          </a>
        )}
      </span>
      <button
        type="button"
        className="tv-appbar-close"
        aria-label={t("landing.appbar.close")}
        onClick={() => {
          try {
            localStorage.setItem(DISMISS_KEY, "1");
          } catch {
            /* storage unavailable: the close still applies to this view */
          }
          setDismissed(true);
        }}
      >
        ×
      </button>
    </div>
  );
}
