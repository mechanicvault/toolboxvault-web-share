import { useEffect, useState } from "react";
import { useAuth } from "../core";
import { useT } from "../../i18n/LocaleContext";
import { listCompanies } from "./api";
import FindAgentPanel from "./components/FindAgentPanel";
import FindLocalAgentPanel from "./components/FindLocalAgentPanel";
import type { DealerCompany } from "./types";

/**
 * Find an Agent, standalone (dealer build): at its own URL —
 * signed-in users get the stage-3 Find local Agent search
 * (ZIP + radius, connect joins the roster), signed-out visitors
 * get the read-only public twin of the coverage search (the
 * directory itself is a signed-in surface; searching who's
 * around is public).
 */
export default function FindAgentPage() {
  const { user } = useAuth();
  const t = useT();
  const [directory, setDirectory] = useState<DealerCompany[]>([]);

  useEffect(() => {
    if (!user) return;
    listCompanies()
      .then((cs) => setDirectory(cs.filter((c) => c.is_directory)))
      .catch(() => setDirectory([]));
  }, [user]);

  return (
    <div className="tv-findagent" style={{ display: "grid", gap: "var(--spacing)" }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Find an agent</h1>
        <p style={{ color: "var(--text-muted)", margin: "0.35rem 0 0" }}>
          {user
            ? t("dealers.findLocal.pageIntro")
            : "Dealer agents who cover your area — search by ZIP, city, or address."}
        </p>
      </div>
      {user ? (
        <FindLocalAgentPanel />
      ) : (
        <FindAgentPanel
          directory={directory}
          onPreferredChanged={() => {}}
          publicMode
        />
      )}
    </div>
  );
}
