/**
 * ArtIcon — the site-wide REAL icon library (owner, 2026-11-05
 * 17:05 + 17:06 + 19:09: "if we use icons for something, i want
 * real colored icons, not plain flat clipart" — the main menu
 * icons named explicitly). Every icon that DEPICTS something —
 * a module, a stat, a category, a feature — is drawn here ONCE
 * as hand-built full-color SVG artwork and reused on every
 * surface that depicts the same concept (the main-menu rail,
 * Home widgets, Overview stat chips, search group chips, the
 * landing feature faces via BrandIcon, empty states, the audit
 * timeline). The same concept wears the same artwork everywhere.
 *
 * Pure control symbols stay functional glyphs in icons.tsx
 * (× close, carets, checkmarks, sort arrows, the hamburger, the
 * header cluster) — they are controls, not depictions.
 *
 * Craft rules (the FileTypeArt seed's): one shared 48×48 canvas,
 * bold silhouettes and a limited palette per icon so the work
 * stays legible at the 20–28px seats it renders in; gradients
 * and filters are id-prefixed per icon and identical across
 * instances, so repeated renders resolve to the same defs.
 * Nothing here is a copied brand asset; the trade objects are
 * drawn in the site's own hand.
 */
import type { ReactNode } from "react";

export type ArtName =
  | "home"
  | "flyers"
  | "inventory"
  | "parts"
  | "categories"
  | "people"
  | "shared"
  | "marketplace"
  | "borrowing"
  | "repairs"
  | "dealers"
  | "claims"
  | "disaster"
  | "reports"
  | "messages"
  | "forum"
  | "feedback"
  | "wishlist"
  | "expansion"
  | "truck"
  | "support"
  | "videos"
  | "settings"
  | "money"
  | "tag"
  | "warning"
  | "badge"
  | "backup"
  | "info"
  | "search"
  | "adminTickets"
  | "adminBug"
  | "adminFeature"
  | "adminForum"
  | "adminStats"
  | "converter"
  | "downloads";

const FONT = "Arial, Helvetica, sans-serif";

/** One vertical (or horizontal) two-stop gradient def. */
function lg(id: string, stops: [string, string], horizontal = false) {
  return (
    <linearGradient
      id={id}
      x1="0"
      y1="0"
      x2={horizontal ? "1" : "0"}
      y2={horizontal ? "0" : "1"}
    >
      <stop offset="0" stopColor={stops[0]} />
      <stop offset="1" stopColor={stops[1]} />
    </linearGradient>
  );
}

/** The shared soft drop shadow def (FileTypeArt's recipe). */
function shadow(name: string) {
  return (
    <filter id={`ai-${name}-sh`} x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="1.2" stdDeviation="1.2" floodColor="#000000" floodOpacity="0.32" />
    </filter>
  );
}

/** A gear: rotated-rect teeth around a disc, a recessed hub and
 *  a steel centre. fill/hub accept gradient urls. */
function Gear({
  cx,
  cy,
  r,
  teeth,
  fill,
  recess,
  centre,
}: {
  cx: number;
  cy: number;
  r: number;
  teeth: number;
  fill: string;
  recess: string;
  centre: string;
}) {
  const toothW = r * 0.36;
  const toothH = r * 0.34;
  return (
    <g>
      {Array.from({ length: teeth }).map((_, i) => (
        <rect
          key={i}
          x={cx - toothW / 2}
          y={cy - r - toothH + r * 0.08}
          width={toothW}
          height={toothH}
          rx={r * 0.07}
          fill={fill}
          transform={`rotate(${(360 / teeth) * i} ${cx} ${cy})`}
        />
      ))}
      <circle cx={cx} cy={cy} r={r} fill={fill} />
      <circle cx={cx} cy={cy} r={r * 0.52} fill={recess} />
      <circle cx={cx} cy={cy} r={r * 0.24} fill={centre} />
    </g>
  );
}

/** A filled wrench silhouette (the classic open-jaw profile),
 *  drawn on a 24-unit box so callers scale it into place. */
const WRENCH_PATH =
  "M14.7 5.6a1.15 1.15 0 0 0 0 1.63l1.75 1.75a1.15 1.15 0 0 0 1.63 0l3.6-3.6a6.2 6.2 0 0 1-8.2 8.2l-6.75 6.75a2.2 2.2 0 0 1-3.1-3.1l6.75-6.75a6.2 6.2 0 0 1 8.2-8.2z";

function WrenchSilhouette({
  x,
  y,
  scale,
  fill,
  stroke,
}: {
  x: number;
  y: number;
  scale: number;
  fill: string;
  stroke?: string;
}) {
  return (
    <path
      d={WRENCH_PATH}
      transform={`translate(${x} ${y}) scale(${scale})`}
      fill={fill}
      stroke={stroke}
      strokeWidth={stroke ? 0.55 : undefined}
    />
  );
}

/** One person bust: head + shoulders, jacket in `jacket`. */
function Bust({
  cx,
  headR,
  shoulderY,
  skin,
  jacket,
  collar,
}: {
  cx: number;
  headR: number;
  shoulderY: number;
  skin: string;
  jacket: string;
  collar?: boolean;
}) {
  const w = headR * 1.92;
  return (
    <g>
      <path
        d={`M${cx - w} 43c.7-6.4 5-10.2 ${w} -10.2s${w - 0.7} 3.8 ${w} 10.2Z`}
        fill={jacket}
        transform={`translate(0 ${shoulderY - 33})`}
      />
      <circle cx={cx} cy={shoulderY - 12.4} r={headR} fill={skin} />
      {collar && (
        <polygon
          points={`${cx - 3},${shoulderY - 0.5} ${cx + 3},${shoulderY - 0.5} ${cx},${shoulderY + 3.4}`}
          fill="#eef1f4"
        />
      )}
    </g>
  );
}

/* ---------------- the artwork ---------------- */

function HomeArt() {
  return (
    <>
      <defs>
        {shadow("home")}
        {lg("ai-home-roof", ["#66788c", "#3d4a59"])}
        {lg("ai-home-wall", ["#e8ecf0", "#c3ccd5"])}
        {lg("ai-home-door", ["#d84a35", "#a82c1c"])}
      </defs>
      <g filter="url(#ai-home-sh)">
        <rect x="33.5" y="10.5" width="4.6" height="7.5" fill="#8a4b38" />
        <polygon points="4,23 24,7 44,23 40.5,23 24,10.6 7.5,23" fill="url(#ai-home-roof)" />
        <rect x="10.5" y="23" width="27" height="17.5" fill="url(#ai-home-wall)" />
        <rect x="13.5" y="27" width="5.4" height="5.4" fill="#79b8ec" stroke="#5b7186" strokeWidth="0.8" />
        <rect x="20.6" y="29" width="7" height="11.5" fill="url(#ai-home-door)" stroke="#7e1f12" strokeWidth="0.7" />
        <circle cx="26" cy="35" r="0.95" fill="#f2b544" />
        <rect x="8" y="40.5" width="32" height="2.2" rx="1" fill="#77828e" />
      </g>
    </>
  );
}

