import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Panel,
  Spinner,
  LinkButton,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import HealthFixWizard from "./HealthFixWizard";
import "./wizard.css";
import type { HealthCheckItem, HealthCheckResult } from "./types";

/**
 * Health Check (gap wave 1): the claim-readiness scan. Which
 * ACTIVE items are missing the data a claim actually needs — an
 * identifier (a model number OR a serial number; either one
 * satisfies it, owner ruling 2026-11-03), a photo, a purchase
 * date — grouped/filterable by what's missing. The list is a
 * TRUE list (owner rebuild, 2026-11-12): one row per item and
 * one column per field the scan checks — identifier, photo,
 * purchase date, piece serials — with a check box in every
 * cell: a GREY check when the item has the field, a RED check
 * when it's the missing thing. Every red check is a link to
 * the EXACT spot that fixes it (owner ruling 2026-11-05): the
 * Photos tab's add area for a photo, the model/serial field
 * for the identifier, the purchase-date field, a piece's own
 * serial field — and the row's Fix it flies to the first
 * gap. The landing focus + highlight is
 * lib/fixFocus. Set pieces missing serials surface under their
 * set (pieces have no model/photo/date of their own). Inactive
 * items (over the plan limit) are excluded, the same rule
 * reports use.
 *
 * The list wears the INVENTORY MAIN LIST's presentation
 * (owner order, 2026-11-12): the framed .tv-inv-list surface,
 * the inventory table's header treatment, row padding and
 * --table-edge dividers, and its phone restack — the two lists
 * are one family. The section's controls (filters, the
 * "Ignore all missing photos" bulk action) sit above the
 * framed list, the way Inventory's toolbar sits above its
 * list. "Ignore all missing photos" applies the SAME per-item
 * flag as the row button, to every flagged missing photo at
 * once (POST /inventory/health-check/photo-ignore-all).
 */

/** Where one gap's Fix-it link lands. The hash names the fix;
 *  the destination page resolves it to the field (lib/fixFocus). */
function gapTarget(item: HealthCheckItem, gap: string): string {
  const base =
    item.kind === "tool"
      ? `/inventory/${item.id}`
      : `/inventory/batteries/${item.id}`;
  if (gap === "photo") return `${base}#photos`;
  if (gap === "identifier") return `${base}/edit#fix-model`;
  if (gap === "purchase_date") return `${base}/edit#fix-purchase-date`;
  return `${base}/edit`;
}

function pieceTarget(item: HealthCheckItem, pieceId: string): string {
  return `/inventory/${item.id}/edit#fix-piece-${pieceId}`;
}

/** The row's Fix it target: the FIRST gap, in display order. */
function firstGapTarget(item: HealthCheckItem): string {
  if (item.missing.length > 0) return gapTarget(item, item.missing[0]);
  if (item.pieces_missing.length > 0)
    return pieceTarget(item, item.pieces_missing[0].id);
  return gapTarget(item, "");
}

/** One check-box cell mark (owner rebuild, 2026-11-12): a small
 *  square box with a check in it — GREY when the item has the
 *  field, RED when the field is the missing thing (the red
 *  marks render inside links to the exact fix; see the row
 *  renderer). Colors ride the design tokens (--text-muted /
 *  --edge-strong for grey, --danger / --danger-soft for red)
 *  so the mark reads in both themes. */
