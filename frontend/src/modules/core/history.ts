/**
 * History & restore — shared wire shapes + formatting for the
 * user audit trail (Settings section and the Admin user drawer's
 * on-behalf block render the same data).
 */

export interface RestoreMarker {
  id: string;
  label: string;
  kind: "baseline" | "daily" | "manual" | "pre_bulk" | "pre_restore" | string;
  journal_seq: number;
  created_at: string;
}

export interface JournalEntry {
  id: string;
  seq: number;
  occurred_at: string;
  module: string;
  entity_type: string;
  action: string;
  label: string;
  restorable: boolean;
  actor: "you" | "owner" | "other" | "system" | string;
}

export interface RestorePreview {
  marker_id: string;
  changes_to_undo: number;
  shared_not_changed: number;
}

export interface RestoreResult {
  restored: number;
  not_changed: number;
  pre_restore_marker_id: string;
  marker_id: string;
}

const KIND_FALLBACK: Record<string, string> = {
  baseline: "Account created",
  daily: "Daily restore point",
  manual: "Restore point",
  pre_bulk: "Before a bulk change",
  pre_restore: "Before a restore",
};

export function markerTitle(marker: RestoreMarker): string {
  return marker.label?.trim() || KIND_FALLBACK[marker.kind] || "Restore point";
}

export function markerWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function entryDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function entryTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Group entries (already newest-first) under day headings. */
export function groupByDay(
  entries: JournalEntry[],
): { day: string; entries: JournalEntry[] }[] {
  const groups: { day: string; entries: JournalEntry[] }[] = [];
  for (const entry of entries) {
    const day = entryDay(entry.occurred_at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.entries.push(entry);
    else groups.push({ day, entries: [entry] });
  }
  return groups;
}
