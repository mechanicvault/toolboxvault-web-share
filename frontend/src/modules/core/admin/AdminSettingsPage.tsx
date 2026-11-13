import { useCallback, useEffect, useState, type CSSProperties } from "react";

import {
  Alert,
  Button,
  DataTable,
  FormField,
  Panel,
  Spinner,
  TextArea,
  TextInput,
  Toggle,
  useToast,
  type Column,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { RequireAuth } from "../auth/RequireAuth";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Settings (Phase A2): the system switches an operator may
 * flip without a deploy. Blocks:
 *  - Entitlements enforcement — THE launch switch. It stays OFF
 *    until launch by the owner's decision; while off, plan limits
 *    are computed for display but never enforced.
 *  - AI provider config — provider, model, and the NAME of the
 *    server-side key reference (never the key itself: keys live in
 *    server secrets; this panel stores only which one to use),
 *    plus the per-action credit prices (wave 4). Every AI feature
 *    (Quick Add lookup + identification, report summaries, manual
 *    lookups) reads this config through the one AI seam; until
 *    it's complete those surfaces stay hidden.
 *  - Product lookup — the UPC database + manual web search
 *    layers' provider names and key references (wave 4); blank
 *    legs are dark and skipped silently.
 *  - Stripe payments — the price IDs (plans, Business brackets,
 *    AI credit packs). The KEYS are server secrets, not settings:
 *    this panel shows whether they're configured and takes the
 *    pricing live the moment both exist (Stripe wiring, 2026-10-19).
 *  - Landing page — the public page's display prices, the
 *    self-serve trial switch + copy, and the app-store URLs
 *    (landing build, 2026-10-20). Display config only: the
 *    chargeable prices stay the Stripe IDs above; the trial
 *    block and store block render on the page ONLY while these
 *    settings say they exist.
 *  - System stats — cheap live aggregates.
 */

interface BackupRunView {
  started_at: string;
  finished_at: string | null;
  bundle_name: string | null;
  size_bytes: number | null;
  encrypted: boolean;
  uploaded: boolean;
  verified: boolean;
  status: string;
}

interface JobRunView {
  job: string;
  interval_minutes: number;
  last_status: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  summary: string | null;
  error: string | null;
}

interface StripePack {
  id: string;
  label: string;
  credits: number;
  stripe_price_id: string;
}

interface SpamTier {
  new_threads_per_hour: number;
  new_threads_per_day: number;
  messages_per_hour: number;
  messages_per_day: number;
}

interface SpamConfig {
  blast_threshold: number;
  blast_window_minutes: number;
  blast_similarity: number;
  blocked_domains: string[];
  lure_patterns: string[];
  tiers: Record<string, SpamTier>;
}

interface SettingsView {
  enforcement_enabled: boolean;
  require_email_verification: boolean;
  audit_retention_days: number;
  spam: SpamConfig;
  parts_pool_enabled: boolean;
  marketplace_enabled: boolean;
  forum_enabled: boolean;
  claim_readiness_nudges_enabled: boolean;
  claim_readiness_interval_days: number;
  /** NEW-badge registry (release machinery, 2026-11-08): nav
   *  item key -> release date ("YYYY-MM-DD"). */
  nav_new_badges: Record<string, string>;
  truck_payments: {
    connect_enabled: boolean;
    configured: boolean;
    truck_fee_percent: number;
  };
  ai: {
    provider: string;
    model: string;
    api_key_ref: string;
    /** Per-action credit prices (wave 4): {action: credits}. */
    prices: Record<string, number>;
    /** Per-action model overrides (2026-10-25): {action: model};
     * blank/absent rides the site model. */
    action_models: Record<string, string>;
  };
  /** Product lookup layers (wave 4). Web search is not here:
   * it rides the AI provider's own search (one vendor). */
  lookup: {
    upc_provider: string;
    upc_api_key_ref: string;
  };
  stripe: {
    configured: boolean;
    price_pro_monthly: string;
    price_pro_yearly: string;
    price_business_monthly: string;
    price_business_yearly: string;
    price_business_brackets: Record<string, string>;
    brackets: { bracket_key: string; up_to_employees: number | null }[];
    ai_credit_packs: StripePack[];
  };
  landing: {
    pro_monthly_price: string;
    pro_yearly_price: string;
    business_monthly_price: string;
    business_yearly_price: string;
    self_serve_trial_enabled: boolean;
    trial_copy: string;
    app_store_url: string;
    play_store_url: string;
  };
  /** Teaser mode (2026-10-26): the code itself is NEVER in this
   *  shape — only whether a custom one is in effect, plus the
   *  current trailer's set/name (keys and URLs stay server-side). */
  teaser: {
    enabled: boolean;
    gate_code_custom: boolean;
    video_set: boolean;
    video_name: string;
  };
  stats: {
    users: number;
    tools: number;
    feature_modules: number;
    tables: Record<string, number>;
  };
  backups: BackupRunView[];
  /** Disaster Vault off-site leg (2026-10-24): the platform
   * Drive connection the nightly uploads ride on. */
  backup_drive?: {
    connected: boolean;
    email: string;
    folder_id: string;
    connected_at: string | null;
    oauth_configured: boolean;
  };
  jobs: JobRunView[];
}

/** Shared style objects for the Backups panel (defined once and
 * passed by reference — the inline-style ratchet counts only
 * `style={{` literals, and reuse keeps the panel consistent). */
const mutedTextStyle: CSSProperties = { color: "var(--text-muted)" };
const mutedNoteStyle: CSSProperties = { color: "var(--text-muted)", margin: 0 };
const panelNoteStyle: CSSProperties = {
  color: "var(--text-muted)",
  margin: "var(--space-3) 0 0",
  fontSize: "var(--font-size-sm)",
};
const listStackStyle: CSSProperties = { display: "grid", gap: "var(--space-1)" };
const panelStackStyle: CSSProperties = { display: "grid", gap: "var(--space-3)" };

/** Capture a poster frame from a local MP4 in the browser: load
 *  the file into an off-screen <video>, seek just past the
 *  start, draw to a canvas, export WebP. Best-effort by design —
 *  any failure resolves null and the teaser upload proceeds
 *  without a poster (the page then shows the video's own first
 *  frame). A timeout keeps a stubborn file from hanging the
 *  panel. */
function captureVideoPoster(file: File): Promise<Blob | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    const settle = (blob: Blob | null) => {
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
      resolve(blob);
    };
    const timer = window.setTimeout(() => settle(null), 5000);
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.onloadedmetadata = () => {
      video.currentTime = Math.min(0.6, (video.duration || 1) / 2);
    };
    video.onseeked = () => {
      window.clearTimeout(timer);
      try {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx || canvas.width === 0) {
          settle(null);
          return;
        }
        ctx.drawImage(video, 0, 0);
        canvas.toBlob((blob) => settle(blob), "image/webp", 0.82);
      } catch {
        settle(null);
      }
    };
    video.onerror = () => {
      window.clearTimeout(timer);
      settle(null);
    };
    video.src = url;
  });
}
const rowSpreadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  flexWrap: "wrap",
};
const blockHeadingStyle: CSSProperties = { fontWeight: 700, margin: 0 };
const blockStackStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
  marginBottom: "var(--space-3)",
};

