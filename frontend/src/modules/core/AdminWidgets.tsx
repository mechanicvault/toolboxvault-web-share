/** Admin Home widgets (admin lane, owner 2026-11-06; polish
 *  lane, owner corrections 2026-11-07): the five responder-side
 *  blocks — Support Tickets, Bug Reports, Feature Requests,
 *  Forum Moderator, Site Stats — registered in CorePage ONLY
 *  for god + moderator_admin seats, so the blocks (and their
 *  Edit-view Add entries) never exist for anyone else.
 *
 *  POLISH (2026-11-07): the widgets now wear the STANDARD Home
 *  widget chrome — the same Panel, the whole-box cover link
 *  (which is what earns the Main highlight lift + glow), the
 *  head row with the ArtIcon tile + title + Open CTA seat, and
 *  stat rows at the standard widgets' compact line rhythm —
 *  instead of the admin lane's flat panel with a footer door
 *  button. Each widget has its own real ArtIcon artwork. Every
 *  stat ROW is individually toggleable in the widget's options
 *  (no grouped toggles; a line that's off leaves no gap). The
 *  Site Stats widget mirrors the admin Site Overview report:
 *  member-type counts and paying-by-plan rows ride along, each
 *  with its own toggle and its own day-over-day delta when the
 *  daily snapshot has a baseline for it.
 *
 *  All five read ONE endpoint — GET /api/admin/home-widgets,
 *  itself tier-gated server-side — through a shared cached
 *  loader, so a Home full of admin widgets costs one fetch.
 *  Rows and doors go inert in Home Edit view, like every other
 *  block. Deltas come from the daily snapshot; with no earlier
 *  snapshot (or none holding the newer dimensions) the widget
 *  says so plainly instead of inventing a baseline.
 */

import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Panel, QuietSkeleton } from "../../components";
import { ArtIcon, type ArtName } from "../../components/ArtIcon";
import type { StatTone } from "../../components/OverviewRow";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import { api } from "../../lib/api";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import { optBool } from "./widgetOptions";
import "./adminWidgets.css";

interface FlaggedRow {
  surface: string;
  title: string;
  excerpt: string;
  reason: string;
  href: string;
  created_at: string | null;
}

interface PlanRow {
  plan_key: string;
  name: string;
  monthly: number;
  annual: number;
  total: number;
}

interface AdminWidgetsPayload {
  tickets: { open: number; closed: number; unanswered: number; total: number };
  bug_reports: BoardBlock;
  feature_requests: BoardBlock;
  forum_moderator: {
    open_flags: number;
    held: number;
    new_posts_today: number;
    flagged: FlaggedRow[];
    top_threads: { title: string; replies: number; href: string }[];
  };
  site: {
    users_total: number;
    users_by_tier: Record<string, number>;
    users_by_type: Record<string, number>;
    paying_by_plan: PlanRow[];
    free_users: number;
    paying_users: number;
    mrr: string;
    tools_total: number;
    new_users: number;
    new_paid: number;
    tools_logged: number;
    tier_deltas: Record<string, number> | null;
    paying_delta: number | null;
    type_deltas: Record<string, number> | null;
    plan_deltas: Record<
      string,
      { monthly: number; annual: number; total: number }
    > | null;
    baseline_day: string | null;
  };
}

interface BoardBlock {
  total: number;
  open: number;
  new_week: number;
  done: number;
  held: number;
  top: { title: string; votes: number; href: string } | null;
}

let cached: Promise<AdminWidgetsPayload> | null = null;

function loadAdminWidgets(): Promise<AdminWidgetsPayload> {
  if (!cached) {
    cached = api<AdminWidgetsPayload>("/admin/home-widgets").catch((err) => {
      cached = null;
      throw err;
    });
  }
  return cached;
}

