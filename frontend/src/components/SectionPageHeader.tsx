import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Panel } from "./Panel";

export interface SectionPageFact {
  label: ReactNode;
  value: ReactNode;
  /** Optional door: when set, the whole fact is a link to it
   *  (the Home header stats' doors). The fact keeps the exact
   *  facts treatment — bare label over value on the header
   *  panel, no box; the link only gains the standard highlight
   *  on hover/focus (theme/themes/railsteel-home.css). */
  href?: string;
  /** Alert family (a warning/danger stat with something in
   *  it): the value burns in the danger tone. In the facts
   *  seat the signal is the value's colour, never a box. */
  alert?: boolean;
}

/**
 * One fact in the facts anatomy (label over value), shared by
 * the header's own facts row and by the Home header stats —
 * ONE item definition for the one stat family (widget
 * uniformity lane, 2026-11-10): a plain fact is a dt/dd pair;
 * a fact with a door wraps the same label/value pair in a
 * Link wearing the same register classes.
 */
export function SectionPageFactItem({ fact }: { fact: SectionPageFact }) {
  if (fact.href) {
    return (
      <div className="tv-secpage-fact">
        <Link
          className="tv-fact-link"
          to={fact.href}
          data-alert={fact.alert || undefined}
          aria-label={
            typeof fact.label === "string" && typeof fact.value === "string"
              ? `${fact.label}: ${fact.value}`
              : undefined
          }
        >
          <span className="tv-fact-label">{fact.label}</span>
          <span className="tv-fact-value">{fact.value}</span>
        </Link>
      </div>
    );
  }
  return (
    <div className="tv-secpage-fact">
      <dt className="tv-fact-label">{fact.label}</dt>
      <dd className="tv-fact-value">{fact.value}</dd>
    </div>
  );
}

export interface SectionPageHeaderProps {
  /** Content of the framed thumbnail plate at the header's
   *  left — normally the page's `<ArtIcon name="…" size={96} />`.
   *  The plate is decorative (aria-hidden): the title beside it
   *  names the page. Omit for a header with no plate. */
  thumb?: ReactNode;
  /** The page title, rendered as the header's <h1>. */
  title: ReactNode;
  /** One line under the title (the page's standing subtitle). */
  subtitle?: ReactNode;
  /** Standing facts under the title/subtitle, in the shared
   *  anatomy (stacked uppercase label over a bold value).
   *  Omit or pass an empty list while the facts are unknown —
   *  the facts row renders only when there is something true
   *  to show. */
  facts?: SectionPageFact[];
  /** Extra content seated WITH the facts, inside the header's
   *  main block under the title (and after the facts row when
   *  both exist) — the facts seat itself, not the lower `body`
   *  zone. The Home header stats live here (owner correction
   *  2026-11-10: the stats sit at the top of the header wearing
   *  the facts treatment, never in a separate lower strip).
   *  Most pages pass nothing. */
  factsExtra?: ReactNode;
  /** The header's Actions cell at the top-right — normally the
   *  page's one `SettingsActionsMenu` (tab jumps, plus its
   *  `settingsEntry` when the page has settings; see that
   *  component). The cell renders only when content is passed,
   *  so a page with no commands shows no empty seat. */
  actions?: ReactNode;
  /** Optional toolbar row rendered INSIDE the header panel,
   *  under the title/facts/Actions row, behind a hairline —
   *  for a page whose standing toolbar belongs in the header
   *  bar itself (Inventory's search + filter bar, owner order
   *  2026-11-10: "in the header bar" means inside it, never a
   *  separate panel seated under the header). The kit wraps it
   *  in `.tv-secpage-toolbar`, so pass it only when it will
   *  actually render. Pages that pass nothing render exactly
   *  as before. */
  toolbar?: ReactNode;
  /** Optional body row rendered INSIDE the header panel, under
   *  the title/facts/actions row — content that belongs to the
   *  header bar itself (an at-a-glance strip), as opposed to
   *  `statusStrip`, which lives under the panel. Rendered
   *  bare: the seated content roots its own element in
   *  `.tv-secpage-body` (the shared hairline/spacing) and may
   *  render null, leaving no trace in the header — the seat
   *  for content that can legitimately be absent (the Dealers
   *  truck glance). Most pages pass nothing. (`toolbar` and
   *  `body` coexist by design — reconciliation option B,
   *  2026-11-10: wrapped/always-rendered vs bare/may-be-null
   *  are distinct, honest contracts.) */
  body?: ReactNode;
  /** Optional strip rendered directly under the header panel —
   *  the live-state chips seat (the Truck Accounts pattern).
   *  Most pages pass nothing. */
  statusStrip?: ReactNode;
}

/**
 * The section-page header kit (Main Tab Layout program, Lane 0,
 * 2026-11-09): the ONE header every section page in the main
 * tab layout renders — a Panel holding the thumbnail plate,
 * the title/facts block, and the page's Actions dropdown at
 * the top-right, plus an optional `body` row inside the
 * panel under that row (owner, 2026-11-10: header content
 * rides IN the header bar, not under it). Before the kit,
 * Settings, Reports, Repairs, How-to Videos and Flyers each
 * hand-rolled this anatomy with per-module classes; the kit
 * is that anatomy, shared
 * (styles: `.tv-secpage-*` in theme/surfaces.css).
 *
 * The page renders the shared Steel `Tabs` strip directly
 * below this header, as every section page already does —
 * header, then tabs, then tab content is the layout.
 *
 * Usage contract for the program's page lanes: pass only what
 * the page truly has (no placeholder facts, no empty Actions
 * seat), keep tab state and tab content in the page, and give
 * the Actions menu its Settings entry through
 * `SettingsActionsMenu`'s `settingsEntry` when the page has
 * settings of its own.
 */
export function SectionPageHeader({
  thumb,
  title,
  subtitle,
  facts,
  factsExtra,
  actions,
  toolbar,
  body,
  statusStrip,
}: SectionPageHeaderProps) {
  return (
    <>
      <Panel>
        <div className="tv-secpage-head">
          {thumb ? (
            <div className="tv-secpage-thumb" aria-hidden="true">
              {thumb}
            </div>
          ) : null}
          <div className="tv-secpage-main">
            <h1 className="tv-secpage-title">{title}</h1>
            {subtitle ? <p className="tv-secpage-subtitle">{subtitle}</p> : null}
            {facts && facts.length > 0 ? (
              <dl className="tv-secpage-facts">
                {facts.map((fact, i) => (
                  <SectionPageFactItem
                    key={typeof fact.label === "string" ? fact.label : i}
                    fact={fact}
                  />
                ))}
              </dl>
            ) : null}
            {factsExtra}
          </div>
          {actions ? <div className="tv-secpage-actions">{actions}</div> : null}
        </div>
        {toolbar ? <div className="tv-secpage-toolbar">{toolbar}</div> : null}
        {body}
      </Panel>
      {statusStrip}
    </>
  );
}
