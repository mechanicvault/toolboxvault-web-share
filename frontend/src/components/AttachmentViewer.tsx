import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../lib/api";
import { Alert } from "./Alert";
import { Button, HrefButton } from "./Button";
import { FormField } from "./FormField";
import { Modal } from "./Modal";
import { TextInput } from "./TextInput";

/**
 * In-place attachment viewer (owner addition 2026-10-18): clicking
 * any attachment — photo, document, receipt — opens this instead of
 * forcing a download.
 *
 * - Images: zoomable lightbox (scroll/pinch zoom, drag pan,
 *   double-click reset) with a Print action.
 * - PDFs: the browser's native embedded viewer (its own zoom/print),
 *   plus an open-full-screen action.
 * - Everything else (Word/Excel/text) cannot render natively: a
 *   clean file card with Open/Download — no third-party viewer
 *   iframes — and honest copy that printing means download first.
 *
 * "Email this file" posts to the item's email endpoint (`emailPath`,
 * e.g. /inventory/{id}/attachments/email): owner-scoped server-side,
 * rate-limited, sent through the email seam with the file attached.
 */
export interface ViewableAttachment {
  key: string;
  filename: string;
  kind: string;
  content_type: string;
  size_bytes: number;
  url: string;
}

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export function fileTypeLabel(contentType: string, filename: string): string {
  if (contentType === "application/pdf") return "PDF";
  if (contentType.includes("word")) return "Word document";
  if (contentType.includes("sheet") || contentType.includes("excel")) return "Spreadsheet";
  if (contentType === "text/plain") return "Text file";
  if (IMAGE_TYPES.includes(contentType)) return "Image";
  const ext = filename.split(".").pop();
  return ext ? `${ext.toUpperCase()} file` : "File";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function printUrl(url: string) {
  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  iframe.src = url;
  iframe.onload = () => {
    try {
      iframe.contentWindow?.focus();
      iframe.contentWindow?.print();
    } catch {
      window.open(url, "_blank", "noreferrer");
    }
    window.setTimeout(() => iframe.remove(), 60_000);
  };
  document.body.appendChild(iframe);
}

function downloadAttachment(attachment: ViewableAttachment) {
  void fetch(attachment.url)
    .then((r) => r.blob())
    .then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = attachment.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
    })
    .catch(() => window.open(attachment.url, "_blank", "noreferrer"));
}

