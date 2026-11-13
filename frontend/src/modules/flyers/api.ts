import { api } from "../../lib/api";
import type {
  CompanyFlyers,
  DetectedPage,
  FlyerSource,
  FlyerView,
  ScanPage,
} from "./types";

/** Flyers module API (backend: app/modules/flyers). Every call
 *  403s with module_unavailable when the module is off for the
 *  user — embedded callers (Home widget, dealer tab) treat that
 *  as "hide", never as an error worth surfacing. */

export function flyerFeed(): Promise<FlyerSource[]> {
  return api<FlyerSource[]>("/flyers/feed");
}

export function listSources(): Promise<FlyerSource[]> {
  return api<FlyerSource[]>("/flyers/sources");
}

export function sourceDetail(id: string): Promise<FlyerSource> {
  return api<FlyerSource>(`/flyers/sources/${id}`);
}

export function listPostable(): Promise<FlyerSource[]> {
  return api<FlyerSource[]>("/flyers/postable");
}

export function createSource(body: {
  kind: string;
  company_id: string;
  agent_user_id?: string | null;
  private_agent_id?: string | null;
}): Promise<FlyerSource> {
  return api<FlyerSource>("/flyers/sources", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateSource(
  id: string,
  body: { visible?: boolean; history_visible?: boolean; standing_url?: string },
): Promise<FlyerSource> {
  return api<FlyerSource>(`/flyers/sources/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function postLink(
  sourceId: string,
  body: { url: string; label: string; starts_on: string; ends_on: string },
): Promise<FlyerView> {
  return api<FlyerView>(`/flyers/sources/${sourceId}/flyers/link`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

interface UploadTicket {
  upload_url: string;
  key: string;
  expires_in: number;
}

async function putFile(url: string, file: File): Promise<void> {
  const resp = await fetch(url, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type || "application/octet-stream" },
  });
  if (!resp.ok) throw new Error(`Upload failed (${resp.status})`);
}

/** Upload-PDF route: stage the file through a presigned PUT,
 *  then post it — the server verifies the staged object before
 *  a byte is trusted. */
export async function postPdfUpload(
  sourceId: string,
  file: File,
  body: { label: string; starts_on: string; ends_on: string },
): Promise<FlyerView> {
  const ticket = await api<UploadTicket>("/flyers/uploads/pdf-url", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/pdf",
      size_bytes: file.size,
    }),
  });
  await putFile(ticket.upload_url, file);
  return api<FlyerView>(`/flyers/sources/${sourceId}/flyers/upload`, {
    method: "POST",
    body: JSON.stringify({ key: ticket.key, ...body }),
  });
}

/** Stage one page photo and run paper-edge detection over it. */
export async function stagePhoto(file: File): Promise<DetectedPage> {
  const ticket = await api<UploadTicket>("/flyers/uploads/photo-url", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "image/jpeg",
      size_bytes: file.size,
    }),
  });
  await putFile(ticket.upload_url, file);
  const pages = await api<DetectedPage[]>("/flyers/scan/detect", {
    method: "POST",
    body: JSON.stringify({ keys: [ticket.key] }),
  });
  return pages[0];
}

export function postPhotos(
  sourceId: string,
  body: {
    pages: ScanPage[];
    label: string;
    starts_on: string;
    ends_on: string;
  },
): Promise<FlyerView> {
  return api<FlyerView>(`/flyers/sources/${sourceId}/flyers/photos`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteFlyer(id: string): Promise<{ deleted: boolean }> {
  return api<{ deleted: boolean }>(`/flyers/flyers/${id}`, {
    method: "DELETE",
  });
}

export function companyFlyers(
  companyId: string,
  asVisitor = false,
): Promise<CompanyFlyers> {
  return api<CompanyFlyers>(
    asVisitor
      ? `/flyers/companies/${companyId}?as_visitor=true`
      : `/flyers/companies/${companyId}`,
  );
}

export function getAlerts(): Promise<{ enabled: boolean }> {
  return api<{ enabled: boolean }>("/flyers/alerts");
}

export function putAlerts(enabled: boolean): Promise<{ enabled: boolean }> {
  return api<{ enabled: boolean }>("/flyers/alerts", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}
