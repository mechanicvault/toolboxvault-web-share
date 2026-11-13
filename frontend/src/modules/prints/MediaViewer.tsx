/**
 * The showcase preview viewer (owner order 2026-11-08
 * 23:07): click any tile in a listing's Photos / Video tab
 * and the item opens here, large — then you walk the WHOLE
 * set from inside the window: Previous / Next buttons, the
 * arrow keys, and a swipe on touch. Photos wear the site's
 * photo-viewer treatment (the AttachmentViewer's zoom
 * controls); the video plays in place with its native
 * controls. The set is the listing's media in its stored
 * order — the same order the tab's tiles show.
 */

import { useEffect, useRef, useState } from "react";

import { Button, Modal } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { mediaUrl } from "./api";
import type { PrintMedia } from "./types";

export function durationLabel(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Zoom climbs a fixed ladder — the step lives in a data
 * attribute and the transforms in prints.css, so the viewer
 * adds no inline styles (the ratchet's standing rule). */
const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 5];

export function MediaViewer({
  fileId,
  title,
  media,
  index,
  onClose,
  onIndex,
}: {
  fileId: string;
  /** The listing's own title — the window is titled by the
   * file it shows ("<title> — 1 of 2"), never by the photo's
   * camera filename (Sweep B7); the filename is only the
   * fallback for a caller with no title to give. */
  title?: string;
  media: PrintMedia[];
  /** The open item's position in the set, or null (closed). */
  index: number | null;
  onClose: () => void;
  onIndex: (index: number) => void;
}) {
  const t = useT();
  const [zoomStep, setZoomStep] = useState(0);
  const touchX = useRef<number | null>(null);
  const item = index !== null ? (media[index] ?? null) : null;

  // A new item starts unzoomed (the AttachmentViewer rule).
  useEffect(() => {
    setZoomStep(0);
  }, [item?.id]);

  useEffect(() => {
    if (index === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft" && index !== null && index > 0) onIndex(index - 1);
      if (e.key === "ArrowRight" && index !== null && index < media.length - 1) {
        onIndex(index + 1);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, media.length, onIndex]);

  if (!item || index === null) return null;
  const isVideo = item.kind === "video";

  return (
    <Modal
      open
      onClose={onClose}
      title={
        title
          ? `${title} — ${index + 1} ${t("prints.viewer.of")} ${media.length}`
          : item.filename || t("prints.tab.media")
      }
      size="lg"
      footer={
        <>
          <span className="pr-viewer-count">
            {index + 1} / {media.length}
          </span>
          {!isVideo && (
            <>
              <Button
                variant="secondary"
                disabled={zoomStep === 0}
                onClick={() => setZoomStep((s) => Math.max(0, s - 1))}
              >
                {t("prints.viewer.zoomOut")}
              </Button>
              <Button
                variant="secondary"
                disabled={zoomStep === ZOOM_STEPS.length - 1}
                onClick={() =>
                  setZoomStep((s) => Math.min(ZOOM_STEPS.length - 1, s + 1))
                }
              >
                {t("prints.viewer.zoomIn")}
              </Button>
            </>
          )}
          <Button
            variant="secondary"
            disabled={index === 0}
            onClick={() => onIndex(index - 1)}
          >
            ← {t("prints.viewer.prev")}
          </Button>
          <Button
            variant="secondary"
            disabled={index === media.length - 1}
            onClick={() => onIndex(index + 1)}
          >
            {t("prints.viewer.next")} →
          </Button>
        </>
      }
    >
      <div
        className="pr-viewer-stage"
        onPointerDown={(e) => {
          touchX.current = e.clientX;
        }}
        onPointerUp={(e) => {
          if (touchX.current === null) return;
          const delta = e.clientX - touchX.current;
          touchX.current = null;
          if (Math.abs(delta) < 48) return;
          if (delta < 0 && index < media.length - 1) onIndex(index + 1);
          if (delta > 0 && index > 0) onIndex(index - 1);
        }}
      >
        {isVideo ? (
          <video
            key={item.id}
            className="pr-viewer-video"
            src={mediaUrl(fileId, item.id)}
            controls
            playsInline
            preload="metadata"
          />
        ) : (
          <img
            key={item.id}
            className="pr-viewer-img"
            src={mediaUrl(fileId, item.id)}
            alt={item.filename}
            draggable={false}
            data-zoom={ZOOM_STEPS[zoomStep]}
          />
        )}
      </div>
    </Modal>
  );
}
