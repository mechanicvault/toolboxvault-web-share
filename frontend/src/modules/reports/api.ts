/** Reports module API (backend: app/modules/reports). Every call
 *  403s with module_unavailable when the module is off or
 *  unassigned for the user. Exports POST a report spec and stream
 *  the generated file back — they bypass the JSON helper and run
 *  on the stored access token directly. */

import { TOKEN_KEY, api } from "../../lib/api";
import type { ViewableAttachment } from "../../components/AttachmentViewer";
import type {
  CatalogType,
  HistoryEntry,
  ReportArea,
  ReportConfigView,
  ReportResult,
  ReportSpec,
  ReportTemplateView,
  ReportsMeta,
} from "./types";

export function getReportsMeta(): Promise<ReportsMeta> {
  return api<ReportsMeta>("/reports/meta");
}

export function runReport(
  spec: ReportSpec & { page?: number; page_size?: number },
): Promise<ReportResult> {
  return api<ReportResult>("/reports/run", {
    method: "POST",
    body: JSON.stringify(spec),
  });
}

export function listConfigs(): Promise<{
  saved: ReportConfigView[];
  presets: ReportConfigView[];
}> {
  return api("/reports/configs");
}

export function createConfig(name: string, spec: ReportSpec): Promise<ReportConfigView> {
  return api<ReportConfigView>("/reports/configs", {
    method: "POST",
    body: JSON.stringify({ name, spec }),
  });
}

export function updateConfig(
  id: string,
  name: string,
  spec: ReportSpec,
): Promise<ReportConfigView> {
  return api<ReportConfigView>(`/reports/configs/${id}`, {
    method: "PUT",
    body: JSON.stringify({ name, spec }),
  });
}

export function deleteConfig(id: string): Promise<void> {
  return api<void>(`/reports/configs/${id}`, { method: "DELETE" });
}

export type ExportFormat = "csv" | "xlsx" | "pdf";

async function download(path: string, spec: ReportSpec, filename: string): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(spec),
  });
  if (!response.ok) {
    throw new Error(`Export failed (${response.status}).`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function exportReport(format: ExportFormat, spec: ReportSpec): Promise<void> {
  return download(`/reports/export/${format}`, spec, `inventory-report.${format}`);
}

/** AI narrative summary (wave 4): a plain-language paragraph
 *  from the report's aggregates. 503s ai_not_configured while
 *  the seam is dark — the page only offers it when AI is on. */
export function reportNarrative(
  spec: ReportSpec,
): Promise<{ narrative: string; ai_charged: number }> {
  return api("/reports/narrative", {
    method: "POST",
    body: JSON.stringify(spec),
  });
}

export function emailReport(body: {
  format: ExportFormat;
  recipient?: string;
  report_name?: string;
  spec: ReportSpec;
}): Promise<{ sent: boolean; recipient: string; filename: string }> {
  const { spec, ...rest } = body;
  return api("/reports/email", {
    method: "POST",
    body: JSON.stringify({ ...rest, ...spec }),
  });
}

/* -- Reports page redesign (2026-11-06): catalog, templates,
 *    generation, history. Generation stores the file server-side
 *    and returns its History row; the bytes move through the
 *    history download route (and the preview route for the
 *    wizard's look-before-you-generate step). */

export function getCatalog(): Promise<{
  types: CatalogType[];
  /** Admin report types (admin lane, 2026-11-07) — the field
   *  exists ONLY for god + moderator_admin seats; a member's
   *  catalog response has no trace of it. */
  admin_types?: CatalogType[];
}> {
  return api("/reports/catalog");
}

export function describeReport(
  reportType: string,
  settings: Record<string, unknown>,
): Promise<{ name: string; description: string }> {
  return api("/reports/describe", {
    method: "POST",
    body: JSON.stringify({ report_type: reportType, settings }),
  });
}

export function listTemplates(): Promise<{ templates: ReportTemplateView[] }> {
  return api("/reports/templates");
}

export function createTemplate(body: {
  report_type: string;
  name?: string;
  description?: string;
  area?: ReportArea;
  settings?: Record<string, unknown>;
}): Promise<ReportTemplateView> {
  return api<ReportTemplateView>("/reports/templates", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteTemplate(id: string): Promise<void> {
  return api<void>(`/reports/templates/${id}`, { method: "DELETE" });
}

export function generateReport(body: {
  report_type: string;
  settings: Record<string, unknown>;
  format: string;
  name?: string;
}): Promise<HistoryEntry> {
  return api<HistoryEntry>("/reports/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function runTemplate(
  id: string,
  body: { format?: string; year?: number | null },
): Promise<HistoryEntry> {
  return api<HistoryEntry>(`/reports/templates/${id}/run`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

async function authedFetch(path: string, init: RequestInit): Promise<Response> {
  const token = localStorage.getItem(TOKEN_KEY);
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}).`);
  }
  return response;
}

/** The wizard's preview: the actual document, built but never
 *  stored. Returns the blob + its content type. */
export async function previewReport(body: {
  report_type: string;
  settings: Record<string, unknown>;
  format: string;
}): Promise<{ blob: Blob; contentType: string }> {
  const response = await authedFetch("/reports/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const blob = await response.blob();
  return { blob, contentType: response.headers.get("Content-Type") ?? blob.type };
}

export function listHistory(params: {
  from?: string;
  to?: string;
  format?: string;
  q?: string;
}): Promise<{ entries: HistoryEntry[] }> {
  const query = new URLSearchParams();
  if (params.from) query.set("from", params.from);
  if (params.to) query.set("to", params.to);
  if (params.format) query.set("format", params.format);
  if (params.q) query.set("q", params.q);
  const suffix = query.toString();
  return api(`/reports/history${suffix ? `?${suffix}` : ""}`);
}

export async function downloadHistory(entry: HistoryEntry): Promise<void> {
  const response = await authedFetch(`/reports/history/${entry.id}/download`, {
    method: "GET",
  });
  const blob = await response.blob();
  // The server names the file (sanitized); fall back to the
  // entry's own name + format when the header is absent.
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const named = /filename="([^"]+)"/.exec(disposition)?.[1];
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = named ?? `${entry.name}.${entry.format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function historyView(id: string): Promise<{ attachment: ViewableAttachment }> {
  return api(`/reports/history/${id}/view`);
}

export function deleteHistory(id: string): Promise<void> {
  return api<void>(`/reports/history/${id}`, { method: "DELETE" });
}
