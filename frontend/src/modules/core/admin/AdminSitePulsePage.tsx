import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  Panel,
  Spinner,
  StatCard,
  type Column,
} from "../../../components";
import type { DictKey } from "../../../i18n/dictionaries";
import { useT } from "../../../i18n/LocaleContext";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Site pulse (sweep lane D4, owner idea 5): the
 * operator's morning glance — signups, downloads activity,
 * new 3D print listings, and AI calls + cost on ONE read-only
 * page. Every number comes from the one aggregate endpoint
 * (GET /api/admin/site-pulse, operator-gated server-side) and
 * names its window on its tile; windows are UTC days (core/
 * site_pulse.py names the source table behind each number).
 * Stat tiles render ONLY through the shared StatCard kit —
 * the label-over-value register every surface uses.
 */

interface AiWindow {
  actions: number;
  calls: number;
  credits_charged: number;
  tokens_in: number;
  tokens_out: number;
}

interface AiActionRow {
  action: string;
  label: string;
  actions: number;
  calls: number;
  credits_charged: number;
}

interface PulseData {
  generated_at: string;
  signups: {
    today: number;
    last_7_days: number;
    total: number;
    by_tier_now: Record<string, number>;
  };
  downloads: { today: number; last_7_days: number; total: number };
  prints: { today: number; last_7_days: number; total_live: number };
  ai: {
    today: AiWindow;
    last_7_days: AiWindow;
    last_30_days: AiWindow;
    by_action_last_30_days: AiActionRow[];
  };
  attention: {
    support_tickets_waiting: number;
    announcements_sent_total: number;
  };
}

const TIER_ORDER = ["downloads", "normal", "moderator", "moderator_admin", "god"];

// The ai_service PRICE_KEYS vocabulary the dictionary carries
// labels for (admin.pulse.action.*).
const KNOWN_AI_ACTIONS = new Set([
  "lookup",
  "identify",
  "manual_lookup",
  "report_summary",
  "drawer_lookup",
]);

function fmt(value: number): string {
  return value.toLocaleString();
}

