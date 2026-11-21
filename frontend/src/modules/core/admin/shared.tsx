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

import { Panel, QuietSkeleton } from "../../../components";
import { ArtIcon, type ArtName } from "../../../components/ArtIcon";
import type { StatTone } from "../../../components/OverviewRow";
import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { api } from "../../../lib/api";
import type { BlockSettingValue } from "../../../lib/usePageLayout";

export interface FlaggedRow {
  surface: string;
  title: string;
  excerpt: string;
  reason: string;
  href: string;
  created_at: string | null;
}

export interface PlanRow {
  plan_key: string;
  name: string;
  monthly: number;
  annual: number;
  total: number;
}

export interface AdminWidgetsPayload {
  tickets: {
    open: number;
    closed: number;
    unanswered: number;
    total: number;
    latest: {
      subject: string;
      status: string;
      updated_at: string;
      href: string;
    }[];
  };
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

export interface BoardBlock {
  total: number;
  open: number;
  new_week: number;
  done: number;
  held: number;
  top: { title: string; votes: number; href: string } | null;
}

let cached: Promise<AdminWidgetsPayload> | null = null;

export function loadAdminWidgets(): Promise<AdminWidgetsPayload> {
  if (!cached) {
    cached = api<AdminWidgetsPayload>("/admin/home-widgets").catch((err) => {
      cached = null;
      throw err;
    });
  }
  return cached;
}

export function useAdminWidgets(): {
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

export type Settings = Record<string, BlockSettingValue>;

/** One stat line's visibility: its own toggle wins; when the
 *  line has never been toggled, the admin lane's GROUP toggle
 *  it used to live under still speaks (a saved layout keeps
 *  the admin's choice); beyond that, lines show. */
export function optLine(
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

export function StatRow({
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
export function AdminShell({
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

export function Rows({ children }: { children: ReactNode }) {
  return (
    <div className="tv-widget-rowset">
      <div className="tv-widget-rows tv-admin-rows">{children}</div>
    </div>
  );
}

