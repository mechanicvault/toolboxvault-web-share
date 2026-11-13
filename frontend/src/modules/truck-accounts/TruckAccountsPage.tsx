import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  DatePicker,
  EmptyState,
  FormField,
  Modal,
  Panel,
  SectionPageHeader,
  Select,
  Spinner,
  Tabs,
  TextInput,
  useToast,
  LinkButton,
  type SectionPageFact,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { displayDate, money } from "../inventory/format";
import {
  createAccount,
  getIssuableCompanies,
  getSelfCompanies,
  getSelfTargets,
  listAccounts,
  openSelfAccount,
} from "./api";
import TruckAccountWorkbench from "./TruckAccountWorkbench";
import type {
  IssuableCompany,
  SelfOpenTarget,
  TruckAccount,
} from "./types";
import "./truck.css";

/**
 * Truck Accounts (Stage 2 rebuild, 2026-11-05): a main-tab-
 * layout OVERVIEW. The glance list carries the totals across
 * the tabs the user OWES on (total owed to all agents, one
 * row per agent); a status strip names every account needing
 * attention and jumps to its tab; ONE TAB PER CUSTOMER ACCOUNT
 * holds that account's whole workbench (balance, schedule with
 * its missed state, the ledger, quick entry, statements).
 * Accounts the user ISSUED as an agent keep their existing
 * surface — the true-list table — on a final "Accounts you run"
 * tab, each row opening the standalone account page.
 *
 * Two ways in: the customer opens a SELF-KEPT account against
 * any agent on his roster (no agreement gate — his own books),
 * and an agent issues an account to a customer exactly as
 * before (agreement gate and all).
 *
 * Truck page fixes (2026-11-06): "Open for a customer" is a
 * dealer-seat action — it renders only for a user who can
 * actually issue (a verified agent of at least one company);
 * a plain mechanic never sees it. "Your tabs at a glance" is
 * a true list: the total owed to all agents, then one
 * clickable row per agent jumping to his account tab.
 *
 * Main Tab Layout program, Lane 8 (2026-11-10): the bare
 * header row is now the shared kit header (SectionPageHeader —
 * truck plate, title, the standing intro as subtitle, facts =
 * total owed across the owed tabs + the count of accounts the
 * user runs). The two open-account commands fold into the
 * header's Actions menu (same gates, same modals), and the
 * attention strip rides INSIDE the header panel in its body
 * row (owner, 2026-11-10: merged into the header bar; Lane 8
 * first seated it in the status-strip seat under the panel).
 * Tabs, glance, workbench and
 * both open flows are unchanged. Actions → Settings is a
 * recorded n/a: the page owns no user-facing settings section
 * (per-account schedule/terms live in the account's own tab;
 * the platform fee is an Admin setting).
 */

type TranslateFn = ReturnType<typeof useT>;

function statusBadge(account: TruckAccount, t: TranslateFn) {
  if (account.status === "active")
    return <Badge tone="success">{t("dealers.truck.statusActive")}</Badge>;
  if (account.status === "invited")
    return <Badge tone="warning">{t("dealers.truck.statusInvited")}</Badge>;
  return <Badge tone="neutral">{t("dealers.truck.statusClosed")}</Badge>;
}

const STATUS_ORDER: Record<TruckAccount["status"], number> = {
  active: 0,
  invited: 1,
  closed: 2,
};

function tabLabel(account: TruckAccount, t: TranslateFn): string {
  const company = account.dealer_company_name ?? t("truck.dealerFallback");
  const agent = account.agent_name || t("truck.yourRecords");
  const suffix =
    account.status === "invited"
      ? t("truck.tabInviteSuffix")
      : account.status === "closed"
        ? t("truck.tabClosedSuffix")
        : "";
  return `${company} · ${agent}${suffix}`;
}

