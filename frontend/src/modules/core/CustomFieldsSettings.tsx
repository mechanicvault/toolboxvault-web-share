import { useEffect, useState } from "react";

import {
  Alert,
  Button,
  FormField,
  Modal,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  Toggle,
  useToast,
} from "../../components";
import { formGridStyle } from "../../components/formStyles";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { ApiError, api } from "../../lib/api";
import type { FieldDefinition, FieldType } from "../inventory/types";
import { useAuth } from "./AuthContext";
import { useMyModules } from "./MyModules";

/**
 * Settings → Custom fields: the manager for the owner's own
 * field definitions (the typed extras the tool forms render —
 * "Torque spec", "Warranty until", …). The backend CRUD has existed
 * since the inventory module shipped (owner-scoped; definitions
 * live behind the mechanic gate because inventory does) — this is
 * its first UI.
 *
 * Contract notes that shape the form: the API key (`name`) is a
 * slug and is NOT updatable after creation (it's what stored values
 * are filed under), so the key field locks in edit mode; a dropdown
 * needs at least one option and other types take none; deleting a
 * definition SCRUBS the field's values from every one of the
 * owner's tools in the same transaction — the confirm dialog says
 * so in plain words before anything is deleted.
 */

const TYPE_KEYS: Record<FieldType, DictKey> = {
  text: "settings.customFields.typeText",
  number: "settings.customFields.typeNumber",
  date: "settings.customFields.typeDate",
  dropdown: "settings.customFields.typeDropdown",
  boolean: "settings.customFields.typeBoolean",
};

const SLUG_PATTERN = /^[a-z][a-z0-9_]*$/;

function slugify(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_");
  if (!slug) return "";
  return /^[a-z]/.test(slug) ? slug : `field_${slug}`;
}

type AppliesTo = "tool" | "battery" | "both" | "part";

const APPLIES_TO_KEYS: Record<AppliesTo, DictKey> = {
  tool: "settings.customFields.appliesTool",
  battery: "settings.customFields.appliesBattery",
  both: "settings.customFields.appliesBoth",
  part: "settings.customFields.appliesPart",
};

interface FieldForm {
  label: string;
  name: string;
  fieldType: FieldType;
  itemType: AppliesTo;
  required: boolean;
  optionsText: string;
}

const EMPTY_FORM: FieldForm = {
  label: "",
  name: "",
  fieldType: "text",
  itemType: "tool",
  required: false,
  optionsText: "",
};

function optionsFrom(text: string): string[] {
  return text
    .split("\n")
    .map((o) => o.trim())
    .filter(Boolean);
}

