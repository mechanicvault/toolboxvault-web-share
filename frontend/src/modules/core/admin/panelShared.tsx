import { useEffect, useState } from "react";
import { useT } from "../../../i18n/LocaleContext";
import { api } from "../../../lib/api";

export interface PanelWindowTiles {
  downloads: number;
  tools_logged: number;
  ai_credits: number;
  ai_calls: number;
}

export interface PanelScoreRow {
  key: string;
  format: "count" | "credits";
  good_when: "up" | "down";
  today: number;
  last_7_days: number;
  last_30_days: number;
  change_pct: number | null;
}

export interface PanelCheck {
  key: string;
  status: "ok" | "watch" | "check" | "off" | "unknown";
  value: string;
  detail: string;
}

export interface AdminPanelPayload {
  overview: {
    users_total: number;
    paying_users: number;
    free_users: number;
    mrr: string;
    signups_series_30d: number[];
    signups_series_start: string;
    new_last_7_days: number;
    new_prior_7_days: number;
    new_last_30_days: number;
    tiles: Record<"today" | "last_7_days" | "last_30_days", PanelWindowTiles>;
    tile_changes: Record<
      "last_7_days" | "last_30_days",
      Record<"downloads" | "tools_logged" | "ai_credits", number | null>
    >;
    attention: {
      tickets_open: number;
      tickets_over_24h: number;
      flagged_posts: number;
      held_posts: number;
      bug_reports_open: number;
      bug_reports_high: number;
    };
  };
  scoreboard: PanelScoreRow[];
  health: { checks: PanelCheck[]; ok_count: number; total: number };
}

let panelCached: Promise<AdminPanelPayload> | null = null;

export function loadAdminPanel(): Promise<AdminPanelPayload> {
  if (!panelCached) {
    panelCached = api<AdminPanelPayload>("/admin/panel").catch((err) => {
      panelCached = null;
      throw err;
    });
  }
  return panelCached;
}

export function useAdminPanel(): {
  panel: AdminPanelPayload | null;
  failed: boolean;
} {
  const [panel, setPanel] = useState<AdminPanelPayload | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    loadAdminPanel()
      .then((data) => {
        if (live) setPanel(data);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, []);
  return { panel, failed };
}

export const fmtNum = (n: number) => n.toLocaleString("en-US");

/** A change chip: arrow + percent, toned by whether the
 *  movement is the good direction for that metric. A null
 *  percent means there was no baseline (prints "New" when
 *  the current window has anything at all). */
export function ChangeChip({
  pct,
  goodWhen,
  current,
}: {
  pct: number | null;
  goodWhen: "up" | "down";
  current: number;
}) {
  const t = useT();
  if (pct === null) {
    return current > 0 ? (
      <span className="tv-panel-chip" data-tone="good">
        {t("home.panel.new")}
      </span>
    ) : (
      <span className="tv-panel-chip" data-tone="flat">
        —
      </span>
    );
  }
  if (pct === 0) {
    return (
      <span className="tv-panel-chip" data-tone="flat">
        0%
      </span>
    );
  }
  const good = pct > 0 === (goodWhen === "up");
  return (
    <span className="tv-panel-chip" data-tone={good ? "good" : "warn"}>
      {pct > 0 ? "▲" : "▼"} {Math.abs(pct)}%
    </span>
  );
}

export type PanelWindow = "today" | "last_7_days" | "last_30_days";

