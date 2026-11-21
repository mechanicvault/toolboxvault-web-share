/**
 * FileTypeArt — full-color file-type artwork for the document
 * tiles (owner, 2026-11-05 17:05: "use actual colored nice
 * images like in this photo", reversing the 2026-11-04 glyph
 * tiles). One hand-drawn SVG per kind the attachment allowlist
 * can actually store (backend/app/core/storage.py: PDF, Word,
 * Excel, plain text, JPEG/PNG/WebP — no audio/video/zip can
 * ever be attached, so no artwork exists for them): a proper
 * page with a folded corner, brand-family coloring and detail
 * per kind, drawn in that family's spirit — never a copied
 * Microsoft/Adobe asset.
 *
 * This is the seed of the site-wide real-icon library (owner
 * rule, 2026-11-05 17:06: real colored icons, not plain flat
 * clipart, everywhere) — later lanes extend THIS set rather
 * than starting a second one. Every artwork shares one canvas
 * (64×80 page) so tiles align across kinds; gradients/filters
 * are id-prefixed per kind and identical across instances, so
 * repeated renders resolve to the same definitions.
 */
import type { ReactNode } from "react";

export type FileArtKind = "image" | "sheet" | "pdf" | "word" | "text" | "doc";

const PAGE_PATH = "M15 6h27l10 10v55a3 3 0 0 1-3 3H15a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3Z";
const FOLD_PATH = "M42 6l10 10h-7a3 3 0 0 1-3-3Z";
const FONT = "Arial, Helvetica, sans-serif";