function InventoryArt() {
  return (
    <>
      <defs>
        {shadow("inventory")}
        {lg("ai-inventory-lid", ["#e05a40", "#bc3822"])}
        {lg("ai-inventory-body", ["#cf4630", "#9c2716"])}
        {lg("ai-inventory-latch", ["#f2c14e", "#c78f1d"])}
      </defs>
      <g filter="url(#ai-inventory-sh)">
        <path d="M17 11.5v-1.8A2.7 2.7 0 0 1 19.7 7h8.6A2.7 2.7 0 0 1 31 9.7v1.8" fill="none" stroke="#39434e" strokeWidth="2.6" />
        <rect x="7" y="11" width="34" height="9" rx="2" fill="url(#ai-inventory-lid)" stroke="#7e1f12" strokeWidth="0.8" />
        <rect x="7" y="20" width="34" height="17" rx="2" fill="url(#ai-inventory-body)" stroke="#7e1f12" strokeWidth="0.8" />
        <rect x="7" y="24.5" width="34" height="2" fill="#8c2313" opacity="0.55" />
        <rect x="12.5" y="17.5" width="5.6" height="8" rx="1" fill="url(#ai-inventory-latch)" stroke="#8a5f0e" strokeWidth="0.7" />
        <rect x="29.9" y="17.5" width="5.6" height="8" rx="1" fill="url(#ai-inventory-latch)" stroke="#8a5f0e" strokeWidth="0.7" />
        <circle cx="15.3" cy="21.5" r="1" fill="#5d3c08" />
        <circle cx="32.7" cy="21.5" r="1" fill="#5d3c08" />
        <rect x="10" y="37" width="4.5" height="2.6" fill="#39434e" />
        <rect x="33.5" y="37" width="4.5" height="2.6" fill="#39434e" />
      </g>
    </>
  );
}

function PartsArt() {
  return (
    <>
      <defs>
        {shadow("parts")}
        {lg("ai-parts-steel", ["#aeb9c4", "#67737f"])}
        {lg("ai-parts-brass", ["#f2c14e", "#c78f1d"])}
      </defs>
      <g filter="url(#ai-parts-sh)">
        <Gear cx={19} cy={20} r={10.5} teeth={8} fill="url(#ai-parts-steel)" recess="#4a5560" centre="#d7dde3" />
        <Gear cx={34.5} cy={33.5} r={7.4} teeth={7} fill="url(#ai-parts-brass)" recess="#8a5f0e" centre="#f7dc9a" />
      </g>
    </>
  );
}

