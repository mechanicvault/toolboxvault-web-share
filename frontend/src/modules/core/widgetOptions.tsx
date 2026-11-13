import { Fragment, useEffect, useState, type ReactNode } from "react";

import { Checkbox } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api as fetchApi } from "../../lib/api";
import type {
  BlockSettingValue,
  ResolvedBlock,
} from "../../lib/usePageLayout";
import { listSources as listFlyerSources } from "../flyers/api";
import { sourceTitle, type FlyerSource } from "../flyers/types";
import { listFavorites } from "../forum/api";
import type { ForumFavorite } from "../forum/types";

/**
 * WIDGET OPTIONS REGISTRY (widget options program, owner design
 * 2026-11-02): the per-widget option sections that appear in a
 * Home block's Edit-view options popover, keyed by BLOCK key
 * ("widget:maintenance", "notifications", "overview", ...). The
 * popover itself (components/PageBlocks) owns the universal
 * section — the Half | Full width choice every block carries;
 * a widget with something of its own to choose registers a
 * section here and the popover renders it under the width
 * choice, live-editing the same Edit-view draft (Save keeps
 * the changes, Cancel throws them away).
 *
 * Wave 1 shipped this registry EMPTY on purpose: the framework
 * (per-block size, the popover, the settings plumbing through
 * the layout store) landed first, proven end to end. Wave 2
 * registers the owner's named four — Inventory, Borrowing,
 * Claims, Truck accounts — and Waves 3–4 plug the rest in the
 * same way, without touching the popover, the layout hook, or
 * the store.
 *
 * SETTINGS DISCIPLINE: a widget's options are flat leaves in
 * the block's settings bundle (the layout store's sanitizer
 * bounds them server-side). Absence is the unset state, so a
 * control writes `undefined` when the user picks the default —
 * a saved bundle only ever carries real choices. The loaders
 * in homeWidgets read through the same two helpers below with
 * the same defaults, so the popover and the widget can never
 * disagree about what an absent key means.
 */
export interface WidgetOptionsApi {
  /** The block being edited (its draft state: size + settings). */
  block: ResolvedBlock;
  /** Write one option into the block's draft settings bundle;
   *  undefined removes the key — absence is the unset state. */
  setSetting: (name: string, value: BlockSettingValue | undefined) => void;
}

export interface WidgetOptionsDef {
  render: (api: WidgetOptionsApi) => ReactNode;
}

/** A boolean option read through the store's unset rule:
 *  a stored boolean wins; anything else means the default. */
export function optBool(
  settings: Record<string, BlockSettingValue>,
  name: string,
  dflt: boolean,
): boolean {
  const v = settings[name];
  return typeof v === "boolean" ? v : dflt;
}

/** A numeric option, clamped to its control's range: a stored
 *  number wins inside [min, max]; anything else is the default. */
export function optNum(
  settings: Record<string, BlockSettingValue>,
  name: string,
  dflt: number,
  min: number,
  max: number,
): number {
  const v = settings[name];
  if (typeof v !== "number" || !Number.isFinite(v)) return dflt;
  return Math.min(max, Math.max(min, Math.round(v)));
}

/** One labeled group inside a widget's popover section — the
 *  same plate language as the popover's own width group. */
function OptionsGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="tv-block-opts-group">
      <span className="tv-block-opts-label">{label}</span>
      {children}
    </div>
  );
}

/** A checkbox row in a widget's section. Picking the default
 *  clears the key (absence = unset), like every store field. */
function CheckRow({
  label,
  settings,
  name,
  dflt,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: boolean;
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const checked = optBool(settings, name, dflt);
  return (
    <Checkbox
      label={label}
      checked={checked}
      onChange={(e) =>
        setSetting(name, e.target.checked === dflt ? undefined : e.target.checked)
      }
    />
  );
}

/** A small segmented count choice (the width choice's own
 *  machined track): the numbers this option may take. Picking
 *  the default clears the key, like CheckRow. */
function CountRow({
  label,
  settings,
  name,
  dflt,
  min,
  max,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: number;
  min: number;
  max: number;
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const value = optNum(settings, name, dflt, min, max);
  const choices: number[] = [];
  for (let n = min; n <= max; n += 1) choices.push(n);
  return (
    <OptionsGroup label={label}>
      <div className="tv-opts-size" role="group" aria-label={label}>
        {choices.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            onClick={() => setSetting(name, n === dflt ? undefined : n)}
          >
            {n}
          </button>
        ))}
      </div>
    </OptionsGroup>
  );
}