export function AttachmentViewer({
  attachment,
  emailPath,
  deleteControl,
  onClose,
}: {
  attachment: ViewableAttachment | null;
  /** POST endpoint for "Email this file" (owner-scoped). */
  emailPath?: string;
  /**
   * Optional extra footer control (owner correction 2026-11-04
   * 22:19): item pages pass their photos' tap-to-confirm Delete
   * photo control here — a photo is deleted ONLY from inside this
   * viewer, never from a tab surface. Callers that don't pass it
   * (documents, claims, schedules…) render the viewer unchanged.
   */
  deleteControl?: ReactNode;
  onClose: () => void;
}) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [emailOpen, setEmailOpen] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailNote, setEmailNote] = useState<{ ok: boolean; text: string } | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{ distance: number; scale: number } | null>(null);
  const dragStart = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  // Reset the view whenever a different file opens.
  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setEmailOpen(false);
    setEmailNote(null);
    setRecipient("");
  }, [attachment?.key]);

  // Wheel zoom needs a non-passive listener to preventDefault.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el || !attachment || !IMAGE_TYPES.includes(attachment.content_type)) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setScale((s) => Math.min(5, Math.max(1, s * (e.deltaY < 0 ? 1.15 : 0.87))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [attachment]);

  if (!attachment) return null;
  const isImage = IMAGE_TYPES.includes(attachment.content_type);
  const isPdf = attachment.content_type === "application/pdf";

  function onPointerDown(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinchStart.current = {
        distance: Math.hypot(a.x - b.x, a.y - b.y),
        scale,
      };
      dragStart.current = null;
    } else if (pointers.current.size === 1) {
      dragStart.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
    }
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinchStart.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      const next = (pinchStart.current.scale * distance) / Math.max(1, pinchStart.current.distance);
      setScale(Math.min(5, Math.max(1, next)));
    } else if (dragStart.current && scale > 1) {
      setOffset({
        x: dragStart.current.ox + (e.clientX - dragStart.current.x),
        y: dragStart.current.oy + (e.clientY - dragStart.current.y),
      });
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinchStart.current = null;
    if (pointers.current.size === 0) dragStart.current = null;
  }

  async function sendEmail() {
    if (!emailPath || !attachment) return;
    setEmailBusy(true);
    setEmailNote(null);
    try {
      await api(emailPath, {
        method: "POST",
        body: JSON.stringify({ key: attachment.key, recipient: recipient.trim() }),
      });
      setEmailNote({ ok: true, text: `Sent to ${recipient.trim()}.` });
      setRecipient("");
    } catch (err) {
      setEmailNote({
        ok: false,
        text: err instanceof ApiError ? err.message : "Couldn't send the email.",
      });
    } finally {
      setEmailBusy(false);
    }
  }

  return (
    <Modal
      open={attachment !== null}
      onClose={onClose}
      title={attachment.filename}
      size="lg"
      footer={
        <>
          {deleteControl}
          {isImage && (
            <>
              <Button
                variant="secondary"
                onClick={() => setScale((s) => Math.max(1, s / 1.3))}
              >
                Zoom out
              </Button>
              <Button
                variant="secondary"
                onClick={() => setScale((s) => Math.min(5, s * 1.3))}
              >
                Zoom in
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setScale(1);
                  setOffset({ x: 0, y: 0 });
                }}
              >
                Reset view
              </Button>
            </>
          )}
          {isPdf && (
            <Button
              variant="secondary"
              onClick={() => void frameRef.current?.requestFullscreen?.()}
            >
              Full screen
            </Button>
          )}
          <Button variant="secondary" onClick={() => printUrl(attachment.url)}>
            Print
          </Button>
          <Button variant="secondary" onClick={() => downloadAttachment(attachment)}>
            Download
          </Button>
          {emailPath && (
            <Button onClick={() => setEmailOpen((v) => !v)}>Email this file</Button>
          )}
        </>
      }
    >
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {isImage && (
          <div
            ref={viewportRef}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDoubleClick={() => {
              if (scale > 1) {
                setScale(1);
                setOffset({ x: 0, y: 0 });
              } else {
                setScale(2);
              }
            }}
            style={{
              overflow: "hidden",
              touchAction: "none",
              cursor: scale > 1 ? "grab" : "zoom-in",
              background: "var(--surface)",
              border: "1px solid var(--edge)",
              borderRadius: "var(--radius)",
              maxHeight: "70vh",
              display: "grid",
              placeItems: "center",
            }}
          >
            <img
              src={attachment.url}
              alt={attachment.filename}
              draggable={false}
              style={{
                maxWidth: "100%",
                maxHeight: "70vh",
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
                userSelect: "none",
              }}
            />
          </div>
        )}
        {isPdf && (
          <div ref={frameRef} style={{ background: "var(--surface)" }}>
            <iframe
              title={attachment.filename}
              src={attachment.url}
              style={{
                width: "100%",
                height: "70vh",
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                background: "var(--surface)",
              }}
            />
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 0 }}>
              The built-in PDF viewer above has its own zoom and print controls.
            </p>
          </div>
        )}
        {!isImage && !isPdf && (
          <div
            style={{
              border: "1px solid var(--edge)",
              borderRadius: "var(--radius)",
              background: "var(--surface)",
              padding: "1.25rem",
              display: "grid",
              gap: "0.5rem",
              justifyItems: "start",
            }}
          >
            <span
              style={{
                fontWeight: 700,
                letterSpacing: "0.04em",
                border: "1px solid var(--edge-strong)",
                borderRadius: "var(--radius)",
                padding: "0.3rem 0.6rem",
              }}
            >
              {fileTypeLabel(attachment.content_type, attachment.filename)}
            </span>
            <p style={{ margin: 0, fontWeight: 600 }}>{attachment.filename}</p>
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
              {formatBytes(attachment.size_bytes)} · {attachment.kind}
            </p>
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
              This file type can't be previewed in the browser. Open it or
              download it to view it — to print it, download it first and
              print from the app that opens it.
            </p>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <HrefButton href={attachment.url} target="_blank" rel="noreferrer" variant="secondary">Open</HrefButton>
              <Button variant="secondary" onClick={() => downloadAttachment(attachment)}>
                Download
              </Button>
            </div>
          </div>
        )}
        {emailOpen && emailPath && (
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <FormField label="Email this file to" htmlFor="viewer-email-to">
              <TextInput
                id="viewer-email-to"
                type="email"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="name@example.com"
              />
            </FormField>
            {emailNote && (
              <Alert tone={emailNote.ok ? "success" : "danger"}>{emailNote.text}</Alert>
            )}
            <div>
              <Button
                onClick={() => void sendEmail()}
                loading={emailBusy}
                disabled={!recipient.trim()}
              >
                Send file
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
