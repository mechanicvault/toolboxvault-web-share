import { useCallback, useEffect, useState } from "react";
import "./tool-expansion.css";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import {
  Alert,
  Button,
  EmptyState,
  Panel,
  SectionPageHeader,
  Spinner,
  Tabs,
  type SectionPageFact,
  type TabItem,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { getArchivedExpansions, getExpansions } from "./api";
import { ArchivedRow, SuggestionRow } from "./components";
import type {
  ArchivedExpansions,
  ExpansionSuggestions,
} from "./types";

/**
 * Tool Expansion (owner spec 2026-10-25): known addons for the
 * tools and sets you already own, learned by matching model
 * numbers across the community's sets. Every suggestion is
 * grouped under YOUR item it expands; the "Expands your …" line
 * is the door to your own item page. Nothing about the users a
 * suggestion was learned from exists in the payload — a
 * suggestion is a name and a model number, full stop.
 *
 * Main tab layout (program lane 5, 2026-11-10): the kit header
 * (SectionPageHeader) + Steel tabs in Ryan's order — How it
 * works (the explainer) · Matches · Archived matches. The
 * Matches tab is the page this has always been, unchanged: the
 * same suggestion engine, the same per-item Panels and rows.
 * "Remove for me" is now MOVE TO ARCHIVED MATCHES over the same
 * dismissal ledger, and the Archived tab reads that ledger back
 * (GET /tool-expansion/archived) with bring-back (un-archive) —
 * the Report ledger stays its own separate thing and never
 * enters the archive.
 *
 * `?kind=&id=` (from the inventory badge / the item page) scopes
 * the Matches tab to one item and lands there directly; a chip
 * at the top clears back to all. `#matches` / `#archived`
 * deep-link the tabs.
 *
 * The page owns no settings of its own (conformance map — the
 * only expansion-adjacent switch is the catalog-contribution
 * toggle in Settings → Sharing), so the Actions menu — the
 * three tab jumps — carries NO Settings entry (recorded n/a).
 */

/** The page's three tabs (Ryan's spec, 2026-11-09). */
type ExpansionTabId = "how" | "matches" | "archived";

/** Deep links pick the opening tab — a scoped arrival
 *  (?kind=&id=) lands on Matches, #matches / #archived name
 *  their tabs. Anything else opens on the explainer, the
 *  page's main tab. */
function tabFromHash(hash: string): ExpansionTabId {
  const raw = hash.replace(/^#/, "");
  if (raw === "matches" || raw === "archived") return raw;
  return "how";
}

/** The explainer tab (new in lane 5): what this page does for
 *  the user, what they can do with a match, and how reporting
 *  differs from archiving — said plainly, with the door to the
 *  matches. */
function ExplainerTab({ onGo }: { onGo: (tab: ExpansionTabId) => void }) {
  const t = useT();
  const sections = [
    { title: t("toolExpansion.how.whatTitle"), body: t("toolExpansion.how.whatBody") },
    { title: t("toolExpansion.how.actTitle"), body: t("toolExpansion.how.actBody") },
    { title: t("toolExpansion.how.reportTitle"), body: t("toolExpansion.how.reportBody") },
  ];
  return (
    <Panel title={t("toolExpansion.tab.how")} variant="plate">
      <div className="tv-exp-how">
        {sections.map((s) => (
          <div key={s.title}>
            <p className="tv-exp-how-title">{s.title}</p>
            <p className="tv-exp-how-body">{s.body}</p>
          </div>
        ))}
        <div className="tv-exp-how-doors">
          <Button type="button" onClick={() => onGo("matches")}>
            {t("toolExpansion.how.seeMatches")}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

/** The Archived matches tab body: the viewer's own dismissal
 *  ledger as a TRUE list — Suggested piece · Model # · Expands
 *  · Archived · Bring back. Fetches on mount and after every
 *  change (tab content unmounts when another tab is active, so
 *  returning here always re-reads; the page's rev also feeds
 *  in so an archive made on the Matches tab shows here). */
function ArchivedBody({
  rev,
  onChanged,
}: {
  rev: number;
  onChanged: () => void;
}) {
  const t = useT();
  const [data, setData] = useState<ArchivedExpansions | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getArchivedExpansions()
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : t("toolExpansion.archivedLoadFailed"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [rev, t]);

  if (error) return <Alert tone="danger">{error}</Alert>;
  if (data === null) {
    return (
      <p className="tv-exp-loading">
        <Spinner size="sm" /> {t("toolExpansion.loading")}
      </p>
    );
  }
  if (data.entries.length === 0) {
    return (
      <Panel>
        <EmptyState
          title={t("toolExpansion.archivedEmptyTitle")}
          description={t("toolExpansion.archivedEmptyBody")}
        />
      </Panel>
    );
  }
  return (
    <Panel className="tv-exp-panel">
      <p className="tv-exp-arch-intro">{t("toolExpansion.archivedBody")}</p>
      <div className="tv-ix-table" role="table">
        <div className="tv-ix-thead tv-exp-arch-row" role="row">
          <span role="columnheader">{t("toolExpansion.col.suggestedPiece")}</span>
          <span role="columnheader">{t("toolExpansion.col.modelNumber")}</span>
          <span role="columnheader">{t("toolExpansion.col.expands")}</span>
          <span role="columnheader">{t("toolExpansion.col.archivedOn")}</span>
          <span aria-hidden="true" />
        </div>
        {data.entries.map((entry) => (
          <ArchivedRow
            key={`${entry.anchor_kind}:${entry.anchor_id}:${entry.suggested_model}`}
            entry={entry}
            onChanged={onChanged}
          />
        ))}
      </div>
    </Panel>
  );
}

export default function ToolExpansionPage() {
  const t = useT();
  const { hash } = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const kindParam = searchParams.get("kind");
  const idParam = searchParams.get("id");
  const scope =
    (kindParam === "tool" || kindParam === "battery") && idParam
      ? { kind: kindParam as "tool" | "battery", id: idParam }
      : null;

  const [tab, setTab] = useState<ExpansionTabId>(() =>
    scope ? "matches" : tabFromHash(window.location.hash),
  );
  const [data, setData] = useState<ExpansionSuggestions | null>(null);
  const [archivedCount, setArchivedCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0);

  // A hash change while the page stays mounted (an in-app link)
  // lands on its tab too — the Lane 1 hash-follow discipline.
  // Only the two named targets are followed; an unknown hash
  // never yanks the reader back to the explainer.
  useEffect(() => {
    const wanted = tabFromHash(hash);
    if (wanted !== "how") setTab(wanted);
  }, [hash]);

  const refresh = useCallback(() => {
    getExpansions(scope ?? undefined)
      .then(setData)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : t("toolExpansion.loadFailed"),
        ),
      );
    getArchivedExpansions()
      .then((payload) => setArchivedCount(payload.total))
      .catch(() => {
        /* the header fact just stays stale; the tab reports its own errors */
      });
    setRev((r) => r + 1);
    // scope identity is derived from the URL params each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kindParam, idParam]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const scopedItem = scope ? (data?.groups[0]?.item ?? null) : null;

  const tabLabel = (id: ExpansionTabId): string =>
    id === "how"
      ? t("toolExpansion.tab.how")
      : id === "matches"
        ? t("toolExpansion.tab.matches")
        : t("toolExpansion.tab.archived");

  // Header facts (kit anatomy): the two tabs' counts, carried
  // as standing facts once the reads land — nothing true to
  // show before that.
  const facts: SectionPageFact[] | undefined =
    data !== null
      ? [
          { label: t("toolExpansion.fact.matches"), value: data.total },
          ...(archivedCount !== null
            ? [{ label: t("toolExpansion.fact.archived"), value: archivedCount }]
            : []),
        ]
      : undefined;

  const matchesTab = (
    <div className="tv-exp-tabgrid">
      {scope && (
        <div className="tv-exp-scope">
          <span>
            {scopedItem
              ? t("toolExpansion.scopedTo").replace("{name}", scopedItem.name)
              : t("toolExpansion.scopedGeneric")}
          </span>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setSearchParams({})}
          >
            {t("toolExpansion.showAll")}
          </Button>
        </div>
      )}

      {data === null ? (
        <p className="tv-exp-loading">
          <Spinner size="sm" /> {t("toolExpansion.loading")}
        </p>
      ) : data.total === 0 ? (
        <Panel>
          <EmptyState
            title={t("toolExpansion.emptyTitle")}
            description={t("toolExpansion.emptyBody")}
          />
        </Panel>
      ) : (
        data.groups.map((group) => (
          <Panel key={`${group.item.kind}:${group.item.id}`} className="tv-exp-panel">
            <p className="tv-exp-expands">
              {t("toolExpansion.expandsYour")}{" "}
              <Link
                className="tv-ix-link"
                to={
                  group.item.kind === "battery"
                    ? `/inventory/batteries/${group.item.id}`
                    : `/inventory/${group.item.id}`
                }
              >
                {group.item.name}
              </Link>
            </p>
            {/* List-standard wave 6 (2026-11-02): the group panel
                names the owned item; inside it the suggestions
                are a TRUE list — one suggestion per row under a
                header row, Suggested piece · Model # · Actions
                in their own columns. */}
            <div className="tv-ix-table" role="table">
              <div className="tv-ix-thead" role="row">
                <span role="columnheader">{t("toolExpansion.col.suggestedPiece")}</span>
                <span role="columnheader">{t("toolExpansion.col.modelNumber")}</span>
                <span aria-hidden="true" />
              </div>
              {group.suggestions.map((suggestion) => (
                <SuggestionRow
                  key={suggestion.suggested_model}
                  item={group.item}
                  suggestion={suggestion}
                  onChanged={refresh}
                />
              ))}
            </div>
          </Panel>
        ))
      )}
    </div>
  );

  const tabs: TabItem[] = [
    {
      id: "how",
      label: tabLabel("how"),
      content: <ExplainerTab onGo={setTab} />,
    },
    { id: "matches", label: tabLabel("matches"), content: matchesTab },
    {
      id: "archived",
      label: tabLabel("archived"),
      content: <ArchivedBody rev={rev} onChanged={refresh} />,
    },
  ];

  return (
    <RequireAuth>
      <div className="tv-exp-page">
        <SectionPageHeader
          thumb={<ArtIcon name="expansion" size={96} />}
          title={t("toolExpansion.title")}
          subtitle={t("toolExpansion.subtitle")}
          facts={facts}
          actions={
            <SettingsActionsMenu
              ariaLabel={t("toolExpansion.title")}
              buttonLabel={t("inventory.actions")}
              entries={(["how", "matches", "archived"] as const).map((id) => ({
                key: id,
                label: tabLabel(id),
                run: () => setTab(id),
              }))}
            />
          }
        />

        {error && <Alert tone="danger">{error}</Alert>}

        <Tabs
          tabs={tabs}
          activeId={tab}
          onChange={(id) => setTab(id as ExpansionTabId)}
        />
      </div>
    </RequireAuth>
  );
}
