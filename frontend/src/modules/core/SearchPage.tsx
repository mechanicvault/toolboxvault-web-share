import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState } from "../../components/EmptyState";
import { ArtIcon } from "../../components/ArtIcon";
import { Badge, type BadgeTone } from "../../components/Badge";
import { ItemThumb } from "../../components/ItemThumb";
import { Panel } from "../../components/Panel";
import { Spinner } from "../../components/Spinner";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import { api } from "../../lib/api";
import "./search.css";

interface SearchResultItem {
  id: string;
  kind: string;
  title: string;
  detail: string;
  excerpt: string;
  link: string;
  /** Inventory group only: the item's primary-photo renditions,
   *  or null when the item has no photo (placeholder paints). */
  photo?: {
    thumb_url?: string | null;
    thumb_url_sm?: string | null;
  } | null;
  /** The record's status (busy work #2), resolved server-side:
   *  the module's dictionary key for its own status word + the
   *  pill tone the module gives that state. Null for the kinds
   *  whose records carry no meaningful status. */
  status?: { key: string; tone: BadgeTone } | null;
}

interface SearchGroup {
  key: string;
  total: number;
  results: SearchResultItem[];
}

interface SearchPayload {
  query: string;
  groups: SearchGroup[];
}

/**
 * Global search results (owner spec, 2026-10-25): the header bar
 * searches the user's OWN records everywhere, and the matches land
 * here on one page, grouped by kind of record under its own
 * heading with its total — Inventory, Parts, Wishlist, Dealers,
 * People, and the rest. Every row clicks through to the record
 * itself (the server ships the deep link, same doctrine as the
 * notification click-through). The forums are NOT here — they
 * have their own search on the forum page, by the owner's word.
 *
 * List standard (2026-11-02): under each group heading, a true
 * list — a header row and one row per result, facts in columns.
 * The column set is PER GROUP, derived from what that group's
 * results actually carry: the `detail` fact means something
 * different in each group (an inventory item's brand/model, a
 * person's contact, a claim's insurer…), so its header names
 * that group's fact; groups whose results carry no detail
 * (Wishlist, Dealers, Truck accounts) get no detail column, and
 * the matching-text column appears only when a result in the
 * group actually matched on long text. Long excerpts truncate
 * in-cell — the full text lives on the record's own page.
 *
 * Status column (busy work #2, 2026-11-10): a result whose
 * record HAS a status carries it in the payload — resolved on
 * the server from the record itself — and it renders here as
 * the shared Badge in the module's own words, seated in its own
 * column right after Kind (the record's standing is a headline
 * fact, ahead of the group's secondary detail). The column
 * appears only when a result in the group actually carries a
 * status, on the same conditional-column rule as detail/match.
 */

/**
 * The header-band glyph per group key (owner, 2026-11-04: "each
 * box should have a little icon with the header text"). Each
 * group wears THE ICON OF THE MODULE IT BELONGS TO — the same
 * glyph that module's Home widget carries (modules/core/
 * homeWidgets.tsx), so the results page ties visually to the
 * modules the rows lead to. Keys are the server search families
 * (backend global_search._FAMILIES); the map is generic over
 * group keys, so a parked module's group returning later
 * inherits its icon with no page change. Two judgment calls:
 * `people` has no module of its own (it is the borrowing
 * module's address book), so it wears the people artwork; and any
 * future group without an entry falls back to the categories artwork
 * rather than rendering bare. The glyph is decorative — the
 * group name text sits right beside it.
 */
const GROUP_ICONS: Record<string, ReactNode> = {
  inventory: <ArtIcon name="inventory" size={22} />,
  parts: <ArtIcon name="parts" size={22} />,
  wishlist: <ArtIcon name="wishlist" size={22} />,
  dealers: <ArtIcon name="dealers" size={22} />,
  people: <ArtIcon name="people" size={22} />,
  borrowing: <ArtIcon name="borrowing" size={22} />,
  claims: <ArtIcon name="claims" size={22} />,
  disaster_claims: <ArtIcon name="disaster" size={22} />,
  maintenance: <ArtIcon name="repairs" size={22} />,
  truck_accounts: <ArtIcon name="truck" size={22} />,
  listings: <ArtIcon name="marketplace" size={22} />,
  messages: <ArtIcon name="messages" size={22} />,
  support: <ArtIcon name="support" size={22} />,
  prints: <ArtIcon name="parts" size={22} />,
};

/** The detail column's header per group key — present only for
 *  groups whose server builder fills `detail`. (Listings and
 *  support used to fill it with their raw status value; since
 *  busy work #2 that fact rides the Status column as a pill, so
 *  those groups carry no detail.) */
const DETAIL_HEADERS: Record<string, DictKey> = {
  inventory: "search.col.detail.inventory",
  parts: "search.col.detail.parts",
  people: "search.col.detail.people",
  borrowing: "search.col.detail.borrowing",
  claims: "search.col.detail.claims",
  disaster_claims: "search.col.detail.disaster_claims",
  maintenance: "search.col.detail.maintenance",
  messages: "search.col.detail.messages",
};

