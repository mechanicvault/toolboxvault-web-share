import { useEffect, useState, type FormEvent } from "react";

import {
  Alert,
  Button,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Roadmap (audit A15): the operator CRUD behind the
 * public "What's coming" page. Entries publish the moment
 * they're saved — there is no draft state, by design: the page
 * is the operator's public word.
 */

interface RoadmapEntry {
  id: string;
  title: string;
  note: string;
  status: string;
  sort_order: number;
}

const STATUS_LABEL: Record<string, string> = {
  planned: "Planned",
  in_progress: "In progress",
  shipped: "Shipped",
};

function RoadmapEditor() {
  const { toast } = useToast();
  const [entries, setEntries] = useState<RoadmapEntry[] | null>(null);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [statusValue, setStatusValue] = useState("planned");
  const [sortOrder, setSortOrder] = useState("0");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setEntries(await api<RoadmapEntry[]>("/admin/roadmap-entries"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the roadmap entries.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function resetForm() {
    setEditingId(null);
    setTitle("");
    setNote("");
    setStatusValue("planned");
    setSortOrder("0");
  }

  function startEdit(entry: RoadmapEntry) {
    setEditingId(entry.id);
    setTitle(entry.title);
    setNote(entry.note);
    setStatusValue(entry.status);
    setSortOrder(String(entry.sort_order));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const body = {
        title: title.trim(),
        note: note.trim(),
        status: statusValue,
        sort_order: Number(sortOrder) || 0,
      };
      if (editingId) {
        await api(`/admin/roadmap-entries/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
        toast("Roadmap entry updated.", { tone: "success" });
      } else {
        await api("/admin/roadmap-entries", {
          method: "POST",
          body: JSON.stringify(body),
        });
        toast("Roadmap entry published.", { tone: "success" });
      }
      resetForm();
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save the entry.", {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function remove(entry: RoadmapEntry) {
    if (!window.confirm(`Remove "${entry.title}" from the public roadmap?`)) return;
    try {
      await api(`/admin/roadmap-entries/${entry.id}`, { method: "DELETE" });
      if (editingId === entry.id) resetForm();
      await load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't remove the entry.", {
        tone: "danger",
      });
    }
  }

  return (
    <Panel title="Roadmap — What's coming">
      <div style={{ display: "grid", gap: "1rem" }}>
        <p style={{ margin: 0, color: "var(--muted)" }}>
          These entries are the public{" "}
          <a href="/roadmap" target="_blank" rel="noreferrer">
            /roadmap
          </a>{" "}
          page, word for word. Saving publishes immediately. Leave the
          list empty and the page says so — nothing is ever seeded or
          invented.
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        <form
          onSubmit={(e) => void submit(e)}
          style={{
            display: "grid",
            gap: "0.7rem",
            border: "1px solid var(--edge, currentColor)",
            borderRadius: "0.5rem",
            padding: "1rem",
          }}
        >
          <strong>{editingId ? "Edit entry" : "New entry"}</strong>
          <FormField label="Title" htmlFor="roadmap-title">
            <TextInput
              id="roadmap-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={200}
              placeholder="e.g. Spanish language support"
            />
          </FormField>
          <FormField label="Note (optional)" htmlFor="roadmap-note">
            <TextArea
              id="roadmap-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="One or two plain sentences. No dates you can't keep."
            />
          </FormField>
          <div style={{ display: "flex", gap: "0.8rem", flexWrap: "wrap" }}>
            <FormField label="Status" htmlFor="roadmap-status">
              <Select
                id="roadmap-status"
                value={statusValue}
                onChange={(e) => setStatusValue(e.target.value)}
              >
                <option value="planned">Planned</option>
                <option value="in_progress">In progress</option>
                <option value="shipped">Shipped</option>
              </Select>
            </FormField>
            <FormField label="Sort order" htmlFor="roadmap-sort" hint="Lower numbers appear first on the public roadmap.">
              <TextInput
                id="roadmap-sort"
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                style={{ width: "7rem" }}
              />
            </FormField>
          </div>
          <div style={{ display: "flex", gap: "0.6rem" }}>
            <Button type="submit" loading={busy}>
              {editingId ? "Save changes" : "Publish entry"}
            </Button>
            {editingId && (
              <Button type="button" variant="secondary" onClick={resetForm}>
                Cancel edit
              </Button>
            )}
          </div>
        </form>
        {!entries && <Spinner />}
        {entries && entries.length === 0 && (
          <EmptyState
            title="Nothing published"
            description="The public roadmap page is empty — exactly as shipped. Add the first entry above when there's something real to say."
          />
        )}
        {entries &&
          entries.map((entry) => (
            <div
              key={entry.id}
              style={{
                display: "flex",
                gap: "0.8rem",
                alignItems: "baseline",
                border: "1px solid var(--edge, currentColor)",
                borderRadius: "0.5rem",
                padding: "0.7rem 1rem",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                {STATUS_LABEL[entry.status] ?? entry.status}
              </span>
              <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                #{entry.sort_order}
              </span>
              <strong style={{ flex: 1, minWidth: "10rem" }}>{entry.title}</strong>
              <Button variant="secondary" onClick={() => startEdit(entry)}>
                Edit
              </Button>
              <Button variant="secondary" onClick={() => void remove(entry)}>
                Remove
              </Button>
            </div>
          ))}
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
