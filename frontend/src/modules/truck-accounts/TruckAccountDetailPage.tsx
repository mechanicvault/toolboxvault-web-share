import { Link, useParams } from "react-router-dom";
import { usePageCrumbs } from "../../lib/navTrail";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import TruckAccountWorkbench from "./TruckAccountWorkbench";
import "./truck.css";

/**
 * One truck account, standalone (Stage 2, 2026-11-05): a slim
 * wrapper around TruckAccountWorkbench — the same panels the
 * Truck Accounts overview renders inside the account's tab, so
 * the deep link and the tab can never drift. The overview tab
 * is the primary home now; this route stays for bookmarks,
 * notifications, dealer-page links and the home widget.
 */
export default function TruckAccountDetailPage() {
  const t = useT();
  const { id } = useParams<{ id: string }>();

  // The link tree lives in the shell bar, right of the back /
  // forward arrows (owner ruling 2026-11-03).
  usePageCrumbs([
    { label: t("nav.truck-accounts"), to: "/truck-accounts" },
    { label: t("truck.detail.crumbAccount") },
  ]);

  if (!id) {
    return (
      <RequireAuth>
        <p className="tv-truck-loading">{t("truck.detail.incompleteLink")}</p>
      </RequireAuth>
    );
  }
  return (
    <RequireAuth>
      <div className="tv-truck-stack" style={{ gap: "var(--spacing)" }}>
        <TruckAccountWorkbench accountId={id} />
        <p style={{ margin: 0 }}>
          <Link
            to={`/truck-accounts#account=${id}`}
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {t("truck.detail.inOverview")}
          </Link>
        </p>
      </div>
    </RequireAuth>
  );
}
