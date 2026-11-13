import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormField,
  Panel,
  Select,
  Spinner,
  TextInput,
  Toggle,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api"
import { useT } from "../../i18n/LocaleContext";
import { plural } from "../../lib/format";
import { accountTypeLabel } from "./accountTypes";
import PeerSharingSettings from "./PeerSharingSettings";
import {
  LOCKED_SHARE_FIELDS,
  OPTIONAL_SHARE_FIELDS,
  type ShareGroupState,
  type ShareRecipientGroup,
  type ShareRule,
  type ShareRuleScope,
  type SharingOverview,
} from "./sharing";

/**
 * Settings → Sharing (consent sharing, owner directive 2026-10-17).
 *
 * A mechanic can share their tool list with the shop group and/or
 * the insurance group — per group: an on/off switch, the fields
 * that group may see (identity fields are locked on), and the items
 * (all / none / per item). Everything here is opt-in and lives only
 * on this settings page; nothing in the daily inventory flow changes
 * for users who never open it. Saving is per group: config first,
 * then the item set (the API replaces the set wholesale).
 *
 * The panel's third section is People (PeerSharingSettings):
 * person-to-person list sharing for borrowing — a separate system
 * with a fixed minimal payload, managed from the same panel.
 */

interface GroupDraft {
  enabled: boolean;
  fields: Set<string>;
  selected: Set<string>;
  /** Per-set addon choices (tool id -> include addons?). Sets ask
   *  "include addon pieces?" wherever they're shared; the choice
   *  is stored with the share. */
  setChoices: Map<string, boolean>;
  /** Package C: items withheld from this group even when picked
   *  or matched by a rule (exclusions are the final word). Saved
   *  with the group, wholesale like the picks. */
  excluded: Set<string>;
}

function savedSelected(state: ShareGroupState): Set<string> {
  // Item ids are unique across tools and batteries (UUIDs), so one
  // selection set carries both kinds; the kind split happens at save.
  return new Set([...state.shared_tool_ids, ...state.shared_battery_ids]);
}

function savedExcluded(state: ShareGroupState): Set<string> {
  return new Set((state.excluded_items ?? []).map((r) => r.id));
}

function draftFrom(state: ShareGroupState): GroupDraft {
  return {
    enabled: state.enabled,
    fields: new Set(state.fields),
    selected: savedSelected(state),
    setChoices: new Map(
      (state.set_choices ?? []).map((c) => [c.tool_id, c.include_addons]),
    ),
    excluded: savedExcluded(state),
  };
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  return a.size === b.size && [...a].every((v) => b.has(v));
}

const RULE_SCOPE_LABELS: Record<ShareRuleScope, string> = {
  category: "Category",
  location: "Location",
  tag: "Tag",
  all: "Everything",
};

/**
 * The rules editor for one group (Package C): sharing that follows
 * RULES instead of one-by-one picking. A rule matches by category,
 * by location (the whole subtree under a toolbox/place), by tag,
 * or everything — and resolves LIVE, so an item bought tomorrow
 * into a shared category or toolbox is shared with no further
 * action. Rules save immediately (each add/remove/update is its
 * own call returning the group's fresh state); the include-addons
 * answer for matched sets is asked here, per rule.
 */
