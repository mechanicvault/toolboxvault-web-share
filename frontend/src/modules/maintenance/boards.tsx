import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, EmptyState, Panel, Spinner, useToast } from "../../components";
import { ApiError } from "../../lib/api";
import { StatusBadge } from "../claims/components";
import { getMaintenanceOverview, logDone } from "./api";
import {
  DUE_STATUS_LABELS,
  DUE_STATUS_TONES,
  REPAIR_STATE_LABELS,
  REPAIR_STATE_TONES,
  SCHEDULE_KIND_LABELS,
  fullDate,
  scheduleTitle,
} from "./format";
import type { MaintenanceOverview, MaintenanceSchedule, OutOfServiceEntry } from "./types";
import "./maintenance.css";

/**
 * The maintenance boards (module doctrine build, 2026-10-19;
 * split out of the module page by the Repairs & Maintenance
 * merge, 2026-11-05): everything currently out of service
 * (broken / in repair, set pieces included) and every schedule
 * across the owner's items with its computed due standing.
 * Since the repairs ∪ claims merge (2026-11-04) the
 * out-of-service board is claims-driven: each row links
 * straight at the open claim that is the item's repair (or at
 * the item's Claims / Replace tab when no claim is driving it).
 *
 * On the merged page the two boards live on different tabs —
 * the out-of-service board on the landing Out of service tab
 * (which reads it through the inventory-gated endpoint and may
 * append borrowed rows), the schedules on the Tool Maintenance
 * tab — so they are separate components here. Both boards are
 * TRUE lists (list-standard wave 6, 2026-11-02): one record per
 * row under a header row, each fact in its own column.
 */

export function itemPath(entry: { item_kind: string; item_id: string; set_id?: string | null }): string {
  if (entry.item_kind === "battery") return `/inventory/batteries/${entry.item_id}`;
  if (entry.item_kind === "piece") return `/inventory/${entry.set_id ?? entry.item_id}`;
  return `/inventory/${entry.item_id}`;
}

export function TableHead({ cols }: { cols: (string | null)[] }) {
  return (
    <div className="tv-maint-thead" role="row">
      {cols.map((col, i) =>
        col === null ? (
          <span key={i} aria-hidden="true" />
        ) : (
          <span key={i} role="columnheader">
            {col}
          </span>
        ),
      )}
    </div>
  );
}

/** The Dealer column's cell (owner, sheet row 143, 2026-11-18):
 *  brand over dealer, the way the main tools list stacks them;
 *  the one alone when only one exists; the standard dash when
 *  neither does. Shared by the board rows and the borrowed rows. */
export function DealerCell({
  brand,
  dealerName,
}: {
  brand: string | null | undefined;
  dealerName: string | null | undefined;
}) {
  const brandText = (brand || "").trim();
  const dealerText = (dealerName || "").trim();
  const joined = [brandText, dealerText].filter(Boolean).join(" · ");
  return (
    <div role="cell">
      <span className="tv-maint-mlabel">Dealer/Brand</span>
      {brandText || dealerText ? (
        <span title={joined || undefined}>
          <span>{brandText || dealerText}</span>
          {brandText && dealerText && (
            <span className="tv-maint-dealer-sub">{dealerText}</span>
          )}
        </span>
      ) : (
        "—"
      )}
    </div>
  );
}

export function OutOfServiceRow({ entry }: { entry: OutOfServiceEntry }) {
  return (
    <div className="tv-maint-row" role="row">
      <div className="tv-maint-cell-item" role="cell">
        <Link to={itemPath(entry)} style={{ color: "var(--accent)" }}>
          {entry.item_name}
        </Link>
        {entry.item_kind === "piece" && <Badge tone="neutral">Piece of {entry.set_name}</Badge>}
      </div>
      <DealerCell brand={entry.brand} dealerName={entry.dealer_company_name} />
      <div role="cell">
        <span className="tv-maint-mlabel">Problem</span>
        <span className="tv-maint-problem" title={entry.problem}>
          {/* A lost/stolen item with no claim, problem text or
              loss-report notes still names its reason (sheet
              row 6) — never a blank cell. */}
          {entry.problem ||
            (entry.state === "lost"
              ? "Marked lost"
              : entry.state === "stolen"
                ? "Marked stolen"
                : entry.problem)}
        </span>
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Since</span>
        {entry.since ? fullDate(entry.since) : "—"}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Status</span>
        <Badge tone={REPAIR_STATE_TONES[entry.state]} dot>
          {REPAIR_STATE_LABELS[entry.state]}
        </Badge>
      </div>
      {/* Work the repair from here: straight at the open claim
          that IS the repair (merge, 2026-11-04), or at the item's
          Claims / Replace tab when no claim is driving it. The
          claim's own status rides beside the link (Repairs &
          Maintenance merge, 2026-11-05) — it arrives only while
          the claims module is effective for the reader. */}
      <div role="cell">
        {entry.claim_id ? (
          <span className="tv-maint-claimcell">
            <Link to={`/claims/${entry.claim_id}`} style={{ color: "var(--accent)", fontSize: "0.9rem" }}>
              Open claim {entry.claim_number ?? ""} →
            </Link>
            {entry.claim_status && <StatusBadge status={entry.claim_status} />}
          </span>
        ) : (
          <Link to={`${itemPath(entry)}#claims`} style={{ color: "var(--accent)", fontSize: "0.9rem" }}>
            Open item →
          </Link>
        )}
      </div>
    </div>
  );
}

