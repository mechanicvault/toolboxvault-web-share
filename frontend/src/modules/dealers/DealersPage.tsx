import { useCallback, useEffect, useState, type FormEvent } from "react";
import "./dealers.css";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  CopyButton,
  EmptyState,
  FormField,
  formGridStyle,
  LinkButton,
  Modal,
  Panel,
  SectionHeader,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  TextArea,
  TextInput,
  useToast,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { AddBlockMenu } from "../../components/AddBlockMenu";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { displayDate, money } from "../inventory/format";
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
import type { TruckStatusSummary } from "../truck-accounts/types";
import {
  addPreferred,
  createListEntry,
  createPrivateAgent,
  deleteCompany,
  deletePrivateAgent,
  getDealerListSettings,
  hideDirectoryCompany,
  linkPrivateAgent,
  listCompanies,
  listPreferred,
  listPrivateAgents,
  removePreferred,
  unhideDirectoryCompany,
  unlinkPrivateAgent,
  updateCompany,
  updatePrivateAgent,
} from "./api";
import { AgentImportButton } from "./AgentCardImport";
import { ClaimCodeCard } from "./ClaimCodeCard";
import { ListEntryForm, RemoveX } from "./DealerListSettings";
import { summarizePreferred } from "./rosterFormat";
import { CompanyForm, companyToWrite } from "./components/CompanyForm";
import { CompanyLogo } from "./components/CompanyLogo";
import { ContactPickButton } from "./components/ContactPickButton";
import FindAgentPanel from "./components/FindAgentPanel";
import WarrantyRequestsPanel from "./components/WarrantyRequestsPanel";
import type {
  DealerCompany,
  PreferredAgent,
  PreferredSummary,
  PrivateAgent,
  PrivateAgentWrite,
} from "./types";

