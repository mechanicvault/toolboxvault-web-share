import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  EmptyState,
  Panel,
  Select,
  Spinner,
  TagChip,
  TAG_COLORS,
  TextInput,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import type { CategoryRow, Tag } from "./types";
import { categoryDisplayName } from "./categoryLabel";

// Star controls (owner spec 2026-10-24). Const style objects —
// the inline-style ratchet counts inline style literals, not
// shared consts, and this page adds none.
const starWrapStyle = {
  position: "relative",
  display: "inline-flex",
} as const;

const starBtnStyle = {
  background: "none",
  border: "none",
  cursor: "pointer",
  fontSize: "1.15rem",
  lineHeight: 1,
  padding: "0.15rem",
  color: "var(--text-muted)",
} as const;

const starBtnOnStyle = { ...starBtnStyle, color: "var(--accent)" } as const;

const starTipStyle = {
  position: "absolute",
  bottom: "calc(100% + 0.45rem)",
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 30,
  whiteSpace: "nowrap",
  background: "var(--surface-raised)",
  color: "var(--text)",
  border: "1px solid var(--edge-strong)",
  borderRadius: "var(--radius-sm)",
  boxShadow: "0 8px 20px rgb(0 0 0 / 0.35)",
  padding: "0.4rem 0.6rem",
  fontSize: "0.85rem",
  fontWeight: 600,
  pointerEvents: "none",
} as const;

const counterStyle = {
  color: "var(--text-muted)",
  fontSize: "0.85rem",
} as const;

// Section wrappers for the URL-driven landing (the Inventory
// hamburger's Edit tags / Edit categories): the target section
// flashes briefly so the landing reads — the page itself always
// lands at scrollY=0 (B-01), it never scrolls to the section.
const sectionWrapStyle = { display: "grid" } as const;

const sectionFlashStyle = {
  display: "grid",
  outline: "2px solid var(--accent)",
  outlineOffset: "4px",
  borderRadius: "var(--radius-md)",
} as const;

/** The star cap (owner spec 2026-10-25, cut from 10 to 5 so
 *  the Inventory row fits one line). The server enforces it;
 *  this is the client's instant-feedback copy of the number. */
const STAR_LIMIT = 5;

/** A category's star toggle, with the cap tooltip anchored to
 *  it. `tip` is non-null only while this control shows the
 *  "up to 5" bubble. */
function StarToggle({
  starred,
  label,
  tip,
  disabled,
  onToggle,
}: {
  starred: boolean;
  label: string;
  tip: string | null;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <span style={starWrapStyle}>
      <button
        type="button"
        aria-pressed={starred}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onToggle}
        style={starred ? starBtnOnStyle : starBtnStyle}
      >
        {starred ? "★" : "☆"}
      </button>
      {tip && (
        <span role="tooltip" style={starTipStyle}>
          {tip}
        </span>
      )}
    </span>
  );
}

/**
 * Categories & tags manager (gap wave 1). Categories are the
 * free-text filing vocabulary on items; this surface gives it
 * control: see every category WITH its item count, create one
 * (it can sit empty), rename it (the new name lands on every
 * item), merge one into another, or delete it — which DETACHES
 * the items (they become uncategorized; items are never
 * deleted). Names fold case-insensitively, the importer's rule:
 * "Power Tools" and "power tools" are one category.
 *
 * Tags sit beside them: rename (cascades the same way), recolor
 * from the fixed palette, delete.
 *
 * Categories also carry a star (owner spec 2026-10-24): up to
 * five starred categories ride the Inventory view row as
 * shortcut links. The cap lives on the server; hitting it shows
 * a tooltip at the star, never an alert. A category can be born
 * starred from the create form. `?section=tags|categories`
 * lands the page on one section (the Inventory hamburger's
 * Edit tags / Edit categories items).
 *
 * Four categories are preinstalled starters (owner spec
 * 2026-10-25): Batteries, Hand Tools, Power Tools, Pneumatic
 * Tools — seeded starred for every account. They show a
 * "Built-in" mark and offer no Delete (and no merge-away);
 * Batteries offers no Rename either (its name is wired to
 * battery records). Unstarring stays available for all four.
 */
export default function CategoriesPage() {
  return (
    <RequireAuth>
      <CategoriesContent />
    </RequireAuth>
  );
}