/** The board's empty state, shared by the tab that hosts it. */
export function OutOfServiceEmpty() {
  return (
    <EmptyState
      title="Everything is in service"
      description="Anything out of service shows up here — an item (or a single set piece) marked broken or sent for repair, marked lost or stolen, or lent out — until it's back. The repair itself runs on the item's claim."
    />
  );
}

function ScheduleRow({
  schedule,
  onLogged,
}: {
  schedule: MaintenanceSchedule;
  onLogged: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  async function quickLog() {
    setBusy(true);
    try {
      await logDone(schedule.id, {});
      toast(`“${scheduleTitle(schedule)}” logged done today.`, {
        tone: "success",
        title: "Maintenance",
      });
      onLogged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't log that.", {
        tone: "danger",
      });
      setBusy(false);
    }
  }

  return (
    <div className="tv-maint-row" role="row">
      <div className="tv-maint-cell-item" role="cell">
        <Link to={itemPath(schedule)} style={{ color: "var(--accent)" }}>
          {schedule.item_name}
        </Link>
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Schedule</span>
        {scheduleTitle(schedule)}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Type</span>
        {SCHEDULE_KIND_LABELS[schedule.kind]}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Interval</span>
        {schedule.interval_days ? `Every ${schedule.interval_days} days` : "—"}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Last done</span>
        {schedule.last_done_at ? fullDate(schedule.last_done_at) : "Never done"}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Next due</span>
        {schedule.next_due ? fullDate(schedule.next_due) : "—"}
      </div>
      <div role="cell">
        <span className="tv-maint-mlabel">Status</span>
        <Badge tone={DUE_STATUS_TONES[schedule.due_status]} dot>
          {DUE_STATUS_LABELS[schedule.due_status]}
        </Badge>
      </div>
      <div role="cell">
        <Button type="button" size="sm" variant="secondary" loading={busy} onClick={() => void quickLog()}>
          Mark done
        </Button>
      </div>
    </div>
  );
}

type DueFilter = "all" | "due_soon" | "overdue";

/** The schedules board — the Tool Maintenance tab's content on
 *  the merged page: every schedule across the owner's items
 *  with its computed due standing and a one-click "log done",
 *  exactly as the module page carried it. (The page's H1 and
 *  out-of-service board live elsewhere now — see the file
 *  header.) */
export function MaintenanceSchedules() {
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<DueFilter>("all");

  const load = useCallback(() => {
    getMaintenanceOverview()
      .then(setOverview)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load maintenance."),
      );
  }, []);

  useEffect(load, [load]);

  if (error) return <Alert tone="danger">{error}</Alert>;
  if (overview === null) return <Spinner label="Loading maintenance…" />;

  const schedules = overview.schedules.filter((s) => {
    if (filter === "all") return true;
    if (filter === "overdue") return s.due_status === "overdue";
    // F5-12: due-soon and overdue are DISJOINT — the old filter
    // counted overdue items in both chips (2 = 1 + 1 read as 2 + 1).
    return s.due_status === "due_soon";
  });
  const overdueCount = overview.schedules.filter((s) => s.due_status === "overdue").length;
  const dueSoonCount = overview.schedules.filter(
    (s) => s.due_status === "due_soon",
  ).length;

  const chip = (value: DueFilter, label: string) => (
    <Button
      key={value}
      type="button"
      size="sm"
      variant={filter === value ? "primary" : "secondary"}
      onClick={() => setFilter(value)}
    >
      {label}
    </Button>
  );

  return (
    <Panel title="Schedules" className="tv-maint-panel">
      <div style={{ display: "grid", gap: "0.6rem" }}>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {chip("all", `All (${overview.schedules.length})`)}
          {chip("due_soon", `Due soon (${dueSoonCount})`)}
          {chip("overdue", `Overdue (${overdueCount})`)}
        </div>
        {schedules.length === 0 ? (
          <EmptyState
            title={filter === "all" ? "No schedules yet" : "Nothing in this view"}
            description={
              filter === "all"
                ? "Add a calibration, service, or inspection schedule from any tool or battery's page — due dates are worked out automatically."
                : "No schedules match this filter right now."
            }
          />
        ) : (
          <div className="tv-maint-table tv-maint-table--schedules" role="table">
            <TableHead cols={["Item", "Schedule", "Type", "Interval", "Last done", "Next due", "Status", null]} />
            {schedules.map((schedule) => (
              <ScheduleRow key={schedule.id} schedule={schedule} onLogged={load} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
