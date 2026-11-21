import { useEffect, useState } from "react";
import "../dealers.css";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
  EmptyState,
  FormField,
  HrefButton,
  ItemThumb,
  Modal,
  Panel,
  Select,
  TextInput,
  useToast,
} from "../../../components";
import type { TabItem } from "../../../components/Tabs";
import { ApiError } from "../../../lib/api";
import { formatPhone, phoneHref, todayLocalIso } from "../../../lib/format";
import { useT } from "../../../i18n/LocaleContext";
import { useAuth } from "../../core/AuthContext";
import { useMyModules } from "../../core/MyModules";
import "../../flyers/flyers.css";
import { DealerFlyersTab } from "../../flyers/DealerFlyersTab";
import { StatusBadge } from "../../claims/components";
import type { ClaimStatus } from "../../claims/types";
import { displayDate, money } from "../../inventory/format";
import { addPreferredByAgent } from "../api";
import {
  addEntry as addTruckEntry,
  getIssuableCompanies,
  getSelfCompanies,
} from "../../truck-accounts/api";
import TruckAccountWorkbench from "../../truck-accounts/TruckAccountWorkbench";
import {
  IssueAccountModal,
  SelfOpenModal,
} from "../../truck-accounts/TruckModals";
import { isDealerOnlyAccount } from "../../core/settingsMeta";
import type { TruckAccount } from "../../truck-accounts/types";
import "../../truck-accounts/truck.css";
import { DealerClaimPicker } from "../DealerClaimPicker";
import { AgentRoster } from "../AgentRoster";
import FindLocalAgentPanel from "./FindLocalAgentPanel";
import { hasWarrantyData, WarrantyBlock } from "./WarrantyBlock";
import type {
  CompanyClaimRef,
  CompanyDetail,
  CompanyMyRecords,
  PublicAgentCard,
} from "../types";

/**
 * The dealer page's SECTIONS (Details, Truck accounts, Agents,
 * Flyers, Repair claims, Repair history, Warranty Service,
 * Tools) — the whole content of the old standalone dealer
 * page, living in the Dealers tab's side panel since the
 * owner retired that page (2026-11-14: "That separate dealer
 * page is no longer to be used, everything should be under
 * this one page"). The panel owns the reads (detail, the
 * viewer's records, the truck accounts, and the visitor
 * preview swap) and passes them down; this component owns
 * the section strip and the interactions inside the
 * sections. Sections render exactly when they did on the
 * old page: the claims sections when the my-records payload
 * carries claims (the server-side two-seat gate), Warranty
 * Service under hasWarrantyData, Flyers while the flyers
 * module is effective.
 */

/** Quick pay's payment types: the select shows the localized
 *  label; the ledger note stores the canonical word. */
const PAY_TYPE_NOTES: Record<string, string> = {
  cash: "Cash",
  check: "Check",
  card: "Card",
  other: "Other",
};

/** The panel's one-shot ask: open a section (and, for the
 *  Agents section, one agent's record). `n` makes every ask
 *  a fresh signal. */
export type CompanySectionSignal = {
  section: string | null;
  agentKey: string | null;
  /** Retired truck page deep links (2026-11-17): open this
   *  account's workbench in the Truck section. */
  accountId?: string | null;
  /** Open the self-kept modal, preselected to this agent. */
  openSelfAgent?: string | null;
  /** Open the issue-for-a-customer modal. */
  issue?: boolean;
  n: number;
};

