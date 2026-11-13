import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  Alert,
  Button,
  FormField,
  TextInput,
  useToast,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { geocodePlace, updateMyProfile } from "../api";
import type { AgentProfile, AreaPolygon } from "../types";

/**
 * The service-area editor (dealer build, 2026-10-20 — Settings ->
 * Dealer profile). Two ways to define a territory:
 *
 *  DRAW — click the map to drop points, drag them to adjust, and
 *  close any shape of any size (the owner's design: territory is
 *  drawn, never reduced to a circle or a box). Undo steps back one
 *  point; Clear starts over.
 *
 *  ZIP + RADIUS — the blunt fallback: a ZIP and a radius in miles,
 *  with the understanding that specifics get confirmed with the
 *  dealer directly.
 *
 * The map is Leaflet over OpenStreetMap tiles. Everything saved
 * goes through the profile write; the server validates the
 * geometry and refuses a public listing that has no area.
 */

type LatLng = [number, number];

const US_CENTER: LatLng = [39.8, -98.5];

function polygonToVertices(polygon: AreaPolygon | null): LatLng[] {
  if (!polygon) return [];
  const ring = polygon.coordinates[0] ?? [];
  const points = ring.slice();
  if (
    points.length > 1 &&
    points[0][0] === points[points.length - 1][0] &&
    points[0][1] === points[points.length - 1][1]
  ) {
    points.pop();
  }
  return points.map(([lng, lat]) => [lat, lng] as LatLng);
}

function verticesToPolygon(vertices: LatLng[]): AreaPolygon {
  const ring: [number, number][] = vertices.map(([lat, lng]) => [lng, lat]);
  if (ring.length > 0) ring.push([...ring[0]]);
  return { type: "Polygon", coordinates: [ring] };
}