function HealthMark({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span
      className={`tv-health-mark tv-health-mark--${ok ? "ok" : "missing"}`}
      title={label}
      role="img"
      aria-label={label}
    >
      <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
        <path
          d="M2.2 6.7 4.9 9.2 9.8 3.2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
const MISSING_KEYS: Record<string, string> = {
  identifier: "inventory.health.labelIdentifier",
  photo: "inventory.health.labelPhoto",
  purchase_date: "inventory.health.labelPurchase",
  piece_serial: "inventory.health.labelPieceSerial",
};

const FILTER_KEYS: Array<{ key: string; labelKey: string }> = [
  { key: "all", labelKey: "inventory.health.filterAll" },
  { key: "identifier", labelKey: "inventory.health.filterIdentifier" },
  { key: "photo", labelKey: "inventory.health.filterPhoto" },
  { key: "purchase_date", labelKey: "inventory.health.filterPurchase" },
  { key: "piece_serial", labelKey: "inventory.health.filterPieces" },
];

export default function HealthCheckPage() {
  return (
    <RequireAuth>
      <HealthCheckContent />
    </RequireAuth>
  );
}

function HealthCheckContent() {
  const t = useT();
  const [result, setResult] = useState<HealthCheckResult | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  // Sweep E3 (busy-work #5): the fix-all ask + wizard, and the
  // per-item photo-ignore toggle's in-flight marker.
  const [wizardOpen, setWizardOpen] = useState(false);
  const [askDismissed, setAskDismissed] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [ignoringAll, setIgnoringAll] = useState(false);

  const reload = useCallback(() => {
    api<HealthCheckResult>("/inventory/health-check")
      .then(setResult)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : t("inventory.health.loadFailed")),
      );
  }, [t]);

  useEffect(() => {
    reload();
  }, [reload]);

  /** Ignore / un-ignore ONE item's missing photo (sweep E3):
   *  photo only, from this page, reversible from this page. The
   *  scan re-runs so the counts above move with it. */
  const togglePhotoIgnore = useCallback(
    async (item: { kind: string; id: string }, ignored: boolean) => {
      setTogglingId(item.id);
      try {
        await api("/inventory/health-check/photo-ignore", {
          method: "POST",
          body: JSON.stringify({ kind: item.kind, item_id: item.id, ignored }),
        });
        reload();
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : t("inventory.health.loadFailed"),
        );
      } finally {
        setTogglingId(null);
      }
    },
    [reload, t],
  );

  /** Ignore ALL currently-flagged missing photos at once
   *  (owner order, 2026-11-12): the same per-item flag the row
   *  button sets, applied by the bulk endpoint to every item
   *  the scan flags for a photo. The scan re-runs so the
   *  counts, the list, and the ignored section move together —
   *  and the Home due count reads the same scan, so it agrees. */
  const ignoreAllPhotos = useCallback(async () => {
    setIgnoringAll(true);
    try {
      await api("/inventory/health-check/photo-ignore-all", {
        method: "POST",
      });
      reload();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("inventory.health.loadFailed"),
      );
    } finally {
      setIgnoringAll(false);
    }
  }, [reload, t]);

  /** "No {label}" — a red check's hover/reader words (the old
   *  gap pill's own text, kept). */
  const noLabel = (labelKey: string) =>
    t("inventory.health.badgeNo").replace(
      "{label}",
      t(labelKey as never).toLowerCase(),
    );

  const items = useMemo(() => {
    if (!result) return [];
    if (filter === "all") return result.items;
    if (filter === "piece_serial")
      return result.items.filter((i) => i.pieces_missing_serial.length > 0);
    return result.items.filter((i) =>
      i.missing.includes(filter as (typeof i.missing)[number]),
    );
  }, [result, filter]);

  // Sweep B2-F16: an empty vault is not "claim-ready" — the scan
  // ran over zero items. total_items separates the two states.
  const vaultEmpty = result !== null && (result.total_items ?? 0) === 0;

  return (
    // Sweep B2-F10: the page takes the standard content width
    // (--max-content-width, the .tv-main-inner measure) instead of
    // its old 880px cap, which left the right of a desktop screen
    // empty. Words and flow are unchanged — the model surface is
    // only widened.
    <div style={{ display: "grid", gap: "var(--spacing)", maxWidth: "var(--max-content-width)" }}>
      <div>
        <h1 style={{ margin: "0 0 0.25rem", fontSize: "1.6rem" }}>{t("inventory.healthCheck")}</h1>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          {t("inventory.health.intro")}
        </p>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {result === null && !error ? (
        <Spinner />
      ) : result ? (
        <>
          <Panel>
            <p style={{ margin: 0, fontSize: "1.1rem" }}>
              {vaultEmpty ? (
                <strong>{t("inventory.health.noItems")}</strong>
              ) : result.total === 0 ? (
                <strong>{t("inventory.health.allReady")}</strong>
              ) : (
                <strong>
                  {t(
                    result.total === 1
                      ? "inventory.health.needOne"
                      : "inventory.health.needMany",
                  ).replace("{count}", String(result.total))}
                </strong>
              )}
            </p>
            {result.total > 0 && (
              <p style={{ margin: "0.4rem 0 0", color: "var(--text-muted)" }}>
                {Object.entries(result.counts)
                  .filter(([, n]) => n > 0)
                  .map(([key, n]) =>
                    t("inventory.health.countsLine")
                      .replace("{count}", String(n))
                      .replace(
                        "{label}",
                        (MISSING_KEYS[key]
                          ? t(MISSING_KEYS[key] as never)
                          : key
                        ).toLowerCase(),
                      ),
                  )
                  .join(" · ")}
              </p>
            )}
          </Panel>
          {result.total > 10 && !askDismissed && !wizardOpen && (
            <Panel>
              <p className="tv-health-plain">{t("inventory.health.fixAllAsk")}</p>
              <div className="tv-health-actions">
                <Button
                  type="button"
                  variant="primary"
                  onClick={() => setWizardOpen(true)}
                >
                  {t("inventory.health.fixAllYes")}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setAskDismissed(true)}
                >
                  {t("inventory.health.fixAllNo")}
                </Button>
              </div>
            </Panel>
          )}
          {result.total > 0 && (
            <div>
              <div className="tv-section-header">
                <h2 className="tv-section-title">
                  {t("inventory.health.panelTitle")}
                </h2>
                <span className="tv-section-rule" aria-hidden="true" />
              </div>
              <div className="tv-health-filters">
                {FILTER_KEYS.map((f) => (
                  <Button
                    key={f.key}
                    type="button"
                    variant={filter === f.key ? "primary" : "secondary"}
                    onClick={() => setFilter(f.key)}
                  >
                    {t(f.labelKey as never)}
                  </Button>
                ))}
                {(result.counts.photo ?? 0) > 0 && (
                  <Button
                    type="button"
                    variant="secondary"
                    className="tv-health-ignore-all"
                    loading={ignoringAll}
                    onClick={ignoreAllPhotos}
                  >
                    {t("inventory.health.ignoreAllPhotos")}
                  </Button>
                )}
              </div>
              {items.length === 0 ? (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {t("inventory.health.filterEmpty")}
                </p>
              ) : (
                <>
                  <p className="tv-health-legend">
                    {t("inventory.health.legend")}
                  </p>
                  <div className="tv-inv-list tv-health-table" role="table">
                    <div className="tv-health-thead" role="row">
                      <span
                        className="tv-health-th tv-health-th--name"
                        role="columnheader"
                      >
                        {t("inventory.health.colItem")}
                      </span>
                      <span className="tv-health-th" role="columnheader">
                        {t("inventory.health.labelIdentifier")}
                      </span>
                      <span className="tv-health-th" role="columnheader">
                        {t("inventory.health.labelPhoto")}
                      </span>
                      <span className="tv-health-th" role="columnheader">
                        {t("inventory.health.labelPurchase")}
                      </span>
                      <span className="tv-health-th" role="columnheader">
                        {t("inventory.health.labelPieceSerial")}
                      </span>
                      <span
                        className="tv-health-th"
                        role="columnheader"
                        aria-label={t("inventory.health.fixIt")}
                      />
                    </div>
                    {items.map((item) => (
                      <div
                        className="tv-health-trow"
                        role="row"
                        key={`${item.kind}:${item.id}`}
                      >
                        <div
                          className="tv-health-cell tv-health-cell--name"
                          role="cell"
                        >
                          <strong
                            className="tv-health-item-name"
                            title={item.name}
                          >
                            {item.name}
                          </strong>
                          {item.sub_limit_warning && (
                            <Badge tone="warning">
                              {t("inventory.health.subLimit")}
                            </Badge>
                          )}
                        </div>
                        <div
                          className="tv-health-cell tv-health-cell--ident"
                          role="cell"
                        >
                          <span className="tv-health-cell-label">
                            {t("inventory.health.labelIdentifier")}
                          </span>
                          {item.missing.includes("identifier") ? (
                            <Link
                              className="tv-health-mark-link"
                              to={gapTarget(item, "identifier")}
                              title={noLabel("inventory.health.labelIdentifier")}
                              aria-label={noLabel(
                                "inventory.health.labelIdentifier",
                              )}
                            >
                              <HealthMark ok={false} />
                            </Link>
                          ) : (
                            <HealthMark
                              ok
                              label={t("inventory.health.labelIdentifier")}
                            />
                          )}
                        </div>
                        <div
                          className="tv-health-cell tv-health-cell--photo"
                          role="cell"
                        >
                          <span className="tv-health-cell-label">
                            {t("inventory.health.labelPhoto")}
                          </span>
                          {item.photo_ignored ? (
                            <>
                              <HealthMark
                                ok
                                label={t("inventory.health.photoIgnoredBadge")}
                              />
                              <Badge tone="neutral">
                                {t("inventory.health.photoIgnoredBadge")}
                              </Badge>
                              <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                loading={togglingId === item.id}
                                onClick={() => togglePhotoIgnore(item, false)}
                              >
                                {t("inventory.health.unignorePhoto")}
                              </Button>
                            </>
                          ) : item.missing.includes("photo") ? (
                            <>
                              <Link
                                className="tv-health-mark-link"
                                to={gapTarget(item, "photo")}
                                title={noLabel("inventory.health.labelPhoto")}
                                aria-label={noLabel(
                                  "inventory.health.labelPhoto",
                                )}
                              >
                                <HealthMark ok={false} />
                              </Link>
                              <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                loading={togglingId === item.id}
                                onClick={() => togglePhotoIgnore(item, true)}
                              >
                                {t("inventory.health.ignorePhoto")}
                              </Button>
                            </>
                          ) : (
                            <HealthMark
                              ok
                              label={t("inventory.health.labelPhoto")}
                            />
                          )}
                        </div>
                        <div
                          className="tv-health-cell tv-health-cell--date"
                          role="cell"
                        >
                          <span className="tv-health-cell-label">
                            {t("inventory.health.labelPurchase")}
                          </span>
                          {item.missing.includes("purchase_date") ? (
                            <Link
                              className="tv-health-mark-link"
                              to={gapTarget(item, "purchase_date")}
                              title={noLabel("inventory.health.labelPurchase")}
                              aria-label={noLabel(
                                "inventory.health.labelPurchase",
                              )}
                            >
                              <HealthMark ok={false} />
                            </Link>
                          ) : (
                            <HealthMark
                              ok
                              label={t("inventory.health.labelPurchase")}
                            />
                          )}
                        </div>
                        <div
                          className="tv-health-cell tv-health-cell--pieces"
                          role="cell"
                        >
                          <span className="tv-health-cell-label">
                            {t("inventory.health.labelPieceSerial")}
                          </span>
                          {item.pieces_missing.length > 0 ? (
                            <>
                              <Link
                                className="tv-health-mark-link"
                                to={pieceTarget(item, item.pieces_missing[0].id)}
                                title={t(
                                  "inventory.health.pieceNoSerial",
                                ).replace(
                                  "{name}",
                                  item.pieces_missing[0].name,
                                )}
                                aria-label={t(
                                  "inventory.health.pieceNoSerial",
                                ).replace(
                                  "{name}",
                                  item.pieces_missing[0].name,
                                )}
                              >
                                <HealthMark ok={false} />
                              </Link>
                              <span className="tv-health-piece-names">
                                {item.pieces_missing
                                  .map((piece) => piece.name)
                                  .join(", ")}
                              </span>
                            </>
                          ) : (
                            <HealthMark
                              ok
                              label={t("inventory.health.labelPieceSerial")}
                            />
                          )}
                        </div>
                        <div
                          className="tv-health-cell tv-health-cell--actions"
                          role="cell"
                        >
                          <LinkButton
                            to={firstGapTarget(item)}
                            variant="secondary"
                          >
                            {t("inventory.health.fixIt")}
                          </LinkButton>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          {result.total === 0 &&
            (vaultEmpty ? (
              <EmptyState
                title={t("inventory.health.noItemsTitle")}
                description={t("inventory.health.noItemsBody")}
              />
            ) : (
              <EmptyState title={t("inventory.health.emptyTitle")} description={t("inventory.health.emptyBody")} />
            ))}
          {(result.photo_ignored_items ?? []).filter(
            (ignored) =>
              !result.items.some(
                (i) => i.kind === ignored.kind && i.id === ignored.id,
              ),
          ).length > 0 && (
            <Panel title={t("inventory.health.ignoredPanelTitle")}>
              <p className="tv-health-muted-line">
                {t("inventory.health.ignoredLine")}
              </p>
              <div className="tv-health-rows">
                {(result.photo_ignored_items ?? [])
                  .filter(
                    (ignored) =>
                      !result.items.some(
                        (i) => i.kind === ignored.kind && i.id === ignored.id,
                      ),
                  )
                  .map((ignored) => (
                    <div
                      key={`${ignored.kind}:${ignored.id}`}
                      className="tv-health-row"
                    >
                      <strong className="tv-health-row-name">{ignored.name}</strong>
                      <Badge tone="neutral">
                        {t("inventory.health.photoIgnoredBadge")}
                      </Badge>
                      <span className="tv-health-row-end">
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          loading={togglingId === ignored.id}
                          onClick={() => togglePhotoIgnore(ignored, false)}
                        >
                          {t("inventory.health.unignorePhoto")}
                        </Button>
                      </span>
                    </div>
                  ))}
              </div>
            </Panel>
          )}
          {wizardOpen && result && (
            <HealthFixWizard
              items={result.items}
              onFinish={() => {
                setWizardOpen(false);
                reload();
              }}
            />
          )}
        </>
      ) : null}
    </div>
  );
}
