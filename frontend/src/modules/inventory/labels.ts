/**
 * QR bin labels (blueprint §18): the print surface's shared logic —
 * canonical payload builders, label data shapes (mirroring the
 * backend's /inventory/labels responses), and the physical sheet
 * presets. Pure module: no React, no fetching.
 *
 * Payload contract: an item label's QR encodes the item's canonical
 * URL, `<origin>/inventory/<kind>/<id>` — exactly the path the
 * backend returns as `qr_path` (pinned by tests/test_labels.py).
 * The kind routes are aliases that redirect to the concrete detail
 * pages, so a scan lands a signed-in owner on the item and everyone
 * else on the sign-in page; nothing resolves without a session.
 */

export type LabelKind = "tool" | "battery";

export interface LabelItemData {
  kind: LabelKind;
  id: string;
  name: string;
  brand: string;
  model: string;
  serial_number: string;
  location: string;
  is_set: boolean;
  qr_path: string;
}

export interface LabelSelectionData {
  labels: LabelItemData[];
  skipped: number;
}

export interface LocationLabelData {
  location: string;
  count: number;
}

/** The selection key used end to end (list page → URL → API). */

/** Canonical item path — mirrors the backend's `qr_path` byte for byte. */
export function itemLabelPath(kind: LabelKind, id: string): string {
  return `/inventory/${kind}/${id}`;
}

/** The full QR payload for an item label. */
export function itemQrPayload(origin: string, kind: LabelKind, id: string): string {
  return `${origin}${itemLabelPath(kind, id)}`;
}

/** The full QR payload for a bin (location) label: the inventory
 *  list filtered to that location (the list page honors ?location=). */
export function locationQrPayload(origin: string, location: string): string {
  return `${origin}/inventory?location=${encodeURIComponent(location)}`;
}

/** One physical label-stock preset. All measurements in inches;
 *  `rowsPerSheet: null` = continuous stock (labels flow across
 *  pages in fixed columns instead of a fixed sheet grid). */
export interface LabelPreset {
  id: string;
  name: string;
  blurb: string;
  labelW: number;
  labelH: number;
  columns: number;
  rowsPerSheet: number | null;
  sheetW: number;
  sheetH: number;
  marginTop: number;
  marginLeft: number;
  gapX: number;
  gapY: number;
}

export const LABEL_PRESETS: LabelPreset[] = [
  {
    id: "avery-5160",
    name: "Avery 5160 sheet",
    blurb: "2.625″ × 1″ address labels · 3 × 10 on US Letter",
    labelW: 2.625,
    labelH: 1,
    columns: 3,
    rowsPerSheet: 10,
    sheetW: 8.5,
    sheetH: 11,
    marginTop: 0.5,
    marginLeft: 0.1875,
    gapX: 0.125,
    gapY: 0,
  },
  {
    id: "thermal-2x1",
    name: "2″ × 1″ labels",
    blurb: "Thermal-style roll stock · 2 across, flows across pages",
    labelW: 2,
    labelH: 1,
    columns: 2,
    rowsPerSheet: null,
    sheetW: 4.625,
    sheetH: 11,
    marginTop: 0.25,
    marginLeft: 0.25,
    gapX: 0.125,
    gapY: 0.125,
  },
  {
    id: "bin-4x2",
    name: "Large bin labels 4″ × 2″",
    blurb: "Big bin labels · 2 × 4 on US Letter",
    labelW: 4,
    labelH: 2,
    columns: 2,
    rowsPerSheet: 4,
    sheetW: 8.5,
    sheetH: 11,
    marginTop: 0.5,
    marginLeft: 0.25,
    gapX: 0,
    gapY: 0,
  },
];

export const DEFAULT_ITEM_PRESET = LABEL_PRESETS[0];
export const DEFAULT_LOCATION_PRESET = LABEL_PRESETS[2];

/** Chunk labels into sheets: one chunk per physical sheet, each
 *  holding at most columns × rowsPerSheet labels. Continuous stock
 *  (rowsPerSheet null) yields a single chunk with everything — the
 *  sheet element then sizes to its content and flows across pages. */
export function chunkSheets<T>(items: T[], preset: LabelPreset): T[][] {
  if (preset.rowsPerSheet === null) return items.length ? [items] : [];
  const perSheet = preset.columns * preset.rowsPerSheet;
  const sheets: T[][] = [];
  for (let i = 0; i < items.length; i += perSheet) {
    sheets.push(items.slice(i, i + perSheet));
  }
  return sheets;
}
