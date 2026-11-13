import { useState } from "react";
import { FileUpload } from "../../../components";
import { ApiError } from "../../../lib/api";
import {
  acceptForKind,
  attachmentFileError,
  isImageContentType,
  uploadAttachmentFile,
  type AttachmentKind,
} from "./photoTransfer";

/**
 * A file picked in an ADD form, before the record exists. The file is
 * held locally (images with a live preview); on Save the form creates
 * the record, then uploads each staged file against the new id (see
 * uploadStagedFiles). Status fields are driven by that upload pass.
 */
export interface StagedFile {
  id: string;
  file: File;
  previewUrl: string | null;
  status: "staged" | "uploading" | "done" | "error";
  progress: number;
  error?: string;
}

/** Back-compat alias: photos were the original staged kind. */

let stagedSeq = 0;

const KIND_COPY: Record<AttachmentKind, { label: string; hint: string; noun: string }> = {
  photo: {
    label: "Drop photos here, or",
    hint: "JPG, PNG, or WebP · up to 10 MB each — they upload when you save",
    noun: "photo",
  },
  document: {
    label: "Drop documents here, or",
    hint: "PDF, Word, Excel, text, or a photo of the document · up to 25 MB each — they upload when you save",
    noun: "document",
  },
  receipt: {
    label: "Drop receipts here, or",
    hint: "PDF, Word, Excel, text, or a photo of the receipt · up to 25 MB each — they upload when you save",
    noun: "receipt",
  },
  manual: {
    label: "Drop manuals here, or",
    hint: "PDF, Word, Excel, text, or a photo of the manual · up to 25 MB each — they upload when you save",
    noun: "manual",
  },
};

/**
 * File picker for records that don't exist yet (owner directive
 * 2026-10-18: files are picked WHILE filling in the form — never
 * "save first, come back later"). One picker per attachment KIND —
 * photos, documents, receipts (owner clarification: documents and
 * receipts accept document files AND photos of documents, validated
 * per kind on the spot, exactly like the edit-mode uploader).
 */
