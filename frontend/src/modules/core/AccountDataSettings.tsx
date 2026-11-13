import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  FormField,
  Modal,
  Panel,
  TextInput,
  useToast,
} from "../../components";
import { api, apiBlob, ApiError } from "../../lib/api";
import { useAuth } from "./AuthContext";

/**
 * Settings → Your data & account: the self-serve export (user
 * backup v1 — everything that's yours, in one ZIP) and the danger
 * zone: permanent, type-to-confirm account deletion.
 */
export default function AccountDataSettings() {
  const { toast } = useToast();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [exporting, setExporting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Per-category removal (audit A11).
  interface RemovalCategory {
    key: string;
    label: string;
    count: number;
    note: string;
    blocked_reason: string | null;
  }
  const [categories, setCategories] = useState<RemovalCategory[] | null>(null);
  const [removingKey, setRemovingKey] = useState<string | null>(null);
  const [removeConfirm, setRemoveConfirm] = useState("");
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);

  async function loadCategories() {
    try {
      setCategories(await api<RemovalCategory[]>("/core/data-removal"));
    } catch {
      setCategories([]);
    }
  }

  useEffect(() => {
    void loadCategories();
  }, []);

  async function onRemoveCategory(e: FormEvent) {
    e.preventDefault();
    if (!removingKey) return;
    setRemoveError(null);
    setRemoving(true);
    try {
      const result = await api<{ category: string; removed: Record<string, number> }>(
        "/core/data-removal",
        {
          method: "POST",
          body: JSON.stringify({
            category: removingKey,
            confirmation: removeConfirm.trim(),
          }),
        },
      );
      const total = Object.values(result.removed).reduce((a, b) => a + b, 0);
      toast(`Removed ${total} record${total === 1 ? "" : "s"} — everything else is untouched.`, {
        tone: "success",
        title: "Data removed",
      });
      setRemovingKey(null);
      setRemoveConfirm("");
      await loadCategories();
    } catch (err) {
      setRemoveError(
        err instanceof ApiError ? err.message : "Couldn't remove that data. Try again.",
      );
    } finally {
      setRemoving(false);
    }
  }

  async function onExport() {
    setExporting(true);
    try {
      const blob = await apiBlob("/core/export");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "toolbox-vault-export.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast("Your data export is downloading.", { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't build your export.",
        { tone: "danger" },
      );
    } finally {
      setExporting(false);
    }
  }

  async function onDelete(e: FormEvent) {
    e.preventDefault();
    setDeleteError(null);
    setDeleting(true);
    try {
      await api("/core/me", {
        method: "DELETE",
        body: JSON.stringify({ confirmation: confirmText }),
      });
      logout();
      navigate("/login", { replace: true });
    } catch (err) {
      setDeleteError(
        err instanceof ApiError
          ? err.message
          : "Couldn't delete your account. Try again.",
      );
      setDeleting(false);
    }
  }

  return (
    <Panel title="Your data & account" variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            Download my data
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            One ZIP with everything that's yours: your profile, tools
            (including custom fields), sharing settings, and your
            photos and documents as files. Anything that can't be
            bundled is listed in the export with a download link.
          </p>
          <Button variant="secondary" loading={exporting} onClick={() => void onExport()}>
            Download my data
          </Button>
        </div>

        <div
          style={{
            borderTop: "1px solid var(--edge)",
            paddingTop: "1rem",
          }}
        >
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            Delete one kind of data
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            Erase a single category and keep everything else — your
            account stays exactly as it is. Each removal asks you to
            type the category's name first, and is written to the
            audit log. Some categories refuse while they'd break a
            record that has to stay whole; the reason shows right
            on the row.
          </p>
          {categories === null ? (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>Loading…</p>
          ) : (
            <div style={{ display: "grid", gap: "0.6rem" }}>
              {categories.map((cat) => (
                <div
                  key={cat.key}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    flexWrap: "wrap",
                    alignItems: "center",
                    border: "1px solid var(--edge)",
                    borderRadius: "var(--radius)",
                    padding: "0.7rem 0.9rem",
                  }}
                >
                  <div style={{ minWidth: "min(320px, 100%)" }}>
                    <p style={{ fontWeight: 600, margin: 0 }}>
                      {cat.label}{" "}
                      <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                        — {cat.count} record{cat.count === 1 ? "" : "s"}
                      </span>
                    </p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      {cat.blocked_reason ?? cat.note}
                    </p>
                  </div>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={cat.count === 0 || cat.blocked_reason !== null}
                    onClick={() => {
                      setRemoveError(null);
                      setRemoveConfirm("");
                      setRemovingKey(cat.key);
                    }}
                  >
                    Remove…
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div
          className="tv-danger-zone"
          style={{
            borderTop: "1px solid var(--edge)",
            paddingTop: "1rem",
          }}
        >
          <p
            style={{
              fontWeight: 700,
              margin: "0 0 var(--space-2)",
              color: "var(--danger)",
            }}
          >
            Delete my account
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            Deleting your account is permanent. Your tools, photos,
            sharing, and settings are erased and can't be recovered.
            Download your data first if you want a copy.
          </p>
          <Button variant="danger" onClick={() => setConfirmOpen(true)}>
            Delete my account…
          </Button>
        </div>
      </div>

      <Modal
        open={removingKey !== null}
        onClose={() => setRemovingKey(null)}
        title="Delete this data permanently?"
      >
        <form onSubmit={onRemoveCategory} style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ margin: 0 }}>
            This removes{" "}
            <strong>
              {categories?.find((c) => c.key === removingKey)?.label ?? removingKey}
            </strong>{" "}
            and nothing else. Your account and all other data stay.
            It cannot be undone from here.
          </p>
          {removeError && <Alert tone="danger">{removeError}</Alert>}
          <FormField
            label={`Type ${removingKey ?? ""} to confirm`}
            htmlFor="remove-confirm"
            required
          >
            <TextInput
              id="remove-confirm"
              value={removeConfirm}
              onChange={(e) => setRemoveConfirm(e.target.value)}
              autoComplete="off"
              placeholder={removingKey ?? ""}
            />
          </FormField>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Button type="submit" variant="danger" loading={removing}>
              Delete it
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRemovingKey(null)}
            >
              Cancel
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Delete your account permanently?"
      >
        <form onSubmit={onDelete} style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ margin: 0 }}>
            This is <strong>permanent and cannot be undone</strong>. Your
            account, tools, photos, documents, sharing, and settings will
            be erased, and you'll be signed out everywhere.
          </p>
          {deleteError && <Alert tone="danger">{deleteError}</Alert>}
          <FormField
            label="Type DELETE to confirm"
            htmlFor="delete-confirm"
            required
          >
            <TextInput
              id="delete-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoComplete="off"
              placeholder="DELETE"
            />
          </FormField>
          <div
            style={{
              display: "flex",
              gap: "var(--space-2)",
              justifyContent: "flex-end",
            }}
          >
            <Button
              type="button"
              variant="secondary"
              onClick={() => setConfirmOpen(false)}
            >
              Keep my account
            </Button>
            <Button
              type="submit"
              variant="danger"
              loading={deleting}
              disabled={confirmText !== "DELETE"}
            >
              Delete permanently
            </Button>
          </div>
        </form>
      </Modal>
    </Panel>
  );
}