/** A segmented choice over an explicit set of numbers (Wave 4
 *  batch A): the Notifications rows cap takes 3 / 5 / 8 — not a
 *  contiguous range — so CountRow's min..max sweep can't speak
 *  for it. Same machined track, same unset rule: picking the
 *  default clears the key. */
function ChoicesRow({
  label,
  settings,
  name,
  dflt,
  choices,
  setSetting,
}: {
  label: string;
  settings: Record<string, BlockSettingValue>;
  name: string;
  dflt: number;
  choices: number[];
  setSetting: WidgetOptionsApi["setSetting"];
}) {
  const raw = settings[name];
  const value =
    typeof raw === "number" && choices.includes(raw) ? raw : dflt;
  return (
    <OptionsGroup label={label}>
      <div className="tv-opts-size" role="group" aria-label={label}>
        {choices.map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={value === n}
            onClick={() => setSetting(name, n === dflt ? undefined : n)}
          >
            {n}
          </button>
        ))}
      </div>
    </OptionsGroup>
  );
}

/** Inventory (Wave 2): the Add Item button, the three lines,
 *  and how many recently added items ride along. Defaults are
 *  today's widget exactly: lines on, no button, latest only. */
function InventoryOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.inventory.addButton")}
          settings={s}
          name="addButton"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.valueLine")}
          settings={s}
          name="showValue"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.latestLine")}
          settings={s}
          name="showLatest"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.inventory.recentCount")}
        settings={s}
        name="recentCount"
        dflt={1}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Borrowing (Wave 2): the lent / borrowed lists, the overdue
 *  names, the requests line, and how many rows show before a
 *  list scrolls inside the box (the owner's default: 3). */
function BorrowingOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.borrowing.lentList")}
          settings={s}
          name="lentList"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.borrowedList")}
          settings={s}
          name="borrowedList"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.overdueNames")}
          settings={s}
          name="overdueNames"
          dflt={false}
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.borrowing.requestsLine")}
          settings={s}
          name="requestsLine"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={3}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Disaster Claims (claims separation, 2026-11-05): the
 *  claims widget's options for the insurance section — recent
 *  rows + the Open / History buttons. */
function DisasterClaimsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.disasterClaims.showButtons")}
          settings={s}
          name="showButtons"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.disasterClaims.recentCount")}
        settings={s}
        name="recentCount"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Truck accounts (Wave 2): the quick-entry buttons (the
 *  owner's named write action — on by default; the account
 *  page's own door and rules decide every post) and how many
 *  account rows show before the list scrolls. */
function TruckOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.truck.quickEntry")}
          settings={s}
          name="quickEntry"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.accountsBeforeScroll")}
        settings={s}
        name="rowsVisible"
        dflt={3}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Forum (Wave 3): which favorite the expanded (full-width)
 *  widget features. The choices are the member's own favorites,
 *  fetched once when the popover opens (the design's flagged
 *  extra read — the same list the widget itself reads). "Most
 *  recent activity" is the default and stores nothing; picking
 *  a favorite stores its kind:id key. A stored pick whose
 *  target later becomes invisible is never an error: the
 *  widget falls back to the next favorite, then the empty
 *  state, on its own. */
function ForumOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const [favorites, setFavorites] = useState<ForumFavorite[] | null>(null);
  useEffect(() => {
    let live = true;
    listFavorites()
      .then((favs) => {
        if (live) setFavorites(favs);
      })
      .catch(() => {
        if (live) setFavorites([]);
      });
    return () => {
      live = false;
    };
  }, []);
  const pick =
    typeof api.block.settings.featured === "string"
      ? api.block.settings.featured
      : "";
  return (
    <OptionsGroup label={t("home.opt.forum.featured")}>
      <div className="tv-fav-picks">
        <button
          type="button"
          className="tv-fav-pick"
          aria-pressed={pick === ""}
          onClick={() => api.setSetting("featured", undefined)}
        >
          <span className="tv-fav-pick-title">
            {t("home.opt.forum.mostRecent")}
          </span>
        </button>
        {(favorites ?? []).map((f) => {
          const key = `${f.kind}:${f.target_id}`;
          return (
            <button
              key={key}
              type="button"
              className="tv-fav-pick"
              aria-pressed={pick === key}
              onClick={() => api.setSetting("featured", key)}
            >
              <span className="tv-fav-pick-title">{f.title}</span>
              <span className="tv-fav-pick-board">{f.board_name}</span>
            </button>
          );
        })}
      </div>
      {favorites !== null && favorites.length === 0 && (
        <p className="tv-muted">{t("home.opt.forum.none")}</p>
      )}
    </OptionsGroup>
  );
}

/** Notifications (Wave 4 batch A): how many rows show before
 *  the list scrolls inside the block (3 / 5 / 8 — 5 is today's
 *  cap), the maintenance overdue line, and unread-only. The
 *  block itself reads the same keys through the same helpers;
 *  defaults are today's block exactly. */
function NotificationsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <ChoicesRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="rowsBeforeScroll"
        dflt={5}
        choices={[3, 5, 8]}
        setSetting={api.setSetting}
      />
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.notifications.overdueLine")}
          settings={s}
          name="overdueLine"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.notifications.unreadOnly")}
          settings={s}
          name="unreadOnly"
          dflt={false}
          setSetting={api.setSetting}
        />
      </OptionsGroup>
    </>
  );
}

