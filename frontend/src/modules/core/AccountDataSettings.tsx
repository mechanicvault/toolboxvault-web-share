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
import { useLocale, useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { api, apiBlob, ApiError } from "../../lib/api";
import { useAuth } from "./AuthContext";

/**
 * Settings → Your data & account: the self-serve export (user
 * backup v1 — everything that's yours, in one ZIP) and the danger
 * zone: permanent, type-to-confirm account deletion.
 */
/** Removal-category vocabulary (backend data_removal.LABELS /
 * NOTES — a FIXED set): labels and notes render through the
 * dictionary by category key; unknown keys fall back to the API
 * text. The filed-claims suffix the API appends to the
 * claim-drafts note is re-rendered keyed on ES seats; EN seats
 * always see the API note verbatim. */
const CATEGORY_LABEL_KEYS: Record<string, DictKey> = {
  inventory: "settings.data.catInventory",
  parts: "settings.data.catParts",
  "claim-drafts": "settings.data.catClaimDrafts",
  marketplace: "settings.data.catMarketplace",
  forum: "settings.data.catForum",
  wishlist: "settings.data.catWishlist",
  "truck-accounts": "settings.data.catTruckAccounts",
};

const CATEGORY_NOTE_KEYS: Record<string, DictKey> = {
  inventory: "settings.data.catInventoryNote",
  parts: "settings.data.catPartsNote",
  "claim-drafts": "settings.data.catClaimDraftsNote",
  marketplace: "settings.data.catMarketplaceNote",
  forum: "settings.data.catForumNote",
  wishlist: "settings.data.catWishlistNote",
  "truck-accounts": "settings.data.catTruckAccountsNote",
};

const FILED_SUFFIX = / \((\d+) filed claims? stay untouched\.\)$/;

export default function AccountDataSettings() {
  const { toast } = useToast();
  const t = useT();
  const { locale } = useLocale();

  function categoryLabel(cat: RemovalCategory): string {
    const key = CATEGORY_LABEL_KEYS[cat.key];
    return key ? t(key) : cat.label;
  }

  function categoryNote(cat: RemovalCategory): string {
    if (cat.blocked_reason) return cat.blocked_reason;
    if (locale === "en") return cat.note;
    const key = CATEGORY_NOTE_KEYS[cat.key];
    if (!key) return cat.note;
    let text = t(key);
    const filed = cat.note.match(FILED_SUFFIX);
    if (filed) {
      text += t(
        filed[1] === "1"
          ? "settings.data.filedSuffixOne"
          : "settings.data.filedSuffixMany",
      ).replace("{count}", filed[1]);
    }
    return text;
  }
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
      toast(
        t(
          total === 1
            ? "settings.data.removedOne"
            : "settings.data.removedMany",
        ).replace("{count}", String(total)),
        {
          tone: "success",
          title: t("settings.data.removedTitle"),
        },
      );
      setRemovingKey(null);
      setRemoveConfirm("");
      await loadCategories();
    } catch (err) {
      setRemoveError(
        err instanceof ApiError ? err.message : t("settings.data.removeFailed"),
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
      toast(t("settings.data.exportToast"), { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.data.exportFailed"),
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
          : t("settings.data.deleteFailed"),
      );
      setDeleting(false);
    }
  }

  return (
    <Panel title={t("settings.data.title")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-4)" }}>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.data.download")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            {t("settings.data.downloadIntro")}
          </p>
          <Button variant="secondary" loading={exporting} onClick={() => void onExport()}>
            {t("settings.data.download")}
          </Button>
        </div>

        <div
          style={{
            borderTop: "1px solid var(--edge)",
            paddingTop: "1rem",
          }}
        >
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.data.deleteOneHeading")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            {t("settings.data.deleteOneIntro")}
          </p>
          {categories === null ? (
            <p style={{ color: "var(--text-muted)", margin: 0 }}>{t("shell.loading")}</p>
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
                      {categoryLabel(cat)}{" "}
                      <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                        {t(
                          cat.count === 1
                            ? "settings.data.recordsOne"
                            : "settings.data.recordsMany",
                        ).replace("{count}", String(cat.count))}
                      </span>
                    </p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      {categoryNote(cat)}
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
                    {t("settings.data.removeButton")}
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
            {t("settings.data.deleteAccountHeading")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            {t("settings.data.deleteAccountIntro")}
          </p>
          <Button variant="danger" onClick={() => setConfirmOpen(true)}>
            {t("settings.data.deleteAccountButton")}
          </Button>
        </div>
      </div>

      <Modal
        open={removingKey !== null}
        onClose={() => setRemovingKey(null)}
        title={t("settings.data.removeModalTitle")}
      >
        <form onSubmit={onRemoveCategory} style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ margin: 0 }}>
            {t("settings.data.removeLead")}
            <strong>
              {(() => {
                const cat = categories?.find((c) => c.key === removingKey);
                return cat ? categoryLabel(cat) : removingKey;
              })()}
            </strong>
            {t("settings.data.removeTail")}
          </p>
          {removeError && <Alert tone="danger">{removeError}</Alert>}
          <FormField
            label={t("settings.data.typeToConfirm").replace(
              "{key}",
              removingKey ?? "",
            )}
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
              {t("settings.data.deleteIt")}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRemovingKey(null)}
            >
              {t("settings.history.cancel")}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t("settings.data.deleteModalTitle")}
      >
        <form onSubmit={onDelete} style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ margin: 0 }}>
            {t("settings.data.deleteLead")}
            <strong>{t("settings.data.deleteStrong")}</strong>
            {t("settings.data.deleteTail")}
          </p>
          {deleteError && <Alert tone="danger">{deleteError}</Alert>}
          <FormField
            label={t("settings.data.typeDelete")}
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
              {t("settings.data.keepAccount")}
            </Button>
            <Button
              type="submit"
              variant="danger"
              loading={deleting}
              disabled={confirmText !== "DELETE"}
            >
              {t("settings.data.deletePermanently")}
            </Button>
          </div>
        </form>
      </Modal>
    </Panel>
  );
}
