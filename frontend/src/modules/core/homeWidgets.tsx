import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Link, useNavigate } from "react-router-dom";

import {
  Button,
  FileUpload,
  FormField,
  Panel,
  QuietSkeleton,
  Select,
  TextInput,
  buttonClasses,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import type { StatTone } from "../../components/OverviewRow";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import type {
  BlockSettingValue,
  BlockSize,
} from "../../lib/usePageLayout";
import { activeLocale, formatDate, formatDateTime } from "../../lib/format";
import { formatMoney } from "../../lib/money";
import { getBorrowingOverview } from "../borrowing/api";
import {
  disasterClaimsApi,
  getClaimsStats,
  listClaims,
} from "../claims/api";
import { getDealerListSettings, getNearYou, listCompanies } from "../dealers/api";
import { CompanyLogo } from "../dealers/components/CompanyLogo";
import type {
  HealthCheckDueItem,
  HealthCheckDueResult,
} from "../inventory/types";
import {
  acceptForKind,
  photoFileError,
} from "../inventory/components/photoTransfer";
import {
  quickAddSeedState,
  type QuickAddSeed,
} from "../inventory/quickAddSeed";
import { StatusBadge } from "../claims/components";
import { getBoard } from "../feedback/api";
import { ConverterBody } from "./DownloadsConverter";
import "../flyers/flyers.css";
import { flyerFeed } from "../flyers/api";
import { sourceTitle } from "../flyers/types";
import { getCategories, listFavorites } from "../forum/api";
import { getBoard as getMarketplaceBoard } from "../marketplace/api";
import { getMaintenanceOverview, getMaintenanceStats } from "../maintenance/api";
import { getUnread, listThreads } from "../messaging/api";
import { getPartsStats, listParts } from "../parts/api";
import type { PeerOverview } from "../peer/types";
import { browsePrints, previewUrl } from "../prints/api";
import type { PrintFileRow } from "../prints/types";
import "../prints/prints.css";
import "./downloads.css";
import { listTemplates } from "../reports/api";
import { listMyTickets } from "../support/api";
import { getExpansionSummary } from "../tool-expansion/api";
import { addEntry, listAccounts } from "../truck-accounts/api";
import type { TruckAccount } from "../truck-accounts/types";
import { listWishlist } from "../wishlist/api";
import { optBool, optNum } from "./widgetOptions";

/**
 * HOME WIDGETS (Home + Header program, owner 2026-10-24): the
 * modules on Home are LIVE WIDGETS now, not description boxes —
 * the phone-home-screen model. One widget per module: a headline
 * number or two, a few live lines read from the MODULE'S OWN
 * endpoints (modules own their data — the widget only reads the
 * same payloads the module's panel already reads), and a button
 * that goes to the module. Widget on/off is a HOME choice (the
 * home layout's widget:<id> blocks), separate from module
 * enablement; a widget only exists for a user while its module
 * is effective for them and serves one of their groups.
 *
 * Catalog gets no widget (it has no surface of its own — it is
 * embedded panels inside Inventory) and ai_assistant gets none
 * while it is inert/unconfigured: nothing live to show, and the
 * rule is no invented content.
 */
/**
 * One structured widget row (widget options Wave 1 framework):
 * a row of fact cells laid out side by side — a claim number,
 * the item, its status — as against the plain-text `lines`.
 * `href` makes the whole row a link (dropped in Edit view,
 * where a box never navigates). Rows render in the widget's
 * interactive layer, above the whole-box cover anchor, so a
 * row link is hit-tested as itself — never shadowed by the
 * box link.
 */
export interface WidgetRow {
  cells: ReactNode[];
  href?: string;
}

/**
 * One named list inside a widget (widget options Wave 2):
 * Borrowing's lent-out and borrowed-by-me lists are the first
 * tenants. Groups stack at half width and sit side by side at
 * full width, each capped at its own `visible` rows with the
 * rest scrolling inside the group (the Notifications pattern).
 */
export interface WidgetRowGroup {
  label?: string;
  /** Column headings for the group's rows (Sweep B1, 01-F7):
   *  worn at full width like every widget row set's header; at
   *  half width the cells themselves carry the separation. */
  header?: ReactNode[];
  /** Column template class for the group's row set (full width). */
  rowsClass?: string;
  rows: WidgetRow[];
  /** Rows shown before the group scrolls internally. */
  visible?: number;
}

/**
 * What a widget's load is handed (widget options Wave 2): the
 * block's resolved width and options bundle (read through the
 * registry's optBool/optNum helpers — the popover and the
 * loader share the defaults), whether Home is in Edit view
 * (interactive cells stay out of the arrangement surface), and
 * a reload the widget may call after it changes its own data
 * (the truck quick entry posts, then the rows re-read so the
 * balance updates in place).
 */
export interface WidgetLoadCtx {
  size: BlockSize;
  settings: Record<string, BlockSettingValue>;
  editing: boolean;
  reload: () => void;
}

/**
 * One tile in a showcase strip (dashboard-flare lane, owner
 * order 2026-11-09): a thumbnail (or an icon fallback where
 * the record carries no image), a title, an optional small
 * sub-line (a count, a rating), and the tile's own deep link.
 * Strips scroll sideways inside the widget — the rest of the
 * tiles wait off the right edge, the phone-home-screen way.
 */
export interface WidgetStripTile {
  thumb?: string;
  /** A ready-made thumbnail element that replaces the
   *  img/icon pair — the dealers widget seats the directory's
   *  own CompanyLogo here, so a logo that fails to load falls
   *  back to the brand's initial tile exactly as it does on
   *  the Dealers page itself. The frame renders bare (the
   *  node carries its own tile). */
  thumbNode?: ReactNode;
  icon?: ReactNode;
  /** Paint the thumb on a dark tile (white-glyph logos). */
  darkTile?: boolean;
  title: string;
  sub?: string;
  href: string;
}

/** One labeled showcase strip inside a widget: the Downloads
 *  weekly chart, the prints widget's two shelves (new, most
 *  downloaded), the dealer tiles. */
export interface WidgetStrip {
  label?: string;
  tiles: WidgetStripTile[];
}

/** One glanceable stat in a widget's stats grid: a value over
 *  its label, in a uniform grid of identical cells (the
 *  Downloads widget's facts — dashboard-flare lane). */
export interface WidgetStat {
  label: string;
  value: string;
}

export interface WidgetData {
  headline?: string;
  lines: string[];
  /**
   * Structured rows + an actions slot (widget options Wave 1
   * framework extension): a widget MAY supply either alongside
   * (or instead of) plain lines. `actions` is real controls —
   * buttons, links — rendered under the content in the same
   * above-the-cover layer as rows, so inner controls win over
   * the whole-box link in real clicks. A widget that supplies
   * only lines renders exactly as it always has.
   */
  rows?: WidgetRow[];
  /** Rows shown before the plain rows list scrolls internally
   *  (widget options Wave 2); absent = the list never caps. */
  rowsVisible?: number;
  /** Column headings for the rows list, worn only at full
   *  width, where the rows take their table shape (Wave 2). */
  header?: ReactNode[];
  /** Per-widget column template for the full-width table
   *  shape: a modifier class on the row set (Wave 2). */
  rowsClass?: string;
  /** Named row groups (Wave 2) — see WidgetRowGroup. */
  groups?: WidgetRowGroup[];
  /** Plain lines that belong AFTER the rows/groups (Wave 2):
   *  Borrowing's waiting/overdue lines keep their reading
   *  order under its lists instead of jumping above them. */
  linesAfter?: string[];
  /** The glanceable stats grid (dashboard-flare lane): uniform
   *  label/value cells above the strips. */
  stats?: WidgetStat[];
  /** Showcase strips (dashboard-flare lane): sideways-
   *  scrolling thumbnail tiles with deep links, rendered
   *  after the lines/stats and before any rows/groups. */
  strips?: WidgetStrip[];
  actions?: ReactNode;
}

export interface WidgetDef {
  icon: ReactNode;
  tone: StatTone;
  /** The go-to button's words: "See the rest" for list modules,
   *  "Open" for the rest. */
  cta: "viewAll" | "open";
  load: (t?: (key: never) => string, ctx?: WidgetLoadCtx) => Promise<WidgetData>;
  /**
   * The widget's door when the module itself has no nav door:
   * support's surface is the Help & Support page (the header ?
   * is its door), so its widget points there instead of at a
   * module nav path.
   */
  path?: string;
  /**
   * The widget starts OFF for users whose saved layout doesn't
   * carry it (the layout resolver's `defaultVisible: false`):
   * a NEW widget joins the picker without rearranging anyone's
   * stored Home (owner follow-up, 2026-11-09 — the 3D Print
   * Files widget). CorePage's module-widget assembly reads this
   * flag; CorePage's registry reads the same flag.
   */
  defaultOff?: boolean;
}

const count = (n: number): string => n.toLocaleString(activeLocale());

/** Widget line templates (item 19, Deep Audit Round 2): every
 * load() receives the translator from HomeWidget, like the
 * tool_expansion widget already did; the English fallback keeps
 * the load usable from any future caller without one. */
type WT = (key: never) => string;
const line = (
  t: WT | undefined,
  key: string,
  fallback: string,
  subs: Record<string, string> = {},
): string => {
  let out = t ? t(key as never) : fallback;
  for (const [k, v] of Object.entries(subs)) out = out.replace(`{${k}}`, v);
  return out;
};

/** The face a truck account shows in the widget, from the
 *  viewer's seat: their tab names the company; an account they
 *  hold as dealer names the customer. */
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
 * The Quick Add box (widget wave 2 build 3): one input, one
 * drop zone — a door into the add wizard, nothing more. A typed
 * name rides location state as the wizard's seed (the wizard
 * seats it in its own name field; see quickAddSeed.ts); a
 * dropped or picked photo rides as the File itself, which the
 * wizard stages as the item's first photo while its lookup
 * step runs photo identification on it — the exact treatment a
 * pick inside the wizard gets. The box validates a photo with
 * the wizard's own photo rules (photoFileError — the staged
 * picker's own words) and says so in place when a file can't
 * ride; the name path and the wizard door stay usable. An
 * empty name simply opens the wizard — a valid door too. The
 * fork (battery or tool) is the wizard's own first question;
 * the box never asks it.
 */
