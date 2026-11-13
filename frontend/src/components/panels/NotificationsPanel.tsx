import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { PanelUtility } from "./PanelUtility";

/**
 * The notifications page panel (Home + Header program): the
 * inbox's doors — back Home, and over to Help & Support where
 * ticket answers come from — over the shared utility block.
 */
export function NotificationsPanel() {
  const t = useT();
  const item = (to: string, label: string, end = false) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      className={({ isActive }) => `tv-sp-item${isActive ? " is-active" : ""}`}
    >
      <span>{label}</span>
    </NavLink>
  );
  return (
    <>
      <p className="tv-sp-kicker">Inbox</p>
      <h2 className="tv-sp-title">{t("notifications.title")}</h2>
      {item("/", "Home", true)}
      {item("/help", t("help.title"))}
      <PanelUtility />
    </>
  );
}
