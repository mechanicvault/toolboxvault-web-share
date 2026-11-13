import { useEffect, useMemo, useState } from "react";
import "./repairs.css";
import { Panel, Spinner, Tabs, type TabItem } from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import { useMyModules } from "../core/MyModules";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { ClaimsList } from "../claims/ClaimsList";
import { claimsApi } from "../claims/api";
import { getMaintenanceStats, getOutOfService } from "../maintenance/api";
import { MaintenanceSchedules } from "../maintenance/boards";
import type { OutOfServiceEntry } from "../maintenance/types";
import { OutOfServiceTab } from "./OutOfServiceTab";

/**
 * Repairs & Maintenance (owner's merge, 2026-11-05): the Claims
 * menu and the Maintenance menu fold into ONE entry and ONE
 * main tab layout page. Under the hood the claims and
 * maintenance MODULES stay separate modules with their own
 * operator/tier/user gating — only the menu and this page
 * compose them:
 *
 *   Out of service (landing) — the out-of-service board, riding
 *     on the inventory module; claim facts ride along only
 *     while the claims module is effective (the server resolves
 *     that per user). A toggle folds in the tools currently
 *     lent out.
 *   Repair claims — the open warranty claims list, exactly as
 *     the Claims page carried it (disaster claims never appear:
 *     the separation's kind scoping is untouched).
 *   Repair history — the closed warranty claims.
 *   Tool Maintenance — the maintenance schedules board.
 *
 * Each tab exists only while its module is effective for the
 * signed-in user; the page lands on Out of service, or on the
 * first available tab when that one is gated off. Deep links:
 * #out-of-service · #repair-claims · #repair-history ·
 * #tool-maintenance. The old /claims and /maintenance routes
 * redirect here (see Redirects.tsx).
 */

type TabId = "out" | "claims" | "history" | "maintenance";

const HASH_TO_TAB: Record<string, TabId> = {
  "#out-of-service": "out",
  "#repair-claims": "claims",
  "#repair-history": "history",
  "#tool-maintenance": "maintenance",
};

function RepairsHome() {
  const t = useT();
  const myModules = useMyModules();
  const [picked, setPicked] = useState<TabId | null>(null);
  const [hashTab] = useState<TabId | null>(
    () => HASH_TO_TAB[window.location.hash] ?? null,
  );
  const [board, setBoard] = useState<OutOfServiceEntry[] | null>(null);
  const [boardError, setBoardError] = useState<string | null>(null);
  const [openClaims, setOpenClaims] = useState<number | null>(null);
  const [maintDue, setMaintDue] = useState<number | null>(null);

  const invOn = myModules.has("inventory");
  const claimsOn = myModules.has("claims");
  const maintOn = myModules.has("maintenance");
  const borrowingOn = myModules.has("borrowing");

  const tabs = useMemo<TabItem[]>(() => {
    const defs: TabItem[] = [];
    if (invOn)
      defs.push({
        id: "out",
        label: t("repairs.tab.outOfService"),
        content: (
          <OutOfServiceTab
            entries={board}
            error={boardError}
            borrowingOn={borrowingOn}
          />
        ),
      });
    if (claimsOn) {
      defs.push({
        id: "claims",
        label: t("repairs.tab.claims"),
        content: <ClaimsList view="open" />,
      });
      defs.push({
        id: "history",
        label: t("repairs.tab.history"),
        content: <ClaimsList view="history" />,
      });
    }
    if (maintOn)
      defs.push({
        id: "maintenance",
        label: t("repairs.tab.maintenance"),
        content: <MaintenanceSchedules />,
      });
    return defs;
  }, [invOn, claimsOn, maintOn, borrowingOn, board, boardError, t]);

  const active: TabId | null =
    (picked && tabs.some((tab) => tab.id === picked) && picked) ||
    (hashTab && tabs.some((tab) => tab.id === hashTab) && hashTab) ||
    (tabs[0]?.id as TabId | undefined) ||
    null;

  // The board fetch doubles as the header's out-of-service
  // count; the other header facts ride each module's own stats.
  // Every fetch is best-effort for the FACTS — the tab itself
  // surfaces a board failure properly.
  useEffect(() => {
    if (myModules.loading || !invOn) return;
    let cancelled = false;
    getOutOfService()
      .then((rows) => {
        if (!cancelled) setBoard(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setBoardError(
            err instanceof ApiError
              ? err.message
              : "Couldn't load the out-of-service board.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [myModules.loading, invOn]);

  useEffect(() => {
    if (myModules.loading || !claimsOn) return;
    let cancelled = false;
    claimsApi
      .getClaimsStats()
      .then((stats) => {
        if (!cancelled) setOpenClaims(stats.open_claims_count);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [myModules.loading, claimsOn]);

  useEffect(() => {
    if (myModules.loading || !maintOn) return;
    let cancelled = false;
    getMaintenanceStats()
      .then((stats) => {
        if (!cancelled) setMaintDue(stats.maintenance_due_count);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [myModules.loading, maintOn]);

  if (myModules.loading) return <Spinner label="Loading…" />;
  if (active === null) return null;

  const title = t("repairs.title");
  const facts: { label: string; value: number }[] = [];
  if (board !== null)
    facts.push({ label: t("stat.maintenance.out_of_service"), value: board.length });
  if (openClaims !== null)
    facts.push({ label: t("stat.claims.open_claims"), value: openClaims });
  if (maintDue !== null)
    facts.push({ label: t("stat.maintenance.maintenance_due"), value: maintDue });

  return (
    <div>
      <Panel>
        <div className="tv-repairs-head">
          <div className="tv-repairs-thumb" aria-hidden="true">
            <ArtIcon name="repairs" size={96} />
          </div>
          <div className="tv-repairs-head-main">
            <h1 className="tv-repairs-title">{title}</h1>
            {facts.length > 0 && (
              <dl className="tv-repairs-facts">
                {facts.map((fact) => (
                  <div key={fact.label} className="tv-repairs-fact">
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <div className="tv-repairs-head-actions">
            <SettingsActionsMenu
              ariaLabel={title}
              buttonLabel={t("inventory.actions")}
              entries={tabs.map((tab) => ({
                key: tab.id,
                label: tab.label,
                run: () => setPicked(tab.id as TabId),
              }))}
            />
          </div>
        </div>
      </Panel>
      <Tabs
        tabs={tabs}
        activeId={active}
        onChange={(id) => setPicked(id as TabId)}
      />
    </div>
  );
}

export default function RepairsPage() {
  return (
    <RequireAuth>
      <RepairsHome />
    </RequireAuth>
  );
}