export default function TruckAccountsPage() {
  const { toast } = useToast();
  const t = useT();
  const location = useLocation();
  const [accounts, setAccounts] = useState<TruckAccount[] | null>(null);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<string>("");

  // Dealer issuance (unchanged flow). Whether THIS user can
  // issue at all — the "Open for a customer" button's gate.
  const [canIssue, setCanIssue] = useState(false);
  const [creating, setCreating] = useState(false);
  const [mode, setMode] = useState<"number" | "email">("number");
  const [accountNumber, setAccountNumber] = useState("");
  const [email, setEmail] = useState("");
  const [cadence, setCadence] = useState("weekly");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [companies, setCompanies] = useState<IssuableCompany[] | null>(null);
  const [companyId, setCompanyId] = useState("");
  const [creditLimit, setCreditLimit] = useState("");

  // Stage 2: the self-kept open flow.
  const [selfOpen, setSelfOpen] = useState(false);
  const [selfCompanies, setSelfCompanies] = useState<IssuableCompany[] | null>(null);
  const [selfCompanyId, setSelfCompanyId] = useState("");
  const [selfTargets, setSelfTargets] = useState<SelfOpenTarget[] | null>(null);
  const [selfTarget, setSelfTarget] = useState("");
  const [selfBalance, setSelfBalance] = useState("");
  const [selfNote, setSelfNote] = useState("");
  const [selfCadence, setSelfCadence] = useState("weekly");
  const [selfAmount, setSelfAmount] = useState("");
  const [selfDue, setSelfDue] = useState("");
  const [selfMode, setSelfMode] = useState("manual");
  const [selfSaving, setSelfSaving] = useState(false);
  const [pendingAgent, setPendingAgent] = useState("");

  useEffect(() => {
    if (!creating || companies !== null) return;
    getIssuableCompanies()
      .then((rows) => {
        setCompanies(rows);
        if (rows.length === 1) setCompanyId(rows[0].company_id);
      })
      .catch(() => setCompanies([]));
  }, [creating, companies]);

  // The issuable-companies read is the same fact the create
  // flow and the API gate on: a verified representation of at
  // least one company. It decides whether the dealer-seat
  // "Open for a customer" action exists on this page at all.
  useEffect(() => {
    getIssuableCompanies()
      .then((rows) => setCanIssue(rows.length > 0))
      .catch(() => setCanIssue(false));
  }, []);

  const refresh = useCallback(() => {
    listAccounts()
      .then(setAccounts)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : t("truck.loadFailed"),
        ),
      );
  }, []);

  useEffect(refresh, [refresh]);

  const mine = useMemo(
    () => (accounts ?? []).filter((a) => a.my_role === "dealer"),
    [accounts],
  );
  const theirs = useMemo(
    () =>
      (accounts ?? [])
        .filter((a) => a.my_role === "customer")
        .sort(
          (x, y) =>
            STATUS_ORDER[x.status] - STATUS_ORDER[y.status] ||
            (x.dealer_company_name ?? "").localeCompare(
              y.dealer_company_name ?? "",
            ) ||
            x.agent_name.localeCompare(y.agent_name),
        ),
    [accounts],
  );

  // The deep links: #account=<id> selects that account's tab;
  // ?open=self&company=<id>&agent=<kind>:<ref> opens the
  // self-kept modal prefilled (the agent record's Open action).
  // An id naming an account the viewer RUNS selects the
  // accounts-you-run tab instead (sweep B3, F2): it used to fall
  // through silently, leaving the viewer's own first customer
  // tab on screen — a door that landed on the wrong account.
  useEffect(() => {
    if (!accounts) return;
    const match = location.hash.match(/account=([0-9a-f-]{36})/i);
    if (!match) return;
    if (theirs.some((a) => a.id === match[1])) {
      setActiveTab(`acct:${match[1]}`);
    } else if (mine.some((a) => a.id === match[1])) {
      setActiveTab("dealer-run");
    }
  }, [accounts, location.hash, theirs, mine]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get("open") !== "self") return;
    setSelfOpen(true);
    const company = params.get("company");
    if (company) setSelfCompanyId(company);
    const agent = params.get("agent");
    if (agent) setPendingAgent(agent);
    // Run once on mount — the params are a landing instruction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selfOpen) return;
    if (selfCompanies === null) {
      getSelfCompanies()
        .then((rows) => {
          setSelfCompanies(rows);
          if (!selfCompanyId && rows.length === 1) {
            setSelfCompanyId(rows[0].company_id);
          }
        })
        .catch(() => setSelfCompanies([]));
      return;
    }
    if (!selfCompanyId) {
      setSelfTargets(null);
      return;
    }
    getSelfTargets(selfCompanyId)
      .then((rows) => {
        setSelfTargets(rows);
        const wanted = pendingAgent
          ? rows.find(
              (t) =>
                `${t.kind}:${t.private_agent_id ?? t.agent_user_id}` ===
                pendingAgent,
            )
          : undefined;
        const firstFree = rows.find((t) => !t.has_open_account);
        const pick = wanted && !wanted.has_open_account ? wanted : firstFree;
        setSelfTarget(
          pick ? `${pick.kind}:${pick.private_agent_id ?? pick.agent_user_id}` : "",
        );
      })
      .catch(() => setSelfTargets([]));
  }, [selfOpen, selfCompanies, selfCompanyId, pendingAgent]);

  async function create() {
    setSaving(true);
    try {
      const account = await createAccount({
        customer_account_number: mode === "number" ? accountNumber.trim() : "",
        customer_email: mode === "email" ? email.trim() : "",
        payment_cadence: cadence,
        payment_amount: amount === "" ? null : amount,
        next_due_date: dueDate || null,
        dealer_company_id: companyId || null,
        credit_limit: creditLimit === "" ? null : creditLimit,
      });
      toast(
        account.customer_user_id
          ? t("truck.toastOpenedInbox")
          : t("truck.toastInviteSaved"),
      );
      setCreating(false);
      setAccountNumber("");
      setEmail("");
      setAmount("");
      setDueDate("");
      setCreditLimit("");
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function createSelf() {
    const [kindPart, refId] = selfTarget.split(":");
    if (!selfCompanyId || !kindPart || !refId) return;
    setSelfSaving(true);
    try {
      const account = await openSelfAccount({
        company_id: selfCompanyId,
        private_agent_id: kindPart === "private" ? refId : null,
        agent_user_id: kindPart === "platform" ? refId : null,
        opening_balance: selfBalance === "" ? "0" : selfBalance,
        opening_note: selfNote.trim(),
        payment_cadence: selfCadence as "weekly" | "biweekly",
        payment_amount: selfAmount === "" ? null : selfAmount,
        next_due_date: selfDue || null,
        payment_mode: selfMode as "manual" | "automatic",
      });
      toast(t("truck.toastSelfOpened"));
      setSelfOpen(false);
      setSelfBalance("");
      setSelfNote("");
      setSelfAmount("");
      setSelfDue("");
      refresh();
      setActiveTab(`acct:${account.id}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
    } finally {
      setSelfSaving(false);
    }
  }

  /** The dealer-seat table (list standard): unchanged from the
   *  pre-stage-2 page — one account per row, facts in columns,
   *  each row opening the standalone account page. */
  function renderDealerTable(rows: TruckAccount[]) {
    return (
      <div className="tv-truck-table" role="table">
        <div className="tv-truck-thead" role="row">
          <span role="columnheader">{t("truck.col.company")}</span>
          <span role="columnheader">{t("dealers.truck.col.agent")}</span>
          <span role="columnheader">{t("dealers.truck.col.customer")}</span>
          <span role="columnheader">{t("truck.col.balance")}</span>
          <span role="columnheader">{t("truck.col.creditLimit")}</span>
          <span role="columnheader">{t("truck.col.payment")}</span>
          <span role="columnheader">{t("truck.col.nextDue")}</span>
          <span role="columnheader">{t("dealers.truck.col.status")}</span>
          <span aria-hidden="true" />
        </div>
        {rows.map((account) => (
          <div className="tv-truck-rowline" role="row" key={account.id}>
            <div className="tv-truck-cell-company" role="cell">
              {account.dealer_company_name || "—"}
            </div>
            <div role="cell">{account.agent_name || "—"}</div>
            <div role="cell">
              <Link
                to={`/truck-accounts/${account.id}`}
                style={{ color: "var(--accent)", fontWeight: 700 }}
              >
                {account.customer_name}
              </Link>
            </div>
            <div role="cell">
              <strong>{money(account.balance)}</strong>
            </div>
            <div role="cell">
              {account.credit_limit ? money(account.credit_limit) : "—"}
            </div>
            <div role="cell">
              {account.payment_amount
                ? `${money(account.payment_amount)} ${account.payment_cadence === "weekly" ? t("truck.cadenceWeekly") : t("truck.cadenceBiweekly")}`
                : "—"}
            </div>
            <div role="cell">
              {account.next_due_date && account.status === "active"
                ? displayDate(account.next_due_date)
                : "—"}
            </div>
            <div role="cell">{statusBadge(account, t)}</div>
            <div role="cell">
              <LinkButton to={`/truck-accounts/${account.id}`} size="sm" variant="secondary">
                {t("truck.openAccountBtn")}
              </LinkButton>
            </div>
          </div>
        ))}
      </div>
    );
  }

  // Header totals across the tabs the user owes on.
  const owedAccounts = theirs.filter((a) => a.status !== "closed");
  const totalOwed = owedAccounts.reduce(
    (sum, a) => sum + Number(a.balance),
    0,
  );
  const missedTotal = owedAccounts.reduce((s, a) => s + a.missed_payments, 0);
  const pastDueTotal = owedAccounts.reduce(
    (s, a) => s + Number(a.amount_past_due),
    0,
  );
  const attention = theirs.filter(
    (a) => a.missed_payments > 0 || a.status === "invited",
  );

  // "Your tabs at a glance" as a true list (truck page fixes,
  // 2026-11-06): ONE ROW PER AGENT the user owes — his total
  // across every open tab he holds, the next payment coming
  // due (the soonest scheduled one), and his plan. A row jumps
  // to the tab of the account its due columns describe (the
  // soonest-due account; the biggest balance when nothing is
  // scheduled). Plans: an account carrying a payment schedule
  // reads Weekly / Biweekly by its cadence; an account with no
  // schedule set is paid by hand — Manual. An agent whose
  // accounts disagree shows each plan he runs, joined. (The
  // plan vocabulary names Monthly too, but no cadence in the
  // system is monthly today — cadences are weekly/biweekly.)
  function planOf(account: TruckAccount): string {
    const scheduled =
      account.status === "active" &&
      account.payment_amount != null &&
      account.next_due_date != null;
    if (!scheduled) return t("truck.planManual");
    return account.payment_cadence === "weekly"
      ? t("truck.planWeekly")
      : t("truck.planBiweekly");
  }

  interface AgentGlance {
    key: string;
    name: string;
    companies: string[];
    total: number;
    dueAmount: string | null;
    dueDate: string | null;
    plans: string[];
    targetId: string;
  }

  const glance: AgentGlance[] = useMemo(() => {
    const groups = new Map<string, TruckAccount[]>();
    for (const account of theirs) {
      if (account.status === "closed") continue;
      const key =
        account.agent_kind === "platform" && account.dealer_user_id
          ? `platform:${account.dealer_user_id}`
          : account.private_agent_id
            ? `private:${account.private_agent_id}`
            : "records";
      const rows = groups.get(key) ?? [];
      rows.push(account);
      groups.set(key, rows);
    }
    const out: AgentGlance[] = [];
    for (const [key, rows] of groups) {
      const due = rows
        .filter(
          (a) =>
            a.status === "active" &&
            Number(a.balance) > 0 &&
            a.payment_amount != null &&
            a.next_due_date != null,
        )
        .sort((x, y) =>
          (x.next_due_date as string).localeCompare(
            y.next_due_date as string,
          ),
        )[0];
      const target =
        due ??
        [...rows].sort((x, y) => Number(y.balance) - Number(x.balance))[0];
      out.push({
        key,
        name:
          key === "records"
            ? t("truck.yourRecords")
            : rows[0].agent_name || t("truck.yourRecords"),
        companies: [
          ...new Set(
            rows
              .map((a) => a.dealer_company_name ?? "")
              .filter((n) => n !== ""),
          ),
        ],
        total: rows.reduce((s, a) => s + Number(a.balance), 0),
        dueAmount: due?.payment_amount ?? null,
        dueDate: due?.next_due_date ?? null,
        plans: [...new Set(rows.map(planOf))],
        targetId: target.id,
      });
    }
    return out.sort((x, y) => y.total - x.total || x.name.localeCompare(y.name));
  }, [theirs]);

  const tabs = [
    ...theirs.map((account) => ({
      id: `acct:${account.id}`,
      label: tabLabel(account, t),
      content: (
        <TruckAccountWorkbench
          key={account.id}
          accountId={account.id}
          onChanged={refresh}
        />
      ),
    })),
    ...(mine.length > 0
      ? [
          {
            id: "dealer-run",
            label: t("truck.factYouRun"),
            content: (
              <section className="tv-truck-section">
                <h2 style={{ margin: 0, fontSize: "1.05rem" }}>
                  {t("truck.accountsYouRunTitle")}
                </h2>
                <p className="tv-truck-note">{t("truck.accountsYouRunNote")}</p>
                {renderDealerTable(mine)}
              </section>
            ),
          },
        ]
      : []),
  ];
  const selectedTab =
    tabs.find((t) => t.id === activeTab)?.id ??
    tabs[0]?.id ??
    "";

  // The kit header's standing facts (Lane 8): the total owed
  // across the tabs the user owes on — the glance panel's own
  // headline number — plus, for dealer seats, how many accounts
  // they run. Unknown until the accounts read lands: pass
  // undefined, never a placeholder.
  const facts: SectionPageFact[] | undefined =
    accounts === null
      ? undefined
      : [
          ...(theirs.length > 0
            ? [
                {
                  label: t("truck.factTotalOwed"),
                  value: money(String(totalOwed)),
                },
              ]
            : []),
          ...(mine.length > 0
            ? [{ label: t("truck.factYouRun"), value: String(mine.length) }]
            : []),
        ];

  // The two open-account commands, folded into the header's
  // Actions menu (Lane 8): same gates as the loose buttons they
  // replace — "Open for a customer" exists only for a seat that
  // can actually issue; the self-kept door is every user's.
  const headerActions = (
    <SettingsActionsMenu
      ariaLabel={t("nav.truck-accounts")}
      buttonLabel={t("inventory.actions")}
      entries={[
        ...(canIssue
          ? [
              {
                key: "open-customer",
                label: t("truck.openForCustomer"),
                run: () => setCreating(true),
              },
            ]
          : []),
        {
          key: "open-self",
          label: t("truck.openSelfKept"),
          run: () => setSelfOpen(true),
        },
      ]}
    />
  );

  // The attention strip rides INSIDE the header panel, in
  // the header's body row under the title/facts row (owner,
  // 2026-11-10: merged into the header bar; Lane 8 had it in
  // the status-strip seat below the panel). Its root carries
  // the kit's `.tv-secpage-body` class, so when there's
  // nothing to report the header shows no trace of it. The
  // chips and their tab jumps are unchanged.
  const headerBody =
    accounts !== null && accounts.length > 0 && attention.length > 0 ? (
      <div className="tv-secpage-body">
        <div className="tv-truck-strip" role="group" aria-label={t("truck.needsAttention")}>
          <span className="tv-truck-strip-label">{t("truck.needsAttention")}</span>
          {attention.map((account) => (
            <Button
              key={account.id}
              size="sm"
              variant="secondary"
              onClick={() => setActiveTab(`acct:${account.id}`)}
            >
              {account.dealer_company_name ?? t("truck.dealerFallback")} ·{" "}
              {account.agent_name || t("truck.yourRecords")} —{" "}
              {account.status === "invited"
                ? t("truck.attentionInvite")
                : t("truck.attentionMissed").replace(
                    "{count}",
                    String(account.missed_payments),
                  )}
            </Button>
          ))}
        </div>
      </div>
    ) : undefined;

  return (
    <RequireAuth>
      <div className="tv-stack">
        <SectionPageHeader
          thumb={<ArtIcon name="truck" size={96} />}
          title={t("nav.truck-accounts")}
          subtitle={t("truck.subtitle")}
          facts={facts}
          actions={headerActions}
          body={headerBody}
        />

        {error && <Alert tone="danger">{error}</Alert>}

        {accounts === null ? (
          <p className="tv-truck-loading">
            <Spinner size="sm" /> {t("shell.loading")}
          </p>
        ) : accounts.length === 0 ? (
          <EmptyState
            title={t("truck.emptyTitle")}
            description={t("truck.emptyBody")}
            action={
              <Button onClick={() => setSelfOpen(true)}>
                {t("truck.openSelfKept")}
              </Button>
            }
          />
        ) : (
          <>
            {glance.length > 0 && (
              <div className="tv-truck-glance-wrap">
              <Panel title={t("truck.glanceTitle")} variant="accent-edge">
                <p className="tv-truck-glance-total">
                  {t("dealers.truck.totalOwed")}{" "}
                  <strong>{money(String(totalOwed))}</strong>
                  {missedTotal > 0 && (
                    <>
                      {t("truck.glanceMissed")
                        .replace("{missed}", String(missedTotal))
                        .replace("{amount}", money(String(pastDueTotal)))}
                    </>
                  )}
                </p>
                <div className="tv-truck-glance">
                  <div className="tv-truck-glance-thead" aria-hidden="true">
                    <span>{t("dealers.truck.col.agent")}</span>
                    <span>{t("truck.glanceColTotalOwed")}</span>
                    <span>{t("truck.glanceColNextPayment")}</span>
                    <span>{t("truck.glanceColDueDate")}</span>
                    <span>{t("truck.glanceColPlan")}</span>
                  </div>
                  {glance.map((row) => (
                    <button
                      key={row.key}
                      type="button"
                      className="tv-truck-glance-row"
                      onClick={() => setActiveTab(`acct:${row.targetId}`)}
                      aria-label={t("truck.glanceRowAria").replace("{name}", row.name).replace("{amount}", money(String(row.total)))}
                    >
                      <span className="tv-truck-glance-agent">
                        {row.name}
                        {row.companies.length > 1 && (
                          <span className="tv-truck-glance-companies">
                            {row.companies.join(" · ")}
                          </span>
                        )}
                      </span>
                      <span className="tv-truck-glance-owed">
                        {money(String(row.total))}
                      </span>
                      <span>
                        {row.dueAmount != null ? money(row.dueAmount) : "—"}
                      </span>
                      <span>
                        {row.dueDate ? displayDate(row.dueDate) : "—"}
                      </span>
                      <span>{row.plans.join(" · ")}</span>
                    </button>
                  ))}
                </div>
              </Panel>
              </div>
            )}

            <Tabs
              tabs={tabs}
              activeId={selectedTab}
              onChange={setActiveTab}
            />
          </>
        )}
      </div>

      <Modal
        open={selfOpen}
        onClose={() => setSelfOpen(false)}
        title={t("truck.selfModalTitle")}
      >
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <p className="tv-truck-note">{t("truck.selfIntro")}</p>
          <FormField label={t("truck.fieldDealer")} htmlFor="self-company">
            <Select
              id="self-company"
              value={selfCompanyId}
              onChange={(e) => {
                setSelfCompanyId(e.target.value);
                setPendingAgent("");
              }}
            >
              <option value="">{t("truck.chooseDealer")}</option>
              {(selfCompanies ?? []).map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.company_name}
                </option>
              ))}
            </Select>
          </FormField>
          {selfCompanies !== null && selfCompanies.length === 0 ? (
            <p className="tv-truck-note">{t("truck.noAgentsNote")}</p>
          ) : (
            <FormField
              label={t("dealers.truck.col.agent")}
              htmlFor="self-agent"
              hint={t("truck.agentHint")}
            >
              <Select
                id="self-agent"
                value={selfTarget}
                onChange={(e) => setSelfTarget(e.target.value)}
              >
                <option value="">{t("truck.chooseAgent")}</option>
                {(selfTargets ?? []).map((target) => (
                  <option
                    key={`${target.kind}:${target.private_agent_id ?? target.agent_user_id}`}
                    value={`${target.kind}:${target.private_agent_id ?? target.agent_user_id}`}
                    disabled={target.has_open_account}
                  >
                    {target.name}
                    {target.kind === "private" ? t("truck.agentYourRecord") : ""}
                    {target.is_preferred ? t("truck.agentPreferred") : ""}
                    {target.has_open_account ? t("truck.agentTabOpen") : ""}
                  </option>
                ))}
              </Select>
            </FormField>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <FormField
              label={t("dealers.truck.col.start")}
              htmlFor="self-balance"
              hint={t("truck.openingBalanceHint")}
            >
              <TextInput
                id="self-balance"
                inputMode="decimal"
                value={selfBalance}
                onChange={(e) => setSelfBalance(e.target.value)}
                placeholder="0.00"
              />
            </FormField>
            <FormField label={t("truck.openingNoteLabel")} htmlFor="self-opening-note">
              <TextInput
                id="self-opening-note"
                value={selfNote}
                onChange={(e) => setSelfNote(e.target.value)}
                placeholder={t("dealers.truck.col.start")}
              />
            </FormField>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <FormField label={t("truck.paymentCadence")} htmlFor="self-cadence">
              <Select
                id="self-cadence"
                value={selfCadence}
                onChange={(e) => setSelfCadence(e.target.value)}
              >
                <option value="weekly">{t("truck.cadenceWeekly")}</option>
                <option value="biweekly">{t("truck.cadenceBiweekly")}</option>
              </Select>
            </FormField>
            <FormField label={t("truck.paymentAmount")} htmlFor="self-amount">
              <TextInput
                id="self-amount"
                inputMode="decimal"
                value={selfAmount}
                onChange={(e) => setSelfAmount(e.target.value)}
                placeholder="50.00"
              />
            </FormField>
          </div>
          <FormField
            label={t("truck.firstDueOptional")}
            htmlFor="self-due"
            hint={t("truck.selfDueHint")}
          >
            <DatePicker
              id="self-due"
              value={selfDue}
              onChange={setSelfDue}
              clearable
            />
          </FormField>
          <FormField
            label={t("truck.howYouPay")}
            htmlFor="self-mode"
            hint={t("truck.selfModeHint")}
          >
            <Select
              id="self-mode"
              value={selfMode}
              onChange={(e) => setSelfMode(e.target.value)}
            >
              <option value="manual">{t("truck.modeManual")}</option>
              <option value="automatic">{t("truck.modeAutomaticSelf")}</option>
            </Select>
          </FormField>
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setSelfOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={selfSaving}
              onClick={() => void createSelf()}
              disabled={!selfCompanyId || !selfTarget}
            >
              {t("truck.openTheAccount")}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t("truck.createModalTitle")}
      >
        <div style={{ display: "grid", gap: "0.75rem" }}>
          <FormField
            label={t("truck.fieldCustomer")}
            htmlFor="truck-mode"
            hint={t("truck.customerHint")}
          >
            <Select
              id="truck-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as "number" | "email")}
            >
              <option value="number">{t("truck.modeAccountNumber")}</option>
              <option value="email">{t("truck.modeEmailInvite")}</option>
            </Select>
          </FormField>
          {mode === "number" ? (
            <FormField label={t("truck.customerAccountNumber")} htmlFor="truck-number">
              <TextInput
                id="truck-number"
                value={accountNumber}
                onChange={(e) => setAccountNumber(e.target.value)}
                placeholder="TV-MS-000159"
              />
            </FormField>
          ) : (
            <FormField label={t("truck.customerEmail")} htmlFor="truck-email">
              <TextInput
                id="truck-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="them@example.com"
              />
            </FormField>
          )}
          <FormField
            label={t("truck.fieldCompanyQ")}
            htmlFor="truck-company"
            hint={t("truck.companyHint")}
          >
            <Select
              id="truck-company"
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
            >
              <option value="">{t("truck.chooseCompany")}</option>
              {(companies ?? []).map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.company_name}
                </option>
              ))}
            </Select>
          </FormField>
          {companies !== null && companies.length === 0 ? (
            <p className="tv-truck-note">{t("truck.notVerifiedNote")}</p>
          ) : null}
          <FormField
            label={t("truck.creditLimitOptional")}
            htmlFor="truck-credit"
            hint={t("truck.creditLimitHint")}
          >
            <TextInput
              id="truck-credit"
              inputMode="decimal"
              value={creditLimit}
              onChange={(e) => setCreditLimit(e.target.value)}
              placeholder="e.g. 2000"
            />
          </FormField>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <FormField label={t("truck.paymentCadence")} htmlFor="truck-cadence">
              <Select
                id="truck-cadence"
                value={cadence}
                onChange={(e) => setCadence(e.target.value)}
              >
                <option value="weekly">{t("truck.cadenceWeekly")}</option>
                <option value="biweekly">{t("truck.cadenceBiweekly")}</option>
              </Select>
            </FormField>
            <FormField label={t("truck.paymentAmount")} htmlFor="truck-amount">
              <TextInput
                id="truck-amount"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="10.00"
              />
            </FormField>
          </div>
          <FormField
            label={t("truck.firstDueOptional")}
            htmlFor="truck-due"
            hint={t("truck.createDueHint")}
          >
            <DatePicker
              id="truck-due"
              value={dueDate}
              onChange={setDueDate}
              clearable
            />
          </FormField>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
            {t("truck.agreementNote")}
          </p>
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setCreating(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={saving}
              onClick={() => void create()}
              disabled={
                (mode === "number" && !accountNumber.trim()) ||
                (mode === "email" && !email.trim()) ||
                !companyId
              }
            >
              {t("truck.openAccountBtn")}
            </Button>
          </div>
        </div>
      </Modal>
    </RequireAuth>
  );
}
