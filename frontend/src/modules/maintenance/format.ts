/** Maintenance display helpers: labels, tones, dates — one
 *  phrasing everywhere (detail panels, module page, set badges). */

import type { BadgeTone } from "../../components";
import { formatDate } from "../../lib/format";
import type { DueStatus, RepairState, ScheduleKind } from "./types";

export const REPAIR_STATE_LABELS: Record<RepairState, string> = {
  // The item's repair STATE label — an item-status label, so it
  // follows the owner's 2026-11-03 rename: "Available", not
  // "In service".
  in_service: "Available",
  broken: "Broken",
  in_repair: "In repair",
  lost: "Lost",
  stolen: "Stolen",
};

export const REPAIR_STATE_TONES: Record<RepairState, BadgeTone> = {
  in_service: "success",
  broken: "danger",
  in_repair: "warning",
  lost: "neutral",
  stolen: "danger",
};

export const SCHEDULE_KIND_LABELS: Record<ScheduleKind, string> = {
  calibration: "Calibration",
  service: "Service",
  inspection: "Inspection",
  other: "Other",
};

export const DUE_STATUS_LABELS: Record<DueStatus, string> = {
  overdue: "Overdue",
  due_soon: "Due soon",
  ok: "On schedule",
  unknown: "No due date",
};

export const DUE_STATUS_TONES: Record<DueStatus, BadgeTone> = {
  overdue: "danger",
  due_soon: "warning",
  ok: "success",
  unknown: "neutral",
};

/** "Oct 30, 2026" for an ISO datetime/date; "—" when absent. */
export function fullDate(iso: string | null | undefined): string {
  return formatDate(iso);
}

/** A schedule's human title: its label, else its kind. */
export function scheduleTitle(s: { label: string; kind: ScheduleKind }): string {
  return s.label || SCHEDULE_KIND_LABELS[s.kind];
}
