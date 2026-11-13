import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  DatePicker,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { todayLocalIso } from "../../lib/format";
import { displayDate, money } from "../inventory/format";
import {
  acceptAccount,
  addEntry,
  closeAccount,
  decidePaymentRequest,
  declineAccount,
  downloadStatement,
  getAccount,
  requestPayment,
  setPaymentMode,
  transferAccount,
  updateSchedule,
} from "./api";
import type { TruckAccountDetail, TruckEntry } from "./types";
import "./truck.css";

/**
 * The truck-account workbench (Stage 2, 2026-11-05): everything
 * one account holds — balance, the agreement gate, payment
 * requests, the entry form, the ledger as a TRUE LIST with a
 * running balance, the schedule with its missed state, the
 * payment-mode choice, statement downloads, transfer, close.
 *
 * It renders in two homes: the standalone account page (a slim
 * wrapper) and one tab of the Truck Accounts overview — the
 * same component, so the two can never drift. Charges are the
 * dealer's pen on an agent-kept tab and the customer's pen on
 * a tab he keeps himself; every increase is explained (a note,
 * or the tool the charge links to — item-linked charges render
 * as a link through to the item).
 */

const ENTRY_LABEL_KEYS: Record<TruckEntry["kind"], string> = {
  charge: "truck.wb.kindCharge",
  payment: "truck.wb.kindPayment",
  adjustment: "truck.wb.kindAdjustment",
};

/** The current agreement version rides in the preview's first
 *  line ("... (version YYYY-MM-DD.N)") — acceptance must name
 *  it, so parse it back out rather than hardcoding it here. */
function versionFromPreview(preview: string | null): string {
  if (!preview) return "";
  const match = preview.match(/version ([0-9A-Za-z.-]+)\)/);
  return match ? match[1] : "";
}

/** Where a ledger entry's item link lands: sets ride the tool
 *  page; batteries have their own route. */
export function itemPath(entry: TruckEntry): string | null {
  if (!entry.item_link_id) return null;
  return entry.item_kind === "battery"
    ? `/inventory/batteries/${entry.item_link_id}`
    : `/inventory/${entry.item_link_id}`;
}