export default function CustomFieldsSettings() {
  const { user } = useAuth();
  const { toast } = useToast();
  const t = useT();
  const { loading: modulesLoading, has } = useMyModules();
  // Parked-module signs (owner directive, 2026-10-31): the
  // "My Parts" target is offered for NEW fields only while the
  // parts module is effective for this viewer — and returns on
  // its own when the module is unparked. An existing part field
  // keeps its option below (its edit form renders its own value;
  // the target is fixed at creation and never re-submitted), so
  // nothing already filed is stranded.
  const partsOn = !modulesLoading && has("parts");
  // Definitions serve inventory (mechanic) and Used Parts
  // (mechanic + shop): the panel opens for either owning group.
  const accountTypes = user?.account_types ?? [];
  const isMechanic =
    accountTypes.includes("mechanic_technician") ||
    accountTypes.includes("shop_company");

  const [definitions, setDefinitions] = useState<FieldDefinition[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<FieldForm>(EMPTY_FORM);
  const [nameTouched, setNameTouched] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<FieldDefinition | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!isMechanic) return;
    let live = true;
    api<FieldDefinition[]>("/inventory/field-definitions?item_type=all")
      .then((data) => {
        if (live) setDefinitions(data);
      })
      .catch((err) => {
        if (live) {
          setLoadError(
            err instanceof ApiError ? err.message : t("settings.customFields.loadFailed"),
          );
        }
      });
    return () => {
      live = false;
    };
  }, [isMechanic]);

  if (!isMechanic) {
    return (
      <Panel title={t("settings.customFields.title")} variant="plate">
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.customFields.notMechanic")}
        </p>
      </Panel>
    );
  }

  function resetForm() {
    setForm(EMPTY_FORM);
    setNameTouched(false);
    setEditingId(null);
    setFormError(null);
  }

  function beginEdit(def: FieldDefinition) {
    setEditingId(def.id);
    setForm({
      label: def.label,
      name: def.name,
      fieldType: def.field_type,
      itemType: (def.item_type as AppliesTo) ?? "tool",
      required: def.required,
      optionsText: def.options.join("\n"),
    });
    setNameTouched(true);
    setFormError(null);
  }

  async function onSave() {
    const options = form.fieldType === "dropdown" ? optionsFrom(form.optionsText) : [];
    if (!form.label.trim()) {
      setFormError(t("settings.customFields.labelRequired"));
      return;
    }
    if (editingId === null && !SLUG_PATTERN.test(form.name)) {
      setFormError(
        t("settings.customFields.keyInvalid"),
      );
      return;
    }
    if (form.fieldType === "dropdown" && options.length === 0) {
      setFormError(t("settings.customFields.dropdownNeedsChoice"));
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editingId === null) {
        const created = await api<FieldDefinition>("/inventory/field-definitions", {
          method: "POST",
          body: JSON.stringify({
            item_type: form.itemType,
            name: form.name,
            label: form.label.trim(),
            field_type: form.fieldType,
            required: form.required,
            searchable: true,
            options,
          }),
        });
        setDefinitions((d) => [...(d ?? []), created]);
        toast(
          t("settings.customFields.addedToast").replace("{label}", created.label),
          {
          title: t("settings.publicProfile.savedTitle"),
          tone: "success",
          duration: 8000,
        });
      } else {
        const updated = await api<FieldDefinition>(
          `/inventory/field-definitions/${editingId}`,
          {
            method: "PUT",
            body: JSON.stringify({
              label: form.label.trim(),
              field_type: form.fieldType,
              required: form.required,
              options,
            }),
          },
        );
        setDefinitions((d) => (d ?? []).map((x) => (x.id === updated.id ? updated : x)));
        toast(
          t("settings.customFields.updatedToast").replace("{label}", updated.label),
          {
          title: t("settings.publicProfile.savedTitle"),
          tone: "success",
          duration: 8000,
        });
      }
      resetForm();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t("settings.customFields.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  }

  async function onDeleteConfirmed() {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await api<void>(`/inventory/field-definitions/${confirmDelete.id}`, {
        method: "DELETE",
      });
      setDefinitions((d) => (d ?? []).filter((x) => x.id !== confirmDelete.id));
      if (editingId === confirmDelete.id) resetForm();
      toast(
        t("settings.customFields.deletedToast").replace(
          "{label}",
          confirmDelete.label,
        ),
        {
        title: t("settings.publicProfile.savedTitle"),
        tone: "success",
        duration: 8000,
      });
      setConfirmDelete(null);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.customFields.deleteFailedToast"),
        { title: t("settings.customFields.deleteFailedTitle"), tone: "danger", duration: 8000 },
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div id="custom-fields">
      <Panel title={t("settings.customFields.title")} variant="plate">
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
          {t("settings.customFields.intro")}
        </p>
        {loadError && <Alert tone="danger">{loadError}</Alert>}
        {!definitions && !loadError && <Spinner label={t("settings.customFields.loadingLabel")} />}

        {definitions && definitions.length > 0 && (
          <div style={{ display: "grid", gap: "var(--space-2)", marginBottom: "var(--space-4)" }}>
            {definitions.map((def) => (
              <div
                key={def.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "1rem",
                  flexWrap: "wrap",
                  border: "1px solid var(--edge)",
                  borderRadius: "var(--radius)",
                  padding: "0.6rem 0.8rem",
                }}
              >
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>{def.label}</div>
                  <div style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>
                    <code>{def.name}</code> · {t(TYPE_KEYS[def.field_type])} ·{" "}
                    {t(APPLIES_TO_KEYS[(def.item_type as AppliesTo) ?? "tool"])} ·{" "}
                    {def.required
                      ? t("settings.customFields.requiredWord")
                      : t("settings.customFields.optionalWord")}
                    {def.field_type === "dropdown" &&
                      t(
                        def.options.length === 1
                          ? "settings.customFields.choicesSuffixOne"
                          : "settings.customFields.choicesSuffixMany",
                      ).replace("{count}", String(def.options.length))}
                  </div>
                </div>
                <Button type="button" variant="ghost" size="sm" onClick={() => beginEdit(def)}>
                  {t("settings.customFields.edit")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDelete(def)}
                >
                  {t("settings.customFields.delete")}
                </Button>
              </div>
            ))}
          </div>
        )}
        {definitions && definitions.length === 0 && (
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            {t("settings.customFields.noFields")}
          </p>
        )}

        <h3 style={{ margin: "0 0 var(--space-2)", fontSize: "1rem" }}>
          {editingId
            ? t("settings.customFields.editHeading").replace(
                "{label}",
                form.label || t("settings.customFields.fieldFallback"),
              )
            : t("settings.customFields.addHeading")}
        </h3>
        {formError && <Alert tone="danger">{formError}</Alert>}
        <div style={{ ...formGridStyle, marginTop: "var(--space-2)" }}>
          <FormField label={t("settings.customFields.labelLabel")} htmlFor="cf-label" hint={t("settings.customFields.labelHint")}>
            <TextInput
              id="cf-label"
              value={form.label}
              onChange={(e) => {
                const label = e.target.value;
                setForm((f) => ({
                  ...f,
                  label,
                  name: nameTouched || editingId ? f.name : slugify(label),
                }));
              }}
              placeholder={t("settings.customFields.labelPlaceholder")}
            />
          </FormField>
          <FormField
            label={t("settings.customFields.keyLabel")}
            htmlFor="cf-name"
            hint={
              editingId
                ? t("settings.customFields.keyHintEdit")
                : t("settings.customFields.keyHintNew")
            }
          >
            <TextInput
              id="cf-name"
              value={form.name}
              disabled={editingId !== null}
              onChange={(e) => {
                setNameTouched(true);
                setForm((f) => ({ ...f, name: e.target.value }));
              }}
              placeholder="torque_spec"
            />
          </FormField>
          <FormField label={t("settings.customFields.typeLabel")} htmlFor="cf-type">
            <Select
              id="cf-type"
              value={form.fieldType}
              onChange={(e) =>
                setForm((f) => ({ ...f, fieldType: e.target.value as FieldType }))
              }
            >
              {(Object.keys(TYPE_KEYS) as FieldType[]).map((ft) => (
                <option key={ft} value={ft}>
                  {t(TYPE_KEYS[ft])}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label={t("settings.customFields.appliesLabel")}
            htmlFor="cf-applies"
            hint={
              editingId
                ? t("settings.customFields.appliesHintEdit")
                : t("settings.customFields.appliesHintNew")
            }
          >
            <Select
              id="cf-applies"
              value={form.itemType}
              disabled={editingId !== null}
              onChange={(e) =>
                setForm((f) => ({ ...f, itemType: e.target.value as AppliesTo }))
              }
            >
              {(Object.keys(APPLIES_TO_KEYS) as AppliesTo[])
                .filter(
                  (at) =>
                    at !== "part" || partsOn || form.itemType === "part",
                )
                .map((at) => (
                  <option key={at} value={at}>
                    {t(APPLIES_TO_KEYS[at])}
                  </option>
                ))}
            </Select>
          </FormField>
          <FormField label={t("settings.customFields.requiredLabel")} htmlFor="cf-required" hint={t("settings.customFields.requiredHint")}>
            <Toggle
              id="cf-required"
              checked={form.required}
              onChange={(checked) => setForm((f) => ({ ...f, required: checked }))}
              ariaLabel={t("settings.customFields.requiredAria")}
            />
          </FormField>
          {form.fieldType === "dropdown" && (
            <FormField
              label={t("settings.customFields.choicesLabel")}
              htmlFor="cf-options"
              hint={t("settings.customFields.choicesHint")}
            >
              <TextArea
                id="cf-options"
                value={form.optionsText}
                onChange={(e) => setForm((f) => ({ ...f, optionsText: e.target.value }))}
                placeholder={t("settings.customFields.choicesPlaceholder")}
                rows={4}
              />
            </FormField>
          )}
        </div>
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginTop: "var(--space-3)",
            flexWrap: "wrap",
          }}
        >
          <Button type="button" loading={saving} onClick={onSave}>
            {editingId ? t("settings.customFields.saveField") : t("settings.customFields.addField")}
          </Button>
          {editingId && (
            <Button type="button" variant="ghost" onClick={resetForm} disabled={saving}>
              {t("settings.customFields.cancelEdit")}
            </Button>
          )}
        </div>
      </Panel>

      <Modal
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title={t("settings.customFields.deleteModalTitle")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)} disabled={deleting}>
              {t("settings.customFields.keepField")}
            </Button>
            <Button variant="danger" loading={deleting} onClick={onDeleteConfirmed}>
              {t("settings.customFields.deleteField")}
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          {t("settings.customFields.deleteLead")}
          <strong>{confirmDelete?.label}</strong>
          {t("settings.customFields.deleteTail")}
        </p>
      </Modal>
    </div>
  );
}