function GroupRulesEditor({
  group,
  overview,
  onSaved,
}: {
  group: ShareRecipientGroup;
  overview: SharingOverview;
  onSaved: (state: ShareGroupState) => void;
}) {
  const { toast } = useToast();
  const saved = overview.groups.find((g) => g.recipient_group === group);
  const [scope, setScope] = useState<ShareRuleScope>("category");
  const [categoryChoice, setCategoryChoice] = useState("");
  const [categoryText, setCategoryText] = useState("");
  const [refId, setRefId] = useState("");
  const [addons, setAddons] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!saved) return null;
  const rules = saved.rules ?? [];
  const label = accountTypeLabel(group);
  const newCategory = categoryChoice === "__new__";
  const categoryValue = newCategory ? categoryText : categoryChoice;

  async function apply(promise: Promise<ShareGroupState>, message: string) {
    setError(null);
    setBusy(true);
    try {
      const state = await promise;
      onSaved(state);
      toast(message, { tone: "success", title: "Saved", duration: 8000 });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save that rule.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function addRule() {
    const body: Record<string, unknown> = {
      scope,
      include_addons: addons,
    };
    if (scope === "category") body.scope_value = categoryValue.trim();
    if (scope === "location" || scope === "tag") body.scope_ref_id = refId;
    await apply(
      api<ShareGroupState>(`/core/sharing/${group}/rules`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
      `Rule added for ${label}.`,
    );
    setCategoryChoice("");
    setCategoryText("");
    setRefId("");
    setAddons(false);
  }

  const canAdd =
    scope === "all" ||
    (scope === "category" && categoryValue.trim().length > 0) ||
    ((scope === "location" || scope === "tag") && refId !== "");

  return (
    <div>
      <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-1)" }}>
        Share by rule
      </p>
      <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
        Instead of picking items one by one: everything in a category,
        everything filed under a location (a toolbox and all its
        drawers), everything with a tag — or your whole inventory.
        Rules apply the moment an item matches, including items you
        add later. An item you exclude above stays out even when a
        rule matches it.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      {rules.length === 0 ? (
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
          No rules yet for {label}.
        </p>
      ) : (
        <div style={{ display: "grid", gap: "0.5rem", marginBottom: "var(--space-2)" }}>
          {rules.map((rule: ShareRule) => (
            <div
              key={rule.id}
              style={{
                border: "1px solid var(--edge)",
                borderRadius: "var(--radius)",
                padding: "0.6rem 0.75rem",
                display: "grid",
                gap: "0.35rem",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "1rem",
                  flexWrap: "wrap",
                }}
              >
                <span>
                  <strong>{RULE_SCOPE_LABELS[rule.scope]}</strong>
                  {rule.scope !== "all" && <> — {rule.scope_label}</>}
                  <span style={{ color: "var(--text-muted)" }}>
                    {" "}
                    · sharing {rule.match_count} item
                    {rule.match_count === 1 ? "" : "s"} now
                  </span>
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    apply(
                      api<ShareGroupState>(
                        `/core/sharing/${group}/rules/${rule.id}`,
                        { method: "DELETE" },
                      ),
                      `Rule removed for ${label}.`,
                    )
                  }
                >
                  Remove rule
                </Button>
              </div>
              <Checkbox
                name={`share-${group}-rule-addons-${rule.id}`}
                checked={rule.include_addons}
                disabled={busy}
                onChange={(e) =>
                  apply(
                    api<ShareGroupState>(
                      `/core/sharing/${group}/rules/${rule.id}`,
                      {
                        method: "PUT",
                        body: JSON.stringify({
                          include_addons: e.target.checked,
                        }),
                      },
                    ),
                    `Rule updated for ${label}.`,
                  )
                }
                label="When a set matches, include its addon pieces & attached tools?"
              />
            </div>
          ))}
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "flex-end",
          flexWrap: "wrap",
        }}
      >
        <FormField label="Rule type">
          <Select
            value={scope}
            onChange={(e) => setScope(e.target.value as ShareRuleScope)}
            aria-label="Rule type"
          >
            <option value="category">Category</option>
            <option value="location">Location</option>
            <option value="tag">Tag</option>
            <option value="all">Everything</option>
          </Select>
        </FormField>
        {scope === "category" && (
          <>
            {overview.categories.length > 0 && (
              <FormField label="Category">
                <Select
                  value={categoryChoice}
                  onChange={(e) => setCategoryChoice(e.target.value)}
                  aria-label="Category"
                >
                  <option value="">Choose a category…</option>
                  {overview.categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                  <option value="__new__">Type a new category…</option>
                </Select>
              </FormField>
            )}
            {(newCategory || overview.categories.length === 0) && (
              <FormField label="New category">
                <TextInput
                  value={categoryText}
                  onChange={(e) => setCategoryText(e.target.value)}
                  placeholder="e.g. Wrenches"
                  aria-label="New category"
                />
              </FormField>
            )}
          </>
        )}
        {scope === "location" && (
          <FormField label="Location">
            <Select
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              aria-label="Location"
            >
              <option value="">Choose a location…</option>
              {overview.locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.path} ({plural(loc.subtree_item_count, "item")})
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {scope === "tag" && (
          <FormField label="Tag">
            <Select
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              aria-label="Tag"
            >
              <option value="">Choose a tag…</option>
              {overview.tags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name} ({plural(tag.item_count, "item")})
                </option>
              ))}
            </Select>
          </FormField>
        )}
        <Button
          type="button"
          variant="secondary"
          disabled={busy || !canAdd}
          onClick={addRule}
        >
          Add rule
        </Button>
      </div>
      <div style={{ marginTop: "0.35rem" }}>
        <Checkbox
          name={`share-${group}-new-rule-addons`}
          checked={addons}
          onChange={(e) => setAddons(e.target.checked)}
          label="When a set matches the new rule, include its addon pieces & attached tools?"
        />
      </div>
    </div>
  );
}

