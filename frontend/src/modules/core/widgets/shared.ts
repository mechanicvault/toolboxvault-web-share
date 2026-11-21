import {type ReactNode} from "react";
import type {StatTone} from "../../../components/OverviewRow";
import type {
  BlockSettingValue,
  BlockSize,
} from "../../../lib/usePageLayout";
import {activeLocale} from "../../../lib/format";

/**
 * HOME WIDGETS (Home + Header program, owner 2026-10-24): the
 * modules on Home are LIVE WIDGETS now, not description boxes —
 * the phone-home-screen model. One widget per module: a headline
 * number or two, a few live lines read from the MODULE'S OWN
 * endpoints (modules own their data — the widget only reads the
 * same payloads the module's panel already reads), and a button
 * that goes to the module. Widget on/off is a HOME choice (the
 * home layout's widget:<id> blocks), separate from module
 * enablement; a widget only exists for a user while its module
 * is effective for them and serves one of their groups.
 *
 * Catalog gets no widget (it has no surface of its own — it is
 * embedded panels inside Inventory) and ai_assistant gets none
 * while it is inert/unconfigured: nothing live to show, and the
 * rule is no invented content.
 */
/**
 * One structured widget row (widget options Wave 1 framework):
 * a row of fact cells laid out side by side — a claim number,
 * the item, its status — as against the plain-text `lines`.
 * `href` makes the whole row a link (dropped in Edit view,
 * where a box never navigates). Rows render in the widget's
 * interactive layer, above the whole-box cover anchor, so a
 * row link is hit-tested as itself — never shadowed by the
 * box link.
 */
export interface WidgetRow {
  cells: ReactNode[];
  href?: string;
  /** Sample redesign (2026-11-15): a letter tile that leads
   *  the row (the Dealer directory's monograms). */
  monogram?: string;
  /** Sheet row 51 (owner): when the record carries a real
   *  logo, it fills the monogram tile instead of the letter
   *  (the Dealer directory's company logos). */
  monogramImg?: string;
  /** Sample redesign (2026-11-15): a trailing › — the row
   *  reads as a door into its detail (the Repairs claim card). */
  chevron?: boolean;
}

/** One tab inside a widget (sample redesign, 2026-11-15):
 *  the samples switch a widget's list in place — Open claims /
 *  Coming up / Repaired — so the box stays short. A tab carries
 *  its own rows (or groups) and an optional count chip. */
export interface WidgetTab {
  id: string;
  label: string;
  count?: number;
  rows?: WidgetRow[];
  rowsClass?: string;
  header?: ReactNode[];
  rowsVisible?: number;
  groups?: WidgetRowGroup[];
  /** Shown when the tab has no rows (the tab bar still names
   *  the list honestly instead of the widget going blank). */
  emptyText?: string;
  /** Gallery strips inside the tab (Downloads' shelves). */
  strips?: WidgetStrip[];
}

/**
 * One named list inside a widget (widget options Wave 2):
 * Borrowing's lent-out and borrowed-by-me lists are the first
 * tenants. Groups stack at half width and sit side by side at
 * full width, each capped at its own `visible` rows with the
 * rest scrolling inside the group (the Notifications pattern).
 */
export interface WidgetRowGroup {
  label?: string;
  /** Column headings for the group's rows (Sweep B1, 01-F7):
   *  worn at full width like every widget row set's header; at
   *  half width the cells themselves carry the separation. */
  header?: ReactNode[];
  /** Column template class for the group's row set (full width). */
  rowsClass?: string;
  rows: WidgetRow[];
  /** Rows shown before the group scrolls internally. */
  visible?: number;
}

/**
 * What a widget's load is handed (widget options Wave 2): the
 * block's resolved width and options bundle (read through the
 * registry's optBool/optNum helpers — the popover and the
 * loader share the defaults), whether Home is in Edit view
 * (interactive cells stay out of the arrangement surface), and
 * a reload the widget may call after it changes its own data
 * (the truck quick entry posts, then the rows re-read so the
 * balance updates in place).
 */
export interface WidgetLoadCtx {
  size: BlockSize;
  settings: Record<string, BlockSettingValue>;
  editing: boolean;
  reload: () => void;
}

/**
 * One tile in a showcase strip (dashboard-flare lane, owner
 * order 2026-11-09): a thumbnail (or an icon fallback where
 * the record carries no image), a title, an optional small
 * sub-line (a count, a rating), and the tile's own deep link.
 * Strips scroll sideways inside the widget — the rest of the
 * tiles wait off the right edge, the phone-home-screen way.
 */
export interface WidgetStripTile {
  thumb?: string;
  /** A ready-made thumbnail element that replaces the
   *  img/icon pair — the dealers widget seats the directory's
   *  own CompanyLogo here, so a logo that fails to load falls
   *  back to the brand's initial tile exactly as it does on
   *  the Dealers page itself. The frame renders bare (the
   *  node carries its own tile). */
  thumbNode?: ReactNode;
  icon?: ReactNode;
  /** Paint the thumb on a dark tile (white-glyph logos). */
  darkTile?: boolean;
  title: string;
  sub?: string;
  href: string;
}