/** Dealer dashboard (Wave 4 batch A): which of the dashboard's
 *  sections appear — the profile strip and the five registered
 *  sections, each with the same in-place checkbox Overview's
 *  stat tiles use. Every section defaults on (today's stack);
 *  the dashboard reads the same keys. */
function DealerDashboardOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const rows: { name: string; label: string }[] = [
    { name: "showProfile", label: t("home.opt.dealer.profile") },
    { name: "showWarrantyRequests", label: t("home.opt.dealer.warrantyRequests") },
    { name: "showWarrantyClaims", label: t("home.opt.dealer.warrantyClaims") },
    { name: "showTruckAccounts", label: t("home.opt.dealer.truckAccounts") },
    { name: "showPaymentsDue", label: t("home.opt.dealer.paymentsDue") },
    { name: "showRoute", label: t("home.opt.dealer.route") },
  ];
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      {rows.map((row) => (
        <CheckRow
          key={row.name}
          label={row.label}
          settings={s}
          name={row.name}
          dflt
          setSetting={api.setSetting}
        />
      ))}
    </OptionsGroup>
  );
}

/** Maintenance (Wave 4 batch A): the two count lines are
 *  individually hideable (both on = today's combined line), the
 *  coming-up list can step aside for today's single Next line,
 *  and its rows show 1–5 before scrolling.
 *
 *  Claims merge (2026-11-06): the retired Claims widget's
 *  choices live here now — the open-claims line, the
 *  backordered line, the recent-claims list with its row
 *  count, and the Repair claims / history buttons. Every one
 *  defaults ON, the union of what the two widgets showed. */
function MaintenanceOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.maintenance.dueLine")}
          settings={s}
          name="showDue"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.outLine")}
          settings={s}
          name="showOut"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.comingUp")}
          settings={s}
          name="comingUp"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.openClaimsLine")}
          settings={s}
          name="showClaimsLine"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.backorderedLine")}
          settings={s}
          name="showBackordered"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.claimsList")}
          settings={s}
          name="claimsList"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.maintenance.claimButtons")}
          settings={s}
          name="showClaimButtons"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
      <CountRow
        label={t("home.opt.claims.recentCount")}
        settings={s}
        name="claimCount"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Reports (Wave 4 batch A): how many saved reports ride as
 *  rows before the list scrolls (2 is today's count). At full
 *  width the rows are links that open that report. */
function ReportsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <CountRow
      label={t("home.opt.rowsBeforeScroll")}
      settings={s}
      name="rowsVisible"
      dflt={2}
      min={2}
      max={5}
      setSetting={api.setSetting}
    />
  );
}

/** Dealers (REBUILT, dashboard-flare lane 2026-11-09): the
 *  widget is the user's dealer tiles now — the count line
 *  gets a switch and the strip a size. The Wave 4 agent-stat
 *  switches (showPreferred / showProfile) retire with the
 *  lines they governed; a stored bundle carrying them is
 *  simply inert. */
function DealersOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.dealers.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.dealers.tiles")}
        settings={s}
        name="tilesToShow"
        dflt={8}
        min={4}
        max={16}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Dealers near you (widget wave 2, 2026-11-10): the search
 *  radius the widget reads with (50 is the widget's default —
 *  the Find an Agent page's own presets are the choice set)
 *  and how many (agent, dealer) rows ride. Picking a default
 *  clears its key, like every store field. */
function DealersNearYouOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <ChoicesRow
        label={t("home.opt.near.radius")}
        settings={s}
        name="radiusMiles"
        dflt={50}
        choices={[10, 25, 50, 100]}
        setSetting={api.setSetting}
      />
      <CountRow
        label={t("home.opt.near.rows")}
        settings={s}
        name="rowsToShow"
        dflt={4}
        min={2}
        max={6}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Health checks due (widget wave 2, 2026-11-10): how many
 *  flagged items ride as rows (4 is the widget's default —
 *  the rest wait on the Health Check page itself, one tap
 *  away). Picking the default clears the key, like every
 *  store field. */
function HealthChecksDueOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <CountRow
      label={t("home.opt.health.rows")}
      settings={s}
      name="rowsToShow"
      dflt={4}
      min={2}
      max={6}
      setSetting={api.setSetting}
    />
  );
}

/** Feedback (Wave 4 batch B): the newest titles from each
 *  board ride as rows under the counts line — the owner's
 *  named shape, on by default at 3 per board; 0 is the off
 *  switch, restoring today's counts-only widget exactly.
 *  The counts line itself gets a switch too. */
function FeedbackOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.feedback.countLine")}
          settings={s}
          name="showCounts"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.feedback.rowsPerBoard")}
        settings={s}
        name="rowsPerBoard"
        dflt={3}
        min={0}
        max={3}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Shared tools (Wave 4 batch B): the two lines each get a
 *  switch (both on = today). The sharer-name rows are the
 *  widget's new shape and carry no switch of their own —
 *  the design names none. */
function SharedToolsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow
        label={t("home.opt.shared.countsLine")}
        settings={s}
        name="showCounts"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.shared.invitesLine")}
        settings={s}
        name="showInvites"
        dflt
        setSetting={api.setSetting}
      />
    </OptionsGroup>
  );
}

/** Support (Wave 4 batch B): the open tickets ride as rows,
 *  each a link into that ticket on the Help page — 1–5 of
 *  them (3 by default, the Claims rows' shape); the rows
 *  take the place of today's single Latest line. The open
 *  count line gets its own switch. */
function SupportOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.support.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.support.rowsToShow")}
        settings={s}
        name="rowsToShow"
        dflt={3}
        min={1}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Downloads (REBUILT, dashboard-flare lane 2026-11-09):
 *  the stats grid and the top-downloads strip each get a
 *  switch; one count row sizes the strip. The follow-up's
 *  list switches (showCounts / showDocuments /
 *  showWallpapers / rowsToShow) retire with the lists they
 *  governed; stored bundles carrying them are inert. */
function DownloadsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.downloads.stats")}
          settings={s}
          name="showStats"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.downloads.weekly")}
          settings={s}
          name="showWeekly"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.downloads.tiles")}
        settings={s}
        name="tilesToShow"
        dflt={8}
        min={4}
        max={12}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** 3D Print Files (REBUILT, dashboard-flare lane 2026-11-09):
 *  the follow-up's switches carry over (count line, ratings,
 *  Upload button) and the two showcase strips + the My
 *  Uploads button get theirs; one count row sizes both
 *  strips. The old rowsToShow retires with the row list it
 *  sized; stored bundles carrying it are inert. */
function PrintsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.prints.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.ratings")}
          settings={s}
          name="showRatings"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.newStrip")}
          settings={s}
          name="showNew"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.topStrip")}
          settings={s}
          name="showTop"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.uploadButton")}
          settings={s}
          name="showUpload"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.prints.mineButton")}
          settings={s}
          name="showMine"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.prints.tiles")}
        settings={s}
        name="tilesToShow"
        dflt={8}
        min={4}
        max={12}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Quick Reports (dashboard-flare lane, 2026-11-09): how
 *  many of the user's quick reports the widget lists before
 *  the "more on the Reports page" line — every listed report
 *  runs in place, so the count is the only choice there is. */
function QuickReportsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <CountRow
      label={t("home.opt.qr.rowsToShow")}
      settings={s}
      name="rowsToShow"
      dflt={5}
      min={1}
      max={10}
      setSetting={api.setSetting}
    />
  );
}

/** Tool Expansion (Wave 4 batch B): how many suggestions
 *  ride (2 is today's widget) and the known-addons count
 *  line's switch. */
function ExpansionOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.expansion.countLine")}
          settings={s}
          name="showCount"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.expansion.rowsToShow")}
        settings={s}
        name="rowsToShow"
        dflt={2}
        min={2}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** My Parts (Wave 4 batch B, parked): the parts ride as
 *  rows — 2 visible before the rest scroll is today's
 *  count of titles — and the shelf count line's switch. */
function PartsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.parts.shelfLine")}
          settings={s}
          name="showShelf"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="visibleRows"
        dflt={2}
        min={2}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Tools For Sale (Wave 4 batch B, parked): how many
 *  listings ride (3 is today's widget) and whether each
 *  listing's price sits beside its title — a pure extra,
 *  so it defaults off (today's titles-only board glance). */
function MarketplaceOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.marketplace.prices")}
          settings={s}
          name="showPrices"
          dflt={false}
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.marketplace.listingCount")}
        settings={s}
        name="listingCount"
        dflt={3}
        min={3}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Messages (Wave 4 batch B, parked): the two count lines
 *  each get a switch, and the latest-conversation names —
 *  the design's flagged extra read — get theirs: the read
 *  only happens while the names are switched on. */
function MessagingOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow
        label={t("home.opt.messaging.unreadLine")}
        settings={s}
        name="showUnread"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.messaging.requestsLine")}
        settings={s}
        name="showRequests"
        dflt
        setSetting={api.setSetting}
      />
      <CheckRow
        label={t("home.opt.messaging.conversations")}
        settings={s}
        name="showConversations"
        dflt
        setSetting={api.setSetting}
      />
    </OptionsGroup>
  );
}

/** Wishlist (Wave 4 batch B, parked): the three lines each
 *  get a switch (all on = today), and the wanted items ride
 *  as rows — how many show before the rest scroll; 0 puts
 *  the rows away and today's Latest line returns. */
function WishlistOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <>
      <OptionsGroup label={t("home.opt.whatShows")}>
        <CheckRow
          label={t("home.opt.wishlist.wantedLine")}
          settings={s}
          name="showWanted"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.wishlist.highLine")}
          settings={s}
          name="showHigh"
          dflt
          setSetting={api.setSetting}
        />
        <CheckRow
          label={t("home.opt.inventory.latestLine")}
          settings={s}
          name="showLatest"
          dflt
          setSetting={api.setSetting}
        />
      </OptionsGroup>
      <CountRow
        label={t("home.opt.rowsBeforeScroll")}
        settings={s}
        name="wantedRows"
        dflt={3}
        min={0}
        max={5}
        setSetting={api.setSetting}
      />
    </>
  );
}

/** Flyers (2026-11-06): which connected dealers/agents show
 *  in the widget — one checkbox per flyer source; unchecking
 *  stores the source's key in hiddenSources (absence of the
 *  key = everything shows, the settings discipline). */
function FlyersOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const [sources, setSources] = useState<FlyerSource[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listFlyerSources()
      .then((rows) => {
        if (!cancelled) setSources(rows);
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const raw = api.block.settings.hiddenSources;
  const hidden = new Set(Array.isArray(raw) ? raw : []);
  const toggle = (key: string, show: boolean) => {
    const next = new Set(hidden);
    if (show) next.delete(key);
    else next.add(key);
    api.setSetting(
      "hiddenSources",
      next.size > 0 ? Array.from(next) : undefined,
    );
  };
  return (
    <OptionsGroup label={t("flyers.optSources")}>
      {(sources ?? []).map((source) => (
        <Checkbox
          key={source.key}
          label={sourceTitle(source)}
          checked={!hidden.has(source.key)}
          onChange={(e) => toggle(source.key, e.target.checked)}
        />
      ))}
    </OptionsGroup>
  );
}

/** Admin widgets (admin lane, 2026-11-07; polish lane,
 *  2026-11-07): every stat ROW in every admin widget is its
 *  own toggle, all default ON — the seat hides what they
 *  don't watch, line by line; the admin lane's grouped Site
 *  Stats switches were retired by the polish lane (a saved
 *  group choice still reads as the per-line default until
 *  the line itself is toggled — see AdminSiteStatsOptions).
 *  The keys here are the same keys AdminWidgets reads. */
function AdminTicketsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showOpen")} settings={s} name="showOpen" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showClosed")} settings={s} name="showClosed" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showUnanswered")} settings={s} name="showUnanswered" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

function AdminBoardOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showTotal")} settings={s} name="showTotal" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showOpen")} settings={s} name="showOpen" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewWeek")} settings={s} name="showNewWeek" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showDone")} settings={s} name="showDone" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showHeld")} settings={s} name="showHeld" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showTop")} settings={s} name="showTop" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

function AdminForumModeratorOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showFlags")} settings={s} name="showFlags" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showHeld")} settings={s} name="showHeld" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewPosts")} settings={s} name="showNewPosts" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showTopThreads")} settings={s} name="showTop" dflt setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

interface AdminPlanOption {
  plan_key: string;
  name: string;
}

/** Site Stats options (polish lane, owner 2026-11-07): EVERY
 *  row line is its own toggle — the admin lane's grouped
 *  switches (members-by-tier as one, free-vs-paying as one…)
 *  are gone. A line that was never toggled still follows its
 *  old group switch when one is saved, so existing admin
 *  layouts keep their choices; the per-line default each
 *  CheckRow is handed IS that fallback. The paying-by-plan
 *  lines are one toggle per plan per billing period — the
 *  plan list is the admin payload's own (the FlyersOptions
 *  pattern: the section reads the data it configures). */
function AdminSiteStatsOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const [plans, setPlans] = useState<AdminPlanOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchApi<{ site: { paying_by_plan: AdminPlanOption[] } }>(
      "/admin/home-widgets",
    )
      .then((data) => {
        if (!cancelled) setPlans(data.site.paying_by_plan ?? []);
      })
      .catch(() => {
        if (!cancelled) setPlans([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const tiersDflt = optBool(s, "showTiers", true);
  const plansDflt = optBool(s, "showPlans", true);
  const toolsDflt = optBool(s, "showTools", true);
  const newDflt = optBool(s, "showNewPaid", true);
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      <CheckRow label={t("home.opt.admin.showMembers")} settings={s} name="showMembers" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierGod")} settings={s} name="showTierGod" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierModAdmin")} settings={s} name="showTierModAdmin" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierModerator")} settings={s} name="showTierModerator" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.tierMember")} settings={s} name="showTierMember" dflt={tiersDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeMechanic")} settings={s} name="showTypeMechanic" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeShop")} settings={s} name="showTypeShop" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeInsurance")} settings={s} name="showTypeInsurance" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.admin.typeAgent")} settings={s} name="showTypeAgent" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showPaying")} settings={s} name="showPaying" dflt={plansDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showFree")} settings={s} name="showFree" dflt={plansDflt} setSetting={api.setSetting} />
      {plans.map((plan) => (
        <Fragment key={plan.plan_key}>
          <CheckRow
            label={`${plan.name} — ${t("home.opt.admin.monthlyPaying")}`}
            settings={s}
            name={`payPlan:${plan.plan_key}:monthly`}
            dflt
            setSetting={api.setSetting}
          />
          <CheckRow
            label={`${plan.name} — ${t("home.opt.admin.annualPaying")}`}
            settings={s}
            name={`payPlan:${plan.plan_key}:annual`}
            dflt
            setSetting={api.setSetting}
          />
        </Fragment>
      ))}
      <CheckRow label={t("home.opt.admin.showMrr")} settings={s} name="showMrr" dflt setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showToolsTotal")} settings={s} name="showToolsTotal" dflt={toolsDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showToolsToday")} settings={s} name="showToolsToday" dflt={toolsDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewMembers")} settings={s} name="showNewMembers" dflt={newDflt} setSetting={api.setSetting} />
      <CheckRow label={t("home.opt.admin.showNewPaidToday")} settings={s} name="showNewPaidToday" dflt={newDflt} setSetting={api.setSetting} />
    </OptionsGroup>
  );
}