function formatBytes(size: number | null): string {
  if (size === null) return "—";
  if (size < 1_000_000) return `${(size / 1_000).toFixed(1)} KB`;
  return `${(size / 1_000_000).toFixed(1)} MB`;
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function SettingsSection() {
  const { toast } = useToast();
  const [view, setView] = useState<SettingsView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingSwitch, setSavingSwitch] = useState(false);
  const [savingVerification, setSavingVerification] = useState(false);
  const [savingTeaser, setSavingTeaser] = useState(false);
  const [gateCodeDraft, setGateCodeDraft] = useState("");
  const [teaserFile, setTeaserFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKeyRef, setApiKeyRef] = useState("");
  const [savingAi, setSavingAi] = useState(false);
  // Wave 4: per-action AI credit prices + the lookup layers.
  const [aiPrices, setAiPrices] = useState<Record<string, string>>({});
  const [aiActionModels, setAiActionModels] = useState<Record<string, string>>({});
  const [upcProvider, setUpcProvider] = useState("");
  const [upcApiKeyRef, setUpcApiKeyRef] = useState("");
  const [savingLookup, setSavingLookup] = useState(false);
  const [priceProMonthly, setPriceProMonthly] = useState("");
  const [priceProYearly, setPriceProYearly] = useState("");
  const [priceBizMonthly, setPriceBizMonthly] = useState("");
  const [priceBizYearly, setPriceBizYearly] = useState("");
  const [bracketPrices, setBracketPrices] = useState<Record<string, string>>({});
  const [packs, setPacks] = useState<StripePack[]>([]);
  const [savingStripe, setSavingStripe] = useState(false);
  const [landingProMonthly, setLandingProMonthly] = useState("");
  const [landingProYearly, setLandingProYearly] = useState("");
  const [landingBizMonthly, setLandingBizMonthly] = useState("");
  const [landingBizYearly, setLandingBizYearly] = useState("");
  const [landingTrialEnabled, setLandingTrialEnabled] = useState(false);
  const [landingTrialCopy, setLandingTrialCopy] = useState("");
  const [landingAppStoreUrl, setLandingAppStoreUrl] = useState("");
  const [landingPlayStoreUrl, setLandingPlayStoreUrl] = useState("");
  const [savingLanding, setSavingLanding] = useState(false);
  const [retentionDays, setRetentionDays] = useState("180");
  const [savingRetention, setSavingRetention] = useState(false);
  const [spam, setSpam] = useState<SpamConfig | null>(null);
  const [blockedText, setBlockedText] = useState("");
  const [lureText, setLureText] = useState("");
  const [savingSpam, setSavingSpam] = useState(false);
  const [savingPool, setSavingPool] = useState(false);
  const [truckFee, setTruckFee] = useState("0");
  const [readinessInterval, setReadinessInterval] = useState("7");
  const [savingReadiness, setSavingReadiness] = useState(false);
  // NEW-badge registry (release machinery, 2026-11-08): the map
  // edited as JSON text; parsed + shape-checked before saving,
  // and the API validates every date again server-side.
  const [badgesText, setBadgesText] = useState("{}");
  const [savingBadges, setSavingBadges] = useState(false);
  const [savingTruck, setSavingTruck] = useState(false);
  const [driveBusy, setDriveBusy] = useState(false);
  // The Drive connect round-trip lands back here with ?drive=
  // (connected | denied | failed) — read once on mount.
  const [driveResult] = useState<string | null>(() =>
    typeof window === "undefined"
      ? null
      : new URLSearchParams(window.location.search).get("drive"),
  );

  const load = useCallback(async () => {
    try {
      const data = await api<SettingsView>("/admin/settings");
      setView(data);
      setProvider(data.ai.provider);
      setModel(data.ai.model);
      setApiKeyRef(data.ai.api_key_ref);
      setAiPrices(
        Object.fromEntries(
          Object.entries(data.ai.prices ?? {}).map(([k, v]) => [k, String(v)]),
        ),
      );
      setAiActionModels(data.ai.action_models ?? {});
      setUpcProvider(data.lookup?.upc_provider ?? "");
      setUpcApiKeyRef(data.lookup?.upc_api_key_ref ?? "");
      setPriceProMonthly(data.stripe.price_pro_monthly);
      setPriceProYearly(data.stripe.price_pro_yearly);
      setPriceBizMonthly(data.stripe.price_business_monthly);
      setPriceBizYearly(data.stripe.price_business_yearly);
      setBracketPrices(data.stripe.price_business_brackets);
      setPacks(data.stripe.ai_credit_packs);
      setLandingProMonthly(data.landing.pro_monthly_price);
      setLandingProYearly(data.landing.pro_yearly_price);
      setLandingBizMonthly(data.landing.business_monthly_price);
      setLandingBizYearly(data.landing.business_yearly_price);
      setLandingTrialEnabled(data.landing.self_serve_trial_enabled);
      setLandingTrialCopy(data.landing.trial_copy);
      setLandingAppStoreUrl(data.landing.app_store_url);
      setLandingPlayStoreUrl(data.landing.play_store_url);
      setRetentionDays(String(data.audit_retention_days));
      setTruckFee(String(data.truck_payments.truck_fee_percent));
      setReadinessInterval(String(data.claim_readiness_interval_days ?? 7));
      setBadgesText(JSON.stringify(data.nav_new_badges ?? {}, null, 2));
      setSpam(data.spam);
      setBlockedText(data.spam.blocked_domains.join("\n"));
      setLureText(data.spam.lure_patterns.join("\n"));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load system settings.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function connectDrive() {
    setDriveBusy(true);
    try {
      const data = await api<{ authorize_url: string }>(
        "/admin/settings/backup-drive/connect",
        { method: "POST" },
      );
      window.location.href = data.authorize_url;
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't start the Drive connection.",
        { tone: "danger" },
      );
      setDriveBusy(false);
    }
  }

  async function disconnectDrive() {
    setDriveBusy(true);
    try {
      const data = await api<SettingsView>(
        "/admin/settings/backup-drive/disconnect",
        { method: "POST" },
      );
      setView(data);
      toast(
        "Backup Drive disconnected — nightly bundles stay on this server only.",
        { tone: "success", duration: 8000 },
      );
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't disconnect the backup Drive.",
        { tone: "danger" },
      );
    } finally {
      setDriveBusy(false);
    }
  }

  async function save(body: Record<string, unknown>, success: string) {
    try {
      const data = await api<SettingsView>("/admin/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setView(data);
      toast(success, { tone: "success", duration: 8000 });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save that setting.",
        { tone: "danger" },
      );
      await load(); // re-sync the controls with the server's truth
    }
  }

  async function flipEnforcement(enabled: boolean) {
    setSavingSwitch(true);
    try {
      await save(
        { enforcement_enabled: enabled },
        enabled
          ? "Enforcement is ON — plan item limits now apply."
          : "Enforcement is OFF — limits are display-only.",
      );
    } finally {
      setSavingSwitch(false);
    }
  }

  async function flipVerification(enabled: boolean) {
    setSavingVerification(true);
    try {
      await save(
        { require_email_verification: enabled },
        enabled
          ? "Email verification is REQUIRED — unverified accounts can't sign in."
          : "Email verification is NOT required — sign-in is open.",
      );
    } finally {
      setSavingVerification(false);
    }
  }

  async function flipTeaser(enabled: boolean) {
    setSavingTeaser(true);
    try {
      await save(
        { teaser_enabled: enabled },
        enabled
          ? "Teaser mode ON — the public front door is the teaser; signup is open, and the gate code unlocks the full site (no code = the Downloads level)."
          : "Teaser mode OFF — the landing page and open signup are live again.",
      );
    } finally {
      setSavingTeaser(false);
    }
  }

  /** Set/replace the teaser trailer (owner refinement,
   *  2026-10-26): presigned PUT of the MP4 straight to object
   *  storage, a poster frame captured from the file right here
   *  in the browser (best-effort — the upload never fails over a
   *  poster), then the complete call that verifies and points
   *  the settings at the new objects. The replaced video's
   *  objects are deleted server-side. */
  async function uploadTeaserVideo() {
    if (!teaserFile) return;
    if (teaserFile.size > 10 * 1024 * 1024) {
      toast("That MP4 is over the 10 MB series limit.", { tone: "danger" });
      return;
    }
    setSavingTeaser(true);
    try {
      const issued = await api<{ upload_url: string; key: string }>(
        "/admin/settings/teaser-video/upload-url",
        {
          method: "POST",
          body: JSON.stringify({
            kind: "video",
            filename: teaserFile.name,
            content_type: "video/mp4",
            size_bytes: teaserFile.size,
          }),
        },
      );
      const put = await fetch(issued.upload_url, {
        method: "PUT",
        body: teaserFile,
        headers: { "Content-Type": "video/mp4" },
      });
      if (!put.ok) throw new Error(`Storage refused the upload (${put.status}).`);
      let posterKey = "";
      const poster = await captureVideoPoster(teaserFile).catch(() => null);
      if (poster) {
        const posterIssued = await api<{ upload_url: string; key: string }>(
          "/admin/settings/teaser-video/upload-url",
          {
            method: "POST",
            body: JSON.stringify({
              kind: "poster",
              filename: "poster.webp",
              content_type: poster.type,
              size_bytes: poster.size,
            }),
          },
        );
        const posterPut = await fetch(posterIssued.upload_url, {
          method: "PUT",
          body: poster,
          headers: { "Content-Type": poster.type },
        });
        if (posterPut.ok) posterKey = posterIssued.key;
      }
      const data = await api<SettingsView>("/admin/settings/teaser-video/complete", {
        method: "POST",
        body: JSON.stringify({
          key: issued.key,
          poster_key: posterKey,
          name: teaserFile.name,
        }),
      });
      setView(data);
      setTeaserFile(null);
      toast("Teaser video updated — it's live on the teaser page now.", {
        tone: "success",
        duration: 8000,
      });
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Couldn't set the teaser video.",
        { tone: "danger" },
      );
      await load();
    } finally {
      setSavingTeaser(false);
    }
  }

  async function clearTeaserVideo() {
    setSavingTeaser(true);
    try {
      const data = await api<SettingsView>("/admin/settings/teaser-video", {
        method: "DELETE",
      });
      setView(data);
      toast("Teaser video cleared — the page renders with no video slot.", {
        tone: "success",
        duration: 8000,
      });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't clear the teaser video.", {
        tone: "danger",
      });
      await load();
    } finally {
      setSavingTeaser(false);
    }
  }

  async function saveGateCode() {
    const next = gateCodeDraft.trim();
    setSavingTeaser(true);
    try {
      await save(
        { teaser_gate_code: next },
        next
          ? "Gate code updated. It is never shown anywhere — keep it somewhere safe."
          : "Gate code cleared — the owner's default code is in effect again.",
      );
      setGateCodeDraft("");
    } finally {
      setSavingTeaser(false);
    }
  }

  async function saveAi() {
    setSavingAi(true);
    try {
      const body: Record<string, unknown> = {
        ai_provider: provider,
        ai_model: model,
        ai_api_key_ref: apiKeyRef,
      };
      for (const action of ["lookup", "identify", "manual_lookup", "report_summary", "drawer_lookup"]) {
        const raw = aiPrices[action];
        if (raw !== undefined && raw !== "") {
          body[`ai_price_${action}`] = Math.max(0, Math.floor(Number(raw) || 0));
        }
      }
      // Per-action model overrides always ride along (a blank
      // string clears the override back to the site model).
      body["ai_model_drawer_lookup"] = (aiActionModels["drawer_lookup"] ?? "").trim();
      await save(body, "AI provider config saved.");
    } finally {
      setSavingAi(false);
    }
  }

  async function saveLookup() {
    setSavingLookup(true);
    try {
      await save(
        {
          lookup_upc_provider: upcProvider,
          lookup_upc_api_key_ref: upcApiKeyRef,
        },
        "Product lookup config saved.",
      );
    } finally {
      setSavingLookup(false);
    }
  }

  async function saveStripe() {
    setSavingStripe(true);
    try {
      await save(
        {
          stripe_price_pro_monthly: priceProMonthly.trim(),
          stripe_price_pro_yearly: priceProYearly.trim(),
          stripe_price_business_monthly: priceBizMonthly.trim(),
          stripe_price_business_yearly: priceBizYearly.trim(),
          stripe_price_business_brackets: bracketPrices,
          stripe_ai_credit_packs: packs
            .filter((pack) => pack.id.trim() || pack.label.trim())
            .map((pack) => ({
              id: pack.id.trim(),
              label: pack.label.trim(),
              credits: Number(pack.credits) || 0,
              stripe_price_id: pack.stripe_price_id.trim(),
            })),
        },
        "Stripe pricing saved — changes are live immediately.",
      );
    } finally {
      setSavingStripe(false);
    }
  }

  async function saveLanding() {
    setSavingLanding(true);
    try {
      await save(
        {
          landing_pro_monthly_price: landingProMonthly.trim(),
          landing_pro_yearly_price: landingProYearly.trim(),
          landing_business_monthly_price: landingBizMonthly.trim(),
          landing_business_yearly_price: landingBizYearly.trim(),
          landing_self_serve_trial_enabled: landingTrialEnabled,
          landing_trial_copy: landingTrialCopy,
          landing_app_store_url: landingAppStoreUrl.trim(),
          landing_play_store_url: landingPlayStoreUrl.trim(),
        },
        "Landing page saved — the public page shows the new values now.",
      );
    } finally {
      setSavingLanding(false);
    }
  }

  async function flipPool(enabled: boolean) {
    setSavingPool(true);
    try {
      await save(
        { community_parts_pool_enabled: enabled },
        enabled
          ? "Community Parts pool is ON — public listings are visible."
          : "Community Parts pool is OFF — listings are hidden everywhere (shelves are untouched).",
      );
    } finally {
      setSavingPool(false);
    }
  }

  async function flipMarketplace(enabled: boolean) {
    setSavingPool(true);
    try {
      await save(
        { community_marketplace_enabled: enabled },
        enabled
          ? "Tools for sale is ON — the board is visible."
          : "Tools for sale is OFF — the board is hidden everywhere (members' listings and ratings are untouched).",
      );
    } finally {
      setSavingPool(false);
    }
  }

  async function flipTruckConnect(enabled: boolean) {
    setSavingTruck(true);
    try {
      await save(
        { payments_connect_enabled: enabled },
        enabled
          ? "Truck online payments switch is ON — it goes live once the platform Stripe keys exist."
          : "Truck online payments switch is OFF — dealers' Pay online buttons stay hidden.",
      );
    } finally {
      setSavingTruck(false);
    }
  }

  async function saveTruckFee() {
    const value = Number(truckFee);
    if (Number.isNaN(value) || value < 0 || value > 100) {
      toast("The truck platform fee must be a percent between 0 and 100.", {
        tone: "danger",
      });
      return;
    }
    setSavingTruck(true);
    try {
      await save(
        { payments_truck_fee_percent: value },
        "Truck platform fee saved — new agreement acceptances disclose it.",
      );
    } finally {
      setSavingTruck(false);
    }
  }

  async function flipForum(enabled: boolean) {
    setSavingPool(true);
    try {
      await save(
        { community_forum_enabled: enabled },
        enabled
          ? "Community Forum is ON — categories and threads are visible."
          : "Community Forum is OFF — the forum is hidden everywhere (threads and posts are untouched).",
      );
    } finally {
      setSavingPool(false);
    }
  }

  async function flipReadiness(enabled: boolean) {
    setSavingReadiness(true);
    try {
      await save(
        { claim_readiness_nudges_enabled: enabled },
        enabled
          ? "Claim-readiness nudges are ON — owners with record gaps get at most one inbox nudge per period."
          : "Claim-readiness nudges are OFF — no owner is nudged (silence preferences and records are untouched).",
      );
    } finally {
      setSavingReadiness(false);
    }
  }

  async function saveBadges() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(badgesText);
    } catch {
      toast("The NEW-badge registry isn't valid JSON.", { tone: "danger" });
      return;
    }
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed) ||
      !Object.entries(parsed).every(
        ([k, v]) => k.length > 0 && typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v),
      )
    ) {
      toast(
        'The registry must map menu keys to release dates, like {"reports": "2026-12-01"}.',
        { tone: "danger" },
      );
      return;
    }
    setSavingBadges(true);
    try {
      await save(
        { nav_new_badges: parsed },
        "NEW-badge registry saved. Badges show for each item's first week.",
      );
    } finally {
      setSavingBadges(false);
    }
  }

  async function saveReadinessInterval() {
    const value = Number(readinessInterval);
    if (!Number.isInteger(value) || value < 1 || value > 90) {
      toast("The nudge interval must be a whole number of days between 1 and 90.", {
        tone: "danger",
      });
      return;
    }
    setSavingReadiness(true);
    try {
      await save(
        { claim_readiness_interval_days: value },
        "Claim-readiness nudge interval saved.",
      );
    } finally {
      setSavingReadiness(false);
    }
  }

  async function saveSpam() {
    if (!spam) return;
    setSavingSpam(true);
    try {
      const data = await api<SettingsView>("/admin/settings", {
        method: "PUT",
        body: JSON.stringify({
          spam: {
            ...spam,
            blocked_domains: blockedText
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
            lure_patterns: lureText
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          },
        }),
      });
      setView(data);
      setSpam(data.spam);
      setBlockedText(data.spam.blocked_domains.join("\n"));
      setLureText(data.spam.lure_patterns.join("\n"));
      toast("Spam firewall settings saved — they apply to the next message sent.", {
        tone: "success",
        duration: 8000,
      });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save the spam settings.",
        { tone: "danger" },
      );
      await load();
    } finally {
      setSavingSpam(false);
    }
  }

  async function saveRetention() {
    const days = Number(retentionDays);
    if (!Number.isInteger(days) || days < 7 || days > 3650) {
      toast("Retention must be a whole number of days between 7 and 3650.", {
        tone: "danger",
      });
      return;
    }
    setSavingRetention(true);
    try {
      await save(
        { audit_retention_days: days },
        `File retention set to ${days} days — deleted files stay restorable for that long.`,
      );
    } finally {
      setSavingRetention(false);
    }
  }

  function updatePack(index: number, patch: Partial<StripePack>) {
    setPacks((current) =>
      current.map((pack, i) => (i === index ? { ...pack, ...patch } : pack)),
    );
  }

  return (
    <AdminShell>
      <div style={{ display: "grid", gap: "var(--spacing)" }}>
        {loadError && <Alert tone="danger">{loadError}</Alert>}
        {!view && !loadError && (
          <p style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", margin: 0 }}>
            <Spinner size="sm" /> Loading settings…
          </p>
        )}
        {view && (
          <>
            <Panel title="Entitlements enforcement">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <Toggle
                  checked={view.enforcement_enabled}
                  disabled={savingSwitch}
                  label={
                    view.enforcement_enabled
                      ? "Enforcement ON — plan item limits apply"
                      : "Enforcement OFF — limits are display-only"
                  }
                  onChange={(enabled) => void flipEnforcement(enabled)}
                />
                <Alert tone="warning">
                  Launch switch — leave OFF until launch. Turning this on starts
                  enforcing the free plan's item limit (accounts over the limit
                  keep their newest items active; the rest go inactive) for
                  every account, immediately.
                </Alert>
              </div>
            </Panel>

            <Panel title="Email verification">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <Toggle
                  checked={view.require_email_verification}
                  disabled={savingVerification}
                  label={
                    view.require_email_verification
                      ? "Verification REQUIRED — unverified accounts can't sign in"
                      : "Verification not required — sign-in is open"
                  }
                  onChange={(enabled) => void flipVerification(enabled)}
                />
                <Alert tone="warning">
                  Launch switch — leave OFF until launch. Turning this on blocks
                  password sign-in for every account whose email address isn't
                  verified yet (they get a resend-verification option on the
                  login page). Social sign-ins are exempt — their provider
                  already verified the address.
                </Alert>
              </div>
            </Panel>

            <Panel title="Teaser mode — pre-launch front door">
              <div style={panelStackStyle}>
                <Toggle
                  checked={view.teaser.enabled}
                  disabled={savingTeaser}
                  label={
                    view.teaser.enabled
                      ? "Teaser ON — public sees the teaser; signup open (gate code = full site, no code = Downloads level)"
                      : "Teaser OFF — the landing page and open signup are live"
                  }
                  onChange={(enabled) => void flipTeaser(enabled)}
                />
                <Alert tone="warning">
                  Launch switch — while ON, signed-out visitors can reach only
                  the teaser page, the login page, and signup. Signup is OPEN:
                  with the gate code a new account gets the full site; without
                  one it lands on the Downloads level (Downloads + 3D Print
                  Files) until you open more to that level or launch day
                  arrives. Signed-in members see the full site exactly as
                  usual. Turn it OFF on launch day: the merged landing page
                  and full open signup come back untouched, and nothing about
                  the teaser is deleted.
                </Alert>
                <FormField
                  label="Full-access signup code"
                  htmlFor="teaser-gate-code"
                  hint={
                    view.teaser.gate_code_custom
                      ? "A custom code is in effect. The code itself is never displayed — type a new one to replace it, or save it blank to return to the default."
                      : "The owner's default code is in effect. Type a new code (at least 4 characters) to replace it. The code is never displayed anywhere."
                  }
                >
                  <TextInput
                    id="teaser-gate-code"
                    type="password"
                    autoComplete="off"
                    value={gateCodeDraft}
                    onChange={(e) => setGateCodeDraft(e.target.value)}
                    placeholder="New gate code"
                  />
                </FormField>
                <div>
                  <Button
                    type="button"
                    disabled={savingTeaser}
                    onClick={() => void saveGateCode()}
                  >
                    Save gate code
                  </Button>
                </div>
                <FormField
                  label="Teaser video (plays on the teaser page)"
                  htmlFor="teaser-video-file"
                  hint={
                    view.teaser.video_set
                      ? `Current video: ${view.teaser.video_name || "set"} — uploading a new MP4 replaces it (the old file is deleted). Clear removes the slot from the page entirely.`
                      : "No video set — the teaser page renders complete with no video slot. Upload the current approved teaser trailer (MP4, 10 MB max); a poster frame is captured automatically."
                  }
                >
                  <input
                    id="teaser-video-file"
                    className="tv-admin-file-input"
                    type="file"
                    accept="video/mp4"
                    disabled={savingTeaser}
                    onChange={(e) => setTeaserFile(e.target.files?.[0] ?? null)}
                  />
                </FormField>
                <div>
                  <Button
                    type="button"
                    disabled={savingTeaser || !teaserFile}
                    onClick={() => void uploadTeaserVideo()}
                  >
                    {view.teaser.video_set ? "Replace video" : "Set video"}
                  </Button>
                </div>
                {view.teaser.video_set && (
                  <div>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={savingTeaser}
                      onClick={() => void clearTeaserVideo()}
                    >
                      Clear video
                    </Button>
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="AI provider">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  <FormField label="Provider">
                    <TextInput
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                      placeholder="e.g. anthropic, google"
                    />
                  </FormField>
                  <FormField label="Model">
                    <TextInput
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="e.g. claude-sonnet"
                    />
                  </FormField>
                  <FormField label="API key reference">
                    <TextInput
                      value={apiKeyRef}
                      onChange={(e) => setApiKeyRef(e.target.value)}
                      placeholder="e.g. ANTHROPIC_API_KEY"
                    />
                  </FormField>
                </div>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  The key reference is the NAME of the server secret the AI service
                  should use — never paste the key itself here. Supported providers:
                  openai, anthropic. Until a provider, a model, AND the named secret
                  are all set, every AI surface stays hidden and its endpoint
                  answers "not configured" — nothing degrades, it simply isn't
                  offered. Swapping providers is this form, not a deploy.
                </p>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  Site-wide AI usage — calls and credits by action for any
                  period — is the AI Usage report in Reports (the Admin
                  reports): this panel sets the prices, that report shows
                  what they added up to. (09b-F11)
                </p>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  {(
                    [
                      ["lookup", "Quick Add lookup (credits)"],
                      ["identify", "Item identification (credits)"],
                      ["manual_lookup", "Manual lookup (credits)"],
                      ["report_summary", "Report summary (credits)"],
                      ["drawer_lookup", "Toolbox drawer lookup (credits)"],
                    ] as const
                  ).map(([action, label]) => (
                    <FormField key={action} label={label}>
                      <TextInput
                        type="number"
                        min={0}
                        value={aiPrices[action] ?? "0"}
                        onChange={(e) =>
                          setAiPrices((prev) => ({
                            ...prev,
                            [action]: e.target.value,
                          }))
                        }
                      />
                    </FormField>
                  ))}
                </div>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  Per-action credit prices, charged through the user's AI
                  wallet only when the AI call actually runs. 0 = free.
                  The drawer lookup below answers from model knowledge of
                  a toolbox's factory spec, where small models decline or
                  misremember — it can ride a stronger model than the
                  rest of the site; blank = the site model above.
                </p>
                <FormField label="Drawer lookup model override">
                  <TextInput
                    value={aiActionModels["drawer_lookup"] ?? ""}
                    onChange={(e) =>
                      setAiActionModels((prev) => ({
                        ...prev,
                        drawer_lookup: e.target.value,
                      }))
                    }
                    placeholder={model || "site model"}
                  />
                </FormField>
                <div>
                  <Button loading={savingAi} onClick={() => void saveAi()}>
                    Save AI config
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="Product lookup">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  <FormField label="UPC provider">
                    <TextInput
                      value={upcProvider}
                      onChange={(e) => setUpcProvider(e.target.value)}
                      placeholder="upcitemdb"
                    />
                  </FormField>
                  <FormField label="UPC API key reference">
                    <TextInput
                      value={upcApiKeyRef}
                      onChange={(e) => setUpcApiKeyRef(e.target.value)}
                      placeholder="e.g. UPCITEMDB_KEY"
                    />
                  </FormField>
                </div>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  The UPC database is the one optional outside layer —
                  same reference-name pattern as the AI key: name the
                  server secret, never paste the key. Left blank it is
                  dark and the lookup chain skips it silently. Web
                  search for Quick Add and Locate User Manual needs no
                  settings here: it runs through the AI provider
                  configured in the AI panel above (one vendor for the
                  AI and the search alike), and the community catalog
                  and manufacturer manual sources always work.
                </p>
                <div>
                  <Button loading={savingLookup} onClick={() => void saveLookup()}>
                    Save lookup config
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="Stripe payments">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                {view.stripe.configured ? (
                  <Alert tone="success">
                    Server keys are configured — plans and packs become
                    purchasable as soon as their price IDs below are set.
                  </Alert>
                ) : (
                  <Alert tone="warning">
                    Payments are DARK: no Stripe keys on the server yet
                    (STRIPE_SECRET_KEY &amp; friends arrive via GitHub
                    secrets at deploy). Price IDs can be staged here
                    now; nothing is chargeable until the keys exist.
                  </Alert>
                )}
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  Price IDs come from the Stripe Dashboard (Products →
                  each price's ID, looks like <code>price_…</code>).
                  Business is charged as the base price PLUS the
                  bracket fee, so it needs both. An empty ID means
                  "not on sale yet" — users see "Pricing opens at
                  launch" for it. Annual prices are set at 10× the
                  monthly price.
                </p>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  <FormField label="Pro (monthly) price ID">
                    <TextInput
                      value={priceProMonthly}
                      onChange={(e) => setPriceProMonthly(e.target.value)}
                      placeholder="price_…"
                    />
                  </FormField>
                  <FormField label="Pro (annual) price ID">
                    <TextInput
                      value={priceProYearly}
                      onChange={(e) => setPriceProYearly(e.target.value)}
                      placeholder="price_…"
                    />
                  </FormField>
                  <FormField label="Business (monthly) base price ID">
                    <TextInput
                      value={priceBizMonthly}
                      onChange={(e) => setPriceBizMonthly(e.target.value)}
                      placeholder="price_…"
                    />
                  </FormField>
                  <FormField label="Business (annual) base price ID">
                    <TextInput
                      value={priceBizYearly}
                      onChange={(e) => setPriceBizYearly(e.target.value)}
                      placeholder="price_…"
                    />
                  </FormField>
                </div>
                <p style={{ fontWeight: 700, margin: 0 }}>
                  Business bracket fees (one price ID per bracket)
                </p>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  {view.stripe.brackets.map((bracket) => (
                    <FormField
                      key={bracket.bracket_key}
                      label={
                        bracket.up_to_employees === null
                          ? "Unlimited employees"
                          : `Up to ${bracket.up_to_employees} employees`
                      }
                    >
                      <TextInput
                        value={bracketPrices[bracket.bracket_key] ?? ""}
                        onChange={(e) =>
                          setBracketPrices((current) => ({
                            ...current,
                            [bracket.bracket_key]: e.target.value,
                          }))
                        }
                        placeholder="price_…"
                      />
                    </FormField>
                  ))}
                </div>
                <p style={{ fontWeight: 700, margin: 0 }}>AI credit packs</p>
                {packs.length === 0 && (
                  <p style={{ color: "var(--text-muted)", margin: 0 }}>
                    No packs defined — the "Buy credits" block stays
                    hidden in user Settings until one exists here.
                  </p>
                )}
                {packs.map((pack, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      gap: "var(--space-3)",
                      flexWrap: "wrap",
                      alignItems: "end",
                    }}
                  >
                    <FormField label="Pack id">
                      <TextInput
                        value={pack.id}
                        onChange={(e) => updatePack(i, { id: e.target.value })}
                        placeholder="e.g. pack_100"
                      />
                    </FormField>
                    <FormField label="Label">
                      <TextInput
                        value={pack.label}
                        onChange={(e) => updatePack(i, { label: e.target.value })}
                        placeholder="e.g. 100 credits"
                      />
                    </FormField>
                    <FormField label="Credits">
                      <TextInput
                        value={String(pack.credits)}
                        inputMode="numeric"
                        onChange={(e) =>
                          updatePack(i, {
                            credits: Number(e.target.value.replace(/\D/g, "")) || 0,
                          })
                        }
                      />
                    </FormField>
                    <FormField label="Stripe price ID">
                      <TextInput
                        value={pack.stripe_price_id}
                        onChange={(e) =>
                          updatePack(i, { stripe_price_id: e.target.value })
                        }
                        placeholder="price_…"
                      />
                    </FormField>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        setPacks((current) =>
                          current.filter((_, j) => j !== i),
                        )
                      }
                    >
                      Remove
                    </Button>
                  </div>
                ))}
                <div>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      setPacks((current) => [
                        ...current,
                        { id: "", label: "", credits: 0, stripe_price_id: "" },
                      ])
                    }
                  >
                    Add a credit pack
                  </Button>
                </div>
                <div>
                  <Button loading={savingStripe} onClick={() => void saveStripe()}>
                    Save Stripe pricing
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="Landing page">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  What the signed-out front page may say. Prices here
                  are DISPLAY copy, typed exactly as they should read
                  (the chargeable prices are the Stripe price IDs
                  above). An empty price hides that figure on the
                  page; Business shows its "base + crew-size bracket"
                  wording until figures are set here. The free tier's
                  item limit on the page comes from the plan catalog
                  itself — it can't drift from the real limit.
                </p>
                <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
                  <FormField label="Pro (monthly) display price">
                    <TextInput
                      value={landingProMonthly}
                      onChange={(e) => setLandingProMonthly(e.target.value)}
                      placeholder="e.g. 7.99"
                    />
                  </FormField>
                  <FormField label="Pro (annual) display price">
                    <TextInput
                      value={landingProYearly}
                      onChange={(e) => setLandingProYearly(e.target.value)}
                      placeholder="e.g. 79.99"
                    />
                  </FormField>
                  <FormField label="Business (monthly) base display price">
                    <TextInput
                      value={landingBizMonthly}
                      onChange={(e) => setLandingBizMonthly(e.target.value)}
                      placeholder="Empty = no figure shown"
                    />
                  </FormField>
                  <FormField label="Business (annual) base display price">
                    <TextInput
                      value={landingBizYearly}
                      onChange={(e) => setLandingBizYearly(e.target.value)}
                      placeholder="Empty = no figure shown"
                    />
                  </FormField>
                </div>
                <Toggle
                  checked={landingTrialEnabled}
                  label={
                    landingTrialEnabled
                      ? "Self-serve trial OFFERED — the landing page shows the trial block"
                      : "No self-serve trial — the landing page hides the trial block"
                  }
                  onChange={setLandingTrialEnabled}
                />
                <Alert tone="warning">
                  Only turn the trial offer on when a visitor can
                  actually start one from the signup page. Trials are
                  admin-started today — advertising one that doesn't
                  exist yet would be a promise the site can't keep.
                </Alert>
                <FormField label="Trial copy (shown when the offer is on)">
                  <TextArea
                    value={landingTrialCopy}
                    onChange={(e) => setLandingTrialCopy(e.target.value)}
                    placeholder="e.g. Try Pro free for 14 days — no card required."
                    rows={2}
                  />
                </FormField>
                {/* Equal grid halves (supervisory polish
                    2026-10-23): unsized flex children shrank these
                    URL fields to ~150px and truncated the very links
                    the operator pastes here to verify. */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(min(260px, 100%), 1fr))",
                    gap: "var(--space-3)",
                  }}
                >
                  <FormField label="App Store URL">
                    <TextInput
                      value={landingAppStoreUrl}
                      onChange={(e) => setLandingAppStoreUrl(e.target.value)}
                      placeholder="Empty = badge hidden"
                    />
                  </FormField>
                  <FormField label="Google Play URL">
                    <TextInput
                      value={landingPlayStoreUrl}
                      onChange={(e) => setLandingPlayStoreUrl(e.target.value)}
                      placeholder="Empty = badge hidden"
                    />
                  </FormField>
                </div>
                <p style={{ color: "var(--text-muted)", margin: 0, fontSize: "var(--font-size-sm)" }}>
                  The app-store block renders only while at least one
                  URL is set — paste the REAL store listing links
                  only; an empty block is better than a dead badge.
                </p>
                <div>
                  <Button loading={savingLanding} onClick={() => void saveLanding()}>
                    Save landing page
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="History & restore — file retention">
              <div style={{ display: "grid", gap: "var(--space-3)" }}>
                <p style={{ color: "var(--text-muted)", margin: 0 }}>
                  When a user deletes something, its files (photos,
                  documents, receipts) are kept — hidden — for this
                  many days so a restore from their History can bring
                  them back. After the window, the nightly jobs purge
                  them for good. Applies to every account.
                </p>
                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-2)",
                    flexWrap: "wrap",
                    alignItems: "end",
                  }}
                >
                  <FormField label="Retention (days)">
                    <TextInput
                      type="number"
                      min={7}
                      max={3650}
                      value={retentionDays}
                      onChange={(e) => setRetentionDays(e.target.value)}
                      style={{ width: "8rem" }}
                    />
                  </FormField>
                  <Button
                    size="sm"
                    loading={savingRetention}
                    onClick={() => void saveRetention()}
                  >
                    Save retention
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="Community & spam firewall">
              {/* Kill-switch rows: the text column takes a 0%
                  basis so both items always collect onto one flex
                  line and the text shrinks/wraps beside the toggle.
                  (A 1 1 auto basis let the long Claim-readiness
                  description's max-content push the toggle onto a
                  line of its own — supervisory polish 2026-10-23.) */}
              <div style={{ display: "grid", gap: "var(--space-4)" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "var(--space-3)",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <div style={{ flex: "1 1 0%", minWidth: 0 }}>
                    <p style={{ fontWeight: 700, margin: 0 }}>Community Parts pool</p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      The operator kill-switch for the pool. Off hides
                      every listing (public and signed-in) — members'
                      shelves and settings are untouched.
                    </p>
                  </div>
                  <Toggle
                    checked={view.parts_pool_enabled}
                    onChange={(v) => void flipPool(v)}
                    disabled={savingPool}
                    ariaLabel="Community Parts pool enabled"
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "var(--space-3)",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <div style={{ flex: "1 1 0%", minWidth: 0 }}>
                    <p style={{ fontWeight: 700, margin: 0 }}>Tools for sale</p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      The operator kill-switch for the board. Off hides
                      every listing and the public reputation pages —
                      members' listings, deals and ratings are untouched.
                    </p>
                  </div>
                  <Toggle
                    checked={view.marketplace_enabled}
                    onChange={(v) => void flipMarketplace(v)}
                    disabled={savingPool}
                    ariaLabel="Tools for sale enabled"
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "var(--space-3)",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <div style={{ flex: "1 1 0%", minWidth: 0 }}>
                    <p style={{ fontWeight: 700, margin: 0 }}>Community Forum</p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      The operator kill-switch for the forum. Off hides
                      every category and thread — members' threads and
                      posts are untouched.
                    </p>
                  </div>
                  <Toggle
                    checked={view.forum_enabled}
                    onChange={(v) => void flipForum(v)}
                    disabled={savingPool}
                    ariaLabel="Community Forum enabled"
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "var(--space-3)",
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <div style={{ flex: "1 1 0%", minWidth: 0 }}>
                    <p style={{ fontWeight: 700, margin: 0 }}>Claim-readiness nudges</p>
                    <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                      The operator kill-switch for the weekly inbox
                      nudge that tells owners which items are missing
                      a photo, serial number, or purchase price.
                      Owners can also silence it themselves in
                      Settings → Notifications.
                    </p>
                  </div>
                  <Toggle
                    checked={view.claim_readiness_nudges_enabled}
                    onChange={(v) => void flipReadiness(v)}
                    disabled={savingReadiness}
                    ariaLabel="Claim-readiness nudges enabled"
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-2)",
                    flexWrap: "wrap",
                    alignItems: "end",
                  }}
                >
                  <FormField
                    label="Days between readiness nudges"
                    htmlFor="admin-readiness-interval"
                  >
                    <TextInput
                      id="admin-readiness-interval"
                      type="number"
                      min="1"
                      max="90"
                      step="1"
                      value={readinessInterval}
                      onChange={(e) => setReadinessInterval(e.target.value)}
                    />
                  </FormField>
                  <Button
                    type="button"
                    variant="secondary"
                    loading={savingReadiness}
                    onClick={() => void saveReadinessInterval()}
                  >
                    Save interval
                  </Button>
                </div>

                <div className="tv-admin-setblock">
                  <p className="tv-admin-settitle">NEW badges on menu items</p>
                  <p className="tv-admin-setnote">
                    The release registry: map a menu item's key to the date
                    its feature launched, and the item wears a NEW badge for
                    its first week — the badge stops on its own after day 7,
                    with nothing to remove. Keys are the menu items' names
                    (e.g. reports, flyers, truck-accounts, core-settings).
                    An empty {"{}"} badges nothing.
                  </p>
                  <FormField label="Badge registry (JSON)" htmlFor="admin-nav-badges">
                    <TextArea
                      id="admin-nav-badges"
                      value={badgesText}
                      onChange={(e) => setBadgesText(e.target.value)}
                      rows={4}
                      spellCheck={false}
                    />
                  </FormField>
                  <div className="tv-admin-setactions">
                    <Button
                      type="button"
                      variant="secondary"
                      loading={savingBadges}
                      onClick={() => void saveBadges()}
                    >
                      Save badge registry
                    </Button>
                  </div>
                </div>

                <div style={{ display: "grid", gap: "var(--space-3)" }}>
                  <p style={{ fontWeight: 700, margin: 0 }}>
                    Truck account payments (Stripe Connect)
                  </p>
                  <p style={{ color: "var(--text-muted)", margin: 0 }}>
                    Online payments on dealer truck accounts run through
                    Stripe Connect: the customer pays Stripe, Stripe pays
                    the dealer's bank — Toolbox Vault never holds the
                    money. The seam is deliberately DARK until BOTH the
                    platform Stripe keys exist AND this switch is on.
                    {view.truck_payments.configured
                      ? " Right now: CONFIGURED — dealers can onboard and their customers see Pay online."
                      : " Right now: DARK (keys missing and/or switch off) — the API answers payments_not_configured and no Pay online button renders."}
                  </p>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: "var(--space-3)",
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <p style={{ fontWeight: 700, margin: 0 }}>Online payments enabled</p>
                      <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
                        The master switch for truck-account online
                        payments. Manual (cash/check at the truck)
                        entries are unaffected.
                      </p>
                    </div>
                    <Toggle
                      checked={view.truck_payments.connect_enabled}
                      onChange={(v) => void flipTruckConnect(v)}
                      disabled={savingTruck}
                      ariaLabel="Truck online payments enabled"
                    />
                  </div>
                  <div
                    style={{
                      display: "flex",
                      gap: "var(--space-3)",
                      alignItems: "end",
                      flexWrap: "wrap",
                    }}
                  >
                    <FormField
                      label="Platform fee (%)"
                      hint="Disclosed in the truck account agreement. 0 = no platform fee (the launch posture until Ryan decides otherwise)."
                    >
                      <TextInput
                        type="number"
                        min={0}
                        max={100}
                        step="0.1"
                        value={truckFee}
                        onChange={(e) => setTruckFee(e.target.value)}
                      />
                    </FormField>
                    <Button
                      variant="secondary"
                      loading={savingTruck}
                      onClick={() => void saveTruckFee()}
                    >
                      Save fee
                    </Button>
                  </div>
                </div>

                {spam && (
                  <div style={{ display: "grid", gap: "var(--space-3)" }}>
                    <p style={{ fontWeight: 700, margin: 0 }}>
                      Anti-spam firewall (shared by messaging and
                      the forum)
                    </p>
                    <p style={{ color: "var(--text-muted)", margin: 0 }}>
                      First contacts land in a request quarantine.
                      Held messages wait in the moderation queue —
                      nothing is silently dropped. Trust tiers: 0 =
                      brand-new, 1 = a week old, 2 = a month old or
                      paid, 3 = paid + established. A trial never
                      raises a tier.
                    </p>
                    <div
                      style={{
                        display: "grid",
                        gap: "var(--space-3)",
                        gridTemplateColumns:
                          "repeat(auto-fit, minmax(min(100%, 170px), 1fr))",
                      }}
                    >
                      <FormField label="Blast: distinct recipients">
                        <TextInput
                          type="number"
                          min={1}
                          value={spam.blast_threshold}
                          onChange={(e) =>
                            setSpam({ ...spam, blast_threshold: Number(e.target.value) })
                          }
                        />
                      </FormField>
                      <FormField label="Blast window (minutes)">
                        <TextInput
                          type="number"
                          min={1}
                          value={spam.blast_window_minutes}
                          onChange={(e) =>
                            setSpam({
                              ...spam,
                              blast_window_minutes: Number(e.target.value),
                            })
                          }
                        />
                      </FormField>
                      <FormField label="Blast similarity (0–1)">
                        <TextInput
                          type="number"
                          min={0}
                          max={1}
                          step="0.05"
                          value={spam.blast_similarity}
                          onChange={(e) =>
                            setSpam({ ...spam, blast_similarity: Number(e.target.value) })
                          }
                        />
                      </FormField>
                    </div>

                    <div style={{ display: "grid", gap: "var(--space-2)" }}>
                      {(["0", "1", "2", "3"] as const).map((tier) => {
                        const caps = spam.tiers[tier];
                        if (!caps) return null;
                        const setCap = (key: keyof SpamTier, value: number) =>
                          setSpam({
                            ...spam,
                            tiers: {
                              ...spam.tiers,
                              [tier]: { ...caps, [key]: value },
                            },
                          });
                        return (
                          <div
                            key={tier}
                            style={{
                              display: "grid",
                              gap: "var(--space-2)",
                              gridTemplateColumns:
                                "repeat(auto-fit, minmax(min(100%, 130px), 1fr))",
                              alignItems: "end",
                            }}
                          >
                            <span style={{ fontWeight: 600 }}>Tier {tier}</span>
                            {(
                              [
                                ["new_threads_per_hour", "New threads / hour"],
                                ["new_threads_per_day", "New threads / day"],
                                ["messages_per_hour", "Messages / hour"],
                                ["messages_per_day", "Messages / day"],
                              ] as [keyof SpamTier, string][]
                            ).map(([key, label]) => (
                              <FormField key={key} label={label}>
                                <TextInput
                                  type="number"
                                  min={0}
                                  value={caps[key]}
                                  onChange={(e) => setCap(key, Number(e.target.value))}
                                />
                              </FormField>
                            ))}
                          </div>
                        );
                      })}
                    </div>

                    <FormField label="Blocked link domains (one per line; messages linking these are held)">
                      <TextArea
                        rows={4}
                        value={blockedText}
                        onChange={(e) => setBlockedText(e.target.value)}
                      />
                    </FormField>
                    <FormField label="Lure patterns (one regular expression per line; matches are held for moderation)">
                      <TextArea
                        rows={4}
                        value={lureText}
                        onChange={(e) => setLureText(e.target.value)}
                      />
                    </FormField>
                    <div>
                      <Button loading={savingSpam} onClick={() => void saveSpam()}>
                        Save spam settings
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Panel>

            <Panel title="Backups — last 7 runs">
              <div style={blockStackStyle}>
                <p style={blockHeadingStyle}>
                  Backup Drive — off-site copies
                </p>
                {driveResult === "connected" && (
                  <Alert tone="success">
                    Backup Drive connected — nightly bundles now upload
                    off-site after they are built and encrypted.
                  </Alert>
                )}
                {(driveResult === "denied" || driveResult === "failed") && (
                  <Alert tone="danger">
                    The backup Drive connection didn&apos;t finish. Try
                    connecting again, and make sure you approve the
                    request while signed in as the backup account.
                  </Alert>
                )}
                {view.backup_drive?.connected ? (
                  <>
                    <p style={mutedNoteStyle}>
                      Connected as {view.backup_drive.email || "the backup account"}
                      {view.backup_drive.folder_id
                        ? ` · folder ${view.backup_drive.folder_id}`
                        : ""}
                      {view.backup_drive.connected_at
                        ? ` · since ${formatWhen(view.backup_drive.connected_at)}`
                        : ""}
                    </p>
                    <div>
                      <Button
                        loading={driveBusy}
                        onClick={() => void disconnectDrive()}
                      >
                        Disconnect backup Drive
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <p style={mutedNoteStyle}>
                      Not connected — nightly bundles stay on this server
                      only. Connect the backup account&apos;s Google Drive
                      once and every encrypted bundle uploads there
                      automatically.
                    </p>
                    <div>
                      <Button
                        loading={driveBusy}
                        onClick={() => void connectDrive()}
                      >
                        Connect backup Drive
                      </Button>
                    </div>
                  </>
                )}
              </div>
              {view.backups.length === 0 ? (
                <p style={mutedNoteStyle}>
                  No backup runs recorded yet. The backup service runs
                  nightly; runs appear here as they happen.
                </p>
              ) : (
                <div style={listStackStyle}>
                  {view.backups.map((run, i) => (
                    <div key={`${run.started_at}-${i}`} style={rowSpreadStyle}>
                      <span>{run.bundle_name ?? "(unnamed run)"}</span>
                      <span style={mutedTextStyle}>
                        {formatWhen(run.started_at)}
                      </span>
                      <span>{formatBytes(run.size_bytes)}</span>
                      <strong>
                        {run.status}
                        {run.status === "ok" && run.verified ? " · verified" : ""}
                      </strong>
                    </div>
                  ))}
                </div>
              )}
              <p style={panelNoteStyle}>
                Statuses: ok = encrypted, uploaded to Drive, verified ·
                local_only = complete on the server, off-site upload not
                set up · encryption_not_configured = on the server,
                unencrypted, never uploaded · failed = see the failure
                alert email for the stage and the fix.
              </p>
            </Panel>

            <Panel title="Background jobs">
              {(view.jobs ?? []).length === 0 ? (
                <p style={{ color: "var(--text-muted)", margin: 0 }}>
                  No job information available.
                </p>
              ) : (
                /* 09b-F8: a TRUE list — header row, one job per row,
                   facts in columns (Job · Schedule · Last run ·
                   Result), the status pinned to its own column
                   instead of floating at ragged positions. */
                <DataTable
                  columns={
                    [
                      {
                        key: "job",
                        header: "Job",
                        sortable: true,
                        sortValue: (job) => job.job,
                        render: (job) => <strong>{job.job}</strong>,
                      },
                      {
                        key: "schedule",
                        header: "Schedule",
                        render: (job) =>
                          `Every ${
                            job.interval_minutes >= 60
                              ? `${job.interval_minutes / 60}h`
                              : `${job.interval_minutes}m`
                          }`,
                      },
                      {
                        key: "last_run",
                        header: "Last run",
                        sortable: true,
                        sortValue: (job) => job.last_started_at ?? "",
                        render: (job) =>
                          job.last_started_at
                            ? formatWhen(job.last_started_at)
                            : "Never run",
                      },
                      {
                        key: "result",
                        header: "Result",
                        render: (job) => (
                          <strong>
                            {job.last_status ?? "—"}
                            {job.last_status === "ok" && job.summary
                              ? ` · ${job.summary}`
                              : ""}
                            {job.last_status === "failed" && job.error
                              ? ` · ${job.error}`
                              : ""}
                          </strong>
                        ),
                      },
                    ] as Column<(typeof view.jobs)[number]>[]
                  }
                  rows={view.jobs ?? []}
                  rowKey={(job) => job.job}
                />
              )}
              <p style={{ color: "var(--text-muted)", margin: "var(--space-3) 0 0", fontSize: "var(--font-size-sm)" }}>
                The compose jobs service runs the periodic chores:
                entitlements (subscription lapses + AI refills),
                maintenance and claims notifications, the marketplace
                14-day rating sweep, and the audit daily markers +
                file purge. Each run is recorded; a failed run shows
                its error here instead of failing silently.
              </p>
            </Panel>

            <Panel title="System stats">
              <dl
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                  gap: "var(--space-2) var(--space-4)",
                  margin: "0 0 var(--space-3)",
                }}
              >
                {[
                  ["Accounts", String(view.stats.users)],
                  ["Tools", String(view.stats.tools)],
                  ["Feature modules", String(view.stats.feature_modules)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>{label}</dt>
                    <dd style={{ margin: 0, fontWeight: 700, fontSize: "var(--font-size-lg)" }}>{value}</dd>
                  </div>
                ))}
              </dl>
              {/* 09b-F7: the raw table census is diagnostics, not
                  the panel's face — it folds behind a disclosure so
                  the panel opens on the three human stats, and long
                  table names wrap inside their own cell instead of
                  colliding into the next column. */}
              <details>
                <summary style={{ fontWeight: 700, cursor: "pointer" }}>
                  Rows per table (diagnostics)
                </summary>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                    gap: "var(--space-1) var(--space-4)",
                    marginTop: "var(--space-2)",
                  }}
                >
                  {Object.entries(view.stats.tables)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([table, count]) => (
                      <div
                        key={table}
                        style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}
                      >
                        <span style={{ color: "var(--text-muted)", overflowWrap: "anywhere" }}>{table}</span>
                        <strong>{count}</strong>
                      </div>
                    ))}
                </div>
              </details>
            </Panel>
          </>
        )}
      </div>
    </AdminShell>
  );
}

export default function AdminSettingsPage() {
  return (
    <RequireAuth>
      <SettingsSection />
    </RequireAuth>
  );
}