/** One labeled showcase strip inside a widget: the Downloads
 *  weekly chart, the prints widget's two shelves (new, most
 *  downloaded), the dealer tiles. */
export interface WidgetStrip {
  label?: string;
  tiles: WidgetStripTile[];
}

/** One glanceable stat in a widget's stats grid: a value over
 *  its label, in a uniform grid of identical cells (the
 *  Downloads widget's facts — dashboard-flare lane). */
export interface WidgetStat {
  label: string;
  value: string;
  /** Sample redesign (2026-11-15): the value wears the
   *  accent (Account & Plan's over-limit items count). */
  tone?: "warn" | "good";
}

export interface WidgetData {
  headline?: string;
  lines: string[];
  /** Sample redesign (2026-11-15): the ONE counts line under
   *  the head — bold values with quiet labels, joined by " · "
   *  ("0 due · 2 out of service"). */
  counts?: { value: string; label: string }[];
  /** Sample redesign (2026-11-15): in-widget tabs that switch
   *  the list in place (see WidgetTab). */
  tabs?: WidgetTab[];
  /** Sample redesign (2026-11-15): the stats ride as a left
   *  RAIL beside the rows at full width (Health's "fix these
   *  next" split); at half width they stack above as usual. */
  splitStats?: boolean;
  /** Sample redesign (2026-11-15): the footer actions sit at
   *  the box's right edge (the samples' ghost + primary pair). */
  actionsEnd?: boolean;
  /** Sample redesign (2026-11-15): an alert banner card at the
   *  top of the body (Borrowing's overdue notice). */
  banner?: ReactNode;
  /** Sheet row 48 (2026-11-15): an interactive block rendered
   *  directly under the stat tiles (the truck widget's
   *  this-week payments reveal). Not part of the split rail. */
  afterStats?: ReactNode;
  /**
   * Structured rows + an actions slot (widget options Wave 1
   * framework extension): a widget MAY supply either alongside
   * (or instead of) plain lines. `actions` is real controls —
   * buttons, links — rendered under the content in the same
   * above-the-cover layer as rows, so inner controls win over
   * the whole-box link in real clicks. A widget that supplies
   * only lines renders exactly as it always has.
   */
  rows?: WidgetRow[];
  /** Rows shown before the plain rows list scrolls internally
   *  (widget options Wave 2); absent = the list never caps. */
  rowsVisible?: number;
  /** Column headings for the rows list, worn only at full
   *  width, where the rows take their table shape (Wave 2). */
  header?: ReactNode[];
  /** Per-widget column template for the full-width table
   *  shape: a modifier class on the row set (Wave 2). */
  rowsClass?: string;
  /** Named row groups (Wave 2) — see WidgetRowGroup. */
  groups?: WidgetRowGroup[];
  /** Plain lines that belong AFTER the rows/groups (Wave 2):
   *  Borrowing's waiting/overdue lines keep their reading
   *  order under its lists instead of jumping above them. */
  linesAfter?: string[];
  /** The glanceable stats grid (dashboard-flare lane): uniform
   *  label/value cells above the strips. */
  stats?: WidgetStat[];
  /** Showcase strips (dashboard-flare lane): sideways-
   *  scrolling thumbnail tiles with deep links, rendered
   *  after the lines/stats and before any rows/groups. */
  strips?: WidgetStrip[];
  actions?: ReactNode;
}

export interface WidgetDef {
  icon: ReactNode;
  tone: StatTone;
  /** The go-to button's words: "See the rest" for list modules,
   *  "Open" for the rest. */
  cta: "viewAll" | "open";
  load: (t?: (key: never) => string, ctx?: WidgetLoadCtx) => Promise<WidgetData>;
  /**
   * The widget's door when the module itself has no nav door:
   * support's surface is the Help & Support page (the header ?
   * is its door), so its widget points there instead of at a
   * module nav path.
   */
  path?: string;
  /**
   * The widget starts OFF for users whose saved layout doesn't
   * carry it (the layout resolver's `defaultVisible: false`):
   * a NEW widget joins the picker without rearranging anyone's
   * stored Home (owner follow-up, 2026-11-09 — the 3D Print
   * Files widget). CorePage's module-widget assembly reads this
   * flag; CorePage's registry reads the same flag.
   */
  defaultOff?: boolean;
}

export const count = (n: number): string => n.toLocaleString(activeLocale());

/** Widget line templates (item 19, Deep Audit Round 2): every
 * load() receives the translator from HomeWidget, like the
 * tool_expansion widget already did; the English fallback keeps
 * the load usable from any future caller without one. */
type WT = (key: never) => string;
export const line = (
  t: WT | undefined,
  key: string,
  fallback: string,
  subs: Record<string, string> = {},
): string => {
  let out = t ? t(key as never) : fallback;
  for (const [k, v] of Object.entries(subs)) out = out.replace(`{${k}}`, v);
  return out;
};

/** The face a truck account shows in the widget, from the
 *  viewer's seat: their tab names the company; an account they
 *  hold as dealer names the customer. */