function dotIcon(): L.DivIcon {
  return L.divIcon({
    className: "tv-area-vertex",
    html: '<span style="display:block;width:14px;height:14px;border-radius:50%;background:var(--accent);border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45)"></span>',
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export default function ServiceAreaEditor({
  profile,
  onSaved,
}: {
  profile: AgentProfile;
  onSaved: (profile: AgentProfile) => void;
}) {
  const { toast } = useToast();
  const [mode, setMode] = useState<"draw" | "zip">(
    profile.area_type === "radius" ? "zip" : "draw",
  );
  const [vertices, setVertices] = useState<LatLng[]>(() =>
    polygonToVertices(profile.area_polygon),
  );
  const [zip, setZip] = useState(profile.area_zip || "");
  const [radiusMiles, setRadiusMiles] = useState(
    profile.area_radius_miles ? String(profile.area_radius_miles) : "25",
  );
  const [center, setCenter] = useState<LatLng | null>(
    profile.area_center_lat != null && profile.area_center_lng != null
      ? [profile.area_center_lat, profile.area_center_lng]
      : null,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lookupBusy, setLookupBusy] = useState(false);

  const mapRef = useRef<L.Map | null>(null);
  const mapDivRef = useRef<HTMLDivElement | null>(null);
  const layersRef = useRef<L.LayerGroup | null>(null);
  const stateRef = useRef({ mode, vertices, center, radiusMiles });
  stateRef.current = { mode, vertices, center, radiusMiles };

  /* -- map lifecycle ------------------------------------------------ */
  useEffect(() => {
    if (!mapDivRef.current || mapRef.current) return;
    const map = L.map(mapDivRef.current, { scrollWheelZoom: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    layersRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    map.on("click", (e: L.LeafletMouseEvent) => {
      if (stateRef.current.mode !== "draw") return;
      setVertices((v) => [...v, [e.latlng.lat, e.latlng.lng] as LatLng]);
    });
    const initial =
      stateRef.current.center ??
      (stateRef.current.vertices[0] as LatLng | undefined) ??
      US_CENTER;
    map.setView(initial, stateRef.current.vertices.length || stateRef.current.center ? 9 : 4);
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* -- redraw overlays whenever the shape changes ------------------- */
  useEffect(() => {
    const group = layersRef.current;
    const map = mapRef.current;
    if (!group || !map) return;
    group.clearLayers();
    // Deep audit F3-16: the map ink is the USER's accent token,
    // resolved live — never a hardcoded dealer orange.
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "currentColor";
    if (mode === "draw") {
      vertices.forEach((vertex, index) => {
        const marker = L.marker(vertex, {
          draggable: true,
          icon: dotIcon(),
        });
        marker.on("dragend", () => {
          const at = marker.getLatLng();
          setVertices((v) =>
            v.map((p, i) => (i === index ? ([at.lat, at.lng] as LatLng) : p)),
          );
        });
        marker.addTo(group);
      });
      if (vertices.length >= 2) {
        L.polyline(vertices, { color: accent, weight: 2 }).addTo(group);
      }
      if (vertices.length >= 3) {
        L.polygon(vertices, {
          color: accent,
          weight: 2,
          fillOpacity: 0.15,
        }).addTo(group);
      }
    } else if (center) {
      const miles = Number(radiusMiles);
      L.marker(center, { icon: dotIcon() }).addTo(group);
      if (Number.isFinite(miles) && miles > 0) {
        L.circle(center, {
          radius: (miles / 0.621371) * 1000,
          color: accent,
          weight: 2,
          fillOpacity: 0.15,
        }).addTo(group);
      }
    }
  }, [mode, vertices, center, radiusMiles]);

  async function lookupZip() {
    setError("");
    setLookupBusy(true);
    try {
      const point = await geocodePlace(zip.trim());
      setCenter([point.lat, point.lng]);
      mapRef.current?.setView([point.lat, point.lng], 9);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't find that ZIP code.",
      );
    } finally {
      setLookupBusy(false);
    }
  }

  async function save() {
    setError("");
    setBusy(true);
    try {
      let saved: AgentProfile;
      if (mode === "draw") {
        if (vertices.length < 3) {
          setError("Draw at least 3 points to make a territory.");
          return;
        }
        saved = await updateMyProfile({
          area_type: "polygon",
          area_polygon: verticesToPolygon(vertices),
        });
      } else {
        const miles = Number(radiusMiles);
        if (!center) {
          setError("Look up the ZIP code first so the area has a center.");
          return;
        }
        if (!Number.isFinite(miles) || miles < 1 || miles > 500) {
          setError("Radius must be between 1 and 500 miles.");
          return;
        }
        saved = await updateMyProfile({
          area_type: "radius",
          area_zip: zip.trim(),
          area_center_lat: center[0],
          area_center_lng: center[1],
          area_radius_miles: miles,
        });
      }
      onSaved(saved);
      toast("Service area saved.", { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save the area.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeArea() {
    setError("");
    setBusy(true);
    try {
      const saved = await updateMyProfile({ area_type: null });
      setVertices([]);
      setCenter(null);
      onSaved(saved);
      toast("Service area removed.", { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't remove the area.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <div style={{ display: "flex", gap: "0.5rem" }} role="tablist" aria-label="How to set your service area">
        <Button
          size="sm"
          variant={mode === "draw" ? "primary" : "secondary"}
          onClick={() => setMode("draw")}
        >
          Draw on map
        </Button>
        <Button
          size="sm"
          variant={mode === "zip" ? "primary" : "secondary"}
          onClick={() => setMode("zip")}
        >
          ZIP + radius
        </Button>
      </div>
      {mode === "zip" && (
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            alignItems: "end",
            flexWrap: "wrap",
          }}
        >
          <FormField label="ZIP code">
            <TextInput
              value={zip}
              onChange={(e) => setZip(e.target.value)}
              placeholder="e.g. 56345"
              inputMode="numeric"
            />
          </FormField>
          <FormField label="Radius (miles)">
            <TextInput
              value={radiusMiles}
              onChange={(e) => setRadiusMiles(e.target.value)}
              inputMode="decimal"
              style={{ width: "7rem" }}
            />
          </FormField>
          <Button
            variant="secondary"
            onClick={() => void lookupZip()}
            loading={lookupBusy}
            disabled={!zip.trim()}
          >
            Find ZIP
          </Button>
        </div>
      )}
      <div
        ref={mapDivRef}
        style={{
          height: "320px",
          width: "100%",
          borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
          isolation: "isolate",
          zIndex: 0,
        }}
      />
      {mode === "draw" ? (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Click the map to drop points around the area you cover —
          any shape, any size. Drag points to adjust.{" "}
          {vertices.length > 0
            ? `${vertices.length} point${vertices.length === 1 ? "" : "s"} placed.`
            : "No points yet."}
        </p>
      ) : (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          A plain circle around your ZIP. Customers see it as your
          rough area and confirm specifics with you directly.
        </p>
      )}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Button onClick={() => void save()} loading={busy}>
          Save service area
        </Button>
        {mode === "draw" && vertices.length > 0 && (
          <>
            <Button
              variant="secondary"
              onClick={() => setVertices((v) => v.slice(0, -1))}
            >
              Undo point
            </Button>
            <Button variant="secondary" onClick={() => setVertices([])}>
              Clear
            </Button>
          </>
        )}
        {profile.has_area && (
          <Button
            variant="secondary"
            onClick={() => void removeArea()}
            loading={busy}
          >
            Remove area
          </Button>
        )}
      </div>
    </div>
  );
}
