import { useState } from "react";
import { FileUpload, formatBytes, type UploadFileItem } from "../../../components";
import { ApiError } from "../../../lib/api";
import type { Attachment } from "../types";
import {
  acceptForKind,
  attachmentFileError,
  uploadAttachmentFile,
  type AttachmentKind,
} from "./photoTransfer";

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

/** The record's EXISTING files of this kind, shown as themselves
 *  above the dropzone (deep audit F1-07): the edit form used to
 *  render only an empty dropzone for a record that verifiably had
 *  files — the owner read that as "my photo is gone". Images show
 *  as thumbnails; other files as named rows. Display only: the
 *  product has no attachment-delete surface anywhere, so removal
 *  is not offered here either. */
function ExistingAttachments({ items }: { items: Attachment[] }) {
  const images = items.filter((a) => IMAGE_TYPES.includes(a.content_type));
  const files = items.filter((a) => !IMAGE_TYPES.includes(a.content_type));
  return (
    <div style={{ display: "grid", gap: "0.6rem", marginBottom: "0.7rem" }}>
      {images.length > 0 && (
        <div
          style={{
            display: "grid",
            gap: "var(--space-3)",
            gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 120px), 1fr))",
          }}
        >
          {images.map((a) => (
            <figure key={a.key} style={{ margin: 0, display: "grid", gap: "0.3rem" }}>
              <img
                src={a.url}
                alt={a.filename}
                title={a.filename}
                style={{
                  display: "block",
                  width: "100%",
                  aspectRatio: "1",
                  objectFit: "cover",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  background: "var(--surface)",
                }}
              />
              <figcaption
                style={{
                  fontSize: "0.75rem",
                  color: "var(--text-muted)",
                  overflowWrap: "anywhere",
                }}
              >
                {a.filename}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "0.4rem" }}>
          {files.map((a) => (
            <li
              key={a.key}
              style={{
                display: "flex",
                gap: "0.6rem",
                alignItems: "center",
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                padding: "0.5rem 0.7rem",
                background: "var(--surface)",
              }}
            >
              <span style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{a.filename}</span>
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                {formatBytes(a.size_bytes)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface FileStatus {
  name: string;
  state: "queued" | "uploading" | "done" | "error";
  progress: number;
  message: string;
}

const KIND_COPY: Record<AttachmentKind, { label: string; hint: string }> = {
  photo: {
    label: "Drop photos here, or",
    hint: "JPG, PNG, or WebP · up to 10 MB each",
  },
  document: {
    label: "Drop documents here, or",
    hint: "PDF, Word, Excel, text, or a photo of the document · up to 25 MB each",
  },
  receipt: {
    label: "Drop receipts here, or",
    hint: "PDF, Word, Excel, text, or a photo of the receipt · up to 25 MB each",
  },
  manual: {
    label: "Drop manuals here, or",
    hint: "PDF, Word, Excel, text, or a photo of the manual · up to 25 MB each",
  },
};

/** File picker → presigned URL → direct PUT → link, for one
 *  attachment KIND. One file at a time. Rendering is the shared
 *  FileUpload component; this owns the transfer. `basePath` is the
 *  item's API path — tools, batteries and set pieces share this
 *  uploader. For records that don't exist yet, the add forms stage
 *  files with StagedFilePicker and run the same transfer after
 *  creating. */
export function PhotoUploader({
  toolId,
  basePath,
  kind = "photo",
  onUploaded,
  existing,
}: {
  toolId: string;
  basePath?: string;
  kind?: AttachmentKind;
  onUploaded: () => void;
  /** The record's already-saved attachments of this kind, shown
   *  above the dropzone (see ExistingAttachments). */
  existing?: Attachment[];
}) {
  const itemBase = basePath ?? `/inventory/${toolId}`;
  const [files, setFiles] = useState<FileStatus[]>([]);
  const [busy, setBusy] = useState(false);

  function setFile(i: number, patch: Partial<FileStatus>) {
    setFiles((prev) => prev.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }

  async function uploadOne(file: File, i: number) {
    try {
      setFile(i, { state: "uploading", message: "Uploading…", progress: 0 });
      await uploadAttachmentFile(itemBase, kind, file, (progress) =>
        setFile(i, { progress }),
      );
      setFile(i, { state: "done", message: "Done", progress: 100 });
      onUploaded();
    } catch (err) {
      setFile(i, {
        state: "error",
        message: err instanceof ApiError ? err.message : "Upload failed.",
      });
    }
  }

  async function onPick(picked: File[]) {
    if (picked.length === 0) return;
    const next: FileStatus[] = picked.map((f) => {
      const problem = attachmentFileError(kind, f);
      return problem
        ? { name: f.name, state: "error", progress: 0, message: problem }
        : { name: f.name, state: "queued", progress: 0, message: "Waiting…" };
    });
    setFiles(next);
    setBusy(true);
    for (let i = 0; i < picked.length; i++) {
      if (next[i].state === "error") continue;
      await uploadOne(picked[i], i);
    }
    setBusy(false);
  }

  const items: UploadFileItem[] = files.map((f, i) => ({
    id: `${f.name}-${i}`,
    name: f.name,
    status:
      f.state === "done"
        ? "done"
        : f.state === "error"
          ? "error"
          : f.state === "queued"
            ? "queued"
            : "uploading",
    progress: f.progress,
    message: f.state === "error" ? f.message : undefined,
  }));

  const copy = KIND_COPY[kind];
  return (
    <div>
      {existing && existing.length > 0 && (
        <ExistingAttachments items={existing} />
      )}
      <FileUpload
        onFiles={(picked) => void onPick(picked)}
        accept={acceptForKind(kind)}
        multiple
        disabled={busy}
        files={items}
        label={copy.label}
        hint={copy.hint}
      />
    </div>
  );
}
