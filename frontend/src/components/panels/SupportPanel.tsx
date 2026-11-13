import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { PanelUtility } from "./PanelUtility";

/**
 * The Help & Support panel (Home + Header program, 2026-10-24):
 * the ? door's landing context — the three things the help page
 * carries, as panel doors, over the shared utility block.
 */
export function SupportPanel() {
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
      <p className="tv-sp-kicker">Support</p>
      <h2 className="tv-sp-title">{t("help.title")}</h2>
      {item("/help", t("help.ticketsTitle"), true)}
      {item("/forum", t("help.forumTitle"))}
      {item("/terms", t("help.termsTitle"))}
      <PanelUtility />
    </>
  );
}
