import { useState } from "react";

import { Button, fileTypeLabel, formatBytes, type ViewableAttachment } from "../../../components";
import { FileTypeArt, type FileArtKind } from "../../../components/FileTypeArt";
import { useT } from "../../../i18n/LocaleContext";
import { api, ApiError } from "../../../lib/api";
import type { Attachment } from "../types";
import "../itemPage.css";

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

/** Which artwork an attachment wears (owner, 2026-11-04
 *  22:27: "documents should show up as icons of the document
 *  type"; upgraded 2026-11-05 17:05 to full-color FileTypeArt
 *  in place of the single-color glyphs). The kind split is
 *  exactly the attachment allowlist's (storage.py: PDF, Word,
 *  Excel, plain text, images — nothing else can be attached)
 *  crossed with fileTypeLabel's wording: image files get the
 *  picture, spreadsheets the green grid page, PDFs the red
 *  banner page, Word the blue W page, plain text the ruled
 *  sheet, and anything else the neutral document page. Keyed
 *  off the stored content type, extension as the tiebreak for
 *  generic types, exactly like the label. */
export function fileIconKind(contentType: string, filename: string): FileArtKind {
  if (IMAGE_TYPES.includes(contentType)) return "image";
  if (contentType === "application/pdf") return "pdf";
  if (contentType.includes("sheet") || contentType.includes("excel")) return "sheet";
  if (contentType.includes("word")) return "word";
  if (contentType === "text/plain") return "text";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["jpg", "jpeg", "png", "webp", "gif"].includes(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (["xls", "xlsx", "csv"].includes(ext)) return "sheet";
  if (["doc", "docx"].includes(ext)) return "word";
  if (["txt", "md", "log"].includes(ext)) return "text";
  return "doc";
}

function FileTypeGlyph({ attachment }: { attachment: Attachment }) {
  const kind = fileIconKind(attachment.content_type, attachment.filename);
  return (
    <span className="tv-doc-tile-art" data-file-icon={kind} aria-hidden="true">
      <FileTypeArt kind={kind} />
    </span>
  );
}

/**
 * One attachment kind's list on a detail page. Three layouts:
 * the default mixed list (image files as thumbnails, document
 * files as type-chip rows — the loss-report and maintenance
 * surfaces), "photos" (the Photos tab's uniform grid), and
 * "tiles" (the Documents & Receipts sections' icon grid).
 * EVERY entry opens the shared AttachmentViewer — nothing
 * forces a download (owner addition 2026-10-18).
 */
/** One attachment's tap-to-confirm delete (F1-31's pattern,
 *  extracted 2026-11-04 so the Photos tab's big lead photo gets
 *  the exact same control as the list entries — owner order:
 *  every photo deletable, lead included). The wording splits
 *  BY KIND (owner order 2026-11-04 21:44): a photo's control
 *  says "Delete photo"; every other kind keeps "Delete file". */
export function AttachmentDeleteControl({
  attachment,
  deletePath,
  onDeleted,
  variant,
}: {
  /** The viewer's structural shape suffices (key + kind are all
   *  this control reads); full Attachments are assignable. */
  attachment: ViewableAttachment;
  deletePath: string;
  onDeleted?: () => void;
  /** "link" (owner, 2026-11-05 17:05): the document tiles'
   *  below-the-box treatment — the control renders as a plain
   *  accent link under its tile instead of a ghost button.
   *  Same tap-to-confirm, same DELETE path. Default (button)
   *  is every other surface's, unchanged. */
  variant?: "button" | "link";
}) {
  const t = useT();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const isPhoto = attachment.kind === "photo";
  const label = t(isPhoto ? "inventory.attachments.deletePhoto" : "inventory.attachments.deleteFile");

  async function doDelete() {
    setBusy(true);
    setError("");
    try {
      await api(`${deletePath}?key=${encodeURIComponent(attachment.key)}`, {
        method: "DELETE",
      });
      setConfirming(false);
      onDeleted?.();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t(isPhoto ? "inventory.attachments.deletePhotoError" : "inventory.attachments.deleteFileError"),
      );
    } finally {
      setBusy(false);
    }
  }

  if (variant === "link") {
    if (!confirming) {
      return (
        <span className="tv-doc-del">
          <button type="button" className="tv-doc-del-link" onClick={() => setConfirming(true)}>
            {label}
          </button>
          {error && <span className="tv-doc-del-error">{error}</span>}
        </span>
      );
    }
    return (
      <span className="tv-doc-del">
        <span className="tv-doc-del-confirm">
          {t(isPhoto ? "inventory.attachments.deletePhotoConfirm" : "inventory.attachments.deleteFileConfirm")}
        </span>
        <Button size="sm" variant="danger" loading={busy} onClick={() => void doDelete()}>
          {t("common.delete")}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
          {t("common.cancel")}
        </Button>
        {error && <span className="tv-doc-del-error">{error}</span>}
      </span>
    );
  }

  if (!confirming) {
    return (
      <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
        <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
          {label}
        </Button>
        {error && <span style={{ color: "var(--danger)", fontSize: "0.9rem" }}>{error}</span>}
      </span>
    );
  }
  return (
    <span style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center" }}>
      <span style={{ fontSize: "0.85rem" }}>
        {t(isPhoto ? "inventory.attachments.deletePhotoConfirm" : "inventory.attachments.deleteFileConfirm")}
      </span>
      <Button size="sm" variant="danger" loading={busy} onClick={() => void doDelete()}>
        {t("common.delete")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
        {t("common.cancel")}
      </Button>
      {error && <span style={{ color: "var(--danger)", fontSize: "0.9rem" }}>{error}</span>}
    </span>
  );
}

export function AttachmentList({
  items,
  emailPath,
  onView,
  deletePath,
  onDeleted,
  layout,
}: {
  items: Attachment[];
  emailPath: string;
  onView: (attachment: Attachment, emailPath: string) => void;
  /** F1-31: when set (the item's attachments endpoint, e.g.
   *  /inventory/{id}/attachments), every entry gains a Delete
   *  action — inline confirm, then DELETE ?key=… (row + object
   *  removed server-side) and onDeleted refreshes the parent. */
  deletePath?: string;
  onDeleted?: () => void;
  /** "photos" (owner correction 2026-11-04 22:19): the item
   *  Photos tab renders as ONE uniform grid — every photo the
   *  same size, two abreast, each tile about half the width the
   *  old full-width lead photo rendered at (measured 1248px →
   *  ~620px tiles at desktop) — and photo deletes live only
   *  inside the viewer, so Photos callers pass no deletePath.
   *  "tiles" (owner, 2026-11-04 22:27): the Documents &
   *  Receipts tab's file sections render as an ICON GRID — each
   *  file a uniform tile, an icon of its document type with the
   *  file's name below it, 4–6 across on desktop wrapping to
   *  new rows (fewer across on phone). Same open-in-viewer
   *  click; documents get NO delete inside the viewer (that
   *  model is photos-only). Redone 2026-11-05 17:05: the icon
   *  is now full-color FileTypeArt, and "Delete file" moved
   *  OUT of the tile to a link below the box. */
  layout?: "photos" | "tiles";
}) {
  const deleteControls = (a: Attachment, variant?: "button" | "link") =>
    !deletePath ? null : (
      <AttachmentDeleteControl
        attachment={a}
        deletePath={deletePath}
        onDeleted={onDeleted}
        variant={variant}
      />
    );
  if (layout === "tiles") {
    return (
      <div className="tv-doc-tiles">
        {items.map((a) => (
          <div key={a.key} className="tv-doc-tile-cell">
            <div className="tv-doc-tile tv-hoverable">
              <button
                type="button"
                className="tv-doc-tile-btn"
                onClick={() => onView(a, emailPath)}
                title={a.filename}
              >
                <FileTypeGlyph attachment={a} />
                <span className="tv-doc-tile-name">{a.filename}</span>
                <span className="tv-doc-tile-meta">
                  {formatBytes(a.size_bytes)}
                  {a.origin === "manual" &&
                    ` · User manual — saved from ${a.source_name || "the web"}${a.fetched_at ? ` on ${new Date(a.fetched_at).toLocaleDateString()}` : ""}`}
                </span>
              </button>
            </div>
            {deletePath && (
              <div className="tv-doc-tile-del">{deleteControls(a, "link")}</div>
            )}
          </div>
        ))}
      </div>
    );
  }
  const images = items.filter((a) => IMAGE_TYPES.includes(a.content_type));
  const files = items.filter((a) => !IMAGE_TYPES.includes(a.content_type));
  return (
    <div style={{ display: "grid", gap: "0.7rem" }}>
      {images.length > 0 && (
        <div
          style={{
            display: "grid",
            gap: "var(--space-3)",
            gridTemplateColumns:
              layout === "photos"
                ? "repeat(2, minmax(0, 1fr))"
                : "repeat(auto-fill, minmax(min(100%, 140px), 1fr))",
          }}
        >
          {images.map((a) => (
            <div key={a.key} style={{ display: "grid", gap: "0.3rem" }}>
            <button
              type="button"
              onClick={() => onView(a, emailPath)}
              title={a.filename}
              style={{
                padding: 0,
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                overflow: "hidden",
                background: "var(--surface)",
                cursor: "pointer",
              }}
            >
              <img
                src={a.url}
                alt={a.filename}
                style={{
                  display: "block",
                  width: "100%",
                  aspectRatio: layout === "photos" ? "4 / 3" : "1",
                  objectFit: "cover",
                }}
              />
            </button>
            {deleteControls(a)}
            </div>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "0.4rem" }}>
          {files.map((a) => (
            <li key={a.key}>
              <button
                type="button"
                onClick={() => onView(a, emailPath)}
                style={{
                  display: "flex",
                  gap: "0.6rem",
                  alignItems: "center",
                  width: "100%",
                  textAlign: "left",
                  background: "var(--surface)",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.5rem 0.7rem",
                  cursor: "pointer",
                  color: "var(--text)",
                }}
              >
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: "0.75rem",
                    letterSpacing: "0.04em",
                    border: "1px solid var(--edge-strong)",
                    borderRadius: "var(--radius)",
                    padding: "0.15rem 0.45rem",
                    whiteSpace: "nowrap",
                  }}
                >
                  {fileTypeLabel(a.content_type, a.filename)}
                </span>
                <span style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{a.filename}</span>
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {formatBytes(a.size_bytes)}
                </span>
                {a.origin === "manual" && (
                  <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    User manual — saved from {a.source_name || "the web"}
                    {a.fetched_at
                      ? ` on ${new Date(a.fetched_at).toLocaleDateString()}`
                      : ""}
                  </span>
                )}
              </button>
              {deleteControls(a)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
