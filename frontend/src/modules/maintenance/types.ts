/** Maintenance module shapes — mirror the backend's
 *  app/modules/maintenance/schemas.py payloads. */

import type { Attachment } from "../inventory/types";

export type CareItemKind = "tool" | "battery" | "piece";

/** An item's current standing, stored on the inventory record
 *  and written by the claims lifecycle since the repairs ∪
 *  claims merge (2026-11-04) — the repair history lives on the
 *  item's claims now. Package B widened the asset standing with
 *  lost/stolen (set pieces keep the repair trio — a piece's state
 *  never reads lost/stolen). */
export type RepairState = "in_service" | "broken" | "in_repair" | "lost" | "stolen";

export type ScheduleKind = "calibration" | "service" | "inspection" | "other";

export type DueStatus = "overdue" | "due_soon" | "ok" | "unknown";

export interface MaintenanceLogEntry {
  id: string;
  schedule_id: string;
  done_date: string;
  cost: string | null;
  technician: string;
  notes: string;
  /** Documents on this entry (Package B — calibration
   *  certificates and the like), the shared attachment shape. */
  attachments: Attachment[];
  created_at: string;
}

export interface MaintenanceSchedule {
  id: string;
  item_kind: "tool" | "battery";
  item_id: string;
  item_name: string;
  kind: ScheduleKind;
  label: string;
  interval_days: number | null;
  due_date: string | null;
  last_done_at: string | null;
  /** Computed server-side — never stored. */
  next_due: string | null;
  due_status: DueStatus;
  log: MaintenanceLogEntry[];
  created_at: string;
  updated_at: string;
}

export interface PieceStanding {
  piece_id: string;
  name: string;
  kind: "core" | "addon";
  state: RepairState;
  problem: string;
}

export interface ItemStanding {
  item_kind: CareItemKind;
  item_id: string;
  item_name: string;
  state: RepairState;
  problem: string;
  schedules: MaintenanceSchedule[];
  /** Sets only: each piece's own standing. */
  pieces: PieceStanding[];
}

export interface OutOfServiceEntry {
  item_kind: CareItemKind;
  item_id: string;
  item_name: string;
  set_id: string | null;
  set_name: string;
  state: Exclude<RepairState, "in_service">;
  problem: string;
  since: string | null;
  /** The open warranty claim driving the repair, when there is
   *  one (merge, 2026-11-04) — the board links straight at it. */
  claim_id: string | null;
  claim_number: string | null;
  /** The driving claim's status (Repairs & Maintenance merge,
   *  2026-11-05) — rides with the other claim facts: null when
   *  no claim drives the repair OR the claims module is off for
   *  the reader. Typed as the claims module's status union via
   *  a local mirror to keep the modules decoupled. */
  claim_status:
    | "not_reported"
    | "reported"
    | "in_repair"
    | "completed"
    | null;
}

export interface MaintenanceOverview {
  out_of_service: OutOfServiceEntry[];
  schedules: MaintenanceSchedule[];
}

export interface MaintenanceStats {
  maintenance_due_count: number;
  out_of_service_count: number;
}