function Page({
  kind,
  pageStops,
  children,
}: {
  kind: string;
  pageStops: [string, string];
  children?: ReactNode;
}) {
  return (
    <>
      <defs>
        <linearGradient id={`fta-${kind}-page`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={pageStops[0]} />
          <stop offset="1" stopColor={pageStops[1]} />
        </linearGradient>
        <linearGradient id={`fta-${kind}-fold`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f7f8fa" />
          <stop offset="1" stopColor="#c3c9d2" />
        </linearGradient>
        <filter id={`fta-${kind}-sh`} x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="1.6" stdDeviation="1.6" floodColor="#000000" floodOpacity="0.35" />
        </filter>
      </defs>
      <g filter={`url(#fta-${kind}-sh)`}>
        <path d={PAGE_PATH} fill={`url(#fta-${kind}-page)`} stroke="#9aa3ae" strokeWidth="0.8" />
        {children}
        <path d={FOLD_PATH} fill={`url(#fta-${kind}-fold)`} stroke="#9aa3ae" strokeWidth="0.7" />
      </g>
    </>
  );
}

function SheetArt() {
  return (
    <>
      <defs>
        <linearGradient id="fta-sheet-tab" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#35a05e" />
          <stop offset="1" stopColor="#176b3a" />
        </linearGradient>
      </defs>
      <Page kind="sheet" pageStops={["#ffffff", "#dde3ea"]}>
        {/* the spreadsheet grid, right of the tab */}
        <rect x="25" y="31" width="22" height="28" fill="#eaf5ee" />
        <rect x="25" y="31" width="22" height="7" fill="#217346" />
        <rect x="32.9" y="38.6" width="6.1" height="5.8" fill="#bfe3cc" />
        <rect x="40.2" y="45.6" width="6.1" height="5.8" fill="#bfe3cc" />
        <path
          d="M32.3 31v28M39.6 31v28M25 45h22M25 52h22"
          stroke="#a9cbb4"
          strokeWidth="1.2"
          fill="none"
        />
        <rect x="25" y="31" width="22" height="28" fill="none" stroke="#1d7044" strokeWidth="1.4" />
        {/* the green X tab overlapping the page's left edge */}
        <rect
          x="5"
          y="25"
          width="23"
          height="26"
          rx="3.5"
          fill="url(#fta-sheet-tab)"
          stroke="#0e4d2a"
          strokeWidth="1"
        />
        <text x="16.5" y="44" textAnchor="middle" fontFamily={FONT} fontWeight="800" fontSize="17" fill="#ffffff">
          X
        </text>
      </Page>
    </>
  );
}

function PdfArt() {
  return (
    <>
      <defs>
        <linearGradient id="fta-pdf-banner" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e8443a" />
          <stop offset="1" stopColor="#b71c1c" />
        </linearGradient>
      </defs>
      <Page kind="pdf" pageStops={["#ffffff", "#e3e6ea"]}>
        {/* the red PDF banner, sticking past the page's edges */}
        <rect
          x="6"
          y="27"
          width="52"
          height="15"
          rx="2.5"
          fill="url(#fta-pdf-banner)"
          stroke="#8e1414"
          strokeWidth="0.75"
        />
        <text
          x="32"
          y="38.6"
          textAnchor="middle"
          fontFamily={FONT}
          fontWeight="800"
          fontSize="11"
          letterSpacing="1.5"
          fill="#ffffff"
        >
          PDF
        </text>
        {/* a looping ribbon flourish under the banner */}
        <path
          d="M21 62c3.5-6.5 9-8.5 11.5-4.5 2.2 3.5-.5 7.5-4.8 8.3-3.9.7-6.7-2-5.9-5.6.7-3.2 4-5.4 7.4-5.2 4.7.3 8.3 3.4 13.8 1.4"
          stroke="#d32f2f"
          strokeWidth="2.3"
          fill="none"
          strokeLinecap="round"
        />
      </Page>
    </>
  );
}

function WordArt() {
  return (
    <>
      <defs>
        <linearGradient id="fta-word-tab" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#4a7dc9" />
          <stop offset="1" stopColor="#2b579a" />
        </linearGradient>
      </defs>
      <Page kind="word" pageStops={["#ffffff", "#dde3ea"]}>
        <path d="M31 31h16M31 37h16M31 43h12" stroke="#93a9c9" strokeWidth="2.4" strokeLinecap="round" />
        <path d="M18 55h28M18 61h28M18 67h18" stroke="#b9c6d8" strokeWidth="2.4" strokeLinecap="round" />
        {/* the blue W tab overlapping the page's left edge */}
        <rect
          x="5"
          y="25"
          width="23"
          height="26"
          rx="3.5"
          fill="url(#fta-word-tab)"
          stroke="#1f4069"
          strokeWidth="1"
        />
        <text x="16.5" y="43.5" textAnchor="middle" fontFamily={FONT} fontWeight="800" fontSize="15" fill="#ffffff">
          W
        </text>
      </Page>
    </>
  );
}

function ImageArt() {
  return (
    <>
      <defs>
        <linearGradient id="fta-image-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#79b8ec" />
          <stop offset="1" stopColor="#cfeffd" />
        </linearGradient>
        <clipPath id="fta-image-clip">
          <rect x="16" y="13" width="32" height="43" />
        </clipPath>
      </defs>
      <Page kind="image" pageStops={["#ffffff", "#e3e6ea"]}>
        {/* the picture, framed by the page itself */}
        <g clipPath="url(#fta-image-clip)">
          <rect x="16" y="13" width="32" height="43" fill="url(#fta-image-sky)" />
          <polygon points="16,56 28,35 35,46 41,38 48,56" fill="#5b8c5a" />
          <polygon points="26.2,38.6 28,35 29.9,38.6 28,37.4" fill="#ffffff" />
          <polygon points="16,56 23,44 30,51 36,45 48,56" fill="#38663f" />
          <circle cx="23.5" cy="20.5" r="3.2" fill="#ffc93c" stroke="#f0a71b" strokeWidth="0.75" />
        </g>
        <rect x="16" y="13" width="32" height="43" fill="none" stroke="#8a97a5" strokeWidth="1" />
        <path d="M23 64h18M26 69h12" stroke="#b9c6d8" strokeWidth="2.2" strokeLinecap="round" />
      </Page>
    </>
  );
}

function TextArt() {
  return (
    <Page kind="text" pageStops={["#fffdf4", "#e9e5d8"]}>
      {/* notebook rules with a red margin line */}
      <path
        d="M17 21h32M17 29h32M17 37h32M17 45h32M17 53h32M17 61h32M17 69h32"
        stroke="#a8bedd"
        strokeWidth="1.5"
      />
      <path d="M21.5 10v62" stroke="#e58a8a" strokeWidth="1.3" />
      <path
        d="M25 27.6h20M25 35.6h14M25 43.6h21M25 51.6h12"
        stroke="#6e8cae"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </Page>
  );
}

function DocArt() {
  return (
    <Page kind="doc" pageStops={["#f2f4f6", "#d3d8df"]}>
      <rect x="18" y="14" width="20" height="6.5" rx="1.5" fill="#79838f" />
      <path
        d="M18 29h28M18 37h28M18 45h28M18 53h28M18 61h16"
        stroke="#a3acb8"
        strokeWidth="2.3"
        strokeLinecap="round"
      />
    </Page>
  );
}

export function FileTypeArt({ kind, height = 80 }: { kind: FileArtKind; height?: number }) {
  return (
    <svg
      viewBox="0 0 64 80"
      height={height}
      width={Math.round(height * 0.8)}
      aria-hidden="true"
      focusable="false"
    >
      {kind === "sheet" ? (
        <SheetArt />
      ) : kind === "pdf" ? (
        <PdfArt />
      ) : kind === "word" ? (
        <WordArt />
      ) : kind === "image" ? (
        <ImageArt />
      ) : kind === "text" ? (
        <TextArt />
      ) : (
        <DocArt />
      )}
    </svg>
  );
}
