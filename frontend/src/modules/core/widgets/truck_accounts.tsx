import {
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {Link} from "react-router-dom";
import {
  Button,
  FormField,
  Select,
  TextInput,
  buttonClasses,
} from "../../../components";
import {ArtIcon} from "../../../components/ArtIcon";
import {useT} from "../../../i18n/LocaleContext";
import {ApiError} from "../../../lib/api";
import {formatMoney} from "../../../lib/money";
import {
  addEntry,
  getStatusSummary,
  listAccounts,
} from "../../truck-accounts/api";
import type {TruckAccount} from "../../truck-accounts/types";
import {
  optBool,
  optNum,
} from "../widgetOptions";
import type {
  WidgetData,
  WidgetDef,
} from "./shared";
import {
  count,
  line,
} from "./shared";

function truckAccountFace(a: TruckAccount): string {
  return a.my_role === "dealer"
    ? a.customer_name
    : a.dealer_company_name ?? a.dealer_name ?? "Dealer";
}

/**
 * The truck widget's quick-entry bridge (widget options
 * Wave 2): one load builds both the account rows — whose
 * + Entry buttons live in row cells — and the entry form in
 * the actions slot; the bus is how a row's button opens the
 * form on its account. A fresh bus per load; the form
 * registers its opener on mount and whenever the bus swaps
 * (a reload after a post hands it a new one).
 */
interface EntryBus {
  open: (accountId: string) => void;
  set: (fn: (accountId: string) => void) => void;
}

function createEntryBus(): EntryBus {
  const bus: EntryBus = {
    open: () => {},
    set: (fn) => {
      bus.open = fn;
    },
  };
  return bus;
}

/**
 * The truck accounts widget's quick-entry form (widget
 * options Wave 2, Decision 3): pick the account, Payment or
 * Charge, the amount, an optional note — with the balance it
 * lands on shown BEFORE anything posts — then post through
 * the EXISTING addEntry endpoint, the account page's own
 * door, unchanged. Either seat may post (the endpoint rules:
 * charges only from the dealer seat or a customer-maintained
 * tab, exactly as the account page offers them); only active
 * accounts are listed, and a refusal comes back as the
 * endpoint's own words in the form — never a silent failure.
 * On success the widget reloads, so the row's balance and
 * the totals update in place.
 */
/** Sheet row 48 (Ryan, 2026-11-15): a button in the Truck
 *  accounts widget that shows this week's total payments
 *  across all the viewer's open truck accounts. The total is
 *  the backend status summary's payments_this_week — payment
 *  entries dated in the current Monday-start calendar week,
 *  stated positive. */
function TruckWeekPayments({ total }: { total: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="tv-truck-weekpay">
      <button
        type="button"
        className={buttonClasses("ghost", "sm")}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {line(t, "home.widget.truckWeekPayBtn", "This week's payments")}
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <p className="tv-truck-weekpay-total">
          <span>
            {line(t, "home.widget.truckWeekPayLabel", "Paid this week")}
          </span>
          <strong>{total}</strong>
        </p>
      )}
    </div>
  );
}

