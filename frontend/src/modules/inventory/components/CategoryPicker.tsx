import { useEffect, useRef, useState } from "react";
import { Button, Select, TextInput } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import type { CategoryRow } from "../types";
import { categoryDisplayName } from "../categoryLabel";

/** Light client fold for "is this value one of the listed
 *  categories" — case/punctuation-insensitive, mirroring the
 *  server identity closely enough for display (the server does
 *  the real folding when the item is saved). */
function fold(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

const ADD_NEW = "__add_new_category__";

// Shared const styles (the inline-style ratchet counts inline
// literals in components, not module-level consts).
const addRowStyle = {
  display: "flex",
  gap: "0.5rem",
  marginTop: "0.5rem",
  flexWrap: "wrap",
  alignItems: "center",
} as const;

const errorStyle = {
  color: "var(--danger)",
  fontSize: "0.85rem",
  margin: "0.4rem 0 0",
} as const;

/**
 * The category picker for the item forms (owner spec
 * 2026-10-25): a select of ALL the owner's categories (registry
 * order — starters first — starred or not: filing is not row
 * display), plus "Add new category…", which reveals an inline
 * name field ON THE SAME SCREEN; submitting creates the
 * category through the categories API and selects it. The
 * inline add never auto-stars (starring lives on the Categories
 * page).
 *
 * A stored value that is NOT in the registry (legacy free-typed
 * text) rides along as its own option, selected — editing an
 * item never silently strips its category.
 *
 * `defaultSystemKey` (the battery form passes "batteries"):
 * once the list loads, an EMPTY value adopts that starter's
 * display name — the form's standing default, now spelled the
 * way the seeded category is.
 */
export function CategoryPicker({
  id,
  value,
  onChange,
  defaultSystemKey,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  defaultSystemKey?: string;
}) {
  const t = useT();
  const [rows, setRows] = useState<CategoryRow[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const defaultApplied = useRef(false);

  useEffect(() => {
    let live = true;
    api<CategoryRow[]>("/inventory/categories")
      .then((cats) => {
        if (live) setRows(cats);
      })
      .catch(() => {
        if (live) setRows([]);
      });
    return () => {
      live = false;
    };
  }, []);

  // The standing default (battery form → the Batteries
  // starter), applied once, only into an untouched empty value.
  useEffect(() => {
    if (defaultApplied.current || !defaultSystemKey || rows === null) return;
    defaultApplied.current = true;
    if (value !== "") return;
    const starter = rows.find((row) => row.system_key === defaultSystemKey);
    if (starter) onChange(starter.name);
    // The value at load time is the form's initial value by
    // construction; later edits are the owner's, never the
    // default's business.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, defaultSystemKey]);

  // A stored spelling variant of a registry name ("power
  // tools" filed years ago) IS that category: the select shows
  // the registry spelling. The form value itself only changes
  // if the owner actually picks — display never rewrites data.
  const matchedRow =
    rows !== null && value !== ""
      ? rows.find((row) => fold(row.name) === fold(value))
      : undefined;
  const legacyValue = value !== "" && rows !== null && !matchedRow ? value : null;
  const selectValue = adding ? ADD_NEW : (matchedRow ? matchedRow.name : value);

  async function createCategory() {
    const name = draft.trim();
    if (!name || busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await api<CategoryRow>("/inventory/categories", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      // The API folds duplicates onto the existing category —
      // its response name is the canonical spelling to file
      // under (never auto-starred: no `starred` is sent).
      setRows((prev) =>
        prev === null || prev.some((row) => fold(row.name) === fold(created.name))
          ? prev
          : [...prev, created],
      );
      onChange(created.name);
      setDraft("");
      setAdding(false);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("inventory.categoryCreateFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Select
        id={id}
        value={selectValue}
        onChange={(e) => {
          if (e.target.value === ADD_NEW) {
            setAdding(true);
            return;
          }
          onChange(e.target.value);
        }}
      >
        <option value="">{t("inventory.categoryNone")}</option>
        {(rows ?? []).map((row) => (
          <option key={row.name} value={row.name}>
            {categoryDisplayName(t, row)}
          </option>
        ))}
        {legacyValue !== null && (
          <option value={legacyValue}>{legacyValue}</option>
        )}
        {rows === null && value !== "" && (
          // The list is still loading: keep the current value
          // selectable so the control never flashes empty.
          <option value={value}>{value}</option>
        )}
        <option value={ADD_NEW}>{t("inventory.categoryAddNew")}</option>
      </Select>
      {adding && (
        <div style={addRowStyle}>
          <TextInput
            aria-label={t("inventory.categoryNewName")}
            placeholder={t("inventory.categoryNewName")}
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void createCategory();
              }
              if (e.key === "Escape") {
                setAdding(false);
                setDraft("");
                setError("");
              }
            }}
          />
          <Button
            type="button"
            size="sm"
            loading={busy}
            disabled={!draft.trim()}
            onClick={() => void createCategory()}
          >
            {t("inventory.categoryAdd")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setAdding(false);
              setDraft("");
              setError("");
            }}
          >
            {t("common.cancel")}
          </Button>
        </div>
      )}
      {error && <p style={errorStyle}>{error}</p>}
    </div>
  );
}