/**
 * Dealers (module): the platform directory, the user's private
 * companies, their private agent records, and their preferred agents
 * per company. The agent side (profiles, representation, public
 * listing) is the dealer portal: Settings -> Dealer profile, plus a
 * detail page per directory company. Private records can be LINKED
 * to a real account when the agent signs up (My agents, below).
 *
 * Main tab layout (program lane 6, 2026-11-10): the kit header
 * (SectionPageHeader) + Steel tabs in Ryan's order — Dealers ·
 * Agents · Find an agent (owner's tab list, 2026-11-09). The
 * "Your truck accounts at a glance" area is GONE (owner,
 * 2026-11-10, superseding the same morning's in-header strip):
 * its numbers live in the header's facts row instead — Total
 * accounts · This week's payments · Total owed, each value a
 * text link to the Truck Accounts page — and the route lines
 * and the strip's door went away with the area. The tab mapping
 * over the old stacked page: Dealers = Directory + My
 * companies (the two dealer
 * lists); Agents = My agents (with Preferred agents) + the
 * dealer seat's agent-code card + Warranty requests (the
 * page's agent-work surfaces); Find an agent = the existing
 * FindAgentPanel, the same component the /dealers/find-agent
 * route renders. Every section body is the old code verbatim —
 * only the page shell changed.
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
  const { hash } = useLocation();
  const [tab, setTab] = useState<DealersTabId>(() =>
    tabFromHash(window.location.hash),
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
  // list view's agent + contact columns) — the display rule
  // (owner, 2026-11-06): exactly one flagged agent is named;
  // MORE than one flagged shows "Multiple Agents" and names
  // nobody; none flagged falls back to the earliest
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
                  value: (
                    <Link to="/truck-accounts" className="tv-fact-link">
                      {truckSummary.customer_open_accounts +
                        truckSummary.dealer_open_accounts}
                    </Link>
                  ),
                },
                {
                  label: t("dealers.fact.paymentsThisWeek"),
                  value: (
                    <Link to="/truck-accounts" className="tv-fact-link">
                      {money(truckSummary.payments_this_week)}
                    </Link>
                  ),
                },
                {
                  label: t("dealers.fact.totalOwed"),
                  value: (
                    <Link to="/truck-accounts" className="tv-fact-link">
                      {money(
                        truckSummary.customer_open_accounts > 0
                          ? truckSummary.customer_total_balance
                          : truckSummary.dealer_total_outstanding,
                      )}
                    </Link>
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
        <div className="tv-dealers-tabstack">
          <section className="tv-dir-section">
            <DirectoryHead
              customizing={customizing}
              onCustomize={() => setCustomizing((v) => !v)}
            />
            {listError && <Alert tone="danger">{listError}</Alert>}
            {customizing && (
              <div className="tv-dir-editbar">
                <AddBlockMenu
                  items={dirAddItems}
                  onAdd={handleDirAdd}
                  menuLabel={t("dealerList.addMenuLabel")}
                />
              </div>
            )}
            {directory.length === 0 ? (
              /* The shared nothing-here-yet kit (Sweep A1,
                 finding 11-F9): the old box stated a fact and
                 stopped. Now it says what belongs here and
                 carries the door — Find an Agent, this page's
                 own tab. */
              <EmptyState
                art="dealers"
                title={t("dealers.directory.emptyTitle")}
                description={t("dealers.directory.empty")}
                action={
                  <Button type="button" onClick={() => setTab("find-agent")}>
                    {t("dealers.tab.findAgent")}
                  </Button>
                }
              />
            ) : directoryVisible.length === 0 ? (
              <EmptyState
                art="dealers"
                title={t("dealers.directory.allHiddenTitle")}
                description={t("dealers.directory.allHidden")}
                action={
                  <Button type="button" onClick={() => setCustomizing(true)}>
                    {t("dealerList.customize")}
                  </Button>
                }
              />
            ) : (
              <DirectoryTable
                companies={directoryVisible}
                agentSummaries={agentSummaryByCompany}
                editing={customizing}
                busyId={dirBusyId}
                onRemove={(company) => void hideBrand(company)}
              />
            )}
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
          </section>

          <MyCompanies mine={mine} onChanged={() => void refresh()} />
        </div>
      ),
    },
    {
      id: "agents",
      label: tabLabel("agents"),
      content: (
        <div className="tv-dealers-tabstack">
          <MyAgents
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
          thumb={<ArtIcon name="dealers" size={96} />}
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

        {companies === null && !error ? (
          <p style={{ color: "var(--text-muted)" }}>
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

/** Directory section head: the stencil title + the Customize
 *  toggle that arms the in-place edit mode on the rows. (The
 *  List | Tiles toggle that rode here is gone — owner,
 *  2026-11-05: the directory is a list, only a list.) */
function DirectoryHead({
  customizing,
  onCustomize,
}: {
  customizing: boolean;
  onCustomize: () => void;
}) {
  const t = useT();
  return (
    <div className="tv-dir-head">
      <SectionHeader title={t("dealers.directory.title")} />
      <div className="tv-dir-toggle">
        <Button
          size="sm"
          variant={customizing ? "primary" : "secondary"}
          aria-pressed={customizing}
          onClick={onCustomize}
        >
          {customizing ? t("dealerList.done") : t("dealerList.customize")}
        </Button>
      </div>
    </div>
  );
}

/** The directory LIST view (owner correction, 2026-11-01) — and
 *  since 2026-11-05 the ONLY view: a true list — one dealer
 *  per ROW, its facts spread in COLUMNS across the row, not
 *  stacked cards.
 *
 *  The row IS the dealer's link (owner, 2026-11-06): the
 *  whole row opens the dealer's page — a real anchor laid
 *  over the row, the Home widget cover pattern — and there is
 *  NO View button. The row's own links ride above the cover
 *  and keep their own targets: the agent's name opens his
 *  record (the #agent= deep link); with MORE THAN ONE
 *  preferred agent, a "Multiple Agents" link goes to the
 *  dealer's Agents tab instead of any one agent's specifics;
 *  the phone dials, the email mails, the website opens the
 *  dealer's site.
 *
 *  The columns after the agent are CONTACT FACTS ONLY —
 *  phone · email · website · next route day — and WHOSE
 *  facts they are follows the preferred-agent summary (owner,
 *  2026-11-06): when ONE agent stands in the agent column,
 *  HIS phone and email take the dealer's place and the route
 *  day is HIS next route day. The PHONE falls back to the
 *  dealer's own when he has none on record (its customer-
 *  service pick); the EMAIL NEVER FALLS BACK — a shown agent
 *  with no email leaves the cell blank (owner correction,
 *  2026-11-06 06:39). With multiple preferred or none,
 *  the facts are the DEALER's own (the viewer's effective
 *  record, personal edits layered, as the company read
 *  serves it) and there is no route day — a dealer has no
 *  route of its own. An absent fact reads "—". Everything
 *  else (address, notes, extra numbers) lives on the
 *  dealer's own page, not in the row.
 *
 *  In customize mode there is NO cover and no row links at
 *  all — the rows never navigate while customizing (Home's
 *  Edit-view rule) — and each row grows a red ×, in place. */
function DirectoryTable({
  companies,
  agentSummaries,
  editing,
  busyId,
  onRemove,
}: {
  companies: DealerCompany[];
  agentSummaries: Map<string, PreferredSummary>;
  editing: boolean;
  busyId: string;
  onRemove: (company: DealerCompany) => void;
}) {
  const t = useT();
  const none = <span className="tv-dir-none">—</span>;
  return (
    <div
      className={`tv-dir-table${editing ? " tv-dir-table--editing" : ""}`}
      role="table"
    >
      <div className="tv-dir-thead" role="row">
        <span role="columnheader">{t("dealers.directory.col.dealer")}</span>
        <span role="columnheader">{t("dealers.directory.col.preferredAgent")}</span>
        <span role="columnheader">{t("dealers.directory.col.phone")}</span>
        <span role="columnheader">{t("dealers.directory.col.email")}</span>
        <span role="columnheader">{t("dealers.directory.col.website")}</span>
        <span role="columnheader">{t("dealers.directory.col.nextRouteDay")}</span>
        {editing && <span aria-hidden="true" />}
      </div>
      {companies.map((company) => {
        const summary = agentSummaries.get(company.id) ?? null;
        /* The summary's agent exists only in the "one" state,
         * so in the "many"/"none" states agent is null and
         * every fact below resolves to the dealer's own —
         * never one of several agents'. */
        const agent = summary?.agent ?? null;
        const agentRef = agent
          ? agent.kind === "private"
            ? agent.private_agent_id
            : agent.agent_user_id
          : null;
        /* WHOSE facts: the one shown agent's phone/email
         * stand in for the dealer's. The phone falls back to
         * the dealer's own when he has none on record (the
         * customer-service pick the company read computes,
         * else its first listed number); the email does NOT
         * fall back — a shown agent with no email leaves the
         * cell blank (owner, 2026-11-06 06:39). The website
         * is always the dealer's — an agent has none — and
         * the route day is the agent's alone: no agent shown,
         * no route day. */
        const agentPhone =
          agent && agent.phone.trim() !== "" ? agent.phone : null;
        const contactPhone =
          agentPhone ??
          company.customer_service_phone ??
          company.phones[0]?.number ??
          null;
        const agentEmail =
          agent && agent.email.trim() !== "" ? agent.email : null;
        /* One agent shown → HIS email or blank, never the
         * dealer's (owner, 2026-11-06 06:39). No agent shown
         * (many / none) → the dealer's own facts, email
         * included. */
        const contactEmail = agent ? agentEmail : company.email || null;
        const website = company.website || null;
        const nextVisit = agent?.next_visit ?? null;
        const dealerHref = `/dealers/${company.id}`;
        return (
          <div className="tv-dir-row" role="row" key={company.id}>
            {!editing && (
              <Link
                className="tv-dir-cover"
                to={dealerHref}
                aria-label={company.name}
              />
            )}
            <div className="tv-dir-cell-name" role="cell">
              <CompanyLogo company={company} />
              <span className="tv-dir-cell-name-text">
                {editing ? (
                  company.name
                ) : (
                  <Link className="tv-dir-name-link" to={dealerHref}>
                    {company.name}
                  </Link>
                )}
              </span>
            </div>
            <div className="tv-dir-cell-pref" role="cell">
              {summary?.state === "many" ? (
                editing ? (
                  t("dealers.directory.multipleAgents")
                ) : (
                  <Link
                    className="tv-dir-name-link"
                    to={`${dealerHref}#agents`}
                  >
                    {t("dealers.directory.multipleAgents")}
                  </Link>
                )
              ) : agent && agentRef ? (
                editing ? (
                  agent.name
                ) : (
                  <Link
                    className="tv-dir-name-link"
                    to={`${dealerHref}#agent=${agent.kind}:${agentRef}`}
                  >
                    {agent.name}
                  </Link>
                )
              ) : null}
            </div>
            <div className="tv-dir-cell-fact tv-dir-cell-phone" role="cell">
              {contactPhone ? (
                editing ? (
                  contactPhone
                ) : (
                  <a
                    className="tv-dir-phone"
                    href={`tel:${contactPhone}`}
                    title={contactPhone}
                  >
                    {contactPhone}
                  </a>
                )
              ) : (
                none
              )}
            </div>
            <div className="tv-dir-cell-fact" role="cell">
              {contactEmail ? (
                editing ? (
                  <span className="tv-dir-fact-text" title={contactEmail}>
                    {contactEmail}
                  </span>
                ) : (
                  <a
                    className="tv-fact-link tv-dir-fact-text"
                    href={`mailto:${contactEmail}`}
                    title={contactEmail}
                  >
                    {contactEmail}
                  </a>
                )
              ) : (
                none
              )}
            </div>
            <div className="tv-dir-cell-fact" role="cell">
              {website ? (
                editing ? (
                  <span className="tv-dir-fact-text" title={website}>
                    {website}
                  </span>
                ) : (
                  <a
                    className="tv-fact-link tv-dir-fact-text"
                    href={
                      website.startsWith("http")
                        ? website
                        : `https://${website}`
                    }
                    title={website}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {website}
                  </a>
                )
              ) : (
                none
              )}
            </div>
            <div className="tv-dir-cell-fact" role="cell">
              {nextVisit ? displayDate(nextVisit) : none}
            </div>
            {editing && (
              <div className="tv-dir-cell-x" role="cell">
                <RemoveX
                  name={company.name}
                  removeLabel={t("home.remove")}
                  busy={busyId === company.id}
                  onRemove={() => onRemove(company)}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function CompanyFacts({
  company,
  notes = true,
}: {
  company: DealerCompany;
  /** The directory-notes prose paragraph. On by default (the
   *  company page shows it); a list row that renders facts
   *  passes false so rows stay short — the notes themselves
   *  live on the dealer's own page. */
  notes?: boolean;
}) {
  const t = useT();
  return (
    <div style={{ display: "grid", gap: "0.45rem", fontSize: "0.92rem" }}>
      {company.phones.map((phone) => (
        <p key={`${phone.label}-${phone.number}`} style={{ margin: 0 }}>
          <span style={{ color: "var(--text-muted)" }}>{phone.label}: </span>
          <a href={`tel:${phone.number}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
            {phone.number}
          </a>{" "}
          <CopyButton
            text={phone.number}
            label={t("dealers.facts.copy")}
            ariaLabel={t("dealers.facts.copyPhone").replace("{label}", phone.label)}
          />
        </p>
      ))}
      {company.email && (
        <p style={{ margin: 0 }}>
          <span style={{ color: "var(--text-muted)" }}>{t("dealers.facts.email")}: </span>
          <a href={`mailto:${company.email}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
            {company.email}
          </a>
        </p>
      )}
      {company.website && (
        <p style={{ margin: 0 }}>
          <span style={{ color: "var(--text-muted)" }}>{t("dealers.facts.web")}: </span>
          <a
            href={company.website.startsWith("http") ? company.website : `https://${company.website}`}
            target="_blank"
            rel="noreferrer"
            style={{ color: "var(--accent)", fontWeight: 600 }}
          >
            {company.website}
          </a>
        </p>
      )}
      {company.address && (
        <p style={{ margin: 0, whiteSpace: "pre-line" }}>
          {company.address}{" "}
          <CopyButton
            text={company.address}
            label={t("dealers.facts.copyAddress")}
            ariaLabel={t("dealers.facts.copyAddressAria")}
          />
        </p>
      )}
      {notes && company.notes && (
        <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.85rem" }}>
          {company.notes}
        </p>
      )}
    </div>
  );
}

/* My companies is a true list (MyCompaniesTable) — its own
 * List | Tiles toggle and panel rendering went the way of the
 * directory's (owner, 2026-11-05: no tile options for the
 * dealer lists, lists only). */
function MyCompanies({
  mine,
  onChanged,
}: {
  mine: DealerCompany[];
  onChanged: () => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState<DealerCompany | null>(null);
  const [error, setError] = useState("");
  const empty = !editing && mine.length === 0;

  async function remove(company: DealerCompany) {
    if (!window.confirm(t("dealers.myCompanies.deleteConfirm").replace("{name}", company.name))) return;
    setError("");
    try {
      await deleteCompany(company.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myCompanies.deleteError"));
    }
  }

  return (
    <section className="tv-dir-section">
      <div className="tv-dir-head">
        <SectionHeader title={t("dealers.myCompanies.title")} />
      </div>
      {/* When the list is empty the shared empty state below
          carries this same Add door and explanation (Sweep A1,
          finding 11-F9) — showing both would put the same door
          and the same words twice in one section. Populated
          sections keep both exactly as before. */}
      {!editing && !empty && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          {/* Wizard Phase 2: adding a dealer opens the Add
              Dealer wizard (basics → agent step → review). This
              button is an entry point; editing below stays on
              the full form. */}
          <LinkButton size="sm" to="/dealers/new">
            {t("dealers.myCompanies.add")}
          </LinkButton>
        </div>
      )}
      {!empty && (
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          {t("dealers.myCompanies.intro")}
        </p>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {editing && (
        <Panel title={t("dealers.myCompanies.editTitle").replace("{name}", editing.name)}>
          <CompanyForm
            initial={companyToWrite(editing)}
            submitLabel={t("dealers.myCompanies.saveChanges")}
            onSubmit={async (body) => {
              await updateCompany(editing.id, body);
              setEditing(null);
              onChanged();
            }}
            onCancel={() => setEditing(null)}
          />
        </Panel>
      )}
      {!editing &&
        (mine.length === 0 ? (
          <EmptyState
            art="dealers"
            title={t("dealers.myCompanies.emptyTitle")}
            description={t("dealers.myCompanies.empty")}
            action={
              <LinkButton to="/dealers/new">{t("dealers.myCompanies.add")}</LinkButton>
            }
          />
        ) : (
          <MyCompaniesTable
            companies={mine}
            onEdit={(company) => setEditing(company)}
            onRemove={(company) => void remove(company)}
          />
        ))}
    </section>
  );
}

/** The My companies LIST (owner list standard, 2026-11-02) —
 *  since 2026-11-05 the section's only rendering: a true list
 *  in the DirectoryTable pattern — one company per ROW, a
 *  header row, each fact the company carries in its OWN column
 *  (company · phone · email · website · address), and
 *  Edit/Delete riding the row's trailing actions cell next to
 *  the company-page link. The notes prose is the one company
 *  fact NOT in a row cell: like the directory's Contact trim,
 *  long prose lives on the company's own page (Company details
 *  in its Details tab) so rows stay short. */
function MyCompaniesTable({
  companies,
  onEdit,
  onRemove,
}: {
  companies: DealerCompany[];
  onEdit: (company: DealerCompany) => void;
  onRemove: (company: DealerCompany) => void;
}) {
  const t = useT();
  return (
    <div className="tv-myco-table" role="table">
      <div className="tv-myco-thead" role="row">
        <span role="columnheader">{t("dealers.myCompanies.col.company")}</span>
        <span role="columnheader">{t("dealers.myCompanies.col.phone")}</span>
        <span role="columnheader">{t("dealers.myCompanies.col.email")}</span>
        <span role="columnheader">{t("dealers.myCompanies.col.website")}</span>
        <span role="columnheader">{t("dealers.myCompanies.col.address")}</span>
        <span role="columnheader">{t("dealers.myCompanies.col.actions")}</span>
      </div>
      {companies.map((company) => (
        <div className="tv-myco-row" role="row" key={company.id}>
          <div className="tv-myco-cell-name" role="cell">
            <CompanyLogo company={company} />
            <span className="tv-myco-cell-name-text">
              <Link className="tv-dir-name-link" to={`/dealers/${company.id}`}>
                {company.name}
              </Link>
              {company.kind === "retailer" && (
                <Badge tone="accent">{t("dealers.myCompanies.retailer")}</Badge>
              )}
            </span>
          </div>
          <div className="tv-myco-phones" role="cell">
            {company.phones.length > 0 ? (
              company.phones.map((phone) => (
                <p
                  key={`${phone.label}-${phone.number}`}
                  className="tv-myco-fact"
                >
                  <span className="tv-fact-label">{phone.label}: </span>
                  <a className="tv-fact-link" href={`tel:${phone.number}`}>
                    {phone.number}
                  </a>{" "}
                  <CopyButton
                    text={phone.number}
                    label={t("dealers.facts.copy")}
                    ariaLabel={t("dealers.facts.copyPhone").replace("{label}", phone.label)}
                  />
                </p>
              ))
            ) : (
              <span className="tv-dir-none">—</span>
            )}
          </div>
          <div role="cell">
            {company.email ? (
              <a className="tv-fact-link" href={`mailto:${company.email}`}>
                {company.email}
              </a>
            ) : (
              <span className="tv-dir-none">—</span>
            )}
          </div>
          <div role="cell">
            {company.website ? (
              <a
                className="tv-fact-link"
                href={
                  company.website.startsWith("http")
                    ? company.website
                    : `https://${company.website}`
                }
                target="_blank"
                rel="noreferrer"
              >
                {company.website}
              </a>
            ) : (
              <span className="tv-dir-none">—</span>
            )}
          </div>
          <div role="cell">
            {company.address ? (
              <span className="tv-myco-address">
                {company.address}{" "}
                <CopyButton
                  text={company.address}
                  label={t("dealers.facts.copyAddress")}
                  ariaLabel={t("dealers.facts.copyAddressAria")}
                />
              </span>
            ) : (
              <span className="tv-dir-none">—</span>
            )}
          </div>
          <div className="tv-myco-actions" role="cell">
            <LinkButton size="sm" to={`/dealers/${company.id}`}>
              {t("dealers.myCompanies.view")}
            </LinkButton>
            <Button size="sm" variant="secondary" onClick={() => onEdit(company)}>
              {t("dealers.myCompanies.edit")}
            </Button>
            <Button size="sm" variant="danger" onClick={() => onRemove(company)}>
              {t("common.delete")}
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

const EMPTY_AGENT: PrivateAgentWrite = {
  company_id: null,
  name: "",
  phone: "",
  email: "",
  notes: "",
};

function MyAgents({
  companies,
  pickerCompanies,
  agents,
  preferred,
  onChanged,
}: {
  companies: DealerCompany[];
  /** The company pickers' options: every company except the
   *  directory brands this user removed from their list (owner
   *  fix, 2026-11-01 — a removed brand leaves every chooser, not
   *  just the item picker). */
  pickerCompanies: DealerCompany[];
  agents: PrivateAgent[];
  preferred: PreferredAgent[];
  onChanged: () => void;
}) {
  const [agentForm, setAgentForm] = useState<PrivateAgentWrite | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [prefCompany, setPrefCompany] = useState("");
  const [prefAgent, setPrefAgent] = useState("");
  const [prefAccount, setPrefAccount] = useState("");
  const [prefBusy, setPrefBusy] = useState(false);
  const [linkingId, setLinkingId] = useState<string | null>(null);
  const [linkNumber, setLinkNumber] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const t = useT();
  const { toast } = useToast();

  const activeAgents = agents.filter((a) => !a.archived);
  const linkedAgents = agents.filter((a) => a.archived);

  /** Picker options for a company select: the user's list, plus
   *  the current value when it sits outside the list — an agent
   *  already recorded for a since-removed brand must still show
   *  its company (records are never stranded by a list edit). */
  const optionsFor = (currentId: string | null): DealerCompany[] => {
    if (currentId && !pickerCompanies.some((c) => c.id === currentId)) {
      const current = companies.find((c) => c.id === currentId);
      if (current) return [...pickerCompanies, current];
    }
    return pickerCompanies;
  };

  async function doLink(agent: PrivateAgent) {
    setError("");
    if (!linkNumber.trim()) {
      setError(t("dealers.myAgents.linkNumberRequired"));
      return;
    }
    setLinkBusy(true);
    try {
      await linkPrivateAgent(agent.id, linkNumber.trim());
      setLinkingId(null);
      setLinkNumber("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.linkError"));
    } finally {
      setLinkBusy(false);
    }
  }

  async function doUnlink(agent: PrivateAgent) {
    setError("");
    try {
      await unlinkPrivateAgent(agent.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.unlinkError"));
    }
  }

  async function saveAgent(e: FormEvent) {
    e.preventDefault();
    if (!agentForm) return;
    setError("");
    if (!agentForm.name.trim()) {
      setError(t("dealers.myAgents.nameRequired"));
      return;
    }
    try {
      if (editingId) await updatePrivateAgent(editingId, agentForm);
      else await createPrivateAgent(agentForm);
      setAgentForm(null);
      setEditingId(null);
      onChanged();
      if (!editingId) {
        toast(t("dealers.myAgents.savedNext"), { tone: "success" });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.saveError"));
    }
  }

  async function removeAgent(agent: PrivateAgent) {
    if (!window.confirm(t("dealers.myAgents.deleteConfirm").replace("{name}", agent.name))) return;
    try {
      await deletePrivateAgent(agent.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.deleteError"));
    }
  }

  async function addPref() {
    setError("");
    if (!prefCompany) {
      setError(t("dealers.myAgents.prefCompanyRequired"));
      return;
    }
    if (!prefAgent && !prefAccount.trim()) {
      setError(t("dealers.myAgents.prefPickRequired"));
      return;
    }
    setPrefBusy(true);
    try {
      await addPreferred({
        company_id: prefCompany,
        ...(prefAgent
          ? { private_agent_id: prefAgent }
          : { agent_account_number: prefAccount.trim() }),
      });
      setPrefAgent("");
      setPrefAccount("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.prefAddError"));
    } finally {
      setPrefBusy(false);
    }
  }

  /** Contact pick on the preferred form: the picked person becomes
   *  a private agent record AND one of the viewer's agents for the
   *  chosen company in one motion — flagged preferred when the
   *  company has none yet (the record stays editable above). */
  async function preferFromContact(contact: {
    name?: string;
    phone?: string;
    email?: string;
  }) {
    setError("");
    if (!prefCompany) {
      setError(t("dealers.myAgents.prefCompanyFirstContact"));
      return;
    }
    if (!contact.name && !contact.phone && !contact.email) return;
    setPrefBusy(true);
    try {
      const created = await createPrivateAgent({
        company_id: prefCompany,
        name: contact.name ?? contact.phone ?? contact.email ?? t("dealers.myAgents.fallbackName"),
        phone: contact.phone ?? "",
        email: contact.email ?? "",
        notes: "",
      });
      await addPreferred({ company_id: prefCompany, private_agent_id: created.id });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.prefContactError"));
    } finally {
      setPrefBusy(false);
    }
  }

  async function removePref(entry: PreferredAgent) {
    try {
      await removePreferred(entry.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dealers.myAgents.prefRemoveError"));
    }
  }

  return (
    <section>
      <SectionHeader title={t("dealers.myAgents.title")} />
      {!agentForm && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          <Button
            size="sm"
            onClick={() => {
              setEditingId(null);
              setAgentForm(EMPTY_AGENT);
            }}
          >
            {t("dealers.myAgents.add")}
          </Button>{" "}
          <AgentImportButton onImported={onChanged} />
        </div>
      )}
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        {t("dealers.myAgents.intro")}
      </p>
      {error && <Alert tone="danger">{error}</Alert>}

      {agentForm && (
        <Panel title={editingId ? t("dealers.myAgents.edit") : t("dealers.myAgents.new")}>
          <form onSubmit={(e) => void saveAgent(e)} style={{ display: "grid", gap: "var(--space-3)" }}>
            <div style={formGridStyle}>
              <FormField label={t("dealers.myAgents.nameLabel")} required>
                <TextInput
                  value={agentForm.name}
                  onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.company")}>
                <Select
                  value={agentForm.company_id ?? ""}
                  onChange={(e) =>
                    setAgentForm({ ...agentForm, company_id: e.target.value || null })
                  }
                >
                  <option value="">{t("dealers.myAgents.noCompany")}</option>
                  {optionsFor(agentForm.company_id).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label={t("dealers.myAgents.phoneLabel")}>
                <TextInput
                  value={agentForm.phone}
                  onChange={(e) => setAgentForm({ ...agentForm, phone: e.target.value })}
                />
              </FormField>
              <FormField label={t("dealers.myAgents.emailLabel")}>
                <TextInput
                  type="email"
                  value={agentForm.email}
                  onChange={(e) => setAgentForm({ ...agentForm, email: e.target.value })}
                />
              </FormField>
            </div>
            <FormField label={t("dealers.myAgents.notesLabel")}>
              <TextArea
                value={agentForm.notes}
                onChange={(e) => setAgentForm({ ...agentForm, notes: e.target.value })}
                rows={2}
              />
            </FormField>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <Button type="submit">{editingId ? t("dealers.myAgents.saveChanges") : t("dealers.myAgents.addSubmit")}</Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setAgentForm(null);
                  setEditingId(null);
                }}
              >
                {t("common.cancel")}
              </Button>
              <ContactPickButton
                onPick={(contact) =>
                  setAgentForm((current) =>
                    current
                      ? {
                          ...current,
                          name: contact.name ?? current.name,
                          phone: contact.phone ?? current.phone,
                          email: contact.email ?? current.email,
                        }
                      : current,
                  )
                }
              />
            </div>
          </form>
        </Panel>
      )}

      {!agentForm &&
        (activeAgents.length === 0 ? (
          <EmptyState title={t("dealers.myAgents.empty")} />
        ) : (
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {activeAgents.map((agent) => (
              <Panel key={agent.id} className="tv-dealer-agent">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <p style={{ margin: 0 }}>
                    <strong>{agent.name}</strong>{" "}
                    {agent.company_name && (
                      <Badge tone="neutral">{agent.company_name}</Badge>
                    )}{" "}
                    <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                      {[agent.phone, agent.email].filter(Boolean).join(" · ")}
                    </span>
                  </p>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setEditingId(agent.id);
                        setAgentForm({
                          company_id: agent.company_id,
                          name: agent.name,
                          phone: agent.phone,
                          email: agent.email,
                          notes: agent.notes,
                        });
                      }}
                    >
                      {t("dealers.myAgents.editButton")}
                    </Button>
                    {agent.link_source !== "takeover" && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setLinkingId(linkingId === agent.id ? null : agent.id);
                          setLinkNumber("");
                        }}
                      >
                        {t("dealers.myAgents.linkAccount")}
                      </Button>
                    )}
                    <Button size="sm" variant="danger" onClick={() => void removeAgent(agent)}>
                      {t("common.delete")}
                    </Button>
                  </div>
                </div>
                {agent.link_source === "takeover" ? (
                  <p className="tv-agent-meta">
                    {t("dealers.myAgents.claimedBy")
                      .replace("{name}", agent.claimed_by_name ?? "")
                      .replace("{number}", agent.claimed_by_account_number ?? "")}
                  </p>
                ) : (
                  <p className="tv-agent-meta">
                    {t("dealers.myAgents.codeLabel")}:{" "}
                    <span className="tv-agent-code-sm">{agent.agent_code_display}</span>
                  </p>
                )}
                {linkingId === agent.id && (
                  <div style={{ marginTop: "0.7rem", display: "grid", gap: "0.5rem" }}>
                    <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "0.9rem" }}>
                      {t("dealers.myAgents.linkIntro").replace("{name}", agent.name)}
                    </p>
                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "end", flexWrap: "wrap" }}>
                      <FormField label={t("dealers.myAgents.theirAccountNumber")}>
                        <TextInput
                          value={linkNumber}
                          onChange={(e) => setLinkNumber(e.target.value)}
                          placeholder="TV-D-000123"
                        />
                      </FormField>
                      <Button onClick={() => void doLink(agent)} loading={linkBusy}>
                        {t("dealers.myAgents.linkSubmit")}
                      </Button>
                    </div>
                  </div>
                )}
              </Panel>
            ))}
          </div>
        ))}

      {linkedAgents.length > 0 && (
        <div style={{ marginTop: "var(--space-4)" }}>
          <p style={{ fontWeight: 600, margin: "0 0 var(--space-2)" }}>
            {t("dealers.myAgents.linkedTitle")}
          </p>
          <div style={{ display: "grid", gap: "0.5rem" }}>
            {linkedAgents.map((agent) => (
              <Panel key={agent.id} className="tv-dealer-agent">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <p style={{ margin: 0 }}>
                    <strong>{agent.name}</strong>{" "}
                    <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                      {t("dealers.myAgents.linkedLine").replace(
                        "{number}",
                        agent.linked_account_number ?? t("dealers.myAgents.linkedFallback"),
                      )}
                    </span>
                  </p>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <Button size="sm" variant="secondary" onClick={() => void doUnlink(agent)}>
                      {t("dealers.myAgents.unlink")}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => void removeAgent(agent)}>
                      {t("common.delete")}
                    </Button>
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        </div>
      )}

      <Panel title={t("dealers.myAgents.preferredTitle")} >
        <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
          {t("dealers.myAgents.preferredIntro")}
        </p>
        {preferred.length > 0 && (
          <div style={{ display: "grid", gap: "0.4rem", marginBottom: "0.8rem" }}>
            {preferred.map((entry) => (
              <div
                key={entry.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: "1rem",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <p style={{ margin: 0 }}>
                  <strong>{entry.name}</strong>{" "}
                  <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                    {t("dealers.myAgents.prefFor").replace("{company}", entry.company_name ?? "—")} ·{" "}
                    {entry.kind === "platform"
                      ? t("dealers.myAgents.prefPlatform").replace("{number}", entry.account_number ?? "")
                      : t("dealers.myAgents.prefPrivate")}
                  </span>
                </p>
                <Button size="sm" variant="secondary" onClick={() => void removePref(entry)}>
                  {t("dealers.myAgents.remove")}
                </Button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "grid", gap: "0.6rem" }}>
          <div style={formGridStyle}>
            <FormField label={t("dealers.myAgents.company")}>
              <Select value={prefCompany} onChange={(e) => setPrefCompany(e.target.value)}>
                <option value="">{t("dealers.myAgents.pickCompany")}</option>
                {optionsFor(prefCompany || null).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label={t("dealers.myAgents.oneOfMine")}>
              <Select value={prefAgent} onChange={(e) => setPrefAgent(e.target.value)}>
                <option value="">{t("dealers.myAgents.orAccountNumber")}</option>
                {activeAgents
                  .filter((a) => !prefCompany || a.company_id === prefCompany)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
              </Select>
            </FormField>
            <FormField label={t("dealers.myAgents.dealerAccountNumber")}>
              <TextInput
                value={prefAccount}
                onChange={(e) => setPrefAccount(e.target.value)}
                placeholder="TV-D-000123"
              />
            </FormField>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <Button onClick={() => void addPref()} loading={prefBusy}>
              {t("dealers.myAgents.addPreferred")}
            </Button>
            <ContactPickButton
              onPick={(contact) => void preferFromContact(contact)}
            />
          </div>
        </div>
      </Panel>
    </section>
  );
}