function CategoriesContent() {
  const { toast } = useToast();
  const t = useT();
  const [searchParams] = useSearchParams();
  const [categories, setCategories] = useState<CategoryRow[] | null>(null);
  const [tags, setTags] = useState<Tag[] | null>(null);
  const [error, setError] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [newStarred, setNewStarred] = useState(false);
  const [newTag, setNewTag] = useState("");
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({});
  const [mergeTargets, setMergeTargets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  // Which control currently shows the star-cap tooltip: a
  // category name, "__create__" for the create form's star, or
  // null. Dismisses on a timer, the next pointer-down anywhere,
  // or Esc — whichever comes first.
  const [capTip, setCapTip] = useState<string | null>(null);
  const capTipTimer = useRef<number | null>(null);
  // Section the URL asked to land on ("tags" | "categories"),
  // flashed briefly after the scroll.
  const [flash, setFlash] = useState<string | null>(null);

  const starredCount = categories?.filter((c) => c.starred).length ?? 0;

  function showCapTip(key: string) {
    setCapTip(key);
    if (capTipTimer.current) window.clearTimeout(capTipTimer.current);
    capTipTimer.current = window.setTimeout(() => setCapTip(null), 4500);
  }

  useEffect(() => {
    if (!capTip) return;
    const dismiss = () => setCapTip(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", onKey);
    };
  }, [capTip]);

  // URL-driven section landing (Inventory hamburger → Edit tags
  // / Edit categories): flash the asked-for section so the
  // landing reads, but NEVER scroll to it (B-01, Deep Audit
  // Round 2): every PUSH landing sits at scrollY=0 like every
  // other route — the old scrollIntoView here was the only
  // scroll-0 miss in 32 probed routes, settling these two
  // landings at scrollY=37 once the lists loaded. The flash
  // waits until BOTH lists have loaded, once per URL, so later
  // data changes (starring, creating) never re-flash.
  const handledSection = useRef<string | null>(null);
  useEffect(() => {
    const section = searchParams.get("section");
    if (section !== "tags" && section !== "categories") return;
    const key = searchParams.toString();
    if (handledSection.current === key) return;
    if (categories === null || tags === null) return;
    const el = document.getElementById(
      section === "tags" ? "tags-section" : "categories-section",
    );
    if (!el) return;
    handledSection.current = key;
    setFlash(section);
    const timer = window.setTimeout(() => setFlash(null), 2000);
    return () => window.clearTimeout(timer);
  }, [searchParams, categories, tags]);

  const load = useCallback(() => {
    Promise.all([
      api<CategoryRow[]>("/inventory/categories"),
      api<Tag[]>("/inventory/tags"),
    ])
      .then(([cats, tagRows]) => {
        setCategories(cats);
        setTags(tagRows);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load the manager."),
      );
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast(ok, { title: "Done", tone: "success" });
      load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't work.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onCreateCategory(event: FormEvent) {
    event.preventDefault();
    if (!newCategory.trim()) return;
    setBusy(true);
    try {
      const created = await api<CategoryRow>("/inventory/categories", {
        method: "POST",
        body: JSON.stringify({ name: newCategory.trim(), starred: newStarred }),
      });
      toast("Category saved.", { title: "Done", tone: "success" });
      setNewCategory("");
      setNewStarred(false);
      load();
      // Born-starred was asked for but the cap was full: the
      // category exists (unstarred) and the star control says
      // why — the limit blocks the star, never the category.
      if (created.star_capped) showCapTip("__create__");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't work.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  /** Star/unstar one category in place. The cap is checked
   *  here for an instant tooltip and AGAIN on the server (the
   *  409's `star_limit_reached` code lands in the same tooltip)
   *  — the server is the enforcement, this is just the feel. */
  async function toggleStar(cat: CategoryRow) {
    if (!cat.starred && starredCount >= STAR_LIMIT) {
      showCapTip(cat.name);
      return;
    }
    setBusy(true);
    try {
      const updated = await api<CategoryRow>("/inventory/categories/star", {
        method: "POST",
        body: JSON.stringify({ name: cat.name, starred: !cat.starred }),
      });
      setCategories(
        (prev) =>
          prev?.map((c) =>
            c.name === cat.name
              ? { ...c, starred: updated.starred, registered: updated.registered }
              : c,
          ) ?? prev,
      );
    } catch (err) {
      if (err instanceof ApiError && err.code === "star_limit_reached") {
        showCapTip(cat.name);
      } else {
        toast(err instanceof ApiError ? err.message : "That didn't work.", {
          title: "Something went wrong",
          tone: "danger",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  function toggleNewStar() {
    if (!newStarred && starredCount >= STAR_LIMIT) {
      showCapTip("__create__");
      return;
    }
    setNewStarred((v) => !v);
  }

  async function onCreateTag(event: FormEvent) {
    event.preventDefault();
    if (!newTag.trim()) return;
    await run(
      () =>
        api("/inventory/tags", {
          method: "POST",
          body: JSON.stringify({ name: newTag.trim(), color: "amber" }),
        }),
      "Tag created.",
    );
    setNewTag("");
  }

  const rowStyle = {
    display: "flex",
    gap: "0.6rem",
    alignItems: "center",
    flexWrap: "wrap",
    borderTop: "1px solid var(--edge)",
    padding: "0.6rem 0",
  } as const;

  return (
    <div style={{ display: "grid", gap: "var(--spacing)", maxWidth: "880px" }}>
      <div>
        <h1 style={{ margin: "0 0 0.25rem", fontSize: "1.6rem" }}>Categories &amp; tags</h1>
        <p style={{ margin: 0, color: "var(--text-muted)" }}>
          The filing vocabulary for your inventory. Renames land on
          every item at once; deleting a category never deletes
          items — they just become uncategorized.
        </p>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}

      <div
        id="categories-section"
        style={flash === "categories" ? sectionFlashStyle : sectionWrapStyle}
      >
      <Panel
        title="Categories"
        actions={
          <span style={counterStyle}>
            {t("inventory.starredCount").replace("{count}", String(starredCount))}
          </span>
        }
      >
        {categories === null ? (
          <Spinner size="sm" />
        ) : (
          <div style={{ display: "grid", gap: "0.2rem" }}>
            {categories.length === 0 && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No categories yet — file an item under one, or create it here.
              </p>
            )}
            {categories.map((cat) => {
              const draft = renameDrafts[cat.name] ?? cat.name;
              const target = mergeTargets[cat.name] ?? "";
              return (
                <div key={cat.name} style={rowStyle}>
                  <StarToggle
                    starred={cat.starred}
                    label={t(
                      cat.starred
                        ? "inventory.unstarCategory"
                        : "inventory.starCategory",
                    ).replace("{name}", cat.name)}
                    tip={capTip === cat.name ? t("inventory.starLimitTip") : null}
                    disabled={busy}
                    onToggle={() => void toggleStar(cat)}
                  />
                  <strong style={{ minWidth: "10rem" }}>{categoryDisplayName(t, cat)}</strong>
                  <span style={{ color: "var(--text-muted)" }}>
                    {cat.item_count} item{cat.item_count === 1 ? "" : "s"}
                  </span>
                  {cat.preinstalled && (
                    <span style={counterStyle}>{t("inventory.categoryBuiltIn")}</span>
                  )}
                  {cat.system_key !== "batteries" && (
                    <>
                      <TextInput
                        aria-label={`Rename ${cat.name}`}
                        value={draft}
                        onChange={(e) =>
                          setRenameDrafts({ ...renameDrafts, [cat.name]: e.target.value })
                        }
                        style={{ flex: "1 1 160px" }}
                      />
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={busy || draft.trim() === "" || draft === cat.name}
                        onClick={() =>
                          void run(
                            () =>
                              api("/inventory/categories/rename", {
                                method: "POST",
                                body: JSON.stringify({
                                  old_name: cat.name,
                                  new_name: draft.trim(),
                                }),
                              }),
                            `Renamed to “${draft.trim()}” — every item updated.`,
                          )
                        }
                      >
                        Rename
                      </Button>
                    </>
                  )}
                  {categories.length > 1 && !cat.preinstalled && (
                    <>
                      <Select
                        aria-label={`Merge ${cat.name} into`}
                        value={target}
                        onChange={(e) =>
                          setMergeTargets({ ...mergeTargets, [cat.name]: e.target.value })
                        }
                      >
                        <option value="">Merge into…</option>
                        {categories
                          .filter((c) => c.name !== cat.name)
                          .map((c) => (
                            <option key={c.name} value={c.name}>
                              {c.name}
                            </option>
                          ))}
                      </Select>
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={busy || !target}
                        onClick={() =>
                          void run(
                            () =>
                              api("/inventory/categories/merge", {
                                method: "POST",
                                body: JSON.stringify({
                                  source_name: cat.name,
                                  target_name: target,
                                }),
                              }),
                            `Merged into “${target}”.`,
                          )
                        }
                      >
                        Merge
                      </Button>
                    </>
                  )}
                  {!cat.preinstalled && (
                    <Button
                      type="button"
                      variant="danger"
                      disabled={busy}
                      onClick={() => {
                        if (
                          !window.confirm(
                            `Delete the category “${cat.name}”? Its ${cat.item_count} item${cat.item_count === 1 ? "" : "s"} become uncategorized — nothing is deleted.`,
                          )
                        )
                          return;
                        void run(
                          () =>
                            api("/inventory/categories/delete", {
                              method: "POST",
                              body: JSON.stringify({ name: cat.name }),
                            }),
                          "Category deleted — items detached.",
                        );
                      }}
                    >
                      Delete
                    </Button>
                  )}
                </div>
              );
            })}
            <form
              onSubmit={(e) => void onCreateCategory(e)}
              style={{ display: "flex", gap: "0.5rem", marginTop: "0.8rem", flexWrap: "wrap", alignItems: "center" }}
            >
              <StarToggle
                starred={newStarred}
                label={t("inventory.starNewCategory")}
                tip={capTip === "__create__" ? t("inventory.starLimitTip") : null}
                disabled={busy}
                onToggle={toggleNewStar}
              />
              <TextInput
                aria-label="New category name"
                placeholder="New category"
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
                style={{ flex: "1 1 200px" }}
              />
              <Button type="submit" loading={busy} disabled={!newCategory.trim()}>
                Add category
              </Button>
            </form>
          </div>
        )}
      </Panel>
      </div>

      <div
        id="tags-section"
        style={flash === "tags" ? sectionFlashStyle : sectionWrapStyle}
      >
      <Panel title="Tags">
        {tags === null ? (
          <Spinner size="sm" />
        ) : (
          <div style={{ display: "grid", gap: "0.2rem" }}>
            {tags.length === 0 && (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No tags yet — create one here or on any item form.
              </p>
            )}
            {tags.map((tag) => {
              const draft = renameDrafts[`tag:${tag.id}`] ?? tag.name;
              return (
                <div key={tag.id} style={rowStyle}>
                  <TagChip name={tag.name} color={tag.color} />
                  <span style={{ color: "var(--text-muted)" }}>
                    {tag.item_count ?? 0} item{(tag.item_count ?? 0) === 1 ? "" : "s"}
                  </span>
                  <TextInput
                    aria-label={`Rename tag ${tag.name}`}
                    value={draft}
                    onChange={(e) =>
                      setRenameDrafts({ ...renameDrafts, [`tag:${tag.id}`]: e.target.value })
                    }
                    style={{ flex: "1 1 140px" }}
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={busy || draft.trim() === "" || draft === tag.name}
                    onClick={() =>
                      void run(
                        () =>
                          api(`/inventory/tags/${tag.id}`, {
                            method: "PUT",
                            body: JSON.stringify({ name: draft.trim() }),
                          }),
                        "Tag renamed everywhere.",
                      )
                    }
                  >
                    Rename
                  </Button>
                  <span style={{ display: "inline-flex", gap: "0.25rem", flexWrap: "wrap" }}>
                    {TAG_COLORS.map((color) => (
                      <button
                        key={color}
                        type="button"
                        title={color}
                        aria-label={`Set ${tag.name} color to ${color}`}
                        aria-pressed={tag.color === color}
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () =>
                              api(`/inventory/tags/${tag.id}`, {
                                method: "PUT",
                                body: JSON.stringify({ color }),
                              }),
                            "Tag color updated.",
                          )
                        }
                        style={{
                          width: "1.1rem",
                          height: "1.1rem",
                          borderRadius: "50%",
                          border:
                            tag.color === color
                              ? "2px solid var(--text)"
                              : "1px solid var(--edge-strong)",
                          background: `var(--tag-${color})`,
                          cursor: "pointer",
                          padding: 0,
                        }}
                      />
                    ))}
                  </span>
                  <Button
                    type="button"
                    variant="danger"
                    disabled={busy}
                    onClick={() => {
                      if (!window.confirm(`Delete the tag “${tag.name}”? Items keep everything else.`))
                        return;
                      void run(
                        () => api(`/inventory/tags/${tag.id}`, { method: "DELETE" }),
                        "Tag deleted.",
                      );
                    }}
                  >
                    Delete
                  </Button>
                </div>
              );
            })}
            <form
              onSubmit={(e) => void onCreateTag(e)}
              style={{ display: "flex", gap: "0.5rem", marginTop: "0.8rem", flexWrap: "wrap" }}
            >
              <TextInput
                aria-label="New tag name"
                placeholder="New tag"
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                style={{ flex: "1 1 200px" }}
              />
              <Button type="submit" loading={busy} disabled={!newTag.trim()}>
                Add tag
              </Button>
            </form>
          </div>
        )}
      </Panel>
      </div>

      {categories !== null && categories.length === 0 && tags !== null && tags.length === 0 && (
        <EmptyState title="Nothing to manage yet" />
      )}
    </div>
  );
}