function QuickAddBox() {
  const t = useT();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const openWizard = (seed?: QuickAddSeed) => {
    navigate(
      "/inventory/new",
      seed ? { state: quickAddSeedState(seed) } : undefined,
    );
  };

  const onPhoto = (files: File[]) => {
    const file = files[0];
    if (!file) return;
    const problem = photoFileError(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    openWizard({ photo: file });
  };

  return (
    <div className="tv-quickadd">
      <form
        className="tv-quickadd-form"
        onSubmit={(e) => {
          e.preventDefault();
          const trimmed = name.trim();
          openWizard(trimmed ? { name: trimmed } : undefined);
        }}
      >
        <TextInput
          inputSize="sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("home.widget.quickAdd.namePlaceholder")}
          aria-label={t("home.widget.quickAdd.nameLabel")}
        />
        <Button type="submit" size="sm">
          {t("home.widget.quickAdd.go")}
        </Button>
      </form>
      <FileUpload
        onFiles={onPhoto}
        accept={acceptForKind("photo")}
        multiple={false}
        label={t("home.widget.quickAdd.dropLabel")}
        hint={t("home.widget.quickAdd.dropHint")}
      />
      {error && (
        <p className="tv-widget-entry-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** The Account & Plan widget's read: GET /billing/me's payload
 *  (the billing module's EntitlementView — the same shape
 *  Settings → Plan & billing renders from). */
interface AccountPlanView {
  plan_name: string;
  source: string;
  is_paid: boolean;
  item_limit: number | null;
  items_total: number;
  enforcement_enabled: boolean;
  subscription: {
    status: string;
    current_period_end: string | null;
    grace_until: string | null;
    trial_end: string | null;
  } | null;
}

/** Plain-language names for the entitlement sources the widget
 *  names in a line. A source outside this map gets NO line —
 *  the widget never prints a raw enum value. Mirrors the source
 *  vocabulary of billing/entitlements.resolve_entitlement. */
const ACCOUNT_PLAN_SOURCES: Record<string, { key: string; fallback: string }> = {
  subscription: {
    key: "home.widget.accountPlan.source.subscription",
    fallback: "Paid subscription",
  },
  subscription_grace: {
    key: "home.widget.accountPlan.source.subscriptionGrace",
    fallback: "Subscription — in its grace period",
  },
  trial: {
    key: "home.widget.accountPlan.source.trial",
    fallback: "Free trial",
  },
  lifetime: {
    key: "home.widget.accountPlan.source.lifetime",
    fallback: "Lifetime access",
  },
  referral: {
    key: "home.widget.accountPlan.source.referral",
    fallback: "Referral reward",
  },
  redeem_code: {
    key: "home.widget.accountPlan.source.redeem",
    fallback: "Redeem code",
  },
  admin: {
    key: "home.widget.accountPlan.source.admin",
    fallback: "Granted by Toolbox Vault",
  },
};

/** The renewal-class date the widget may show, if any — ONLY a
 *  date the subscription record itself carries: a trial's end,
 *  a grace window's end, or a paid subscription's period end
 *  (\"Renews\", or \"Ends\" when the subscription is canceled and
 *  will not renew). An account with no such record gets no date
 *  tile at all — honest absence, never a placeholder. */
function accountPlanRenewal(
  view: AccountPlanView,
): { key: string; fallback: string; iso: string } | null {
  const sub = view.subscription;
  if (!sub || !view.is_paid) return null;
  if (view.source === "trial" && sub.trial_end) {
    return {
      key: "home.widget.accountPlan.trialEnds",
      fallback: "Trial ends",
      iso: sub.trial_end,
    };
  }
  if (view.source === "subscription_grace" && sub.grace_until) {
    return {
      key: "home.widget.accountPlan.accessThrough",
      fallback: "Access through",
      iso: sub.grace_until,
    };
  }
  if (view.source === "subscription" && sub.current_period_end) {
    return sub.status === "canceled"
      ? {
          key: "home.widget.accountPlan.ends",
          fallback: "Ends",
          iso: sub.current_period_end,
        }
      : {
          key: "home.widget.accountPlan.renews",
          fallback: "Renews",
          iso: sub.current_period_end,
        };
  }
  return null;
}

export const HOME_WIDGETS: Record<string, WidgetDef> = {
  inventory: {
    icon: <ArtIcon name="inventory" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 2: the line toggles, the Add Item
      // button, and the recently-added list (1–5). Every
      // default is today's widget: lines on, no button, the
      // latest item only. The data is the same two reads the
      // widget has always made — the search just asks for a
      // few more names, per the approved design.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const showValue = optBool(settings, "showValue", true);
      const showLatest = optBool(settings, "showLatest", true);
      const addButton = optBool(settings, "addButton", false);
      const recentCount = optNum(settings, "recentCount", 1, 1, 5);
      const [stats, tools] = await Promise.all([
        api<{
          total_items: number;
          total_value: string;
          warranties_expiring_soon?: number;
        }>("/inventory/stats"),
        api<{ name: string; location: string }[]>("/inventory/search?limit=5"),
      ]);
      const lines: string[] = [];
      if (showCount) {
        lines.push(line(t, "home.widget.toolsTracked", "{count} tools tracked", { count: count(stats.total_items) }));
      }
      if (showValue) {
        lines.push(line(t, "home.widget.totalValue", "Total value {value}", { value: formatMoney(stats.total_value, null, true) }));
      }
      // Sweep B1 (01-F7): a related fact the stats read already
      // carries — warranties about to expire — fills the panel
      // honestly when it is true, and stays absent when it isn't.
      if ((stats.warranties_expiring_soon ?? 0) > 0) {
        lines.push(
          line(t, "home.widget.warrantiesSoon", "{count} warranties expiring soon", {
            count: count(stats.warranties_expiring_soon ?? 0),
          }),
        );
      }
      const data: WidgetData = { lines };
      const recent = tools.slice(0, recentCount);
      if (showLatest && recent.length > 0) {
        if (ctx?.size === "full") {
          // Full width: the recent list becomes proper rows,
          // each item's location beside its name.
          data.header = [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.panel.location", "Location"),
          ];
          data.rowsClass = "tv-widget-rows--cols-inventory";
          data.rows = recent.map((tool) => ({
            cells: [tool.name, tool.location || "—"],
          }));
        } else if (recentCount === 1) {
          lines.push(line(t, "home.widget.latest", "Latest: {name}", { name: recent[0].name }));
        } else {
          lines.push(line(t, "home.widget.latest", "Latest: {name}", { name: recent[0].name }));
          for (const tool of recent.slice(1)) lines.push(tool.name);
        }
      }
      if (addButton) {
        // A real inner control: it rides the actions layer
        // above the whole-box cover, so the click starts the
        // wizard instead of following the box.
        data.actions = (
          <Link to="/inventory/new" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.addItem", "Add item")}
          </Link>
        );
      }
      return data;
    },
  },
  marketplace: {
    icon: <ArtIcon name="marketplace" size={24} />,
    tone: "success",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the listings ride as rows — 3 is
      // today's glance, the choice takes it to 5 — and
      // each listing's price can sit beside its title
      // (off by default: today's widget shows titles
      // only). At full width with prices on, the rows
      // take their title · price table shape. The board
      // already carries the prices, in the seller's
      // currency.
      const settings = ctx?.settings ?? {};
      const showPrices = optBool(settings, "showPrices", false);
      const listingCount = optNum(settings, "listingCount", 3, 3, 5);
      const board = await getMarketplaceBoard({});
      const data: WidgetData = { lines: [] };
      const shown = board.slice(0, listingCount);
      if (shown.length > 0) {
        const full = ctx?.size === "full";
        if (full && showPrices) {
          data.header = [
            line(t, "home.widget.colTitle", "Title"),
            line(t, "inventory.col.price", "Price"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-marketplace";
        data.rows = shown.map((l) => {
          const cells: ReactNode[] = [l.title];
          if (showPrices) {
            cells.push(
              l.price != null
                ? formatMoney(l.price, l.seller_currency)
                : line(t, "home.widget.makeOffer", "Make offer"),
            );
          }
          return { cells };
        });
      }
      return data;
    },
  },
  borrowing: {
    icon: <ArtIcon name="borrowing" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 2: the lent-out list as real rows
      // (the owner's ask — who has what), a borrowed-by-me
      // list, overdue names, and the requests line, all from
      // the ONE overview this widget has always loaded. At
      // full width the two lists sit side by side, each
      // scrolling on its own; the counts line stays on top
      // and the waiting/overdue lines keep their place under
      // the lists, as they read today.
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const lentList = optBool(settings, "lentList", true);
      const borrowedList = optBool(settings, "borrowedList", false);
      const overdueNames = optBool(settings, "overdueNames", false);
      const requestsLine = optBool(settings, "requestsLine", true);
      const visibleRows = optNum(settings, "visibleRows", 3, 2, 6);
      const o = await getBorrowingOverview();
      // The counts line's own switch (custom-widget aspects,
      // Lane 2): absence = on, so the predefined widget is
      // byte-identical; a custom box may leave the line out.
      const lines: string[] = showCounts
        ? [
            line(t, "home.widget.lentBorrowed", "{lent} lent out · {borrowed} borrowed by me", {
              lent: count(o.lent_out.length),
              borrowed: count(o.borrowed_by_me.length),
            }),
          ]
        : [];
      const groups: WidgetRowGroup[] = [];
      // Sweep B1 (01-F7): each lend reads as item · person · due
      // columns — the due date the overview already carries —
      // never one run-on line where item and person blur.
      const dueCell = (c: (typeof o.lent_out)[number]) =>
        c.due_at
          ? formatDate(c.due_at)
          : line(t, "home.widget.noDue", "No due date");
      if (lentList && o.lent_out.length > 0) {
        groups.push({
          label: line(t, "home.widget.lentOut", "Lent out"),
          header: [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.widget.colBorrower", "Borrower"),
            line(t, "home.widget.colDue", "Due back"),
          ],
          rows: o.lent_out.map((c) => ({
            cells: [c.item_name, c.borrower_name, dueCell(c)],
          })),
          rowsClass: "tv-widget-rows--cols-borrowing",
          visible: visibleRows,
        });
      }
      if (borrowedList && o.borrowed_by_me.length > 0) {
        groups.push({
          label: line(t, "home.widget.borrowedByMe", "Borrowed by me"),
          header: [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.widget.colOwner", "Owner"),
            line(t, "home.widget.colDue", "Due back"),
          ],
          rows: o.borrowed_by_me.map((c) => ({
            cells: [c.item_name, c.owner_name ?? "", dueCell(c)],
          })),
          rowsClass: "tv-widget-rows--cols-borrowing",
          visible: visibleRows,
        });
      }
      const linesAfter: string[] = [];
      if (requestsLine && o.counts.pending_requests > 0) {
        linesAfter.push(line(t, "home.widget.requestsWaiting", "{count} requests waiting on you", { count: count(o.counts.pending_requests) }));
      }
      const overdueLent = o.lent_out.filter((c) => c.overdue);
      const overdueBorrowed = o.borrowed_by_me.filter((c) => c.overdue);
      if (overdueNames && overdueLent.length + overdueBorrowed.length > 0) {
        for (const c of overdueLent) {
          linesAfter.push(line(t, "home.widget.overdueWith", "Overdue: {item} — with {name}", { item: c.item_name, name: c.borrower_name }));
        }
        for (const c of overdueBorrowed) {
          linesAfter.push(line(t, "home.widget.overdueFrom", "Overdue: {item} — from {name}", { item: c.item_name, name: c.owner_name ?? "" }));
        }
      } else if (o.counts.overdue > 0) {
        linesAfter.push(line(t, "home.widget.overdue", "{count} overdue", { count: count(o.counts.overdue) }));
      }
      const data: WidgetData = { lines };
      if (groups.length > 0) data.groups = groups;
      if (linesAfter.length > 0) data.linesAfter = linesAfter;
      return data;
    },
  },
  maintenance: {
    icon: <ArtIcon name="repairs" size={24} />,
    tone: "warning",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch A: the two counts are
      // individually hideable (both on = today's combined line,
      // byte for byte), and the coming-up list — the schedules
      // as real rows from the SAME overview this widget has
      // always loaded, 1–5 visible before the rest scroll. The
      // list is the design's named shape, so it defaults on;
      // switching it off restores today's single Next line.
      // Full width adds the due-date column.
      //
      // Claims merge (owner, 2026-11-06): the standalone
      // Claims widget is GONE — everything it carried lives
      // here now, under this widget's own view options
      // (defaults = everything both widgets showed, so nobody
      // loses information on upgrade): the open-claims count
      // line, a backordered line when any claim sits
      // backordered, the recent-claims rows, and the Repair
      // claims / Repair history buttons (the merged page's
      // tabs). WARRANTY/repair claims only (claims
      // separation): insurance stays in the Disaster Claims
      // widget. The claims reads load SOFTLY — the claims
      // module can be off for a user whose maintenance module
      // is on, and then this widget simply shows its
      // maintenance half.
      const settings = ctx?.settings ?? {};
      const showDue = optBool(settings, "showDue", true);
      const showOut = optBool(settings, "showOut", true);
      const comingUp = optBool(settings, "comingUp", true);
      const visibleRows = optNum(settings, "visibleRows", 3, 1, 5);
      const showClaimsLine = optBool(settings, "showClaimsLine", true);
      const showBackordered = optBool(settings, "showBackordered", true);
      const claimsList = optBool(settings, "claimsList", true);
      const claimCount = optNum(settings, "claimCount", 3, 1, 5);
      const showClaimButtons = optBool(settings, "showClaimButtons", true);
      const [stats, overview] = await Promise.all([
        getMaintenanceStats(),
        getMaintenanceOverview(),
      ]);
      let claimStats: Awaited<ReturnType<typeof getClaimsStats>> | null = null;
      let claimList: Awaited<ReturnType<typeof listClaims>> | null = null;
      if (showClaimsLine || showBackordered || claimsList || showClaimButtons) {
        try {
          [claimStats, claimList] = await Promise.all([
            getClaimsStats(),
            listClaims(false),
          ]);
        } catch {
          claimStats = null;
          claimList = null;
        }
      }
      const lines: string[] = [];
      if (showDue && showOut) {
        lines.push(line(t, "home.widget.dueOut", "{due} due · {out} out of service", {
          due: count(stats.maintenance_due_count),
          out: count(stats.out_of_service_count),
        }));
      } else if (showDue) {
        lines.push(line(t, "home.widget.dueOnly", "{count} due", {
          count: count(stats.maintenance_due_count),
        }));
      } else if (showOut) {
        lines.push(line(t, "home.widget.outOnly", "{count} out of service", {
          count: count(stats.out_of_service_count),
        }));
      }
      if (claimStats && showClaimsLine) {
        lines.push(line(t, "home.widget.openClaims", "{count} open claims", {
          count: count(claimStats.open_claims_count),
        }));
      }
      if (claimList && showBackordered) {
        const backordered = claimList.filter(
          (c) => c.status === "backordered",
        ).length;
        if (backordered > 0) {
          lines.push(line(t, "home.widget.backordered", "{count} backordered", {
            count: count(backordered),
          }));
        }
      }
      const data: WidgetData = { lines };
      const full = ctx?.size === "full";
      // The schedules, built once — they take the primary
      // rows slot when no claim rows are showing, and a
      // labeled group under the claim rows when both show.
      const scheduleRows = overview.schedules.map((s) => {
        const cells: ReactNode[] = [s.item_name, s.label];
        if (full) {
          const due = s.next_due ?? s.due_date;
          cells.push(due ? formatDate(due) : "—");
        }
        return { cells };
      });
      const recent = claimsList && claimList ? claimList.slice(0, claimCount) : [];
      if (recent.length > 0) {
        if (full) {
          data.header = [
            line(t, "claims.col.claim", "Claim"),
            line(t, "home.widget.colItem", "Item"),
            line(t, "claims.col.status", "Status"),
            line(t, "home.widget.claimParty", "Dealer / Agent"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-claims";
        data.rowsVisible = claimCount;
        data.rows = recent.map((c) => {
          const cells: ReactNode[] = [
            c.claim_number,
            c.first_item_name || "—",
            <StatusBadge key="status" status={c.status} />,
          ];
          if (full) {
            // Full width adds who the claim runs through: the
            // agent (or dealer) on the claim.
            cells.push(c.warranty_agent_name || c.dealer_name || "—");
          }
          return { cells, href: `/claims/${c.id}` };
        });
        if (comingUp && scheduleRows.length > 0) {
          data.groups = [
            {
              label: line(t, "home.widget.comingUp", "Coming up"),
              rows: scheduleRows,
              visible: visibleRows,
            },
          ];
        }
      } else if (comingUp && scheduleRows.length > 0) {
        if (full) {
          data.header = [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.widget.colWhatsDue", "What's due"),
            line(t, "home.widget.colDueDate", "Due date"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-maintenance";
        data.rowsVisible = visibleRows;
        data.rows = scheduleRows;
      }
      if (!comingUp) {
        const next = overview.schedules[0];
        if (next) lines.push(line(t, "home.widget.next", "Next: {item} — {label}", { item: next.item_name, label: next.label }));
      }
      if (showClaimButtons && (claimStats || claimList)) {
        data.actions = (
          <>
            <Link to="/repairs#repair-claims" className={buttonClasses("secondary", "sm")}>
              {line(t, "home.widget.openClaimsBtn", "Repair claims")}
            </Link>
            <Link to="/repairs#repair-history" className={buttonClasses("secondary", "sm")}>
              {line(t, "home.widget.historyClaimsBtn", "Repair history")}
            </Link>
          </>
        );
      }
      return data;
    },
  },
  disaster_claims: {
    icon: <ArtIcon name="disaster" size={24} />,
    tone: "violet",
    cta: "open",
    load: async (t, ctx) => {
      // Disaster Claims widget (claims separation, 2026-11-05):
      // the claims widget's shape, for the insurance section —
      // open count, the last few disaster claims as real rows
      // (number · item · where it stands; the insurer at full
      // width), and Open / History buttons landing on the
      // Disaster Claims page's tabs (Open rides #open, History
      // rides its #history hash — the Closed tab since lane 4).
      const settings = ctx?.settings ?? {};
      const recentCount = optNum(settings, "recentCount", 3, 1, 5);
      const showButtons = optBool(settings, "showButtons", true);
      // Custom-widget aspect gates (Lane 2): the count line
      // and the recent rows carry their own switches, both
      // defaulting ON — absence is today's widget exactly.
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const [stats, claims] = await Promise.all([
        disasterClaimsApi.getClaimsStats(),
        disasterClaimsApi.listClaims(false),
      ]);
      const lines = showCount
        ? [
            line(t, "home.widget.openDisasterClaims", "{count} open disaster claims", { count: count(stats.open_claims_count) }),
          ]
        : [];
      const data: WidgetData = { lines };
      const recent = claims.slice(0, recentCount);
      if (showRows && recent.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "claims.col.claim", "Claim"),
            line(t, "home.widget.colItem", "Item"),
            line(t, "claims.col.status", "Status"),
            line(t, "disasterClaims.col.insurer", "Insurer"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-claims";
        data.rows = recent.map((c) => {
          const cells: ReactNode[] = [
            c.claim_number,
            c.first_item_name || "—",
            <StatusBadge key="status" status={c.status} />,
          ];
          if (full) cells.push(c.insurer_name || "—");
          return { cells, href: `/disaster-claims/${c.id}` };
        });
      }
      if (showButtons) {
        data.actions = (
          <>
            <Link to="/disaster-claims#open" className={buttonClasses("secondary", "sm")}>
              {line(t, "home.widget.disasterOpenBtn", "Open claims")}
            </Link>
            <Link to="/disaster-claims#history" className={buttonClasses("secondary", "sm")}>
              {line(t, "home.widget.disasterHistoryBtn", "History claims")}
            </Link>
          </>
        );
      }
      return data;
    },
  },
  parts: {
    icon: <ArtIcon name="parts" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark, appears when the module returns): the
      // parts ride as rows instead of bare title lines —
      // 2 visible before the rest scroll, today's count —
      // and at full width each row gains its quantity
      // beside the title, from the same loaded list. The
      // shelf count line gets its switch.
      const settings = ctx?.settings ?? {};
      const showShelf = optBool(settings, "showShelf", true);
      const visibleRows = optNum(settings, "visibleRows", 2, 2, 5);
      const [stats, parts] = await Promise.all([
        getPartsStats(),
        listParts({}),
      ]);
      const lines: string[] = [];
      if (showShelf) {
        lines.push(line(t, "home.widget.partsOnShelf", "{count} parts on the shelf", { count: count(stats.parts_count) }));
      }
      const data: WidgetData = { lines };
      if (parts.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "home.widget.colPart", "Part"),
            line(t, "home.widget.colQty", "Qty"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-parts";
        data.rowsVisible = visibleRows;
        data.rows = parts.map((p) => {
          const cells: ReactNode[] = [p.title];
          if (full) cells.push(count(p.quantity));
          return { cells };
        });
      }
      return data;
    },
  },
  dealers: {
    icon: <ArtIcon name="dealers" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      // Dealer Directory widget REBUILT (dashboard-flare lane,
      // owner order 2026-11-09): the widget stops reciting the
      // agent-stats lines and shows the user's OWN dealers —
      // the same list the Dealers page shows them (directory
      // companies they haven't hidden, then their own private
      // companies) — as a thumbnail strip: each dealer's logo
      // where the record carries one, the dealers artwork
      // where it doesn't, one tap to that dealer's page. Two
      // real doors ride the actions slot: Find a dealer (the
      // find-an-agent search) and the Dealer directory itself.
      // The old /dealers/stats lines were an agent's mirror
      // (preferred-by counts); a dealer-group user's dashboard
      // block still carries that world — this widget is the
      // directory's.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 16);
      // Custom-widget aspect gates (Lane 2): the tile strip
      // and the two door buttons carry their own switches,
      // both defaulting ON — absence is today's widget.
      const showTiles = optBool(settings, "showTiles", true);
      const showActions = optBool(settings, "showActions", true);
      const [companies, listSettings] = await Promise.all([
        listCompanies(),
        getDealerListSettings().catch(() => null),
      ]);
      const hidden = new Set(
        (listSettings?.directory ?? [])
          .filter((row) => row.hidden)
          .map((row) => row.company.id),
      );
      const mine = [
        ...companies.filter((c) => c.is_directory && !hidden.has(c.id)),
        ...companies.filter((c) => !c.is_directory),
      ];
      const data: WidgetData = { lines: [] };
      if (showCount) {
        data.lines.push(
          line(t, "home.widget.dealersCount", "{count} dealers in your directory", {
            count: count(mine.length),
          }),
        );
      }
      if (showTiles && mine.length > 0) {
        data.strips = [
          {
            tiles: mine.slice(0, tilesToShow).map((c) => ({
              // The directory's own logo component: the real
              // logo where the record carries one, the brand's
              // initial as a clean text tile where it doesn't
              // (or where the stored file fails) — the same
              // honest fallback the Dealers page shows.
              thumbNode: <CompanyLogo company={c} width={116} height={84} />,
              title: c.name,
              href: `/dealers/${c.id}`,
            })),
          },
        ];
      }
      if (showActions) {
        data.actions = (
          <>
            <Link to="/dealers/find-agent" className={buttonClasses("primary", "sm")}>
              {line(t, "home.widget.dealerFind", "Find a dealer")}
            </Link>
            <Link to="/dealers" className={buttonClasses("ghost", "sm")}>
              {line(t, "nav.dealers", "Dealer directory")}
            </Link>
          </>
        );
      }
      return data;
    },
  },
  dealers_near_you: {
    icon: <ArtIcon name="dealers" size={24} />,
    tone: "info",
    cta: "open",
    path: "/dealers/find-agent",
    // A NEW widget (widget wave 2, owner approval 2026-11-09):
    // it joins the picker OFF for everyone who already has a
    // Home — nobody's stored layout is rearranged. (It is NOT
    // a module widget in HOME_WIDGET_ORDER — the dealers module
    // already seats its directory widget there; CorePage seats
    // this one as its own block gated on the dealers module,
    // the Quick Reports pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Dealers near you (idea C#1): the directory widget shows
      // dealers you HAVE; this one finds NEW ones — the nearest
      // findable agents to the ZIP in the viewer's own profile
      // postal address, read server-side by /dealers/near-you
      // through the Find local Agent search itself, so the
      // findability bar and the distance math are the page's
      // own. Rows are (agent, company) pairs — the directory's
      // CompanyLogo treatment on the company cell, the agent's
      // name, and the honest distance (0 reads as "covers your
      // ZIP", never a dressed-up 0 mi). No ZIP on file is a
      // plain statement with a door to the profile — never a
      // fake list, never a guessed location.
      const settings = ctx?.settings ?? {};
      const rawRadius = settings.radiusMiles;
      const radius =
        typeof rawRadius === "number" &&
        [10, 25, 50, 100].includes(rawRadius)
          ? rawRadius
          : 50;
      const rowsToShow = optNum(settings, "rowsToShow", 4, 2, 6);
      const near = await getNearYou(radius);
      const findDoor = (
        <Link to="/dealers/find-agent" className={buttonClasses("primary", "sm")}>
          {line(t, "home.widget.dealerFind", "Find a dealer")}
        </Link>
      );
      if (near.state === "no_location") {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.noLocation",
              "Add a ZIP code to the postal address on your profile, and this widget will show the dealer agents near you.",
            ),
          ],
          actions: (
            <>
              <Link to="/settings/profile" className={buttonClasses("primary", "sm")}>
                {line(t, "home.widget.dealersNear.setZip", "Update your profile")}
              </Link>
              <Link to="/dealers/find-agent" className={buttonClasses("ghost", "sm")}>
                {line(t, "home.widget.dealerFind", "Find a dealer")}
              </Link>
            </>
          ),
        };
      }
      if (near.state === "unknown_zip") {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.unknownZip",
              "We couldn't find the ZIP code in your profile address ({zip}). Check it in your profile and this widget will try again.",
              { zip: near.zip ?? "" },
            ),
          ],
          actions: (
            <>
              <Link to="/settings/profile" className={buttonClasses("primary", "sm")}>
                {line(t, "home.widget.dealersNear.setZip", "Update your profile")}
              </Link>
              <Link to="/dealers/find-agent" className={buttonClasses("ghost", "sm")}>
                {line(t, "home.widget.dealerFind", "Find a dealer")}
              </Link>
            </>
          ),
        };
      }
      if (near.state === "none_near" || near.results.length === 0) {
        return {
          lines: [
            line(
              t,
              "home.widget.dealersNear.noneNear",
              "No dealer agents within {radius} miles of {zip} yet. Find a dealer runs a wider search whenever you want one.",
              { radius: String(near.radius_miles), zip: near.zip ?? "" },
            ),
          ],
          actions: findDoor,
        };
      }
      const rows: WidgetRow[] = [];
      for (const agent of near.results) {
        for (const company of agent.companies) {
          rows.push({
            cells: [
              <span key="dealer" className="tv-near-dealer">
                <CompanyLogo
                  company={{
                    name: company.company_name,
                    logo_url: company.logo_url,
                    logo_tile: company.logo_tile,
                  }}
                  width={72}
                  height={40}
                />
                <span>{company.company_name}</span>
              </span>,
              <span key="agent" className="tv-near-agent">
                {agent.photo_url ? (
                  <img className="tv-near-photo" src={agent.photo_url} alt="" />
                ) : null}
                <span>{agent.display_name}</span>
              </span>,
              agent.covers_zip
                ? line(t, "home.widget.dealersNear.covers", "Covers your ZIP")
                : line(t, "dealers.findLocal.away", "≈ {miles} mi away", {
                    miles: String(agent.distance_miles),
                  }),
            ],
            href: `/dealers/${company.company_id}`,
          });
        }
      }
      const data: WidgetData = {
        lines: [
          line(t, "home.widget.dealersNear.within", "Dealer agents within {radius} miles of {place}", {
            radius: String(near.radius_miles),
            place: near.point?.display_name ?? near.zip ?? "",
          }),
        ],
        rowsClass: "tv-widget-rows--cols-near",
        rows: rows.slice(0, rowsToShow),
        actions: (
          <>
            {findDoor}
            <Link to="/dealers" className={buttonClasses("ghost", "sm")}>
              {line(t, "nav.dealers", "Dealer directory")}
            </Link>
          </>
        ),
      };
      if (ctx?.size === "full") {
        data.header = [
          line(t, "dealers.findLocal.col.companies", "Dealer"),
          line(t, "dealers.roster.col.name", "Agent"),
          line(t, "dealers.findLocal.col.distance", "Distance"),
        ];
      }
      return data;
    },
  },
  health_checks_due: {
    icon: <ArtIcon name="inventory" size={24} />,
    tone: "warning",
    cta: "open",
    path: "/inventory/health",
    // A NEW widget (widget wave 2, owner approval 2026-11-09):
    // OFF by default like the Dealers near you widget beside
    // it — nobody's stored Home is rearranged; Edit view's Add
    // menu and the widget gallery offer it. (It is
    // NOT a module widget in HOME_WIDGET_ORDER — the inventory
    // module already seats its own widget there; CorePage
    // seats this one as its own block gated on the inventory
    // module, the Dealers near you pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Health checks due (idea C#2): the items the Health
      // Check scan flags, read from /inventory/health-check-due
      // — the scan itself, verbatim, plus each item's photo
      // thumbnail. The scan has ONE definition of "needs a
      // check" (an ACTIVE item missing an identifier — a model
      // OR a serial satisfies it — a photo, or a purchase date;
      // a set's pieces missing serials surface under the set),
      // and this widget restates none of it: the headline and
      // the counts line are the Health Check page's own words,
      // the row's gap column is the page's own labels, and a
      // row's link is the page's own Fix-it target — the FIRST
      // gap's exact fix spot (gapTarget/firstGapTarget in
      // HealthCheckPage, mirrored here; the two must move
      // together). Nothing flagged is the quiet state: the
      // page's all-ready line and one plain explainer.
      const settings = ctx?.settings ?? {};
      const rowsToShow = optNum(settings, "rowsToShow", 4, 2, 6);
      const due = await api<HealthCheckDueResult>("/inventory/health-check-due");
      const openDoor = (primary: boolean) => (
        <Link
          to="/inventory/health"
          className={buttonClasses(primary ? "primary" : "ghost", "sm")}
        >
          {line(t, "home.widget.health.open", "Open health check")}
        </Link>
      );
      if (due.total === 0) {
        return {
          lines: [
            line(t, "inventory.health.allReady", "Everything is claim-ready."),
            line(
              t,
              "home.widget.health.explainer",
              "The health check scans your active items for the details a claim needs. When everything has them, this widget stays quiet.",
            ),
          ],
          actions: openDoor(false),
        };
      }
      const labelKeys: Record<string, string> = {
        identifier: "inventory.health.labelIdentifier",
        photo: "inventory.health.labelPhoto",
        purchase_date: "inventory.health.labelPurchase",
      };
      const countsLine = Object.entries(due.counts)
        .filter(([, n]) => n > 0)
        .map(([key, n]) =>
          line(t, "inventory.health.countsLine", "{count} missing {label}", {
            count: String(n),
            label: line(
              t,
              key === "piece_serial"
                ? "inventory.health.labelPieceSerial"
                : (labelKeys[key] ?? key),
              key,
            ).toLowerCase(),
          }),
        )
        .join(" · ");
      const gapTarget = (item: HealthCheckDueItem, gap: string): string => {
        const base =
          item.kind === "tool"
            ? `/inventory/${item.id}`
            : `/inventory/batteries/${item.id}`;
        if (gap === "photo") return `${base}#photos`;
        if (gap === "identifier") return `${base}/edit#fix-model`;
        if (gap === "purchase_date") return `${base}/edit#fix-purchase-date`;
        return `${base}/edit`;
      };
      const firstGapTarget = (item: HealthCheckDueItem): string => {
        if (item.missing.length > 0) return gapTarget(item, item.missing[0]);
        if (item.pieces_missing.length > 0)
          return `/inventory/${item.id}/edit#fix-piece-${item.pieces_missing[0].id}`;
        return gapTarget(item, "");
      };
      const rows: WidgetRow[] = due.items.map((item) => {
        const gaps = item.missing.map((key) =>
          line(t, labelKeys[key] ?? key, key),
        );
        if (item.pieces_missing.length > 0) {
          gaps.push(
            line(t, "inventory.health.labelPieceSerial", "Piece serials"),
          );
        }
        return {
          cells: [
            <span key="item" className="tv-health-item">
              {item.thumb_url_sm ? (
                <img className="tv-health-thumb" src={item.thumb_url_sm} alt="" />
              ) : null}
              <span>{item.name}</span>
            </span>,
            gaps.length > 0
              ? gaps.join(" · ")
              : line(
                  t,
                  "inventory.health.subLimit",
                  "Business use — your policy's sub-limit may cap this item",
                ),
          ],
          href: firstGapTarget(item),
        };
      });
      const data: WidgetData = {
        lines: [
          line(
            t,
            due.total === 1
              ? "inventory.health.needOne"
              : "inventory.health.needMany",
            due.total === 1
              ? "{count} item needs attention"
              : "{count} items need attention",
            { count: count(due.total) },
          ),
          ...(countsLine ? [countsLine] : []),
        ],
        rowsClass: "tv-widget-rows--cols-health",
        rows: rows.slice(0, rowsToShow),
        actions: openDoor(true),
      };
      if (ctx?.size === "full") {
        data.header = [
          line(t, "home.widget.colItem", "Item"),
          line(t, "inventory.health.panelTitle", "Needs attention"),
        ];
      }
      return data;
    },
  },
  quick_add: {
    icon: <ArtIcon name="search" size={24} />,
    tone: "info",
    cta: "open",
    path: "/inventory/new",
    // A NEW widget (widget wave 2 build 3, owner approval
    // 2026-11-09): OFF by default like Builds 1–2 beside it —
    // nobody's stored Home is rearranged; Edit view's Add menu
    // and the widget gallery offers it. (It is NOT a
    // module widget in HOME_WIDGET_ORDER — the inventory module
    // already seats its own widget there; CorePage seats this
    // one as its own block gated on the inventory module, the
    // Builds 1–2 pattern.)
    defaultOff: true,
    load: async (t, ctx) => {
      // Quick Add (idea C#3): the site's AI tool entry as a
      // Home door — one box: type a tool name, or drop a photo,
      // and the add wizard opens with the seed already in it.
      // The body rides the actions slot (the converter's seat),
      // above the whole-box cover, so its field, button and
      // drop zone take real clicks and drops. In Edit view the
      // frame hides the actions slot — the load then answers
      // with the explainer as a line, so the box describes
      // itself while it is arranged (the converter's pattern).
      if (ctx?.editing) {
        return {
          lines: [
            line(
              t,
              "home.widget.quickAdd.explainer",
              "Start the add wizard from here — type a tool name, or drop a photo and the wizard identifies it.",
            ),
          ],
        };
      }
      return { lines: [], actions: <QuickAddBox /> };
    },
  },
  account_plan: {
    icon: <ArtIcon name="money" size={24} />,
    tone: "info",
    cta: "open",
    path: "/settings/billing",
    // A NEW widget (widget wave 2 build 4, owner approval
    // 2026-11-09/10): OFF by default like Builds 1–3 beside it —
    // nobody's stored Home is rearranged; Edit view's Add menu
    // and the widget gallery offers it. CORE reach,
    // not a feature module: the widget reads the account's own
    // standing from /billing/me — always-on billing
    // infrastructure, deliberately ungated by modules (see
    // billing/routes.py) — plus /core/me for the tier, so
    // CorePage seats it for EVERY seat, the downloads rung
    // included: their plan IS the downloads level.
    defaultOff: true,
    load: async (t, ctx) => {
      // Account & Plan (idea C#4): the plan the account pages
      // themselves present (GET /billing/me is the exact read
      // Settings → Plan & billing renders — plan name, the
      // limit's OWN item count, the subscription record), the
      // tier from /core/me. Nothing is recomputed here: the
      // count is entitlements.asset_count, the same number the
      // free-tier limit enforces against, and a date shows only
      // when the subscription record itself carries one.
      //
      // Custom-widget aspect gates (Lane 2): every stat, note
      // line and button carries its own switch, all defaulting
      // ON — absence is today's widget, byte for byte; a
      // custom box picks the slices it wants.
      const settings = ctx?.settings ?? {};
      const showPlan = optBool(settings, "showPlan", true);
      const showAccount = optBool(settings, "showAccount", true);
      const showItems = optBool(settings, "showItems", true);
      const showRenewal = optBool(settings, "showRenewal", true);
      const showSource = optBool(settings, "showSource", true);
      const showManage = optBool(settings, "showManage", true);
      const showAccountBtn = optBool(settings, "showAccountBtn", true);
      const [view, me] = await Promise.all([
        api<AccountPlanView>("/billing/me"),
        api<{ tier: string; beta_tester: boolean; account_number: string }>(
          "/core/me",
        ),
      ]);
      const stats: WidgetStat[] = [];
      const lines: string[] = [];
      const rung = me.tier === "downloads";
      if (rung) {
        // The rung's plan is the downloads level itself. The
        // item limit counts inventory items (tools + batteries);
        // the rung's world is 3D print files, which the limit
        // never counts — a fraction would mislead, so the rung
        // gets the plan fact and its account number (the fact
        // support asks for), and no item stat at all.
        if (showPlan) {
          stats.push({
            label: line(t, "home.widget.accountPlan.statPlan", "Plan"),
            value: line(
              t,
              "home.widget.accountPlan.levelDownloads",
              "Downloads level",
            ),
          });
        }
        if (showAccount) {
          stats.push({
            label: line(t, "home.widget.accountPlan.statAccount", "Account"),
            value: me.account_number,
          });
        }
      } else {
        if (showPlan) {
          stats.push({
            label: line(t, "home.widget.accountPlan.statPlan", "Plan"),
            value: view.plan_name,
          });
        }
        if (showItems) {
          if (view.item_limit === null) {
            // A plan the limit does not bind: the count stands
            // plainly, no fraction is faked (the Plan & billing
            // page's own posture).
            stats.push({
              label: line(t, "home.widget.accountPlan.statItems", "Items"),
              value: count(view.items_total),
            });
            lines.push(
              line(
                t,
                "home.widget.accountPlan.noLimit",
                "No item limit on this plan.",
              ),
            );
          } else {
            stats.push({
              label: line(t, "home.widget.accountPlan.statItems", "Items"),
              value: line(
                t,
                "home.widget.accountPlan.itemsOf",
                "{count} of {limit}",
                {
                  count: count(view.items_total),
                  limit: count(view.item_limit),
                },
              ),
            });
            if (!view.enforcement_enabled) {
              lines.push(
                line(
                  t,
                  "home.widget.accountPlan.limitsAtLaunch",
                  "Item limits switch on at launch.",
                ),
              );
            }
          }
        }
        const renewal = accountPlanRenewal(view);
        if (showRenewal && renewal) {
          stats.push({
            label: line(t, renewal.key, renewal.fallback),
            value: formatDate(renewal.iso),
          });
        }
        const source = ACCOUNT_PLAN_SOURCES[view.source];
        if (showSource && source) {
          lines.push(line(t, source.key, source.fallback));
        }
        if (showSource && me.beta_tester) {
          lines.push(
            line(
              t,
              "home.widget.accountPlan.beta",
              "Beta tester — new features reach this account early.",
            ),
          );
        }
      }
      const buttons: ReactNode[] = [];
      if (rung) {
        if (showAccountBtn) {
          buttons.push(
            <Link
              key="account"
              to="/settings/profile"
              className={buttonClasses("primary", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.accountSettings",
                "Account settings",
              )}
            </Link>,
          );
        }
      } else {
        if (showManage) {
          buttons.push(
            <Link
              key="manage"
              to="/settings/billing"
              className={buttonClasses("primary", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.manage",
                "Manage subscription",
              )}
            </Link>,
          );
        }
        if (showAccountBtn) {
          buttons.push(
            <Link
              key="account"
              to="/settings/profile"
              className={buttonClasses("ghost", "sm")}
            >
              {line(
                t,
                "home.widget.accountPlan.accountSettings",
                "Account settings",
              )}
            </Link>,
          );
        }
      }
      return {
        lines,
        stats,
        actions: buttons.length > 0 ? <>{buttons}</> : undefined,
      };
    },
  },
  flyers: {
    icon: <ArtIcon name="flyers" size={24} />,
    tone: "accent",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Flyers (2026-11-06): thumbnail teasers of THIS WEEK's
      // flyers from the user's connected dealers/agents. The
      // options choose which sources show (hiddenSources holds
      // the unchecked ones; absence shows everything). A row
      // click lands on the flyer page at that source's tab.
      const settings = ctx?.settings ?? {};
      const raw = settings.hiddenSources;
      const hidden = new Set(Array.isArray(raw) ? raw : []);
      // Custom-widget aspect gates (Lane 2): the count line
      // and the source rows carry their own switches, both
      // defaulting ON — absence is today's widget exactly.
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const feed = await flyerFeed();
      const shown = feed.filter((s) => !hidden.has(s.key));
      const lines = showCount
        ? [
            shown.length === 1
              ? line(t, "flyers.widgetOne", "1 flyer up this week")
              : line(t, "flyers.widgetLive", "{count} flyers up this week", {
                  count: count(shown.length),
                }),
          ]
        : [];
      const data: WidgetData = { lines };
      if (showRows && shown.length > 0) {
        data.rowsVisible = 3;
        data.rows = shown.map((s) => ({
          cells: [
            <span key="who" className="flyer-widget-cell">
              {s.current?.thumb_url ? (
                <img
                  className="flyer-widget-thumb"
                  src={s.current.thumb_url}
                  alt=""
                />
              ) : null}
              <span>{sourceTitle(s)}</span>
            </span>,
            s.current?.label || `${s.current?.starts_on} → ${s.current?.ends_on}`,
          ],
          href: `/flyers#${s.key}`,
        }));
      }
      return data;
    },
  },
  reports: {
    icon: <ArtIcon name="reports" size={24} />,
    tone: "violet",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch A: the saved reports ride
      // as real rows — 2 visible before scrolling is today's
      // shape; the option takes it to 5. The list already loads
      // in full. Reports redesign (2026-11-06): the saved
      // reports are the page's TEMPLATES now — at full width
      // each row links to the tab that template lives on
      // (Quick Reports on #new, Accounting on #accounting); at
      // half width the rows stay names, and the box's own cover
      // link rules the click.
      const settings = ctx?.settings ?? {};
      const rowsVisible = optNum(settings, "rowsVisible", 2, 2, 5);
      // Custom-widget aspect gates (Lane 2): the count line
      // and the template rows carry their own switches, both
      // defaulting ON — absence is today's widget exactly.
      const showCount = optBool(settings, "showCount", true);
      const showRows = optBool(settings, "showRows", true);
      const { templates } = await listTemplates();
      const lines = showCount
        ? [
            line(t, "home.widget.savedReports", "{count} saved reports", { count: count(templates.length) }),
          ]
        : [];
      const data: WidgetData = { lines };
      if (showRows && templates.length > 0) {
        const full = ctx?.size === "full";
        data.rowsVisible = rowsVisible;
        data.rows = templates.map((c) =>
          full
            ? {
                cells: [c.name],
                href: c.area === "accounting" ? "/reports#accounting" : "/reports#new",
              }
            : { cells: [c.name] },
        );
      }
      return data;
    },
  },
  messaging: {
    icon: <ArtIcon name="messages" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the two count lines each get a switch,
      // and the newest conversation names ride under the
      // counts. That costs the design's ONE flagged extra
      // read — the conversation list the Messages page
      // loads — asked for only while the names are
      // switched on. At full width each row gains that
      // conversation's own unread count.
      const settings = ctx?.settings ?? {};
      const showUnread = optBool(settings, "showUnread", true);
      const showRequests = optBool(settings, "showRequests", true);
      const showConversations = optBool(settings, "showConversations", true);
      const u = await getUnread();
      const lines: string[] = [];
      if (showUnread) {
        lines.push(line(t, "home.widget.unread", "{count} unread messages", { count: count(u.inbox_unread) }));
      }
      if (showRequests) {
        lines.push(line(t, "home.widget.messageRequests", "{count} message requests", { count: count(u.requests_count) }));
      }
      const data: WidgetData = { lines };
      if (showConversations) {
        const threads = await listThreads("inbox");
        if (threads.length > 0) {
          const full = ctx?.size === "full";
          if (full) {
            data.header = [
              line(t, "home.widget.colConversation", "Conversation"),
              line(t, "home.widget.colUnread", "Unread"),
            ];
          }
          data.rowsClass = "tv-widget-rows--cols-messaging";
          data.rows = threads.slice(0, 5).map((th) => {
            const cells: ReactNode[] = [th.other_name];
            if (full) cells.push(th.unread_count > 0 ? count(th.unread_count) : "—");
            return { cells };
          });
        }
      }
      return data;
    },
  },
  forum: {
    icon: <ArtIcon name="forum" size={24} />,
    tone: "info",
    cta: "open",
    load: async (t, ctx) => {
      const cats = await getCategories(true);
      const threads = cats.reduce((n, c) => n + c.thread_count, 0);
      const lines = [
        line(t, "home.widget.boardsThreads", "{boards} boards · {threads} threads", {
          boards: count(cats.length),
          threads: count(threads),
        }),
      ];
      // Widget options Wave 3: the expanded view IS the
      // full-width mode — it features the member's favorite
      // thread (or board post): the one they picked in the
      // options, or the favorite that moved most recently
      // (the list arrives in that order). It costs the
      // design's ONE flagged extra read (the favorites list),
      // made only at full width, inside this same load. The
      // small view is byte-for-byte the counts view above.
      if (!ctx || ctx.size !== "full") return { lines };
      let favorites;
      try {
        favorites = await listFavorites();
      } catch {
        return { lines };
      }
      if (favorites.length === 0) {
        lines.push(
          line(
            t,
            "home.widget.favEmpty",
            "Star a thread in the forum and it will be featured here.",
          ),
        );
        return { lines };
      }
      const pick =
        typeof ctx.settings.featured === "string" ? ctx.settings.featured : "";
      const featured =
        favorites.find((f) => `${f.kind}:${f.target_id}` === pick) ??
        favorites[0];
      const data: WidgetData = {
        lines,
        header: [
          line(t, "forum.list.col.thread", "Thread"),
          line(t, "home.widget.favColBoard", "Board"),
          line(t, "forum.list.col.replies", "Replies"),
          line(t, "forum.list.col.lastActivity", "Last activity"),
        ],
        rowsClass: "tv-widget-rows--cols-forum",
        rows: [
          {
            cells: [
              featured.title,
              featured.board_name,
              count(featured.reply_count),
              formatDate(featured.last_activity_at),
            ],
            href:
              featured.kind === "thread"
                ? `/forum/thread/${featured.target_id}`
                : `/feedback/post/${featured.target_id}`,
          },
        ],
      };
      return data;
    },
  },
  feedback: {
    icon: <ArtIcon name="feedback" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the newest titles
      // from each board ride as rows — the boards already
      // load in full to count them, so the titles are in
      // hand. Rows are grouped per board: stacked at half
      // width, side by side as two titled columns at full.
      // Each row links to its post's own page. 0 per board
      // puts the rows away (today's counts-only widget).
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const perBoard = optNum(settings, "rowsPerBoard", 3, 0, 3);
      // Custom-widget aspect gates (Lane 2): each board's
      // rows carry their own switch, both defaulting ON —
      // absence is today's widget exactly.
      const showBugRows = optBool(settings, "showBugRows", true);
      const showFeatureRows = optBool(settings, "showFeatureRows", true);
      const [bugs, features] = await Promise.all([
        getBoard("bug", true),
        getBoard("feature", true),
      ]);
      const lines: string[] = [];
      if (showCounts) {
        lines.push(line(t, "home.widget.bugsFeatures", "{bugs} bug reports · {features} feature ideas", {
          bugs: count(bugs.length),
          features: count(features.length),
        }));
      }
      const data: WidgetData = { lines };
      if (perBoard > 0) {
        const groups: WidgetRowGroup[] = [];
        if (showBugRows && bugs.length > 0) {
          groups.push({
            label: line(t, "home.widget.feedbackBugs", "Bug reports"),
            rows: bugs.slice(0, perBoard).map((p) => ({
              cells: [p.title],
              href: `/feedback/post/${p.id}`,
            })),
          });
        }
        if (showFeatureRows && features.length > 0) {
          groups.push({
            label: line(t, "home.widget.feedbackFeatures", "Feature ideas"),
            rows: features.slice(0, perBoard).map((p) => ({
              cells: [p.title],
              href: `/feedback/post/${p.id}`,
            })),
          });
        }
        if (groups.length > 0) data.groups = groups;
      }
      return data;
    },
  },
  wishlist: {
    icon: <ArtIcon name="wishlist" size={24} />,
    tone: "slate",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B (parked — built in
      // the dark): the three lines each get a switch, and
      // the wanted items ride as rows — a few visible,
      // the rest scrolling inside the box. The rows take
      // the Latest line's place (the latest item is the
      // first row); putting the rows away (0) brings the
      // Latest line back. At full width each row carries
      // its priority marker beside the title. The full
      // list already loads to count it.
      const settings = ctx?.settings ?? {};
      const showWanted = optBool(settings, "showWanted", true);
      const showHigh = optBool(settings, "showHigh", true);
      const showLatest = optBool(settings, "showLatest", true);
      const wantedRows = optNum(settings, "wantedRows", 3, 0, 5);
      const items = await listWishlist();
      const wanted = items.filter((i) => i.status === "wanted");
      const lines: string[] = [];
      if (showWanted) {
        lines.push(line(t, "home.widget.wanted", "{count} wanted", { count: count(wanted.length) }));
      }
      const high = wanted.filter((i) => i.priority === "high").length;
      if (showHigh && high > 0) {
        lines.push(line(t, "home.widget.highPriority", "{count} high priority", { count: count(high) }));
      }
      const data: WidgetData = { lines };
      if (wantedRows > 0 && wanted.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "home.widget.colItem", "Item"),
            line(t, "home.widget.colPriority", "Priority"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-wishlist";
        data.rowsVisible = wantedRows;
        data.rows = wanted.map((i) => {
          const cells: ReactNode[] = [i.title];
          if (full) {
            cells.push(line(t, `home.widget.priority.${i.priority}`, i.priority));
          }
          return { cells };
        });
      } else if (showLatest && wanted[0]) {
        lines.push(line(t, "home.widget.latest", "Latest: {name}", { name: wanted[0].title }));
      }
      return data;
    },
  },
  tool_expansion: {
    icon: <ArtIcon name="expansion" size={24} />,
    tone: "accent",
    cta: "viewAll",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the count line gets
      // its switch, and how many suggestions ride is a
      // choice (2 is today's widget). Half width keeps
      // today's sentence lines; at full width the
      // suggestions line up as rows — the piece, and the
      // item of yours it expands — in two columns.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const rowsToShow = optNum(settings, "rowsToShow", 2, 2, 5);
      // Custom-widget aspect gate (Lane 2): the suggestion
      // rows/lines carry their own switch, defaulting ON —
      // absence is today's widget exactly.
      const showRows = optBool(settings, "showRows", true);
      const summary = await getExpansionSummary();
      const lines: string[] = [];
      if (showCount) {
        lines.push(
          t
            ? t("toolExpansion.widgetKnown" as never).replace(
                "{count}",
                count(summary.count),
              )
            : `${count(summary.count)} known addons for your tools`,
        );
      }
      const data: WidgetData = { lines };
      const tops = summary.top.slice(0, rowsToShow);
      if (showRows && tops.length > 0) {
        if (ctx?.size === "full") {
          data.header = [
            line(t, "toolExpansion.col.suggestedPiece", "Suggested piece"),
            line(t, "toolExpansion.expandsYour", "Expands your"),
          ];
          data.rowsClass = "tv-widget-rows--cols-expansion";
          data.rows = tops.map((top) => ({
            cells: [`${top.name} (${top.model_number})`, top.item_name],
          }));
        } else {
          for (const top of tops) {
            lines.push(
              t
                ? t("toolExpansion.widgetFor" as never)
                    .replace("{name}", top.name)
                    .replace("{model}", top.model_number)
                    .replace("{item}", top.item_name)
                : `${top.name} (${top.model_number}) — for your ${top.item_name}`,
            );
          }
        }
      }
      return data;
    },
  },
  truck_accounts: {
    icon: <ArtIcon name="truck" size={24} />,
    tone: "success",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 2: the accounts as real rows —
      // company, the agent holding the tab, the balance — with
      // the quick-entry form riding the actions slot (the
      // owner's named write action on Home, Decision 3: it
      // posts through the truck module's own entry door, the
      // exact endpoint the account page uses). The totals
      // lines above the rows are today's, unchanged; the old
      // per-tab text lines are what the rows replace.
      const settings = ctx?.settings ?? {};
      const quickEntry = optBool(settings, "quickEntry", true);
      const rowsVisible = optNum(settings, "rowsVisible", 3, 2, 6);
      // Custom-widget aspect gates (Lane 2): each glance line
      // and the rows carry their own switch, all defaulting ON
      // — absence is today's widget, byte for byte.
      const showOpenCount = optBool(settings, "showOpenCount", true);
      const showDueTotal = optBool(settings, "showDueTotal", true);
      const showOwed = optBool(settings, "showOwed", true);
      const showRows = optBool(settings, "showRows", true);
      const accounts = await listAccounts();
      const open = accounts.filter((a) => a.status !== "closed");
      const due = open.reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
      const lines: string[] = [];
      if (showOpenCount) {
        lines.push(line(t, "home.widget.openAccounts", "{count} open accounts", { count: count(open.length) }));
      }
      if (showDueTotal) {
        lines.push(line(t, "home.widget.balancesDue", "Balances due {value}", { value: formatMoney(String(due), null, true) }));
      }
      // Agent revision (2026-10-31): the glance names WHERE the
      // money sits. The dealer-seat total line survives as a
      // line exactly as today (it fires only when the viewer
      // holds no customer tab with a balance); the per-account
      // detail itself moved into the rows below.
      const myTabs = open.filter(
        (a) => a.my_role === "customer" && (Number(a.balance) || 0) > 0,
      );
      if (showOwed && myTabs.length === 0) {
        const owed = open
          .filter((a) => a.my_role === "dealer")
          .reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
        if (owed > 0) {
          lines.push(`Customers owe you ${formatMoney(String(owed), null, true)}`);
        }
      }
      const data: WidgetData = { lines };
      if (open.length > 0) {
        const full = ctx?.size === "full";
        const editing = ctx?.editing ?? false;
        // The customer's own tabs first (the owner's framing),
        // then the accounts they hold as dealer, biggest
        // balance first inside each seat.
        const roleRank = (a: TruckAccount): number =>
          a.my_role === "customer" ? 0 : a.my_role === "dealer" ? 1 : 2;
        const sorted = [...open].sort(
          (a, b) =>
            roleRank(a) - roleRank(b) ||
            (Number(b.balance) || 0) - (Number(a.balance) || 0),
        );
        const bus = createEntryBus();
        const active = sorted.filter((a) => a.status === "active");
        if (showRows && full) {
          data.header = [
            line(t, "home.widget.truck.account", "Account"),
            line(t, "claims.warranty.agent", "Agent"),
            line(t, "home.widget.truck.balance", "Balance"),
            line(t, "home.widget.truck.nextDue", "Next due"),
            "",
          ];
        }
        if (showRows) {
          data.rowsClass = "tv-widget-rows--cols-truck";
          data.rowsVisible = rowsVisible;
          data.rows = sorted.map((a) => {
          const face = truckAccountFace(a);
          // Stage 2: a tab with missed payments says so on its
          // row — missed shows as missed everywhere it appears.
          const missedSuffix =
            a.missed_payments > 0
              ? ` · ${line(t, "home.widget.truck.missed", "{count} missed", {
                  count: String(a.missed_payments),
                })}`
              : "";
          const cells: ReactNode[] = [
            face,
            full
              ? a.agent_name || "—"
              : a.agent_name
                ? `agent ${a.agent_name}`
                : "—",
            formatMoney(a.balance, a.currency, true) + missedSuffix,
          ];
          if (full) {
            cells.push(
              a.status === "active" ? formatDate(a.next_due_date) : "—",
            );
          }
          // The + Entry affordance: active accounts only (the
          // entry door refuses the rest), never in Edit view
          // (the box is being arranged there, and the form it
          // opens lives in the actions slot Edit view drops).
          if (quickEntry && a.status === "active" && !editing) {
            cells.push(
              <button
                key="entry"
                type="button"
                className="tv-widget-entry-btn"
                onClick={() => bus.open(a.id)}
              >
                {line(t, "home.widget.truck.addEntry", "+ Entry")}
              </button>,
            );
          } else if (full) {
            cells.push("");
          }
            return { cells };
          });
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
      return data;
    },
  },
  shared_tools: {
    icon: <ArtIcon name="shared" size={24} />,
    tone: "teal",
    cta: "open",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the two lines each
      // get a switch, and the people behind the counts ride
      // as name rows from the SAME overview — at half width
      // the "shared with you" names (the design's ask); at
      // full width both directions sit side by side as two
      // short lists. Email invites still out (no account to
      // name yet) stay out of the name rows, exactly as the
      // counts have always treated them.
      const settings = ctx?.settings ?? {};
      const showCounts = optBool(settings, "showCounts", true);
      const showInvites = optBool(settings, "showInvites", true);
      // Custom-widget aspect gates (Lane 2): the two name
      // lists carry their own switches, both defaulting ON —
      // absence is today's widget exactly.
      const showMine = optBool(settings, "showMine", true);
      const showWithMe = optBool(settings, "showWithMe", true);
      const o = await api<PeerOverview>("/core/sharing/peer");
      const mine = o.sharing_with.filter((g) => g.status === "accepted");
      const withMe = o.shared_with_me.filter((g) => g.status === "accepted");
      const lines: string[] = [];
      if (showCounts) {
        lines.push(line(t, "home.widget.sharingWith", "Sharing with {a} · {b} share with you", {
          a: count(mine.length),
          b: count(withMe.length),
        }));
      }
      if (showInvites && o.pending_for_me.length > 0) {
        lines.push(line(t, "home.widget.invitesWaiting", "{count} invites waiting on you", { count: count(o.pending_for_me.length) }));
      }
      const data: WidgetData = { lines };
      const groups: WidgetRowGroup[] = [];
      if (showMine && ctx?.size === "full") {
        const mineRows = mine
          .filter((g) => g.viewer !== null)
          .map((g) => ({ cells: [g.viewer!.name] }));
        if (mineRows.length > 0) {
          groups.push({
            label: line(t, "home.widget.youShareWith", "You share with"),
            rows: mineRows,
            visible: 4,
          });
        }
      }
      if (showWithMe && withMe.length > 0) {
        groups.push({
          label: line(t, "home.widget.sharedWithYou", "Shared with you"),
          rows: withMe.map((g) => ({ cells: [g.owner.name] })),
          visible: 4,
        });
      }
      if (groups.length > 0) data.groups = groups;
      return data;
    },
  },
  support: {
    icon: <ArtIcon name="support" size={24} />,
    tone: "warning",
    cta: "open",
    path: "/help",
    load: async (t, ctx) => {
      // Widget options Wave 4 batch B: the open tickets
      // ride as rows — subject, and at full width the last
      // time the ticket moved — each row a link into that
      // very ticket on the Help page (its ?ticket= deep
      // link, the standing door). The rows take the place
      // of today's single Latest line, as the Claims rows
      // did; the full list already loads to count them.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const rowsToShow = optNum(settings, "rowsToShow", 3, 1, 5);
      // Custom-widget aspect gate (Lane 2): the ticket rows
      // carry their own switch, defaulting ON — absence is
      // today's widget exactly.
      const showRows = optBool(settings, "showRows", true);
      const tickets = await listMyTickets();
      const open = tickets.filter((tk) => tk.status !== "closed");
      const lines: string[] = [];
      if (showCount) {
        lines.push(line(t, "home.widget.openTickets", "{count} open tickets", { count: count(open.length) }));
      }
      const data: WidgetData = { lines };
      if (showRows && open.length > 0) {
        const full = ctx?.size === "full";
        if (full) {
          data.header = [
            line(t, "home.widget.colSubject", "Subject"),
            line(t, "home.widget.colUpdated", "Last updated"),
          ];
        }
        data.rowsClass = "tv-widget-rows--cols-support";
        data.rows = open.slice(0, rowsToShow).map((tk) => {
          const cells: ReactNode[] = [tk.subject];
          if (full) cells.push(formatDateTime(tk.updated_at));
          return { cells, href: `/help?ticket=${tk.id}` };
        });
      }
      return data;
    },
  },
  prints: {
    icon: <ArtIcon name="parts" size={24} />,
    tone: "violet",
    cta: "viewAll",
    // A NEW widget (owner follow-up, 2026-11-09): it joins the
    // picker OFF for everyone who already has a Home — nobody's
    // stored layout is rearranged — except on the downloads
    // level, whose default Home seats it (CorePage's rung
    // assembly overrides the default there).
    defaultOff: true,
    load: async (t, ctx) => {
      // 3D Print Files widget REBUILT as a showcase
      // (dashboard-flare lane, owner order 2026-11-09): two
      // thumbnail strips from the module's OWN browse reads —
      // row 1 NEW UPLOADS (sort=newest), row 2 MOST DOWNLOADED
      // (sort=downloads) — each tile the listing's preview art
      // (or the module artwork), its title, and its rating or
      // download count underneath, one tap to the listing.
      // Ryan's two doors ride the actions slot beside the
      // member's Upload door: My Uploads (the shelf page's own
      // My tab, deep-linked) and 3D Files (the shelf itself).
      // The old text-row table retires: at any width this
      // widget is a showcase now — the shelf page is the list.
      const settings = ctx?.settings ?? {};
      const showCount = optBool(settings, "showCount", true);
      const showRatings = optBool(settings, "showRatings", true);
      const showUpload = optBool(settings, "showUpload", true);
      const showNew = optBool(settings, "showNew", true);
      const showTop = optBool(settings, "showTop", true);
      const showMine = optBool(settings, "showMine", true);
      // Custom-widget aspect gate (Lane 2): the always-on
      // "3D Files" door button carries its own switch,
      // defaulting ON — absence is today's widget exactly.
      const showFiles = optBool(settings, "showFiles", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 12);
      const [newest, top] = await Promise.all([
        browsePrints({ sort: "newest" }),
        browsePrints({ sort: "downloads" }).catch(() => null),
      ]);
      const lines: string[] = [];
      if (showCount) {
        lines.push(
          line(t, "home.widget.printsShared", "{count} print files shared", {
            count: count(newest.total),
          }),
        );
      }
      const data: WidgetData = { lines };
      const tile = (row: PrintFileRow, withRating: boolean) => ({
        thumb: row.has_preview ? previewUrl(row.id) : undefined,
        icon: <ArtIcon name="parts" size={30} />,
        title: row.title,
        sub:
          withRating && row.rating.count > 0 && row.rating.average !== null
            ? `★ ${row.rating.average.toFixed(1)} (${count(row.rating.count)})`
            : count(row.download_count),
        href: `/3dprints/${row.id}`,
      });
      const strips: WidgetStrip[] = [];
      if (showNew && newest.files.length > 0) {
        strips.push({
          label: line(t, "home.widget.printsNew", "New uploads"),
          tiles: newest.files.slice(0, tilesToShow).map((row) => tile(row, showRatings)),
        });
      }
      if (showTop && top && top.files.length > 0) {
        strips.push({
          label: line(t, "home.widget.printsTop", "Most downloaded"),
          tiles: top.files.slice(0, tilesToShow).map((row) => tile(row, false)),
        });
      }
      if (strips.length > 0) data.strips = strips;
      const buttons: ReactNode[] = [];
      if (showUpload) {
        // A real inner control in the actions layer (the
        // inventory Add-Item precedent): publishing is the
        // module's member door, one tap from the dashboard.
        buttons.push(
          <Link key="up" to="/3dprints/upload" className={buttonClasses("primary", "sm")}>
            {line(t, "prints.upload", "Upload a print file")}
          </Link>,
        );
      }
      if (showMine) {
        buttons.push(
          <Link key="mine" to="/3dprints#my" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.printsMine", "My Uploads")}
          </Link>,
        );
      }
      if (showFiles) {
        buttons.push(
          <Link key="all" to="/3dprints" className={buttonClasses("ghost", "sm")}>
            {line(t, "home.widget.printsFiles", "3D Files")}
          </Link>,
        );
      }
      if (buttons.length > 0) data.actions = <>{buttons}</>;
      return data;
    },
  },
  downloads: {
    icon: <ArtIcon name="downloads" size={24} />,
    tone: "info",
    cta: "open",
    path: "/downloads",
    load: async (t, ctx) => {
      // Downloads widget REBUILT (dashboard-flare lane, owner
      // order 2026-11-09). Still NOT a module widget — Downloads
      // is a plain ungated door, seated as its own block in
      // CorePage. The shape is now the glanceable one Ryan
      // ordered: (b) a STATS GRID of the shelf's facts
      // (documents, wallpapers, 3D print files, total
      // downloads), (a) a thumbnail strip of the TOP DOWNLOADS
      // THIS WEEK from the dated download record (migration
      // 0098's download_events, read through
      // /downloads/top-window) — while that record is younger
      // than a week the strip labels itself "since <date>",
      // never a dressed-up week, and with no events at all it
      // says the chart starts with the first download instead
      // of inventing a ranking; and (c) an Open Downloads
      // button. The old cumulative most-downloaded lists retire
      // here (the page itself still ranks all-time); names ride
      // the shelf's dictionary copy, exactly as the page
      // speaks them.
      const settings = ctx?.settings ?? {};
      const showStats = optBool(settings, "showStats", true);
      const showWeekly = optBool(settings, "showWeekly", true);
      const tilesToShow = optNum(settings, "tilesToShow", 8, 4, 12);
      // Custom-widget aspect gate (Lane 2): the Open
      // Downloads button carries its own switch, defaulting
      // ON — absence is today's widget exactly.
      const showDoor = optBool(settings, "showDoor", true);
      const [catalog, shelf, topWindow, prints] = await Promise.all([
        api<{
          files: {
            key: string;
            format: string;
            filename: string;
            download_count: number;
          }[];
        }>("/downloads/catalog"),
        api<{
          wallpapers: {
            key: string;
            branded: boolean;
            download_count: number;
          }[];
        }>("/downloads/wallpapers"),
        api<{
          window_days: number;
          tracking_since: string | null;
          items: { key: string; kind: string; count: number }[];
        }>("/downloads/top-window"),
        browsePrints({}).catch(() => null),
      ]);
      const data: WidgetData = { lines: [] };
      const total =
        catalog.files.reduce((sum, f) => sum + f.download_count, 0) +
        shelf.wallpapers.reduce((sum, w) => sum + w.download_count, 0);
      if (showStats) {
        const stats: WidgetStat[] = [
          {
            label: line(t, "home.widget.dlStatDocuments", "Documents"),
            value: count(catalog.files.length),
          },
          {
            label: line(t, "home.widget.dlStatWallpapers", "Wallpapers"),
            value: count(shelf.wallpapers.length),
          },
        ];
        if (prints) {
          stats.push({
            label: line(t, "home.widget.dlStatPrints", "3D print files"),
            value: count(prints.total),
          });
        }
        stats.push({
          label: line(t, "home.widget.dlStatDownloads", "Downloads"),
          value: count(total),
        });
        data.stats = stats;
      }
      if (showWeekly) {
        const docByKey = new Map(catalog.files.map((f) => [f.key, f]));
        const items = topWindow.items.slice(0, tilesToShow);
        if (items.length > 0) {
          const since = topWindow.tracking_since
            ? new Date(topWindow.tracking_since)
            : null;
          const fullWeek =
            since != null &&
            Date.now() - since.getTime() >= 7 * 24 * 3600 * 1000;
          data.strips = [
            {
              label: fullWeek
                ? line(t, "home.widget.dlTopWeek", "Top downloads · last 7 days")
                : line(t, "home.widget.dlTopSince", "Top downloads since {date}", {
                    date: since ? formatDate(since.toISOString()) : "",
                  }),
              tiles: items.map((item) =>
                item.kind === "wallpaper"
                  ? {
                      thumb: `/api/downloads/wallpapers/${item.key}/view/thumb`,
                      icon: <ArtIcon name="downloads" size={30} />,
                      title: line(
                        t,
                        `downloads.wallpaper.${item.key}.name`,
                        item.key,
                      ),
                      sub: count(item.count),
                      href: "/downloads#wallpapers",
                    }
                  : {
                      icon: <ArtIcon name="downloads" size={30} />,
                      title: line(
                        t,
                        `downloads.file.${item.key}.name`,
                        docByKey.get(item.key)?.filename ?? item.key,
                      ),
                      sub: count(item.count),
                      href: "/downloads#documents",
                    },
              ),
            },
          ];
        } else if (topWindow.tracking_since) {
          data.lines.push(
            line(
              t,
              "home.widget.dlTopEmptyWeek",
              "Nothing has been downloaded in the last 7 days.",
            ),
          );
        } else {
          data.lines.push(
            line(
              t,
              "home.widget.dlTopEmptyStart",
              "The weekly chart starts with the first download.",
            ),
          );
        }
      }
      if (showDoor) {
        data.actions = (
          <Link to="/downloads" className={buttonClasses("primary", "sm")}>
            {line(t, "home.widget.dlOpen", "Open Downloads")}
          </Link>
        );
      }
      return data;
    },
  },
  converter: {
    icon: <ArtIcon name="converter" size={24} />,
    tone: "info",
    cta: "open",
    path: "/downloads#documents",
    load: async (t, ctx) => {
      // Converter widget (owner 2026-11-08): NOT a module widget —
      // the Downloads converter as a pinnable Home widget, seated
      // as its own block in CorePage (the board-widgets pattern)
      // but rendered through this frame like every module widget.
      // The body is the SAME ConverterBody the Downloads panel
      // renders: one component, one math, nothing to drift. It
      // rides the actions slot (the truck quick entry's seat),
      // above the whole-box cover, so its fields take real
      // clicks. In Edit view the frame hides the actions slot —
      // the load then answers with the converter's own sub as a
      // line, so the box describes itself while it is arranged.
      if (ctx?.editing) {
        return {
          lines: [
            line(
              t,
              "downloads.conv.sub",
              "The readings a shop converts every day — pick a kind, type a number, get the rest.",
            ),
          ],
        };
      }
      return {
        lines: [],
        actions: (
          <ConverterBody variant="widget" size={ctx?.size ?? "half"} />
        ),
      };
    },
  },
};

