/** 3D Print Files API — thin wrappers over the shared client
 * (the forum api.ts posture). Reads are public; the client
 * attaches the session when one exists, so signed-in readers
 * get their own rating and ownership flags in the same views.
 *
 * Downloads and the preview are plain URLs (anchors), not
 * client calls — the print download is the public counted
 * door; the STEP door answers 401 signed-out, which an anchor
 * surfaces as the browser's own refusal, so the STEP buttons
 * only render for signed-in members. */

import { api, TOKEN_KEY } from "../../lib/api";
import type {
  MakerLink,
  PrintComment,
  PrintDetail,
  PrintFileRow,
  PrintMedia,
  PrintReport,
} from "./types";

export function browsePrints(params: {
  q?: string;
  category?: string;
  sort?: string;
}): Promise<{
  files: PrintFileRow[];
  total: number;
  stats: { listings: number; downloads: number };
}> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.category) qs.set("category", params.category);
  if (params.sort) qs.set("sort", params.sort);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return api(`/prints/files${suffix}`);
}

export function getPrint(id: string): Promise<PrintDetail> {
  return api(`/prints/files/${id}`);
}

export function getPrintComments(id: string): Promise<{ comments: PrintComment[] }> {
  return api(`/prints/files/${id}/comments`);
}

/** "View as visitor" preview fetches (Sweep D5): the
 * publisher-only reads that return this listing shaped for a
 * signed-in member with no relationship to it — the server
 * runs the same serializers with the visitor stand-in, so
 * what lands here IS the real non-owner data shape. */
export function getPrintAsVisitor(id: string): Promise<PrintDetail> {
  return api(`/prints/files/${id}?as_visitor=true`);
}

export function getPrintCommentsAsVisitor(
  id: string,
): Promise<{ comments: PrintComment[] }> {
  return api(`/prints/files/${id}/comments?as_visitor=true`);
}

export function printDownloadUrl(id: string, version?: number): string {
  return version
    ? `/api/prints/files/${id}/download?version=${version}`
    : `/api/prints/files/${id}/download`;
}

export function stepDownloadUrl(id: string, version?: number): string {
  return version
    ? `/api/prints/files/${id}/step?version=${version}`
    : `/api/prints/files/${id}/step`;
}

export function previewUrl(id: string, size?: "display"): string {
  // The endpoint serves the right-sized rendition: the card
  // size by default (browse cards, the record header plate),
  // the display size for the cover's big-preview modal.
  return size
    ? `/api/prints/files/${id}/preview?size=${size}`
    : `/api/prints/files/${id}/preview`;
}

export function setPrintFollow(
  id: string,
  following: boolean,
): Promise<{ following: boolean }> {
  return api(`/prints/files/${id}/follow`, {
    method: "PUT",
    body: JSON.stringify({ following }),
  });
}

export function ratePrint(id: string, stars: number) {
  return api(`/prints/files/${id}/rate`, {
    method: "POST",
    body: JSON.stringify({ stars }),
  });
}

export function postPrintComment(id: string, body: string): Promise<PrintComment> {
  return api(`/prints/files/${id}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function removePrintComment(commentId: string) {
  return api(`/prints/comments/${commentId}`, { method: "DELETE" });
}

export function reportPrintFile(id: string, reason: string) {
  return api(`/prints/files/${id}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function reportPrintComment(commentId: string, reason: string) {
  return api(`/prints/comments/${commentId}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function removePrintFile(id: string) {
  return api(`/prints/files/${id}`, { method: "DELETE" });
}

export function getMyPrints(): Promise<{ files: PrintFileRow[] }> {
  return api(`/prints/me/files`);
}

export function getMyLinks(): Promise<{ links: MakerLink[] }> {
  return api(`/prints/me/links`);
}

export function createMyLink(label: string, url: string): Promise<MakerLink> {
  return api(`/prints/me/links`, {
    method: "POST",
    body: JSON.stringify({ label, url }),
  });
}

export function deleteMyLink(id: string) {
  return api(`/prints/me/links/${id}`, { method: "DELETE" });
}

/** Multipart publish/update — the shared client JSON-encodes
 * bodies, so uploads go through fetch with the same stored
 * token the client would attach. */
async function uploadForm(path: string, form: FormData): Promise<PrintDetail> {
  const token = localStorage.getItem(TOKEN_KEY);
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    // A 413 never reaches the API — an edge in front of it
    // refused the body — so there is no server detail to read;
    // say the useful thing in words (bug lane 2026-11-09: a
    // member's 31 MB video died exactly here as "Upload failed
    // (413)").
    if (res.status === 413) {
      throw new Error("That file is too large to upload.");
    }
    let message = `Upload failed (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* keep the status message */
    }
    throw new Error(message);
  }
  return (await res.json()) as PrintDetail;
}

export function publishPrint(form: FormData): Promise<PrintDetail> {
  return uploadForm(`/prints/files`, form);
}

export function publishPrintUpdate(id: string, form: FormData): Promise<PrintDetail> {
  return uploadForm(`/prints/files/${id}/versions`, form);
}

/* -- showcase media + the listing edit (2026-11-08) -------- */

/** One media item's bytes — a plain URL (the tab's tiles,
 * the viewer's stage, the <video> element). Public: the
 * whole listing is public, media included. */
export function mediaUrl(fileId: string, mediaId: string): string {
  return `/api/prints/files/${fileId}/media/${mediaId}`;
}

export function updatePrintListing(
  id: string,
  body: { title: string; description: string; category: string },
): Promise<PrintDetail> {
  return api(`/prints/files/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

async function uploadMedia(
  path: string,
  field: string,
  file: File,
): Promise<{ media: PrintMedia[] }> {
  const form = new FormData();
  form.append(field, file);
  const token = localStorage.getItem(TOKEN_KEY);
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    // A 413 never reaches the API — an edge in front of it
    // refused the body — so there is no server detail to read;
    // say the useful thing in words (bug lane 2026-11-09: a
    // member's 31 MB video died exactly here as "Upload failed
    // (413)").
    if (res.status === 413) {
      throw new Error("That file is too large to upload.");
    }
    let message = `Upload failed (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* keep the status message */
    }
    throw new Error(message);
  }
  return (await res.json()) as { media: PrintMedia[] };
}

export function addPrintPhoto(id: string, file: File): Promise<{ media: PrintMedia[] }> {
  return uploadMedia(`/prints/files/${id}/media/photos`, "photo", file);
}

export function addPrintVideo(id: string, file: File): Promise<{ media: PrintMedia[] }> {
  return uploadMedia(`/prints/files/${id}/media/video`, "video", file);
}

export function removePrintMedia(
  id: string,
  mediaId: string,
): Promise<{ media: PrintMedia[] }> {
  return api(`/prints/files/${id}/media/${mediaId}`, { method: "DELETE" });
}

export function reorderPrintMedia(
  id: string,
  mediaIds: string[],
): Promise<{ media: PrintMedia[] }> {
  return api(`/prints/files/${id}/media/order`, {
    method: "PUT",
    body: JSON.stringify({ media_ids: mediaIds }),
  });
}

/** The moderation queue's print section (ModerationPage). */
export function getPrintReports(): Promise<{ reports: PrintReport[] }> {
  return api(`/prints/moderation/reports?status_filter=open`);
}

export function dismissPrintReport(id: string, resolution: string) {
  return api(`/prints/moderation/reports/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function modRemovePrintFile(id: string, reason: string) {
  return api(`/prints/moderation/files/${id}/remove`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function modRemovePrintComment(id: string, reason: string) {
  return api(`/prints/moderation/comments/${id}/remove`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