function useAdminWidgets(): {
  payload: AdminWidgetsPayload | null;
  failed: boolean;
} {
  const [payload, setPayload] = useState<AdminWidgetsPayload | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    loadAdminWidgets()
      .then((data) => {
        if (live) setPayload(data);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, []);
  return { payload, failed };
}

type Settings = Record<string, BlockSettingValue>;

/** One stat line's visibility: its own toggle wins; when the
 *  line has never been toggled, the admin lane's GROUP toggle
 *  it used to live under still speaks (a saved layout keeps
 *  the admin's choice); beyond that, lines show. */
function optLine(
  settings: Settings,
  name: string,
  legacyGroup?: string,
): boolean {
  const own = settings[name];
  if (typeof own === "boolean") return own;
  if (legacyGroup) {
    const group = settings[legacyGroup];
    if (typeof group === "boolean") return group;
  }
  return true;
}

function StatRow({
  label,
  value,
  href,
  editing,
}: {
  label: string;
  value: ReactNode;
  href?: string;
  editing?: boolean;
}) {
  const cells = (
    <>
      <span className="tv-widget-cell tv-admin-label">{label}</span>
      <span className="tv-widget-cell tv-admin-value">{value}</span>
    </>
  );
  if (href && !editing) {
    return (
      <Link to={href} className="tv-widget-row tv-widget-row--link">
        {cells}
      </Link>
    );
  }
  return <div className="tv-widget-row">{cells}</div>;
}

/** The standard Home widget shell, mirrored piece for piece
 *  from HomeWidget: head with icon tile, title and the CTA —
 *  and, like HomeWidget, its whole-box cover anchor is RETIRED
 *  (dashboard redesign 2026-11-10): the title and the Open
 *  button are the doors, rows keep their own links. In the
 *  retired Edit view there was no cover and the seat rendered
 *  as the inert face; that mode no longer exists, but the
 *  `editing` prop keeps its neutered rendering. */
function AdminShell({
  titleKey,
  icon,
  tone,
  door,
  editing,
  failed,
  loading,
  children,
}: {
  titleKey: DictKey;
  icon: ArtName;
  tone: StatTone;
  door: string;
  editing?: boolean;
  failed: boolean;
  loading: boolean;
  children: ReactNode;
}) {
  const t = useT();
  const title = t(titleKey);
  return (
    <Panel className="tv-home-widget">
      {/* No "Open →" button in the head (Ryan, 2026-11-10
          17:29 — retired on every Home widget); the title link
          is the door. */}
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone={tone} aria-hidden="true">
          <ArtIcon name={icon} size={24} />
        </span>
        <h3 className="tv-widget-title">
          {editing ? (
            title
          ) : (
            <Link to={door} className="tv-widget-title-link">
              {title}
            </Link>
          )}
        </h3>
      </div>
      {failed ? (
        <p className="tv-muted">{t("home.widgetLoadFailed")}</p>
      ) : loading ? (
        <QuietSkeleton lines={2} />
      ) : (
        children
      )}
    </Panel>
  );
}

function Rows({ children }: { children: ReactNode }) {
  return (
    <div className="tv-widget-rowset">
      <div className="tv-widget-rows tv-admin-rows">{children}</div>
    </div>
  );
}

export function AdminTicketsWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.tickets;
  return (
    <AdminShell
      titleKey="home.widget.adminTickets"
      icon="adminTickets"
      tone="info"
      door="/admin/support"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <Rows>
          {optBool(settings, "showOpen", true) && (
            <StatRow label={t("home.admin.open")} value={data.open} editing={editing} />
          )}
          {optBool(settings, "showClosed", true) && (
            <StatRow label={t("home.admin.closed")} value={data.closed} editing={editing} />
          )}
          {optBool(settings, "showUnanswered", true) && (
            <StatRow
              label={t("home.admin.unanswered")}
              value={data.unanswered}
              editing={editing}
            />
          )}
        </Rows>
      )}
    </AdminShell>
  );
}

