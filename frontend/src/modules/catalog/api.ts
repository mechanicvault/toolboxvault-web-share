import { api } from "../../lib/api";

/** Catalog module API (wave 4): the layered lookup behind Quick
 *  Add, AI item identification, and Locate User Manual. */

export interface LookupField {
  value: string | number;
  source: "community" | "barcode" | "web" | "ai" | string;
  detail: string;
}

export interface LookupResult {
  fields: Record<string, LookupField>;
  sources: string[];
  ai_charged: number;
  /** Grounded contract (2026-10-25): partial = real details
   *  but no verified name; image_url = the product page's real
   *  photo; source_name/source_url name the page the web facts
   *  were read from; web_configured = the web search layer is
   *  switched on; link_error = a pasted page couldn't be read. */
  partial?: boolean;
  /** Mismatch honesty (C-08): model_mismatch = the winning
   *  page's model differs from the typed model (a variant);
   *  found_model names that page's model so the card can say
   *  so in plain words before anything is prefilled. */
  model_mismatch?: boolean;
  found_model?: string | null;
  /** Photo identification only: the model's own stated
   *  confidence in its read ("high" | "medium" | "low"), so
   *  the surface can say plainly how sure the AI is. */
  confidence?: string | null;
  image_url?: string | null;
  source_name?: string | null;
  source_url?: string | null;
  web_configured?: boolean;
  link_error?: boolean;
}

export interface AiStatus {
  configured: boolean;
  provider: string;
  model: string;
}

export interface ManualCandidate {
  title: string;
  source_name: string;
  source_url: string;
  file_type: string;
  importable: boolean;
  /** Byte size when the source states it (found manuals are
   *  probe-verified server-side, so this is real when present). */
  size_bytes?: number | null;
}

export interface ManualSearchResult {
  /** Proven, pullable PDF manuals — the only "found" tier. */
  candidates: ManualCandidate[];
  /** Backup web pages, shown only when no manual was found. */
  links: ManualCandidate[];
  charged: number;
}

export function lookupProduct(params: {
  brand?: string;
  model?: string;
  upc?: string;
  link?: string;
}): Promise<LookupResult> {
  const q = new URLSearchParams();
  if (params.brand) q.set("brand", params.brand);
  if (params.model) q.set("model", params.model);
  if (params.upc) q.set("upc", params.upc);
  if (params.link) q.set("link", params.link);
  return api<LookupResult>(`/catalog/lookup?${q.toString()}`);
}

/** Download the product photo a grounded page offered (the
 *  server fetches it with the manual-import SSRF guards) and
 *  hand it back as a File the wizard stages exactly like an
 *  uploaded photo. Throws ApiError (code photo_unreadable)
 *  when the link doesn't lead to a real photo. */
export async function fetchLookupPhoto(url: string): Promise<File> {
  const data = await api<{
    filename: string;
    content_type: string;
    data_base64: string;
  }>("/catalog/fetch-photo", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
  const binary = atob(data.data_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new File([bytes], data.filename, { type: data.content_type });
}

export function identifyItem(text: string): Promise<LookupResult> {
  return api<LookupResult>("/catalog/identify", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

/** Photo identification (AI wizard completion, 2026-11-07):
 *  one photo of the item (or its label) -> the same LookupResult
 *  contract as identifyItem, plus the model's stated
 *  confidence. The browser reads the file and posts its bytes
 *  as base64; the server byte-sniffs the real type and the AI
 *  seam's vision reads it. Callers keep the file under the
 *  server's 8 MB cap (checked here too, so the refusal is
 *  instant and plain). */
export const IDENTIFY_PHOTO_MAX_BYTES = 8 * 1024 * 1024;

export async function identifyPhoto(file: File): Promise<LookupResult> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("read failed"));
    reader.readAsDataURL(file);
  });
  const base64 = dataUrl.includes(",")
    ? dataUrl.slice(dataUrl.indexOf(",") + 1)
    : dataUrl;
  return api<LookupResult>("/catalog/identify-photo", {
    method: "POST",
    body: JSON.stringify({ image_base64: base64 }),
  });
}

export function fetchAiStatus(): Promise<AiStatus> {
  return api<AiStatus>("/catalog/ai-status");
}

export function locateManual(
  segment: "tools" | "batteries",
  itemId: string,
): Promise<ManualSearchResult> {
  return api<ManualSearchResult>(`/inventory/${segment}/${itemId}/locate-manual`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

/** The wizard's search door (owner order 2026-11-05): brand +
 *  model from the draft, before the item exists. The pick is
 *  imported through importManual once the item is created. */
export function searchManuals(
  brand: string,
  model: string,
): Promise<ManualSearchResult> {
  return api<ManualSearchResult>(`/inventory/manual-lookup`, {
    method: "POST",
    body: JSON.stringify({ brand, model }),
  });
}

export function importManual(
  segment: "tools" | "batteries",
  itemId: string,
  sourceUrl: string,
  sourceName: string,
): Promise<{ attachment: unknown; already_present: boolean }> {
  return api(`/inventory/${segment}/${itemId}/locate-manual/import`, {
    method: "POST",
    body: JSON.stringify({ source_url: sourceUrl, source_name: sourceName }),
  });
}

/** Add a manual by pasting a link (owner ruling 2026-11-03):
 *  the server fetches the address itself (SSRF-guarded, PDFs
 *  only) and stores the downloaded bytes as the item's manual.
 *  Throws ApiError with the server's refusal message when the
 *  link can't be used — nothing is filed in that case. */
export function importManualLink(
  segment: "tools" | "batteries",
  itemId: string,
  url: string,
): Promise<{ attachment: unknown; already_present: boolean }> {
  return api(`/inventory/${segment}/${itemId}/locate-manual/import-link`, {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}
