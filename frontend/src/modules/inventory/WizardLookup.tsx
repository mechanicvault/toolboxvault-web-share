import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import "./wizard.css";

import {
  AiWorking,
  Button,
  FormField,
  formGridStyle,
  Panel,
  TextInput,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { type DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import {
  fetchAiStatus,
  fetchLookupPhoto,
  identifyPhoto,
  IDENTIFY_PHOTO_MAX_BYTES,
  lookupProduct,
  type LookupField,
  type LookupResult,
} from "../catalog/api";
import { type QuickAddValues } from "../catalog/QuickAddPanel";
import { FieldSuggest } from "./components/FieldSuggest";

/** The wizard's quick-lookup step (owner fix, 2026-10-25;
 *  grounded rework the same day).
 *
 *  Ryan's verdict on the first cut: he typed a brand in the top
 *  boxes and "nothing happens, no buttons to click", then found a
 *  SECOND box further down asking for the same thing, whose
 *  results were "very unorganized, very crude looking". So this
 *  step is deliberately boring in the best way:
 *
 *  - ONE tidy group — brand, model number, barcode, and a
 *    product-page link box — with ONE primary button ("Look it
 *    up") sitting right there. Enter in any box runs it too. No
 *    silent auto-lookups, no dead inputs, and NO second identify
 *    box (the shared QuickAddPanel keeps its fuller layout on
 *    the full Tool/Battery forms; the wizard runs the same
 *    lookup chain directly).
 *  - A "Skip quick lookup" button is visible at ALL times and
 *    goes straight to the basics step.
 *  - The chain behind it is grounded: it reads the facts off a
 *    real product page when one can be found (or the pasted
 *    link), and the AI's own memory is a labeled last resort
 *    whose echoes of the user's typing never count as finds.
 *  - A hit renders as ONE clean card: the item's name up top,
 *    the found specs as tidy labeled rows, one plain line saying
 *    where the match came from (the product page is NAMED and
 *    linked), and two clear exits — "Use this" (prefills the
 *    basics, auto-checks the sections it fills) and "Not it —
 *    look up again". Details without a verified name render as
 *    an honest PARTIAL card that says the name couldn't be
 *    verified — never a full-success card titled with the
 *    user's own typing. A miss says so plainly, with the same
 *    two exits (the button above, or Skip); a pasted page that
 *    couldn't be read says exactly that.
 *  - PHOTOS: when the product page yielded a real main photo,
 *    the card offers it — "Use this photo" downloads it (via
 *    the server, guarded like a manual import) and stages it
 *    exactly like an uploaded photo; "I'll add my own" retires
 *    the offer. No page photo, no offer — never a stock or
 *    invented image.
 *  - PHOTO IDENTIFICATION (AI wizard completion, 2026-11-07):
 *    while the AI seam is lit, a second path in — "Identify
 *    from a photo": the user uploads or snaps a photo of the
 *    tool or its label, the AI reads it and states its
 *    confidence in plain words, and on the user's "Look it
 *    up" the identification fills the brand/model boxes and
 *    runs THIS SAME grounded lookup — the filled facts still
 *    come from the verified product page. Discarding costs
 *    nothing and the typed path is untouched; a photo the AI
 *    can't read lands on a soft note, never an error wall.
 *    A dark seam renders no photo affordance at all (the
 *    dark-seam contract, same as every AI surface). */

type Phase = "idle" | "busy" | "hit" | "partial" | "miss" | "failed" | "linkfail";

const ROW_FIELDS: { key: string; labelKey: DictKey }[] = [
  { key: "brand", labelKey: "wizard.fBrand" },
  { key: "model", labelKey: "wizard.fModel" },
  { key: "category", labelKey: "wizard.fCategory" },
  { key: "size", labelKey: "wizard.fSize" },
  { key: "msrp", labelKey: "wizard.fMsrp" },
];

const SOURCE_ORDER = ["community", "barcode", "web", "ai"] as const;
const SOURCE_LABEL_KEYS: Record<string, DictKey> = {
  community: "wizard.srcCommunity",
  barcode: "wizard.srcBarcode",
  web: "wizard.srcWeb",
  ai: "wizard.srcAi",
};

type PhotoState = "offered" | "busy" | "chosen" | "declined";

/** A-13 (Deep Audit Round 2): the preview's lifecycle. The card
 * used to render the maker's raw remote URL in an <img> — when
 * the source refuses hotlinking (or 404s, or needs a referrer),
 * the user got a solid black box with a broken-image glyph and
 * was asked to decide on a photo they could not see. The save
 * flow ("Use this photo") never had that problem: it goes
 * through the server-side fetch (/catalog/fetch-photo). So the
 * preview now rides the SAME path: the photo is fetched through
 * the server when a hit lands, and the card shows the frame
 * ONLY once those bytes are in hand as an object URL. While the
 * fetch is in flight or if it fails, there is no frame at all —
 * never a broken one — and a failed fetch retires the offer
 * (the save would fail the same way). */
type PhotoPreview =
  | { status: "loading" }
  | { status: "ready"; url: string; file: File }
  | { status: "failed" };

export function WizardLookup({
  brand,
  model,
  upc,
  onBrandChange,
  onModelChange,
  onUpcChange,
  onApply,
  onApplyPhoto,
  onLinkChange,
  onDone,
  seedPhoto,
  onSeedPhotoConsumed,
}: {
  brand: string;
  model: string;
  upc: string;
  onBrandChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onUpcChange: (value: string) => void;
  onApply: (values: QuickAddValues) => void;
  /** Stage the product page's photo as this item's photo
   *  (rides the wizard's normal staged-photo save). */
  onApplyPhoto?: (file: File) => void;
  /** The pasted-link box is the one lookup input held locally;
   *  report it up so the wizard's unsaved-work guard (B-08)
   *  counts it as the typed work it is. */
  onLinkChange?: (value: string) => void;
  onDone: () => void;
  /** Quick Add seed (widget wave 2 build 3): a photo handed in
   *  from the Home Quick Add widget. When the AI seam is lit,
   *  the identification flow below runs on it exactly as if the
   *  user had picked it here; the wizard has already staged the
   *  same File as the item's photo. Absent = the step behaves
   *  exactly as it always has. */
  seedPhoto?: File | null;
  /** Called once the seed has been taken (run or stepped
   *  aside for), so the wizard drops its copy. */
  onSeedPhotoConsumed?: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<LookupResult | null>(null);
  const [link, setLink] = useState("");
  useEffect(() => {
    onLinkChange?.(link);
  }, [link, onLinkChange]);
  const [photoState, setPhotoState] = useState<PhotoState>("offered");
  const [photoPreview, setPhotoPreview] = useState<PhotoPreview | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const aliveRef = useRef(true);

  // Photo identification: offered only while the AI seam is
  // lit (the status read decides; a failed read hides it, the
  // dark-seam contract).
  const [aiOn, setAiOn] = useState(false);
  const [photoPhase, setPhotoPhase] = useState<
    "idle" | "busy" | "found" | "unknown" | "failed"
  >("idle");
  const [photoResult, setPhotoResult] = useState<LookupResult | null>(null);
  const photoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchAiStatus()
      .then((s) => {
        if (!cancelled) setAiOn(s.configured);
      })
      .catch(() => {
        if (!cancelled) setAiOn(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A-13: fetch the offered photo through the server path as
  // soon as a hit carries one (see PhotoPreview above). The
  // fetched File is cached so "Use this photo" reuses these
  // exact bytes instead of fetching twice.
  const offerUrl =
    (phase === "hit" || phase === "partial") && result?.image_url
      ? result.image_url
      : null;
  useEffect(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    if (!offerUrl) {
      setPhotoPreview(null);
      return;
    }
    let cancelled = false;
    setPhotoPreview({ status: "loading" });
    fetchLookupPhoto(offerUrl)
      .then((file) => {
        if (cancelled || !aliveRef.current) return;
        const url = URL.createObjectURL(file);
        previewUrlRef.current = url;
        setPhotoPreview({ status: "ready", url, file });
      })
      .catch(() => {
        if (cancelled || !aliveRef.current) return;
        setPhotoPreview({ status: "failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [offerUrl]);

  const stopScan = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScanning(false);
  }, []);

  useEffect(() => stopScan, [stopScan]);

  // Editing any box after a result retires that result — the
  // card on screen always matches the boxes above it.
  const retire = () => {
    if (phase !== "idle" && phase !== "busy") {
      setPhase("idle");
      setResult(null);
      setPhotoState("offered");
    }
  };
  const edit =
    (apply: (value: string) => void) =>
    (value: string) => {
      apply(value);
      retire();
    };
  const editBrand = edit(onBrandChange);
  const editModel = edit(onModelChange);
  const editUpc = edit(onUpcChange);
  const editLink = (value: string) => {
    setLink(value);
    retire();
  };

  const runLookup = useCallback(
    async (b: string, m: string, u: string, l: string) => {
      if (!b.trim() && !m.trim() && !u.trim() && !l.trim()) return;
      setPhase("busy");
      try {
        const data = await lookupProduct({
          brand: b.trim(),
          model: m.trim(),
          upc: u.trim(),
          link: l.trim(),
        });
        if (!aliveRef.current) return;
        setPhotoState("offered");
        if (data.link_error) {
          setResult(null);
          setPhase("linkfail");
        } else if (Object.keys(data.fields).length > 0) {
          setResult(data);
          setPhase(data.partial ? "partial" : "hit");
        } else {
          setResult(data);
          setPhase("miss");
        }
      } catch (err) {
        if (!aliveRef.current) return;
        if (err instanceof ApiError && err.code === "insufficient_credits") {
          toast(err.message, { tone: "danger" });
        }
        setResult(null);
        setPhase("failed");
      }
    },
    [toast],
  );

  const startScan = async () => {
    const Detector = (
      window as unknown as {
        BarcodeDetector?: new (opts: object) => {
          detect: (source: HTMLVideoElement) => Promise<{ rawValue?: string }[]>;
        };
      }
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
        const detector = new Detector({
          formats: ["upc_a", "upc_e", "ean_13", "ean_8", "code_128"],
        });
        const tick = async () => {
          if (!streamRef.current) return;
          try {
            const codes = await detector.detect(video);
            const value = codes.find((c) => c.rawValue)?.rawValue;
            if (value) {
              onUpcChange(value);
              stopScan();
              void runLookup(brand, model, value, link);
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
      toast(t("wizard.cameraUnavailable"), {
        tone: "danger",
      });
    }
  };

  const canScan =
    typeof window !== "undefined" &&
    "BarcodeDetector" in window &&
    !!navigator.mediaDevices?.getUserMedia;
  const canRun = Boolean(
    brand.trim() || model.trim() || upc.trim() || link.trim(),
  );

  const fields: Record<string, LookupField> = result?.fields ?? {};
  const presentSources = SOURCE_ORDER.filter((source) =>
    Object.values(fields).some((field) => field.source === source),
  );
  const anyAi = presentSources.includes("ai");
  const webOff =
    result !== null && result.web_configured === false && !link.trim();

  const useThis = () => {
    if (!result) return;
    const values: QuickAddValues = {};
    for (const key of [
      "name",
      "brand",
      "model",
      "category",
      "size",
      "msrp",
      "description",
    ]) {
      const field = result.fields[key];
      if (field) (values as Record<string, string>)[key] = String(field.value);
    }
    onApply(values);
    onDone();
  };

  // -- photo identification ------------------------------------
  const onPhotoPicked = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > IDENTIFY_PHOTO_MAX_BYTES) {
      toast(t("wizard.photoIdTooBig"), { tone: "danger" });
      return;
    }
    setPhotoPhase("busy");
    setPhotoResult(null);
    try {
      const data = await identifyPhoto(file);
      if (!aliveRef.current) return;
      if (Object.keys(data.fields).length > 0) {
        setPhotoResult(data);
        setPhotoPhase("found");
      } else {
        setPhotoPhase("unknown");
      }
    } catch (err) {
      if (!aliveRef.current) return;
      if (err instanceof ApiError && err.code === "insufficient_credits") {
        toast(err.message, { tone: "danger" });
        setPhotoPhase("idle");
        return;
      }
      // Every other failure is a soft landing: the typed path
      // above is untouched and fully usable.
      setPhotoPhase("failed");
    }
  };

  const usePhotoId = () => {
    if (!photoResult) return;
    const b = photoResult.fields.brand
      ? String(photoResult.fields.brand.value)
      : brand;
    const m = photoResult.fields.model
      ? String(photoResult.fields.model.value)
      : model;
    editBrand(b);
    editModel(m);
    // The photo path replaces the pasted-link path: the
    // grounded lookup runs on the identified brand + model.
    setLink("");
    setPhotoResult(null);
    setPhotoPhase("idle");
    void runLookup(b, m, upc, "");
  };

  const discardPhotoId = () => {
    setPhotoResult(null);
    setPhotoPhase("idle");
  };

  // Quick Add seed (widget wave 2 build 3): a photo handed in
  // from Home runs the identification above the moment the AI
  // seam reports lit — the same call, the same soft landings,
  // as a pick on this step. Two guards keep it a guest, never
  // an interruption: it waits for the seam read (a dark seam
  // has no photo affordance at all, so the seed simply stays
  // staged as the item's photo), and if the user has already
  // started on this step themselves, the auto-run steps aside
  // and only the staging stands. Consumed exactly once.
  const seedHandledRef = useRef(false);
  const photoPickedRef = useRef(onPhotoPicked);
  photoPickedRef.current = onPhotoPicked;
  useEffect(() => {
    if (!seedPhoto || seedHandledRef.current || !aiOn) return;
    seedHandledRef.current = true;
    if (phase === "idle" && photoPhase === "idle") {
      void photoPickedRef.current(seedPhoto);
    }
    onSeedPhotoConsumed?.();
  }, [seedPhoto, aiOn, phase, photoPhase, onSeedPhotoConsumed]);

  const photoIdCard = photoPhase === "found" && photoResult && (
    <div className="tv-wizard-hit">
      <p className="tv-wizard-hit-source">{t("wizard.photoIdTitle")}</p>
      {photoResult.fields.name && (
        <p className="tv-wizard-hit-name">
          {String(photoResult.fields.name.value)}
        </p>
      )}
      <dl className="tv-wizard-hit-rows">
        {ROW_FIELDS.filter(({ key }) => photoResult.fields[key]).map(
          ({ key, labelKey }) => (
            <div className="tv-wizard-hit-row" key={key}>
              <dt>{t(labelKey)}</dt>
              <dd>{String(photoResult.fields[key].value)}</dd>
            </div>
          ),
        )}
      </dl>
      <p className="tv-wizard-hit-source" role="status">
        {photoResult.confidence === "high"
          ? t("wizard.photoIdConfidenceHigh")
          : photoResult.confidence === "medium"
            ? t("wizard.photoIdConfidenceMedium")
            : t("wizard.photoIdConfidenceLow")}
      </p>
      <div className="tv-wizard-hit-actions">
        <Button type="button" onClick={usePhotoId}>
          {t("wizard.photoIdUse")}
        </Button>
        <Button type="button" variant="secondary" onClick={discardPhotoId}>
          {t("wizard.photoIdDiscard")}
        </Button>
      </div>
    </div>
  );

  const notIt = () => {
    setResult(null);
    setPhase("idle");
    setPhotoState("offered");
    document.getElementById("wz-lookup-brand")?.focus();
  };

  const usePhoto = async () => {
    if (!result?.image_url || !onApplyPhoto) return;
    setPhotoState("busy");
    try {
      // Reuse the preview's server-fetched bytes when they are
      // already in hand (A-13); fall back to the same fetch.
      const file =
        photoPreview?.status === "ready"
          ? photoPreview.file
          : await fetchLookupPhoto(result.image_url);
      if (!aliveRef.current) return;
      onApplyPhoto(file);
      setPhotoState("chosen");
    } catch {
      if (!aliveRef.current) return;
      setPhotoState("offered");
      toast(t("wizard.photoFailed"), { tone: "danger" });
    }
  };

  const photoOffer = (phase === "hit" || phase === "partial") &&
    result?.image_url &&
    onApplyPhoto &&
    photoPreview !== null &&
    photoPreview.status !== "failed" && (
      <div className="tv-wizard-hit-photo">
        {photoPreview.status === "ready" && (
          <img
            className="tv-wizard-hit-photo-img"
            src={photoPreview.url}
            alt=""
            loading="lazy"
          />
        )}
        <div className="tv-wizard-hit-photo-side">
          <p className="tv-wizard-hit-source">{t("wizard.photoFromPage")}</p>
          {photoState === "chosen" ? (
            <p className="tv-wizard-hit-source">{t("wizard.photoAdded")}</p>
          ) : photoState !== "declined" ? (
            <div className="tv-wizard-hit-actions">
              <Button
                type="button"
                size="sm"
                loading={photoState === "busy"}
                onClick={() => void usePhoto()}
              >
                {t("wizard.usePhoto")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => setPhotoState("declined")}
              >
                {t("wizard.ownPhoto")}
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    );

  const resultCard = (partial: boolean) =>
    result && (
      <div className="tv-wizard-hit">
        {partial ? (
          <p className="tv-wizard-hit-name">{t("wizard.partialTitle")}</p>
        ) : (
          <p className="tv-wizard-hit-name">
            {fields.name ? String(fields.name.value) : ""}
          </p>
        )}
        {presentSources.length > 0 && (
          <p className="tv-wizard-hit-source">
            {t("wizard.foundVia").replace(
              "{sources}",
              presentSources
                .map((source) => t(SOURCE_LABEL_KEYS[source]))
                .join(" · "),
            )}
            {result.source_url && result.source_name ? (
              <>
                {" — "}
                <a href={result.source_url} target="_blank" rel="noreferrer">
                  {result.source_name}
                </a>
              </>
            ) : null}
          </p>
        )}
        {partial && (
          <p className="tv-wizard-hit-source">{t("wizard.partialNote")}</p>
        )}
        {result.model_mismatch && result.found_model && (
          <p className="tv-wizard-hit-source" role="status">
            {t("wizard.modelMismatch").replace(
              "{model}",
              result.found_model,
            )}
          </p>
        )}
        {anyAi && (
          <p className="tv-wizard-hit-source">{t("wizard.aiCheckNote")}</p>
        )}
        <dl className="tv-wizard-hit-rows">
          {ROW_FIELDS.filter(({ key }) => fields[key]).map(
            ({ key, labelKey }) => (
              <div className="tv-wizard-hit-row" key={key}>
                <dt>{t(labelKey)}</dt>
                <dd>{String(fields[key].value)}</dd>
              </div>
            ),
          )}
        </dl>
        {fields.description && (
          <p className="tv-wizard-hit-desc">
            <strong>{t("wizard.fDescription")}:</strong>{" "}
            {String(fields.description.value)}
          </p>
        )}
        {photoOffer}
        <div className="tv-wizard-hit-actions">
          <Button type="button" onClick={useThis}>
            {t("wizard.useThis")}
          </Button>
          <Button type="button" variant="secondary" onClick={notIt}>
            {t("wizard.notIt")}
          </Button>
        </div>
      </div>
    );

  return (
    <div className="tv-wizard-lookup">
      <p className="tv-wizard-lookup-intro">{t("wizard.lookupIntro")}</p>
      <Panel title={t("wizard.lookupTitle")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void runLookup(brand, model, upc, link);
          }}
        >
          <div style={formGridStyle}>
            <FormField label={t("wizard.brandManufacturer")} htmlFor="wz-lookup-brand">
              <FieldSuggest
                field="brand"
                id="wz-lookup-brand"
                value={brand}
                onChange={editBrand}
              />
            </FormField>
            <FormField label={t("wizard.modelHash")} htmlFor="wz-lookup-model">
              <TextInput
                id="wz-lookup-model"
                value={model}
                onChange={(e) => editModel(e.target.value)}
              />
            </FormField>
            <FormField label={t("wizard.lookupUpc")} htmlFor="wz-lookup-upc">
              <TextInput
                id="wz-lookup-upc"
                value={upc}
                onChange={(e) => editUpc(e.target.value)}
                placeholder={t("wizard.lookupUpcPlaceholder")}
                inputMode="numeric"
              />
            </FormField>
          </div>
          <FormField label={t("wizard.linkLabel")} htmlFor="wz-lookup-link">
            <TextInput
              id="wz-lookup-link"
              value={link}
              onChange={(e) => editLink(e.target.value)}
              placeholder={t("wizard.linkPlaceholder")}
              inputMode="url"
            />
          </FormField>
          <div className="tv-wizard-lookup-actions">
            <Button type="submit" loading={phase === "busy"} disabled={!canRun}>
              {t("wizard.lookItUp")}
            </Button>
            {canScan && !scanning && (
              <Button type="button" variant="secondary" onClick={startScan}>
                {t("wizard.scanBarcode")}
              </Button>
            )}
            <Button type="button" variant="secondary" onClick={onDone}>
              {t("wizard.skipLookup")}
            </Button>
          </div>
          {phase === "busy" && <AiWorking label={t("wizard.lookingUp")} />}
          {scanning && (
            <div>
              <video
                ref={videoRef}
                className="tv-wizard-lookup-video"
                muted
                playsInline
              />
              <div className="tv-wizard-lookup-actions">
                <Button type="button" variant="secondary" onClick={stopScan}>
                  {t("wizard.stopScan")}
                </Button>
              </div>
            </div>
          )}
        </form>

        {aiOn && (
          <div className="tv-wizard-photoid">
            <p className="tv-wizard-lookup-note">{t("wizard.photoIdIntro")}</p>
            <div className="tv-wizard-lookup-actions">
              <Button
                type="button"
                variant="secondary"
                loading={photoPhase === "busy"}
                onClick={() => photoInputRef.current?.click()}
              >
                {t("wizard.photoIdButton")}
              </Button>
            </div>
            <input
              ref={photoInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                void onPhotoPicked(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            {photoPhase === "busy" && (
              <AiWorking label={t("wizard.photoIdBusy")} />
            )}
            {photoPhase === "unknown" && (
              <p className="tv-wizard-lookup-note" role="status">
                {t("wizard.photoIdUnknown")}
              </p>
            )}
            {photoPhase === "failed" && (
              <p className="tv-wizard-lookup-note" role="status">
                {t("wizard.photoIdFailed")}
              </p>
            )}
            {photoIdCard}
          </div>
        )}

        {phase === "miss" && (
          <>
            <p className="tv-wizard-lookup-note" role="status">
              {t("wizard.lookupMiss")}
            </p>
            {webOff && (
              <p className="tv-wizard-lookup-note" role="status">
                {t("wizard.webOffNote")}
              </p>
            )}
          </>
        )}
        {phase === "failed" && (
          <p className="tv-wizard-lookup-note" role="status">
            {t("wizard.lookupFailed")}
          </p>
        )}
        {phase === "linkfail" && (
          <p className="tv-wizard-lookup-note" role="status">
            {t("wizard.linkFailed")}
          </p>
        )}

        {phase === "hit" && resultCard(false)}
        {phase === "partial" && resultCard(true)}
      </Panel>
    </div>
  );
}