export function AdminBoardWidget({
  board,
  editing = false,
  settings = {},
}: {
  board: "bug" | "feature";
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = board === "bug" ? payload?.bug_reports : payload?.feature_requests;
  const boardPath = board === "bug" ? "/feedback/bugs" : "/feedback/features";
  return (
    <AdminShell
      titleKey={
        board === "bug"
          ? "home.widget.adminBugReports"
          : "home.widget.adminFeatureRequests"
      }
      icon={board === "bug" ? "adminBug" : "adminFeature"}
      tone={board === "bug" ? "danger" : "warning"}
      door={boardPath}
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <Rows>
          {optBool(settings, "showTotal", true) && (
            <StatRow label={t("home.admin.total")} value={data.total} editing={editing} />
          )}
          {optBool(settings, "showOpen", true) && (
            <StatRow label={t("home.admin.open")} value={data.open} editing={editing} />
          )}
          {optBool(settings, "showNewWeek", true) && (
            <StatRow
              label={t("home.admin.newThisWeek")}
              value={data.new_week}
              editing={editing}
            />
          )}
          {optBool(settings, "showDone", true) && (
            <StatRow label={t("home.admin.done")} value={data.done} editing={editing} />
          )}
          {optBool(settings, "showHeld", true) && (
            <StatRow label={t("home.admin.held")} value={data.held} editing={editing} />
          )}
          {optBool(settings, "showTop", true) && data.top && (
            <StatRow
              label={t("home.admin.topPost")}
              value={
                <>
                  {data.top.title}{" "}
                  <span className="tv-admin-note">▲ {data.top.votes}</span>
                </>
              }
              href={data.top.href}
              editing={editing}
            />
          )}
        </Rows>
      )}
    </AdminShell>
  );
}

export function AdminForumModeratorWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.forum_moderator;
  return (
    <AdminShell
      titleKey="home.widget.adminForumModerator"
      icon="adminForum"
      tone="violet"
      door="/moderation"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <>
          <Rows>
            {optBool(settings, "showFlags", true) && (
              <StatRow
                label={t("home.admin.flaggedNow")}
                value={data.open_flags}
                editing={editing}
              />
            )}
            {optBool(settings, "showHeld", true) && (
              <StatRow
                label={t("home.admin.heldNow")}
                value={data.held}
                editing={editing}
              />
            )}
            {optBool(settings, "showNewPosts", true) && (
              <StatRow
                label={t("home.admin.newPostsToday")}
                value={data.new_posts_today}
                editing={editing}
              />
            )}
            {optBool(settings, "showFlags", true) &&
              data.flagged.map((row, i) => (
                <StatRow
                  key={`flag-${i}`}
                  label={row.title || row.excerpt || "—"}
                  value={row.reason || "⚑"}
                  href={row.href}
                  editing={editing}
                />
              ))}
            {optBool(settings, "showTop", true) &&
              data.top_threads.length > 0 && (
                <>
                  <div className="tv-admin-subhead">{t("home.admin.topThreads")}</div>
                  {data.top_threads.map((row, i) => (
                    <StatRow
                      key={`top-${i}`}
                      label={row.title}
                      value={`${row.replies} ${t("home.admin.replies")}`}
                      href={row.href}
                      editing={editing}
                    />
                  ))}
                </>
              )}
          </Rows>
          {data.open_flags === 0 && data.held === 0 && (
            <p className="tv-muted">{t("home.admin.nothingWaiting")}</p>
          )}
        </>
      )}
    </AdminShell>
  );
}

const TIER_ROWS: { rung: string; labelKey: DictKey; opt: string }[] = [
  { rung: "god", labelKey: "home.admin.tierGod", opt: "showTierGod" },
  {
    rung: "moderator_admin",
    labelKey: "home.admin.tierModAdmin",
    opt: "showTierModAdmin",
  },
  { rung: "moderator", labelKey: "home.admin.tierModerator", opt: "showTierModerator" },
  { rung: "normal", labelKey: "home.admin.tierMember", opt: "showTierMember" },
];

const TYPE_ROWS: { key: string; labelKey: DictKey; opt: string }[] = [
  { key: "mechanic", labelKey: "home.admin.typeMechanic", opt: "showTypeMechanic" },
  { key: "shop", labelKey: "home.admin.typeShop", opt: "showTypeShop" },
  { key: "insurance", labelKey: "home.admin.typeInsurance", opt: "showTypeInsurance" },
  { key: "agent", labelKey: "home.admin.typeAgent", opt: "showTypeAgent" },
];

function deltaText(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "";
  if (delta > 0) return ` (+${delta})`;
  if (delta < 0) return ` (${delta})`;
  return " (±0)";
}