/** Account & Plan (Sweep B1, finding 01-F5): the widget's loader
 *  already honours a show* switch for every stat, note line, and
 *  button it renders (they gate the custom-box aspects too) — the
 *  predefined widget simply had no registered panel, so its Edit
 *  options held only the width toggle. These rows write the exact
 *  names/defaults the loader reads. */
function AccountPlanOptions({ api }: { api: WidgetOptionsApi }) {
  const t = useT();
  const s = api.block.settings;
  const rows: { label: string; name: string }[] = [
    { label: t("home.opt.accountPlan.showPlan"), name: "showPlan" },
    { label: t("home.opt.accountPlan.showAccount"), name: "showAccount" },
    { label: t("home.opt.accountPlan.showItems"), name: "showItems" },
    { label: t("home.opt.accountPlan.showRenewal"), name: "showRenewal" },
    { label: t("home.opt.accountPlan.showSource"), name: "showSource" },
    { label: t("home.opt.accountPlan.showManage"), name: "showManage" },
    { label: t("home.opt.accountPlan.showAccountBtn"), name: "showAccountBtn" },
  ];
  return (
    <OptionsGroup label={t("home.opt.whatShows")}>
      {rows.map((r) => (
        <CheckRow
          key={r.name}
          label={r.label}
          settings={s}
          name={r.name}
          dflt
          setSetting={api.setSetting}
        />
      ))}
    </OptionsGroup>
  );
}

export const WIDGET_OPTIONS: Record<string, WidgetOptionsDef> = {
  account_plan: { render: (api) => <AccountPlanOptions api={api} /> },
  "widget:flyers": { render: (api) => <FlyersOptions api={api} /> },
  "widget:inventory": { render: (api) => <InventoryOptions api={api} /> },
  "widget:borrowing": { render: (api) => <BorrowingOptions api={api} /> },
  "widget:disaster_claims": {
    render: (api) => <DisasterClaimsOptions api={api} />,
  },
  "widget:truck_accounts": { render: (api) => <TruckOptions api={api} /> },
  "widget:forum": { render: (api) => <ForumOptions api={api} /> },
  notifications: { render: (api) => <NotificationsOptions api={api} /> },
  dealer_dashboard: {
    render: (api) => <DealerDashboardOptions api={api} />,
  },
  "widget:maintenance": { render: (api) => <MaintenanceOptions api={api} /> },
  "widget:reports": { render: (api) => <ReportsOptions api={api} /> },
  "widget:dealers": { render: (api) => <DealersOptions api={api} /> },
  dealers_near_you: {
    render: (api) => <DealersNearYouOptions api={api} />,
  },
  health_checks_due: {
    render: (api) => <HealthChecksDueOptions api={api} />,
  },
  "widget:feedback": { render: (api) => <FeedbackOptions api={api} /> },
  "widget:shared_tools": { render: (api) => <SharedToolsOptions api={api} /> },
  "widget:support": { render: (api) => <SupportOptions api={api} /> },
  "widget:downloads": { render: (api) => <DownloadsOptions api={api} /> },
  "widget:prints": { render: (api) => <PrintsOptions api={api} /> },
  quick_reports: { render: (api) => <QuickReportsOptions api={api} /> },
  "widget:tool_expansion": { render: (api) => <ExpansionOptions api={api} /> },
  "widget:parts": { render: (api) => <PartsOptions api={api} /> },
  "widget:marketplace": { render: (api) => <MarketplaceOptions api={api} /> },
  "widget:messaging": { render: (api) => <MessagingOptions api={api} /> },
  "widget:wishlist": { render: (api) => <WishlistOptions api={api} /> },
  admin_tickets: { render: (api) => <AdminTicketsOptions api={api} /> },
  admin_bug_reports: { render: (api) => <AdminBoardOptions api={api} /> },
  admin_feature_requests: { render: (api) => <AdminBoardOptions api={api} /> },
  admin_forum_moderator: {
    render: (api) => <AdminForumModeratorOptions api={api} />,
  },
  admin_site_stats: { render: (api) => <AdminSiteStatsOptions api={api} /> },
};

/** The popover's extra content for one block: its registered
 *  option sections, or null when the block has none. */
export function renderWidgetOptions(
  block: ResolvedBlock,
  setSetting: WidgetOptionsApi["setSetting"],
): ReactNode {
  const def = WIDGET_OPTIONS[block.key];
  if (!def) return null;
  return def.render({ block, setSetting });
}
