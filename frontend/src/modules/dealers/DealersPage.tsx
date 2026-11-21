import { useCallback, useEffect, useState } from "react";
import "./dealers.css";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Modal,
  SectionPageHeader,
  Spinner,
  Tabs,
  useToast,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { HeaderArt } from "../../components/HeaderArt";
import { ApiError } from "../../lib/api";
import { money } from "../inventory/format";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth, useAuth } from "../core";
import { groupLayerWaived } from "../core/accountTypes";
import { useMyModules } from "../core/MyModules";
import {
  SETTINGS_SECTIONS,
  sectionVisibleFor,
} from "../core/settingsMeta";
import {
  SettingsActionsMenu,
  type SettingsActionEntry,
} from "../core/SettingsActionsMenu";
import { getStatusSummary } from "../truck-accounts/api";
import TruckGlance from "../truck-accounts/TruckGlance";
import type { TruckStatusSummary } from "../truck-accounts/types";
import {
  createListEntry,
  getDealerListSettings,
  hideDirectoryCompany,
  listCompanies,
  listPreferred,
  listPrivateAgents,
  unhideDirectoryCompany,
} from "./api";
import { ClaimCodeCard } from "./ClaimCodeCard";
import { AgentsSplitTab } from "./AgentsSplitTab";
import { DealersSplitTab } from "./DealersSplitTab";
import { ListEntryForm } from "./DealerListSettings";
import { summarizePreferred } from "./rosterFormat";
import FindAgentPanel from "./components/FindAgentPanel";
import WarrantyRequestsPanel from "./components/WarrantyRequestsPanel";
import type {
  DealerCompany,
  PreferredAgent,
  PreferredSummary,
  PrivateAgent,
} from "./types";

/**
 * Dealers (module): the platform directory, the user's private
 * companies, their private agent records, and their preferred
 * agents per company. The agent side (profiles, representation,
 * public listing) is the dealer portal: Settings -> Dealer
 * profile, plus a detail page per directory company. Private
 * records can be LINKED to a real account when the agent signs
 * up (My agents, below).
 *
 * Main tab layout (program lane 6, 2026-11-10): the kit header
 * (SectionPageHeader) + Steel tabs in Ryan's order — Dealers ·
 * Agents · Find an agent (owner's tab list, 2026-11-09). The
 * header's facts row carries the page's standing counts plus
 * the truck picture (Total accounts · This week's payments ·
 * Total owed, each value a text link to the Truck Accounts
 * page).
 *
 * SIDE LIST rebuild (owner's picks, 2026-11-13): the Dealers
 * and Agents tabs are both SIDE LISTS — the owner's named
 * pattern (a scrolling list on the left, the clicked item's
 * full information on the right, in place). The Dealers tab's
 * list carries the directory and My companies as labeled
 * groups in ONE list (DealersSplitTab); the Agents tab's list
 * carries every agent across every dealer, grouped by the
 * owner's own current/former rule — starred (preferred) on
 * top, everyone else below the divider (AgentsSplitTab). The
 * Find an agent tab is the existing FindAgentPanel, the same
 * component the /dealers/find-agent route renders.
 *
 * The Actions menu carries the three tab jumps plus the
 * Settings group (Actions → Settings, owner order 2026-11-09):
 * the two Settings sections this page owns — My dealer list
 * (every seat) and Dealer profile (dealer seats only) — gated
 * by the Settings shell's own predicate (sectionVisibleFor),
 * each landing on its section route.
 */

/** The page's three tabs (Ryan's spec, 2026-11-09). */
type DealersTabId = "dealers" | "agents" | "find-agent";

/** Deep links pick the opening tab — #agents / #find-agent,
 *  the way /borrowing's hashes pick theirs. Anything else
 *  opens on Dealers. */