function SearchGroupTable({ group }: { group: SearchGroup }) {
  const t = useT();
  const hasStatus = group.results.some((r) => r.status);
  const hasDetail = group.results.some((r) => r.detail);
  const hasExcerpt = group.results.some((r) => r.excerpt);
  const detailHeader = DETAIL_HEADERS[group.key] ?? "search.col.detail";
  const className =
    "tv-search-table" +
    (hasStatus ? " tv-search-table--s" : "") +
    (hasDetail ? " tv-search-table--d" : "") +
    (hasExcerpt ? " tv-search-table--e" : "");
  return (
    <div className="tv-search-tablewrap">
      <div className={className} role="table">
        <div className="tv-search-thead" role="row">
          <span role="columnheader">{t("search.col.title")}</span>
          <span role="columnheader">{t("search.col.kind")}</span>
          {hasStatus && (
            <span role="columnheader">{t("search.col.status")}</span>
          )}
          {hasDetail && <span role="columnheader">{t(detailHeader)}</span>}
          {hasExcerpt && (
            <span role="columnheader">{t("search.col.match")}</span>
          )}
        </div>
        {group.results.map((r) => (
          <Link
            key={`${group.key}-${r.id}`}
            className="tv-search-trow"
            role="row"
            to={r.link}
          >
            <span className="tv-search-cell-title" role="cell">
              {group.key === "inventory" && (
                <span className="tv-thumb-cell--sm">
                  <ItemThumb
                    src={r.photo?.thumb_url_sm || r.photo?.thumb_url || null}
                    name={r.title}
                    aspectRatio="4 / 3"
                  />
                </span>
              )}
              <span className="tv-search-title-text">{r.title}</span>
            </span>
            <span className="tv-search-cell-kind" role="cell">
              {t(`search.kind.${r.kind}` as DictKey)}
            </span>
            {hasStatus && (
              <span
                className="tv-search-cell-status"
                role="cell"
                // A pill whose word outgrows the column ellipsises
                // (the shared Badge rule); the full word rides the
                // hover title, per the site's pill rule.
                title={r.status ? t(r.status.key as DictKey) : undefined}
              >
                {r.status ? (
                  <Badge tone={r.status.tone} dot>
                    {t(r.status.key as DictKey)}
                  </Badge>
                ) : (
                  "—"
                )}
              </span>
            )}
            {hasDetail && (
              <span className="tv-search-cell-detail" role="cell">
                {r.detail || "—"}
              </span>
            )}
            {hasExcerpt && (
              <span className="tv-search-cell-excerpt" role="cell">
                {r.excerpt || "—"}
              </span>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function SearchPage() {
  const t = useT();
  const [searchParams] = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim();
  const [payload, setPayload] = useState<SearchPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!q) {
      setPayload(null);
      setFailed(false);
      return;
    }
    let live = true;
    setPayload(null);
    setFailed(false);
    api<SearchPayload>(`/core/search?q=${encodeURIComponent(q)}`)
      .then((data) => {
        if (live) setPayload(data);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [q]);

  if (!q) {
    return (
      <div className="tv-stack tv-page-narrow">
        <div className="tv-title-row">
          <div>
            <h1>{t("search.title")}</h1>
            <p className="tv-muted">{t("search.intro")}</p>
          </div>
        </div>
        <Panel>
          <EmptyState
            title={t("search.promptTitle")}
            description={t("search.promptBody")}
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="tv-stack tv-page-narrow">
      <div className="tv-title-row">
        <div>
          <h1>{t("search.resultsFor").replace("{q}", q)}</h1>
          <p className="tv-muted">{t("search.intro")}</p>
        </div>
      </div>
      {failed ? (
        <Panel>
          <p className="tv-muted">{t("search.loadFailed")}</p>
        </Panel>
      ) : payload === null ? (
        <Panel>
          <Spinner />
        </Panel>
      ) : payload.groups.length === 0 ? (
        <Panel>
          <EmptyState
            title={t("search.emptyTitle").replace("{q}", q)}
            description={t("search.emptyBody")}
          />
        </Panel>
      ) : (
        payload.groups.map((group) => (
          /* Grouping chrome (owner, 2026-11-03): each category is
           * its own panel with the standard header band carrying
           * the category name + count, so where one category ends
           * and the next begins is unmistakable. The groups, their
           * order, and every row inside are unchanged. */
          <Panel
            key={group.key}
            className="tv-search-group"
            title={
              <>
                <span className="tv-search-group-lead">
                  <span className="tv-search-group-icon" aria-hidden="true">
                    {GROUP_ICONS[group.key] ?? <ArtIcon name="categories" size={22} />}
                  </span>
                  {t(`search.group.${group.key}` as DictKey)}
                </span>{" "}
                <span className="tv-search-group-count">({group.total})</span>
              </>
            }
          >
            {group.total > group.results.length && (
              <p className="tv-muted tv-search-group-note">
                {t("search.showingOf")
                  .replace("{shown}", String(group.results.length))
                  .replace("{total}", String(group.total))}
              </p>
            )}
            <SearchGroupTable group={group} />
          </Panel>
        ))
      )}
    </div>
  );
}
