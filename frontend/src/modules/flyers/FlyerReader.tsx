import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Modal, Spinner } from "../../components";
import {
  downloadAttachment,
  printUrl,
  type ViewableAttachment,
} from "../../components/AttachmentViewer";
import { useT } from "../../i18n/LocaleContext";
import { apiBlob } from "../../lib/api";
import type { FlyerView } from "./types";

/**
 * The book-style flyer reader (sheet row 7, 2026-11-15):
 * Ryan's words — "more of a read a book type of preview.
 * the pages should be a sideways scroller on the bottom
 * while the main part is zoom in and out, and all the share
 * options that normal previews have… the user needs to
 * easily be able to read these flyers, not complicated at
 * all." Replaces the browser's embedded PDF viewer for
 * flyers on every flyer surface: one big page up top with
 * zoom, a sideways page scroller along the bottom, and the
 * normal preview actions (full screen, print, download).
 * Pages arrive as JPEGs from GET /flyers/flyers/{id}/pages/
 * {n} through the authenticated blob fetch — nothing is
 * embedded in an iframe.
 */
export function FlyerReader({
  flyer,
  onClose,
}: {
  flyer: FlyerView | null;
  onClose: () => void;
}) {
  if (!flyer) return null;
  return <ReaderBody key={flyer.id} flyer={flyer} onClose={onClose} />;
}

function ReaderBody({
  flyer,
  onClose,
}: {
  flyer: FlyerView;
  onClose: () => void;
}) {
  const t = useT();
  const count = Math.max(1, flyer.page_count);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [urls, setUrls] = useState<Map<number, string>>(new Map());
  const [failed, setFailed] = useState<Set<number>>(new Set());
  const urlsRef = useRef<Map<number, string>>(new Map());
  const loadingRef = useRef<Set<number>>(new Set());
  const stageRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);

  const loadPage = useCallback(
    async (n: number) => {
      if (urlsRef.current.has(n) || loadingRef.current.has(n)) return;
      loadingRef.current.add(n);
      try {
        const blob = await apiBlob(`/flyers/flyers/${flyer.id}/pages/${n}`);
        const url = URL.createObjectURL(blob);
        urlsRef.current.set(n, url);
        setUrls(new Map(urlsRef.current));
        setFailed((prev) => {
          if (!prev.has(n)) return prev;
          const next = new Set(prev);
          next.delete(n);
          return next;
        });
      } catch {
        setFailed((prev) => new Set(prev).add(n));
      } finally {
        loadingRef.current.delete(n);
      }
    },
    [flyer.id],
  );

  // The filmstrip needs every page anyway — load them all;
  // the stage reads the same cache.
  useEffect(() => {
    for (let n = 1; n <= count; n++) void loadPage(n);
  }, [count, loadPage]);

  // Object URLs die with the reader.
  useEffect(() => {
    const cache = urlsRef.current;
    return () => {
      cache.forEach((url) => URL.revokeObjectURL(url));
      cache.clear();
    };
  }, []);

  const goTo = useCallback(
    (n: number) => {
      const next = Math.min(count, Math.max(1, n));
      setPage(next);
      setZoom(1);
      if (stageRef.current) stageRef.current.scrollTop = 0;
    },
    [count],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight") goTo(page + 1);
      if (e.key === "ArrowLeft") goTo(page - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [page, goTo]);

  // Keep the picked page's thumbnail in view in the strip.
  useEffect(() => {
    stripRef.current
      ?.querySelector(`[data-page="${page}"]`)
      ?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [page]);

  const pageOf = (n: number) =>
    t("flyers.pageOf")
      .replace("{page}", String(n))
      .replace("{count}", String(count));
  const currentUrl = urls.get(page);
  const currentFailed = failed.has(page);
  const attachment: ViewableAttachment = {
    key: flyer.id,
    filename: flyer.label || t("flyers.title"),
    kind: "Flyer",
    content_type: "application/pdf",
    size_bytes: 0,
    url: flyer.pdf_url ?? "",
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={flyer.label || t("flyers.title")}
      size="lg"
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => void stageRef.current?.requestFullscreen?.()}
          >
            {t("flyers.fullScreen")}
          </Button>
          {flyer.pdf_url && (
            <Button
              variant="secondary"
              onClick={() => printUrl(flyer.pdf_url as string)}
            >
              {t("flyers.print")}
            </Button>
          )}
          {flyer.pdf_url && (
            <Button
              variant="secondary"
              onClick={() => downloadAttachment(attachment)}
            >
              {t("flyers.download")}
            </Button>
          )}
        </>
      }
    >
      <div className="flyer-reader">
        <div className="flyer-reader-stage" ref={stageRef}>
          {currentUrl ? (
            <img
              className="flyer-reader-page"
              src={currentUrl}
              alt={pageOf(page)}
              style={
                zoom > 1 ? { width: `${zoom * 100}%` } : undefined
              }
            />
          ) : currentFailed ? (
            <div className="flyer-reader-missing">
              <p>{t("flyers.pageLoadError")}</p>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void loadPage(page)}
              >
                {t("flyers.retry")}
              </Button>
            </div>
          ) : (
            <Spinner label="Loading…" />
          )}
        </div>

        <div className="flyer-reader-bar">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1}
            onClick={() => goTo(page - 1)}
          >
            {t("flyers.prevPage")}
          </Button>
          <span className="flyer-reader-count">
            {pageOf(page)}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= count}
            onClick={() => goTo(page + 1)}
          >
            {t("flyers.nextPage")}
          </Button>
          <span className="flyer-reader-zoom">
            <Button
              variant="secondary"
              size="sm"
              disabled={zoom <= 1}
              onClick={() => setZoom((z) => Math.max(1, z / 1.3))}
            >
              {t("flyers.zoomOut")}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={zoom >= 4}
              onClick={() => setZoom((z) => Math.min(4, z * 1.3))}
            >
              {t("flyers.zoomIn")}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={zoom === 1}
              onClick={() => setZoom(1)}
            >
              {t("flyers.resetView")}
            </Button>
          </span>
        </div>

        {count > 1 && (
          <div className="flyer-reader-strip" ref={stripRef}>
            {Array.from({ length: count }, (_, i) => i + 1).map((n) => {
              const url = urls.get(n);
              return (
                <button
                  key={n}
                  type="button"
                  data-page={n}
                  className={
                    "flyer-reader-thumb" + (n === page ? " is-active" : "")
                  }
                  aria-label={pageOf(n)}
                  aria-current={n === page ? "true" : undefined}
                  onClick={() => goTo(n)}
                >
                  {url ? (
                    <img src={url} alt="" draggable={false} />
                  ) : (
                    <span className="flyer-reader-thumbnum">{n}</span>
                  )}
                  <span className="flyer-reader-thumbnum">{n}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}