function GroupSharingEditor({
  group,
  overview,
  onSaved,
}: {
  group: ShareRecipientGroup;
  overview: SharingOverview;
  onSaved: (state: ShareGroupState) => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const saved = overview.groups.find((g) => g.recipient_group === group);
  const [draft, setDraft] = useState<GroupDraft | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Initialize (and re-sync after a save) from the server state.
  useEffect(() => {
    if (saved) setDraft(draftFrom(saved));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    saved?.enabled,
    saved?.fields.join(","),
    saved?.shared_tool_ids.join(","),
    saved?.shared_battery_ids.join(","),
    JSON.stringify(saved?.set_choices ?? []),
    (saved?.excluded_items ?? []).map((r) => r.id).join(","),
  ]);

  const visibleItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return overview.items;
    return overview.items.filter((item) =>
      [item.name, item.brand, item.model, item.serial_number]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [overview.items, query]);

  if (!saved || !draft) return null;

  const savedChoices = new Map(
    (saved.set_choices ?? []).map((c) => [c.tool_id, c.include_addons]),
  );
  const choicesDirty = overview.items.some((item) => {
    if (!item.is_set || !draft.selected.has(item.id)) return false;
    return (draft.setChoices.get(item.id) ?? false) !== (savedChoices.get(item.id) ?? false);
  });
  const dirty =
    draft.enabled !== saved.enabled ||
    !sameSet(draft.fields, new Set(saved.fields)) ||
    !sameSet(draft.selected, savedSelected(saved)) ||
    !sameSet(draft.excluded, savedExcluded(saved)) ||
    choicesDirty;

  function toggleField(key: string, on: boolean) {
    setDraft((d) => {
      if (!d) return d;
      const fields = new Set(d.fields);
      if (on) fields.add(key);
      else fields.delete(key);
      return { ...d, fields };
    });
  }

  function toggleItem(id: string, on: boolean) {
    setDraft((d) => {
      if (!d) return d;
      const selected = new Set(d.selected);
      if (on) selected.add(id);
      else selected.delete(id);
      return { ...d, selected };
    });
  }

  function toggleExcluded(id: string, on: boolean) {
    setDraft((d) => {
      if (!d) return d;
      const excluded = new Set(d.excluded);
      if (on) excluded.add(id);
      else excluded.delete(id);
      return { ...d, excluded };
    });
  }

  async function onSave() {
    if (!draft) return;
    setError(null);
    setSaving(true);
    try {
      const config = await api<ShareGroupState>(`/core/sharing/${group}`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: draft.enabled,
          fields: OPTIONAL_SHARE_FIELDS.map((f) => f.key).filter((k) =>
            draft.fields.has(k),
          ),
        }),
      });
      const kindOf = new Map(overview.items.map((i) => [i.id, i.kind]));
      await api<ShareGroupState>(`/core/sharing/${group}/items`, {
        method: "PUT",
        body: JSON.stringify({
          tool_ids: [...draft.selected].filter(
            (id) => kindOf.get(id) !== "battery",
          ),
          battery_ids: [...draft.selected].filter(
            (id) => kindOf.get(id) === "battery",
          ),
          set_choices: overview.items
            .filter((i) => i.is_set && draft.selected.has(i.id))
            .map((i) => ({
              tool_id: i.id,
              include_addons: draft.setChoices.get(i.id) ?? false,
            })),
        }),
      });
      // Exclusions ride the same save (Package C): items withheld
      // even when a pick or a rule would share them.
      const items = await api<ShareGroupState>(
        `/core/sharing/${group}/exclusions`,
        {
          method: "PUT",
          body: JSON.stringify({
            tool_ids: [...draft.excluded].filter(
              (id) => kindOf.get(id) !== "battery",
            ),
            battery_ids: [...draft.excluded].filter(
              (id) => kindOf.get(id) === "battery",
            ),
          }),
        },
      );
      onSaved({ ...items, enabled: config.enabled, fields: config.fields });
      // Titled + longer-lived than the default toast: a settings
      // save's only feedback is this toast (browser QA, 2026-10-17:
      // the plain 5s toast was missed entirely), so it must be
      // unmissable — same shape as the People section's saves below.
      toast(`Sharing updated for ${accountTypeLabel(group)}.`, {
        tone: "success",
        title: "Saved",
        duration: 8000,
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't save sharing settings. Try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  const label = accountTypeLabel(group);

  return (
    <div
      style={{
        borderTop: "1px solid var(--edge)",
        paddingTop: "1rem",
        display: "grid",
        gap: "var(--space-3)",
      }}
    >
      <div
        className="tv-setting-row"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
        }}
      >
        <p className="tv-setting-row-name">Share with: {label}</p>
        <Toggle
          checked={draft.enabled}
          onChange={(on) => setDraft((d) => (d ? { ...d, enabled: on } : d))}
          label={
            draft.enabled
              ? t("sharing.groupToggle.sharing")
              : t("sharing.groupToggle.notSharing")
          }
          ariaLabel={`Share my tool list with ${label}`}
        />
      </div>

      {error && <Alert tone="danger">{error}</Alert>}

      <div>
        <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
          What they can see
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fill, minmax(min(180px, 100%), 1fr))",
            gap: "0.35rem 1rem",
          }}
        >
          {LOCKED_SHARE_FIELDS.map((f) => (
            <Checkbox
              key={f.key}
              label={f.label}
              checked
              disabled
              name={`share-${group}-locked-${f.key}`}
            />
          ))}
          {OPTIONAL_SHARE_FIELDS.map((f) => (
            <Checkbox
              key={f.key}
              label={f.label}
              checked={draft.fields.has(f.key)}
              onChange={(e) => toggleField(f.key, e.target.checked)}
              name={`share-${group}-field-${f.key}`}
            />
          ))}
        </div>
        <p style={{ color: "var(--text-muted)", margin: "0.35rem 0 0" }}>
          Name, brand, model, and serial number are always shared — a
          recipient has to be able to tell which tool is which.
          Everything else is your choice.
        </p>
      </div>

      <div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
            flexWrap: "wrap",
          }}
        >
          <p className="tv-setting-row-name">Which items</p>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            Sharing {saved.resolved_count} of {overview.items.length} items
            {" — "}
            {draft.selected.size} picked
            {(saved.rules ?? []).length > 0 &&
              `, ${(saved.rules ?? []).length} rule${(saved.rules ?? []).length === 1 ? "" : "s"}`}
            {draft.excluded.size > 0 && `, ${draft.excluded.size} excluded`}
          </p>
        </div>
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            alignItems: "center",
            margin: "var(--space-2) 0",
            flexWrap: "wrap",
          }}
        >
          <div style={{ flex: "1 1 200px" }}>
            <TextInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search your items…"
              aria-label="Search your items"
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() =>
              setDraft((d) =>
                d
                  ? {
                      ...d,
                      selected: new Set(overview.items.map((i) => i.id)),
                    }
                  : d,
              )
            }
          >
            Select all
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() =>
              setDraft((d) => (d ? { ...d, selected: new Set() } : d))
            }
          >
            Select none
          </Button>
        </div>
        {overview.items.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            You don't have any items yet — add tools or batteries in
            Inventory and they'll show up here.
          </p>
        ) : visibleItems.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            No items match that search.
          </p>
        ) : (
          <div
            style={{
              display: "grid",
              gap: "0.35rem",
              maxHeight: "260px",
              overflowY: "auto",
              border: "1px solid var(--edge)",
              borderRadius: "var(--radius)",
              padding: "0.6rem 0.75rem",
            }}
          >
            {visibleItems.map((item) => {
              const picked = draft.selected.has(item.id);
              const excluded = draft.excluded.has(item.id);
              // Server truth: in the resolved set without being
              // picked means a rule is carrying this item.
              const byRule =
                !picked &&
                (saved.resolved_items ?? []).some((r) => r.id === item.id);
              return (
              <div key={item.id}>
                <Checkbox
                  name={`share-${group}-item-${item.id}`}
                  checked={picked}
                  onChange={(e) => toggleItem(item.id, e.target.checked)}
                  label={
                    <>
                      {item.name}
                      {item.kind === "battery" && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {" "}
                          · Battery
                        </span>
                      )}
                      {item.is_set && (
                        <span style={{ color: "var(--text-muted)" }}> · Set</span>
                      )}
                      {(item.brand || item.model) && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {" "}
                          — {[item.brand, item.model]
                            .filter(Boolean)
                            .join(" ")}
                        </span>
                      )}
                      {byRule && !excluded && (
                        <span style={{ color: "var(--text-muted)" }}>
                          {" "}
                          · Shared by rule
                        </span>
                      )}
                      {excluded && (
                        <span style={{ fontWeight: 600 }}>
                          {" "}
                          · Excluded — won't be shared
                        </span>
                      )}
                    </>
                  }
                />
                {item.is_set && picked && (
                  <div style={{ marginLeft: "1.6rem", marginTop: "0.15rem" }}>
                    <Checkbox
                      name={`share-${group}-set-addons-${item.id}`}
                      checked={draft.setChoices.get(item.id) ?? false}
                      onChange={(e) =>
                        setDraft((d) =>
                          d
                            ? {
                                ...d,
                                setChoices: new Map(d.setChoices).set(
                                  item.id,
                                  e.target.checked,
                                ),
                              }
                            : d,
                        )
                      }
                      label="Include addon pieces & attached tools?"
                    />
                  </div>
                )}
                {(picked || byRule || excluded) && (
                  <div style={{ marginLeft: "1.6rem", marginTop: "0.15rem" }}>
                    <Checkbox
                      name={`share-${group}-exclude-${item.id}`}
                      checked={excluded}
                      onChange={(e) =>
                        toggleExcluded(item.id, e.target.checked)
                      }
                      label="Exclude this item: never share it with this group, even if a rule matches"
                    />
                  </div>
                )}
              </div>
              );
            })}
          </div>
        )}
      </div>

      <GroupRulesEditor group={group} overview={overview} onSaved={onSaved} />

      <div>
        <Button
          type="button"
          loading={saving}
          disabled={!dirty}
          onClick={onSave}
        >
          Save sharing for {label}
        </Button>
      </div>
    </div>
  );
}

