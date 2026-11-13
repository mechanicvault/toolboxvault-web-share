import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { stagePhoto } from "./api";
import type { ScanPage } from "./types";

interface EditorPage {
  key: string;
  previewUrl: string;
  width: number;
  height: number;
  corners: number[][];
  detected: boolean;
}

/**
 * The photo-scan intake (owner order, 2026-11-05 #10, route 3):
 * the user adds page photos of a paper flyer; the server finds
 * the paper's edges and answers a guessed outline per page, and
 * the user can DRAG any corner when the guess is off. What
 * leaves this editor is each staged photo + its final corners —
 * the server warps, cleans, and assembles the pages into one
 * PDF when the flyer posts.
 */
export function ScanEditor({
  onChange,
}: {
  onChange: (pages: ScanPage[]) => void;
}) {
  const t = useT();
  const [pages, setPages] = useState<EditorPage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    onChange(pages.map((p) => ({ key: p.key, corners: p.corners })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages]);

  async function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const added: EditorPage[] = [];
      for (const file of Array.from(files)) {
        const detected = await stagePhoto(file);
        added.push({
          key: detected.key,
          previewUrl: URL.createObjectURL(file),
          width: detected.width,
          height: detected.height,
          corners: detected.corners,
          detected: detected.detected,
        });
      }
      setPages((prev) => [...prev, ...added]);
    } catch {
      setError(t("home.widgetLoadFailed"));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function setCorners(index: number, corners: number[][]) {
    setPages((prev) =>
      prev.map((p, i) => (i === index ? { ...p, corners } : p)),
    );
  }

  function removePage(index: number) {
    setPages((prev) => prev.filter((_, i) => i !== index));
  }

  return (
    <div className="flyer-scan">
      <p className="flyer-scan-help">{t("flyers.scanHelp")}</p>
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="flyer-scan-pages">
        {pages.map((page, i) => (
          <div key={page.key} className="flyer-scan-page">
            <ScanPageEditor
              page={page}
              onCorners={(corners) => setCorners(i, corners)}
            />
            {!page.detected ? (
              <p className="flyer-scan-warn">{t("flyers.scanNotFound")}</p>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removePage(i)}
            >
              {t("flyers.removePage")}
            </Button>
          </div>
        ))}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        className="flyer-file-input"
        aria-label={t("flyers.addPhotos")}
        onChange={(e) => void addFiles(e.target.files)}
      />
      <Button
        type="button"
        variant="secondary"
        disabled={busy}
        onClick={() => fileRef.current?.click()}
      >
        {busy ? "…" : t("flyers.addPhotos")}
      </Button>
    </div>
  );
}

/** One page photo with its paper outline: an SVG quad the user
 *  drags by the corners. Coordinates ride as SVG attributes
 *  (viewBox = the photo's own pixels), never inline styles. */
function ScanPageEditor({
  page,
  onCorners,
}: {
  page: EditorPage;
  onCorners: (corners: number[][]) => void;
}) {
  const t = useT();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<number | null>(null);
  const { width, height } = page;
  const pts = page.corners.map(([x, y]) => `${x * width},${y * height}`).join(" ");
  const handleR = Math.max(width, height) * 0.022;

  function toNormalized(e: React.PointerEvent): [number, number] {
    const svg = svgRef.current;
    if (!svg) return [0, 0];
    const rect = svg.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return [
      Math.min(0.99, Math.max(0.01, x)),
      Math.min(0.99, Math.max(0.01, y)),
    ];
  }

  return (
    <svg
      ref={svgRef}
      className="flyer-scan-svg"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={t("flyers.scanOutline")}
      onPointerMove={(e) => {
        const idx = dragRef.current;
        if (idx === null) return;
        const [x, y] = toNormalized(e);
        const next = page.corners.map((pt, i) => (i === idx ? [x, y] : pt));
        onCorners(next);
      }}
      onPointerUp={() => {
        dragRef.current = null;
      }}
      onPointerLeave={() => {
        dragRef.current = null;
      }}
    >
      <image href={page.previewUrl} width={width} height={height} />
      <polygon points={pts} className="flyer-scan-quad" />
      {page.corners.map(([x, y], i) => (
        <circle
          key={i}
          cx={x * width}
          cy={y * height}
          r={handleR}
          className="flyer-scan-handle"
          onPointerDown={(e) => {
            e.preventDefault();
            dragRef.current = i;
          }}
        />
      ))}
    </svg>
  );
}