/** Widget module ids in default display order (the module's own
 *  nav order governs the rail; Home's default widget order puts
 *  the daily-driver modules first). */
export const HOME_WIDGET_ORDER = [
  "inventory",
  "marketplace",
  "borrowing",
  "maintenance",
  "disaster_claims",
  "messaging",
  "parts",
  "shared_tools",
  "dealers",
  "flyers",
  "reports",
  "forum",
  "wishlist",
  "tool_expansion",
  "truck_accounts",
  "feedback",
  "support",
  "prints",
];

/** Whether a loaded widget has anything at all to show —
 *  lines, structured rows, row groups, trailing lines, or an
 *  actions slot (a headline alone is not content: it never
 *  has been). */
function hasWidgetContent(data: WidgetData): boolean {
  return (
    data.lines.length > 0 ||
    (data.rows?.length ?? 0) > 0 ||
    (data.groups?.length ?? 0) > 0 ||
    (data.linesAfter?.length ?? 0) > 0 ||
    (data.stats?.length ?? 0) > 0 ||
    (data.strips?.length ?? 0) > 0 ||
    data.actions != null
  );
}

/**
 * The stats grid (dashboard-flare lane): identical cells in a
 * uniform grid, wearing the header facts treatment (widget
 * uniformity lane, 2026-11-10; register corrected by fix 5,
 * 2026-11-11): the label rides on top in small caps, the
 * value below it, left-aligned as one unit — the facts
 * register the Header Studio's stage facts wear
 * (.tv-fact-label / .tv-fact-value, seated for a cell by
 * .tv-widget-stat-label / .tv-widget-stat-value in
 * theme/widget-kit.css) — so a widget's headline facts read
 * at a glance and line up with the header facts above them
 * and with every other widget.
 */
