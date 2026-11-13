/** Importer API (backend: inventory module's import_routes). The
 *  upload is multipart, so it runs on the stored access token
 *  directly (like the reports downloads); everything else uses the
 *  JSON helper. Every call 403s with module_unavailable when the
 *  inventory module is off or unassigned for the user. */

import { TOKEN_KEY, api } from "../../lib/api";

export type ImportKind = "tool" | "battery";

export interface ImportField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  custom_type?: string | null;
}

export interface ImportSession {
  session_id: string;
  filename: string;
  file_format: string;
  kind: ImportKind;
  headers: string[];
  sample_rows: string[][];
  row_count: number;
  expires_at: string;
  fields: ImportField[];
  suggested_mapping: Record<string, string>;
}

export interface ImportSuggestion {
  kind: ImportKind;
  fields: ImportField[];
  suggested_mapping: Record<string, string>;
}

/** {columnIndex: fieldKey | null} — null/absent means "don't import". */
export type ImportMapping = Record<string, string | null>;

export interface ImportRowPreview {
  models: string[];
  serials: string[];
  is_set: boolean;
  set_serials: string[];
}

export interface ImportRowResult {
  row: number;
  status: "ok" | "warning" | "error" | "blank";
  name: string;
  messages: string[];
  duplicate: boolean;
  preview: ImportRowPreview;
}

export interface ImportCap {
  enforcement: boolean;
  limit?: number | null;
  current_count?: number | null;
  remaining?: number | null;
  would_exceed: number;
}

/** Smart value matching (2026-10-19): one Resolve-step answer for
 *  one distinct incoming value. map -> target_id (dealer/location)
 *  or target_value (brand/category/tag); create -> a new value
 *  (location may carry the parent_id to create under); unset ->
 *  drop the value. */
export interface ImportResolutionDecision {
  action: "map" | "create" | "unset";
  target_id?: string | null;
  target_value?: string | null;
  parent_id?: string | null;
}

/** {fieldKey: {rawValue: decision}} — travels with dry run and
 *  confirm; automatic matches need no entry. */
export type ImportResolutions = Record<
  string,
  Record<string, ImportResolutionDecision>
>;

export interface ImportTarget {
  target_id: string | null;
  target_value: string | null;
  label: string;
  score?: number | null;
}

export interface ImportResolveEntry {
  field: string;
  raw: string;
  rows: number;
  status: "auto" | "ask";
  source: string | null; // exact | learned (auto entries)
  resolution: ImportResolutionDecision | null;
  candidates: ImportTarget[];
}

export interface ImportResolvePlan {
  entries: ImportResolveEntry[];
  options: Record<string, ImportTarget[]>;
  unresolved: number;
}

/** One mapping a run applied — listed in the dry run and the final
 *  summary, silent matches included. */
export interface ImportMappingApplied {
  field: string;
  raw: string;
  rows: number;
  action: string; // map | create | unset
  target_label: string;
  source: string; // exact | learned | decision
}

export interface ImportDryRun {
  session_id: string;
  kind: ImportKind;
  total_rows: number;
  counts: Record<string, number>;
  importable: number;
  cap: ImportCap;
  rows: ImportRowResult[];
  mappings: ImportMappingApplied[];
}

export interface ImportSummary {
  kind: ImportKind;
  imported: number;
  skipped_duplicates: number;
  skipped_over_cap: number;
  over_cap_rows: number[];
  errors: number;
  error_rows: { row: number; messages: string[] }[];
  total_rows: number;
  mappings: ImportMappingApplied[];
}

/** One remembered Resolve answer (Settings -> Import matching). */
export interface LearnedMapping {
  id: string;
  field: string;
  raw_value: string;
  action: string;
  target_id: string | null;
  target_value: string | null;
  target_label: string;
  updated_at: string;
}

export async function uploadImportFile(
  file: File,
  kind: ImportKind,
): Promise<ImportSession> {
  const token = localStorage.getItem(TOKEN_KEY);
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  const response = await fetch("/api/inventory/import/upload", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!response.ok) {
    let message = `Upload failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(message);
  }
  return (await response.json()) as ImportSession;
}

export function suggestImportMapping(
  sessionId: string,
  kind: ImportKind,
): Promise<ImportSuggestion> {
  return api<ImportSuggestion>(`/inventory/import/${sessionId}/suggest`, {
    method: "POST",
    body: JSON.stringify({ kind }),
  });
}

export function resolveImportValues(
  sessionId: string,
  kind: ImportKind,
  mapping: ImportMapping,
): Promise<ImportResolvePlan> {
  return api<ImportResolvePlan>(`/inventory/import/${sessionId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ kind, mapping }),
  });
}

export function dryRunImport(
  sessionId: string,
  kind: ImportKind,
  mapping: ImportMapping,
  skipDuplicates: boolean,
  resolutions: ImportResolutions = {},
): Promise<ImportDryRun> {
  return api<ImportDryRun>(`/inventory/import/${sessionId}/dry-run`, {
    method: "POST",
    body: JSON.stringify({
      kind,
      mapping,
      skip_duplicates: skipDuplicates,
      resolutions,
    }),
  });
}

export function confirmImport(
  sessionId: string,
  kind: ImportKind,
  mapping: ImportMapping,
  skipDuplicates: boolean,
  resolutions: ImportResolutions = {},
): Promise<ImportSummary> {
  return api<ImportSummary>(`/inventory/import/${sessionId}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      kind,
      mapping,
      skip_duplicates: skipDuplicates,
      resolutions,
    }),
  });
}

export function listLearnedMappings(): Promise<LearnedMapping[]> {
  return api<LearnedMapping[]>(`/inventory/import/learned`);
}

export function deleteLearnedMapping(id: string): Promise<void> {
  return api<void>(`/inventory/import/learned/${id}`, { method: "DELETE" });
}

export function discardImportSession(sessionId: string): Promise<void> {
  return api<void>(`/inventory/import/${sessionId}`, { method: "DELETE" });
}
