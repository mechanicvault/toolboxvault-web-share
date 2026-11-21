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
  SideList,
  SideListRow,
} from "../../components";
import { api, ApiError } from "../../lib/api"
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
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

const RULE_SCOPE_KEYS: Record<ShareRuleScope, DictKey> = {
  category: "settings.sharing.scopeCategory",
  location: "settings.sharing.scopeLocation",
  tag: "settings.sharing.scopeTag",
  all: "settings.sharing.scopeAll",
};

const FIELD_KEYS: Record<string, DictKey> = {
  name: "settings.sharing.field.name",
  brand: "settings.sharing.field.brand",
  model: "settings.sharing.field.model",
  serial_number: "settings.sharing.field.serial_number",
  category: "settings.sharing.field.category",
  location: "settings.sharing.field.location",
  purchase_price: "settings.sharing.field.purchase_price",
  purchase_date: "settings.sharing.field.purchase_date",
  msrp: "settings.sharing.field.msrp",
  replacement_cost: "settings.sharing.field.replacement_cost",
  notes: "settings.sharing.field.notes",
  photos: "settings.sharing.field.photos",
  documents: "settings.sharing.field.documents",
  custom_fields: "settings.sharing.field.custom_fields",
};

function itemsCount(t: (key: DictKey) => string, n: number): string {
  return t(
    n === 1
      ? "settings.sharing.itemsCountOne"
      : "settings.sharing.itemsCountMany",
  ).replace("{count}", String(n));
}

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
  const t = useT();
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
  const label = accountTypeLabel(group, t);
  const newCategory = categoryChoice === "__new__";
  const categoryValue = newCategory ? categoryText : categoryChoice;

  async function apply(promise: Promise<ShareGroupState>, message: string) {
    setError(null);
    setBusy(true);
    try {
      const state = await promise;
      onSaved(state);
      toast(message, { tone: "success", title: t("settings.publicProfile.savedTitle"), duration: 8000 });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.sharing.ruleSaveFailed"),
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
      t("settings.sharing.ruleAdded").replace("{label}", label),
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
        {t("settings.sharing.shareByRule")}
      </p>
      <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
        {t("settings.sharing.shareByRuleIntro")}
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      {rules.length === 0 ? (
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
          {t("settings.sharing.noRulesYet").replace("{label}", label)}
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
                  <strong>{t(RULE_SCOPE_KEYS[rule.scope])}</strong>
                  {rule.scope !== "all" && <> — {rule.scope_label}</>}
                  <span style={{ color: "var(--text-muted)" }}>
                    {t(
                      rule.match_count === 1
                        ? "settings.sharing.sharingNowOne"
                        : "settings.sharing.sharingNowMany",
                    ).replace("{count}", String(rule.match_count))}
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
                      t("settings.sharing.ruleRemoved").replace("{label}", label),
                    )
                  }
                >
                  {t("settings.sharing.removeRule")}
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
                    t("settings.sharing.ruleUpdated").replace("{label}", label),
                  )
                }
                label={t("settings.sharing.ruleAddonsLabel")}
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
        <FormField label={t("settings.sharing.ruleType")}>
          <Select
            value={scope}
            onChange={(e) => setScope(e.target.value as ShareRuleScope)}
            aria-label={t("settings.sharing.ruleType")}
          >
            <option value="category">{t("settings.sharing.scopeCategory")}</option>
            <option value="location">{t("settings.sharing.scopeLocation")}</option>
            <option value="tag">{t("settings.sharing.scopeTag")}</option>
            <option value="all">{t("settings.sharing.scopeAll")}</option>
          </Select>
        </FormField>
        {scope === "category" && (
          <>
            {overview.categories.length > 0 && (
              <FormField label={t("settings.sharing.scopeCategory")}>
                <Select
                  value={categoryChoice}
                  onChange={(e) => setCategoryChoice(e.target.value)}
                  aria-label={t("settings.sharing.scopeCategory")}
                >
                  <option value="">{t("settings.sharing.chooseCategory")}</option>
                  {overview.categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                  <option value="__new__">{t("settings.sharing.typeNewCategory")}</option>
                </Select>
              </FormField>
            )}
            {(newCategory || overview.categories.length === 0) && (
              <FormField label={t("settings.sharing.newCategory")}>
                <TextInput
                  value={categoryText}
                  onChange={(e) => setCategoryText(e.target.value)}
                  placeholder={t("settings.sharing.newCategoryPlaceholder")}
                  aria-label={t("settings.sharing.newCategory")}
                />
              </FormField>
            )}
          </>
        )}
        {scope === "location" && (
          <FormField label={t("settings.sharing.scopeLocation")}>
            <Select
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              aria-label={t("settings.sharing.scopeLocation")}
            >
              <option value="">{t("settings.sharing.chooseLocation")}</option>
              {overview.locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.path} ({itemsCount(t, loc.subtree_item_count)})
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {scope === "tag" && (
          <FormField label={t("settings.sharing.scopeTag")}>
            <Select
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              aria-label={t("settings.sharing.scopeTag")}
            >
              <option value="">{t("settings.sharing.chooseTag")}</option>
              {overview.tags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name} ({itemsCount(t, tag.item_count)})
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
          {t("settings.sharing.addRule")}
        </Button>
      </div>
      <div style={{ marginTop: "0.35rem" }}>
        <Checkbox
          name={`share-${group}-new-rule-addons`}
          checked={addons}
          onChange={(e) => setAddons(e.target.checked)}
          label={t("settings.sharing.newRuleAddonsLabel")}
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
      toast(
        t("settings.sharing.updatedFor").replace(
          "{label}",
          accountTypeLabel(group, t),
        ),
        {
          tone: "success",
          title: t("settings.publicProfile.savedTitle"),
          duration: 8000,
        },
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("settings.sharing.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  const label = accountTypeLabel(group, t);

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
        className="tv-setting-row is-clickable"
        onClick={(e) => {
          /* Whole row drives its switch (the Modules pattern). */
          if (
            (e.target as HTMLElement).closest(
              "button, a, input, select, textarea",
            )
          ) {
            return;
          }
          e.currentTarget
            .querySelector<HTMLButtonElement>('[role="switch"]')
            ?.click();
        }}
      >
        <div className="tv-setting-row-main">
          <p className="tv-setting-row-name">{t("settings.sharing.shareWith").replace("{label}", label)}</p>
          <p className="tv-setting-row-desc">
            {t("sharing.groupToggle.desc")}
          </p>
        </div>
        <span className="tv-setting-row-state">
          <span className="tv-setting-row-state-word">
            {draft.enabled ? t("settings.stateOn") : t("settings.stateOff")}
          </span>
          <Toggle
            checked={draft.enabled}
            onChange={(on) => setDraft((d) => (d ? { ...d, enabled: on } : d))}
            ariaLabel={t("settings.sharing.shareWithAria").replace("{label}", label)}
          />
        </span>
      </div>

      {error && <Alert tone="danger">{error}</Alert>}

      <div>
        <p className="tv-setting-row-name" style={{ margin: "0 0 var(--space-2)" }}>
          {t("settings.sharing.whatTheyCanSee")}
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
              label={FIELD_KEYS[f.key] ? t(FIELD_KEYS[f.key]) : f.label}
              checked
              disabled
              name={`share-${group}-locked-${f.key}`}
            />
          ))}
          {OPTIONAL_SHARE_FIELDS.map((f) => (
            <Checkbox
              key={f.key}
              label={FIELD_KEYS[f.key] ? t(FIELD_KEYS[f.key]) : f.label}
              checked={draft.fields.has(f.key)}
              onChange={(e) => toggleField(f.key, e.target.checked)}
              name={`share-${group}-field-${f.key}`}
            />
          ))}
        </div>
        <p style={{ color: "var(--text-muted)", margin: "0.35rem 0 0" }}>
          {t("settings.sharing.alwaysShared")}
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
          <p className="tv-setting-row-name">{t("settings.sharing.whichItems")}</p>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.sharing.sharingCount")
              .replace("{resolved}", String(saved.resolved_count))
              .replace("{total}", String(overview.items.length))
              .replace("{picked}", String(draft.selected.size))}
            {(saved.rules ?? []).length > 0 &&
              t(
                (saved.rules ?? []).length === 1
                  ? "settings.sharing.rulesSuffixOne"
                  : "settings.sharing.rulesSuffixMany",
              ).replace("{count}", String((saved.rules ?? []).length))}
            {draft.excluded.size > 0 &&
              t("settings.sharing.excludedSuffix").replace(
                "{count}",
                String(draft.excluded.size),
              )}
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
              placeholder={t("settings.sharing.searchItemsPlaceholder")}
              aria-label={t("settings.sharing.searchItemsAria")}
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
            {t("settings.sharing.selectAll")}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() =>
              setDraft((d) => (d ? { ...d, selected: new Set() } : d))
            }
          >
            {t("settings.sharing.selectNone")}
          </Button>
        </div>
        {overview.items.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.sharing.noItemsYet")}
          </p>
        ) : visibleItems.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("settings.sharing.noItemsMatch")}
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
                          {t("settings.sharing.batterySuffix")}
                        </span>
                      )}
                      {item.is_set && (
                        <span style={{ color: "var(--text-muted)" }}>{t("settings.sharing.setSuffix")}</span>
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
                          {t("settings.sharing.sharedByRuleSuffix")}
                        </span>
                      )}
                      {excluded && (
                        <span style={{ fontWeight: 600 }}>
                          {" "}
                          {t("settings.sharing.excludedLabel")}
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
                      label={t("settings.sharing.includeAddons")}
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
                      label={t("settings.sharing.excludeItemLabel")}
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
          {t("settings.sharing.saveSharingFor").replace("{label}", label)}
        </Button>
      </div>
    </div>
  );
}

