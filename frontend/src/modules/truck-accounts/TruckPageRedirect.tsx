import { useEffect, useState } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { useT } from "../../i18n/LocaleContext";
import { getAccount } from "./api";
import "./truck.css";

/**
 * The retired standalone Truck Accounts page's addresses
 * (/truck-accounts and /truck-accounts/<id>) land here now
 * (owner order, 2026-11-17: the page is retired, everything
 * lives under the agent window). Old links — bookmarks,
 * notifications, search results, the inbox — translate to
 * the agent window's deep link and replace themselves:
 *
 * - an account id (path, or #account=<id>) opens that
 *   account's company panel on its Truck section with the
 *   account's workbench open;
 * - ?open=self&company=<id>&agent=<kind>:<ref> opens that
 *   company's panel with the self-kept modal up;
 * - anything else lands on the Dealers page, whose glance
 *   panel is the overview now.
 */
export default function TruckPageRedirect() {
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("open") === "self") {
      const company = params.get("company");
      const agent = params.get("agent");
      if (company) {
        setTarget(
          `/dealers?dealer=${company}&section=truck${agent ? `&openself=${encodeURIComponent(agent)}` : ""}`,
        );
      } else {
        setTarget("/dealers#agents");
      }
      return;
    }
    const hashMatch = location.hash.match(/account=([0-9a-f-]{32,36})/i);
    const accountId = id ?? (hashMatch ? hashMatch[1] : null);
    if (!accountId) {
      setTarget("/dealers");
      return;
    }
    let alive = true;
    getAccount(accountId)
      .then((detail) => {
        if (!alive) return;
        const companyId = detail.account.dealer_company_id;
        // The account's own id from the read (canonical
        // dashed form) — the incoming link's id may be an
        // undashed seed-era form the panel would not match.
        setTarget(
          companyId
            ? `/dealers?dealer=${companyId}&section=truck&account=${detail.account.id}`
            : "/dealers#agents",
        );
      })
      .catch(() => {
        if (alive) setTarget("/dealers");
      });
    return () => {
      alive = false;
    };
  }, [id, location.search, location.hash]);

  if (target === null) {
    return <p className="tv-truck-loading">{t("shell.loading")}</p>;
  }
  return <Navigate to={target} replace />;
}
