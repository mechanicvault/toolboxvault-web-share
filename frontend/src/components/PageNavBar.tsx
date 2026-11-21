import { useLocation } from "react-router-dom";

import { useT } from "../i18n/LocaleContext";
import { derivedCrumbs, useNavTrail } from "../lib/navTrail";
import { Breadcrumbs } from "./Breadcrumbs";
import { ChevronLeftIcon, ChevronRightIcon } from "./icons";

/**
 * The page navigation bar (owner directive 2026-11-02 21:21
 * CST): a slim strip in the header zone of every signed-in
 * page, directly above the page's own header — a ‹ › arrow
 * pair at the left of the header text's row (back to the
 * previous page, forward to a page the user just backed away
 * from), and the page's link tree beside it where the page has
 * one (see lib/navTrail for which pages carry which trail).
 *
 * The arrows are driven by the app's own trail, not the
 * browser's history: they grey out honestly at the trail's
 * ends, and back on a fresh deep-link load falls back to the
 * page's parent (an item lands on its list) instead of ever
 * leaving the site. Mounted once in the shell — no page builds
 * its own.
 */
export function PageNavBar() {
  const t = useT();
  const location = useLocation();
  const { backEnabled, canForward, goBack, goForward, crumbs } =
    useNavTrail();
  const trail = crumbs ?? derivedCrumbs(location.pathname, t);
  return (
    <div className="tv-pagenav">
      <div className="tv-pagenav-arrows">
        <button
          type="button"
          className="tv-pagenav-btn"
          onClick={goBack}
          disabled={!backEnabled}
          aria-label={t("nav.back")}
          title={t("nav.back")}
        >
          <ChevronLeftIcon size={16} />
        </button>
        <button
          type="button"
          className="tv-pagenav-btn"
          onClick={goForward}
          disabled={!canForward}
          aria-label={t("nav.forward")}
          title={t("nav.forward")}
        >
          <ChevronRightIcon size={16} />
        </button>
      </div>
      {trail && trail.length > 0 && <Breadcrumbs items={trail} />}
    </div>
  );
}
