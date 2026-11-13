/** Tools For Sale — the listing form (create + edit).
 *
 *  Create has the suite's one-tap path: pick one of my inventory
 *  items and the listing starts as a SNAPSHOT of it (title, brand,
 *  model, photos copied) — the inventory record stays the private
 *  original; editing it later never rewrites this listing, and
 *  nothing else about the item (serial, notes, what I paid) ever
 *  crosses over. Or start blank and write a standalone listing.
 *
 *  Photos on an existing listing ride the shared photo flow
 *  (presigned upload, photo kind only) — the same uploader the
 *  inventory and parts forms use. */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Alert,
  Breadcrumbs,
  Button,
  Checkbox,
  FormField,
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
import { PhotoUploader } from "../inventory/components/PhotoUploader";
import type { Battery, Tool } from "../inventory/types";
import { createListing, listMine, updateListing } from "./api";
import type { OwnerListing } from "./types";

interface SourceOption {
  value: string; // "tool:<id>" | "battery:<id>"
  label: string;
}

function ListingForm() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const editing = !!id;

  const [existing, setExisting] = useState<OwnerListing | null>(null);
  const [loadError, setLoadError] = useState("");
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [source, setSource] = useState(searchParams.get("source") ?? "");

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [listingType, setListingType] = useState<"for_sale" | "wanted">("for_sale");
  const [price, setPrice] = useState("");
  const [condition, setCondition] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [pickup, setPickup] = useState(true);
  const [ships, setShips] = useState(false);
  const [area, setArea] = useState("");
  const [phoneChoice, setPhoneChoice] = useState<"inherit" | "show" | "hide">(
    "inherit",
  );
  const [saving, setSaving] = useState(false);
  const [photoVersion, setPhotoVersion] = useState(0);

  // The inventory picker: my tools + batteries. It quietly
  // disappears for accounts without inventory access (dealers,
  // insurers) or when the module is off — standalone listings
  // remain fully available either way.
  useEffect(() => {
    if (editing) return;
    let cancelled = false;
    Promise.allSettled([
      api<Tool[]>("/inventory/search?limit=100"),
      api<Battery[]>("/inventory/batteries/search?limit=100"),
    ]).then(([tools, batteries]) => {
      if (cancelled) return;
      const options: SourceOption[] = [];
      if (tools.status === "fulfilled") {
        for (const tool of tools.value) {
          options.push({
            value: `tool:${tool.id}`,
            label: `${tool.name}${tool.brand ? ` (${tool.brand})` : ""}`,
          });
        }
      }
      if (batteries.status === "fulfilled") {
        for (const battery of batteries.value) {
          options.push({
            value: `battery:${battery.id}`,
            label: `${battery.name}${battery.brand ? ` (${battery.brand})` : ""} · battery`,
          });
        }
      }
      setSources(options);
    });
    return () => {
      cancelled = true;
    };
  }, [editing]);

  const loadExisting = useCallback(async () => {
    if (!id) return;
    try {
      const mine = await listMine();
      const row = mine.find((listing) => listing.id === id);
      if (!row) {
        setLoadError("That listing isn't yours (or doesn't exist).");
        return;
      }
      setExisting(row);
      setTitle(row.title);
      setDescription(row.description);
      setListingType(row.listing_type);
      setPrice(row.price ?? "");
      setCondition(row.condition);
      setBrand(row.brand);
      setModel(row.model);
      setPickup(row.delivery_local_pickup);
      setShips(row.delivery_ships);
      setArea(row.area_override ?? "");
      setPhoneChoice(
        row.show_phone_override === null
          ? "inherit"
          : row.show_phone_override
            ? "show"
            : "hide",
      );
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load that listing.",
      );
    }
  }, [id]);

  useEffect(() => {
    void loadExisting();
  }, [loadExisting, photoVersion]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const values = {
        title: title.trim(),
        description: description.trim(),
        listing_type: listingType,
        price: price.trim() === "" ? null : price.trim(),
        condition: condition.trim(),
        brand: brand.trim(),
        model: model.trim(),
        delivery_local_pickup: pickup,
        delivery_ships: ships,
        public_area_label: area.trim() === "" ? null : area.trim(),
        show_phone_override:
          phoneChoice === "inherit" ? null : phoneChoice === "show",
      };
      if (editing && id) {
        await updateListing(id, values);
        toast("Listing saved.", { title: "Saved", tone: "success" });
        navigate("/marketplace/mine");
      } else {
        const body: Record<string, unknown> = { ...values };
        if (source) {
          const [kind, sourceId] = source.split(":");
          body.source_kind = kind;
          body.source_id = sourceId;
          // A snapshot listing's title/brand/model/photos come
          // from the item; don't send blanks over them (the API
          // treats a sent field as an override).
          if (!values.title) delete body.title;
          if (!values.brand) delete body.brand;
          if (!values.model) delete body.model;
          if (!values.description) delete body.description;
        }
        const created = await createListing(body);
        toast("Your listing is on the board.", {
          title: "Listed",
          tone: "success",
        });
        // Land on the edit page so photos can be added right away
        // (a snapshot listing already carries the item's photos).
        navigate(`/marketplace/${created.id}/edit`);
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save that listing.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  if (editing && loadError) {
    return (
      <div style={{ display: "grid", gap: "1rem", maxWidth: "760px" }}>
        <Breadcrumbs
          items={[
            { label: "Tools for sale", to: "/marketplace" },
            { label: "My listings", to: "/marketplace/mine" },
            { label: "Edit listing" },
          ]}
        />
        <Alert tone="danger">{loadError}</Alert>
      </div>
    );
  }
  if (editing && !existing) return <Spinner />;

  return (
    <div style={{ display: "grid", gap: "1rem", maxWidth: "760px" }}>
      <Breadcrumbs
        items={[
          { label: "Tools for sale", to: "/marketplace" },
          { label: "My listings", to: "/marketplace/mine" },
          { label: editing ? "Edit listing" : "List an item" },
        ]}
      />
      <h1 style={{ margin: 0 }}>{editing ? "Edit listing" : "List an item"}</h1>

      <form onSubmit={onSubmit} style={{ display: "grid", gap: "1rem" }}>
        <Panel title="The listing">
          <div style={{ display: "grid", gap: "0.9rem" }}>
            {!editing && sources.length > 0 && (
              <FormField
                label="Start from one of my inventory items (optional)"
                htmlFor="mk-source"
              >
                <Select
                  id="mk-source"
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                >
                  <option value="">— Start blank —</option>
                  {sources.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </FormField>
            )}
            {!editing && source && (
              <Alert tone="info">
                The listing copies the item's name, brand, model and
                photos. It's a snapshot: later edits to the inventory
                item won't change the listing, and nothing private
                (serial number, notes, what you paid) ever crosses
                over. You can still adjust the title and price below.
              </Alert>
            )}
            <FormField label="Title" htmlFor="mk-title">
              <TextInput
                id="mk-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required={!source}
                placeholder={source ? "Copied from the item — edit if you like" : ""}
              />
            </FormField>
            <div
              style={{
                display: "grid",
                gap: "0.9rem",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              }}
            >
              <FormField label="Type" htmlFor="mk-listing-type">
                <Select
                  id="mk-listing-type"
                  value={listingType}
                  onChange={(event) =>
                    setListingType(event.target.value as "for_sale" | "wanted")
                  }
                >
                  <option value="for_sale">For sale</option>
                  <option value="wanted">Wanted</option>
                </Select>
              </FormField>
              <FormField label="Price (blank = “Make offer”)" htmlFor="mk-price">
                <TextInput
                  id="mk-price"
                  value={price}
                  onChange={(event) => setPrice(event.target.value)}
                  inputMode="decimal"
                  placeholder="e.g. 150.00"
                />
              </FormField>
              <FormField label="Condition" htmlFor="mk-condition">
                <TextInput
                  id="mk-condition"
                  value={condition}
                  onChange={(event) => setCondition(event.target.value)}
                  placeholder="e.g. Good used, Like new, For parts"
                />
              </FormField>
            </div>
            <div
              style={{
                display: "grid",
                gap: "0.9rem",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              }}
            >
              <FormField label="Brand" htmlFor="mk-brand">
                <TextInput
                  id="mk-brand"
                  value={brand}
                  onChange={(event) => setBrand(event.target.value)}
                />
              </FormField>
              <FormField label="Model" htmlFor="mk-model">
                <TextInput
                  id="mk-model"
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                />
              </FormField>
            </div>
            <FormField label="Description" htmlFor="mk-description">
              <TextArea
                id="mk-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={4}
              />
            </FormField>
            <div style={{ display: "flex", gap: "1.2rem", flexWrap: "wrap" }}>
              <Checkbox
                label="Local pickup"
                checked={pickup}
                onChange={(event) => setPickup(event.target.checked)}
              />
              <Checkbox
                label="Will ship"
                checked={ships}
                onChange={(event) => setShips(event.target.checked)}
              />
            </div>
          </div>
        </Panel>

        <Panel title="Where & how buyers reach you">
          <div style={{ display: "grid", gap: "0.9rem" }}>
            <FormField
              label="Area (blank = your profile's public area)"
              htmlFor="mk-area"
            >
              <TextInput
                id="mk-area"
                value={area}
                onChange={(event) => setArea(event.target.value)}
                placeholder="e.g. Little Falls, MN"
              />
            </FormField>
            <FormField
              label="Show my phone number on this listing"
              htmlFor="mk-phone-choice"
            >
              <Select
                id="mk-phone-choice"
                value={phoneChoice}
                onChange={(event) =>
                  setPhoneChoice(event.target.value as "inherit" | "show" | "hide")
                }
              >
                <option value="inherit">Use my profile setting</option>
                <option value="show">Show it on this listing</option>
                <option value="hide">Never on this listing</option>
              </Select>
            </FormField>
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
              Your email is never shown. Buyers reach you through site
              messages unless you choose to show a number.
            </p>
          </div>
        </Panel>

        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <Button type="submit" loading={saving}>
            {editing ? "Save changes" : "Put it on the board"}
          </Button>
          <LinkButton to="/marketplace/mine" variant="secondary">Cancel</LinkButton>
        </div>
      </form>

      {editing && existing && (
        <Panel title="Photos">
          <div style={{ display: "grid", gap: "0.8rem" }}>
            {existing.photos.length > 0 && (
              <div style={{ display: "flex", gap: "0.7rem", flexWrap: "wrap" }}>
                {existing.photos.map((photo) => (
                  <img
                    key={photo.url}
                    src={photo.url}
                    alt={photo.filename}
                    style={{
                      width: "130px",
                      height: "96px",
                      objectFit: "cover",
                      borderRadius: "var(--radius)",
                      border: "1px solid var(--edge)",
                    }}
                  />
                ))}
              </div>
            )}
            <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
              Photos come off a listing only with the listing itself
              (delete it and relist) — the same rule as inventory and
              parts attachments.
            </p>
            <PhotoUploader
              toolId={existing.id}
              basePath={`/marketplace/listings/${existing.id}`}
              kind="photo"
              onUploaded={() => setPhotoVersion((value) => value + 1)}
            />
          </div>
        </Panel>
      )}
    </div>
  );
}

export default function ListingFormPage() {
  return (
    <RequireAuth>
      <ListingForm />
    </RequireAuth>
  );
}
