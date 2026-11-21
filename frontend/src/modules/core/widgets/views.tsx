import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { Panel, QuietSkeleton } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { AlertPill, useAlertCounts } from "../../../lib/alertCounts";
import type {
  BlockSettingValue,
  BlockSize,
} from "../../../lib/usePageLayout";
import type { WidgetRow, WidgetTab, WidgetLoadCtx, WidgetStrip, WidgetStat, WidgetData } from "./shared";
import { HOME_WIDGETS } from "./index";

/** Whether a loaded widget has anything at all to show —
 *  lines, structured rows, row groups, trailing lines, or an
 *  actions slot (a headline alone is not content: it never
 *  has been). */
function hasWidgetContent(data: WidgetData): boolean {
  return (
    data.lines.length > 0 ||
    (data.counts?.length ?? 0) > 0 ||
    (data.tabs?.length ?? 0) > 0 ||
    (data.rows?.length ?? 0) > 0 ||
    (data.groups?.length ?? 0) > 0 ||
    (data.linesAfter?.length ?? 0) > 0 ||
    (data.stats?.length ?? 0) > 0 ||
    (data.strips?.length ?? 0) > 0 ||
    data.banner != null ||
    data.actions != null
  );
}

/**
 * The stats grid (dashboard-flare lane): identical cells in a
 * uniform grid, wearing the header facts treatment (widget
 * uniformity lane, 2026-11-10; register corrected by fix 5,
 * 2026-11-11): the label rides on top in small caps, the
 * value below it, left-aligned as one unit — the facts
 * register the Header Studio's stage facts wear
 * (.tv-fact-label / .tv-fact-value, seated for a cell by
 * .tv-widget-stat-label / .tv-widget-stat-value in
 * theme/widget-kit.css) — so a widget's headline facts read
 * at a glance and line up with the header facts above them
 * and with every other widget.
 */
