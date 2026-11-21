import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Modal,
  Panel,
  TextInput,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import {
  groupByDay,
  markerTitle,
  markerWhen,
  entryTime,
  type JournalEntry,
  type RestoreMarker,
  type RestorePreview,
  type RestoreResult,
} from "./history";

/**
 * Settings → History & restore: the account's audit trail.
 *
 * Every add / change / delete of the user's own content is
 * journaled server-side with before/after snapshots; this section
 * shows the plain-language timeline and the restore points the
 * account can roll back to. Restores invert everything after the
 * chosen point in one all-or-nothing step — a fresh restore point
 * is saved first, so a restore can itself be undone. Shared
 * records (borrowing, peer shares, filed claims) appear in the
 * timeline for visibility but are never rewound, and the confirm
 * dialog says exactly how many of each a restore will touch.
 */

const PAGE_SIZE = 50;

export default function HistorySettings() {
  const { toast } = useToast();
  const t = useT();
  const [markers, setMarkers] = useState<RestoreMarker[] | null>(null);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [target, setTarget] = useState<RestoreMarker | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    try {
      const [markerRows, page] = await Promise.all([
        api<RestoreMarker[]>("/core/history/markers"),
        api<{ entries: JournalEntry[]; total: number }>(
          `/core/history/entries?limit=${PAGE_SIZE}&offset=0`,
        ),
      ]);
      setMarkers(markerRows);
      setEntries(page.entries);
      setTotal(page.total);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("settings.history.loadFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api<{ entries: JournalEntry[]; total: number }>(
        `/core/history/entries?limit=${PAGE_SIZE}&offset=${entries.length}`,
      );
      setEntries((prev) => [...prev, ...page.entries]);
      setTotal(page.total);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.history.loadMoreFailed"),
        { tone: "danger" },
      );
    } finally {
      setLoadingMore(false);
    }
  }

  async function createPoint(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await api("/core/history/markers", {
        method: "POST",
        body: JSON.stringify({ label: label.trim() }),
      });
      setLabel("");
      toast(t("settings.history.pointSaved"), { tone: "success" });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.history.pointSaveFailed"),
        { tone: "danger" },
      );
    } finally {
      setCreating(false);
    }
  }

  async function openRestore(marker: RestoreMarker) {
    setTarget(marker);
    setPreview(null);
    setPreviewError(null);
    try {
      setPreview(
        await api<RestorePreview>(
          `/core/history/restore-preview?marker_id=${marker.id}`,
        ),
      );
    } catch (err) {
      setPreviewError(
        err instanceof ApiError ? err.message : t("settings.history.countFailed"),
      );
    }
  }

  async function confirmRestore() {
    if (!target) return;
    setRestoring(true);
    try {
      const result = await api<RestoreResult>("/core/history/restore", {
        method: "POST",
        body: JSON.stringify({ marker_id: target.id }),
      });
      setTarget(null);
      toast(
        result.restored > 0
          ? t(
              result.restored === 1
                ? "settings.history.restoredOne"
                : "settings.history.restoredMany",
            ).replace("{count}", String(result.restored)) +
              (result.not_changed > 0
                ? t(
                    result.not_changed === 1
                      ? "settings.history.restoredSharedOne"
                      : "settings.history.restoredSharedMany",
                  ).replace("{count}", String(result.not_changed))
                : ".")
          : t("settings.history.nothingToUndo"),
        { tone: "success", duration: 8000 },
      );
      await load();
    } catch (err) {
      setPreviewError(
        err instanceof ApiError
          ? err.message
          : t("settings.history.restoreFailed"),
      );
    } finally {
      setRestoring(false);
    }
  }

  const groups = groupByDay(entries);

  return (
    <Panel title={t("settings.history.title")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.history.intro")}
        </p>
        {loadError && <Alert tone="danger">{loadError}</Alert>}

        <form
          onSubmit={(e) => void createPoint(e)}
          style={{ display: "grid", gap: "var(--space-2)" }}
        >
          <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.history.restorePoints")}</p>
          <div
            style={{
              display: "flex",
              gap: "var(--space-2)",
              flexWrap: "wrap",
              alignItems: "end",
            }}
          >
            <FormField label={t("settings.history.nameLabel")}>
              <TextInput
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t("settings.history.namePlaceholder")}
                maxLength={200}
                style={{ minWidth: "16rem" }}
              />
            </FormField>
            <Button type="submit" loading={creating}>
              {t("settings.history.createPoint")}
            </Button>
          </div>
        </form>

        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          {markers === null && !loadError && <p style={{ margin: 0 }}>{t("shell.loading")}</p>}
          {markers !== null && markers.length === 0 && (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.history.noPoints")}
            </p>
          )}
          {(markers ?? []).map((marker) => (
            <div
              key={marker.id}
              style={{
                display: "flex",
                gap: "var(--space-3)",
                alignItems: "center",
                flexWrap: "wrap",
                borderTop: "1px solid var(--edge)",
                paddingTop: "var(--space-2)",
              }}
            >
              <div style={{ flex: "1 1 12rem", minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{markerTitle(marker, t)}</div>
                <div
                  style={{
                    color: "var(--text-muted)",
                    fontSize: "var(--font-size-sm)",
                  }}
                >
                  {markerWhen(marker.created_at)}
                </div>
              </div>
              <Badge tone={marker.kind === "baseline" ? "accent" : "neutral"}>
                {marker.kind === "baseline"
                  ? t("settings.history.kindStart")
                  : marker.kind === "daily"
                    ? t("settings.history.kindDailyBadge")
                    : marker.kind === "pre_bulk"
                      ? t("settings.history.kindPreBulkBadge")
                      : marker.kind === "pre_restore"
                        ? t("settings.history.kindPreRestoreBadge")
                        : t("settings.history.kindManualBadge")}
              </Badge>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void openRestore(marker)}
              >
                {t("settings.history.restoreToHere")}
              </Button>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <p style={{ fontWeight: 700, margin: 0 }}>{t("settings.history.activity")}</p>
          {entries.length === 0 && markers !== null && (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              {t("settings.history.historyStarts")}
            </p>
          )}
          {groups.map((group) => (
            <div key={group.day} style={{ display: "grid", gap: "var(--space-1)" }}>
              {/* Day section break (owner, 2026-11-12): the day
                  heading carries a full space-4 above it (24px
                  with the list's own gap) so one day's entries
                  visibly end before the next day begins. */}
              <p
                style={{
                  color: "var(--text-muted)",
                  fontSize: "var(--font-size-sm)",
                  fontWeight: 700,
                  margin: "var(--space-4) 0 0",
                }}
              >
                {group.day}
              </p>
              {group.entries.map((entry) => (
                <div
                  key={entry.id}
                  style={{
                    display: "flex",
                    gap: "var(--space-3)",
                    alignItems: "baseline",
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      color: "var(--text-muted)",
                      fontSize: "var(--font-size-sm)",
                      minWidth: "4.5rem",
                    }}
                  >
                    {entryTime(entry.occurred_at)}
                  </span>
                  <span
                    style={{
                      fontWeight: entry.action === "restore" ? 700 : 400,
                    }}
                  >
                    {entry.label}
                  </span>
                  {entry.actor === "other" && (
                    <Badge tone="neutral">{t("settings.history.bySomeoneElse")}</Badge>
                  )}
                  {entry.actor === "system" && (
                    <Badge tone="neutral">{t("settings.history.systemBadge")}</Badge>
                  )}
                  {!entry.restorable && entry.action !== "restore" && (
                    <span
                      style={{
                        color: "var(--text-muted)",
                        fontSize: "var(--font-size-sm)",
                      }}
                    >
                      {t("settings.history.sharedKept")}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
          {entries.length < total && (
            <div>
              <Button
                variant="secondary"
                loading={loadingMore}
                onClick={() => void loadMore()}
              >
                {t("settings.history.showMore").replace(
                  "{count}",
                  String(total - entries.length),
                )}
              </Button>
            </div>
          )}
        </div>
      </div>

      <Modal
        open={target !== null}
        onClose={() => setTarget(null)}
        title={
          target
            ? t("settings.history.restoreToTitle").replace(
                "{title}",
                markerTitle(target, t),
              )
            : ""
        }
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>
              {t("settings.history.cancel")}
            </Button>
            <Button
              loading={restoring}
              disabled={!preview || preview.changes_to_undo === 0}
              onClick={() => void confirmRestore()}
            >
              {t("settings.history.restoreMyAccount")}
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {previewError && <Alert tone="danger">{previewError}</Alert>}
          {!preview && !previewError && <p style={{ margin: 0 }}>{t("settings.history.countingChanges")}</p>}
          {preview && (
            <>
              <p style={{ margin: 0 }}>
                {preview.changes_to_undo === 0
                  ? t("settings.history.matchesPoint")
                  : t(
                      preview.changes_to_undo === 1
                        ? "settings.history.undoOne"
                        : "settings.history.undoMany",
                    )
                      .replace("{count}", String(preview.changes_to_undo))
                      .replace(
                        "{when}",
                        target
                          ? markerWhen(target.created_at)
                          : t("settings.history.thisPoint"),
                      )}
              </p>
              {preview.shared_not_changed > 0 && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {t(
                    preview.shared_not_changed === 1
                      ? "settings.history.sharedWontOne"
                      : "settings.history.sharedWontMany",
                  ).replace("{count}", String(preview.shared_not_changed))}
                </p>
              )}
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                {t("settings.history.undoNote")}
              </p>
            </>
          )}
        </div>
      </Modal>
    </Panel>
  );
}
