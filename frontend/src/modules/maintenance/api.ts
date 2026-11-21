/** Maintenance module API calls — thin typed wrappers over the
 *  shared client (auth + refresh handled there). Schedules and
 *  standings since the merge; the repair lifecycle lives in the
 *  claims module now. */

import { api } from "../../lib/api";
import type {
  CareItemKind,
  ItemStanding,
  MaintenanceLogEntry,
  MaintenanceOverview,
  MaintenanceStats,
  OutOfServiceEntry,
  ScheduleKind,
} from "./types";

export function getMaintenanceOverview(): Promise<MaintenanceOverview> {
  return api<MaintenanceOverview>("/maintenance/overview");
}

/** The out-of-service board alone (Repairs & Maintenance merge,
 *  2026-11-05): the merged page's landing tab reads the board
 *  through this inventory-gated endpoint, so the board survives
 *  the maintenance module being off. Claim facts ride only
 *  while the claims module is effective for the caller (the
 *  server resolves that per user). */
export function getOutOfService(): Promise<OutOfServiceEntry[]> {
  return api<OutOfServiceEntry[]>("/maintenance/out-of-service");
}

export function getMaintenanceStats(): Promise<MaintenanceStats> {
  return api<MaintenanceStats>("/maintenance/stats");
}

export function getItemStanding(
  itemKind: CareItemKind,
  itemId: string,
): Promise<ItemStanding> {
  return api<ItemStanding>(`/maintenance/items/${itemKind}/${itemId}`);
}

export interface ScheduleCreateBody {
  kind: ScheduleKind;
  label?: string;
  interval_days?: number | null;
  due_date?: string | null;
  last_done_at?: string | null;
}

export function createSchedule(
  itemKind: "tool" | "battery",
  itemId: string,
  body: ScheduleCreateBody,
) {
  return api(`/maintenance/items/${itemKind}/${itemId}/schedules`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteSchedule(scheduleId: string): Promise<void> {
  return api<void>(`/maintenance/schedules/${scheduleId}`, {
    method: "DELETE",
  });
}

export function logDone(
  scheduleId: string,
  body: {
    done_date?: string | null;
    cost?: string | null;
    technician?: string;
    notes?: string;
  },
): Promise<MaintenanceLogEntry> {
  return api<MaintenanceLogEntry>(`/maintenance/schedules/${scheduleId}/log`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

interface LogEntryUploadUrl {
  upload_url: string;
  key: string;
  expires_in: number;
}

/** Attach a document to a log entry (Package B — calibration
 *  certificates): the inventory attachment machinery's presigned
 *  flow against the maintenance routes — request a URL, PUT the
 *  bytes to storage, then link the key to the entry. */
export async function uploadLogEntryDocument(
  entryId: string,
  file: File,
  contentType: string,
): Promise<void> {
  const { upload_url, key } = await api<LogEntryUploadUrl>(
    `/maintenance/log-entries/${entryId}/upload-url`,
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: contentType,
        kind: "document",
        size_bytes: file.size,
      }),
    },
  );
  const put = await fetch(upload_url, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: file,
  });
  if (!put.ok) throw new Error(`Upload failed (HTTP ${put.status})`);
  await api(`/maintenance/log-entries/${entryId}/attachments`, {
    method: "POST",
    body: JSON.stringify({ key, filename: file.name }),
  });
}