export function StagedFilePicker({
  kind,
  files,
  onChange,
  disabled,
}: {
  kind: AttachmentKind;
  files: StagedFile[];
  onChange: (next: StagedFile[]) => void;
  disabled?: boolean;
}) {
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);
  const copy = KIND_COPY[kind];

  function onPick(picked: File[]) {
    const bad: { name: string; reason: string }[] = [];
    const good: StagedFile[] = [];
    for (const file of picked) {
      const problem = attachmentFileError(kind, file);
      if (problem) {
        bad.push({ name: file.name, reason: problem });
      } else {
        good.push({
          id: `staged-${++stagedSeq}`,
          file,
          previewUrl: file.type.startsWith("image/")
            ? URL.createObjectURL(file)
            : null,
          status: "staged",
          progress: 0,
        });
      }
    }
    setRejected(bad);
    if (good.length > 0) onChange([...files, ...good]);
  }

  function remove(id: string) {
    const target = files.find((p) => p.id === id);
    if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
    onChange(files.filter((p) => p.id !== id));
  }

  return (
    <div>
      <FileUpload
        onFiles={onPick}
        accept={acceptForKind(kind)}
        multiple
        disabled={disabled}
        label={copy.label}
        hint={copy.hint}
      />
      {rejected.length > 0 && (
        <ul style={{ margin: "var(--space-3) 0 0", paddingLeft: "1.25rem", display: "grid", gap: "0.25rem" }}>
          {rejected.map((r) => (
            <li key={r.name} style={{ color: "var(--danger)", fontSize: "0.85rem" }}>
              {r.name} — {r.reason}
            </li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(104px, 1fr))",
            gap: "var(--space-3)",
            marginTop: "var(--space-3)",
          }}
        >
          {files.map((entry) => (
            <figure key={entry.id} style={{ margin: 0, display: "grid", gap: "0.35rem" }}>
              <div
                style={{
                  position: "relative",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  overflow: "hidden",
                  background: "var(--surface)",
                }}
              >
                {entry.previewUrl ? (
                  <img
                    src={entry.previewUrl}
                    alt={entry.file.name}
                    style={{
                      display: "block",
                      width: "100%",
                      aspectRatio: "1",
                      objectFit: "cover",
                      opacity:
                        entry.status === "error"
                          ? 0.45
                          : entry.status === "uploading"
                            ? 0.7
                            : 1,
                    }}
                  />
                ) : (
                  <div
                    style={{
                      display: "grid",
                      placeItems: "center",
                      width: "100%",
                      aspectRatio: "1",
                      color: "var(--text-muted)",
                      fontWeight: 700,
                      fontSize: "1.1rem",
                      letterSpacing: "0.04em",
                    }}
                  >
                    {(entry.file.name.split(".").pop() ?? "FILE").toUpperCase().slice(0, 4)}
                  </div>
                )}
                {!disabled && entry.status !== "done" && (
                  <button
                    type="button"
                    aria-label={`Remove ${entry.file.name}`}
                    onClick={() => remove(entry.id)}
                    style={{
                      position: "absolute",
                      top: "0.3rem",
                      right: "0.3rem",
                      width: "1.5rem",
                      height: "1.5rem",
                      borderRadius: "50%",
                      border: "1px solid var(--edge-strong)",
                      background: "var(--panel)",
                      color: "var(--danger)",
                      cursor: "pointer",
                      lineHeight: 1,
                      fontSize: "0.9rem",
                      padding: 0,
                    }}
                  >
                    −
                  </button>
                )}
                {entry.status === "uploading" && (
                  <span
                    style={{
                      position: "absolute",
                      left: "0.4rem",
                      bottom: "0.35rem",
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: "var(--text)",
                      background: "var(--panel)",
                      border: "1px solid var(--edge)",
                      borderRadius: "var(--radius)",
                      padding: "0.05rem 0.4rem",
                    }}
                  >
                    {entry.progress}%
                  </span>
                )}
                {entry.status === "done" && (
                  <span
                    style={{
                      position: "absolute",
                      left: "0.4rem",
                      bottom: "0.35rem",
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: "var(--success)",
                      background: "var(--panel)",
                      border: "1px solid var(--edge)",
                      borderRadius: "var(--radius)",
                      padding: "0.05rem 0.4rem",
                    }}
                  >
                    ✓ Uploaded
                  </span>
                )}
              </div>
              <figcaption
                style={{
                  fontSize: "0.78rem",
                  color: entry.status === "error" ? "var(--danger)" : "var(--text-muted)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={entry.file.name}
              >
                {entry.status === "error"
                  ? `${entry.file.name} — ${entry.error ?? "Upload failed."}`
                  : entry.file.name}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

/** Back-compat photo picker (the original staged component). */
export function StagedPhotoPicker({
  photos,
  onChange,
  disabled,
}: {
  photos: StagedFile[];
  onChange: (next: StagedFile[]) => void;
  disabled?: boolean;
}) {
  return (
    <StagedFilePicker kind="photo" files={photos} onChange={onChange} disabled={disabled} />
  );
}

/**
 * Upload every staged file of one kind against a freshly created
 * record, one at a time, reporting progress through `onChange`.
 * Never throws: files that fail come back in `failed` with their
 * error recorded (and stay visible in the picker in the error
 * state), so the caller can land the user on the new record with a
 * clear warning instead of losing the file silently.
 */
export async function uploadStagedFiles(
  basePath: string,
  kind: AttachmentKind,
  files: StagedFile[],
  onChange: (next: StagedFile[]) => void,
): Promise<{ failed: StagedFile[] }> {
  const failed: StagedFile[] = [];
  let current = files;
  const patch = (id: string, update: Partial<StagedFile>) => {
    current = current.map((p) => (p.id === id ? { ...p, ...update } : p));
    onChange(current);
  };
  for (const entry of files) {
    patch(entry.id, { status: "uploading", progress: 0, error: undefined });
    try {
      await uploadAttachmentFile(basePath, kind, entry.file, (progress) =>
        patch(entry.id, { progress }),
      );
      patch(entry.id, { status: "done", progress: 100 });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Upload failed.";
      patch(entry.id, { status: "error", error: message });
      failed.push({ ...entry, status: "error", error: message });
    }
  }
  return { failed };
}

/** The warning toast copy shared by the add forms when a created
 *  record's files only partially uploaded. */
export function fileFailureToast(
  noun: "tool" | "battery",
  what: string,
  failedNames: string[],
): { title: string; message: string } {
  const count = failedNames.length;
  return {
    title: `${noun === "tool" ? "Tool" : "Battery"} saved — ${count} ${what}${count === 1 ? "" : "s"} didn't upload`,
    message:
      `${failedNames.join(", ")} couldn't be uploaded. You're on the ${noun}'s page now — ` +
      `the attachments sections are right there to add ${count === 1 ? "it" : "them"} again. Nothing else was lost.`,
  };
}

/** Back-compat photo toast. */

export { isImageContentType };
