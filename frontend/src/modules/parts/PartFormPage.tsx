import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Breadcrumbs,
  Button,
  FormField,
  formGridStyle,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  useToast,
  LinkButton,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import type { FieldDefinition } from "../inventory/types";
import { CustomFieldInput } from "../inventory/components/CustomFieldInput";
import { PhotoUploader } from "../inventory/components/PhotoUploader";
import {
  StagedFilePicker,
  uploadStagedFiles,
  type StagedFile,
} from "../inventory/components/StagedPhotoPicker";
import { createPart, getPart, listLocations, listParts, updatePart } from "./api";
import type { Part, PartLocation } from "./types";

const CONDITIONS = [
  "New",
  "Used — good",
  "Used — fair",
  "Core",
  "Needs rebuild",
  "For parts",
];

/** Locations flattened with their full paths for the picker. */
function locationOptions(locations: PartLocation[]): { id: string; path: string }[] {
  const byId = new Map(locations.map((l) => [l.id, l]));
  const pathOf = (loc: PartLocation): string => {
    const names: string[] = [loc.name];
    let parent = loc.parent_id ? byId.get(loc.parent_id) : undefined;
    let guard = 0;
    while (parent && guard <= locations.length) {
      names.unshift(parent.name);
      parent = parent.parent_id ? byId.get(parent.parent_id) : undefined;
      guard += 1;
    }
    return names.join(" / ");
  };
  return locations
    .map((l) => ({ id: l.id, path: pathOf(l) }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

interface FormValues {
  title: string;
  quantity: string;
  condition: string;
  notes: string;
  location_id: string;
  custom_data: Record<string, unknown>;
  // Community Parts (2026-10-19): standard vehicle fields +
  // category (core columns — the community index searches them),
  // and the listing facts. "" visibility = inherit the pool
  // settings; "" show_phone = inherit the profile toggle.
  category: string;
  year: string;
  make: string;
  model: string;
  engine: string;
  asking_price: string;
  public_area_label: string;
  visibility: string;
  show_phone: string;
}

const EMPTY: FormValues = {
  title: "",
  quantity: "1",
  condition: "",
  notes: "",
  location_id: "",
  custom_data: {},
  category: "",
  year: "",
  make: "",
  model: "",
  engine: "",
  asking_price: "",
  public_area_label: "",
  visibility: "",
  show_phone: "",
};

function fromPart(part: Part): FormValues {
  return {
    title: part.title,
    quantity: String(part.quantity),
    condition: part.condition,
    notes: part.notes,
    location_id: part.location_id ?? "",
    custom_data: { ...part.custom_data },
    category: part.category ?? "",
    year: part.year ? String(part.year) : "",
    make: part.make ?? "",
    model: part.model ?? "",
    engine: part.engine ?? "",
    asking_price:
      part.asking_price !== null && part.asking_price !== ""
        ? String(part.asking_price)
        : "",
    public_area_label: part.public_area_label ?? "",
    visibility: part.visibility_override ?? "",
    show_phone:
      part.show_phone_override === null
        ? ""
        : part.show_phone_override
          ? "on"
          : "off",
  };
}

function PartFormContent() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const { toast } = useToast();

  const [values, setValues] = useState<FormValues>(EMPTY);
  const [existing, setExisting] = useState<Part | null>(null);
  const [defs, setDefs] = useState<FieldDefinition[]>([]);
  const [locations, setLocations] = useState<PartLocation[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [photos, setPhotos] = useState<StagedFile[]>([]);
  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([
      api<FieldDefinition[]>("/inventory/field-definitions?item_type=part"),
      listLocations(),
      isEdit && id ? getPart(id) : Promise.resolve(null),
      listParts({}).catch(() => [] as Part[]),
    ])
      .then(([d, locs, part, allParts]) => {
        if (!live) return;
        setDefs(d);
        setLocations(locs);
        // Category suggestions = the labels already on the shelf.
        setCategories(
          [...new Set(allParts.map((p) => p.category).filter(Boolean))].sort(),
        );
        if (part) {
          setExisting(part);
          setValues(fromPart(part));
        }
        setLoading(false);
      })
      .catch((err) => {
        if (live) {
          setError(
            err instanceof ApiError ? err.message : "Couldn't load the form.",
          );
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, [id, isEdit]);

  const options = useMemo(() => locationOptions(locations), [locations]);

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!values.title.trim()) {
      setError("Give the part a title — that's how you'll find it later.");
      return;
    }
    const quantity = Number.parseInt(values.quantity, 10);
    if (!Number.isFinite(quantity) || quantity < 1) {
      setError("Quantity must be at least 1.");
      return;
    }
    const year = values.year.trim()
      ? Number.parseInt(values.year, 10)
      : null;
    if (values.year.trim() && (!Number.isFinite(year) || (year as number) < 1885)) {
      setError("Year doesn't look right — four digits, like 2018.");
      return;
    }
    const asking = values.asking_price.trim()
      ? Number(values.asking_price)
      : null;
    if (values.asking_price.trim() && (!Number.isFinite(asking) || (asking as number) < 0)) {
      setError("Asking price must be a number, or blank.");
      return;
    }
    setSaving(true);
    setError("");
    const body = {
      title: values.title.trim(),
      quantity,
      condition: values.condition,
      notes: values.notes,
      location_id: values.location_id || null,
      custom_data: values.custom_data,
      category: values.category.trim(),
      year,
      make: values.make.trim(),
      model: values.model.trim(),
      engine: values.engine.trim(),
      asking_price: asking !== null ? String(asking) : null,
      public_area_label: values.public_area_label.trim() || null,
      visibility: values.visibility || null,
      show_phone_override:
        values.show_phone === "" ? null : values.show_phone === "on",
    };
    try {
      if (isEdit && id) {
        await updatePart(id, body);
        toast("Part saved.", { title: "Saved", tone: "success" });
        navigate(`/parts/${id}`);
        return;
      }
      const created = await createPart(body);
      // Photos picked during entry upload against the new record —
      // the record is never stranded by a failed file (the entry-time
      // rule): failures land on the detail page with a warning toast.
      if (photos.length > 0) {
        const { failed } = await uploadStagedFiles(
          `/parts/${created.id}`,
          "photo",
          photos,
          setPhotos,
        );
        if (failed.length > 0) {
          const names = failed.map((f) => f.file.name).join(", ");
          toast(
            `${names} couldn't be uploaded. You're on the part's page now — ` +
              "the Photos section is right there to add them again. Nothing else was lost.",
            {
              title: `Part saved — ${failed.length} photo${failed.length === 1 ? "" : "s"} didn't upload`,
              tone: "danger",
              duration: 12000,
            },
          );
        }
      }
      toast("Part added to your shelf.", { title: "Saved", tone: "success" });
      navigate(`/parts/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the part.");
      setSaving(false);
    }
  }

  if (loading) return <Spinner />;

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "880px" }}>
      <Breadcrumbs
        items={[
          { label: "My Parts", to: "/parts" },
          { label: isEdit ? "Edit part" : "Add part" },
        ]}
      />
      <h1 style={{ margin: 0 }}>{isEdit ? "Edit part" : "Add part"}</h1>
      {error && <Alert tone="danger">{error}</Alert>}
      <form onSubmit={(e) => void onSubmit(e)} style={{ display: "grid", gap: "1rem" }}>
        <Panel title="The basics">
          <div style={formGridStyle}>
            <FormField label="Title" htmlFor="part-title">
              <TextInput
                id="part-title"
                value={values.title}
                onChange={(e) => set("title", e.target.value)}
                placeholder="Alternator, reman — 2015 Silverado 5.3"
                required
              />
            </FormField>
            <FormField label="Quantity" htmlFor="part-qty">
              <TextInput
                id="part-qty"
                type="number"
                min={1}
                step={1}
                value={values.quantity}
                onChange={(e) => set("quantity", e.target.value)}
              />
            </FormField>
            <FormField label="Condition" htmlFor="part-condition">
              <Select
                id="part-condition"
                value={values.condition}
                onChange={(e) => set("condition", e.target.value)}
              >
                <option value="">—</option>
                {CONDITIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
                {values.condition && !CONDITIONS.includes(values.condition) && (
                  <option value={values.condition}>{values.condition}</option>
                )}
              </Select>
            </FormField>
            <FormField label="Location" htmlFor="part-location">
              <Select
                id="part-location"
                value={values.location_id}
                onChange={(e) => set("location_id", e.target.value)}
              >
                <option value="">— Unfiled —</option>
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.path}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          <FormField label="Notes" htmlFor="part-notes">
            <TextArea
              id="part-notes"
              value={values.notes}
              onChange={(e) => set("notes", e.target.value)}
              rows={3}
              placeholder="Where it came from, what it fits, what's wrong with it…"
            />
          </FormField>
        </Panel>

        <Panel title="Vehicle fit">
          <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
            The standard fit fields — these are what the Community
            Parts search indexes, so a buyer hunting parts for a
            2018 Silverado 5.3 finds this part. Fill in what you
            know; all optional.
          </p>
          <div style={formGridStyle}>
            <FormField label="Category" htmlFor="part-category">
              <TextInput
                id="part-category"
                value={values.category}
                onChange={(e) => set("category", e.target.value)}
                placeholder="Engine, Suspension, Electrical…"
                list="part-category-list"
              />
              <datalist id="part-category-list">
                {categories.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </FormField>
            <FormField label="Year" htmlFor="part-year">
              <TextInput
                id="part-year"
                type="number"
                value={values.year}
                onChange={(e) => set("year", e.target.value)}
                placeholder="2018"
              />
            </FormField>
            <FormField label="Make" htmlFor="part-make">
              <TextInput
                id="part-make"
                value={values.make}
                onChange={(e) => set("make", e.target.value)}
                placeholder="Chevrolet"
              />
            </FormField>
            <FormField label="Model" htmlFor="part-model">
              <TextInput
                id="part-model"
                value={values.model}
                onChange={(e) => set("model", e.target.value)}
                placeholder="Silverado 1500"
              />
            </FormField>
            <FormField label="Engine" htmlFor="part-engine">
              <TextInput
                id="part-engine"
                value={values.engine}
                onChange={(e) => set("engine", e.target.value)}
                placeholder="5.3L V8"
              />
            </FormField>
          </div>
        </Panel>

        <Panel title="Community Parts">
          <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
            Publishing lists this part in Community Parts for every
            member to find. A listing shows the part, its fit,
            photos, your display name and area — never your storage
            location or notes. Publishing needs a paid plan once
            plan enforcement switches on at launch.
          </p>
          <div style={formGridStyle}>
            <FormField label="Visibility" htmlFor="part-visibility">
              <Select
                id="part-visibility"
                value={values.visibility}
                onChange={(e) => set("visibility", e.target.value)}
              >
                <option value="">Use pool settings (category, then shelf default)</option>
                <option value="public">Public — list this part</option>
                <option value="private">Private — never list this part</option>
              </Select>
            </FormField>
            <FormField label="Asking price" htmlFor="part-asking">
              <TextInput
                id="part-asking"
                type="number"
                min={0}
                step="0.01"
                value={values.asking_price}
                onChange={(e) => set("asking_price", e.target.value)}
                placeholder="Optional"
              />
            </FormField>
            <FormField label="Area shown on the listing" htmlFor="part-area">
              <TextInput
                id="part-area"
                value={values.public_area_label}
                onChange={(e) => set("public_area_label", e.target.value)}
                placeholder="Blank uses your profile area"
              />
            </FormField>
            <FormField label="Show my phone on this listing" htmlFor="part-phone">
              <Select
                id="part-phone"
                value={values.show_phone}
                onChange={(e) => set("show_phone", e.target.value)}
              >
                <option value="">Use my profile setting</option>
                <option value="on">Show my phone for this part</option>
                <option value="off">Never for this part</option>
              </Select>
            </FormField>
          </div>
        </Panel>

        {defs.length > 0 && (
          <Panel title="Your fields">
            <div style={formGridStyle}>
              {defs.map((def) => (
                <CustomFieldInput
                  key={def.id}
                  def={def}
                  value={values.custom_data[def.id]}
                  onChange={(value) =>
                    set("custom_data", { ...values.custom_data, [def.id]: value })
                  }
                />
              ))}
            </div>
            <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
              These are your own fields for your parts — add more in{" "}
              <Link to="/settings#custom-fields">Settings → Custom fields</Link>.
            </p>
          </Panel>
        )}
        {defs.length === 0 && (
          <Panel title="Your fields">
            <p style={{ margin: 0, color: "var(--text-muted)" }}>
              No custom fields yet. Your parts shine with your own details —
              year, make, model, VIN, part number, whatever you track. Define
              them in{" "}
              <Link to="/settings#custom-fields">Settings → Custom fields</Link>{" "}
              (Applies to: My parts) and they'll appear on this form.
            </p>
          </Panel>
        )}

        <Panel title="Photos">
          {isEdit && id ? (
            <div style={{ display: "grid", gap: "0.8rem" }}>
              {existing && existing.attachments.length > 0 && (
                <div
                  style={{
                    display: "grid",
                    gap: "var(--space-3)",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(min(100%, 120px), 1fr))",
                  }}
                >
                  {existing.attachments.map((a) => (
                    <img
                      key={a.key}
                      src={a.url}
                      alt={a.filename}
                      style={{
                        width: "100%",
                        aspectRatio: "1",
                        objectFit: "cover",
                        borderRadius: "var(--radius)",
                        border: "1px solid var(--edge)",
                      }}
                    />
                  ))}
                </div>
              )}
              <PhotoUploader
                toolId={id}
                basePath={`/parts/${id}`}
                kind="photo"
                onUploaded={() => {
                  getPart(id)
                    .then(setExisting)
                    .catch(() => undefined);
                }}
              />
            </div>
          ) : (
            <StagedFilePicker kind="photo" files={photos} onChange={setPhotos} />
          )}
        </Panel>

        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Add part"}
          </Button>
          <LinkButton to={isEdit && id ? `/parts/${id}` : "/parts"} variant="secondary">Cancel</LinkButton>
        </div>
      </form>
    </div>
  );
}

export default function PartFormPage() {
  return (
    <RequireAuth>
      <PartFormContent />
    </RequireAuth>
  );
}
