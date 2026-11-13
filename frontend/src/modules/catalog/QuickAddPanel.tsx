import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Button, Panel, TextInput, useToast } from "../../components";
import { ApiError } from "../../lib/api";
import {
  fetchAiStatus,
  identifyItem,
  lookupProduct,
  type LookupField,
  type LookupResult,
} from "./api";

/** Quick Add (wave 4): the layered lookup inside the Add Tool /
 *  Add Battery forms. Once brand + model are typed (or a barcode
 *  is entered/scanned), one lookup runs the chain — community
 *  catalog → barcode database → AI assist — and offers a prefill
 *  panel: every value labeled with its source and accepted
 *  field-by-field. Nothing applies silently; the user edits
 *  freely afterwards.
 *
 *  AI-dependent pieces (the identify box) render ONLY while the
 *  server reports AI configured — a dark seam shows nothing, not
 *  an error. Barcode camera scanning appears ONLY where the
 *  browser ships BarcodeDetector; typing/pasting always works. */

export interface QuickAddValues {
  name?: string;
  brand?: string;
  model?: string;
  category?: string;
  size?: string;
  msrp?: string;
  /** The product page's own description (2026-11-07); the
   *  forms home it in the item's Notes, editable before save. */
  description?: string;
}

const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  brand: "Brand",
  model: "Model",
  category: "Category",
  size: "Size",
  msrp: "List price (MSRP)",
  description: "Description",
};

function sourceLabel(field: LookupField): string {
  if (field.source === "community") return `Community catalog — ${field.detail}`;
  if (field.source === "barcode") return "Barcode database";
  if (field.source === "ai") return "AI suggestion — check it";
  return field.detail || field.source;
}

