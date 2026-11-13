import { useEffect, useState } from "react";
import "./tool-expansion.css";
import { Link, useNavigate } from "react-router-dom";

import { Button, Modal, Panel, useToast } from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { useT } from "../../i18n/LocaleContext";
import {
  dismissExpansion,
  getExpansions,
  reportExpansion,
  unarchiveExpansion,
} from "./api";
import type {
  ArchivedExpansion,
  ExpansionItemRef,
  ExpansionSuggestion,
} from "./types";

/**
 * Tool Expansion surfaces (owner spec 2026-10-25). Everything
 * here renders ONLY what the API hands back: a suggested piece's
 * name + model number and the viewer's own item. There is no
 * source user anywhere in the data, so there is nothing here
 * that could show one.
 */

/** The inventory cart badge: this item has N live expansions.
 *  A sibling of the row/card open button (never nested inside
 *  it), tapping it lands on the module page scoped to the item. */
export function ExpansionBadge({
  kind,
  id,
  count,
}: {
  kind: "tool" | "battery";
  id: string;
  count: number;
}) {
  const t = useT();
  const navigate = useNavigate();
  if (count <= 0) return null;
  return (
    <button
      type="button"
      className="tv-exp-badge"
      onClick={() => navigate(`/tool-expansion?kind=${kind}&id=${id}`)}
      aria-label={t("toolExpansion.badgeLabel")
        .replace("{count}", String(count))}
      title={t("toolExpansion.badgeLabel").replace("{count}", String(count))}
    >
      <ArtIcon name="expansion" size={18} />
      <span>{count}</span>
    </button>
  );
}

/** One suggestion row: the piece's name, its model number, and
 *  the viewer's two controls — Move to archived matches (per
 *  user, per item; the Archived tab reads the same ledger back)
 *  and Report inaccurate (judges the match for everyone, with a
 *  confirm that says so plainly). */
export function SuggestionRow({
  item,
  suggestion,
  onChanged,
}: {
  item: ExpansionItemRef;
  suggestion: ExpansionSuggestion;
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [busy, setBusy] = useState<"dismiss" | "report" | null>(null);
  const [confirmReport, setConfirmReport] = useState(false);

  async function dismiss() {
    setBusy("dismiss");
    try {
      await dismissExpansion({
        anchor_kind: item.kind,
        anchor_id: item.id,
        suggested_model: suggestion.suggested_model,
      });
      toast(t("toolExpansion.archivedToast"));
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("toolExpansion.actionFailed"),
        { tone: "danger" },
      );
      setBusy(null);
    }
  }

  async function report() {
    // A-16 (Deep Audit Round 2): the confirm is the shared Modal
    // — the site's one confirm language — with the SAME plain
    // copy the native window.confirm carried. Semantics are
    // unchanged (Front B verified the DB effect): one POST, the
    // row hides, a toast confirms.
    setConfirmReport(false);
    setBusy("report");
    try {
      await reportExpansion({
        anchor_model: suggestion.anchor_model,
        suggested_model: suggestion.suggested_model,
      });
      toast(t("toolExpansion.reported"));
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("toolExpansion.actionFailed"),
        { tone: "danger" },
      );
      setBusy(null);
    }
  }

  return (
    <div className="tv-ix-row" role="row">
      <strong className="tv-ix-cell-name" role="cell">{suggestion.name}</strong>
      <span className="tv-ix-facts" role="cell">{suggestion.model_number}</span>
      <span className="tv-exp-actions" role="cell">
        <Button
          size="sm"
          variant="ghost"
          loading={busy === "dismiss"}
          onClick={() => void dismiss()}
        >
          {t("toolExpansion.moveToArchived")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={busy === "report"}
          onClick={() => setConfirmReport(true)}
        >
          {t("toolExpansion.report")}
        </Button>
      </span>
      <Modal
        open={confirmReport}
        onClose={() => setConfirmReport(false)}
        title={t("toolExpansion.report")}
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setConfirmReport(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button onClick={() => void report()}>
              {t("toolExpansion.report")}
            </Button>
          </>
        }
      >
        <p>{t("toolExpansion.reportConfirm")}</p>
      </Modal>
    </div>
  );
}