export default function SharingSettings() {
  const [overview, setOverview] = useState<SharingOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<SharingOverview>("/core/sharing")
      .then((data) => {
        if (live) setOverview(data);
      })
      .catch((err) => {
        if (live) {
          setLoadError(
            err instanceof ApiError
              ? err.message
              : "Couldn't load sharing settings.",
          );
        }
      });
    return () => {
      live = false;
    };
  }, []);

  function onGroupSaved(state: ShareGroupState) {
    setOverview((o) =>
      o
        ? {
            ...o,
            groups: o.groups.map((g) =>
              g.recipient_group === state.recipient_group ? state : g,
            ),
            items: o.items.map((item) => ({
              ...item,
              shared_with: o.groups
                .map((g) =>
                  g.recipient_group === state.recipient_group
                    ? state
                    : g,
                )
                .filter((g) =>
                  (item.kind === "battery"
                    ? g.shared_battery_ids
                    : g.shared_tool_ids
                  ).includes(item.id),
                )
                .map((g) => g.recipient_group),
            })),
          }
        : o,
    );
  }

  return (
    <Panel title="Sharing" variant="plate" className="tv-sharing-panel">
      <p className="tv-settings-intro" style={{ margin: "0 0 var(--space-3)" }}>
        Most people never need this. If a shop or an insurance company
        needs to see some of your items, this is where you approve
        exactly what they see — which items, and which details on each
        item. Nothing is shared until you turn a group on here.
      </p>
      {loadError && <Alert tone="danger">{loadError}</Alert>}
      {!overview && !loadError && (
        <p
          style={{
            color: "var(--text-muted)",
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "center",
            margin: 0,
          }}
        >
          <Spinner size="sm" /> Loading sharing settings…
        </p>
      )}
      {overview && (
        <div style={{ display: "grid", gap: "var(--space-4)" }}>
          {overview.groups.map((g) => (
            <GroupSharingEditor
              key={g.recipient_group}
              group={g.recipient_group}
              overview={overview}
              onSaved={onGroupSaved}
            />
          ))}
        </div>
      )}
      {/* Third section of this panel: sharing with PEOPLE (peer
          sharing). It fetches its own data, so it renders even if
          the group overview above failed to load. */}
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginTop: "var(--space-4)",
          paddingTop: "1rem",
        }}
      >
        <PeerSharingSettings />
      </div>
      {/* Fourth section (wave 4): the community product catalog
          contribution switch — spec data only, derived live. */}
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginTop: "var(--space-4)",
          paddingTop: "1rem",
        }}
      >
        <CatalogContributionSettings />
      </div>
    </Panel>
  );
}