function withDelta(value: number, delta: number | null | undefined) {
  return (
    <>
      {value}
      <span className="tv-admin-note">{deltaText(delta)}</span>
    </>
  );
}

export function AdminSiteStatsWidget({
  editing = false,
  settings = {},
}: {
  editing?: boolean;
  settings?: Settings;
}) {
  const t = useT();
  const { payload, failed } = useAdminWidgets();
  const data = payload?.site;
  return (
    <AdminShell
      titleKey="home.widget.adminSiteStats"
      icon="adminStats"
      tone="teal"
      door="/admin"
      editing={editing}
      failed={failed}
      loading={!payload && !failed}
    >
      {data && (
        <>
          <Rows>
            {optLine(settings, "showMembers", "showTiers") && (
              <StatRow
                label={t("home.admin.members")}
                value={data.users_total}
                editing={editing}
              />
            )}
            {TIER_ROWS.map(({ rung, labelKey, opt }) =>
              optLine(settings, opt, "showTiers") ? (
                <StatRow
                  key={rung}
                  label={t(labelKey)}
                  value={withDelta(
                    data.users_by_tier[rung] ?? 0,
                    data.tier_deltas?.[rung],
                  )}
                  editing={editing}
                />
              ) : null,
            )}
            {TYPE_ROWS.map(({ key, labelKey, opt }) =>
              optLine(settings, opt) ? (
                <StatRow
                  key={key}
                  label={t(labelKey)}
                  value={withDelta(
                    data.users_by_type[key] ?? 0,
                    data.type_deltas?.[key],
                  )}
                  editing={editing}
                />
              ) : null,
            )}
            {optLine(settings, "showPaying", "showPlans") && (
              <StatRow
                label={t("home.admin.paying")}
                value={withDelta(data.paying_users, data.paying_delta)}
                editing={editing}
              />
            )}
            {optLine(settings, "showFree", "showPlans") && (
              <StatRow label={t("home.admin.free")} value={data.free_users} editing={editing} />
            )}
            {data.paying_by_plan.map((plan) => {
              const deltas = data.plan_deltas?.[plan.plan_key];
              return [
                optLine(settings, `payPlan:${plan.plan_key}:monthly`) && (
                  <StatRow
                    key={`${plan.plan_key}-monthly`}
                    label={`${plan.name} — ${t("home.admin.monthlyWord")}`}
                    value={withDelta(plan.monthly, deltas?.monthly)}
                    editing={editing}
                  />
                ),
                optLine(settings, `payPlan:${plan.plan_key}:annual`) && (
                  <StatRow
                    key={`${plan.plan_key}-annual`}
                    label={`${plan.name} — ${t("home.admin.annualWord")}`}
                    value={withDelta(plan.annual, deltas?.annual)}
                    editing={editing}
                  />
                ),
              ];
            })}
            {optLine(settings, "showMrr") && (
              <StatRow label={t("home.admin.mrr")} value={`$${data.mrr}`} editing={editing} />
            )}
            {optLine(settings, "showToolsTotal", "showTools") && (
              <StatRow
                label={t("home.admin.toolsTotal")}
                value={data.tools_total}
                editing={editing}
              />
            )}
            {optLine(settings, "showToolsToday", "showTools") && (
              <StatRow
                label={t("home.admin.toolsToday")}
                value={data.tools_logged}
                editing={editing}
              />
            )}
            {optLine(settings, "showNewMembers", "showNewPaid") && (
              <StatRow
                label={t("home.admin.newMembersToday")}
                value={data.new_users}
                editing={editing}
              />
            )}
            {optLine(settings, "showNewPaidToday", "showNewPaid") && (
              <StatRow
                label={t("home.admin.newPaidToday")}
                value={data.new_paid}
                editing={editing}
              />
            )}
          </Rows>
          {data.baseline_day === null ? (
            <p className="tv-muted">{t("home.admin.noBaseline")}</p>
          ) : (
            <p className="tv-muted">
              {t("home.admin.comparedTo")} {data.baseline_day}
            </p>
          )}
        </>
      )}
    </AdminShell>
  );
}