function WidgetStatsView({
  stats,
  wide = false,
}: {
  stats: WidgetStat[];
  wide?: boolean;
}) {
  return (
    <div
      className={
        wide ? "tv-widget-stats tv-widget-stats--wide" : "tv-widget-stats"
      }
      // Sheet rows 53/54 (owner): a widget's stat boxes ride
      // ALL on one row — the grid's column count follows the
      // stat count (widget-kit.css [data-cols] rules), never
      // a fixed 2-up that drops the third box to a second
      // row at half width.
      data-cols={Math.min(stats.length, 5)}
    >
      {stats.map((stat, i) => (
        <div key={i} className="tv-widget-stat">
          <span className="tv-widget-stat-label">{stat.label}</span>
          <span
            className="tv-widget-stat-value"
            data-tone={stat.tone}
          >
            {stat.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * One showcase strip (dashboard-flare lane): tiles in a
 * sideways-scrolling row — the visible few, the rest a scroll
 * away. Tiles render in the widget's interactive layer, above
 * the whole-box cover, and go inert in Edit view like every
 * other inner link.
 */
function WidgetStripView({
  strip,
  editing,
}: {
  strip: WidgetStrip;
  editing: boolean;
}) {
  return (
    <div className="tv-widget-strip-wrap">
      {strip.label && (
        <div className="tv-widget-group-label">{strip.label}</div>
      )}
      <div className="tv-widget-strip">
        {strip.tiles.map((tile, i) => {
          const body = (
            <>
              <span
                className="tv-widget-tile-thumb"
                data-dark={tile.darkTile || undefined}
                data-bare={tile.thumbNode ? true : undefined}
                aria-hidden="true"
              >
                {tile.thumbNode ??
                  (tile.thumb ? (
                    <img src={tile.thumb} alt="" loading="lazy" />
                  ) : (
                    tile.icon
                  ))}
              </span>
              <span className="tv-widget-tile-title">{tile.title}</span>
              {tile.sub && (
                <span className="tv-widget-tile-sub">{tile.sub}</span>
              )}
            </>
          );
          return editing ? (
            <div key={i} className="tv-widget-tile">
              {body}
            </div>
          ) : (
            <Link key={i} to={tile.href} className="tv-widget-tile">
              {body}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

/**
 * One widget row set (widget options Waves 1–2): the column
 * headings (full width only, where the rows take their table
 * shape) over the rows themselves. The rows list caps at
 * `visible` rows when the loader asks — the rest scroll
 * inside the box, the Notifications pattern. Rows render in
 * the widget's interactive layer, above the whole-box cover;
 * a row's href drops in Edit view, where a box never
 * navigates.
 */
function WidgetRowsView({
  rows,
  visible,
  header,
  rowsClass,
  size,
  editing,
}: {
  rows: WidgetRow[];
  visible?: number;
  header?: ReactNode[];
  rowsClass?: string;
  size: BlockSize;
  editing: boolean;
}) {
  const capped = visible != null && rows.length > visible;
  return (
    <div
      className={["tv-widget-rowset", rowsClass ?? ""].filter(Boolean).join(" ")}
      data-size={size}
    >
      {header && size === "full" && (
        <div className="tv-widget-row tv-widget-row--head" aria-hidden="true">
          {header.map((cell, j) => (
            <span key={j} className="tv-widget-cell">
              {cell}
            </span>
          ))}
        </div>
      )}
      <div
        className={["tv-widget-rows", capped ? "tv-widget-rows--capped" : ""]
          .filter(Boolean)
          .join(" ")}
        data-visible={capped ? visible : undefined}
      >
        {rows.map((row, i) => {
          const inner = (
            <>
              {(row.monogram || row.monogramImg) && (
                <span className="tv-widget-monogram" aria-hidden="true">
                  {row.monogramImg ? (
                    <img
                      className="tv-widget-monogram-img"
                      src={row.monogramImg}
                      alt=""
                    />
                  ) : (
                    row.monogram
                  )}
                </span>
              )}
              {row.cells.map((cell, j) => (
                <span key={j} className="tv-widget-cell">
                  {cell}
                </span>
              ))}
              {row.chevron && (
                <span className="tv-widget-chevron" aria-hidden="true">
                  ›
                </span>
              )}
            </>
          );
          return row.href && !editing ? (
            <Link
              key={i}
              to={row.href}
              className="tv-widget-row tv-widget-row--link"
            >
              {inner}
            </Link>
          ) : (
            <div key={i} className="tv-widget-row">
              {inner}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The in-widget tab switch (sample redesign, 2026-11-15):
 *  a segmented bar — the active tab outlined, wearing its
 *  count chip — and the active tab's list under it. One list
 *  shows at a time, so the box stays short. In Edit view the
 *  bar renders inert like every inner control. */
function WidgetTabsView({
  tabs,
  size,
  editing,
}: {
  tabs: WidgetTab[];
  size: BlockSize;
  editing: boolean;
}) {
  const [activeId, setActiveId] = useState<string>(tabs[0]?.id ?? "");
  const tab = tabs.find((x) => x.id === activeId) ?? tabs[0];
  if (!tab) return null;
  return (
    <div className="tv-widget-tabs-wrap">
      <div className="tv-widget-tabs" role="tablist">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            role="tab"
            aria-selected={tb.id === tab.id}
            className="tv-widget-tab"
            data-active={tb.id === tab.id ? "true" : undefined}
            disabled={editing}
            onClick={() => setActiveId(tb.id)}
          >
            {tb.label}
            {tb.count != null && (
              <span className="tv-widget-tab-count">{tb.count}</span>
            )}
          </button>
        ))}
      </div>
      {(tab.strips?.length ?? 0) > 0 &&
        tab.strips!.map((strip, si) => (
          <WidgetStripView key={si} strip={strip} editing={editing} />
        ))}
      {(tab.rows?.length ?? 0) > 0 && (
        <WidgetRowsView
          rows={tab.rows!}
          visible={tab.rowsVisible}
          header={tab.header}
          rowsClass={tab.rowsClass}
          size={size}
          editing={editing}
        />
      )}
      {(tab.groups?.length ?? 0) > 0 &&
        tab.groups!.map((group, gi) => (
          <div key={gi} className="tv-widget-group">
            {group.label && (
              <div className="tv-widget-group-label">{group.label}</div>
            )}
            <WidgetRowsView
              rows={group.rows}
              visible={group.visible}
              header={group.header}
              rowsClass={group.rowsClass}
              size={size}
              editing={editing}
            />
          </div>
        ))}
      {(tab.rows?.length ?? 0) === 0 &&
        (tab.groups?.length ?? 0) === 0 &&
        (tab.strips?.length ?? 0) === 0 &&
        tab.emptyText && (
          <p className="tv-widget-tab-empty">{tab.emptyText}</p>
        )}
    </div>
  );
}

export function HomeWidget({
  moduleId,
  title,
  path,
  editing = false,
  size,
  settings,
  bare = false,
  onContent,
}: {
  moduleId: string;
  title: string;
  path: string;
  /** Home Edit view: the box must NEVER navigate while
   *  customizing (owner 2026-11-02) — the CTA renders as an
   *  inert span with the button's face, the Overview stat
   *  hrefs drop in their edit rendering the same way. */
  editing?: boolean;
  /** Framework plumbing (widget options Wave 1): the block's
   *  resolved grid width and its options bundle, resolved by
   *  the layout and handed down so the content waves can read
   *  their options without re-plumbing CorePage. Wave 2's
   *  named four read both, through the load context below. */
  size?: BlockSize;
  settings?: Record<string, BlockSettingValue>;
  /** Custom-widget composition (Lane 2): render ONLY the
   *  sections — no Panel, no head — because the composite
   *  box carries its own. An empty load renders nothing at
   *  all (the composite decides the box's empty state), and
   *  `onContent` reports whether anything rendered so the
   *  composite can tell. Standalone renders are untouched. */
  bare?: boolean;
  onContent?: (hasContent: boolean) => void;
}) {
  const t = useT();
  // Urgency flag (sheet row 62): unread movement in this
  // widget's module puts the red count pill on its header
  // banner, beside the flag title.
  const alertCounts = useAlertCounts();
  const def = HOME_WIDGETS[moduleId];
  const [data, setData] = useState<WidgetData | null>(null);
  const [failed, setFailed] = useState(false);
  // A widget may ask for its own reload after it changes its
  // data (the truck quick entry posts, then the rows re-read
  // so the balances update in place — no skeleton flash: the
  // old data stays up until the fresh load lands).
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  const settingsKey = JSON.stringify(settings ?? {});
  const onContentRef = useRef(onContent);
  onContentRef.current = onContent;

  useEffect(() => {
    if (!def) return;
    let live = true;
    const ctx: WidgetLoadCtx = {
      size: size ?? "half",
      settings: settings ?? {},
      editing,
      reload,
    };
    def
      .load(t as never, ctx)
      .then((d) => {
        if (live) {
          setData(d);
          onContentRef.current?.(hasWidgetContent(d));
        }
      })
      .catch(() => {
        if (live) {
          setFailed(true);
          // The failure line itself renders — the body is not
          // "empty" for the composite's accounting.
          onContentRef.current?.(true);
        }
      });
    return () => {
      live = false;
    };
    // The load re-runs when the block's width or options
    // change — in Edit view the widget behind the popover
    // reshapes live, the design's promise; at rest, after a
    // save. `settings` itself is read through settingsKey
    // (its identity changes with every layout render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [def, tick, size, settingsKey, editing]);

  if (!def) return null;
  // The sections under the head — one computation shared by
  // the standalone render (Panel + head below) and the bare
  // render a custom-widget composite asks for (sections only,
  // and nothing at all when the load came back empty: the
  // composite owns the box's empty state).
  const body = failed ? (
    <p className="tv-muted">{t("home.widgetLoadFailed")}</p>
  ) : data === null ? (
    <QuietSkeleton lines={2} />
  ) : !hasWidgetContent(data) ? (
    bare ? null : <p className="tv-muted">{t("home.widgetEmpty")}</p>
  ) : (
    <>
          {(data.headline || data.lines.length > 0) && (
            <div className="tv-widget-lines">
              {data.headline && <p className="tv-widget-headline">{data.headline}</p>}
              {data.lines.map((line, i) => (
                <p key={i} className="tv-widget-line">
                  {line}
                </p>
              ))}
            </div>
          )}
          {data.banner != null && (
            <div className="tv-widget-banner">{data.banner}</div>
          )}
          {(data.counts?.length ?? 0) > 0 && (
            <p className="tv-widget-counts">
              {data.counts!.map((c, i) => (
                <span key={i} className="tv-widget-count">
                  {i > 0 && <span className="tv-widget-count-sep">·</span>}
                  <strong>{c.value}</strong> {c.label}
                </span>
              ))}
            </p>
          )}
          {(() => {
            const lists = (
              <>
                {(data.tabs?.length ?? 0) > 0 && (
                  <WidgetTabsView
                    tabs={data.tabs!}
                    size={size ?? "half"}
                    editing={editing}
                  />
                )}
                {(data.rows?.length ?? 0) > 0 && (
                  <WidgetRowsView
                    rows={data.rows!}
                    visible={data.rowsVisible}
                    header={data.header}
                    rowsClass={data.rowsClass}
                    size={size ?? "half"}
                    editing={editing}
                  />
                )}
                {(data.groups?.length ?? 0) > 0 && (
                  <div
                    className="tv-widget-groups"
                    data-side={
                      (size ?? "half") === "full" && data.groups!.length > 1
                        ? "true"
                        : undefined
                    }
                  >
                    {data.groups!.map((group, gi) => (
                      <div key={gi} className="tv-widget-group">
                        {group.label && (
                          <div className="tv-widget-group-label">{group.label}</div>
                        )}
                        <WidgetRowsView
                          rows={group.rows}
                          visible={group.visible}
                          header={group.header}
                          rowsClass={group.rowsClass}
                          size={size ?? "half"}
                          editing={editing}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            );
            const statsNode = (data.stats?.length ?? 0) > 0 && (
              <WidgetStatsView
                stats={data.stats!}
                wide={(size ?? "half") === "full"}
              />
            );
            if (data.splitStats && (size ?? "half") === "full" && statsNode) {
              return (
                <>
                  <div className="tv-widget-split">
                    <div className="tv-widget-split-rail">{statsNode}</div>
                    <div className="tv-widget-split-main">{lists}</div>
                  </div>
                  {(data.strips?.length ?? 0) > 0 &&
                    data.strips!.map((strip, si) => (
                      <WidgetStripView key={si} strip={strip} editing={editing} />
                    ))}
                </>
              );
            }
            return (
              <>
                {statsNode}
                {data.afterStats}
                {(data.strips?.length ?? 0) > 0 &&
                  data.strips!.map((strip, si) => (
                    <WidgetStripView key={si} strip={strip} editing={editing} />
                  ))}
                {lists}
              </>
            );
          })()}
          {(data.linesAfter?.length ?? 0) > 0 && (
            <div className="tv-widget-lines">
              {data.linesAfter!.map((lineText, i) => (
                <p key={i} className="tv-widget-line">
                  {lineText}
                </p>
              ))}
            </div>
          )}
          {/* The actions slot renders only at rest: in Edit
           *  view the box is being arranged, so its controls go
           *  inert like the CTA and the row links above. */}
          {data.actions != null && !editing && (
            <div
              className={
                data.actionsEnd
                  ? "tv-widget-actions tv-widget-actions--end"
                  : "tv-widget-actions"
              }
            >
              {data.actions}
            </div>
          )}
    </>
  );
  if (bare) return body;
  return (
    <Panel className="tv-home-widget">
      {/* The whole-box cover link is RETIRED (dashboard redesign
       * 2026-11-10, design §4.2.3): the doors are honest and
       * separate — the title is a real link to the module, rows
       * keep their own links, and the box's ⛶/⋯ chrome never
       * fights a cover for the click. The head's "Open →" /
       * "View all →" button is ALSO retired (Ryan, 2026-11-10
       * 17:29): widgets don't need it — the title carries the
       * door. In the retired Edit view the doors rendered
       * inert; that mode no longer exists — the shell always
       * renders live — but the `editing` prop keeps its old
       * neutered rendering for any future caller. */}
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone={def.tone} aria-hidden="true">
          {def.icon}
        </span>
        <h3 className="tv-widget-title">
          {editing ? (
            title
          ) : (
            <Link to={path} className="tv-widget-title-link">
              {title}
            </Link>
          )}
        </h3>
        <AlertPill count={alertCounts[moduleId] ?? 0} />
      </div>
      {body}
    </Panel>
  );
}
