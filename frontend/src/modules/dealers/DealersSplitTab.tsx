import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  EmptyState,
  HrefButton,
  LinkButton,
  Modal,
  Panel,
  SectionHeader,
  SideList,
  SideListGroup,
  SideListRow,
  Spinner,
  VisitorPreviewBanner,
  useToast,
} from "../../components";
import { AddBlockMenu } from "../../components/AddBlockMenu";
import { ApiError } from "../../lib/api";
import { phoneHref } from "../../lib/format";
import { displayDate, money } from "../inventory/format";
import { useT } from "../../i18n/LocaleContext";
import { listAccounts } from "../truck-accounts/api";
import type { TruckAccount } from "../truck-accounts/types";
import {
  clearPersonalCompanyEdit,
  deleteCompany,
  getCompanyDetail,
  getCompanyDetailAsVisitor,
  getCompanyMyRecords,
  getCompanyMyRecordsAsVisitor,
  getRoster,
  listMyRepresentations,
  savePersonalCompanyEdit,
  updateCompany,
} from "./api";
import { useMyModules } from "../core/MyModules";
import { getIssuableCompanies } from "../truck-accounts/api";
import { DealerActionsMenu } from "./components/DealerActionsMenu";
import { CompanyForm, companyToWrite } from "./components/CompanyForm";
import {
  CompanySections,
  type CompanySectionSignal,
} from "./components/CompanySections";
import { CompanyFacts } from "./components/CompanyFacts";
import { CompanyLogo } from "./components/CompanyLogo";
import { RemoveX } from "./DealerListSettings";
import type {
  CompanyDetail,
  CompanyMyRecords,
  DealerCompany,
  DealerCompanyPersonalWrite,
  PreferredSummary,
  RosterEntry,
} from "./types";

/**
 * The Dealers tab as a SIDE LIST (owner's pattern name,
 * 2026-11-13; design D3): one list on the left carrying BOTH
 * populations the tab has always held — the directory and My
 * companies — unbundled into labeled groups inside the one
 * list instead of two stacked tables; the picked dealer's
 * whole picture on the right (his agent up front with worded
 * Call/Email buttons, the company's contact facts, and the
 * viewer's numbers with this dealer), with no page hop.
 *
 * Everything the stacked page did still works from here:
 * Customize edits the directory IN PLACE (the rows grow red
 * ×s, the Add menu rides above the list, rows never select
 * while customizing); a private company is edited and deleted
 * from its own panel; adding a company still opens the Add
 * Dealer wizard; and the panel IS the full dealer page — its
 * sections open under a sub-tab list in the panel, in place
 * (owner, 2026-11-13 late: no more page to go to).
 */
