import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import QRCode from "qrcode";
import {
  Alert,
  Button,
  Checkbox,
  EmptyState,
  FormField,
  Panel,
  Select,
  Spinner,
  LinkButton,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { RequireAuth } from "../core";
import {
  chunkSheets,
  DEFAULT_ITEM_PRESET,
  DEFAULT_LOCATION_PRESET,
  LABEL_PRESETS,
  itemQrPayload,
  locationQrPayload,
  type LabelItemData,
  type LabelPreset,
  type LabelSelectionData,
  type LocationLabelData,
} from "./labels";
import "./labels.css";

/** One label face to render: text lines + the QR payload. Item
 *  faces and bin (location) faces share the sheet machinery. */
interface Face {
  key: string;
  payload: string;
  name: string;
  subs: string[];
  bin: boolean;
}

function itemFace(item: LabelItemData, origin: string): Face {
  const subs: string[] = [];
  const brandModel = [item.brand, item.model].filter(Boolean).join(" · ");
  if (brandModel) subs.push(brandModel);
  if (item.serial_number) subs.push(`S/N ${item.serial_number}`);
  if (item.location) subs.push(item.location);
  if (item.is_set) subs.push("Set");
  return {
    key: `item-${item.kind}-${item.id}`,
    payload: itemQrPayload(origin, item.kind, item.id),
    name: item.name,
    subs,
    bin: false,
  };
}

function locationFace(row: LocationLabelData, origin: string): Face {
  return {
    key: `loc-${row.location}`,
    payload: locationQrPayload(origin, row.location),
    name: row.location,
    subs: [`${row.count} item${row.count === 1 ? "" : "s"}`],
    bin: true,
  };
}

function LabelFace({ face, qr, preset }: { face: Face; qr?: string; preset: LabelPreset }) {
  const sizeClass = face.bin
    ? "tv-label--tall tv-label--bin"
    : preset.labelH >= 2
      ? "tv-label--tall"
      : "tv-label--short";
  return (
    <div
      className={`tv-label ${sizeClass}`}
      style={{ width: `${preset.labelW}in`, height: `${preset.labelH}in` }}
    >
      {qr ? (
        <img className="tv-label-qr" src={qr} alt="" />
      ) : (
        <div className="tv-label-qr" aria-hidden="true" />
      )}
      <div className="tv-label-text">
        <div className="tv-label-name">{face.name}</div>
        {face.subs.map((line) => (
          <div key={line} className="tv-label-sub">
            {line}
          </div>
        ))}
      </div>
      <span className="tv-label-mark">TOOLBOX VAULT</span>
    </div>
  );
}

function Sheet({
  faces,
  preset,
  qrMap,
}: {
  faces: Face[];
  preset: LabelPreset;
  qrMap: Record<string, string>;
}) {
  const sheets = chunkSheets(faces, preset);
  return (
    <div className="tv-labels-sheets">
      {sheets.map((chunk, sheetIdx) => (
        <div
          key={sheetIdx}
          className="tv-label-sheet"
          style={{
            width: `${preset.sheetW}in`,
            height: preset.rowsPerSheet ? `${preset.sheetH}in` : undefined,
            paddingTop: `${preset.marginTop}in`,
            paddingLeft: `${preset.marginLeft}in`,
            gridTemplateColumns: `repeat(${preset.columns}, ${preset.labelW}in)`,
            columnGap: `${preset.gapX}in`,
            rowGap: `${preset.gapY}in`,
          }}
        >
          {chunk.map((face) => (
            <LabelFace key={face.key} face={face} qr={qrMap[face.payload]} preset={preset} />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * QR bin labels (blueprint §18): pick a label stock, preview the
 * sheet at true physical size, print. Two modes — item labels (from
 * a selection made in the inventory list or an item's Print label
 * action) and bin labels (one large label per stored location).
 * Resolution is server-side and owner-scoped: refs that aren't the
 * caller's items never render; they surface only as the skipped
 * count. The printed sheet is black-on-white in every theme (see
 * labels.css).
 */
export default function LabelsPrintPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const idsParam = searchParams.get("ids") ?? "";
  const [mode, setMode] = useState<"items" | "locations">(
    searchParams.get("mode") === "locations" ? "locations" : "items",
  );
  const [itemPresetId, setItemPresetId] = useState(DEFAULT_ITEM_PRESET.id);
  const [locationPresetId, setLocationPresetId] = useState(DEFAULT_LOCATION_PRESET.id);

  const [selection, setSelection] = useState<LabelSelectionData | null>(null);
  const [selectionError, setSelectionError] = useState("");
  const [locations, setLocations] = useState<LocationLabelData[] | null>(null);
  const [locationsError, setLocationsError] = useState("");
  const [pickedLocations, setPickedLocations] = useState<Set<string> | null>(null);
  const [qrMap, setQrMap] = useState<Record<string, string>>({});

  const origin = window.location.origin;

  useEffect(() => {
    if (!idsParam) {
      setSelection({ labels: [], skipped: 0 });
      return;
    }
    let cancelled = false;
    setSelection(null);
    api<LabelSelectionData>(`/inventory/labels?items=${encodeURIComponent(idsParam)}`)
      .then((data) => {
        if (!cancelled) {
          setSelection(data);
          setSelectionError("");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSelection({ labels: [], skipped: 0 });
          setSelectionError(
            err instanceof ApiError ? err.message : "Couldn't load the selected items.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [idsParam]);

  useEffect(() => {
    if (mode !== "locations" || locations !== null) return;
    let cancelled = false;
    api<LocationLabelData[]>("/inventory/labels/locations")
      .then((data) => {
        if (cancelled) return;
        setLocations(data);
        setLocationsError("");
        // Default: every location picked — the user unpicks.
        setPickedLocations(new Set(data.map((row) => row.location)));
      })
      .catch((err) => {
        if (!cancelled) {
          setLocations([]);
          setLocationsError(
            err instanceof ApiError ? err.message : "Couldn't load your locations.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mode, locations]);

  const itemPreset = LABEL_PRESETS.find((p) => p.id === itemPresetId) ?? DEFAULT_ITEM_PRESET;
  const locationPreset =
    LABEL_PRESETS.find((p) => p.id === locationPresetId) ?? DEFAULT_LOCATION_PRESET;

  const itemFaces = useMemo(
    () => (selection ? selection.labels.map((item) => itemFace(item, origin)) : []),
    [selection, origin],
  );
  const locationFaces = useMemo(
    () =>
      (locations ?? [])
        .filter((row) => pickedLocations?.has(row.location))
        .map((row) => locationFace(row, origin)),
    [locations, pickedLocations, origin],
  );
  const activeFaces = mode === "items" ? itemFaces : locationFaces;

  // QR images are generated client-side at print-crisp resolution.
  useEffect(() => {
    const missing = activeFaces.filter((face) => !(face.payload in qrMap));
    if (missing.length === 0) return;
    let cancelled = false;
    Promise.all(
      missing.map(async (face) => {
        const url = await QRCode.toDataURL(face.payload, {
          errorCorrectionLevel: "M",
          margin: 1,
          width: 512,
        });
        return [face.payload, url] as const;
      }),
    )
      .then((entries) => {
        if (!cancelled) {
          setQrMap((prev) => ({ ...prev, ...Object.fromEntries(entries) }));
        }
      })
      .catch(() => {
        /* a failed QR leaves its slot blank rather than breaking the sheet */
      });
    return () => {
      cancelled = true;
    };
  }, [activeFaces, qrMap]);

  function switchMode(next: "items" | "locations") {
    setMode(next);
    const params = new URLSearchParams(searchParams);
    if (next === "locations") params.set("mode", "locations");
    else params.delete("mode");
    setSearchParams(params, { replace: true });
  }

  function toggleLocation(location: string) {
    setPickedLocations((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(location)) next.delete(location);
      else next.add(location);
      return next;
    });
  }

  const preset = mode === "items" ? itemPreset : locationPreset;
  const printable = activeFaces.length > 0;

  return (
    <RequireAuth>
      <div className="tv-labels-page" style={{ display: "grid", gap: "var(--spacing)" }}>
        <div className="tv-labels-noprint" style={{ display: "grid", gap: "var(--spacing)" }}>
          <div
            style={{
              display: "flex",
              gap: "1rem",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
            }}
          >
            <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Print labels</h1>
            <LinkButton to="/inventory" variant="secondary">Back to inventory</LinkButton>
          </div>

          <Panel>
            <div style={{ display: "grid", gap: "0.9rem" }}>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <Button
                  variant={mode === "items" ? "primary" : "secondary"}
                  onClick={() => switchMode("items")}
                >
                  Item labels
                </Button>
                <Button
                  variant={mode === "locations" ? "primary" : "secondary"}
                  onClick={() => switchMode("locations")}
                >
                  Bin labels
                </Button>
              </div>

              <FormField
                label="Label stock"
                htmlFor="labels-preset"
              >
                <Select
                  id="labels-preset"
                  value={preset.id}
                  onChange={(e) =>
                    mode === "items"
                      ? setItemPresetId(e.target.value)
                      : setLocationPresetId(e.target.value)
                  }
                >
                  {LABEL_PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} — {p.blurb}
                    </option>
                  ))}
                </Select>
              </FormField>

              {mode === "locations" && (
                <>
                  {locations === null ? (
                    <p
                      style={{
                        margin: 0,
                        color: "var(--text-muted)",
                        display: "flex",
                        gap: "var(--space-2)",
                        alignItems: "center",
                      }}
                    >
                      <Spinner size="sm" /> Loading locations…
                    </p>
                  ) : locations.length === 0 ? (
                    <p style={{ margin: 0, color: "var(--text-muted)" }}>
                      No locations yet — set a location on a tool or battery and it
                      shows up here for a bin label.
                    </p>
                  ) : (
                    <div style={{ display: "grid", gap: "0.4rem" }}>
                      {locations.map((row) => (
                        <Checkbox
                          key={row.location}
                          label={`${row.location} — ${row.count} item${row.count === 1 ? "" : "s"}`}
                          checked={pickedLocations?.has(row.location) ?? false}
                          onChange={() => toggleLocation(row.location)}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}

              <div
                style={{
                  display: "flex",
                  gap: "0.75rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <Button onClick={() => window.print()} disabled={!printable}>
                  Print {activeFaces.length} label{activeFaces.length === 1 ? "" : "s"}
                </Button>
                <span style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
                  In the print dialog, use “Actual size” / 100% scale and no
                  margins — the sheet is already laid out to the stock.
                </span>
              </div>
            </div>
          </Panel>

          {mode === "items" && selectionError && (
            <Alert tone="danger">{selectionError}</Alert>
          )}
          {mode === "locations" && locationsError && (
            <Alert tone="danger">{locationsError}</Alert>
          )}
          {mode === "items" && selection && selection.skipped > 0 && (
            <Alert tone="warning">
              {selection.skipped} selected item{selection.skipped === 1 ? "" : "s"}{" "}
              couldn’t be found in your inventory and{" "}
              {selection.skipped === 1 ? "was" : "were"} skipped.
            </Alert>
          )}
        </div>

        {mode === "items" &&
          (selection === null ? (
            <p
              className="tv-labels-noprint"
              style={{
                margin: 0,
                color: "var(--text-muted)",
                display: "flex",
                gap: "var(--space-2)",
                alignItems: "center",
              }}
            >
              <Spinner size="sm" /> Loading your selection…
            </p>
          ) : selection.labels.length === 0 ? (
            <div className="tv-labels-noprint">
              <EmptyState
                title={idsParam ? "Nothing to print" : "No items selected"}
                description={
                  idsParam
                    ? "None of the selected items are in your inventory anymore."
                    : "Pick items in your inventory with “Select for labels”, or use Print label on any item’s page."
                }
                action={
                  <LinkButton to="/inventory">Go to inventory</LinkButton>
                }
              />
            </div>
          ) : (
            <Sheet faces={itemFaces} preset={itemPreset} qrMap={qrMap} />
          ))}

        {mode === "locations" &&
          locations !== null &&
          (locationFaces.length === 0 ? (
            <div className="tv-labels-noprint">
              <EmptyState
                title="No bin labels selected"
                description="Tick at least one location above to build its bin label."
              />
            </div>
          ) : (
            <Sheet faces={locationFaces} preset={locationPreset} qrMap={qrMap} />
          ))}
      </div>
    </RequireAuth>
  );
}
