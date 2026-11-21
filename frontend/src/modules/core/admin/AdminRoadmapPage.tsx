import { useEffect, useState } from "react";

import {
  Alert,
  Button,
  EmptyState,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import {
  ROADMAP_STAGES,
  RoadmapStageBar,
  stageLabelKey,
} from "../RoadmapStageBar";
import "../roadmap.css";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Roadmap (audit A15; stage rebuild 2026-11-12): the
 * operator task list behind the public "What's coming" page.
 * A Main list layout: Add at the top, edit IN PLACE on the
 * rows, the stage is a dropdown right on the row, rows reorder
 * by hold-drag on the grip. Saving publishes immediately —
 * there is no draft state, by design: the page is the
 * operator's public word.
 */

interface RoadmapEntry {
  id: string;
  title: string;
  note: string;
  stage: string;
  sort_order: number;
}

const NEW_ID = "new";

function RoadmapEditor() {
  const t = useT();
  const { toast } = useToast();
  const [entries, setEntries] = useState<RoadmapEntry[] | null>(null);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftNote, setDraftNote] = useState("");
  const [draftStage, setDraftStage] = useState<string>("idea");
  const [busy, setBusy] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [armedId, setArmedId] = useState<string | null>(null);

  async function load() {
    try {
      setEntries(await api<RoadmapEntry[]>("/admin/roadmap-entries"));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("admin.roadmap.loadError"),
      );
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startAdd() {
    setEditingId(NEW_ID);
    setDraftTitle("");
    setDraftNote("");
    setDraftStage("idea");
  }

  function startEdit(entry: RoadmapEntry) {
    setEditingId(entry.id);
    setDraftTitle(entry.title);
    setDraftNote(entry.note);
    setDraftStage(entry.stage);
  }

  function cancelEdit() {
    setEditingId(null);
  }

  async function saveEdit() {
    if (!editingId || busy) return;
    if (!draftTitle.trim()) return;
    setBusy(true);
    try {
      if (editingId === NEW_ID) {
        const first = entries && entries.length > 0 ? entries[0] : null;
        await api("/admin/roadmap-entries", {
          method: "POST",
          body: JSON.stringify({
            title: draftTitle.trim(),
            note: draftNote.trim(),
            stage: draftStage,
            sort_order: first ? first.sort_order - 10 : 0,
          }),
        });
        toast(t("admin.roadmap.published"), { tone: "success" });
      } else {
        const entry = entries?.find((e) => e.id === editingId);
        if (!entry) return;
        await api(`/admin/roadmap-entries/${entry.id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: draftTitle.trim(),
            note: draftNote.trim(),
            stage: draftStage,
            sort_order: entry.sort_order,
          }),
        });
        toast(t("admin.roadmap.updated"), { tone: "success" });
      }
      setEditingId(null);
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("admin.roadmap.saveError"), {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function changeStage(entry: RoadmapEntry, stage: string) {
    if (stage === entry.stage) return;
    setEntries((prev) =>
      prev ? prev.map((e) => (e.id === entry.id ? { ...e, stage } : e)) : prev,
    );
    try {
      await api(`/admin/roadmap-entries/${entry.id}`, {
        method: "PUT",
        body: JSON.stringify({
          title: entry.title,
          note: entry.note,
          stage,
          sort_order: entry.sort_order,
        }),
      });
      toast(t("admin.roadmap.stageSaved"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("admin.roadmap.saveError"), {
        tone: "danger",
      });
      await load();
    }
  }

  async function remove(entry: RoadmapEntry) {
    const question = t("admin.roadmap.removeConfirm").replace(
      "{title}",
      entry.title,
    );
    if (!window.confirm(question)) return;
    try {
      await api(`/admin/roadmap-entries/${entry.id}`, { method: "DELETE" });
      if (editingId === entry.id) setEditingId(null);
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("admin.roadmap.removeError"),
        { tone: "danger" },
      );
    }
  }

  async function reorder(fromId: string, toId: string) {
    if (!entries || fromId === toId) return;
    const from = entries.findIndex((e) => e.id === fromId);
    const to = entries.findIndex((e) => e.id === toId);
    if (from < 0 || to < 0) return;
    const next = [...entries];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setEntries(next);
    try {
      let changed = false;
      for (let i = 0; i < next.length; i += 1) {
        const desired = (i + 1) * 10;
        const entry = next[i];
        if (entry.sort_order !== desired) {
          changed = true;
          await api(`/admin/roadmap-entries/${entry.id}`, {
            method: "PUT",
            body: JSON.stringify({
              title: entry.title,
              note: entry.note,
              stage: entry.stage,
              sort_order: desired,
            }),
          });
        }
      }
      if (changed) toast(t("admin.roadmap.orderSaved"), { tone: "success" });
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("admin.roadmap.saveError"), {
        tone: "danger",
      });
      await load();
    }
  }

  function stageOptions() {
    return ROADMAP_STAGES.map((s) => (
      <option key={s} value={s}>
        {t(stageLabelKey(s))}
      </option>
    ));
  }

  function renderEditRow(key: string) {
    return (
      <div key={key} className="tv-rm-trow" role="row">
        <span />
        <div className="tv-rm-item tv-rm-item-edit">
          <TextInput
            aria-label={t("admin.roadmap.titleLabel")}
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void saveEdit();
              }
            }}
            maxLength={200}
            placeholder={t("admin.roadmap.titlePlaceholder")}
            autoFocus
          />
          <TextArea
            aria-label={t("admin.roadmap.noteLabel")}
            value={draftNote}
            onChange={(e) => setDraftNote(e.target.value)}
            rows={2}
            placeholder={t("admin.roadmap.notePlaceholder")}
          />
        </div>
        <div className="tv-rm-stage">
          <Select
            aria-label={t("admin.roadmap.colStage")}
            value={draftStage}
            onChange={(e) => setDraftStage(e.target.value)}
          >
            {stageOptions()}
          </Select>
        </div>
        <div className="tv-rm-status">
          <RoadmapStageBar stage={draftStage} labels={false} />
        </div>
        <div className="tv-rm-actions">
          <Button type="button" loading={busy} onClick={() => void saveEdit()}>
            {t("admin.roadmap.save")}
          </Button>
          <Button type="button" variant="secondary" onClick={cancelEdit}>
            {t("admin.roadmap.cancel")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <Panel title={t("admin.roadmap.title")}>
      <div style={{ display: "grid", gap: "1rem" }}>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          {t("admin.roadmap.intro")}{" "}
          <a href="/roadmap" target="_blank" rel="noreferrer">
            {t("admin.roadmap.viewPublic")}
          </a>
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="tv-rm-addrow">
          <Button
            type="button"
            onClick={startAdd}
            disabled={editingId === NEW_ID}
          >
            + {t("admin.roadmap.add")}
          </Button>
        </div>
        {!entries && <Spinner />}
        {entries && entries.length === 0 && editingId !== NEW_ID && (
          <EmptyState
            title={t("admin.roadmap.emptyTitle")}
            description={t("admin.roadmap.emptyBody")}
          />
        )}
        {entries && (entries.length > 0 || editingId === NEW_ID) && (
          <div className="tv-inv-list tv-rm-list" role="table">
            <div className="tv-rm-thead" role="row">
              <span role="columnheader" />
              <span role="columnheader">{t("admin.roadmap.colItem")}</span>
              <span role="columnheader">{t("admin.roadmap.colStage")}</span>
              <span role="columnheader">{t("admin.roadmap.colStatus")}</span>
              <span role="columnheader" />
            </div>
            {editingId === NEW_ID && renderEditRow(NEW_ID)}
            {entries.map((entry) =>
              editingId === entry.id ? (
                renderEditRow(entry.id)
              ) : (
                <div
                  key={entry.id}
                  className="tv-rm-trow"
                  role="row"
                  data-dragging={dragId === entry.id || undefined}
                  data-dragover={overId === entry.id || undefined}
                  draggable={armedId === entry.id}
                  onDragStart={(e) => {
                    setDragId(entry.id);
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (dragId && dragId !== entry.id) setOverId(entry.id);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (dragId) void reorder(dragId, entry.id);
                    setDragId(null);
                    setOverId(null);
                    setArmedId(null);
                  }}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverId(null);
                    setArmedId(null);
                  }}
                >
                  <span
                    className="tv-block-grip tv-rm-grip"
                    title={t("admin.roadmap.drag")}
                    aria-hidden="true"
                    onMouseDown={() => setArmedId(entry.id)}
                    onMouseUp={() => setArmedId(null)}
                  >
                    ⠿
                  </span>
                  <div className="tv-rm-item">
                    <div className="tv-rm-item-title">{entry.title}</div>
                    {entry.note && (
                      <p className="tv-rm-item-note">{entry.note}</p>
                    )}
                  </div>
                  <div className="tv-rm-stage">
                    <Select
                      aria-label={t("admin.roadmap.colStage")}
                      value={entry.stage}
                      onChange={(e) => void changeStage(entry, e.target.value)}
                    >
                      {stageOptions()}
                    </Select>
                  </div>
                  <div className="tv-rm-status">
                    <RoadmapStageBar stage={entry.stage} labels={false} />
                  </div>
                  <div className="tv-rm-actions">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => startEdit(entry)}
                    >
                      {t("admin.roadmap.edit")}
                    </Button>
                    <button
                      type="button"
                      className="tv-rm-remove"
                      aria-label={t("admin.roadmap.removeFor").replace(
                        "{title}",
                        entry.title,
                      )}
                      title={t("admin.roadmap.remove")}
                      onClick={() => void remove(entry)}
                    >
                      −
                    </button>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

export default function AdminRoadmapPage() {
  return (
    <RequireAuth>
      <AdminShell>
        <RoadmapEditor />
      </AdminShell>
    </RequireAuth>
  );
}