export default function SharingSettings({
  onSharingChanged,
}: {
  /** Fired after any successful save in this panel (group
   *  config/items/rules and every peer mutation). The Shared
   *  Tools page passes it so its audience tabs — which read
   *  their own copies of the sharing state — refresh in the
   *  same session instead of showing the pre-save state until
   *  a reload (trio fix, 2026-11-12). The Settings-page seat
   *  passes nothing: nothing else on that page derives from
   *  sharing state. */
  onSharingChanged?: () => void;
} = {}) {
  const t = useT();
  const [overview, setOverview] = useState<SharingOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Side list layout (owner, sheet row 148, 2026-11-18): one
  // entry per sharing category — Shop Company, Insurance
  // Agency, Coworkers — and the selected category's settings
  // in the panel. The two tier groups are the overview's
  // recipient groups; Coworkers is the peer-sharing section.
  const [category, setCategory] = useState<
    ShareRecipientGroup | "coworkers"
  >("shop_company");

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
              : t("settings.sharing.loadFailed"),
          );
        }
      });
    return () => {
      live = false;
    };
  }, [t]);

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
    // Both save paths funnel here (the group editor's Save and
    // the rules editor's immediate saves) — tell the host page
    // its sharing-derived tabs are stale now.
    onSharingChanged?.();
  }

  return (
    <Panel title={t("settings.sharing.title")} variant="plate" className="tv-sharing-panel">
      <p className="tv-settings-intro" style={{ margin: "0 0 var(--space-3)" }}>
        {t("settings.sharing.intro")}
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
          <Spinner size="sm" /> {t("settings.sharing.loadingSharing")}
        </p>
      )}
      {overview && (
        <SideList
          listLabel={t("settings.sharing.title")}
          list={
            <>
              {overview.groups.map((g) => (
                <SideListRow
                  key={g.recipient_group}
                  selected={category === g.recipient_group}
                  onSelect={() => setCategory(g.recipient_group)}
                  title={t(
                    `settings.sharing.cat.${g.recipient_group}` as DictKey,
                  )}
                  sub={
                    g.enabled
                      ? t("settings.sharing.catOn")
                      : t("settings.sharing.catOff")
                  }
                />
              ))}
              <SideListRow
                selected={category === "coworkers"}
                onSelect={() => setCategory("coworkers")}
                title={t("settings.sharing.cat.coworkers")}
              />
            </>
          }
          panel={
            category === "coworkers" ? (
              <PeerSharingSettings onSharingChanged={onSharingChanged} />
            ) : (
              <GroupSharingEditor
                key={category}
                group={category}
                overview={overview}
                onSaved={onGroupSaved}
              />
            )
          }
        />
      )}
      {/* Sharing with PEOPLE (peer sharing, the Coworkers
          entry above) fetches its own data, so on a group
          overview load failure it still renders on its own. */}
      {!overview && loadError && (
        <div
          style={{
            borderTop: "1px solid var(--edge)",
            marginTop: "var(--space-4)",
            paddingTop: "1rem",
          }}
        >
          <PeerSharingSettings onSharingChanged={onSharingChanged} />
        </div>
      )}
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
  const t = useT();
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
      toast(t("settings.sharing.catalogSaved"), { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.sharing.catalogSaveFailed"),
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {/* The catalog switch rides the standard setting-row
          anatomy (settings uniformity, 2026-11-13): name +
          description + state word + switch; the "What
          contributes" detail stays as the block's footnote
          paragraph under the row. */}
      <div
        className="tv-setting-row is-clickable"
        onClick={(e) => {
          if (
            (e.target as HTMLElement).closest(
              "button, a, input, select, textarea",
            )
          ) {
            return;
          }
          e.currentTarget
            .querySelector<HTMLButtonElement>('[role="switch"]')
            ?.click();
        }}
      >
        <div className="tv-setting-row-main">
          <p className="tv-setting-row-name">
            {t("settings.sharing.catalogTitle")}
          </p>
          <p className="tv-setting-row-desc">
            {t("settings.sharing.catalogDesc")}
          </p>
        </div>
        {enabled === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            <Spinner size="sm" /> {t("shell.loading")}
          </p>
        ) : (
          <span className="tv-setting-row-state">
            <span className="tv-setting-row-state-word">
              {enabled ? t("settings.stateOn") : t("settings.stateOff")}
            </span>
            <Toggle
              checked={enabled}
              disabled={busy}
              onChange={(on) => void toggle(on)}
              ariaLabel={t("settings.sharing.catalogAria")}
            />
          </span>
        )}
      </div>
      <p className="tv-settings-intro" style={{ marginBottom: 0 }}>
        <strong>{t("settings.sharing.catalogWhatLead")}</strong>
        {t("settings.sharing.catalogWhatBody")}
        <strong>{t("settings.sharing.catalogNeverLead")}</strong>
        {t("settings.sharing.catalogNeverBody")}
      </p>
    </div>
  );
}
