/**
 * Shared stroke glyphs — the SearchBar pattern: inline SVG,
 * `stroke="currentColor"`, so the theme/accent layer owns the color.
 * 24-unit grid, round caps/joins. No emoji, no icon font.
 */
import type { ReactNode } from "react";

function Glyph({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

/** Calendar — the DatePicker trigger glyph (date-pickers
 * site-wide, 2026-11-04). */
export function CalendarIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18" />
      <path d="M8 3v4" />
      <path d="M16 3v4" />
    </Glyph>
  );
}

/** Bell — the header notifications door (Home + Header program). */
export function BellIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </Glyph>
  );
}

/** Circled question mark — the Help & Support door. */
export function HelpIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </Glyph>
  );
}

/** Speech bubble — conversations / messages. */
export function ChatIcon() {
  return (
    <Glyph>
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </Glyph>
  );
}

/** Shopping cart — Tool Expansion's badge and doors (known
 *  addons you can still pick up for what you own). */

/** Cube / package — inventory items. */
export function BoxIcon() {
  return (
    <Glyph>
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <path d="M3.29 7 12 12l8.71-5" />
      <path d="M12 22V12" />
    </Glyph>
  );
}

/** Coin with a dollar mark — money totals. */
export function CoinIcon() {
  return (
    <Glyph>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6.5v11" />
      <path d="M15.2 8.4c-.55-1-1.7-1.6-3.2-1.6-1.9 0-3.3 1.05-3.3 2.45 0 3.55 6.6 2.3 6.6 5.05 0 1.4-1.45 2.5-3.3 2.5-1.5 0-2.7-.65-3.25-1.7" />
    </Glyph>
  );
}

/** Price tag — replacement cost. */
export function TagIcon() {
  return (
    <Glyph>
      <path d="M20.59 13.41 11 3.83A2 2 0 0 0 9.59 3.24H4a1 1 0 0 0-1 1v5.59c0 .53.21 1.04.59 1.41l9.58 9.59a2 2 0 0 0 2.83 0l4.59-4.59a2 2 0 0 0 0-2.83z" />
      <circle cx="7.5" cy="7.5" r="0.6" fill="currentColor" />
    </Glyph>
  );
}

/** Four squares — categories / groupings. */
export function GridIcon() {
  return (
    <Glyph>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.2" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.2" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.2" />
    </Glyph>
  );
}

/** House — the home / dashboard module. */
export function HomeIcon() {
  return (
    <Glyph>
      <path d="M3 10.8 12 3l9 7.8" />
      <path d="M5.2 9.4V21h13.6V9.4" />
      <path d="M9.6 21v-6h4.8v6" />
    </Glyph>
  );
}

/** Warning triangle with an exclamation mark — site notices. */

/** Two opposing arrows — an item goes out, an item comes back:
 *  borrowing / check-out. */
export function SwapIcon() {
  return (
    <Glyph>
      <path d="M4 7h13" />
      <path d="m13.5 3.5 3.5 3.5-3.5 3.5" />
      <path d="M20 17H7" />
      <path d="m10.5 13.5-3.5 3.5 3.5 3.5" />
    </Glyph>
  );
}

/** Bar chart — reports: the vault measured, grouped and totaled. */

/** Two people — tools shared between people. */
export function UsersIcon() {
  return (
    <Glyph>
      <circle cx="9" cy="8" r="3.4" />
      <path d="M3.4 20c.6-3.1 2.8-4.9 5.6-4.9s5 1.8 5.6 4.9" />
      <circle cx="17.3" cy="9" r="2.6" />
      <path d="M16.2 15.3c2.2.3 3.8 1.8 4.3 4" />
    </Glyph>
  );
}

/** One person — the header user-menu door (owner, 2026-11-03:
 * the account menu's trigger moved out of the rail to a person
 * icon beside the Help ? in the header cluster). */
export function PersonIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M5 20c.8-3.6 3.6-5.4 7-5.4s6.2 1.8 7 5.4" />
    </Glyph>
  );
}

/** Briefcase — work / jobs / a carried kit. */

/** Badge with a check — verified / covered. */

/** Cloud with an up arrow — uploads / backups. */

/** Circle with an i — information / empty-state notices. */

/** Stacked layers — modules / collections. */
export function LayersIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="m12 3.5 9 4.7-9 4.7-9-4.7z" />
      <path d="m3.6 12.7 8.4 4.4 8.4-4.4" />
      <path d="m3.6 17 8.4 4.4L20.4 17" />
    </Glyph>
  );
}

/** Circular arrow — refresh / sync / history. */
export function RefreshIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 3.8v4h-4" />
    </Glyph>
  );
}

/** Magnifier — search. */
/** Map pin — the item header's location line (record pages). */
export function PinIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </Glyph>
  );
}

export function SearchIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </Glyph>
  );
}

/** Share nodes — sharing between people. */

/** Sliders — per-block options (the Home chrome bar's options
 *  control, widget options Wave 1). Two rails, two knobs: the
 *  universal "this box has settings" glyph. */
export function SlidersIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M3.5 7h9" />
      <path d="M17.5 7h3" />
      <circle cx="14.5" cy="7" r="2.1" />
      <path d="M3.5 17h3" />
      <path d="M11.5 17h9" />
      <circle cx="8.5" cy="17" r="2.1" />
    </Glyph>
  );
}

/** Push-pin — the rail pin's glyph (widget options Wave 1):
 *  a thumbtack, grip on top, skirt, point down. NOT the map
 *  pin (PinIcon above is locations). Since the 2026-11-05
 *  move it renders in the header gear popup's pin row; when
 *  the rail is pinned the row fills this glyph with the
 *  accent (see the pin-row rules in surfaces.css). */
export function PushPinIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M9.5 3h5v5h-5z" />
      <path d="M9.5 8c-1.6 1.3-2.8 2.8-3.2 4.7h11.4c-.4-1.9-1.6-3.4-3.2-4.7" />
      <path d="M12 12.7V21" />
    </Glyph>
  );
}

/** Star — forum favorites (widget options Wave 3): an outline
 *  star at rest; a pressed toggle fills it with the accent
 *  (the .tv-fav-btn rules in forum.css, the rail pin's trick). */
export function StarIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M12 3.6l2.55 5.17 5.7.83-4.12 4.02.97 5.68L12 16.66l-5.1 2.64.97-5.68L3.75 9.6l5.7-.83z" />
    </Glyph>
  );
}

/** Chevron left — the page navigation bar's back arrow. */
export function ChevronLeftIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M14.5 5.5 8 12l6.5 6.5" />
    </Glyph>
  );
}

/** Chevron right — the page navigation bar's forward arrow. */
export function ChevronRightIcon({ size }: { size?: number }) {
  return (
    <Glyph size={size}>
      <path d="M9.5 5.5 16 12l-6.5 6.5" />
    </Glyph>
  );
}

/** Shield with a check — protection / insurance cover. */

/** Document page with a folded corner — the generic file tile
 *  (documents icon grid, 2026-11-04: PDF / Word / text / other
 *  files all read as a document). */

/** Picture frame (mountains + sun) — an image file's tile. */

/** Plain sheet of ruled lines, no folded corner — a text
 *  file's tile (distinct from the document glyph: a text file
 *  is a bare page of lines, not a formatted document). */

/** Table grid — a spreadsheet file's tile. */