/** Community catalog contribution (wave 4): the derived catalog
 *  behind Quick Add learns from every contributing account's
 *  items. The switch is a PATCH /me — aggregation reads live
 *  items, so turning it off removes this account's weight from
 *  every aggregate immediately. */
function CatalogContributionSettings() {
  const { toast } = useToast();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api<{ catalog_contribute: boolean }>("/core/me")
      .then((me) => {
        if (live) setEnabled(Boolean(me.catalog_contribute));
      })
      .catch(() => {
        if (live) setEnabled(null);
      });
    return () => {
      live = false;
    };
  }, []);

  async function toggle(next: boolean) {
    setBusy(true);
    try {
      const me = await api<{ catalog_contribute: boolean }>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ catalog_contribute: next }),
      });
      setEnabled(Boolean(me.catalog_contribute));
      toast("Catalog contribution saved", { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save that setting.",
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
        Community product catalog
      </p>
      <p className="tv-settings-intro">
        The catalog helps everyone add tools faster: when two or more
        owners catalogue the same product, the facts they agree on
        (category, size, list price) become a suggestion the next
        person sees in Quick Add.
      </p>
      {enabled === null ? (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          <Spinner size="sm" /> Loading…
        </p>
      ) : (
        <Toggle
          checked={enabled}
          disabled={busy}
          onChange={(on) => void toggle(on)}
          label={enabled ? "Contributing" : "Not contributing"}
          ariaLabel="Contribute my items' spec data to the community catalog"
        />
      )}
      <p className="tv-settings-intro" style={{ marginBottom: 0 }}>
        <strong>What contributes:</strong> brand, model, category,
        size and list price (MSRP) from your tools and batteries.{" "}
        <strong>What never contributes:</strong> serial numbers, the
        prices you paid, photos, and notes — those stay yours alone.
        Turning this off removes your items from the catalog right
        away; nothing about you is ever shown with a suggestion.
      </p>
    </div>
  );
}
