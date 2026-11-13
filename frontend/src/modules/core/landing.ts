import { api } from "../../lib/api";

/**
 * The public landing config — the ONLY data the signed-out pages
 * read (GET /api/core/landing, no auth; core/landing.py owns the
 * values and the honesty rules). Every value is operator-edited
 * in Admin → Settings: display prices, the self-serve trial
 * switch + copy, the app-store URLs, and the plan catalog's free
 * item limit. The fallback below mirrors the server's seeded
 * defaults so a failed fetch degrades to the same page, never to
 * invented numbers.
 */
export interface LandingConfig {
  pro_monthly_price: string;
  pro_yearly_price: string;
  business_monthly_price: string;
  business_yearly_price: string;
  self_serve_trial_enabled: boolean;
  trial_copy: string;
  app_store_url: string;
  play_store_url: string;
  free_item_limit: number;
  /** Teaser mode (2026-10-26): is the public front door the
   *  teaser right now? One boolean — the gate code is never in
   *  this shape (it never leaves the server). */
  teaser_mode: boolean;
  /** Free-access card gates (2026-10-31): the landing's Tools
   *  For Sale / Community Parts cards render only while the
   *  operator switchboard has those modules usable somewhere on
   *  the site. Computed server-side; fallback is false — never
   *  advertise what isn't there. */
  marketplace_enabled: boolean;
  community_parts_enabled: boolean;
  /** The current teaser trailer's presigned URLs (site-hosted
   *  MP4 + poster frame). Empty unless the teaser is on AND the
   *  operator has set a video — empty means NO slot renders. */
  teaser_video_url: string;
  teaser_poster_url: string;
}

export const LANDING_FALLBACK: LandingConfig = {
  pro_monthly_price: "7.99",
  pro_yearly_price: "79.99",
  business_monthly_price: "",
  business_yearly_price: "",
  self_serve_trial_enabled: false,
  trial_copy: "",
  app_store_url: "",
  play_store_url: "",
  free_item_limit: 20,
  teaser_mode: false,
  marketplace_enabled: false,
  community_parts_enabled: false,
  teaser_video_url: "",
  teaser_poster_url: "",
};

export async function fetchLandingConfig(): Promise<LandingConfig> {
  try {
    return await api<LandingConfig>("/core/landing");
  } catch {
    return LANDING_FALLBACK;
  }
}

/** The landing config, fetched once per document and shared:
 *  the shell (teaser wall + chrome), the home route and the
 *  signup page all read the same public posture, and one fetch
 *  keeps them from ever disagreeing mid-load. */
let sharedLandingConfig: Promise<LandingConfig> | null = null;
export function fetchLandingConfigShared(): Promise<LandingConfig> {
  sharedLandingConfig ??= fetchLandingConfig();
  return sharedLandingConfig;
}

/** The signup gate's posture for THIS browser (core/teaser.py):
 *  teaser on or off, and whether this browser already holds the
 *  unlock. Deliberately NOT cached — the answer changes the
 *  moment an unlock lands. */
export interface SignupGate {
  teaser_mode: boolean;
  unlocked: boolean;
}

export async function fetchSignupGate(): Promise<SignupGate> {
  return api<SignupGate>("/core/signup-gate");
}

export async function unlockSignup(code: string): Promise<SignupGate> {
  return api<SignupGate>("/core/signup-unlock", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}
