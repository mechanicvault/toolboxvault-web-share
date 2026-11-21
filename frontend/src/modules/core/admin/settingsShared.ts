import { type CSSProperties } from "react";

export interface BackupRunView {
  started_at: string;
  finished_at: string | null;
  bundle_name: string | null;
  size_bytes: number | null;
  encrypted: boolean;
  uploaded: boolean;
  verified: boolean;
  status: string;
}

export interface JobRunView {
  job: string;
  interval_minutes: number;
  last_status: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  summary: string | null;
  error: string | null;
}

export interface StripePack {
  id: string;
  label: string;
  credits: number;
  stripe_price_id: string;
}

export interface SpamTier {
  new_threads_per_hour: number;
  new_threads_per_day: number;
  messages_per_hour: number;
  messages_per_day: number;
}

export interface SpamConfig {
  blast_threshold: number;
  blast_window_minutes: number;
  blast_similarity: number;
  blocked_domains: string[];
  lure_patterns: string[];
  tiers: Record<string, SpamTier>;
}

export interface SettingsView {
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
export const mutedTextStyle: CSSProperties = { color: "var(--text-muted)" };
export const mutedNoteStyle: CSSProperties = { color: "var(--text-muted)", margin: 0 };
export const panelNoteStyle: CSSProperties = {
  color: "var(--text-muted)",
  margin: "var(--space-3) 0 0",
  fontSize: "var(--font-size-sm)",
};
export const listStackStyle: CSSProperties = { display: "grid", gap: "var(--space-1)" };
export const panelStackStyle: CSSProperties = { display: "grid", gap: "var(--space-3)" };

/** Capture a poster frame from a local MP4 in the browser: load
 *  the file into an off-screen <video>, seek just past the
 *  start, draw to a canvas, export WebP. Best-effort by design —
 *  any failure resolves null and the teaser upload proceeds
 *  without a poster (the page then shows the video's own first
 *  frame). A timeout keeps a stubborn file from hanging the
 *  panel. */
export function captureVideoPoster(file: File): Promise<Blob | null> {
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
export const rowSpreadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "var(--space-3)",
  flexWrap: "wrap",
};
export const blockHeadingStyle: CSSProperties = { fontWeight: 700, margin: 0 };
export const blockStackStyle: CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
  marginBottom: "var(--space-3)",
};

export function formatBytes(size: number | null): string {
  if (size === null) return "—";
  if (size < 1_000_000) return `${(size / 1_000).toFixed(1)} KB`;
  return `${(size / 1_000_000).toFixed(1)} MB`;
}

export function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