export function DealersSplitTab({
  directory,
  directoryVisible,
  mine,
  agentSummaries,
  customizing,
  onToggleCustomize,
  dirAddItems,
  onDirAdd,
  listError,
  dirBusyId,
  onHideBrand,
  onChanged,
  userId,
  onFindAgent,
}: {
  /** Every directory company (hidden included) — the empty
   *  state decision reads the whole directory, not the list. */
  directory: DealerCompany[];
  directoryVisible: DealerCompany[];
  mine: DealerCompany[];
  agentSummaries: Map<string, PreferredSummary>;
  customizing: boolean;
  onToggleCustomize: () => void;
  dirAddItems: { key: string; title: string }[];
  onDirAdd: (key: string) => void;
  listError: string;
  dirBusyId: string;
  onHideBrand: (company: DealerCompany) => void;
  onChanged: () => void;
  userId: string;
  onFindAgent: () => void;
}) {
  const t = useT();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // The one-shot signal into the panel's sections: open a
  // section (on one agent's record when a key rides along).
  // `n` makes every ask a fresh signal.
  const [sectionSignal, setSectionSignal] =
    useState<CompanySectionSignal | null>(null);

  // Deep-link intake (the retired dealer page's links, in
  // their new shape): /dealers?dealer=<id> selects the
  // dealer; &section=<tab> / &agent=<kind>:<ref> open that
  // section of his panel. Consumed once, then cleared from
  // the address so a later tab switch never re-fires them.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkDealer = searchParams.get("dealer");
  const linkSection = searchParams.get("section");
  const linkAgent = searchParams.get("agent");
  const linkAccount = searchParams.get("account");
  const linkOpenSelf = searchParams.get("openself");
  useEffect(() => {
    if (!linkDealer) return;
    setSelectedId(linkDealer);
    if (linkSection || linkAgent || linkAccount || linkOpenSelf) {
      setSectionSignal((s) => ({
        section: linkAgent ? "agents" : linkSection,
        agentKey: linkAgent,
        accountId: linkAccount,
        openSelfAgent: linkOpenSelf,
        n: (s?.n ?? 0) + 1,
      }));
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("dealer");
        next.delete("section");
        next.delete("agent");
        next.delete("account");
        next.delete("openself");
        return next;
      },
      { replace: true },
    );
  }, [linkDealer, linkSection, linkAgent, linkAccount, linkOpenSelf, setSearchParams]);

  const ordered = useMemo(
    () => [...directoryVisible, ...mine],
    [directoryVisible, mine],
  );
  // The DEFAULT selection (2026-11-13, gate-14 follow-up): the
  // first dealer who has a STARRED (preferred) agent — the
  // fullest panel — ahead of the first dealer with any agent,
  // ahead of the plain first row. Before this, the panel opened
  // on the first directory row in directory order, in practice
  // a no-agent retailer: the emptiest panel as the first
  // impression. List ORDER never changes; only which row
  // starts selected. A summary carries a starred agent when
  // it resolved to "many" (two or more flagged) or to a
  // flagged "one"; an unflagged "one" is the earliest-
  // connection fallback — an agent, but nobody starred.
  const defaultSelected = useMemo(() => {
    const hasStarredAgent = (c: DealerCompany) => {
      const s = agentSummaries.get(c.id);
      return (
        !!s && (s.state === "many" || (s.agent?.is_preferred ?? false))
      );
    };
    const hasAnyAgent = (c: DealerCompany) => {
      const s = agentSummaries.get(c.id);
      return !!s && s.state !== "none";
    };
    return (
      ordered.find(hasStarredAgent) ??
      ordered.find(hasAnyAgent) ??
      ordered[0] ??
      null
    );
  }, [ordered, agentSummaries]);
  const selected =
    ordered.find((c) => c.id === selectedId) ?? defaultSelected;

  // Panel reads, cached per company and dropped whenever the
  // page's own data reloads: my-records (tools tagged + open
  // claims) and the roster (the shown agent's route area). The
  // page rebuilds its arrays on every render, so the caches key
  // on a content signature, not array identity.
  const dataSignature = useMemo(
    () =>
      JSON.stringify([
        directory.map((c) => c.id),
        mine.map((c) => c.id),
        [...agentSummaries.entries()].map(([k, v]) => [
          k,
          v.state,
          v.agent?.id ?? null,
          v.agent?.is_preferred ?? null,
        ]),
      ]),
    [directory, mine, agentSummaries],
  );
  const recordsCache = useRef(new Map<string, CompanyMyRecords>());
  const rosterCache = useRef(new Map<string, RosterEntry[]>());
  const [, setCacheTick] = useState(0);
  useEffect(() => {
    recordsCache.current.clear();
    rosterCache.current.clear();
    setCacheTick((v) => v + 1);
  }, [dataSignature]);

  // The truck picture per company: the viewer's own customer
  // accounts at each dealer, summed — the same numbers the
  // header facts total up. Best-effort, exactly like the
  // header's truck read: when the read fails or the module is
  // out of reach, the stat simply never appears.
  const [truckByCompany, setTruckByCompany] = useState<Map<
    string,
    number
  > | null>(null);
  // The raw accounts ride along: the panel's Truck section
  // renders the selected dealer's own accounts from the same
  // read (one fetch, both uses), and a quick pay reloads it.
  const [allAccounts, setAllAccounts] = useState<TruckAccount[] | null>(null);
  const loadTruck = useCallback(async () => {
    try {
      const accounts = await listAccounts();
      setAllAccounts(accounts);
      const sums = new Map<string, number>();
      for (const account of accounts) {
        if (account.customer_user_id !== userId) continue;
        if (!account.dealer_company_id) continue;
        if (account.status === "closed") continue;
        sums.set(
          account.dealer_company_id,
          (sums.get(account.dealer_company_id) ?? 0) +
            (Number(account.balance) || 0),
        );
      }
      setTruckByCompany(sums);
    } catch {
      setAllAccounts(null);
      setTruckByCompany(null);
    }
  }, [userId]);
  useEffect(() => {
    void loadTruck();
  }, [loadTruck, dataSignature]);

  // Load the selected dealer's panel reads on selection.
  const selectedIdRef = selected?.id ?? null;
  useEffect(() => {
    if (!selectedIdRef) return;
    let cancelled = false;
    if (!recordsCache.current.has(selectedIdRef)) {
      getCompanyMyRecords(selectedIdRef)
        .then((data) => {
          recordsCache.current.set(selectedIdRef, data);
          if (!cancelled) setCacheTick((v) => v + 1);
        })
        .catch(() => {
          /* the stats strip just stays off for this dealer */
        });
    }
    if (!rosterCache.current.has(selectedIdRef)) {
      getRoster(selectedIdRef)
        .then((data) => {
          rosterCache.current.set(selectedIdRef, data);
          if (!cancelled) setCacheTick((v) => v + 1);
        })
        .catch(() => {
          /* the agent block just loses its area line */
        });
    }
    return () => {
      cancelled = true;
    };
  }, [selectedIdRef]);

  // (No signal reset on selection change: the deep-link
  // intake sets the selection AND the signal in one batch,
  // and a reset keyed on the selection wiped the signal it
  // had just set. Manual picks clear the signal at the pick
  // itself, below.)

  if (directory.length === 0 && mine.length === 0) {
    // The first-run shape the stacked page had: the shared
    // nothing-here-yet states, doors included.
    return (
      <div className="tv-dealers-tabstack">
        <section className="tv-dir-section">
          <div className="tv-dir-head">
            <SectionHeader title={t("dealers.directory.title")} />
          </div>
          <EmptyState
            art="dealers"
            title={t("dealers.directory.emptyTitle")}
            description={t("dealers.directory.empty")}
            action={
              <Button type="button" onClick={onFindAgent}>
                {t("dealers.tab.findAgent")}
              </Button>
            }
          />
        </section>
        <section className="tv-dir-section">
          <div className="tv-dir-head">
            <SectionHeader title={t("dealers.myCompanies.title")} />
          </div>
          <EmptyState
            art="dealers"
            title={t("dealers.myCompanies.emptyTitle")}
            description={t("dealers.myCompanies.empty")}
            action={
              <LinkButton to="/dealers/new">
                {t("dealers.myCompanies.add")}
              </LinkButton>
            }
          />
        </section>
      </div>
    );
  }

  const summary = selected
    ? (agentSummaries.get(selected.id) ?? null)
    : null;
  const records = selected
    ? (recordsCache.current.get(selected.id) ?? null)
    : null;
  const roster = selected
    ? (rosterCache.current.get(selected.id) ?? null)
    : null;

  return (
    <div className="tv-dealers-tabstack">
      <div className="tv-dir-head">
        <SectionHeader title={t("dealers.side.pickDealer")} />
        <div className="tv-dir-toggle">
          <Button
            size="sm"
            variant={customizing ? "primary" : "secondary"}
            aria-pressed={customizing}
            onClick={onToggleCustomize}
          >
            {customizing ? t("dealerList.done") : t("dealerList.customize")}
          </Button>
        </div>
      </div>
      <p className="tv-side-note">{t("dealers.side.pickDealerNote")}</p>
      {listError && <Alert tone="danger">{listError}</Alert>}
      {customizing && (
        <div className="tv-dir-editbar">
          <AddBlockMenu
            items={dirAddItems}
            onAdd={onDirAdd}
            menuLabel={t("dealerList.addMenuLabel")}
          />
        </div>
      )}
      <SideList
        listLabel={t("dealers.side.listLabel")}
        list={
          <>
            <SideListGroup label={t("dealers.directory.title")}>
              {directoryVisible.length === 0 ? (
                <p className="tv-sidelist-empty">
                  {t("dealers.directory.allHidden")}
                </p>
              ) : (
                directoryVisible.map((company) => {
                  const rowSummary =
                    agentSummaries.get(company.id) ?? null;
                  const agent = rowSummary?.agent ?? null;
                  return (
                    <SideListRow
                      key={company.id}
                      selected={selected?.id === company.id && !customizing}
                      onSelect={() => {
                        // Sheet row 52 (owner, 2026-11-15):
                        // picking a dealer opens its Details
                        // section automatically — the ask
                        // rides the same one-shot signal the
                        // deep links use.
                        if (!customizing) { setSelectedId(company.id); setSectionSignal((s) => ({ section: "details", agentKey: null, n: (s?.n ?? 0) + 1 })); }
                      }}
                      leading={
                        <CompanyLogo company={company} width={64} height={40} />
                      }
                      title={company.name}
                      sub={
                        rowSummary?.state === "many"
                          ? t("dealers.directory.multipleAgents")
                          : agent
                            ? agent.name
                            : t("dealers.side.noAgent")
                      }
                      trailing={
                        customizing ? (
                          <RemoveX
                            name={company.name}
                            removeLabel={t("home.remove")}
                            busy={dirBusyId === company.id}
                            onRemove={() => onHideBrand(company)}
                          />
                        ) : agent?.next_visit ? (
                          displayDate(agent.next_visit)
                        ) : agent ? (
                          t("dealers.side.noRouteDay")
                        ) : undefined
                      }
                    />
                  );
                })
              )}
            </SideListGroup>
            <SideListGroup label={t("dealers.myCompanies.title")}>
              <p className="tv-sidelist-groupnote">
                {t("dealers.myCompanies.intro")}
              </p>
              {mine.map((company) => (
                <SideListRow
                  key={company.id}
                  selected={selected?.id === company.id}
                  onSelect={() => { setSelectedId(company.id); setSectionSignal((s) => ({ section: "details", agentKey: null, n: (s?.n ?? 0) + 1 })); }}
                  leading={
                    <CompanyLogo company={company} width={64} height={40} />
                  }
                  title={company.name}
                  sub={t("dealers.side.yourCompany")}
                  trailing={
                    company.kind === "retailer" ? (
                      <Badge tone="accent">
                        {t("dealers.myCompanies.retailer")}
                      </Badge>
                    ) : undefined
                  }
                />
              ))}
              <Link className="tv-sidelist-addrow" to="/dealers/new">
                + {t("dealers.myCompanies.add")}
              </Link>
            </SideListGroup>
          </>
        }
        panel={
          selected ? (
            <Panel>
              <DealerPanelBody
                company={selected}
                summary={summary}
                records={records}
                roster={roster}
                truckBalance={truckByCompany?.get(selected.id) ?? null}
                truckLoaded={truckByCompany !== null}
                allAccounts={allAccounts}
                onChanged={onChanged}
                signal={sectionSignal}
                onOpenSection={(section, agentKey, extra) =>
                  setSectionSignal((s) => ({
                    section,
                    agentKey,
                    ...(extra ?? {}),
                    n: (s?.n ?? 0) + 1,
                  }))
                }
                onReloadTruck={() => void loadTruck()}
              />
            </Panel>
          ) : (
            <Panel>
              <p className="tv-side-note">{t("dealers.directory.empty")}</p>
            </Panel>
          )
        }
      />
    </div>
  );
}