export function QuickAddPanel({
  kind,
  brand,
  model,
  upc,
  onUpcChange,
  onApply,
}: {
  kind: "tool" | "battery";
  brand: string;
  model: string;
  upc: string;
  onUpcChange: (value: string) => void;
  onApply: (values: QuickAddValues) => void;
}) {
  const { toast } = useToast();
  const [result, setResult] = useState<LookupResult | null>(null);
  const [applied, setApplied] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  const [aiOn, setAiOn] = useState(false);
  const [identifyText, setIdentifyText] = useState("");
  const [scanning, setScanning] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const lastKey = useRef<string>("");

  useEffect(() => {
    let live = true;
    fetchAiStatus()
      .then((s) => {
        if (live) setAiOn(s.configured);
      })
      .catch(() => {
        if (live) setAiOn(false);
      });
    return () => {
      live = false;
    };
  }, []);

  const runLookup = useCallback(
    async (b: string, m: string, u: string) => {
      if (!b.trim() && !m.trim() && !u.trim()) return;
      setBusy(true);
      try {
        const data = await lookupProduct({
          brand: b.trim(),
          model: m.trim(),
          upc: u.trim(),
        });
        setResult(data);
        setApplied(new Set());
        setChecked(true);
      } catch (err) {
        if (err instanceof ApiError && err.code === "insufficient_credits") {
          toast(err.message, { tone: "danger" });
        }
        // Every other failure is quiet: Quick Add is an assist,
        // never a blocker — manual entry just continues.
        setChecked(true);
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  // Auto-check once brand + model are both present (debounced),
  // and whenever the barcode changes to a fresh value.
  useEffect(() => {
    const key = `${brand.trim()}|${model.trim()}|${upc.trim()}`;
    if (key === lastKey.current) return;
    if (!((brand.trim() && model.trim()) || upc.trim())) return;
    const timer = setTimeout(() => {
      lastKey.current = key;
      void runLookup(brand, model, upc);
    }, 600);
    return () => clearTimeout(timer);
  }, [brand, model, upc, runLookup]);

  const stopScan = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
  }, []);

  useEffect(() => stopScan, [stopScan]);

  const startScan = async () => {
    const Detector = (
      window as unknown as { BarcodeDetector?: new (opts: object) => {
        detect: (source: HTMLVideoElement) => Promise<{ rawValue?: string }[]>;
      } }
    ).BarcodeDetector;
    if (!Detector || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      setScanning(true);
      requestAnimationFrame(async () => {
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = stream;
        await video.play().catch(() => undefined);
        const detector = new Detector({ formats: ["upc_a", "upc_e", "ean_13", "ean_8", "code_128"] });
        const tick = async () => {
          if (!streamRef.current) return;
          try {
            const codes = await detector.detect(video);
            const value = codes.find((c) => c.rawValue)?.rawValue;
            if (value) {
              onUpcChange(value);
              stopScan();
              void runLookup(brand, model, value);
              return;
            }
          } catch {
            /* keep scanning */
          }
          if (streamRef.current) setTimeout(tick, 400);
        };
        void tick();
      });
    } catch {
      toast("Camera isn't available — type or paste the barcode instead.", {
        tone: "danger",
      });
    }
  };

  const runIdentify = async () => {
    if (!identifyText.trim()) return;
    setBusy(true);
    try {
      const data = await identifyItem(identifyText.trim());
      setResult(data);
      setApplied(new Set());
      setChecked(true);
    } catch (err) {
      if (err instanceof ApiError) toast(err.message, { tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const applyField = (field: string, fieldData: LookupField) => {
    onApply({ [field]: String(fieldData.value) } as QuickAddValues);
    setApplied((prev) => new Set(prev).add(field));
  };

  const applyAll = () => {
    if (!result) return;
    const values: QuickAddValues = {};
    for (const [field, fieldData] of Object.entries(result.fields)) {
      if (field === "size" && kind === "battery") continue;
      (values as Record<string, string>)[field] = String(fieldData.value);
    }
    onApply(values);
    setApplied(new Set(Object.keys(values)));
  };

  const canScan =
    typeof window !== "undefined" &&
    "BarcodeDetector" in window &&
    !!navigator.mediaDevices?.getUserMedia;
  const fields = result
    ? Object.entries(result.fields).filter(
        ([field]) => !(field === "size" && kind === "battery"),
      )
    : [];

  return (
    <Panel title="Quick Add — find it fast">
      <p className="tv-muted" style={{ marginTop: 0 }}>
        Enter the brand and model (or a barcode) and we'll check the
        community catalog, the barcode database, and — when it's
        switched on — AI. Suggestions are yours to accept or ignore;
        nothing fills in on its own.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <div style={{ flex: "1 1 220px" }}>
          <label className="tv-field-label" htmlFor="quickadd-upc">
            UPC / barcode
          </label>
          <TextInput
            id="quickadd-upc"
            value={upc}
            onChange={(e) => onUpcChange(e.target.value)}
            placeholder="Type or paste the barcode number"
            inputMode="numeric"
          />
        </div>
        {canScan && !scanning && (
          <Button type="button" variant="secondary" onClick={startScan}>
            Scan barcode
          </Button>
        )}
        <Button
          type="button"
          variant="secondary"
          disabled={busy || (!brand.trim() && !model.trim() && !upc.trim())}
          onClick={() => void runLookup(brand, model, upc)}
        >
          {busy ? "Checking…" : "Check for suggestions"}
        </Button>
      </div>
      {scanning && (
        <div style={{ marginTop: 10 }}>
          <video
            ref={videoRef}
            style={{ width: "100%", maxWidth: 420, borderRadius: 8 }}
            muted
            playsInline
          />
          <div style={{ marginTop: 6 }}>
            <Button type="button" variant="secondary" onClick={stopScan}>
              Stop scanning
            </Button>
          </div>
        </div>
      )}

      {checked && !busy && fields.length === 0 && (
        <p className="tv-muted" style={{ marginBottom: 0 }}>
          No suggestions found — the manual fields below work as always.
        </p>
      )}
      {result?.model_mismatch && result.found_model && (
        <p className="tv-muted" role="status">
          The page we found is for {result.found_model} — a different
          version than the one you typed. Check it&apos;s yours before
          using it.
        </p>
      )}
      {fields.length > 0 && (
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          {fields.map(([field, fieldData]) => (
            <div
              key={field}
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <span style={{ minWidth: 110 }}>
                <strong>{FIELD_LABELS[field] ?? field}:</strong>
              </span>
              <span>{String(fieldData.value)}</span>
              <Badge tone={fieldData.source === "ai" ? "warning" : "neutral"}>
                {sourceLabel(fieldData)}
              </Badge>
              <span style={{ flex: 1 }} />
              {applied.has(field) ? (
                <Badge tone="success">Applied</Badge>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => applyField(field, fieldData)}
                >
                  Use this
                </Button>
              )}
            </div>
          ))}
          <div>
            <Button type="button" size="sm" onClick={applyAll}>
              Use all suggestions
            </Button>
          </div>
        </div>
      )}

      {aiOn && (
        <div style={{ marginTop: 14 }}>
          <label className="tv-field-label" htmlFor="quickadd-identify">
            Not sure what it is? Describe it or paste a listing title — AI
            will take a guess (check it before saving)
          </label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 260px" }}>
              <TextInput
                id="quickadd-identify"
                value={identifyText}
                onChange={(e) => setIdentifyText(e.target.value)}
                placeholder="e.g. Milwaukee M18 Fuel half-inch impact wrench, model 2967-20"
              />
            </div>
            <Button
              type="button"
              variant="secondary"
              disabled={busy || !identifyText.trim()}
              onClick={() => void runIdentify()}
            >
              Identify it
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}