function TruckQuickEntry({
  accounts,
  bus,
  onPosted,
}: {
  accounts: TruckAccount[];
  bus: EntryBus;
  onPosted: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [kind, setKind] = useState<"payment" | "charge">("payment");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [posted, setPosted] = useState("");

  useEffect(() => {
    bus.set((id) => {
      setAccountId(id);
      setError("");
      setPosted("");
      setOpen(true);
    });
  }, [bus]);

  const account =
    accounts.find((a) => a.id === accountId) ?? accounts[0] ?? null;
  if (!account) return null;
  // The account page's own rule (stage 2): a charge is offered
  // to the dealer seat on an agent-kept tab, or to the customer
  // on a tab he maintains — never to the dealer on a tab the
  // customer keeps (his path there is a payment request).
  const canCharge =
    account.my_role === "dealer"
      ? account.ledger_keeper === "agent"
      : account.customer_maintained;
  const effKind = kind === "charge" && !canCharge ? "payment" : kind;
  const amt = Number(amount);
  // Stage 2: a charge with no note is refused by the API
  // (every increase is explained) — the form holds the same
  // line instead of letting the post fail.
  const chargeNeedsNote = effKind === "charge" && note.trim() === "";
  const valid =
    amount.trim() !== "" &&
    Number.isFinite(amt) &&
    amt > 0 &&
    !chargeNeedsNote;
  const balanceNow = Number(account.balance) || 0;
  const balanceAfter = valid
    ? effKind === "payment"
      ? balanceNow - amt
      : balanceNow + amt
    : null;

  async function post() {
    if (!account || !valid || busy) return;
    setBusy(true);
    setError("");
    try {
      await addEntry(account.id, {
        kind: effKind,
        amount: amount.trim(),
        note: note.trim(),
        item_link_id: null,
        entry_date: null,
      });
      setPosted(
        effKind === "payment"
          ? t("home.widget.truck.postedPayment")
          : t("home.widget.truck.postedCharge"),
      );
      setAmount("");
      setNote("");
      setOpen(false);
      onPosted();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("home.widget.truck.postFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return posted ? (
      <p className="tv-widget-entry-flash" role="status">
        {posted}
      </p>
    ) : null;
  }

  return (
    <form
      className="tv-widget-entry-form"
      onSubmit={(e) => {
        e.preventDefault();
        void post();
      }}
    >
      <FormField label={t("home.widget.truck.account")} htmlFor="tw-entry-account">
        <Select
          id="tw-entry-account"
          inputSize="sm"
          value={account.id}
          onChange={(e) => {
            setAccountId(e.target.value);
            setError("");
          }}
        >
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {truckAccountFace(a)} · {formatMoney(a.balance, a.currency, true)}
            </option>
          ))}
        </Select>
      </FormField>
      <div className="tv-widget-entry-row" role="group" aria-label={t("home.widget.truck.payment")}>
        <Button
          type="button"
          size="sm"
          variant={effKind === "payment" ? "primary" : "ghost"}
          aria-pressed={effKind === "payment"}
          onClick={() => setKind("payment")}
        >
          {t("home.widget.truck.payment")}
        </Button>
        {canCharge && (
          <Button
            type="button"
            size="sm"
            variant={effKind === "charge" ? "primary" : "ghost"}
            aria-pressed={effKind === "charge"}
            onClick={() => setKind("charge")}
          >
            {t("home.widget.truck.charge")}
          </Button>
        )}
      </div>
      <div className="tv-widget-entry-row">
        <FormField label={t("home.widget.truck.amount")} htmlFor="tw-entry-amount">
          <TextInput
            id="tw-entry-amount"
            inputSize="sm"
            inputMode="decimal"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </FormField>
        <FormField label={t("home.widget.truck.note")} htmlFor="tw-entry-note">
          <TextInput
            id="tw-entry-note"
            inputSize="sm"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </FormField>
      </div>
      <p className="tv-widget-entry-note">
        {t("home.widget.truck.balanceNow").replace(
          "{value}",
          formatMoney(account.balance, account.currency, true),
        )}
        {balanceAfter !== null &&
          ` · ${t("home.widget.truck.balanceAfter").replace(
            "{value}",
            formatMoney(balanceAfter.toFixed(2), account.currency, true),
          )}`}
      </p>
      {chargeNeedsNote && (
        <p className="tv-widget-entry-note">
          {t("home.widget.truck.noteRequired")}
        </p>
      )}
      {error && (
        <p className="tv-widget-entry-error" role="alert">
          {error}
        </p>
      )}
      <div className="tv-widget-entry-row">
        <Button type="submit" size="sm" loading={busy} disabled={!valid}>
          {effKind === "payment"
            ? t("home.widget.truck.recordPayment")
            : t("home.widget.truck.recordCharge")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setOpen(false)}
        >
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

/**
 * The Dealers near you widget's finder (owner, 2026-11-14):
 * a ZIP field and a range IN the widget, and a "Find an agent
 * near me" button — the search runs the typed ZIP through the
 * same /dealers/near-you read (zip_code replaces the profile
 * ZIP server-side) and the answers land in a POPUP over Home:
 * one row per (agent, company), the directory's CompanyLogo
 * treatment, the agent's name, and the honest distance, each
 * row a door to that dealer. An unknown ZIP and an empty
 * result are plain sentences in the popup, never a fake list.
 * The form rides the widget's actions slot (the truck quick
 * entry's seat), above the whole-box cover, so its fields
 * take real clicks; the widget body above it keeps showing
 * the profile-ZIP rows as before.
 */

export const truckAccountsWidget: WidgetDef = {
    icon: <ArtIcon name="truck" size={24} />,
    tone: "success",
    cta: "open",
    // The standalone truck page is retired (2026-11-17):
    // the widget's door is the Dealers page, whose glance
    // panel is the overview now.
    path: "/dealers",
    load: async (t, ctx) => {
      // Sample redesign (2026-11-15): the counts line,
      // two stat tiles (total owed / due this week — the
      // MISSED tile was removed by owner order, sheet row
      // 51, 2026-11-15; the rows' missed pill was removed
      // by owner order, sheet row 76, 2026-11-17), then the
      // ACCOUNTS rows — the tab's face with its agent quiet
      // underneath, an empty pill column, the balance, and
      // the + Entry door on active accounts.
      // The quick-entry form keeps riding the actions slot
      // (the owner's named write action on Home).
      const settings = ctx?.settings ?? {};
      const quickEntry = optBool(settings, "quickEntry", true);
      const rowsVisible = optNum(settings, "rowsVisible", 3, 2, 6);
      const showOpenCount = optBool(settings, "showOpenCount", true);
      const showDueTotal = optBool(settings, "showDueTotal", true);
      const showOwed = optBool(settings, "showOwed", true);
      const showRows = optBool(settings, "showRows", true);
      const accounts = await listAccounts();
      const open = accounts.filter((a) => a.status !== "closed");
      const due = open.reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
      const data: WidgetData = { lines: [] };
      const counts: { value: string; label: string }[] = [];
      if (showOpenCount) {
        counts.push({
          value: count(open.length),
          label: line(t, "home.widget.truckAccountsWord", "accounts"),
        });
      }
      if (showDueTotal) {
        counts.push({
          value: formatMoney(String(due), null, true),
          label: line(t, "home.widget.truckDueWord", "balances due"),
        });
      }
      if (counts.length > 0) data.counts = counts;
      const summary = await getStatusSummary().catch(() => null);
      if (summary && open.length > 0) {
        data.afterStats = (
          <TruckWeekPayments
            total={formatMoney(summary.payments_this_week, null, true)}
          />
        );
      }
      if (showOwed || showDueTotal) {
        const weekOut = Date.now() + 7 * 24 * 3600 * 1000;
        const dueWeek = open
          .filter(
            (a) =>
              a.status === "active" &&
              a.next_due_date &&
              new Date(a.next_due_date).getTime() <= weekOut,
          )
          .reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
        data.stats = [
          {
            label: line(t, "home.widget.truckTileOwed", "Total owed"),
            value: formatMoney(String(due), null, true),
          },
          {
            label: line(t, "home.widget.truckTileWeek", "Due this week"),
            value: formatMoney(String(dueWeek), null, true),
          },
        ];
      }
      if (open.length > 0) {
        const editing = ctx?.editing ?? false;
        const roleRank = (a: TruckAccount): number =>
          a.my_role === "customer" ? 0 : a.my_role === "dealer" ? 1 : 2;
        const sorted = [...open].sort(
          (a, b) =>
            roleRank(a) - roleRank(b) ||
            (Number(b.balance) || 0) - (Number(a.balance) || 0),
        );
        const bus = createEntryBus();
        const active = sorted.filter((a) => a.status === "active");
        if (showRows) {
          data.groups = [
            {
              label: line(t, "home.widget.truckAccountsGroup", "Accounts"),
              rowsClass: "tv-widget-rows--reports",
              rows: sorted.map((a) => {
                const cells: ReactNode[] = [
                  <span key="f" className="tv-widget-cellstack">
                    <span>{truckAccountFace(a)}</span>
                    <span className="tv-widget-cellsub">
                      {a.agent_name
                        ? line(t, "home.widget.truckAgentSub", "agent {name}", {
                            name: a.agent_name,
                          })
                        : line(t, "home.widget.truckNoAgent", "No agent named")}
                    </span>
                  </span>,
                  <span key="m" />,
                  formatMoney(a.balance, a.currency, true),
                  quickEntry && a.status === "active" && !editing ? (
                    <button
                      key="entry"
                      type="button"
                      className="tv-widget-entry-btn"
                      onClick={() => bus.open(a.id)}
                    >
                      {line(t, "home.widget.truck.addEntry", "+ Entry")}
                    </button>
                  ) : (
                    <span key="entry" />
                  ),
                ];
                return { cells };
              }),
              visible: rowsVisible,
            },
          ];
        }
        if (quickEntry && active.length > 0 && ctx) {
          data.actions = (
            <TruckQuickEntry
              accounts={active}
              bus={bus}
              onPosted={ctx.reload}
            />
          );
        }
      }
      // The footer pair rides under the quick-entry form when
      // the form is present, and as the footer row otherwise.
      const truckPair = (
        <>
          <Link to="/dealers" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.truckAllAccounts", "All accounts")}
          </Link>
          <Link to="/dealers" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.truckNewAccount", "New account")}
          </Link>
        </>
      );
      if (data.actions) {
        const form = data.actions;
        data.actions = (
          <>
            {form}
            <div className="tv-widget-actionsend">{truckPair}</div>
          </>
        );
      } else {
        data.actions = truckPair;
        data.actionsEnd = true;
      }
      return data;
    },
  };