/** The right-hand panel for one dealer (owner's layout,
 *  2026-11-13 late): the logo at the Home widgets' size with
 *  the viewer's numbers at the top right of the head, the
 *  company's facts under the logo and his agent beside them —
 *  and below, the FULL dealer page itself: its sections ride
 *  a sub-tab list in the panel. Since 2026-11-14 the panel
 *  also carries everything the retired standalone page still
 *  held — the Actions menu (edit, delete, View as visitor,
 *  open a truck account), the personal-edit layer, and the
 *  visitor preview itself — so the panel is the ONLY dealer
 *  page (owner: "That separate dealer page is no longer to
 *  be used, everything should be under this one page"). */
function DealerPanelBody({
  company,
  summary,
  records,
  roster,
  truckBalance,
  truckLoaded,
  allAccounts,
  onChanged,
  signal,
  onOpenSection,
  onReloadTruck,
}: {
  company: DealerCompany;
  summary: PreferredSummary | null;
  records: CompanyMyRecords | null;
  roster: RosterEntry[] | null;
  truckBalance: number | null;
  truckLoaded: boolean;
  allAccounts: TruckAccount[] | null;
  onChanged: () => void;
  signal: CompanySectionSignal | null;
  onOpenSection: (
    section: string | null,
    agentKey: string | null,
    extra?: Partial<CompanySectionSignal>,
  ) => void;
  onReloadTruck: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const { has } = useMyModules();

  // The detail read (the sections' data + the edit layer's
  // base). The panel refetches per dealer; the visitor
  // preview swaps in its own payloads beside it.
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [moduleOff, setModuleOff] = useState(false);
  const refreshDetail = useCallback(async () => {
    try {
      setDetail(await getCompanyDetail(company.id));
    } catch {
      /* keep the last good detail */
    }
  }, [company.id]);
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setDetailError("");
    setNotFound(false);
    setModuleOff(false);
    setPreview(false);
    setPreviewDetail(null);
    setPreviewRecords(null);
    getCompanyDetail(company.id)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.code === "MODULE_DISABLED") {
          setModuleOff(true);
        } else if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setDetailError(
            err instanceof ApiError ? err.message : "Couldn't load this company.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [company.id, t]);

  // Visitor preview (Sweep D5), the panel edition: the
  // sections and the head swap to the visitor-shaped
  // payloads; the panel's personal layer (the agent block,
  // the Actions menu) stands down with them.
  const [preview, setPreview] = useState(false);
  const [previewDetail, setPreviewDetail] = useState<CompanyDetail | null>(
    null,
  );
  const [previewRecords, setPreviewRecords] =
    useState<CompanyMyRecords | null>(null);
  async function enterPreview() {
    try {
      const [visitorDetail, visitorRecords] = await Promise.all([
        getCompanyDetailAsVisitor(company.id),
        getCompanyMyRecordsAsVisitor(company.id).catch(() => null),
      ]);
      setPreviewDetail(visitorDetail);
      setPreviewRecords(visitorRecords);
      setPreview(true);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("preview.loadError"), {
        tone: "danger",
      });
    }
  }

  async function exitPreview() {
    await refreshDetail();
    setPreview(false);
    setPreviewDetail(null);
    setPreviewRecords(null);
  }

  // "View as visitor" shows only for the company's own
  // representatives (the same read the retired page used).
  const [represents, setRepresents] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!detail || !detail.company.is_directory) {
      setRepresents(false);
      return;
    }
    listMyRepresentations()
      .then((rows) => {
        if (!cancelled) {
          setRepresents(rows.some((r) => r.company_id === detail.company.id));
        }
      })
      .catch(() => {
        if (!cancelled) setRepresents(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail]);

  // "Open a truck account" gates like the retired page did:
  // truck module effective for the viewer AND this company
  // on his issuable list (a verified representative).
  const [canIssueTruck, setCanIssueTruck] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!has("truck_accounts") || !detail) {
      setCanIssueTruck(false);
      return;
    }
    getIssuableCompanies()
      .then((rows) => {
        if (!cancelled) {
          setCanIssueTruck(rows.some((r) => r.company_id === detail.company.id));
        }
      })
      .catch(() => {
        if (!cancelled) setCanIssueTruck(false);
      });
    return () => {
      cancelled = true;
    };
  }, [detail, has]);

  // The edit layer (the retired page's modals, verbatim
  // behavior): personal edits on a directory company, the
  // record itself on his own; reset + delete confirms.
  const [logoOpen, setLogoOpen] = useState(false);
  const [editingCompany, setEditingCompany] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  async function onDeleteCompany() {
    if (!detail) return;
    setDeleting(true);
    try {
      await deleteCompany(detail.company.id);
      toast(`${detail.company.name} deleted.`, { tone: "success" });
      setConfirmDelete(false);
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't delete the company.",
        { tone: "danger" },
      );
    } finally {
      setDeleting(false);
    }
  }

  async function onResetPersonal() {
    if (!detail) return;
    setResetting(true);
    try {
      await clearPersonalCompanyEdit(detail.company.id);
      await refreshDetail();
      toast(t("dealers.personal.resetDone"), { tone: "success" });
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't clear your details.",
        { tone: "danger" },
      );
    } finally {
      setResetting(false);
      setConfirmReset(false);
    }
  }

  const shownDetail = preview ? previewDetail : detail;
  const shownCompany = shownDetail?.company ?? company;
  const shownRecords = preview ? previewRecords : records;
  const shownSummary = preview ? null : summary;
  const agent = shownSummary?.agent ?? null;
  // The shown agent's roster entry carries his route area —
  // matched on the same (kind, ref) the directory row links.
  const agentEntry = agent
    ? (roster?.find(
        (e) =>
          (agent.kind === "private" &&
            e.kind === "private" &&
            e.private_agent_id === agent.private_agent_id) ||
          (agent.kind === "platform" &&
            e.kind === "platform" &&
            e.agent_user_id === agent.agent_user_id),
      ) ?? null)
    : null;
  // Whose number the Call button dials: the shown agent's,
  // else the dealer's own (the directory row's standing rule).
  const callPhone =
    (agent && agent.phone.trim() !== "" ? agent.phone : null) ??
    shownCompany.customer_service_phone ??
    shownCompany.phones[0]?.number ??
    null;
  const firstName = agent ? agent.name.split(/\s+/)[0] : "";

  return (
    <div className="tv-side-panelbody">
      <div className="tv-side-dealer-head">
        {shownCompany.logo_url ? (
          <button
            type="button"
            className="tv-side-logo-btn"
            onClick={() => setLogoOpen(true)}
            aria-label={t("dealers.page.viewLogo").replace(
              "{name}",
              shownCompany.name,
            )}
          >
            <CompanyLogo company={shownCompany} width={116} height={84} />
          </button>
        ) : (
          <CompanyLogo company={shownCompany} width={116} height={84} />
        )}
        <div className="tv-side-dealer-id">
          <h3 className="tv-side-panel-name">{shownCompany.name}</h3>
          {agent?.next_visit && (
            <p className="tv-side-badges">
              <Badge tone="accent">
                {t("dealers.roster.nextVisit").replace(
                  "{date}",
                  displayDate(agent.next_visit),
                )}
              </Badge>
            </p>
          )}
        </div>
        <div className="tv-side-dealer-side">
          {detail &&
            (preview ? (
              <Button disabled>
                {t("dealers.actions.title")}{" "}
                <span className="tv-dealer-actions-caret" aria-hidden="true">
                  ▾
                </span>
              </Button>
            ) : (
              <DealerActionsMenu
                companyName={detail.company.name}
                isMine={!detail.company.is_directory}
                canIssueTruckAccount={canIssueTruck}
                onOpenTruckAccount={() =>
                  onOpenSection("truck", null, { issue: true })
                }
                onEdit={() => setEditingCompany(true)}
                onDelete={() => setConfirmDelete(true)}
                onViewAsVisitor={
                  detail.company.is_directory && represents
                    ? () => void enterPreview()
                    : undefined
                }
              />
            ))}
          <div className="tv-side-dealer-stats">
            {shownRecords ? (
              <>
                <span>
                  <strong>{shownRecords.stats.items_count}</strong>{" "}
                  {t("dealers.side.toolsTagged")}
                </span>
                {shownRecords.stats.open_claims !== null && (
                  <span>
                    <strong>{shownRecords.stats.open_claims}</strong>{" "}
                    {t("dealers.side.openClaims")}
                  </span>
                )}
              </>
            ) : (
              <Spinner size="sm" />
            )}
            {truckLoaded && !preview && (
              <span>
                {t("dealers.side.truckAccount")}{" "}
                <strong className="tv-side-money">
                  {money((truckBalance ?? 0).toFixed(2))}
                </strong>
              </span>
            )}
          </div>
        </div>
      </div>

      {preview && <VisitorPreviewBanner onExit={() => void exitPreview()} />}
      {detail?.company.personal_edit && !preview && (
        <p className="tv-note">{t("dealers.personal.marker")}</p>
      )}

      <div className="tv-side-blocks">
        <div>
          <p className="tv-side-block-label">{t("dealers.side.theCompany")}</p>
          <CompanyFacts company={shownCompany} notes={false} />
        </div>
        <div>
          <p className="tv-side-block-label">{t("dealers.side.yourAgent")}</p>
          {shownSummary?.state === "many" ? (
            <>
              <p className="tv-side-block-text">
                {t("dealers.directory.multipleAgents")}
              </p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onOpenSection("agents", null)}
              >
                {t("dealers.side.seeAgents")}
              </Button>
            </>
          ) : agent ? (
            <>
              <div className="tv-side-agent-line">
                <Avatar name={agent.name} size="md" />
                <div>
                  <p className="tv-side-agent-name">
                    <button
                      type="button"
                      className="tv-ix-link tv-side-agent-name-btn"
                      onClick={() =>
                        onOpenSection(
                          "agents",
                          `${agent.kind}:${agent.kind === "private" ? agent.private_agent_id : agent.agent_user_id}`,
                        )
                      }
                    >
                      {agent.name}
                    </button>
                    {/* Sheet row 52 (owner, 2026-11-15): the
                        PREFERRED pillbox beside the agent's
                        name is removed — the star on the
                        Agents roster carries the state. */}
                  </p>
                  {(agentEntry?.location || agent.account_number) && (
                    <p className="tv-side-agent-sub">
                      {[
                        agentEntry?.location ?? "",
                        agent.account_number ?? "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  )}
                </div>
              </div>
              <div className="tv-side-contact-actions">
                {callPhone && (
                  <HrefButton
                    href={`tel:${phoneHref(callPhone)}`}
                    variant="primary"
                    size="sm"
                  >
                    {t("dealers.side.callName").replace("{name}", firstName)}
                  </HrefButton>
                )}
                {agent.email && (
                  <HrefButton
                    href={`mailto:${agent.email}`}
                    variant="secondary"
                    size="sm"
                  >
                    {t("dealers.side.emailName").replace("{name}", firstName)}
                  </HrefButton>
                )}
              </div>
            </>
          ) : (
            <p className="tv-side-block-text">{t("dealers.side.noAgentYet")}</p>
          )}
        </div>
      </div>

      <div className="tv-dealer-embedded">
        {moduleOff ? (
          <p className="tv-side-note">{t("dealers.page.moduleOffBody")}</p>
        ) : notFound ? (
          <p className="tv-side-note">{t("dealers.page.notFoundBody")}</p>
        ) : detailError ? (
          <Alert tone="danger">{detailError}</Alert>
        ) : shownDetail ? (
          <CompanySections
            detail={shownDetail}
            records={shownRecords}
            truckAccounts={
              preview
                ? []
                : allAccounts
                  ? allAccounts.filter(
                      (a) => a.dealer_company_id === company.id,
                    )
                  : null
            }
            preview={preview}
            signal={signal}
            onRefreshDetail={() => void refreshDetail()}
            onReloadTruck={onReloadTruck}
          />
        ) : (
          <Spinner />
        )}
      </div>

      {detail && (
        <>
          <Modal
            open={logoOpen}
            onClose={() => setLogoOpen(false)}
            title={detail.company.name}
          >
            <div className="tv-dealer-logo-large">
              <CompanyLogo company={detail.company} width={420} height={180} />
            </div>
          </Modal>

          <Modal
            open={editingCompany}
            onClose={() => setEditingCompany(false)}
            title={`Edit ${detail.company.name}`}
            size="lg"
          >
            <CompanyForm
              initial={companyToWrite(detail.company)}
              submitLabel="Save changes"
              personal={detail.company.is_directory}
              onReset={
                detail.company.personal_edit
                  ? () => {
                      setEditingCompany(false);
                      setConfirmReset(true);
                    }
                  : undefined
              }
              onSubmit={async (body) => {
                if (detail.company.is_directory) {
                  // Personal edits (2026-11-05): a directory
                  // company saves the viewer's personal layer —
                  // only the identity/contact subset leaves the
                  // form; the warranty block stays directory data.
                  const personalBody: DealerCompanyPersonalWrite = {
                    name: body.name,
                    email: body.email,
                    website: body.website,
                    address: body.address,
                    phones: body.phones,
                    notes: body.notes,
                    logo_key: body.logo_key,
                    logo_tile: body.logo_tile,
                  };
                  await savePersonalCompanyEdit(detail.company.id, personalBody);
                  await refreshDetail();
                  setEditingCompany(false);
                  toast(t("dealers.personal.saved"), { tone: "success" });
                  onChanged();
                  return;
                }
                await updateCompany(detail.company.id, body);
                await refreshDetail();
                setEditingCompany(false);
                toast(`${detail.company.name} updated.`, { tone: "success" });
                onChanged();
              }}
              onCancel={() => setEditingCompany(false)}
            />
          </Modal>

          <Modal
            open={confirmReset}
            onClose={() => setConfirmReset(false)}
            title={t("dealers.personal.reset")}
            size="sm"
            footer={
              <>
                <Button type="button" variant="secondary" onClick={() => setConfirmReset(false)}>
                  Keep mine
                </Button>
                <Button type="button" variant="danger" onClick={() => void onResetPersonal()} disabled={resetting}>
                  {t("dealers.personal.reset")}
                </Button>
              </>
            }
          >
            <p className="tv-dealer-reset-note">{t("dealers.personal.resetConfirm")}</p>
          </Modal>

          <Modal
            open={confirmDelete}
            onClose={() => setConfirmDelete(false)}
            title={`Delete "${detail.company.name}"?`}
            size="sm"
            footer={
              <>
                <Button type="button" variant="secondary" onClick={() => setConfirmDelete(false)}>
                  Keep it
                </Button>
                <Button type="button" variant="danger" onClick={() => void onDeleteCompany()} disabled={deleting}>
                  {deleting ? "Deleting…" : "Delete company"}
                </Button>
              </>
            }
          >
            <p style={{ margin: 0 }}>
              Items tagged with it keep their other data; the tag
              clears. This can't be undone.
            </p>
          </Modal>
        </>
      )}
    </div>
  );
}
