import { useEffect, useState } from "react";
import {
  Button,
  DatePicker,
  FormField,
  Modal,
  Select,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import {
  createAccount,
  getIssuableCompanies,
  getSelfCompanies,
  getSelfTargets,
  openSelfAccount,
  reopenAccount,
} from "./api";
import type { IssuableCompany, SelfOpenTarget, TruckAccount } from "./types";

/**
 * The two open-account flows, lifted out of the retired
 * standalone Truck Accounts page (owner order, 2026-11-17:
 * the page goes away; everything it held lives under the
 * agent window). The modals are unchanged from the page —
 * same fields, same gates, same API calls — only their home
 * moved: the Dealers page's glance panel, the company panel's
 * Truck section, and the agent record all host them now.
 */

/** The reopen-or-new question (owner rule, 2026-11-17): when
 *  the pair's only account is closed, an open stops with the
 *  409 and the user picks — reopen the old account (same
 *  account, same number, history kept) or open a new one. */
type ClosedPrompt = {
  accountId: string;
  accountNumber: string | null;
  message: string;
};

function closedPromptFrom(err: unknown): ClosedPrompt | null {
  if (
    err instanceof ApiError &&
    err.code === "closed_account_exists" &&
    err.detail
  ) {
    return {
      accountId: String(err.detail.account_id ?? ""),
      accountNumber:
        typeof err.detail.account_number === "string"
          ? err.detail.account_number
          : null,
      message: err.message,
    };
  }
  return null;
}

function ClosedAccountPrompt({
  prompt,
  busy,
  onReopen,
  onNew,
}: {
  prompt: ClosedPrompt;
  busy: boolean;
  onReopen: () => void;
  onNew: () => void;
}) {
  const t = useT();
  return (
    <div
      style={{
        display: "grid",
        gap: "0.6rem",
        border: "1px solid var(--edge-strong)",
        borderRadius: "var(--radius)",
        padding: "0.85rem",
      }}
    >
      <p className="tv-truck-note" style={{ margin: 0 }}>
        {prompt.message}
      </p>
      {prompt.accountNumber && (
        <p className="tv-truck-note" style={{ margin: 0 }}>
          {t("truck.closedAccountLine").replace(
            "{number}",
            prompt.accountNumber,
          )}
        </p>
      )}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Button loading={busy} onClick={onReopen}>
          {t("truck.reopenAction")}
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onNew}>
          {t("truck.openNewAction")}
        </Button>
      </div>
    </div>
  );
}

export function SelfOpenModal({
  open,
  onClose,
  onOpened,
  initialCompanyId,
  initialAgentKey,
}: {
  open: boolean;
  onClose: () => void;
  /** Fired with the created account after a successful open. */
  onOpened?: (account: TruckAccount) => void;
  initialCompanyId?: string;
  /** "<kind>:<ref>" — preselects that agent when he has no
   *  open account yet (the agent record's Open door). */
  initialAgentKey?: string;
}) {
  const { toast } = useToast();
  const t = useT();
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
  const [closedPrompt, setClosedPrompt] = useState<ClosedPrompt | null>(null);
  const [pendingAgent, setPendingAgent] = useState("");

  // Landing instruction: preselect the company/agent the
  // door named, once per opening.
  useEffect(() => {
    if (!open) return;
    if (initialCompanyId) setSelfCompanyId(initialCompanyId);
    if (initialAgentKey) setPendingAgent(initialAgentKey);
  }, [open, initialCompanyId, initialAgentKey]);

  useEffect(() => {
    if (!open) return;
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
              (row) =>
                `${row.kind}:${row.private_agent_id ?? row.agent_user_id}` ===
                pendingAgent,
            )
          : undefined;
        const firstFree = rows.find((row) => !row.has_open_account);
        const pick = wanted && !wanted.has_open_account ? wanted : firstFree;
        setSelfTarget(
          pick ? `${pick.kind}:${pick.private_agent_id ?? pick.agent_user_id}` : "",
        );
      })
      .catch(() => setSelfTargets([]));
  }, [open, selfCompanies, selfCompanyId, pendingAgent]);

  async function createSelf(allowNewOverClosed = false) {
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
        allow_new_over_closed: allowNewOverClosed || undefined,
      });
      toast(t("truck.toastSelfOpened"));
      setSelfBalance("");
      setSelfNote("");
      setSelfAmount("");
      setSelfDue("");
      setClosedPrompt(null);
      onClose();
      onOpened?.(account);
    } catch (err) {
      const prompt = closedPromptFrom(err);
      if (prompt) {
        setClosedPrompt(prompt);
      } else {
        toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
      }
    } finally {
      setSelfSaving(false);
    }
  }

  async function reopenClosed() {
    if (!closedPrompt) return;
    setSelfSaving(true);
    try {
      const account = await reopenAccount(closedPrompt.accountId);
      toast(t("truck.toastReopened"));
      setClosedPrompt(null);
      onClose();
      onOpened?.(account);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
    } finally {
      setSelfSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
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
        {closedPrompt && (
          <ClosedAccountPrompt
            prompt={closedPrompt}
            busy={selfSaving}
            onReopen={() => void reopenClosed()}
            onNew={() => {
              setClosedPrompt(null);
              void createSelf(true);
            }}
          />
        )}
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose}>
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
  );
}

