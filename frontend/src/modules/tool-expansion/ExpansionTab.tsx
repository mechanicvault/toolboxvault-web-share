import { useCallback, useEffect, useState } from "react";
import "./tool-expansion.css";
import { Link } from "react-router-dom";

import {
  Alert,
  Button,
  EmptyState,
  Panel,
  SideList,
  SideListRow,
  Spinner,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { getArchivedExpansions, getExpansions } from "./api";
import { ArchivedRow, SuggestionRow } from "./components";
import type { ArchivedExpansions, ExpansionSuggestions } from "./types";

/**
 * Tool Expansion as the Inventory page's EXPAND tab (owner
 * order, sheet row 134, 2026-11-18): the whole standalone
 * Tool Expansion page moved into Inventory — the main-menu
 * entry is gone and /tool-expansion redirects here. The tab
 * wears the Side List layout (owner's pattern, 2026-11-13):
 * the list on the left carries the page's three sections —
 * How it works · Expansion Matches · Archived items — and
 * the picked section's full content renders on the right, in
 * place. The section bodies are the page's own, unchanged:
 * the same suggestion engine, the same per-item groups and
 * rows (Main list layout), the same dismissal ledger behind
 * Archived with bring-back.
 *
 * `scope` (from the inventory badge / the item page, carried
 * as ?kind=&id= on the Inventory URL) scopes the Matches
 * section to one item and opens there directly; the chip at
 * the top of Matches clears back to all.
 */

export type ExpansionSectionId = "how" | "matches" | "archived";

export interface ExpansionScope {
  kind: "tool" | "battery";
  id: string;
}

/** The explainer section: what expansion does for the user,
 *  what they can do with a match, and how reporting differs
 *  from archiving — said plainly, with the door to the
 *  matches. */
function ExplainerSection({
  onGo,
}: {
  onGo: (section: ExpansionSectionId) => void;
}) {
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

/** The Archived matches section body: the viewer's own
 *  dismissal ledger as a TRUE list — Suggested piece ·
 *  Model # · Expands · Archived · Bring back. Fetches on
 *  mount and after every change (the section unmounts when
 *  another is active, so returning here always re-reads; the
 *  tab's rev also feeds in so an archive made on Matches
 *  shows here). */
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
    <div>
      <p className="tv-exp-arch-intro">{t("toolExpansion.archivedBody")}</p>
      <div className="tv-inv-list tv-exp-mlist" role="table">
        <div className="tv-exp-mhead tv-exp-arch-cols" role="row">
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
    </div>
  );
}

export function ExpansionTab({
  scope,
  onClearScope,
  section,
  onSectionChange,
}: {
  scope: ExpansionScope | null;
  onClearScope: () => void;
  section: ExpansionSectionId;
  onSectionChange: (section: ExpansionSectionId) => void;
}) {
  const t = useT();
  const [data, setData] = useState<ExpansionSuggestions | null>(null);
  const [archivedCount, setArchivedCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0);

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
        /* the counts just stay stale; the sections report their own errors */
      });
    setRev((r) => r + 1);
    // scope identity is derived from the URL params each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope?.kind, scope?.id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const scopedItem = scope ? (data?.groups[0]?.item ?? null) : null;

  const matchesPanel = (
    <div className="tv-exp-tabgrid">
      {scope && (
        <div className="tv-exp-scope">
          <span>
            {scopedItem
              ? t("toolExpansion.scopedTo").replace("{name}", scopedItem.name)
              : t("toolExpansion.scopedGeneric")}
          </span>
          <Button size="sm" variant="secondary" onClick={onClearScope}>
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
          <div key={`${group.item.kind}:${group.item.id}`} className="tv-exp-group">
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
            {/* The group names the owned item; inside it the
                suggestions are a TRUE list — one suggestion per
                row under a header row, Suggested piece ·
                Model # · Actions in their own columns, wearing
                the Inventory list's framed .tv-inv-list
                presentation (Main list layout). */}
            <div className="tv-inv-list tv-exp-mlist" role="table">
              <div className="tv-exp-mhead" role="row">
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
                  variant="mlist"
                />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );

  const panel =
    section === "how" ? (
      <ExplainerSection onGo={onSectionChange} />
    ) : section === "matches" ? (
      matchesPanel
    ) : (
      <ArchivedBody rev={rev} onChanged={refresh} />
    );

  return (
    <div>
      {error && <Alert tone="danger">{error}</Alert>}
      <SideList
        listLabel={t("toolExpansion.title")}
        list={
          <>
            <SideListRow
              selected={section === "how"}
              onSelect={() => onSectionChange("how")}
              title={t("toolExpansion.tab.how")}
            />
            <SideListRow
              selected={section === "matches"}
              onSelect={() => onSectionChange("matches")}
              title={t("inventory.expand.matches")}
              trailing={data !== null ? data.total : undefined}
            />
            <SideListRow
              selected={section === "archived"}
              onSelect={() => onSectionChange("archived")}
              title={t("inventory.expand.archived")}
              trailing={archivedCount ?? undefined}
            />
          </>
        }
        panel={panel}
      />
    </div>
  );
}
