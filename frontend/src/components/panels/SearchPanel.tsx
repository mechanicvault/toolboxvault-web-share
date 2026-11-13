import { NavLink } from "react-router-dom";

import { useT } from "../../i18n/LocaleContext";
import { PanelUtility } from "./PanelUtility";

/**
 * The global search results panel (owner spec, 2026-10-25):
 * modeled on the notifications panel — the way back Home over
 * the shared utility block (whose search well targets this same
 * page, so refining a search from the panel works).
 */
export function SearchPanel() {
  const t = useT();
  return (
    <>
      <p className="tv-sp-kicker">Search</p>
      <h2 className="tv-sp-title">{t("search.title")}</h2>
      <NavLink to="/" end className="tv-sp-item">
        <span>Home</span>
      </NavLink>
      <PanelUtility />
    </>
  );
}