async function saveBlob(blob: Blob, filename: string): Promise<void> {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function TruckAccountWorkbench({
  accountId,
  onChanged,
}: {
  accountId: string;
  /** The overview page refreshes its tabs/totals after a change. */
  onChanged?: () => void;
}) {
  const { toast } = useToast();
  const t = useT();
  const [detail, setDetail] = useState<TruckAccountDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [agreed, setAgreed] = useState(false);
  // Entry form.
  const [kind, setKind] = useState("payment");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  /* A new ledger entry starts on today (owner's date rule,
   * 2026-11-04); clearable back to null, as the field allowed. */
  const [entryDate, setEntryDate] = useState(() => todayLocalIso());
  // Schedule form.
  const [cadence, setCadence] = useState("weekly");
  const [payAmount, setPayAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  // Transfer (customer): "platform:<user id>" | "private:<record id>".
  const [transferTarget, setTransferTarget] = useState("");
  // Stage 2: payment request form (agent seat) + decline note.
  const [reqAmount, setReqAmount] = useState("");
  const [reqNote, setReqNote] = useState("");
  const [declineNote, setDeclineNote] = useState("");
  // Stage 2: the customer's stored payment-mode choice.
  const [modeChoice, setModeChoice] = useState("manual");

  const refresh = useCallback(() => {
    getAccount(accountId)
      .then((d) => {
        setDetail(d);
        setCadence(d.account.payment_cadence);
        setPayAmount(d.account.payment_amount ?? "");
        setDueDate(d.account.next_due_date ?? "");
        setModeChoice(d.account.payment_mode);
      })
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : t("truck.wb.loadFailed"),
        ),
      );
  }, [accountId]);

  useEffect(refresh, [refresh]);

  if (error) {
    return <Alert tone="danger">{error}</Alert>;
  }
  if (!detail) {
    return (
      <p className="tv-truck-loading">
        <Spinner size="sm" /> {t("shell.loading")}
      </p>
    );
  }

  const { account, entries, schedule } = detail;
  const isDealer = account.my_role === "dealer";
  const otherName = isDealer
    ? account.customer_name
    : account.dealer_name ?? t("truck.dealerFallback");
  // The plain-language header (truck page fixes, 2026-11-06):
  // whose account, with whom — the agent as the customer reads
  // his name (the agent record's name, not the login name),
  // falling back to the company when the tab has no agent name
  // of its own.
  const agentLabel =
    account.agent_name && account.agent_name !== "Dealer"
      ? account.agent_name
      : (account.dealer_company_name ?? t("truck.wb.yourDealer"));
  const headerName = isDealer ? account.customer_name : agentLabel;
  const closed = account.status === "closed";
  const invited = account.status === "invited";
  const agreementVersion = versionFromPreview(detail.agreement_preview);
  const pendingRequest = detail.payment_requests.find(
    (r) => r.status === "pending",
  );
  const decidedRequests = detail.payment_requests.filter(
    (r) => r.status !== "pending",
  );
  // On a customer-kept tab the linked agent asks instead of
  // charging; on an agent-kept tab there are no requests.
  const canRequest =
    isDealer && account.ledger_keeper === "customer" && !pendingRequest;

  async function run(action: () => Promise<unknown>, okMessage: string) {
    setBusy(true);
    try {
      await action();
      toast(okMessage);
      refresh();
      onChanged?.();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("truck.wb.genericFailed"),
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitEntry() {
    if (amount === "") return;
    await run(
      () =>
        addEntry(accountId, {
          kind,
          amount,
          note: note.trim(),
          item_link_id: null,
          entry_date: entryDate || null,
        }),
      kind === "payment"
        ? t("truck.wb.toastPaymentRecorded")
        : t("truck.wb.toastEntryRecorded"),
    );
    setAmount("");
    setNote("");
    setEntryDate(todayLocalIso());
  }

  async function submitRequest() {
    if (reqAmount === "") return;
    await run(
      () =>
        requestPayment(accountId, {
          amount: reqAmount,
          note: reqNote.trim(),
        }),
      t("truck.wb.toastPaymentRequested"),
    );
    setReqAmount("");
    setReqNote("");
  }

  async function download(fmt: "pdf" | "csv") {
    try {
      const blob = await downloadStatement(accountId, fmt);
      await saveBlob(blob, `truck-statement-${accountId}.${fmt}`);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("truck.wb.toastStatementFailed"),
        { tone: "danger" },
      );
    }
  }

  // The ledger's running balance, oldest first; rows render
  // newest first with the balance as it stood after each entry.
  let runningCents = 0;
  const rows = entries.map((entry) => {
    runningCents += Math.round(Number(entry.amount) * 100);
    return { entry, balanceAfter: runningCents / 100 };
  });

  // Who holds the charge pen: the dealer on an agent-kept tab,
  // the customer on a tab he keeps himself (the API refuses a
  // dealer charge on a customer-kept tab — his money path
  // there is a payment request).
  const canCharge = isDealer
    ? account.ledger_keeper === "agent"
    : account.customer_maintained;

  // A manual charge with no note is refused by the API (every
  // increase is explained) — the form says so up front instead
  // of letting the submit fail.
  const chargeNeedsNote = kind === "charge" && note.trim() === "";

  return (
    <div className="tv-truck-stack" style={{ gap: "var(--spacing)" }}>
      <div>
        <p className="tv-truck-title">
          {t("truck.wb.titleWith").replace("{name}", headerName)}
          {invited && (
            <Badge tone="warning">{t("dealers.truck.statusInvited")}</Badge>
          )}
          {closed && (
            <Badge tone="neutral">{t("dealers.truck.statusClosed")}</Badge>
          )}
          {schedule.missed_payments > 0 && (
            <Badge tone="danger">
              {t("truck.attentionMissed").replace(
                "{count}",
                String(schedule.missed_payments),
              )}
            </Badge>
          )}
        </p>
        <p className="tv-truck-sub">
          {isDealer ? (
            <>{t("truck.wb.customerOwes").replace("{name}", account.customer_name)}</>
          ) : (
            <>{t("truck.wb.youOwe")}</>
          )}
          <strong>{money(account.balance)}</strong>
          {t("truck.wb.onThisAccount")}
          {account.dealer_company_name && (
            <> {account.dealer_company_name}.</>
          )}
          {isDealer && account.customer_account_number && (
            <>{t("truck.wb.customerLabel").replace("{number}", account.customer_account_number)}</>
          )}
          {!isDealer && account.dealer_account_number && (
            <>{t("truck.wb.dealerLabel").replace("{number}", account.dealer_account_number)}</>
          )}
          {account.ledger_keeper === "customer" && (
            <>
              {" "}
              {isDealer
                ? t("truck.wb.keeperCustomerDealer")
                : t("truck.wb.keeperCustomerSelf")}
            </>
          )}
          {account.customer_maintained && !isDealer && account.ledger_keeper !== "customer" && (
            <>
              {" "}
              {t("truck.wb.keeperOwnRecord")}
            </>
          )}
        </p>
      </div>

      <Panel title={t("truck.wb.balanceTitle")} variant="accent-edge">
        <div className="tv-truck-headline">
          <p className="tv-truck-balance">{money(account.balance)}</p>
          <p className="tv-truck-muted">
            {account.payment_amount
              ? `${money(account.payment_amount)} ${account.payment_cadence === "weekly" ? t("truck.cadenceWeekly") : t("truck.cadenceBiweekly")}`
              : t("truck.wb.noSchedule")}
            {account.next_due_date && (
              <>{t("truck.wb.nextDueSuffix").replace("{date}", displayDate(account.next_due_date))}</>
            )}
          </p>
          {schedule.missed_payments > 0 && (
            <p className="tv-truck-missed">
              {(schedule.missed_payments === 1
                ? t("truck.wb.missedLineOne")
                : t("truck.wb.missedLine").replace(
                    "{count}",
                    String(schedule.missed_payments),
                  )
              ).replace("{amount}", money(schedule.amount_past_due))}
            </p>
          )}
          {account.credit_limit && (
            <p className="tv-truck-muted">
              {t("truck.wb.creditLine").replace("{amount}", money(account.credit_limit))}
              {account.credit_available && (
                <>{t("truck.wb.creditAvailable").replace("{amount}", money(account.credit_available))}</>
              )}
            </p>
          )}
          <p className="tv-truck-muted">
            {t("truck.wb.highestLine").replace("{amount}", money(account.highest_balance))}
          </p>
          {!isDealer && (
            <p className="tv-truck-muted">
              {t("truck.wb.paymentModeLabel")}
              {account.payment_mode === "automatic"
                ? t("truck.wb.modeAutomaticWord")
                : t("truck.wb.modeManualWord")}
            </p>
          )}
          {account.pay_online_available && account.status === "active" && !isDealer && (
            <Button
              onClick={() =>
                toast(t("truck.wb.payOnlineToast"), { tone: "info" })
              }
            >
              {t("truck.wb.payOnline")}
            </Button>
          )}
        </div>
      </Panel>

      {invited && !isDealer && detail.agreement_preview && (
        <Panel title={t("truck.wb.agreementPanelTitle")} variant="accent-edge">
          <div className="tv-truck-stack">
            <pre className="tv-truck-agreement">{detail.agreement_preview}</pre>
            <Checkbox
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              label={t("truck.wb.agreementCheckbox")}
            />
            <div className="tv-truck-actions" style={{ justifyContent: "flex-start" }}>
              <Button
                loading={busy}
                disabled={!agreed || !agreementVersion}
                onClick={() =>
                  void run(
                    () => acceptAccount(accountId, agreementVersion),
                    t("truck.wb.toastAccepted"),
                  )
                }
              >
                {t("truck.wb.acceptOpen")}
              </Button>
              <Button
                variant="ghost"
                loading={busy}
                onClick={() => {
                  if (window.confirm(t("truck.wb.declineConfirm"))) {
                    void run(() => declineAccount(accountId), t("truck.wb.toastDeclined"));
                  }
                }}
              >
                {t("truck.wb.decline")}
              </Button>
            </div>
          </div>
        </Panel>
      )}

      {invited && isDealer && (
        <Alert tone="info">
          {t("truck.wb.waitingDealer").replace("{name}", otherName)}
        </Alert>
      )}

      {account.status === "active" &&
        (pendingRequest || canRequest || decidedRequests.length > 0) && (
          <Panel title={t("truck.wb.requestsTitle")}>
            <div className="tv-truck-stack">
              {pendingRequest && (
                <div className="tv-truck-stack">
                  <p className="tv-truck-note">
                    <strong>
                      {pendingRequest.requested_by_name ?? t("truck.wb.requestedByFallback")}
                    </strong>
                    {t("truck.wb.requestLine")}
                    <strong>{money(pendingRequest.amount)}</strong>
                    {pendingRequest.note && <> — “{pendingRequest.note}”</>}
                    {" · "}
                    {displayDate(pendingRequest.created_at.slice(0, 10))}
                  </p>
                  {!isDealer && (
                    <>
                      <FormField
                        label={t("truck.wb.declineNoteLabel")}
                        htmlFor="req-decline-note"
                      >
                        <TextInput
                          id="req-decline-note"
                          value={declineNote}
                          onChange={(e) => setDeclineNote(e.target.value)}
                          placeholder={t("truck.wb.declineNotePlaceholder")}
                        />
                      </FormField>
                      <div className="tv-truck-actions" style={{ justifyContent: "flex-start" }}>
                        <Button
                          loading={busy}
                          onClick={() =>
                            void run(
                              () =>
                                decidePaymentRequest(
                                  accountId,
                                  pendingRequest.id,
                                  "approve",
                                  declineNote.trim(),
                                ),
                              t("truck.wb.toastRequestApproved"),
                            )
                          }
                        >
                          {t("truck.wb.approveRecord")}
                        </Button>
                        <Button
                          variant="ghost"
                          loading={busy}
                          onClick={() =>
                            void run(
                              () =>
                                decidePaymentRequest(
                                  accountId,
                                  pendingRequest.id,
                                  "decline",
                                  declineNote.trim(),
                                ),
                              t("truck.wb.toastRequestDeclined"),
                            )
                          }
                        >
                          {t("truck.wb.decline")}
                        </Button>
                    </div>
                    </>
                  )}
                  {isDealer && (
                    <p className="tv-truck-note">{t("truck.wb.waitingCustomer")}</p>
                  )}
                </div>
              )}
              {canRequest && (
                <div className="tv-truck-stack">
                  <p className="tv-truck-note">{t("truck.wb.canRequestNote")}</p>
                  <div className="tv-truck-form-grid">
                    <FormField label={t("truck.wb.amountLabel")} htmlFor="req-amount">
                      <TextInput
                        id="req-amount"
                        inputMode="decimal"
                        value={reqAmount}
                        onChange={(e) => setReqAmount(e.target.value)}
                        placeholder="50.00"
                      />
                    </FormField>
                    <FormField label={t("truck.wb.noteOptional")} htmlFor="req-note">
                      <TextInput
                        id="req-note"
                        value={reqNote}
                        onChange={(e) => setReqNote(e.target.value)}
                        placeholder={t("truck.wb.reqNotePlaceholder")}
                      />
                    </FormField>
                  </div>
                  <div>
                    <Button
                      loading={busy}
                      disabled={reqAmount === ""}
                      onClick={() => void submitRequest()}
                    >
                      {t("truck.wb.requestPaymentBtn")}
                    </Button>
                  </div>
                </div>
              )}
              {decidedRequests.map((request) => (
                <p className="tv-truck-note" key={request.id}>
                  {request.status === "approved"
                    ? t("truck.wb.requestApprovedMark")
                    : t("truck.wb.requestDeclinedMark")}
                  {" · "}
                  {money(request.amount)}
                  {t("truck.wb.requestedBy").replace(
                    "{name}",
                    request.requested_by_name ?? t("truck.wb.theAgent"),
                  )}
                  {request.decision_note && <> — “{request.decision_note}”</>}
                  {request.decided_at && (
                    <> · {displayDate(request.decided_at.slice(0, 10))}</>
                  )}
                </p>
              ))}
            </div>
          </Panel>
        )}

      {account.status === "active" && (
        <Panel title={t("truck.wb.recordTitle")}>
          <div className="tv-truck-stack">
            <div className="tv-truck-form-grid">
              <FormField label={t("truck.wb.kindLabel")} htmlFor="entry-kind">
                <Select
                  id="entry-kind"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  {canCharge && (
                    <option value="charge">{t("truck.wb.kindCharge")}</option>
                  )}
                  <option value="payment">{t("truck.wb.kindPayment")}</option>
                  <option value="adjustment">{t("truck.wb.kindAdjustment")}</option>
                </Select>
              </FormField>
              <FormField
                label={t("truck.wb.amountLabel")}
                htmlFor="entry-amount"
                hint={
                  kind === "adjustment" ? t("truck.wb.adjustmentHint") : undefined
                }
              >
                <TextInput
                  id="entry-amount"
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="0.00"
                />
              </FormField>
              <FormField label={t("truck.wb.dateLabel")} htmlFor="entry-date">
                <DatePicker
                  id="entry-date"
                  value={entryDate}
                  onChange={setEntryDate}
                  clearable
                />
              </FormField>
            </div>
            <FormField
              label={t("truck.wb.noteLabel")}
              htmlFor="entry-note"
              hint={
                kind === "charge"
                  ? t("truck.wb.chargeNoteHint")
                  : t("truck.wb.paymentNoteHint")
              }
            >
              <TextInput
                id="entry-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={
                  kind === "charge"
                    ? t("truck.wb.chargeNotePlaceholder")
                    : t("truck.wb.paymentNotePlaceholder")
                }
              />
            </FormField>
            <div>
              <Button
                loading={busy}
                onClick={() => void submitEntry()}
                disabled={amount === "" || chargeNeedsNote}
              >
                {t("truck.wb.recordBtn").replace(
                  "{kind}",
                  t(ENTRY_LABEL_KEYS[kind as TruckEntry["kind"]] as never).toLowerCase(),
                )}
              </Button>
            </div>
            <p className="tv-truck-note">{t("truck.wb.entriesNeverNote")}</p>
          </div>
        </Panel>
      )}

      <Panel title={t("truck.wb.ledgerTitle").replace("{count}", String(entries.length))}>
        {entries.length === 0 ? (
          <EmptyState
            title={t("truck.wb.ledgerEmptyTitle")}
            description={t("truck.wb.ledgerEmptyBody")}
          />
        ) : (
          <div className="tv-ledger" role="table">
            <div className="tv-ledger-thead" role="row">
              <span role="columnheader">{t("truck.wb.colDate")}</span>
              <span role="columnheader">{t("truck.wb.colKind")}</span>
              <span role="columnheader">{t("truck.wb.colWhatFor")}</span>
              <span role="columnheader">{t("truck.wb.colRecordedBy")}</span>
              <span role="columnheader">{t("truck.wb.colAmount")}</span>
              <span role="columnheader">{t("truck.wb.colBalance")}</span>
            </div>
            {[...rows].reverse().map(({ entry, balanceAfter }) => {
              const negative = Number(entry.amount) < 0;
              const path = itemPath(entry);
              return (
                <div className="tv-ledger-row" role="row" key={entry.id}>
                  <div role="cell">{displayDate(entry.entry_date)}</div>
                  <div role="cell">
                    <Badge
                      tone={
                        entry.kind === "payment"
                          ? "success"
                          : entry.kind === "charge"
                            ? "accent"
                            : "neutral"
                      }
                    >
                      {t(ENTRY_LABEL_KEYS[entry.kind] as never)}
                    </Badge>
                  </div>
                  <div role="cell">
                    {path ? (
                      <Link to={path} className="tv-ledger-itemlink">
                        {entry.item_name ?? t("truck.wb.linkedItem")}
                      </Link>
                    ) : (
                      entry.note || (
                        <span className="tv-truck-muted">—</span>
                      )
                    )}
                    {path && entry.note && (
                      <span className="tv-truck-muted"> · {entry.note}</span>
                    )}
                    {entry.source === "agent_request" && (
                      <span className="tv-truck-muted">
                        {t("truck.wb.sourceAgentRequest")}
                      </span>
                    )}
                    {entry.source === "migrated" && (
                      <span className="tv-truck-muted">{t("truck.wb.sourceMigrated")}</span>
                    )}
                  </div>
                  <div role="cell">{entry.recorded_by_name ?? "—"}</div>
                  <div
                    role="cell"
                    className={
                      negative ? "tv-ledger-amount-neg" : "tv-ledger-amount"
                    }
                  >
                    {negative ? "−" : "+"}
                    {money(String(Math.abs(Number(entry.amount))))}
                  </div>
                  <div role="cell" className="tv-ledger-balance">
                    {money(String(balanceAfter))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      {(isDealer || account.customer_maintained) && !closed && (
        <Panel title={t("truck.wb.scheduleTitle")}>
          <div className="tv-truck-stack">
            {schedule.has_schedule && schedule.missed_payments > 0 && (
              <Alert tone="danger">
                {t("truck.wb.missedAlert")
                  .replace("{count}", String(schedule.missed_payments))
                  .replace(
                    "{dates}",
                    schedule.missed_due_dates.map(displayDate).join(", "),
                  )
                  .replace("{amount}", money(schedule.amount_past_due))}
              </Alert>
            )}
            <div className="tv-truck-form-grid">
              <FormField label={t("truck.wb.cadenceLabel")} htmlFor="sched-cadence">
                <Select
                  id="sched-cadence"
                  value={cadence}
                  onChange={(e) => setCadence(e.target.value)}
                >
                  <option value="weekly">{t("truck.cadenceWeekly")}</option>
                  <option value="biweekly">{t("truck.cadenceBiweekly")}</option>
                </Select>
              </FormField>
              <FormField label={t("truck.paymentAmount")} htmlFor="sched-amount">
                <TextInput
                  id="sched-amount"
                  inputMode="decimal"
                  value={payAmount}
                  onChange={(e) => setPayAmount(e.target.value)}
                  placeholder="10.00"
                />
              </FormField>
              <FormField label={t("truck.wb.nextDueDateLabel")} htmlFor="sched-due">
                <DatePicker
                  id="sched-due"
                  value={dueDate}
                  onChange={setDueDate}
                  clearable
                />
              </FormField>
            </div>
            <div>
              <Button
                variant="secondary"
                loading={busy}
                onClick={() =>
                  void run(
                    () =>
                      updateSchedule(accountId, {
                        payment_cadence: cadence,
                        payment_amount: payAmount === "" ? undefined : payAmount,
                        next_due_date: dueDate || undefined,
                      }),
                    t("truck.wb.toastScheduleSaved"),
                  )
                }
              >
                {t("truck.wb.saveSchedule")}
              </Button>
            </div>
          </div>
        </Panel>
      )}

      {!isDealer && !closed && (
        <Panel title={t("truck.wb.howYouPayTitle")}>
          <div className="tv-truck-stack">
            <p className="tv-truck-note">
              {t("truck.wb.howYouPayBodyA")}
              <strong>{t("truck.wb.howYouPayAutomatic")}</strong>
              {t("truck.wb.howYouPayBodyB")}
              <strong>{t("truck.wb.howYouPayManual")}</strong>
              {t("truck.wb.howYouPayBodyC")}
            </p>
            <div className="tv-truck-row">
              <Select
                aria-label={t("truck.wb.paymentModeAria")}
                value={modeChoice}
                onChange={(e) => setModeChoice(e.target.value)}
              >
                <option value="manual">{t("truck.modeManual")}</option>
                <option value="automatic">{t("truck.wb.modeAutomaticLong")}</option>
              </Select>
              <Button
                variant="secondary"
                loading={busy}
                disabled={modeChoice === account.payment_mode}
                onClick={() =>
                  void run(
                    () =>
                      setPaymentMode(
                        accountId,
                        modeChoice as "manual" | "automatic",
                      ),
                    t("truck.wb.toastModeSaved"),
                  )
                }
              >
                {t("truck.wb.savePaymentMode")}
              </Button>
            </div>
          </div>
        </Panel>
      )}

      <Panel title={t("truck.wb.statementTitle")}>
        <div className="tv-truck-stack">
          <p className="tv-truck-note">{t("truck.wb.statementBody")}</p>
          <div className="tv-truck-actions" style={{ justifyContent: "flex-start" }}>
            <Button variant="secondary" onClick={() => void download("pdf")}>
              {t("truck.wb.statementPdf")}
            </Button>
            <Button variant="secondary" onClick={() => void download("csv")}>
              {t("truck.wb.ledgerCsv")}
            </Button>
          </div>
        </div>
      </Panel>

      {account.agreement_accepted_at && (
        <Panel title={t("truck.wb.agreementTitle")}>
          <p className="tv-truck-note">
            {t("truck.wb.agreementAcceptedBody")
              .replace("{date}", displayDate(account.agreement_accepted_at.slice(0, 10)))
              .replace(
                "{version}",
                account.agreement_version
                  ? t("truck.wb.agreementVersionSuffix").replace(
                      "{version}",
                      account.agreement_version,
                    )
                  : "",
              )
              .replace(
                "{party}",
                isDealer ? t("truck.wb.partyCustomer") : t("truck.wb.partyDealer"),
              )}
          </p>
        </Panel>
      )}

      {!isDealer && !closed && detail.transfer_options.length > 0 && (
        <Panel title={t("truck.wb.transferTitle")}>
          <div className="tv-truck-stack">
            <p className="tv-truck-note">
              {t("truck.wb.transferBody").replace(
                "{dealer}",
                account.dealer_company_name ?? t("truck.wb.transferDealerFallback"),
              )}
            </p>
            <div className="tv-truck-row">
              <Select
                aria-label={t("truck.wb.newAgentAria")}
                value={transferTarget}
                onChange={(e) => setTransferTarget(e.target.value)}
              >
                <option value="">{t("truck.wb.chooseNewAgent")}</option>
                {detail.transfer_options.map((option) => (
                  <option
                    key={`${option.kind}:${option.agent_user_id ?? option.private_agent_id}`}
                    value={`${option.kind}:${option.agent_user_id ?? option.private_agent_id}`}
                  >
                    {option.name}
                    {option.kind === "private" ? t("truck.wb.ownRecordSuffix") : ""}
                  </option>
                ))}
              </Select>
              <Button
                loading={busy}
                disabled={!transferTarget}
                onClick={() => {
                  const [kindPart, targetId] = transferTarget.split(":");
                  const target = detail.transfer_options.find(
                    (o) =>
                      o.kind === kindPart &&
                      (o.agent_user_id ?? o.private_agent_id) === targetId,
                  );
                  if (!target) return;
                  if (
                    window.confirm(
                      t("truck.wb.transferConfirm")
                        .replace("{target}", target.name)
                        .replace(
                          "{current}",
                          account.agent_name || t("truck.wb.currentAgentFallback"),
                        ),
                    )
                  ) {
                    void run(
                      () =>
                        transferAccount(accountId, {
                          to_agent_user_id:
                            target.kind === "platform"
                              ? target.agent_user_id
                              : null,
                          to_private_agent_id:
                            target.kind === "private"
                              ? target.private_agent_id
                              : null,
                        }),
                      t("truck.wb.toastMoved").replace("{target}", target.name),
                    );
                    setTransferTarget("");
                  }
                }}
              >
                {t("truck.wb.moveAccountBtn")}
              </Button>
            </div>
          </div>
        </Panel>
      )}

      {detail.transfers.length > 0 && (
        <Panel title={t("truck.wb.agentHistoryTitle")}>
          <div>
            {detail.transfers.map((transfer) => (
              <div key={transfer.id} className="tv-truck-history-row">
                <p className="tv-truck-note">
                  {t("truck.wb.movedFromTo")
                    .replace("{from}", transfer.from_agent_name || "—")
                    .replace("{to}", transfer.to_agent_name || "—")}
                  {transfer.to_agent_kind === "private"
                    ? t("truck.wb.ownRecordSuffix")
                    : ""}
                </p>
                <p className="tv-truck-note">
                  {displayDate(transfer.created_at.slice(0, 10))}
                </p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {!closed && (
        <Panel title={t("truck.wb.closeTitle")}>
          <div className="tv-truck-stack">
            <p className="tv-truck-note">
              {t("truck.wb.closeBody").replace("{name}", otherName)}
            </p>
            <div>
              <Button
                variant="danger"
                loading={busy}
                onClick={() => {
                  if (
                    window.confirm(t("truck.wb.closeConfirm"))
                  ) {
                    void run(() => closeAccount(accountId), t("truck.wb.toastClosed"));
                  }
                }}
              >
                {t("truck.wb.closeBtn")}
              </Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
