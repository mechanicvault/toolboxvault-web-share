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
        err instanceof ApiError ? err.message : "Couldn't load your history.",
      );
    }
  }, []);

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
        err instanceof ApiError ? err.message : "Couldn't load more history.",
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
      toast("Restore point saved.", { tone: "success" });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save a restore point.",
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
        err instanceof ApiError ? err.message : "Couldn't count the changes.",
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
          ? `Restored: ${result.restored} change${result.restored === 1 ? "" : "s"} undone` +
              (result.not_changed > 0
                ? `, ${result.not_changed} shared record${result.not_changed === 1 ? "" : "s"} left as they were.`
                : ".")
          : "Your account already matches that point — nothing to undo.",
        { tone: "success", duration: 8000 },
      );
      await load();
    } catch (err) {
      setPreviewError(
        err instanceof ApiError
          ? err.message
          : "The restore didn't go through — nothing was changed.",
      );
    } finally {
      setRestoring(false);
    }
  }

  const groups = groupByDay(entries);

  return (
    <Panel title="History & restore" variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Everything you add, change or delete is recorded here.
          If something goes wrong — a tool deleted by accident, a
          whole list wiped — pick a restore point and your account
          rolls back to exactly how it was then. Records shared
          with other people (borrowing, tool-list shares, filed
          claims) are listed for completeness but never rewound:
          restoring your account doesn't rewrite anyone else's.
          Deleted files are kept for a while so restores bring
          your photos back too.
        </p>
        {loadError && <Alert tone="danger">{loadError}</Alert>}

        <form
          onSubmit={(e) => void createPoint(e)}
          style={{ display: "grid", gap: "var(--space-2)" }}
        >
          <p style={{ fontWeight: 700, margin: 0 }}>Restore points</p>
          <div
            style={{
              display: "flex",
              gap: "var(--space-2)",
              flexWrap: "wrap",
              alignItems: "end",
            }}
          >
            <FormField label="Name this point (optional)">
              <TextInput
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Before the big cleanout"
                maxLength={200}
                style={{ minWidth: "16rem" }}
              />
            </FormField>
            <Button type="submit" loading={creating}>
              Create restore point
            </Button>
          </div>
        </form>

        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          {markers === null && !loadError && <p style={{ margin: 0 }}>Loading…</p>}
          {markers !== null && markers.length === 0 && (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              No restore points yet — one is saved automatically
              every day your account changes, and you can create
              your own above.
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
                <div style={{ fontWeight: 600 }}>{markerTitle(marker)}</div>
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
                  ? "Start"
                  : marker.kind === "daily"
                    ? "Daily"
                    : marker.kind === "pre_bulk"
                      ? "Before bulk change"
                      : marker.kind === "pre_restore"
                        ? "Before a restore"
                        : "Manual"}
              </Badge>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void openRestore(marker)}
              >
                Restore to here
              </Button>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <p style={{ fontWeight: 700, margin: 0 }}>Activity</p>
          {entries.length === 0 && markers !== null && (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Your history starts now — nothing is recorded before
              today. From here on, every change lands in this list,
              and your starting point is saved above as the first
              restore point.
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
                    <Badge tone="neutral">by someone else</Badge>
                  )}
                  {entry.actor === "system" && (
                    <Badge tone="neutral">system</Badge>
                  )}
                  {!entry.restorable && entry.action !== "restore" && (
                    <span
                      style={{
                        color: "var(--text-muted)",
                        fontSize: "var(--font-size-sm)",
                      }}
                    >
                      Shared record — kept as-is by restores
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
                Show more ({total - entries.length} older)
              </Button>
            </div>
          )}
        </div>
      </div>

      <Modal
        open={target !== null}
        onClose={() => setTarget(null)}
        title={target ? `Restore to “${markerTitle(target)}”?` : ""}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>
              Cancel
            </Button>
            <Button
              loading={restoring}
              disabled={!preview || preview.changes_to_undo === 0}
              onClick={() => void confirmRestore()}
            >
              Restore my account
            </Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--space-3)" }}>
          {previewError && <Alert tone="danger">{previewError}</Alert>}
          {!preview && !previewError && <p style={{ margin: 0 }}>Counting the changes…</p>}
          {preview && (
            <>
              <p style={{ margin: 0 }}>
                {preview.changes_to_undo === 0
                  ? "Your account already matches this point — there is nothing to undo."
                  : `This will undo ${preview.changes_to_undo} change${preview.changes_to_undo === 1 ? "" : "s"} made after ${target ? markerWhen(target.created_at) : "this point"}: additions are removed, edits roll back, and deletions come back — photos included.`}
              </p>
              {preview.shared_not_changed > 0 && (
                <p style={{ margin: 0, color: "var(--text-muted)" }}>
                  {preview.shared_not_changed} shared record
                  {preview.shared_not_changed === 1 ? "" : "s"} (borrowing,
                  tool-list shares, filed claims) won't be changed — they're
                  shared history with other people.
                </p>
              )}
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                A new restore point is saved first, so you can undo this
                restore itself.
              </p>
            </>
          )}
        </div>
      </Modal>
    </Panel>
  );
}