function WidgetStatsView({ stats }: { stats: WidgetStat[] }) {
  return (
    <div className="tv-widget-stats">
      {stats.map((stat, i) => (
        <div key={i} className="tv-widget-stat">
          <span className="tv-widget-stat-label">{stat.label}</span>
          <span className="tv-widget-stat-value">{stat.value}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * One showcase strip (dashboard-flare lane): tiles in a
 * sideways-scrolling row — the visible few, the rest a scroll
 * away. Tiles render in the widget's interactive layer, above
 * the whole-box cover, and go inert in Edit view like every
 * other inner link.
 */
function WidgetStripView({
  strip,
  editing,
}: {
  strip: WidgetStrip;
  editing: boolean;
}) {
  return (
    <div className="tv-widget-strip-wrap">
      {strip.label && (
        <div className="tv-widget-group-label">{strip.label}</div>
      )}
      <div className="tv-widget-strip">
        {strip.tiles.map((tile, i) => {
          const body = (
            <>
              <span
                className="tv-widget-tile-thumb"
                data-dark={tile.darkTile || undefined}
                data-bare={tile.thumbNode ? true : undefined}
                aria-hidden="true"
              >
                {tile.thumbNode ??
                  (tile.thumb ? (
                    <img src={tile.thumb} alt="" loading="lazy" />
                  ) : (
                    tile.icon
                  ))}
              </span>
              <span className="tv-widget-tile-title">{tile.title}</span>
              {tile.sub && (
                <span className="tv-widget-tile-sub">{tile.sub}</span>
              )}
            </>
          );
          return editing ? (
            <div key={i} className="tv-widget-tile">
              {body}
            </div>
          ) : (
            <Link key={i} to={tile.href} className="tv-widget-tile">
              {body}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/**
 * One widget row set (widget options Waves 1–2): the column
 * headings (full width only, where the rows take their table
 * shape) over the rows themselves. The rows list caps at
 * `visible` rows when the loader asks — the rest scroll
 * inside the box, the Notifications pattern. Rows render in
 * the widget's interactive layer, above the whole-box cover;
 * a row's href drops in Edit view, where a box never
 * navigates.
 */
function WidgetRowsView({
  rows,
  visible,
  header,
  rowsClass,
  size,
  editing,
}: {
  rows: WidgetRow[];
  visible?: number;
  header?: ReactNode[];
  rowsClass?: string;
  size: BlockSize;
  editing: boolean;
}) {
  const capped = visible != null && rows.length > visible;
  return (
    <div
      className={["tv-widget-rowset", rowsClass ?? ""].filter(Boolean).join(" ")}
      data-size={size}
    >
      {header && size === "full" && (
        <div className="tv-widget-row tv-widget-row--head" aria-hidden="true">
          {header.map((cell, j) => (
            <span key={j} className="tv-widget-cell">
              {cell}
            </span>
          ))}
        </div>
      )}
      <div
        className={["tv-widget-rows", capped ? "tv-widget-rows--capped" : ""]
          .filter(Boolean)
          .join(" ")}
        data-visible={capped ? visible : undefined}
      >
        {rows.map((row, i) =>
          row.href && !editing ? (
            <Link
              key={i}
              to={row.href}
              className="tv-widget-row tv-widget-row--link"
            >
              {row.cells.map((cell, j) => (
                <span key={j} className="tv-widget-cell">
                  {cell}
                </span>
              ))}
            </Link>
          ) : (
            <div key={i} className="tv-widget-row">
              {row.cells.map((cell, j) => (
                <span key={j} className="tv-widget-cell">
                  {cell}
                </span>
              ))}
            </div>
          ),
        )}
      </div>
    </div>
  );
}

export function HomeWidget({
  moduleId,
  title,
  path,
  editing = false,
  size,
  settings,
  bare = false,
  onContent,
}: {
  moduleId: string;
  title: string;
  path: string;
  /** Home Edit view: the box must NEVER navigate while
   *  customizing (owner 2026-11-02) — the CTA renders as an
   *  inert span with the button's face, the Overview stat
   *  hrefs drop in their edit rendering the same way. */
  editing?: boolean;
  /** Framework plumbing (widget options Wave 1): the block's
   *  resolved grid width and its options bundle, resolved by
   *  the layout and handed down so the content waves can read
   *  their options without re-plumbing CorePage. Wave 2's
   *  named four read both, through the load context below. */
  size?: BlockSize;
  settings?: Record<string, BlockSettingValue>;
  /** Custom-widget composition (Lane 2): render ONLY the
   *  sections — no Panel, no head — because the composite
   *  box carries its own. An empty load renders nothing at
   *  all (the composite decides the box's empty state), and
   *  `onContent` reports whether anything rendered so the
   *  composite can tell. Standalone renders are untouched. */
  bare?: boolean;
  onContent?: (hasContent: boolean) => void;
}) {
  const t = useT();
  const def = HOME_WIDGETS[moduleId];
  const [data, setData] = useState<WidgetData | null>(null);
  const [failed, setFailed] = useState(false);
  // A widget may ask for its own reload after it changes its
  // data (the truck quick entry posts, then the rows re-read
  // so the balances update in place — no skeleton flash: the
  // old data stays up until the fresh load lands).
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const settingsKey = JSON.stringify(settings ?? {});
  const onContentRef = useRef(onContent);
  onContentRef.current = onContent;

  useEffect(() => {
    if (!def) return;
    let live = true;
    const ctx: WidgetLoadCtx = {
      size: size ?? "half",
      settings: settings ?? {},
      editing,
      reload,
    };
    def
      .load(t as never, ctx)
      .then((d) => {
        if (live) {
          setData(d);
          onContentRef.current?.(hasWidgetContent(d));
        }
      })
      .catch(() => {
        if (live) {
          setFailed(true);
          // The failure line itself renders — the body is not
          // "empty" for the composite's accounting.
          onContentRef.current?.(true);
        }
      });
    return () => {
      live = false;
    };
    // The load re-runs when the block's width or options
    // change — in Edit view the widget behind the popover
    // reshapes live, the design's promise; at rest, after a
    // save. `settings` itself is read through settingsKey
    // (its identity changes with every layout render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def, tick, size, settingsKey, editing]);

  if (!def) return null;
  // The sections under the head — one computation shared by
  // the standalone render (Panel + head below) and the bare
  // render a custom-widget composite asks for (sections only,
  // and nothing at all when the load came back empty: the
  // composite owns the box's empty state).
  const body = failed ? (
    <p className="tv-muted">{t("home.widgetLoadFailed")}</p>
  ) : data === null ? (
    <QuietSkeleton lines={2} />
  ) : !hasWidgetContent(data) ? (
    bare ? null : <p className="tv-muted">{t("home.widgetEmpty")}</p>
  ) : (
    <>
          {(data.headline || data.lines.length > 0) && (
            <div className="tv-widget-lines">
              {data.headline && <p className="tv-widget-headline">{data.headline}</p>}
              {data.lines.map((line, i) => (
                <p key={i} className="tv-widget-line">
                  {line}
                </p>
              ))}
            </div>
          )}
          {(data.stats?.length ?? 0) > 0 && (
            <WidgetStatsView stats={data.stats!} />
          )}
          {(data.strips?.length ?? 0) > 0 &&
            data.strips!.map((strip, si) => (
              <WidgetStripView key={si} strip={strip} editing={editing} />
            ))}
          {(data.rows?.length ?? 0) > 0 && (
            <WidgetRowsView
              rows={data.rows!}
              visible={data.rowsVisible}
              header={data.header}
              rowsClass={data.rowsClass}
              size={size ?? "half"}
              editing={editing}
            />
          )}
          {(data.groups?.length ?? 0) > 0 && (
            <div
              className="tv-widget-groups"
              data-side={
                (size ?? "half") === "full" && data.groups!.length > 1
                  ? "true"
                  : undefined
              }
            >
              {data.groups!.map((group, gi) => (
                <div key={gi} className="tv-widget-group">
                  {group.label && (
                    <div className="tv-widget-group-label">{group.label}</div>
                  )}
                  <WidgetRowsView
                    rows={group.rows}
                    visible={group.visible}
                    header={group.header}
                    rowsClass={group.rowsClass}
                    size={size ?? "half"}
                    editing={editing}
                  />
                </div>
              ))}
            </div>
          )}
          {(data.linesAfter?.length ?? 0) > 0 && (
            <div className="tv-widget-lines">
              {data.linesAfter!.map((lineText, i) => (
                <p key={i} className="tv-widget-line">
                  {lineText}
                </p>
              ))}
            </div>
          )}
          {/* The actions slot renders only at rest: in Edit
           *  view the box is being arranged, so its controls go
           *  inert like the CTA and the row links above. */}
          {data.actions != null && !editing && (
            <div className="tv-widget-actions">{data.actions}</div>
          )}
    </>
  );
  if (bare) return body;
  return (
    <Panel className="tv-home-widget">
      {/* The whole-box cover link is RETIRED (dashboard redesign
       * 2026-11-10, design §4.2.3): the doors are honest and
       * separate — the title is a real link to the module, rows
       * keep their own links, and the box's ⛶/⋯ chrome never
       * fights a cover for the click. The head's "Open →" /
       * "View all →" button is ALSO retired (Ryan, 2026-11-10
       * 17:29): widgets don't need it — the title carries the
       * door. In the retired Edit view the doors rendered
       * inert; that mode no longer exists — the shell always
       * renders live — but the `editing` prop keeps its old
       * neutered rendering for any future caller. */}
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone={def.tone} aria-hidden="true">
          {def.icon}
        </span>
        <h3 className="tv-widget-title">
          {editing ? (
            title
          ) : (
            <Link to={path} className="tv-widget-title-link">
              {title}
            </Link>
          )}
        </h3>
      </div>
      {body}
    </Panel>
  );
}