function PulseSection() {
  const t = useT();
  const [data, setData] = useState<PulseData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setData(await api<PulseData>("/admin/site-pulse"));
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("admin.pulse.loadError"),
      );
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const tierRows = data
    ? TIER_ORDER.filter((tier) => tier in data.signups.by_tier_now).map(
        (tier) => ({
          tier,
          label: t(`admin.pulse.tier.${tier}` as DictKey),
          count: data.signups.by_tier_now[tier] ?? 0,
        }),
      )
    : [];
  const tierColumns: Column<(typeof tierRows)[number]>[] = [
    {
      key: "label",
      header: t("admin.pulse.colTier"),
      render: (row) => row.label,
    },
    {
      key: "count",
      header: t("admin.pulse.colAccounts"),
      align: "right",
      render: (row) => fmt(row.count),
    },
  ];

  const actionRows = data?.ai.by_action_last_30_days ?? [];
  const actionColumns: Column<AiActionRow>[] = [
    {
      key: "display",
      header: t("admin.pulse.colAction"),
      // Known purposes translate through the dictionary; an
      // action key the dictionary doesn't carry yet falls back
      // to the backend's own label for that action.
      render: (row) =>
        KNOWN_AI_ACTIONS.has(row.action)
          ? t(`admin.pulse.action.${row.action}` as DictKey)
          : row.label,
    },
    {
      key: "actions",
      header: t("admin.pulse.colUses"),
      align: "right",
      render: (row) => fmt(row.actions),
    },
    {
      key: "calls",
      header: t("admin.pulse.colCalls"),
      align: "right",
      render: (row) => fmt(row.calls),
    },
    {
      key: "credits",
      header: t("admin.pulse.colCredits"),
      align: "right",
      render: (row) => fmt(row.credits_charged),
    },
  ];

  return (
    <AdminShell>
      <div className="tv-admin-stack tv-admin-pulse">
        <p className="tv-admin-muted">{t("admin.pulse.intro")}</p>

        {loadError && (
          <Alert tone="danger">
            {loadError}{" "}
            <Button variant="ghost" size="sm" onClick={() => void load()}>
              {t("admin.pulse.retry")}
            </Button>
          </Alert>
        )}

        {!data && !loadError && (
          <p className="tv-admin-loading">
            <Spinner size="sm" /> Loading…
          </p>
        )}

        {data && (
          <>
            <section className="tv-admin-setblock">
              <h2 className="tv-admin-settitle">{t("admin.pulse.signups")}</h2>
              <div className="tv-overview-grid">
                <StatCard label={t("admin.pulse.signupsToday")} value={fmt(data.signups.today)} />
                <StatCard label={t("admin.pulse.signups7d")} value={fmt(data.signups.last_7_days)} />
                <StatCard label={t("admin.pulse.signupsTotal")} value={fmt(data.signups.total)} />
              </div>
              <Panel>
                <p className="tv-admin-settitle">{t("admin.pulse.tierSplitTitle")}</p>
                <DataTable
                  columns={tierColumns}
                  rows={tierRows}
                  rowKey={(row) => row.tier}
                />
              </Panel>
            </section>

            <section className="tv-admin-setblock">
              <h2 className="tv-admin-settitle">{t("admin.pulse.downloads")}</h2>
              <div className="tv-overview-grid">
                <StatCard label={t("admin.pulse.downloadsToday")} value={fmt(data.downloads.today)} />
                <StatCard label={t("admin.pulse.downloads7d")} value={fmt(data.downloads.last_7_days)} />
                <StatCard label={t("admin.pulse.downloadsTotal")} value={fmt(data.downloads.total)} />
              </div>
            </section>

            <section className="tv-admin-setblock">
              <h2 className="tv-admin-settitle">{t("admin.pulse.prints")}</h2>
              <div className="tv-overview-grid">
                <StatCard label={t("admin.pulse.printsToday")} value={fmt(data.prints.today)} />
                <StatCard label={t("admin.pulse.prints7d")} value={fmt(data.prints.last_7_days)} />
                <StatCard label={t("admin.pulse.printsTotalLive")} value={fmt(data.prints.total_live)} />
              </div>
            </section>

            <section className="tv-admin-setblock">
              <h2 className="tv-admin-settitle">{t("admin.pulse.ai")}</h2>
              <div className="tv-overview-grid">
                <StatCard label={t("admin.pulse.aiActionsToday")} value={fmt(data.ai.today.actions)} />
                <StatCard label={t("admin.pulse.aiActions7d")} value={fmt(data.ai.last_7_days.actions)} />
                <StatCard label={t("admin.pulse.aiActions30d")} value={fmt(data.ai.last_30_days.actions)} />
                <StatCard label={t("admin.pulse.aiCallsToday")} value={fmt(data.ai.today.calls)} />
                <StatCard label={t("admin.pulse.aiCalls7d")} value={fmt(data.ai.last_7_days.calls)} />
                <StatCard label={t("admin.pulse.aiCalls30d")} value={fmt(data.ai.last_30_days.calls)} />
                <StatCard label={t("admin.pulse.aiCreditsToday")} value={fmt(data.ai.today.credits_charged)} />
                <StatCard label={t("admin.pulse.aiCredits7d")} value={fmt(data.ai.last_7_days.credits_charged)} />
                <StatCard label={t("admin.pulse.aiCredits30d")} value={fmt(data.ai.last_30_days.credits_charged)} />
              </div>
              <Panel>
                <p className="tv-admin-settitle">{t("admin.pulse.aiByActionTitle")}</p>
                {actionRows.length > 0 ? (
                  <DataTable
                    columns={actionColumns}
                    rows={actionRows}
                    rowKey={(row) => row.action}
                  />
                ) : (
                  <EmptyState title={t("admin.pulse.aiEmpty")} />
                )}
              </Panel>
            </section>

            <section className="tv-admin-setblock">
              <h2 className="tv-admin-settitle">{t("admin.pulse.attention")}</h2>
              <div className="tv-overview-grid">
                <StatCard
                  label={t("admin.pulse.ticketsWaiting")}
                  value={fmt(data.attention.support_tickets_waiting)}
                  href="/admin/support"
                  alert={data.attention.support_tickets_waiting > 0}
                />
                <StatCard
                  label={t("admin.pulse.announcementsSent")}
                  value={fmt(data.attention.announcements_sent_total)}
                />
              </div>
            </section>
          </>
        )}
      </div>
    </AdminShell>
  );
}

export default function AdminSitePulsePage() {
  return (
    <RequireAuth>
      <PulseSection />
    </RequireAuth>
  );
}