function CategoriesArt() {
  return (
    <>
      <defs>
        {shadow("categories")}
        {lg("ai-categories-a", ["#e05a40", "#b03320"])}
        {lg("ai-categories-b", ["#3fbdb2", "#1d7f78"])}
        {lg("ai-categories-c", ["#ffb62e", "#dd8505"])}
        {lg("ai-categories-d", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-categories-sh)">
        <rect x="7" y="7" width="15.5" height="15.5" rx="3" fill="url(#ai-categories-a)" />
        <rect x="25.5" y="7" width="15.5" height="15.5" rx="3" fill="url(#ai-categories-b)" />
        <rect x="7" y="25.5" width="15.5" height="15.5" rx="3" fill="url(#ai-categories-c)" />
        <rect x="25.5" y="25.5" width="15.5" height="15.5" rx="3" fill="url(#ai-categories-d)" />
      </g>
    </>
  );
}

function PeopleArt() {
  return (
    <>
      <defs>
        {shadow("people")}
        {lg("ai-people-skin", ["#f2c79b", "#dda26a"])}
        {lg("ai-people-a", ["#3d5a80", "#22354d"])}
        {lg("ai-people-b", ["#2ea8a0", "#177e78"])}
      </defs>
      <g filter="url(#ai-people-sh)">
        <Bust cx={31.5} headR={5.6} shoulderY={34} skin="url(#ai-people-skin)" jacket="url(#ai-people-b)" />
        <Bust cx={18.5} headR={6.6} shoulderY={33} skin="url(#ai-people-skin)" jacket="url(#ai-people-a)" collar />
      </g>
    </>
  );
}

function SharedArt() {
  return (
    <>
      <defs>
        {shadow("shared")}
        {lg("ai-shared-skin", ["#f2c79b", "#dda26a"])}
        {lg("ai-shared-a", ["#3d5a80", "#22354d"])}
        {lg("ai-shared-b", ["#2ea8a0", "#177e78"])}
        {lg("ai-shared-wrench", ["#ff8a3c", "#d95d00"])}
      </defs>
      <g filter="url(#ai-shared-sh)">
        <Bust cx={30.5} headR={5.4} shoulderY={32} skin="url(#ai-shared-skin)" jacket="url(#ai-shared-b)" />
        <Bust cx={17.5} headR={6.4} shoulderY={31} skin="url(#ai-shared-skin)" jacket="url(#ai-shared-a)" />
        <WrenchSilhouette x={13.5} y={21.5} scale={0.92} fill="url(#ai-shared-wrench)" stroke="#9c4a00" />
      </g>
    </>
  );
}

function MarketplaceArt() {
  return (
    <>
      <defs>
        {shadow("marketplace")}
        {lg("ai-market-body", ["#e8ecf0", "#c3ccd5"])}
        {lg("ai-market-red", ["#e05a40", "#b03320"])}
      </defs>
      <g filter="url(#ai-market-sh)">
        <rect x="6" y="8.5" width="36" height="3" rx="1.2" fill="#39434e" />
        <path d="M8 11.5h32v5.2a3.9 3.9 0 0 1-7.8 0 3.9 3.9 0 0 1-7.8 0 3.9 3.9 0 0 1-7.8 0 3.9 3.9 0 0 1-7.8 0Z" fill="url(#ai-market-red)" />
        <path d="M16.1 11.5h7.8v5.2a3.9 3.9 0 0 1-7.8 0Z" fill="#f4f6f8" />
        <path d="M31.9 11.5h7.8v5.2a3.9 3.9 0 0 1-7.8 0Z" fill="#f4f6f8" />
        <rect x="10" y="20.5" width="28" height="19.5" fill="url(#ai-market-body)" stroke="#98a2ad" strokeWidth="0.7" />
        <rect x="13.5" y="24.5" width="9.5" height="8.5" fill="#79b8ec" stroke="#5b7186" strokeWidth="0.8" />
        <rect x="27.5" y="24.5" width="7.5" height="15.5" fill="#5d4433" stroke="#3c2b1f" strokeWidth="0.7" />
        <circle cx="33.4" cy="32.5" r="0.95" fill="#f2b544" />
        <rect x="8" y="40" width="32" height="2" rx="1" fill="#77828e" />
      </g>
    </>
  );
}

function BorrowingArt() {
  return (
    <>
      <defs>
        {shadow("borrowing")}
        {lg("ai-borrow-out", ["#ff8a3c", "#d95d00"])}
        {lg("ai-borrow-in", ["#3fbdb2", "#1d7f78"])}
        {lg("ai-borrow-steel", ["#aeb9c4", "#67737f"])}
      </defs>
      <g filter="url(#ai-borrowing-sh)">
        <path d="M13.5 15.5A12.5 12.5 0 0 1 33 10.6" fill="none" stroke="url(#ai-borrow-out)" strokeWidth="4.6" strokeLinecap="round" />
        <polygon points="36.6,4.8 37.8,12.6 30.2,11.2" fill="#e06a00" />
        <path d="M34.5 32.5A12.5 12.5 0 0 1 15 37.4" fill="none" stroke="url(#ai-borrow-in)" strokeWidth="4.6" strokeLinecap="round" />
        <polygon points="11.4,43.2 10.2,35.4 17.8,36.8" fill="#1d8a80" />
        <Gear cx={24} cy={24} r={5.4} teeth={6} fill="url(#ai-borrow-steel)" recess="#4a5560" centre="#d7dde3" />
      </g>
    </>
  );
}

function RepairsArt() {
  return (
    <>
      <defs>
        {shadow("repairs")}
        {lg("ai-repairs-gear", ["#aeb9c4", "#67737f"])}
        {lg("ai-repairs-wrench", ["#f4f7fa", "#a7b2be"])}
      </defs>
      <g filter="url(#ai-repairs-sh)">
        <Gear cx={18.5} cy={19} r={11} teeth={8} fill="url(#ai-repairs-gear)" recess="#4a5560" centre="#d7dde3" />
        <WrenchSilhouette x={10} y={13} scale={1.42} fill="url(#ai-repairs-wrench)" stroke="#5d6a76" />
      </g>
    </>
  );
}

function DealersArt() {
  return (
    <>
      <defs>
        {shadow("dealers")}
        {lg("ai-dealers-box", ["#f4f6f8", "#ccd4dc"])}
        {lg("ai-dealers-cab", ["#e05a40", "#b03320"])}
        {lg("ai-dealers-stripe", ["#ff8a3c", "#d95d00"])}
      </defs>
      <g filter="url(#ai-dealers-sh)">
        <rect x="3.5" y="9" width="27" height="20" rx="1.6" fill="url(#ai-dealers-box)" stroke="#98a2ad" strokeWidth="0.8" />
        <rect x="3.5" y="21.5" width="27" height="3.6" fill="url(#ai-dealers-stripe)" />
        <circle cx="17" cy="15.8" r="4.6" fill="#39434e" />
        <WrenchSilhouette x={13.4} y={12.2} scale={0.3} fill="#f4f6f8" />
        <path d="M30.5 15.5h5.6a3 3 0 0 1 2.3 1.1l4.4 5.4a3 3 0 0 1 .7 1.9V29h-13z" fill="url(#ai-dealers-cab)" stroke="#7e1f12" strokeWidth="0.7" />
        <polygon points="32.5,17.5 36,17.5 39.8,22.5 32.5,22.5" fill="#79b8ec" stroke="#5b7186" strokeWidth="0.6" />
        <rect x="3.5" y="29" width="41" height="2.4" fill="#39434e" />
        <circle cx="12.5" cy="33" r="4.1" fill="#22282e" />
        <circle cx="12.5" cy="33" r="1.8" fill="#aeb9c4" />
        <circle cx="35.5" cy="33" r="4.1" fill="#22282e" />
        <circle cx="35.5" cy="33" r="1.8" fill="#aeb9c4" />
        <rect x="5" y="38.5" width="38" height="1.8" rx="0.9" fill="#98a2ad" opacity="0.7" />
      </g>
    </>
  );
}

function ClaimsArt() {
  return (
    <>
      <defs>
        {shadow("claims")}
        {lg("ai-claims-shield", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-claims-sh)">
        <path
          d="M24 3.5 9.5 8v11.5c0 10.5 6.2 18.3 14.5 21.5 8.3-3.2 14.5-11 14.5-21.5V8Z"
          fill="url(#ai-claims-shield)"
          stroke="#1d3f6e"
          strokeWidth="1"
        />
        <path d="M24 6.6 12.3 10.2v9.1c0 8.6 4.9 15.2 11.7 18 6.8-2.8 11.7-9.4 11.7-18v-9.1Z" fill="#ffffff" opacity="0.14" />
        <path d="m16.5 23.4 5.2 5.2 9.8-10.6" fill="none" stroke="#ffffff" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </>
  );
}

function DisasterArt() {
  return (
    <>
      <defs>
        {shadow("disaster")}
        {lg("ai-disaster-cloud", ["#6d7c8c", "#39434e"])}
        {lg("ai-disaster-bolt", ["#ffd35c", "#e79a1e"])}
      </defs>
      <g filter="url(#ai-disaster-sh)">
        <path
          d="M13 27.5a7.5 7.5 0 0 1-.9-14.9A10.5 10.5 0 0 1 32.4 9a8.5 8.5 0 0 1 4.9 15.9c-.8 1.6-2.2 2.6-4.3 2.6Z"
          fill="url(#ai-disaster-cloud)"
          stroke="#242c33"
          strokeWidth="0.8"
        />
        <polygon points="26.5,24 19.5,36.5 24.3,36.5 21.8,45 31.5,31.5 26.4,31.5" fill="url(#ai-disaster-bolt)" stroke="#b97a10" strokeWidth="0.7" strokeLinejoin="round" />
        <path d="M12.5 33.5l-2 4M12.8 40.5l-1.6 3.2" stroke="#5b93dd" strokeWidth="2.1" strokeLinecap="round" />
        <path d="M37 33.5l-2 4M37.3 40.5l-1.6 3.2" stroke="#5b93dd" strokeWidth="2.1" strokeLinecap="round" />
      </g>
    </>
  );
}

function ReportsArt() {
  return (
    <>
      <defs>
        {shadow("reports")}
        {lg("ai-reports-a", ["#8fa1b3", "#5d6d7e"])}
        {lg("ai-reports-b", ["#3fbdb2", "#1d7f78"])}
        {lg("ai-reports-c", ["#3fae5f", "#1e7a3c"])}
      </defs>
      <g filter="url(#ai-reports-sh)">
        <rect x="9" y="27" width="6.5" height="12" rx="1" fill="url(#ai-reports-a)" />
        <rect x="18.5" y="20" width="6.5" height="19" rx="1" fill="url(#ai-reports-b)" />
        <rect x="28" y="13" width="6.5" height="26" rx="1" fill="url(#ai-reports-c)" />
        <polyline points="10,23 21,16.5 30.5,9.5" fill="none" stroke="#f2760a" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <polygon points="35.8,4.6 36.6,10.4 30.9,10.8" fill="#f2760a" />
        <rect x="6" y="39" width="36" height="2.4" rx="1.2" fill="#39434e" />
      </g>
    </>
  );
}

function MessagesArt() {
  return (
    <>
      <defs>
        {shadow("messages")}
        {lg("ai-messages-bubble", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-messages-sh)">
        <path
          d="M10 7h28a5 5 0 0 1 5 5v15a5 5 0 0 1-5 5H22l-8.2 7.2c-.9.8-2.3.1-2.3-1.1V32H10a5 5 0 0 1-5-5V12a5 5 0 0 1 5-5Z"
          fill="url(#ai-messages-bubble)"
          stroke="#1d3f6e"
          strokeWidth="0.8"
        />
        <rect x="12.5" y="14.5" width="23" height="3.1" rx="1.55" fill="#ffffff" opacity="0.92" />
        <rect x="12.5" y="21.5" width="15.5" height="3.1" rx="1.55" fill="#ffffff" opacity="0.65" />
      </g>
    </>
  );
}

function ForumArt() {
  return (
    <>
      <defs>
        {shadow("forum")}
        {lg("ai-forum-back", ["#3fbdb2", "#1d7f78"])}
        {lg("ai-forum-front", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-forum-sh)">
        <path
          d="M19 5h22a4.4 4.4 0 0 1 4.4 4.4v13.2A4.4 4.4 0 0 1 41 27H30.5l-6.8 5.6c-.8.7-2 .1-2-1V27h-2.7a4.4 4.4 0 0 1-4.4-4.4V9.4A4.4 4.4 0 0 1 19 5Z"
          fill="url(#ai-forum-back)"
          stroke="#125f59"
          strokeWidth="0.7"
        />
        <path
          d="M7 17h23a4.4 4.4 0 0 1 4.4 4.4v11A4.4 4.4 0 0 1 30 36.8h-9.6l-6.4 5.3c-.8.6-1.9.1-1.9-1v-4.3H7a4.4 4.4 0 0 1-4.4-4.4v-11A4.4 4.4 0 0 1 7 17Z"
          fill="url(#ai-forum-front)"
          stroke="#1d3f6e"
          strokeWidth="0.7"
        />
        <rect x="9" y="23.5" width="15" height="2.8" rx="1.4" fill="#ffffff" opacity="0.92" />
        <rect x="9" y="29.3" width="10" height="2.8" rx="1.4" fill="#ffffff" opacity="0.62" />
      </g>
    </>
  );
}

function FeedbackArt() {
  return (
    <>
      <defs>
        {shadow("feedback")}
        {lg("ai-feedback-body", ["#c0504a", "#8e2f28"])}
      </defs>
      <g filter="url(#ai-feedback-sh)">
        <path d="M17.5 10.5 13 5.8M30.5 10.5 35 5.8" stroke="#39434e" strokeWidth="2.2" strokeLinecap="round" fill="none" />
        <circle cx="12.2" cy="5" r="1.7" fill="#39434e" />
        <circle cx="35.8" cy="5" r="1.7" fill="#39434e" />
        <path d="M10 24.5 4.5 21M9.8 31.5H3.8M11.5 37.5l-4.6 3.4M38 24.5l5.5-3.5M38.2 31.5h6M36.5 37.5l4.6 3.4" stroke="#39434e" strokeWidth="2.3" strokeLinecap="round" fill="none" />
        <ellipse cx="24" cy="27.5" rx="12.5" ry="14.5" fill="url(#ai-feedback-body)" stroke="#5f1f1a" strokeWidth="0.9" />
        <path d="M24 13.5v28" stroke="#5f1f1a" strokeWidth="1.7" />
        <path d="M12.5 22.5c3.5 1.7 7.5 2.5 11.5 2.5s8-.8 11.5-2.5M13.5 33.5c3.2 1.5 6.8 2.2 10.5 2.2s7.3-.7 10.5-2.2" fill="none" stroke="#5f1f1a" strokeWidth="1.3" opacity="0.65" />
        <ellipse cx="24" cy="11.8" rx="6" ry="4.6" fill="#39434e" />
        <circle cx="21.8" cy="11" r="1.15" fill="#f4f6f8" />
        <circle cx="26.2" cy="11" r="1.15" fill="#f4f6f8" />
      </g>
    </>
  );
}

function WishlistArt() {
  return (
    <>
      <defs>
        {shadow("wishlist")}
        {lg("ai-wishlist-glass", ["#cfeffd", "#8fc3ee"])}
        {lg("ai-wishlist-wrench", ["#ff8a3c", "#d95d00"])}
      </defs>
      <g filter="url(#ai-wishlist-sh)">
        <circle cx="20.5" cy="20.5" r="12.5" fill="url(#ai-wishlist-glass)" fillOpacity="0.5" />
        <WrenchSilhouette x={10.8} y={10.2} scale={0.82} fill="url(#ai-wishlist-wrench)" />
        <circle cx="20.5" cy="20.5" r="12.5" fill="none" stroke="#39434e" strokeWidth="3.6" />
        <path d="M29.8 29.8 41 41" stroke="#39434e" strokeWidth="5" strokeLinecap="round" />
      </g>
    </>
  );
}

function ExpansionArt() {
  return (
    <>
      <defs>
        {shadow("expansion")}
        {lg("ai-expansion-basket", ["#8fa1b3", "#55636f"])}
        {lg("ai-expansion-wrench", ["#ff8a3c", "#d95d00"])}
        {lg("ai-expansion-box", ["#f2c14e", "#c78f1d"])}
      </defs>
      <g filter="url(#ai-expansion-sh)">
        <WrenchSilhouette x={14.5} y={0.5} scale={0.88} fill="url(#ai-expansion-wrench)" stroke="#9c4a00" />
        <rect x="24.5" y="6.5" width="10.5" height="9" rx="1.2" fill="url(#ai-expansion-box)" stroke="#8a5f0e" strokeWidth="0.7" />
        <path d="M4.5 13.5h4.6l3 16.5a3 3 0 0 0 3 2.5h19.6a3 3 0 0 0 2.9-2.3L41 17.5H10.5" fill="none" stroke="#39434e" strokeWidth="2.7" strokeLinejoin="round" />
        <path d="M11.8 20.5h27.4l-2.6 9.5H14.2Z" fill="url(#ai-expansion-basket)" stroke="#39434e" strokeWidth="0.8" />
        <path d="M18.5 20.8 20 29.8M25.5 20.8v9M32.5 20.8l-1.6 9" stroke="#39434e" strokeWidth="1.3" opacity="0.55" />
        <circle cx="17" cy="38.8" r="3.1" fill="#22282e" />
        <circle cx="17" cy="38.8" r="1.25" fill="#aeb9c4" />
        <circle cx="35" cy="38.8" r="3.1" fill="#22282e" />
        <circle cx="35" cy="38.8" r="1.25" fill="#aeb9c4" />
      </g>
    </>
  );
}

function TruckArt() {
  return (
    <>
      <defs>
        {shadow("truck")}
        {lg("ai-truck-cover", ["#3d5a80", "#22354d"])}
        {lg("ai-truck-coin", ["#ffd35c", "#e79a1e"])}
      </defs>
      <g filter="url(#ai-truck-sh)">
        <polygon points="28.5,36 32.5,36 32.5,46.5 30.5,44 28.5,46.5" fill="#c8402a" stroke="#7e1f12" strokeWidth="0.6" strokeLinejoin="round" />
        <rect x="12" y="5" width="25" height="37" rx="2.4" fill="url(#ai-truck-cover)" stroke="#141f2c" strokeWidth="0.9" />
        <rect x="16.5" y="5" width="3" height="37" fill="#141f2c" opacity="0.4" />
        <rect x="34.8" y="8.5" width="2.2" height="30" fill="#e8ecf0" opacity="0.85" />
        <circle cx="26.5" cy="21.5" r="8" fill="url(#ai-truck-coin)" stroke="#a86e0c" strokeWidth="1" />
        <text x="26.5" y="26.8" textAnchor="middle" fontFamily={FONT} fontWeight="800" fontSize="12.5" fill="#7c5208">
          $
        </text>
      </g>
    </>
  );
}

function SupportArt() {
  return (
    <>
      <defs>
        {shadow("support")}
        {lg("ai-support-cup", ["#4a5560", "#2b333b"])}
        {lg("ai-support-pad", ["#ff8a3c", "#d95d00"])}
      </defs>
      <g filter="url(#ai-support-sh)">
        <path d="M9.5 31v-6.5a14.5 14.5 0 0 1 29 0V31" fill="none" stroke="#2b333b" strokeWidth="4.4" strokeLinecap="round" />
        <rect x="5.5" y="27.5" width="8.5" height="13" rx="3" fill="url(#ai-support-cup)" stroke="#161c21" strokeWidth="0.8" />
        <rect x="34" y="27.5" width="8.5" height="13" rx="3" fill="url(#ai-support-cup)" stroke="#161c21" strokeWidth="0.8" />
        <rect x="8.2" y="31" width="3" height="6.5" rx="1.5" fill="url(#ai-support-pad)" />
        <rect x="36.8" y="31" width="3" height="6.5" rx="1.5" fill="url(#ai-support-pad)" />
        <path d="M38.5 40.5c0 3.4-3.4 5-8.5 5h-3.4" fill="none" stroke="#2b333b" strokeWidth="3" strokeLinecap="round" />
        <rect x="19.5" y="43" width="8.5" height="4.6" rx="2.3" fill="url(#ai-support-pad)" stroke="#9c4a00" strokeWidth="0.7" />
      </g>
    </>
  );
}

/** How-to videos (owner, 2026-11-06): a steel-framed video
 * screen with a red play disc — reads as "watch this" at the
 * rail's 24px seat and holds at the page header's 96px tile. */
function VideosArt() {
  return (
    <>
      <defs>
        {shadow("videos")}
        {lg("ai-videos-frame", ["#4a5560", "#2b333b"])}
        {lg("ai-videos-glass", ["#26313b", "#11171c"])}
        {lg("ai-videos-play", ["#f0564a", "#c22f24"])}
      </defs>
      <g filter="url(#ai-videos-sh)">
        <rect x="5" y="8.5" width="38" height="27" rx="3.5" fill="url(#ai-videos-frame)" stroke="#161c21" strokeWidth="0.9" />
        <rect x="8" y="11.5" width="32" height="21" rx="2" fill="url(#ai-videos-glass)" />
        <circle cx="24" cy="22" r="6.6" fill="url(#ai-videos-play)" stroke="#7e1d16" strokeWidth="0.7" />
        <path d="M21.7 18.6 L28.6 22 L21.7 25.4 Z" fill="#ffffff" />
        <rect x="22.4" y="35.5" width="3.2" height="3.6" fill="#2b333b" />
        <rect x="16" y="39.1" width="16" height="2.7" rx="1.35" fill="url(#ai-videos-frame)" stroke="#161c21" strokeWidth="0.7" />
      </g>
    </>
  );
}

/** Settings (owner, 2026-11-06: "Change the setting icon to a
 *  gear"): ONE steel gear, centred and drawn large — at the
 *  rail's 24px seat a single gear reads instantly where the
 *  two-gear Parts piece would mush. Same steel, recess and
 *  centre as the gears in Parts/Repairs. */
function SettingsArt() {
  return (
    <>
      <defs>
        {shadow("settings")}
        {lg("ai-settings-steel", ["#aeb9c4", "#67737f"])}
      </defs>
      <g filter="url(#ai-settings-sh)">
        <Gear cx={24} cy={24} r={13.5} teeth={8} fill="url(#ai-settings-steel)" recess="#4a5560" centre="#d7dde3" />
      </g>
    </>
  );
}

/** Converter (converter widget lane, owner 2026-11-08): a shop
 *  calculator — navy steel body, a pale reading on the glass,
 *  steel keys and the one orange equals key. The Downloads
 *  converter's face wherever it is depicted (Home widget head). */
function ConverterArt() {
  return (
    <>
      <defs>
        {shadow("converter")}
        {lg("ai-converter-body", ["#46586e", "#27354a"])}
        {lg("ai-converter-glass", ["#d7e8dc", "#a7c3ae"])}
        {lg("ai-converter-key", ["#c9d2da", "#8d99a5"])}
        {lg("ai-converter-equals", ["#f97d1e", "#e05e05"])}
      </defs>
      <g filter="url(#ai-converter-sh)">
        <rect x="13.5" y="4.5" width="21" height="39" rx="3" fill="url(#ai-converter-body)" stroke="#141c28" strokeWidth="0.9" />
        <rect x="17" y="8" width="14" height="8.5" rx="1.5" fill="url(#ai-converter-glass)" stroke="#141c28" strokeWidth="0.6" />
        <rect x="24.6" y="10.6" width="4.4" height="2" rx="0.6" fill="#22382c" />
        <rect x="27.5" y="13.6" width="1.5" height="1.5" rx="0.4" fill="#22382c" />
        {[19.5, 25, 30.5].map((y) =>
          [17.2, 22.2, 27.2].map((x) => (
            <rect key={`${x}-${y}`} x={x} y={y} width="3.6" height="3.6" rx="1" fill="url(#ai-converter-key)" stroke="#141c28" strokeWidth="0.4" />
          )),
        )}
        <rect x="17.2" y="36" width="13.6" height="3.8" rx="1.2" fill="url(#ai-converter-equals)" stroke="#8a3c02" strokeWidth="0.5" />
      </g>
    </>
  );
}

function MoneyArt() {
  return (
    <>
      <defs>
        {shadow("money")}
        {lg("ai-money-coin", ["#ffd35c", "#eda417"])}
      </defs>
      <g filter="url(#ai-money-sh)">
        <circle cx="24" cy="24" r="17" fill="url(#ai-money-coin)" stroke="#a86e0c" strokeWidth="1.4" />
        <circle cx="24" cy="24" r="12.8" fill="none" stroke="#c07f10" strokeWidth="1.6" />
        <circle cx="24" cy="24" r="12.8" fill="none" stroke="#ffe9a8" strokeWidth="0.7" opacity="0.8" transform="translate(0 0.7)" />
        <text x="24" y="31.5" textAnchor="middle" fontFamily={FONT} fontWeight="800" fontSize="19" fill="#7c5208">
          $
        </text>
      </g>
    </>
  );
}

function TagArt() {
  return (
    <>
      <defs>
        {shadow("tag")}
        {lg("ai-tag-body", ["#ff8a3c", "#e05e00"])}
      </defs>
      <g filter="url(#ai-tag-sh)">
        <g transform="rotate(-38 24 24)">
          <path d="M7 16.5h21.5L41 24l-12.5 7.5H7a2.4 2.4 0 0 1-2.4-2.4V18.9A2.4 2.4 0 0 1 7 16.5Z" fill="url(#ai-tag-body)" stroke="#9c4a00" strokeWidth="0.9" strokeLinejoin="round" />
          <circle cx="34.2" cy="24" r="2.7" fill="#f7f3ea" stroke="#9c4a00" strokeWidth="0.8" />
          <path d="M10.5 21h12M10.5 26.5h8" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" opacity="0.8" />
        </g>
      </g>
    </>
  );
}

function WarningArt() {
  return (
    <>
      <defs>
        {shadow("warning")}
        {lg("ai-warning-body", ["#ffcf4d", "#f09c05"])}
      </defs>
      <g filter="url(#ai-warning-sh)">
        <path
          d="M24 5.5a3.4 3.4 0 0 1 3 1.8l15.4 28.5a3.4 3.4 0 0 1-3 5H8.6a3.4 3.4 0 0 1-3-5L21 7.3a3.4 3.4 0 0 1 3-1.8Z"
          fill="url(#ai-warning-body)"
          stroke="#a86a00"
          strokeWidth="1.1"
          strokeLinejoin="round"
        />
        <rect x="22.4" y="17.5" width="3.2" height="11.5" rx="1.6" fill="#4d3200" />
        <circle cx="24" cy="34.6" r="1.9" fill="#4d3200" />
      </g>
    </>
  );
}

function BadgeArt() {
  return (
    <>
      <defs>
        {shadow("badge")}
        {lg("ai-badge-disc", ["#3fbdb2", "#1d7f78"])}
        {lg("ai-badge-ribbon", ["#e05a40", "#b03320"])}
      </defs>
      <g filter="url(#ai-badge-sh)">
        <polygon points="17.5,27 13,43.5 20,40.5 24.5,45.5 25.5,29.5" fill="url(#ai-badge-ribbon)" stroke="#7e1f12" strokeWidth="0.7" strokeLinejoin="round" />
        <polygon points="30.5,27 35,43.5 28,40.5 23.5,45.5 22.5,29.5" fill="url(#ai-badge-ribbon)" stroke="#7e1f12" strokeWidth="0.7" strokeLinejoin="round" transform="translate(0 -1)" />
        <circle cx="24" cy="19.5" r="13" fill="url(#ai-badge-disc)" stroke="#125f59" strokeWidth="1" />
        <circle cx="24" cy="19.5" r="9.8" fill="none" stroke="#ffffff" strokeWidth="1.3" opacity="0.55" />
        <path d="m17.8 19.8 4.2 4.2 8-8.8" fill="none" stroke="#ffffff" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </>
  );
}

function BackupArt() {
  return (
    <>
      <defs>
        {shadow("backup")}
        {lg("ai-backup-cloud", ["#7fa8cf", "#4a719e"])}
        {lg("ai-backup-arrow", ["#3fae5f", "#1e7a3c"])}
      </defs>
      <g filter="url(#ai-backup-sh)">
        <path
          d="M14.5 33a8 8 0 0 1-1.2-15.9A11.5 11.5 0 0 1 35.7 14 7.5 7.5 0 0 1 34.5 33Z"
          fill="url(#ai-backup-cloud)"
          stroke="#2f4d6e"
          strokeWidth="0.9"
        />
        <polygon points="24,22.5 29.5,29.5 26.2,29.5 26.2,39.5 21.8,39.5 21.8,29.5 18.5,29.5" fill="url(#ai-backup-arrow)" stroke="#14522a" strokeWidth="0.8" strokeLinejoin="round" />
      </g>
    </>
  );
}

function InfoArt() {
  return (
    <>
      <defs>
        {shadow("info")}
        {lg("ai-info-disc", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-info-sh)">
        <circle cx="24" cy="24" r="17" fill="url(#ai-info-disc)" stroke="#1d3f6e" strokeWidth="1.1" />
        <circle cx="24" cy="16.8" r="2.5" fill="#ffffff" />
        <rect x="22.2" y="21.8" width="3.6" height="10.5" rx="1.8" fill="#ffffff" />
      </g>
    </>
  );
}

function SearchArt() {
  return (
    <>
      <defs>
        {shadow("search")}
        {lg("ai-search-glass", ["#cfeffd", "#8fc3ee"])}
        {lg("ai-search-pin", ["#ff8a3c", "#d95d00"])}
      </defs>
      <g filter="url(#ai-search-sh)">
        <circle cx="20.5" cy="20.5" r="12.5" fill="url(#ai-search-glass)" fillOpacity="0.5" />
        <path d="M20.5 12.8a4.9 4.9 0 0 1 4.9 4.9c0 3.6-4.9 8.3-4.9 8.3s-4.9-4.7-4.9-8.3a4.9 4.9 0 0 1 4.9-4.9Z" fill="url(#ai-search-pin)" stroke="#9c4a00" strokeWidth="0.7" />
        <circle cx="20.5" cy="17.6" r="1.9" fill="#ffffff" />
        <circle cx="20.5" cy="20.5" r="12.5" fill="none" stroke="#39434e" strokeWidth="3.6" />
        <path d="M29.8 29.8 41 41" stroke="#39434e" strokeWidth="5" strokeLinecap="round" />
      </g>
    </>
  );
}

function FlyersArt() {
  return (
    <>
      <defs>
        {shadow("flyers")}
        {lg("ai-flyers-sheet", ["#fdfdf8", "#d9d9ce"])}
        {lg("ai-flyers-band", ["#f58a2a", "#d95f06"])}
        {lg("ai-flyers-burst", ["#ffd35c", "#e79a1e"])}
      </defs>
      <g filter="url(#ai-flyers-sh)">
        {/* the paper sheet */}
        <path
          d="M13 3.5h16.5L37 11v33.5H13Z"
          fill="url(#ai-flyers-sheet)"
          stroke="#8f8f80"
          strokeWidth="1"
        />
        {/* folded corner */}
        <path d="M29.5 3.5V11H37Z" fill="#c9c9ba" stroke="#8f8f80" strokeWidth="0.8" />
        {/* headline band */}
        <rect x="16.5" y="15" width="15" height="5.2" rx="1" fill="url(#ai-flyers-band)" />
        {/* text lines */}
        <rect x="16.5" y="23.5" width="17" height="2.6" rx="1.3" fill="#5a6068" />
        <rect x="16.5" y="28.6" width="13.5" height="2.6" rx="1.3" fill="#7c828a" />
        <rect x="16.5" y="33.7" width="9" height="2.6" rx="1.3" fill="#7c828a" />
        {/* sale burst */}
        <path
          d="M33.5 30.2l1.7 2.5 2.9-.6-.9 2.9 1.9 2.3-2.9.8-.4 3-2.3-1.9-2.9.8.9-2.9-1.9-2.3 2.9-.8z"
          fill="url(#ai-flyers-burst)"
          stroke="#a86a10"
          strokeWidth="0.7"
          transform="translate(0.5 3.5) scale(0.92)"
        />
      </g>
    </>
  );
}

/** Admin widgets (admin polish lane, 2026-11-07): the five
 *  responder-side Home widgets get real artwork like every
 *  other widget — a golden support ticket with its perforated
 *  stub, a green beetle for bug reports (the Feedback piece's
 *  red beetle stays the boards' own), a lit bulb for feature
 *  requests, a shield flying the moderator's flag, and a
 *  dashboard gauge for site stats. */
function AdminTicketsArt() {
  return (
    <>
      <defs>
        {shadow("admintickets")}
        {lg("ai-admintickets-body", ["#f2c14e", "#d99a1f"])}
      </defs>
      <g filter="url(#ai-admintickets-sh)">
        <g transform="rotate(-8 24 24)">
          <rect x="4.5" y="14" width="39" height="20" rx="3" fill="url(#ai-admintickets-body)" stroke="#8a5f0e" strokeWidth="1" />
          <line x1="32.5" y1="15.5" x2="32.5" y2="32.5" stroke="#8a5f0e" strokeWidth="1.6" strokeDasharray="2.6 2.2" />
          <path d="M10 21.5h15M10 27h11" stroke="#7c5208" strokeWidth="2.4" strokeLinecap="round" opacity="0.75" />
          <polygon points="38,19.8 39.1,22.4 41.9,22.6 39.8,24.4 40.4,27.2 38,25.7 35.6,27.2 36.2,24.4 34.1,22.6 36.9,22.4" fill="#fff7dd" stroke="#8a5f0e" strokeWidth="0.7" strokeLinejoin="round" />
        </g>
      </g>
    </>
  );
}

function AdminBugArt() {
  return (
    <>
      <defs>
        {shadow("adminbug")}
        {lg("ai-adminbug-body", ["#3fae5f", "#1e7a3c"])}
      </defs>
      <g filter="url(#ai-adminbug-sh)">
        <path d="M17.5 10.5 13 5.8M30.5 10.5 35 5.8" stroke="#22301f" strokeWidth="2.2" strokeLinecap="round" fill="none" />
        <circle cx="12.2" cy="5" r="1.7" fill="#22301f" />
        <circle cx="35.8" cy="5" r="1.7" fill="#22301f" />
        <path d="M10 24.5 4.5 21M9.8 31.5H3.8M11.5 37.5l-4.6 3.4M38 24.5l5.5-3.5M38.2 31.5h6M36.5 37.5l4.6 3.4" stroke="#22301f" strokeWidth="2.3" strokeLinecap="round" fill="none" />
        <ellipse cx="24" cy="27.5" rx="12.5" ry="14.5" fill="url(#ai-adminbug-body)" stroke="#14522a" strokeWidth="0.9" />
        <path d="M24 13.5v28" stroke="#14522a" strokeWidth="1.7" />
        <path d="M12.5 22.5c3.5 1.7 7.5 2.5 11.5 2.5s8-.8 11.5-2.5M13.5 33.5c3.2 1.5 6.8 2.2 10.5 2.2s7.3-.7 10.5-2.2" fill="none" stroke="#14522a" strokeWidth="1.3" opacity="0.65" />
        <ellipse cx="24" cy="11.8" rx="6" ry="4.6" fill="#22301f" />
        <circle cx="21.8" cy="11" r="1.15" fill="#ffd35c" />
        <circle cx="26.2" cy="11" r="1.15" fill="#ffd35c" />
      </g>
    </>
  );
}

function AdminFeatureArt() {
  return (
    <>
      <defs>
        {shadow("adminfeature")}
        {lg("ai-adminfeature-bulb", ["#ffd35c", "#f0a50a"])}
        {lg("ai-adminfeature-base", ["#aeb9c4", "#67737f"])}
      </defs>
      <g filter="url(#ai-adminfeature-sh)">
        <path d="M24 3.5v4M10.5 7.5l2.6 3.4M37.5 7.5l-2.6 3.4M5.5 20h4.4M38.1 20h4.4" stroke="#f0a50a" strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="24" cy="21.5" r="12" fill="url(#ai-adminfeature-bulb)" stroke="#a86e0c" strokeWidth="1" />
        <path d="M19.5 26.5c.8-3.4 2.2-5 4.5-5s3.7 1.6 4.5 5" fill="none" stroke="#7c5208" strokeWidth="1.8" strokeLinecap="round" />
        <ellipse cx="19.8" cy="16.8" rx="3.4" ry="2.2" fill="#ffffff" opacity="0.55" transform="rotate(-24 19.8 16.8)" />
        <rect x="19" y="34.5" width="10" height="3" rx="1" fill="url(#ai-adminfeature-base)" stroke="#4a5560" strokeWidth="0.7" />
        <rect x="19.8" y="38.6" width="8.4" height="3" rx="1" fill="url(#ai-adminfeature-base)" stroke="#4a5560" strokeWidth="0.7" />
        <path d="M21.5 41.6h5l-2.5 3.4Z" fill="#4a5560" />
      </g>
    </>
  );
}

function AdminForumArt() {
  return (
    <>
      <defs>
        {shadow("adminforum")}
        {lg("ai-adminforum-shield", ["#5b93dd", "#2f5da3"])}
      </defs>
      <g filter="url(#ai-adminforum-sh)">
        <path
          d="M24 4.5 39 9.5v11c0 10.5-6.4 18.6-15 23C15.4 39.1 9 31 9 20.5v-11Z"
          fill="url(#ai-adminforum-shield)"
          stroke="#1d3f6e"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        <path
          d="M24 8.3 35.4 12.1v8.6c0 8.4-4.9 15-11.4 18.9C17.5 35.7 12.6 29.1 12.6 20.7v-8.6Z"
          fill="none"
          stroke="#ffffff"
          strokeWidth="1.1"
          opacity="0.4"
          strokeLinejoin="round"
        />
        <rect x="22.9" y="15" width="2.2" height="15" fill="#22354d" />
        <path d="M25.1 15.4 33 18.2l-7.9 2.9Z" fill="#f2760a" stroke="#9c4a00" strokeWidth="0.7" strokeLinejoin="round" />
      </g>
    </>
  );
}

function AdminStatsArt() {
  return (
    <>
      <defs>
        {shadow("adminstats")}
        {lg("ai-adminstats-face", ["#39434e", "#22282e"])}
      </defs>
      <g filter="url(#ai-adminstats-sh)">
        <path d="M6 35a19 19 0 0 1 36 0Z" fill="url(#ai-adminstats-face)" stroke="#141a1f" strokeWidth="1" />
        <path d="M10.2 34.2a14.6 14.6 0 0 1 5.4-9.4" fill="none" stroke="#3fae5f" strokeWidth="3.4" strokeLinecap="round" />
        <path d="M17.8 23.4a14.6 14.6 0 0 1 12.4 0" fill="none" stroke="#3fbdb2" strokeWidth="3.4" strokeLinecap="round" />
        <path d="M32.4 24.8a14.6 14.6 0 0 1 5.4 9.4" fill="none" stroke="#f2760a" strokeWidth="3.4" strokeLinecap="round" />
        <path d="M24 35 31.5 24.5" stroke="#ffd35c" strokeWidth="2.8" strokeLinecap="round" />
        <circle cx="24" cy="35" r="3.6" fill="#aeb9c4" stroke="#4a5560" strokeWidth="0.9" />
        <rect x="5" y="35" width="38" height="3" rx="1.5" fill="#141a1f" />
      </g>
    </>
  );
}

/** Downloads (nav promotion, owner 2026-11-09): a bold brand-
 * orange arrow dropping into a steel parts tray — the free
 * shelf's mark in the rail. Drawn in the library's hand: one
 * silhouette per idea, legible at the 20px rail seat. */
function DownloadsArt() {
  return (
    <>
      <defs>
        {shadow("downloads")}
        {lg("ai-downloads-arrow", ["#f78d2e", "#dd6103"])}
        {lg("ai-downloads-tray", ["#8fa1b5", "#54687e"])}
      </defs>
      <g filter="url(#ai-downloads-sh)">
        <polygon
          points="24,33.5 13.8,20.5 20.2,20.5 20.2,6 27.8,6 27.8,20.5 34.2,20.5"
          fill="url(#ai-downloads-arrow)"
          stroke="#9c4a00"
          strokeWidth="0.9"
          strokeLinejoin="round"
        />
        <rect x="7" y="33.5" width="34" height="4" rx="2" fill="url(#ai-downloads-tray)" stroke="#2f3f50" strokeWidth="0.9" />
        <path
          d="M10.5 37.5h27l-2.4 4.9a3 3 0 0 1-2.7 1.9H15.6a3 3 0 0 1-2.7-1.9Z"
          fill="url(#ai-downloads-tray)"
          stroke="#2f3f50"
          strokeWidth="0.9"
          strokeLinejoin="round"
        />
        <circle cx="13" cy="35.5" r="1.1" fill="#22303f" opacity="0.55" />
        <circle cx="35" cy="35.5" r="1.1" fill="#22303f" opacity="0.55" />
      </g>
    </>
  );
}

/* ---------------- the component ---------------- */

const ART: Record<ArtName, () => ReactNode> = {
  home: HomeArt,
  flyers: FlyersArt,
  inventory: InventoryArt,
  parts: PartsArt,
  categories: CategoriesArt,
  people: PeopleArt,
  shared: SharedArt,
  marketplace: MarketplaceArt,
  borrowing: BorrowingArt,
  repairs: RepairsArt,
  dealers: DealersArt,
  claims: ClaimsArt,
  disaster: DisasterArt,
  reports: ReportsArt,
  messages: MessagesArt,
  forum: ForumArt,
  feedback: FeedbackArt,
  wishlist: WishlistArt,
  expansion: ExpansionArt,
  truck: TruckArt,
  support: SupportArt,
  videos: VideosArt,
  settings: SettingsArt,
  money: MoneyArt,
  tag: TagArt,
  warning: WarningArt,
  badge: BadgeArt,
  backup: BackupArt,
  info: InfoArt,
  search: SearchArt,
  adminTickets: AdminTicketsArt,
  adminBug: AdminBugArt,
  adminFeature: AdminFeatureArt,
  adminForum: AdminForumArt,
  adminStats: AdminStatsArt,
  converter: ConverterArt,
  downloads: DownloadsArt,
};


/**
 * One piece of library artwork. `size` is the rendered box in
 * px (the seats run 18–28px; BrandIcon faces run 44–56px; the
 * artwork is drawn bold enough to hold at all of them).
 */
export function ArtIcon({ name, size = 24 }: { name: ArtName; size?: number }) {
  const Art = ART[name];
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <Art />
    </svg>
  );
}