export function CompanySections({
  detail,
  records,
  truckAccounts,
  preview,
  signal,
  onRefreshDetail,
  onReloadTruck,
}: {
  detail: CompanyDetail;
  records: CompanyMyRecords | null;
  truckAccounts: TruckAccount[] | null;
  /** Visitor preview (Sweep D5): the payloads are the
   *  visitor-shaped ones and every write seat stands down. */
  preview: boolean;
  signal: CompanySectionSignal | null;
  onRefreshDetail: () => void;
  onReloadTruck: () => void;
}) {
  const { toast } = useToast();
  const t = useT();
  const { user } = useAuth();
  // The print sheet's frame date (uniform document frame,
  // 2026-11-06): the model's MM/DD/YYYY.
  const frameDate = (() => {
    const [yy, mm, dd] = todayLocalIso().split("-");
    return `${mm}/${dd}/${yy}`;
  })();
  const { has } = useMyModules();
  const [error, setError] = useState("");
  const [busyAgent, setBusyAgent] = useState<string | null>(null);
  // The agent record a signal (or the Truck section's agent
  // link) asks the roster to open — the old #agent= deep
  // link's mechanism, driven in place now.
  const [initialAgentKey, setInitialAgentKey] = useState<string | null>(null);
  // Quick pay: the Truck section row's payment in place —
  // amount, payment type, date — posted through the ordinary
  // ledger entry path.
  const [payTarget, setPayTarget] = useState<TruckAccount | null>(null);
  const [payAmount, setPayAmount] = useState("");
  const [payType, setPayType] = useState("cash");
  const [payDate, setPayDate] = useState("");
  const [payBusy, setPayBusy] = useState(false);
  const [payError, setPayError] = useState("");
  // Find a local Agent: the Agents section's scoped search.
  // A connect bumps the roster epoch to remount the roster
  // with the new agent in it — skipped while a record is
  // open by signal, whose one-shot opening a remount would
  // re-trigger.
  const [findLocalOpen, setFindLocalOpen] = useState(false);
  const [rosterEpoch, setRosterEpoch] = useState(0);
  // The Details section opens by default (sheet row 52,
  // owner 2026-11-15): a picked dealer's panel lands on its
  // details — the panel used to sit on its header alone
  // until a second click picked a section. A signal or a
  // section pick can move it from there; the Tabs component
  // falls back to the first available tab when Details
  // itself is absent.
  const [activeTab, setActiveTab] = useState("details");

  // The Truck section's in-panel account view (2026-11-17):
  // the workbench lives HERE now — the standalone account
  // page is retired, so View Account swaps the table for the
  // account's workbench in place, with a way back.
  const [openAccountId, setOpenAccountId] = useState<string | null>(null);
  const [selfOpen, setSelfOpen] = useState(false);
  const [selfAgentKey, setSelfAgentKey] = useState<string | undefined>(undefined);
  const [issueOpen, setIssueOpen] = useState(false);
  // The two open doors' gates for THIS company, read once
  // per dealer: issue = the viewer is a verified agent of
  // this company; self = the viewer has an agent here he
  // could keep a tab with (and is not a dealer-only seat).
  const [canIssueHere, setCanIssueHere] = useState(false);
  const [canSelfHere, setCanSelfHere] = useState(false);
  const dealerOnly = isDealerOnlyAccount(user?.account_types ?? []);
  useEffect(() => {
    setOpenAccountId(null);
    setSelfOpen(false);
    setIssueOpen(false);
    if (preview) {
      setCanIssueHere(false);
      setCanSelfHere(false);
      return;
    }
    let alive = true;
    getIssuableCompanies()
      .then((rows) => {
        if (alive) setCanIssueHere(rows.some((r) => r.company_id === detail.company.id));
      })
      .catch(() => {});
    if (!dealerOnly) {
      getSelfCompanies()
        .then((rows) => {
          if (alive) setCanSelfHere(rows.some((r) => r.company_id === detail.company.id));
        })
        .catch(() => {});
    } else {
      setCanSelfHere(false);
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.company.id, preview]);

  // The Truck section's agent link: select the agent in the
  // Agents section in place — the roster remounts (its epoch
  // key) so its one-shot opening applies to the new key.
  function openAgentRecord(key: string) {
    setInitialAgentKey(key);
    setRosterEpoch((e) => e + 1);
    setActiveTab("agents");
  }

  // The panel's signal: open the asked-for section (on the
  // named agent's record when a key rides along).
  useEffect(() => {
    if (!signal) return;
    if (signal.accountId || signal.openSelfAgent || signal.issue) {
      setActiveTab("truck");
      if (signal.accountId) setOpenAccountId(signal.accountId);
      if (signal.openSelfAgent) {
        setSelfAgentKey(signal.openSelfAgent);
        setSelfOpen(true);
      }
      if (signal.issue) setIssueOpen(true);
      return;
    }
    if (signal.agentKey) {
      setInitialAgentKey(signal.agentKey);
      setRosterEpoch((e) => e + 1);
      setActiveTab("agents");
    } else if (signal.section) {
      setActiveTab(signal.section);
    }
  }, [signal]);

  function openQuickPay(account: TruckAccount) {
    setPayTarget(account);
    setPayAmount("");
    setPayType("cash");
    setPayDate(todayLocalIso());
    setPayError("");
  }

  async function submitQuickPay() {
    if (!payTarget) return;
    setPayBusy(true);
    setPayError("");
    try {
      await addTruckEntry(payTarget.id, {
        kind: "payment",
        amount: payAmount.trim(),
        // The payment type rides the entry's note — the
        // ledger's one free-text fact both seats read. The
        // canonical English word is stored whatever the UI
        // language, so the record reads the same for both
        // parties (flagged in the lane report).
        note: PAY_TYPE_NOTES[payType] ?? "Other",
        item_link_id: null,
        entry_date: payDate || null,
      });
      toast(t("dealers.truck.payDone"), { tone: "success" });
      setPayTarget(null);
      await onReloadTruck();
    } catch (err) {
      setPayError(
        err instanceof ApiError ? err.message : "Couldn't record that payment.",
      );
    } finally {
      setPayBusy(false);
    }
  }
  const connectedIds = new Set(
    (detail?.my_preferred_agents ?? [])
      .filter((p) => p.kind === "platform" && p.agent_user_id)
      .map((p) => p.agent_user_id as string),
  );
  const preferredPlatformIds = new Set(
    (detail?.my_preferred_agents ?? [])
      .filter((p) => p.is_preferred && p.kind === "platform" && p.agent_user_id)
      .map((p) => p.agent_user_id as string),
  );

  async function addAgent(card: PublicAgentCard) {
    if (!detail || preview) return;
    setError("");
    setBusyAgent(card.agent_user_id);
    try {
      const result = await addPreferredByAgent({
        company_id: detail.company.id,
        agent_user_id: card.agent_user_id,
      });
      toast(
        !result.created
          ? `${card.display_name} is already one of your agents.`
          : result.preferred.is_preferred
            ? `${card.display_name} is now one of your preferred agents for ${detail.company.name}.`
            : `${card.display_name} is now one of your agents for ${detail.company.name}.`,
        { tone: "success" },
      );
      await onRefreshDetail();
      /* Mirror the Find panel's onConnected (stage 3):
       * remount the roster so the just-added agent lands in
       * its "Listed agents" section at once — unless a
       * #agent= deep-link record is open, which a remount
       * would yank away. */
      if (!initialAgentKey) setRosterEpoch((e) => e + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add that agent.");
    } finally {
      setBusyAgent(null);
    }
  }

  /* -- Tools-from-this-dealer list actions (owner, 2026-10-25):
   *    Print renders the print-only sheet at the bottom of this
   *    page (components.css .tv-dealer-tools-print); Export builds
   *    the CSV from the same rows the list shows; Email is a
   *    mailto: — the codebase's only user-triggered email send is
   *    the Reports module's spec-driven mailer, which can't take
   *    an ad-hoc list, so the user's own mail app sends this one
   *    and nothing is sent server-side. -- */
  function printTools() {
    document.body.classList.add("tv-print-dealer-tools");
    const clear = () => document.body.classList.remove("tv-print-dealer-tools");
    window.addEventListener("afterprint", clear, { once: true });
    window.print();
    // Fallback: a browser that never fires afterprint must not
    // leave the page stuck in print posture.
    setTimeout(clear, 1500);
  }

  function exportToolsCsv() {
    if (!records || !detail) return;
    const cell = (v: string) =>
      /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    const head = [
      t("dealers.records.col.item"),
      t("dealers.records.col.brand"),
      t("dealers.records.col.model"),
      t("dealers.records.col.qty"),
      t("dealers.records.col.purchased"),
      t("dealers.records.col.paid"),
    ]
      .map(cell)
      .join(",");
    const lines = records.items.map((item) =>
      [
        item.name,
        item.brand,
        item.model,
        String(item.quantity),
        item.purchase_date ?? "",
        item.spent ?? "",
      ]
        .map(cell)
        .join(","),
    );
    const blob = new Blob([[head, ...lines].join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tools-${detail.company.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function toolsMailtoHref(): string {
    if (!records || !detail) return "mailto:";
    const subject = `${t("dealers.records.itemsTitle")} — ${detail.company.name}`;
    const itemLines = records.items.map((item) => {
      const bits = [item.name];
      const brandModel = [item.brand, item.model].filter(Boolean).join(" ");
      if (brandModel) bits.push(brandModel);
      if (item.quantity > 1) bits.push(`×${item.quantity}`);
      if (item.purchase_date) bits.push(displayDate(item.purchase_date));
      if (item.spent !== null) bits.push(money(item.spent));
      return bits.join(" · ");
    });
    const body = [
      subject,
      "",
      ...(itemLines.length > 0
        ? itemLines
        : [t("dealers.records.itemsEmpty")]),
      "",
      `${t("dealers.records.stat.spent")}: ${money(records.stats.total_spent)}`,
    ].join("\n");
    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  }

  /* -- Tab contents. Each section below is the panel the page
   *  has always carried, moved verbatim into its tab; the tab
   *  strip above them is the only new structure. -- */

  /* The Truck tab (dealer page pass, 2026-11-06 — owner's
   *  spec): the TOTAL OWED TO ALL AGENTS at the top, then a
   *  true list of EVERY account with this company — open and
   *  closed — newest → oldest: agent (a link into his record)
   *  · starting balance · current balance · status pill ·
   *  QUICK PAY · VIEW ACCOUNT (the renamed "Open account").
   *  Closed accounts keep View Account and lose Quick pay —
   *  there is nothing left to pay on them. */
  const sortedTruck = truckAccounts
    ? [...truckAccounts].sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      )
    : null;
  const truckOwedTotal = (truckAccounts ?? [])
    .filter((a) => a.my_role === "customer" && a.status === "active")
    .reduce((sum, a) => sum + Number(a.balance), 0);
  const truckOutstandingTotal = (truckAccounts ?? [])
    .filter((a) => a.my_role === "dealer" && a.status === "active")
    .reduce((sum, a) => sum + Number(a.balance), 0);
  const truckPartyHeader =
    sortedTruck && sortedTruck.every((a) => a.my_role === "dealer")
      ? t("dealers.truck.col.customer")
      : sortedTruck && sortedTruck.every((a) => a.my_role === "customer")
        ? t("dealers.truck.col.agent")
        : t("dealers.truck.col.agentCustomer");

  function truckAgentKey(account: TruckAccount): string | null {
    if (account.agent_kind === "private" && account.private_agent_id)
      return `private:${account.private_agent_id}`;
    if (account.agent_kind === "platform" && account.dealer_user_id)
      return `platform:${account.dealer_user_id}`;
    return null;
  }

  const openTruckAccount = openAccountId
    ? (sortedTruck ?? []).find((a) => a.id === openAccountId) ?? null
    : null;

  const truckTab = detail && sortedTruck && (sortedTruck.length > 0 || canIssueHere || canSelfHere) ? (
    <Panel
      title={
        sortedTruck[0]?.my_role === "dealer"
          ? "Truck accounts you run with this company"
          : `Your truck accounts with ${detail.company.name}`
      }
    >
      {openTruckAccount ? (
        <div className="tv-truck-stack">
          <p style={{ margin: 0 }}>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setOpenAccountId(null)}
            >
              ← {t("truck.backToAccounts")}
            </Button>
          </p>
          <TruckAccountWorkbench
            accountId={openTruckAccount.id}
            onChanged={onReloadTruck}
          />
        </div>
      ) : (
      <>
      {!preview && (canSelfHere || canIssueHere) && (
        <p style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", margin: "0 0 0.75rem" }}>
          {canSelfHere && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setSelfAgentKey(undefined);
                setSelfOpen(true);
              }}
            >
              {t("truck.openSelfKept")}
            </Button>
          )}
          {canIssueHere && (
            <Button size="sm" variant="secondary" onClick={() => setIssueOpen(true)}>
              {t("truck.openForCustomer")}
            </Button>
          )}
        </p>
      )}
      {sortedTruck.length === 0 && (
        <p className="tv-dealer-truck-note">{t("truck.emptyTitle")}</p>
      )}
      {truckOwedTotal > 0 && (
        <p className="tv-dealer-truck-total">
          {t("dealers.truck.totalOwed")}:{" "}
          <strong>{money(String(truckOwedTotal))}</strong>
        </p>
      )}
      {truckOutstandingTotal > 0 && (
        <p className="tv-dealer-truck-total">
          {t("dealers.truck.totalOutstanding")}:{" "}
          <strong>{money(String(truckOutstandingTotal))}</strong>
        </p>
      )}
      <div className="tv-dealer-truck-table">
        <div className="tv-dealer-truck-thead" aria-hidden="true">
          <span>{truckPartyHeader}</span>
          <span>{t("dealers.truck.col.start")}</span>
          <span>{t("dealers.truck.col.current")}</span>
          <span>{t("dealers.truck.col.status")}</span>
          <span />
        </div>
        {sortedTruck.map((account) => {
          const agentKey =
            account.my_role === "customer" ? truckAgentKey(account) : null;
          return (
            <div key={account.id} className="tv-dealer-truck-row">
              <span className="tv-dealer-truck-party">
                {account.my_role === "dealer" ? (
                  (account.customer_name ?? "Customer")
                ) : agentKey ? (
                  <button
                    type="button"
                    className="tv-dealer-agent-link"
                    onClick={() => openAgentRecord(agentKey)}
                  >
                    {account.agent_name}
                  </button>
                ) : (
                  account.agent_name || "—"
                )}
                {account.my_role === "customer" &&
                  account.status === "invited" && (
                    <span className="tv-dealer-truck-note">
                      {" "}
                      {t("dealers.truck.reviewInvite")}
                    </span>
                  )}
              </span>
              <span>{money(account.starting_balance)}</span>
              <span>
                <strong>{money(account.balance)}</strong>
              </span>
              <span className="tv-dealer-truck-status">
                {account.status === "active" ? (
                  <Badge tone="success">{t("dealers.truck.statusActive")}</Badge>
                ) : account.status === "invited" ? (
                  <Badge tone="warning">{t("dealers.truck.statusInvited")}</Badge>
                ) : (
                  <Badge tone="neutral">{t("dealers.truck.statusClosed")}</Badge>
                )}
                {account.missed_payments > 0 && (
                  <span className="tv-agent-missed">
                    {t("dealers.truck.missedLine")
                      .replace("{count}", String(account.missed_payments))
                      .replace("{amount}", money(account.amount_past_due))}
                  </span>
                )}
              </span>
              <span className="tv-dealer-truck-actions">
                {account.status === "active" && (
                  <Button size="sm" onClick={() => openQuickPay(account)}>
                    {t("dealers.truck.quickPay")}
                  </Button>
                )}
                {/* The pair wears ONE treatment (owner,
                 * 2026-11-06): Quick pay and View Account are
                 * the same primary small button, side by side.
                 * View Account opens THIS account's workbench
                 * in place (2026-11-17: the standalone account
                 * page is retired — the workbench lives in
                 * this section now, for both roles). */}
                <Button size="sm" onClick={() => setOpenAccountId(account.id)}>
                  {t("dealers.truck.viewAccount")}
                </Button>
              </span>
            </div>
          );
        })}
      </div>
      </>
      )}
    </Panel>
  ) : null;

  const statsPanel = records ? (
    <Panel title={t("dealers.records.statsTitle")}>
      <dl className="tv-rec-stats">
        <RecordStat
          label={t("dealers.records.stat.items")}
          value={String(records.stats.items_count)}
        />
        <RecordStat
          label={t("dealers.records.stat.spent")}
          value={money(records.stats.total_spent)}
        />
        {records.stats.replacement_value !== null && (
          <RecordStat
            label={t("dealers.records.stat.replacement")}
            value={money(records.stats.replacement_value)}
          />
        )}
        {records.stats.last_purchase_date && (
          <RecordStat
            label={t("dealers.records.stat.lastPurchase")}
            value={displayDate(records.stats.last_purchase_date)}
          />
        )}
        {records.stats.open_claims !== null && (
          <RecordStat
            label={t("dealers.records.stat.openClaims")}
            value={String(records.stats.open_claims)}
          />
        )}
        {records.stats.total_claims !== null && (
          <RecordStat
            label={t("dealers.records.stat.totalClaims")}
            value={String(records.stats.total_claims)}
          />
        )}
      </dl>
    </Panel>
  ) : null;

  /* Details tab (dealer page pass, 2026-11-06): the
   *  "Company details" block is REMOVED on the owner's order
   *  — every fact it held already lives in the page header.
   *  The tab keeps the viewer's stats with this dealer; when
   *  the records read is absent there is nothing left for the
   *  tab to hold, so it renders no tab at all (the Tabs
   *  component falls back to the first available tab). */
  const detailsTab = statsPanel ? (
    <div className="tv-stack">{statsPanel}</div>
  ) : null;

  const agentsTab = detail ? (
    <div className="tv-stack">
      {/* The roster (stage 1, 2026-11-04) LEADS the tab
          (owner, 2026-11-05): the viewer's own agents for
          this company — entered records + connected platform
          agents, the preferred starred — sit at
          the top, above the Find local Agent search and the
          company's listed-agents panel below. */}
      <AgentRoster
        key={`roster-${rosterEpoch}`}
        companyId={detail.company.id}
        onChanged={preview ? () => {} : onRefreshDetail}
        initialSelectedKey={preview ? null : initialAgentKey}
        asVisitor={preview}
      />
      {/* Find local Agent (stage 3, 2026-11-05): the scoped
          ZIP + radius search for this dealer. Directory
          companies only — a private company is one user's own
          record and no registered agent can hold a
          representation of it, so a scoped search there could
          only ever come back empty. */}
      {detail.company.is_directory && (
        <>
          <div>
            <Button
              variant="secondary"
              aria-expanded={findLocalOpen}
              onClick={() => setFindLocalOpen((open) => !open)}
              disabled={preview}
            >
              {t("dealers.findLocal.button")}
            </Button>
          </div>
          {findLocalOpen && !preview && (
            <FindLocalAgentPanel
              companyId={detail.company.id}
              companyName={detail.company.name}
              onConnected={() => {
                onRefreshDetail();
                if (!initialAgentKey) setRosterEpoch((e) => e + 1);
              }}
            />
          )}
        </>
      )}
      <Panel title={t("dealers.page.agentsFor").replace("{name}", detail.company.name)}>
        {detail.agents.length === 0 ? (
          <EmptyState
            title={t("dealers.page.noListedAgents")}
            description={t("dealers.page.noListedAgentsBody")}
          />
        ) : (
          <div style={{ display: "grid", gap: "0.6rem" }}>
            {detail.agents.map((card) => (
              <div
                key={card.agent_user_id}
                style={{
                  display: "flex",
                  gap: "0.9rem",
                  alignItems: "flex-start",
                  flexWrap: "wrap",
                }}
              >
                {card.photo_url && (
                  <img
                    src={card.photo_url}
                    alt={card.display_name}
                    style={{
                      width: "56px",
                      height: "56px",
                      objectFit: "cover",
                      borderRadius: "var(--radius)",
                    }}
                  />
                )}
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <p style={{ margin: 0 }}>
                    <strong>{card.display_name}</strong>{" "}
                    {card.verified && <Badge tone="success">{t("dealers.page.verified")}</Badge>}
                  </p>
                  {card.service_area && (
                    <p style={{ margin: "0.2rem 0 0", color: "var(--text-muted)" }}>
                      {card.service_area}
                    </p>
                  )}
                  {card.bio && <p style={{ margin: "0.3rem 0 0" }}>{card.bio}</p>}
                  <p style={{ margin: "0.4rem 0 0", display: "flex", gap: "0.8rem", flexWrap: "wrap" }}>
                    {card.phone && (
                      <>
                        <a href={`tel:${phoneHref(card.phone)}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
                          {t("dealers.roster.call")}
                        </a>
                        <a href={`sms:${phoneHref(card.phone)}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
                          {t("dealers.roster.text")}
                        </a>
                      </>
                    )}
                    {card.contact_email && (
                      <a href={`mailto:${card.contact_email}`} style={{ color: "var(--accent)", fontWeight: 600 }}>
                        {t("dealers.roster.email")}
                      </a>
                    )}
                  </p>
                </div>
                <div>
                  {preferredPlatformIds.has(card.agent_user_id) ? (
                    <Badge tone="success">{t("dealers.page.yourPreferred")}</Badge>
                  ) : connectedIds.has(card.agent_user_id) ? (
                    <Badge tone="neutral">{t("dealers.page.oneOfYours")}</Badge>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => void addAgent(card)}
                      loading={busyAgent === card.agent_user_id}
                      disabled={preview}
                    >
                      {t("dealers.page.addAsMyAgent")}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  ) : null;

  const claimsOpenTab = records?.claims ? (
    <Panel>
      <div className="tv-claims-tabbar">
        <DealerClaimPicker items={records.items} disabled={preview} />
      </div>
      {records.claims.current.length === 0 ? (
        <p className="tv-ix-empty">{t("dealers.records.claimsEmpty")}</p>
      ) : (
        <DealerClaimGroup claims={records.claims.current} />
      )}
    </Panel>
  ) : null;

  const claimsHistoryTab = records?.claims ? (
    <Panel>
      {records.claims.history.length === 0 ? (
        <p className="tv-ix-empty">{t("dealers.records.claimsEmpty")}</p>
      ) : (
        <DealerClaimGroup claims={records.claims.history} />
      )}
    </Panel>
  ) : null;

  const warrantyTab = detail && hasWarrantyData(detail.company) ? (
    <Panel>
      <WarrantyBlock company={detail.company} />
    </Panel>
  ) : null;

  const toolsTab = records ? (
    <Panel
      title={t("dealers.records.itemsTitle")}
      actions={
        <span className="tv-rec-actions">
          <Button size="sm" variant="secondary" onClick={printTools} disabled={preview}>
            {t("dealers.records.print")}
          </Button>
          {preview ? (
            <Button size="sm" variant="secondary" disabled>
              {t("dealers.records.emailList")}
            </Button>
          ) : (
            <HrefButton size="sm" variant="secondary" href={toolsMailtoHref()}>
              {t("dealers.records.emailList")}
            </HrefButton>
          )}
          <Button size="sm" variant="secondary" onClick={exportToolsCsv} disabled={preview}>
            {t("dealers.records.exportCsv")}
          </Button>
        </span>
      }
    >
      {records.items.length === 0 ? (
        <EmptyState
          title={t("dealers.records.itemsEmpty")}
        />
      ) : (
        <div className="tv-ix-rows">
          {records.items.map((item) => (
            <div
              key={`${item.item_kind}-${item.id}`}
              className="tv-ix-row"
            >
              <span className="tv-thumb-cell--sm">
                <ItemThumb
                  src={item.photo?.thumb_url_sm || item.photo?.thumb_url || null}
                  name={item.name}
                  aspectRatio="4 / 3"
                />
              </span>
              <span className="tv-ix-row-main">
                <Link
                  to={
                    item.item_kind === "battery"
                      ? `/inventory/batteries/${item.id}`
                      : `/inventory/${item.id}`
                  }
                  className="tv-ix-link"
                >
                  {item.name}
                </Link>
                {item.is_set && (
                  <Badge tone="neutral">
                    {t("dealers.records.setBadge")}
                  </Badge>
                )}
                <span className="tv-rec-item-meta">
                  {[item.brand, item.model].filter(Boolean).join(" · ")}
                  {item.quantity > 1 ? ` · ×${item.quantity}` : ""}
                </span>
              </span>
              <span className="tv-rec-item-right">
                {item.purchase_date && (
                  <span>{displayDate(item.purchase_date)}</span>
                )}
                {item.spent !== null && (
                  <strong>{money(item.spent)}</strong>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  ) : null;

  const payAmountNum = Number(payAmount);
  const payValid =
    payAmount.trim() !== "" &&
    Number.isFinite(payAmountNum) &&
    payAmountNum > 0;
  const payBalanceAfter =
    payTarget && payValid
      ? Number(payTarget.balance) - payAmountNum
      : null;

  /* Flyers tab (flyer module, 2026-11-06): this company's
   *  flyer spots — the company's own and its agents' — with
   *  current + history and the posting controls for rights
   *  holders. The tab exists only while the flyers module is
   *  effective for the viewer (module doctrine: an off module
   *  leaves no trace on other modules' pages). */
  const flyersTab =
    detail && has("flyers") ? (
      <DealerFlyersTab
        companyId={detail.company.id}
        companyName={detail.company.name}
        asVisitor={preview}
      />
    ) : null;

  const tabs: TabItem[] = detail
    ? [
        ...(detailsTab
          ? [{ id: "details", label: t("dealers.tabs.details"), content: detailsTab } as TabItem]
          : []),
        ...(truckTab
          ? [{ id: "truck", label: t("dealers.tabs.truckAccounts"), content: truckTab } as TabItem]
          : []),
        ...(agentsTab
          ? [{ id: "agents", label: t("dealers.tabs.agents"), content: agentsTab } as TabItem]
          : []),
        ...(flyersTab
          ? [{ id: "flyers", label: t("flyers.tab"), content: flyersTab } as TabItem]
          : []),
        ...(claimsOpenTab
          ? [{ id: "claims-open", label: t("repairs.tab.claims"), content: claimsOpenTab } as TabItem]
          : []),
        ...(claimsHistoryTab
          ? [
              {
                id: "claims-history",
                label: t("repairs.tab.history"),
                content: claimsHistoryTab,
              } as TabItem,
            ]
          : []),
        ...(warrantyTab
          ? [{ id: "warranty", label: t("dealers.tabs.warrantyService"), content: warrantyTab } as TabItem]
          : []),
        ...(toolsTab
          ? [{ id: "tools", label: t("dealers.tabs.tools"), content: toolsTab } as TabItem]
          : []),
      ]
    : [];

  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      <div
        className="tv-side-subtabs"
        role="group"
        aria-label={t("dealers.side.sectionsLabel")}
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`tv-side-subtab${activeTab === tab.id ? " is-open" : ""}`}
            aria-expanded={activeTab === tab.id}
            onClick={() => setActiveTab(activeTab === tab.id ? "" : tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {(() => {
        const current = tabs.find((tab) => tab.id === activeTab);
        return current ? (
          <div className="tv-side-subtab-body">{current.content}</div>
        ) : null;
      })()}

          <Modal
            open={payTarget !== null}
            onClose={() => setPayTarget(null)}
            title={t("dealers.truck.payTitle")}
            size="sm"
            footer={
              <>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setPayTarget(null)}
                >
                  {t("common.cancel")}
                </Button>
                <Button
                  type="button"
                  onClick={() => void submitQuickPay()}
                  loading={payBusy}
                  disabled={!payValid}
                >
                  {t("dealers.truck.paySubmit")}
                </Button>
              </>
            }
          >
            {payTarget && (
              <div className="tv-stack">
                <p className="tv-dealer-truck-note">
                  {payTarget.my_role === "dealer"
                    ? (payTarget.customer_name ?? "Customer")
                    : payTarget.agent_name}{" "}
                  · {detail.company.name} ·{" "}
                  {money(payTarget.balance)}
                </p>
                {payError && <Alert tone="danger">{payError}</Alert>}
                <FormField
                  label={t("dealers.truck.payAmount")}
                  htmlFor="quick-pay-amount"
                  required
                >
                  <TextInput
                    id="quick-pay-amount"
                    inputMode="decimal"
                    value={payAmount}
                    onChange={(e) => setPayAmount(e.target.value)}
                  />
                </FormField>
                <FormField
                  label={t("dealers.truck.payType")}
                  htmlFor="quick-pay-type"
                >
                  <Select
                    id="quick-pay-type"
                    value={payType}
                    onChange={(e) => setPayType(e.target.value)}
                  >
                    {Object.keys(PAY_TYPE_NOTES).map((key) => (
                      <option key={key} value={key}>
                        {t(`dealers.truck.payType.${key}` as never)}
                      </option>
                    ))}
                  </Select>
                </FormField>
                <FormField
                  label={t("dealers.truck.payDate")}
                  htmlFor="quick-pay-date"
                >
                  <DatePicker
                    id="quick-pay-date"
                    value={payDate}
                    onChange={setPayDate}
                  />
                </FormField>
                {payBalanceAfter !== null && (
                  <p className="tv-dealer-truck-note">
                    {t("dealers.truck.payBalanceAfter")}:{" "}
                    <strong>{money(String(payBalanceAfter))}</strong>
                  </p>
                )}
              </div>
            )}
          </Modal>

      {!preview && (
        <>
          <SelfOpenModal
            open={selfOpen}
            onClose={() => setSelfOpen(false)}
            initialCompanyId={detail.company.id}
            initialAgentKey={selfAgentKey}
            onOpened={(account) => {
              onReloadTruck();
              setOpenAccountId(account.id);
            }}
          />
          <IssueAccountModal
            open={issueOpen}
            onClose={() => setIssueOpen(false)}
            initialCompanyId={detail.company.id}
            onOpened={() => onReloadTruck()}
          />
        </>
      )}

      {records && !preview && (
            <div className="tv-dealer-tools-print" aria-hidden="true">
              {/* The uniform document frame (2026-11-06): the
                  sheet's head wears the same top as every
                  generated document — centered title, prepared
                  date, the bordered prepared-for box — and the
                  wordmark footer closes it. */}
              <h1>{detail.company.name}</h1>
              <p className="tv-dtp-sub">{t("dealers.records.itemsTitle")}</p>
              <p className="tv-dtp-prepared">
                {t("print.prepared").replace("{when}", frameDate)}
              </p>
              {user ? (
                <div className="tv-dtp-for">
                  <div className="tv-dtp-for-left">
                    <span className="tv-dtp-for-label">
                      {t("print.preparedFor")}
                    </span>
                    {user.name ? (
                      <span className="tv-dtp-for-name">{user.name}</span>
                    ) : null}
                    {(user.postal_address || "")
                      .split("\n")
                      .map((line) => line.trim())
                      .filter(Boolean)
                      .map((line, i) => (
                        <span key={i} className="tv-dtp-for-line">
                          {line}
                        </span>
                      ))}
                  </div>
                  <div className="tv-dtp-for-right">
                    {user.phone ? (
                      <span>
                        {t("print.phone")}: {formatPhone(user.phone)}
                      </span>
                    ) : null}
                    {user.email ? (
                      <span>
                        {t("print.email")}: {user.email}
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {/* The navy banner (report layout standard,
                  element 4): the sheet's headline facts — the
                  item count flowing left, the total spent
                  parked right in bold white. */}
              <div className="tv-dtp-banner">
                <span>
                  {t("dealers.records.stat.items")}: {records.stats.items_count}
                </span>
                <span className="tv-dtp-banner-total">
                  {t("dealers.records.stat.spent")}:{" "}
                  {money(records.stats.total_spent)}
                </span>
              </div>
              {records.items.length === 0 ? (
                <p>{t("dealers.records.itemsEmpty")}</p>
              ) : (
                <table className="tv-dtp-table">
                  <thead>
                    <tr>
                      <th>{t("dealers.records.col.item")}</th>
                      <th>{t("dealers.records.col.brand")}</th>
                      <th>{t("dealers.records.col.model")}</th>
                      <th>{t("dealers.records.col.qty")}</th>
                      <th>{t("dealers.records.col.purchased")}</th>
                      <th>{t("dealers.records.col.paid")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.items.map((item) => (
                      <tr key={`print-${item.item_kind}-${item.id}`}>
                        <td>{item.name}</td>
                        <td>{item.brand}</td>
                        <td>{item.model}</td>
                        <td>{item.quantity}</td>
                        <td>
                          {item.purchase_date
                            ? displayDate(item.purchase_date)
                            : ""}
                        </td>
                        <td>{item.spent !== null ? money(item.spent) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                  {/* Print only: the repeating foot reserves
                      the wordmark footer's zone on every page
                      the table breaks across. */}
                  <tfoot aria-hidden="true">
                    <tr>
                      <td colSpan={6} className="tv-dtp-foot-spacer" />
                    </tr>
                  </tfoot>
                </table>
              )}
              <p className="tv-dtp-total">
                {/* The bottom navy totals bar (standard
                    element 7): a SHORT bar hugging its text —
                    just "TOTAL:" + the amount. The count the
                    line used to carry rides the banner above. */}
                <span className="tv-dtp-total-bar">
                  {t("print.total")}: {money(records.stats.total_spent)}
                </span>
              </p>
              <div className="tv-dtp-footer">
                <span>{t("print.generatedBy")}</span>
                <img src="/brand/wordmark-840.webp" alt="" />
                <span>· {frameDate}</span>
              </div>
            </div>
      )}
    </>
  );
}

/** One label/value row of the records stats (the tool page's
 *  Details-row shape: muted label, value beside it). */
function RecordStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="tv-rec-stat">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** One group of the dealer page's claims (the Repair claims
 *  tab renders the current list, the Repair history tab the
 *  history list — the tab itself is the heading now), rebuilt
 *  as a TRUE LIST (dealer page pass, 2026-11-06 — owner's
 *  spec): the claim's headline is the name of the TOOL being
 *  claimed (the claim number stays inside the claim record,
 *  not the row), with Claim date · Claim status · Last update
 *  spread in columns across the row. The whole row is the
 *  link into the claim's OWN section (the separation's
 *  kind-aware routing stands) and carries the Main highlight
 *  effect's ROWS treatment. A claim whose lines name no tool
 *  of this dealer falls back to its claim number as the only
 *  honest headline left. */
function DealerClaimGroup({
  claims,
}: {
  claims: CompanyClaimRef[];
}) {
  const t = useT();
  return (
    <div className="tv-dealer-claim-table">
      <div className="tv-dealer-claim-thead" aria-hidden="true">
        <span>{t("dealers.records.col.claimName")}</span>
        <span>{t("dealers.records.col.claimDate")}</span>
        <span>{t("dealers.records.col.claimStatus")}</span>
        <span>{t("dealers.records.col.claimUpdated")}</span>
      </div>
      {claims.map((claim) => (
        <Link
          key={claim.id}
          to={
            claim.kind === "insurance_disaster"
              ? `/disaster-claims/${claim.id}`
              : `/claims/${claim.id}`
          }
          className="tv-dealer-claim-row"
        >
          <span className="tv-dealer-claim-name">
            <strong>{claim.items[0] ?? claim.claim_number}</strong>
            {claim.items.length > 1 && (
              <span className="tv-dealer-claim-more">
                +{claim.items.length - 1}
              </span>
            )}
          </span>
          <span>
            {displayDate(
              (claim.reported_at ?? claim.created_at).slice(0, 10),
            )}
          </span>
          <span>
            <StatusBadge status={claim.status as ClaimStatus} />
          </span>
          <span>
            {claim.updated_at
              ? displayDate(claim.updated_at.slice(0, 10))
              : "—"}
          </span>
        </Link>
      ))}
    </div>
  );
}