export function IssueAccountModal({
  open,
  onClose,
  onOpened,
  initialCompanyId,
}: {
  open: boolean;
  onClose: () => void;
  onOpened?: (account: TruckAccount) => void;
  initialCompanyId?: string;
}) {
  const { toast } = useToast();
  const t = useT();
  const [mode, setMode] = useState<"number" | "email">("number");
  const [accountNumber, setAccountNumber] = useState("");
  const [email, setEmail] = useState("");
  const [cadence, setCadence] = useState("weekly");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [closedPrompt, setClosedPrompt] = useState<ClosedPrompt | null>(null);
  const [companies, setCompanies] = useState<IssuableCompany[] | null>(null);
  const [companyId, setCompanyId] = useState("");
  const [creditLimit, setCreditLimit] = useState("");

  useEffect(() => {
    if (!open || companies !== null) return;
    getIssuableCompanies()
      .then((rows) => {
        setCompanies(rows);
        if (initialCompanyId && rows.some((r) => r.company_id === initialCompanyId)) {
          setCompanyId(initialCompanyId);
        } else if (rows.length === 1) {
          setCompanyId(rows[0].company_id);
        }
      })
      .catch(() => setCompanies([]));
  }, [open, companies, initialCompanyId]);

  async function create(allowNewOverClosed = false) {
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
        allow_new_over_closed: allowNewOverClosed || undefined,
      });
      toast(
        account.customer_user_id
          ? t("truck.toastOpenedInbox")
          : t("truck.toastInviteSaved"),
      );
      setAccountNumber("");
      setEmail("");
      setAmount("");
      setDueDate("");
      setCreditLimit("");
      setClosedPrompt(null);
      onClose();
      onOpened?.(account);
    } catch (err) {
      const prompt = closedPromptFrom(err);
      if (prompt) {
        setClosedPrompt(prompt);
      } else {
        toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
      }
    } finally {
      setSaving(false);
    }
  }

  async function reopenClosed() {
    if (!closedPrompt) return;
    setSaving(true);
    try {
      const account = await reopenAccount(closedPrompt.accountId);
      toast(t("truck.toastReopened"));
      setClosedPrompt(null);
      onClose();
      onOpened?.(account);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("truck.toastOpenFailed"), { tone: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
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
        {closedPrompt && (
          <ClosedAccountPrompt
            prompt={closedPrompt}
            busy={saving}
            onReopen={() => void reopenClosed()}
            onNew={() => {
              setClosedPrompt(null);
              void create(true);
            }}
          />
        )}
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose}>
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
  );
}
