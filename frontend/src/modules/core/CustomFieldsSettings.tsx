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

const TYPE_LABELS: Record<FieldType, string> = {
  text: "Text",
  number: "Number",
  date: "Date",
  dropdown: "Dropdown (pick from a list)",
  boolean: "Checkbox (yes / no)",
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

const APPLIES_TO_LABELS: Record<AppliesTo, string> = {
  tool: "Tools",
  battery: "Batteries",
  both: "Tools & batteries",
  part: "My Parts",
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
            err instanceof ApiError ? err.message : "Couldn't load your custom fields.",
          );
        }
      });
    return () => {
      live = false;
    };
  }, [isMechanic]);

  if (!isMechanic) {
    return (
      <Panel title="Custom fields" variant="plate">
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Custom fields are the extra details you define on your own
          tools, batteries and parts (a torque spec, a warranty
          date, a part number), so they belong to the Mechanic /
          Technician and Shop / Company groups. Add one of those
          groups under Profile above and this section opens up.
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
      setFormError("Give the field a label — that's what shows on your tool forms.");
      return;
    }
    if (editingId === null && !SLUG_PATTERN.test(form.name)) {
      setFormError(
        "The field key must start with a letter and use only small letters, numbers, and underscores (e.g. torque_spec).",
      );
      return;
    }
    if (form.fieldType === "dropdown" && options.length === 0) {
      setFormError("A dropdown field needs at least one choice — one per line.");
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
        toast(`Custom field “${created.label}” added.`, {
          title: "Saved",
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
        toast(`Custom field “${updated.label}” updated.`, {
          title: "Saved",
          tone: "success",
          duration: 8000,
        });
      }
      resetForm();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Couldn't save the field — try again.",
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
      toast(`Custom field “${confirmDelete.label}” deleted.`, {
        title: "Saved",
        tone: "success",
        duration: 8000,
      });
      setConfirmDelete(null);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't delete the field — try again.",
        { title: "Delete failed", tone: "danger", duration: 8000 },
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div id="custom-fields">
      <Panel title="Custom fields" variant="plate">
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
          Your own extra fields for your items — anything the standard
          form doesn't cover. They appear on the Add / Edit forms and
          are fully searchable. Each field applies to tools, to
          batteries, or to both.
        </p>
        {loadError && <Alert tone="danger">{loadError}</Alert>}
        {!definitions && !loadError && <Spinner label="Loading your custom fields…" />}

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
                  <div style={{ fontWeight: 600 }}>{def.label}</div>
                  <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                    <code>{def.name}</code> · {TYPE_LABELS[def.field_type]} ·{" "}
                    {APPLIES_TO_LABELS[(def.item_type as AppliesTo) ?? "tool"]} ·{" "}
                    {def.required ? "Required" : "Optional"}
                    {def.field_type === "dropdown" &&
                      ` · ${def.options.length} choice${def.options.length === 1 ? "" : "s"}`}
                  </div>
                </div>
                <Button type="button" variant="ghost" size="sm" onClick={() => beginEdit(def)}>
                  Edit
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmDelete(def)}
                >
                  Delete
                </Button>
              </div>
            ))}
          </div>
        )}
        {definitions && definitions.length === 0 && (
          <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-3)" }}>
            No custom fields yet — add your first one below.
          </p>
        )}

        <h3 style={{ margin: "0 0 var(--space-2)", fontSize: "1rem" }}>
          {editingId ? `Edit “${form.label || "field"}”` : "Add a field"}
        </h3>
        {formError && <Alert tone="danger">{formError}</Alert>}
        <div style={{ ...formGridStyle, marginTop: "var(--space-2)" }}>
          <FormField label="Label" htmlFor="cf-label" hint="Shown on your tool forms.">
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
              placeholder="Torque spec"
            />
          </FormField>
          <FormField
            label="Field key"
            htmlFor="cf-name"
            hint={
              editingId
                ? "The key can't change — your tools' values are filed under it."
                : "Set once from the label; small letters, numbers, underscores."
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
          <FormField label="Type" htmlFor="cf-type">
            <Select
              id="cf-type"
              value={form.fieldType}
              onChange={(e) =>
                setForm((f) => ({ ...f, fieldType: e.target.value as FieldType }))
              }
            >
              {(Object.keys(TYPE_LABELS) as FieldType[]).map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField
            label="Applies to"
            htmlFor="cf-applies"
            hint={
              editingId
                ? "Fixed at creation — the records carrying this field's values are already filed under it."
                : "Which records this field appears on."
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
              {(Object.keys(APPLIES_TO_LABELS) as AppliesTo[])
                .filter(
                  (t) =>
                    t !== "part" || partsOn || form.itemType === "part",
                )
                .map((t) => (
                  <option key={t} value={t}>
                    {APPLIES_TO_LABELS[t]}
                  </option>
                ))}
            </Select>
          </FormField>
          <FormField label="Required" htmlFor="cf-required" hint="Required fields must be filled in on every tool.">
            <Toggle
              id="cf-required"
              checked={form.required}
              onChange={(checked) => setForm((f) => ({ ...f, required: checked }))}
              ariaLabel="Required field"
            />
          </FormField>
          {form.fieldType === "dropdown" && (
            <FormField
              label="Choices"
              htmlFor="cf-options"
              hint="One choice per line."
            >
              <TextArea
                id="cf-options"
                value={form.optionsText}
                onChange={(e) => setForm((f) => ({ ...f, optionsText: e.target.value }))}
                placeholder={"Good\nWorn\nNeeds service"}
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
            {editingId ? "Save field" : "Add field"}
          </Button>
          {editingId && (
            <Button type="button" variant="ghost" onClick={resetForm} disabled={saving}>
              Cancel edit
            </Button>
          )}
        </div>
      </Panel>

      <Modal
        open={confirmDelete !== null}
        onClose={() => setConfirmDelete(null)}
        title="Delete this custom field?"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(null)} disabled={deleting}>
              Keep field
            </Button>
            <Button variant="danger" loading={deleting} onClick={onDeleteConfirmed}>
              Delete field
            </Button>
          </>
        }
      >
        <p style={{ margin: 0 }}>
          Deleting <strong>{confirmDelete?.label}</strong> removes the
          field from all of your tools, batteries and parts, and
          every value stored under it is erased with it. This can't
          be undone.
        </p>
      </Modal>
    </div>
  );
}
