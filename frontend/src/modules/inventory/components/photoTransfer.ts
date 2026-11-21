import { api } from "../../../lib/api";

/**
 * Attachment transfer rules (item structure package; owner
 * clarification 2026-10-18): three kinds — photo | document |
 * receipt. PHOTOS are image-only. DOCUMENTS and RECEIPTS accept
 * images (a photo of a receipt / calibration card) AND real document
 * files: PDF, Word (.doc/.docx), spreadsheets (.xls/.xlsx), plain
 * text. Validation is PER KIND, mirrored by the backend's storage
 * allowlist; size caps: photos keep the 10 MB limit, documents and
 * receipts get 25 MB. MANUALS joined as a fourth kind (owner
 * ruling 2026-11-03) with the document rules — same types, same
 * 25 MB cap.
 */

export type AttachmentKind = "photo" | "document" | "receipt" | "manual";

export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const DOCUMENT_TYPES = [
  ...PHOTO_TYPES,
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/plain",
];

export const PHOTO_MAX_BYTES = 10 * 1024 * 1024;
export const DOCUMENT_MAX_BYTES = 25 * 1024 * 1024;

/** Extension → canonical MIME, for browsers that hand us a file with
 *  an empty/odd `type` (common for .doc/.xls from some pickers). The
 *  canonical type is what goes to the backend's allowlist. */
const EXTENSION_TYPES: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  pdf: "application/pdf",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xls: "application/vnd.ms-excel",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  txt: "text/plain",
};

export function fileContentType(file: File): string {
  if (file.type) return file.type;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TYPES[ext] ?? "";
}

export function typesForKind(kind: AttachmentKind): string[] {
  return kind === "photo" ? PHOTO_TYPES : DOCUMENT_TYPES;
}

export function maxBytesForKind(kind: AttachmentKind): number {
  return kind === "photo" ? PHOTO_MAX_BYTES : DOCUMENT_MAX_BYTES;
}

/** `accept` attribute for the file input, per kind. */
export function acceptForKind(kind: AttachmentKind): string {
  return kind === "photo"
    ? PHOTO_TYPES.join(",")
    : [...DOCUMENT_TYPES, ".doc", ".docx", ".xls", ".xlsx", ".txt"].join(",");
}

export function isImageContentType(contentType: string): boolean {
  return PHOTO_TYPES.includes(contentType);
}

/** Why a picked file can't ride as `kind`, or null when acceptable. */
export function attachmentFileError(kind: AttachmentKind, file: File): string | null {
  const type = fileContentType(file);
  if (!typesForKind(kind).includes(type)) {
    if (kind === "photo") {
      return "Photos are JPG, PNG, or WebP only — documents go in Documents or Receipts.";
    }
    if (kind === "manual") {
      return "Manuals take PDF, Word, Excel, text, or image files.";
    }
    return "Documents and receipts take PDF, Word, Excel, text, or image files.";
  }
  const max = maxBytesForKind(kind);
  if (file.size > max) return `Over the ${Math.round(max / (1024 * 1024))} MB limit.`;
  return null;
}

/** Back-compat wrapper (photo flows predating the kinds). */
export function photoFileError(file: File): string | null {
  return attachmentFileError("photo", file);
}

interface UploadUrlResponse {
  upload_url: string;
  key: string;
  expires_in: number;
}

/** PUT a file with progress events. fetch can't report upload progress, so XHR. */
function putWithProgress(url: string, file: File, contentType: string, onProgress: (pct: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload failed (HTTP ${xhr.status})`));
    xhr.onerror = () => reject(new Error("Upload failed — check your connection."));
    xhr.send(file);
  });
}

/**
 * Upload one file against an EXISTING record: presigned URL → direct
 * PUT → link as an attachment. `basePath` is the item's API path
 * (`/inventory/{id}`, `/inventory/batteries/{id}`,
 * `/inventory/pieces/{id}`). Throws on failure — the caller decides
 * how to surface it. Shared by the edit-mode uploader and the add-form
 * staged uploads, so a file lands identically from either flow.
 */
export async function uploadAttachmentFile(
  basePath: string,
  kind: AttachmentKind,
  file: File,
  onProgress?: (pct: number) => void,
  /** Extra fields merged into the attach call — e.g.
   *  { loss_report_id } ties the file to a lost/stolen report. */
  attachExtra?: Record<string, unknown>,
): Promise<void> {
  const contentType = fileContentType(file);
  const { upload_url, key } = await api<UploadUrlResponse>(
    `${basePath}/upload-url`,
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: contentType,
        kind,
        size_bytes: file.size,
      }),
    },
  );
  await putWithProgress(upload_url, file, contentType, onProgress ?? (() => {}));
  await api(`${basePath}/attachments`, {
    method: "POST",
    body: JSON.stringify({ key, filename: file.name, ...attachExtra }),
  });
}

/** Back-compat wrapper for photo-only callers. */
export async function uploadPhotoFile(
  basePath: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<void> {
  return uploadAttachmentFile(basePath, "photo", file, onProgress);
}