function tabFromHash(hash: string): DealersTabId {
  const raw = hash.replace(/^#/, "");
  if (raw === "agents") return "agents";
  if (raw === "find-agent") return "find-agent";
  return "dealers";
}

/** The Settings sections this page owns (settingsMeta ids). */
const DEALER_SETTING_IDS = ["dealer-list", "dealer-profile"];
/* The directory and My companies are LISTS, only lists: the
 * List | Tiles toggles both sections carried are GONE (owner,
 * 2026-11-05 — "completely remove those options like they
 * never existed"), along with the tile renderings and the
 * per-user view preferences that fed them. A stored "tiles"
 * preference from before simply lands on the list. */

export default function DealersPage() {
  const { user } = useAuth();
  const t = useT();
  const { toast } = useToast();
  const navigate = useNavigate();
  const { hash, search } = useLocation();
  const [tab, setTab] = useState<DealersTabId>(() =>
    new URLSearchParams(window.location.search).has("dealer")
      ? "dealers"
      : tabFromHash(window.location.hash),
  );

  // The mount read covers fresh arrivals. An in-app link can
  // also change the hash while this page stays mounted — no
  // remount happens, so follow later hash changes too, or the
  // deep link lands on whatever tab was already open (the
  // lane 1 lesson, via lane 3).
  useEffect(() => {
    const wanted = tabFromHash(hash);
    if (wanted !== "dealers") setTab(wanted);
  }, [hash]);

  // A dealer deep link (?dealer=<id>, the retired company
  // page's new shape) belongs to the Dealers tab whatever tab
  // is open: follow the search too, or a link clicked while
  // the Agents tab is up never reaches the panel's intake.
  useEffect(() => {
    if (new URLSearchParams(search).has("dealer")) setTab("dealers");
  }, [search]);

  const tabLabel = (id: DealersTabId): string =>
    id === "dealers"
      ? t("dealers.tab.dealers")
      : id === "agents"
        ? t("dealers.tab.agents")
        : t("dealers.tab.findAgent");

  // The Actions menu's Settings group (Actions → Settings,
  // owner order 2026-11-09): the Settings sections this page
  // owns, in the Settings page's own order, gated by the very
  // predicate the Settings shell gates with — so the menu
  // never offers a section the shell would bounce (dealer
  // profile waits for a dealer seat; both wait for the
  // dealers module read, like the nav's gated items).
  const { modules: effectiveModules } = useMyModules();
  const moduleIds: ReadonlySet<string> = new Set(
    (effectiveModules ?? []).map((m) => m.id),
  );
  const bareRung = user ? groupLayerWaived(user) : false;
  const dealerSettingsEntries: SettingsActionEntry[] = SETTINGS_SECTIONS.filter(
    (s) =>
      DEALER_SETTING_IDS.includes(s.id) &&
      sectionVisibleFor(s, user?.account_types ?? [], moduleIds, bareRung),
  ).map((s) => ({
    key: s.id,
    label: t(`settings.section.${s.id}` as never),
    run: () => navigate(`/settings/${s.id}`),
  }));
  // My dealer list customize mode (owner correction, 2026-11-01):
  // Customize edits THIS directory IN PLACE, like Home's Edit
  // view — the rows on screen grow a red × and an Add menu
  // appears at the top; no separate manager list swaps in (the
  // manager lives only at Settings → My dealer list). The
  // directory shown is the USER'S list (owner fix, 2026-11-01):
  // a brand they removed leaves the list, while the full
  // directory still feeds Find an Agent (a search over every
  // brand) and every record and filter surface, so nothing
  // already tagged is stranded.
  const [customizing, setCustomizing] = useState(false);
  const [hiddenIds, setHiddenIds] = useState<ReadonlySet<string>>(new Set());
  const [dirBusyId, setDirBusyId] = useState("");
  const [listError, setListError] = useState("");
  const [entryOpen, setEntryOpen] = useState(false);

  const loadHiddenIds = useCallback(async () => {
    try {
      const data = await getDealerListSettings();
      setHiddenIds(
        new Set(
          data.directory
            .filter((row) => row.hidden)
            .map((row) => row.company.id),
        ),
      );
    } catch {
      /* the manager reports its own load failure; until the
       * overlay reads, the grid shows the full directory */
    }
  }, []);

  useEffect(() => {
    void loadHiddenIds();
  }, [loadHiddenIds]);
  const [companies, setCompanies] = useState<DealerCompany[] | null>(null);
  const [agents, setAgents] = useState<PrivateAgent[]>([]);
  const [preferred, setPreferred] = useState<PreferredAgent[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [cs, as, ps] = await Promise.all([
      listCompanies(),
      listPrivateAgents(),
      listPreferred(),
    ]);
    setCompanies(cs);
    setAgents(as);
    setPreferred(ps);
  }, []);

  useEffect(() => {
    refresh().catch((err) =>
      setError(err instanceof ApiError ? err.message : "Couldn't load the dealers page."),
    );
  }, [refresh]);

  // The header's truck facts ride the truck module's status
  // summary — the same read the retired at-a-glance strip used,
  // now feeding the facts row instead (owner, 2026-11-10).
  // Best-effort, exactly as the strip was: when the read fails
  // or the truck module is out of this seat's reach, the three
  // facts simply never appear — no error, no placeholders.
  const [truckSummary, setTruckSummary] =
    useState<TruckStatusSummary | null>(null);
  useEffect(() => {
    let cancelled = false;
    getStatusSummary()
      .then((data) => {
        if (!cancelled) setTruckSummary(data);
      })
      .catch(() => {
        if (!cancelled) setTruckSummary(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const directory = (companies ?? []).filter((c) => c.is_directory);
  const directoryVisible = directory.filter((c) => !hiddenIds.has(c.id));
  const directoryHidden = directory.filter((c) => hiddenIds.has(c.id));
  const pickerCompanies = (companies ?? []).filter(
    (c) => !(c.is_directory && hiddenIds.has(c.id)),
  );
  const mine = (companies ?? []).filter((c) => !c.is_directory);

  // The viewer's preferred-agent SUMMARY by company (the
  // list's agent line + the panel's agent block) — the display
  // rule (owner, 2026-11-06): exactly one flagged agent is
  // named; MORE than one flagged shows "Multiple Agents" and
  // names nobody; none flagged falls back to the earliest
  // connection, as before. The one shared resolver
  // (summarizePreferred) — the same answer the item pages'
  // agent line and the Warranty tab read from the server.
  // The preferred read arrives in connection order, so each
  // company's rows group in resolution order.
  const agentSummaryByCompany = new Map<string, PreferredSummary>();
  {
    const rowsByCompany = new Map<string, PreferredAgent[]>();
    for (const entry of preferred) {
      const rows = rowsByCompany.get(entry.company_id) ?? [];
      rows.push(entry);
      rowsByCompany.set(entry.company_id, rows);
    }
    for (const [companyId, rows] of rowsByCompany) {
      agentSummaryByCompany.set(companyId, summarizePreferred(rows));
    }
  }

  // The Add menu in customize mode (Home's pattern): what is NOT
  // on the user's list — the removed prefilled dealers first
  // (tap = back on the list), then the new-dealer path, which
  // opens the shared entry form in a Modal over this page.
  const dirAddItems = [
    ...directoryHidden.map((company) => ({
      key: `co:${company.id}`,
      title: company.name,
    })),
    { key: "__new__", title: t("dealerList.addEntry") },
  ];

  async function hideBrand(company: DealerCompany) {
    setListError("");
    setDirBusyId(company.id);
    try {
      await hideDirectoryCompany(company.id);
      await loadHiddenIds();
    } catch (err) {
      setListError(
        err instanceof ApiError ? err.message : "Couldn't update your list.",
      );
    } finally {
      setDirBusyId("");
    }
  }

  async function restoreBrand(companyId: string) {
    setListError("");
    setDirBusyId(companyId);
    try {
      await unhideDirectoryCompany(companyId);
      await loadHiddenIds();
    } catch (err) {
      setListError(
        err instanceof ApiError ? err.message : "Couldn't update your list.",
      );
    } finally {
      setDirBusyId("");
    }
  }

  function handleDirAdd(key: string) {
    if (key === "__new__") {
      setEntryOpen(true);
      return;
    }
    if (key.startsWith("co:")) {
      void restoreBrand(key.slice("co:".length));
    }
  }

  const isDealer = (user?.account_types ?? []).includes("tool_dealer");

  // Header facts (kit anatomy): the page's standing counts —
  // the dealers on the viewer's list, their private companies,
  // their active agent records — plus the truck picture (owner,
  // 2026-11-10): total open truck accounts, this week's
  // payments, and the total owed, each VALUE a text link to
  // the Truck Accounts page (the link replaces the retired
  // at-a-glance area and its door). Absent while the page's
  // read is in flight (kit contract: never placeholder
  // facts); the truck facts join only once their own read has
  // landed, and then show even at zero — stats in a stats row.
  // Total owed is what the viewer owes (the customer side);
  // a viewer with no customer-side open accounts who runs
  // accounts as a dealer reads the total owed across their
  // books instead — the two sides are never summed.
  const facts: SectionPageFact[] | undefined =
    companies === null
      ? undefined
      : [
          {
            label: t("dealers.fact.directory"),
            value: directoryVisible.length,
          },
          { label: t("dealers.fact.myCompanies"), value: mine.length },
          {
            label: t("dealers.fact.myAgents"),
            value: agents.filter((a) => !a.archived).length,
          },
          ...(truckSummary
            ? [
                {
                  label: t("dealers.fact.totalAccounts"),
                  value:
                    truckSummary.customer_open_accounts > 0 ? (
                      <a href="#truck-glance" className="tv-fact-link">
                        {truckSummary.customer_open_accounts +
                          truckSummary.dealer_open_accounts}
                      </a>
                    ) : (
                      truckSummary.customer_open_accounts +
                      truckSummary.dealer_open_accounts
                    ),
                },
                {
                  label: t("dealers.fact.paymentsThisWeek"),
                  value:
                    truckSummary.customer_open_accounts > 0 ? (
                      <a href="#truck-glance" className="tv-fact-link">
                        {money(truckSummary.payments_this_week)}
                      </a>
                    ) : (
                      money(truckSummary.payments_this_week)
                    ),
                },
                {
                  label: t("dealers.fact.totalOwed"),
                  value:
                    truckSummary.customer_open_accounts > 0 ? (
                      <a href="#truck-glance" className="tv-fact-link">
                        {money(
                          truckSummary.customer_open_accounts > 0
                            ? truckSummary.customer_total_balance
                            : truckSummary.dealer_total_outstanding,
                        )}
                      </a>
                    ) : (
                      money(
                        truckSummary.customer_open_accounts > 0
                          ? truckSummary.customer_total_balance
                          : truckSummary.dealer_total_outstanding,
                      )
                    ),
                },
              ]
            : []),
        ];

  const tabs: TabItem[] = [
    {
      id: "dealers",
      label: tabLabel("dealers"),
      content: (
        <>
          <DealersSplitTab
            directory={directory}
            directoryVisible={directoryVisible}
            mine={mine}
            agentSummaries={agentSummaryByCompany}
            customizing={customizing}
            onToggleCustomize={() => setCustomizing((v) => !v)}
            dirAddItems={dirAddItems}
            onDirAdd={handleDirAdd}
            listError={listError}
            dirBusyId={dirBusyId}
            onHideBrand={(company) => void hideBrand(company)}
            onChanged={() => void refresh()}
            userId={user?.id ?? ""}
            onFindAgent={() => setTab("find-agent")}
          />
          <Modal
            open={entryOpen}
            onClose={() => setEntryOpen(false)}
            title={t("dealerList.addEntry")}
            size="lg"
          >
            <ListEntryForm
              onSave={async (body) => {
                await createListEntry(body);
                setEntryOpen(false);
                toast(t("dealerList.entrySaved"), { tone: "success" });
              }}
              onCancel={() => setEntryOpen(false)}
            />
          </Modal>
        </>
      ),
    },
    {
      id: "agents",
      label: tabLabel("agents"),
      content: (
        <div className="tv-dealers-tabstack">
          <AgentsSplitTab
            companies={companies ?? []}
            pickerCompanies={pickerCompanies}
            agents={agents}
            preferred={preferred}
            onChanged={() => void refresh()}
          />
          {/* The agent-code panel is the AGENT side of the
              takeover flow — dealer-group accounts only
              (owner, 2026-11-04). A mechanic never sees it;
              the endpoint refuses him too, so the hidden
              panel is not the only lock. It rides the Agents
              tab: the page's agent-work seat. */}
          {isDealer && <ClaimCodeCard />}
          <WarrantyRequestsPanel dealerGroup={isDealer} />
        </div>
      ),
    },
    {
      id: "find-agent",
      label: tabLabel("find-agent"),
      content: (
        <FindAgentPanel
          directory={directory}
          onPreferredChanged={() => void refresh()}
        />
      ),
    },
  ];

  return (
    <RequireAuth>
      <div className="tv-stack">
        <SectionPageHeader
          thumb={<HeaderArt name="dealers" />}
          title={t("dealers.title")}
          subtitle={t("dealers.subtitle")}
          facts={facts}
          actions={
            <SettingsActionsMenu
              ariaLabel={t("dealers.title")}
              buttonLabel={t("inventory.actions")}
              entries={(["dealers", "agents", "find-agent"] as const).map(
                (id) => ({
                  key: id,
                  label: tabLabel(id),
                  run: () => setTab(id),
                }),
              )}
              settingsEntries={dealerSettingsEntries}
              settingsLabel={t("shell.settings")}
            />
          }
        />

        {error && <Alert tone="danger">{error}</Alert>}

        <TruckGlance />

        {companies === null && !error ? (
          <p className="tv-loading-line">
            <Spinner size="sm" /> Loading…
          </p>
        ) : (
          <Tabs
            tabs={tabs}
            activeId={tab}
            onChange={(id) => setTab(id as DealersTabId)}
          />
        )}
      </div>
    </RequireAuth>
  );
}