/** The item detail page's expansions section (intermingling):
 *  this item's live suggestions, each row actionable, with the
 *  door to the module page scoped to the item. Best-effort like
 *  the claims panel beside it: module not effective (403), read
 *  failed, or zero suggestions — the section renders nothing and
 *  the item page stands on its own. */
export function ExpansionSection({
  kind,
  id,
}: {
  kind: "tool" | "battery";
  id: string;
}) {
  const t = useT();
  const [suggestions, setSuggestions] = useState<ExpansionSuggestion[] | null>(
    null,
  );
  const [item, setItem] = useState<ExpansionItemRef | null>(null);
  const [hidden, setHidden] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getExpansions({ kind, id })
      .then((result) => {
        if (cancelled) return;
        const group = result.groups[0];
        setItem(group?.item ?? null);
        setSuggestions(group?.suggestions ?? []);
      })
      .catch(() => {
        if (!cancelled) setHidden(true);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, id, tick]);

  if (hidden || suggestions === null || item === null) return null;
  if (suggestions.length === 0) return null;

  return (
    <Panel title={t("toolExpansion.sectionTitle")}>
      <div className="tv-ix-rows">
        {suggestions.map((suggestion) => (
          <SuggestionRow
            key={suggestion.suggested_model}
            item={item}
            suggestion={suggestion}
            onChanged={() => setTick((n) => n + 1)}
          />
        ))}
      </div>
      <p className="tv-exp-more">
        <Link
          className="tv-ix-link"
          to={`/tool-expansion?kind=${kind}&id=${id}`}
        >
          {t("toolExpansion.viewAll")}
        </Link>
      </p>
    </Panel>
  );
}

/** One archived match row (Archived matches tab, lane 5): the
 *  piece, the viewer's item it expands, the day it was archived,
 *  and Bring back — the un-archive write. Honest tombstones: an
 *  item the viewer no longer owns renders as a note, not a dead
 *  link, and a match that no longer generates says so — its name
 *  cell falls back to the stored model number alone. Bring back
 *  always works (the ledger row is the viewer's own paperwork);
 *  a non-restorable row simply won't reappear in Matches. */
export function ArchivedRow({
  entry,
  onChanged,
}: {
  entry: ArchivedExpansion;
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  async function bringBack() {
    setBusy(true);
    try {
      await unarchiveExpansion({
        anchor_kind: entry.anchor_kind,
        anchor_id: entry.anchor_id,
        suggested_model: entry.suggested_model,
      });
      toast(t("toolExpansion.broughtBack"));
      onChanged();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("toolExpansion.actionFailed"),
        { tone: "danger" },
      );
      setBusy(false);
    }
  }

  return (
    <div className="tv-ix-row tv-exp-arch-row" role="row">
      <span className="tv-ix-cell-name" role="cell">
        {entry.name ? (
          <strong>{entry.name}</strong>
        ) : (
          <strong>{entry.model_number}</strong>
        )}
        {!entry.restorable && (
          <span className="tv-exp-note">{t("toolExpansion.noLongerMatches")}</span>
        )}
      </span>
      <span className="tv-ix-facts" role="cell">{entry.model_number}</span>
      <span role="cell">
        {entry.item ? (
          <Link
            className="tv-ix-link"
            to={
              entry.item.kind === "battery"
                ? `/inventory/batteries/${entry.item.id}`
                : `/inventory/${entry.item.id}`
            }
          >
            {entry.item.name}
          </Link>
        ) : (
          <span className="tv-exp-note">{t("toolExpansion.itemGone")}</span>
        )}
      </span>
      <span className="tv-ix-facts" role="cell">
        {formatDate(entry.archived_at)}
      </span>
      <span className="tv-exp-actions" role="cell">
        <Button
          size="sm"
          variant="ghost"
          loading={busy}
          onClick={() => void bringBack()}
        >
          {t("toolExpansion.bringBack")}
        </Button>
      </span>
    </div>
  );
}
