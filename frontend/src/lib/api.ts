/** Tiny API client. One job: fetch JSON with the JWT attached,
 *  transparently renew the session with the refresh token when the
 *  access token expires, and turn failures into plain-language errors. */

export const TOKEN_KEY = "tv-token";
export const REFRESH_TOKEN_KEY = "tv-refresh-token";

/** Endpoints that must never trigger a refresh-and-retry on 401. */
const NO_REFRESH_PATHS = ["/core/login", "/core/signup", "/core/refresh"];

export class ApiError extends Error {
  status: number;
  /** Machine-readable code from a structured error detail
   *  (e.g. "module_unavailable", "email_unverified"), when the
   *  server sent one — callers branch on this, never on the
   *  message text. */
  code?: string;
  /** The full structured detail object when the server sent one
   *  (e.g. the duplicate-create 409 carries `existing: [...]`) —
   *  wave 4. Callers read named fields off it; never branch on
   *  message text. */
  detail?: Record<string, unknown>;
  constructor(
    status: number,
    message: string,
    code?: string,
    detail?: Record<string, unknown>,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function plainMessage(status: number, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    // Structured details (e.g. the module gate's
    // {code: "module_unavailable", message: "…"}) carry their own
    // plain-language message — show it verbatim.
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d.msg === "string" ? d.msg : null))
      .filter((m): m is string => !!m);
    if (msgs.length > 0) return msgs.join("; ");
  }
  switch (status) {
    case 400:
      return "That request wasn't valid. Check the fields and try again.";
    case 401:
      return "Invalid email or password.";
    case 403:
      return "You don't have permission to do that.";
    case 404:
      return "That wasn't found. It may have been deleted.";
    case 409:
      return "That already exists.";
    case 422:
      return "Some fields need fixing — check and try again.";
    case 429:
      return "Too many attempts. Wait a minute and try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function storeTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  // A new identity must never read the previous one's cached
  // Home reads (the GET cache window below).
  clearGetCache();
  // A fresh authentication starts a new token chain: any refresh
  // busy-mark left behind by a dead document (see attemptRefresh)
  // says nothing about this chain, so it goes.
  clearRefreshBusyMark();
}

export function clearTokens(): void {
  clearGetCache();
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

let refreshInFlight: Promise<boolean> | null = null;

/* -- Cross-document refresh coordination (deep audit W-03) --------
 * The server rotates the refresh token on every use, and presenting
 * an already-rotated token is treated as theft: the WHOLE token
 * family is revoked (F4-01 — by design, unchanged). That makes a
 * second honest presentation catastrophic, and honest clients used
 * to produce one: the old single-flight guard was a per-document
 * variable, so two documents (two tabs, or a page and its
 * replacement in a rapid double load) each read the same stored
 * refresh token and each presented it — the second tripped the
 * theft response and signed the user out everywhere.
 *
 * The protocol below keeps honest documents from ever presenting a
 * token another document is rotating or has rotated:
 *  - A Web Lock serializes refreshes across documents; inside the
 *    lock, if the stored ACCESS token has changed since our 401,
 *    another document already refreshed for us — present nothing,
 *    just retry with the fresh token.
 *  - A busy-mark in localStorage is written BEFORE the refresh POST
 *    and cleared only AFTER the rotated pair is stored. A document
 *    that finds a FRESH mark while holding the lock knows the
 *    previous refresh never stored its result — its owner died
 *    mid-flight and the stored refresh token may already be
 *    rotated server-side. Presenting it would trip the theft
 *    response, so it refuses: this tab signs out, the family (and
 *    every other device) survives. Without Web Locks the mark is
 *    instead waited out, then the same rules apply. */
const REFRESH_BUSY_KEY = "tv-refresh-busy";
const REFRESH_BUSY_FRESH_MS = 30_000;
const REFRESH_WAIT_MS = 12_000;

interface RefreshBusyMark {
  t: number;
  n: string;
}

function readRefreshBusyMark(): RefreshBusyMark | null {
  try {
    const raw = localStorage.getItem(REFRESH_BUSY_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RefreshBusyMark;
    return typeof parsed?.t === "number" ? parsed : null;
  } catch {
    return null;
  }
}

function writeRefreshBusyMark(nonce: string): void {
  try {
    localStorage.setItem(
      REFRESH_BUSY_KEY,
      JSON.stringify({ t: Date.now(), n: nonce }),
    );
  } catch {
    /* storage unavailable — the Web Lock still serializes us */
  }
}

function clearRefreshBusyMark(nonce?: string): void {
  try {
    if (nonce) {
      const mark = readRefreshBusyMark();
      if (mark && mark.n !== nonce) return;
    }
    localStorage.removeItem(REFRESH_BUSY_KEY);
  } catch {
    /* storage unavailable — nothing to clear */
  }
}

/** One actual refresh exchange, busy-marked (see above). */
async function doRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) return false;
  const nonce = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  writeRefreshBusyMark(nonce);
  try {
    const res = await fetch("/api/core/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as {
      access_token: string;
      refresh_token: string;
    };
    storeTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  } finally {
    clearRefreshBusyMark(nonce);
  }
}

async function coordinatedRefresh(
  sentAccess: string | null,
): Promise<boolean> {
  const run = async (): Promise<boolean> => {
    const mark = readRefreshBusyMark();
    if (mark) {
      if (Date.now() - mark.t <= REFRESH_BUSY_FRESH_MS) {
        // Interrupted refresh (see the protocol note): do NOT
        // present the stored token — it may already be rotated.
        clearRefreshBusyMark();
        return false;
      }
      clearRefreshBusyMark(); // ancient debris from a dead chain
    }
    const currentAccess = localStorage.getItem(TOKEN_KEY);
    if (currentAccess && sentAccess && currentAccess !== sentAccess) {
      // Another document already refreshed while we waited; the
      // caller's retry re-reads the fresh access token itself.
      return true;
    }
    return doRefresh();
  };
  const locks = (
    navigator as unknown as {
      locks?: {
        request: (
          name: string,
          cb: () => Promise<boolean>,
        ) => Promise<boolean>;
      };
    }
  ).locks;
  if (locks?.request) {
    return locks.request("tv-token-refresh", run);
  }
  // No Web Locks: if another document's refresh is in flight, wait
  // for its busy-mark to clear, then run the same rules.
  const mark = readRefreshBusyMark();
  if (mark && Date.now() - mark.t <= REFRESH_BUSY_FRESH_MS) {
    const deadline = Date.now() + REFRESH_WAIT_MS;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 200));
      if (!readRefreshBusyMark()) break;
    }
  }
  return run();
}

/** Exchange the stored refresh token for a new token pair (the server
 *  rotates: the presented token dies, a fresh one is stored).
 *  Single-flight within this document, coordinated across documents
 *  (see the W-03 protocol above). `sentAccess` is the access token
 *  the 401'd request carried, so a refresh another document already
 *  completed is recognized instead of duplicated. */
function attemptRefresh(sentAccess: string | null): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = coordinatedRefresh(sentAccess).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function rawFetch(path: string, init: RequestInit): Promise<Response> {
  const token = localStorage.getItem(TOKEN_KEY);
  return fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
}

const UNREACHABLE = "Couldn't reach the server. Check your connection and try again.";

/* -- Home GET cache window ---------------------------------------
 * The new Home shell (design 2026-11-10, §3.9's performance rule)
 * opens this window while it is mounted: opening a menu, flipping
 * an option, or starting a drag must never reload a widget's data
 * over the network, and landing on Home — every visit — should not
 * re-fetch every box from zero. While the window is open, plain
 * GETs are cached for a short TTL with in-flight dedupe (two boxes
 * asking for the same read share one request). Safety rails:
 *  - ANY non-GET request anywhere clears the whole cache (a write
 *    may have changed anything a cached read would serve — the
 *    truck widget's post-then-reload lands fresh because its post
 *    already cleared the window's memory). ONE exception: writes
 *    to the page-layout store (/core/layouts/…) — the Home shell
 *    saves a layout after nearly every chrome gesture, and a
 *    layout is not widget data; letting those saves clear the
 *    cache would make the very next option flip re-fetch over the
 *    network, breaking the rule this window exists to keep. The
 *    shell owns layout state itself and never reads it back
 *    through this cache mid-session;
 *  - storing or clearing auth tokens clears it (a new identity
 *    must never read the previous one's cached answers);
 *  - failed reads are never cached;
 *  - closing the window (Home unmounts) clears it.
 * Outside the window the client behaves exactly as it always has. */
const GET_CACHE_TTL_MS = 45_000;
let getCacheWindowOpen = false;
const getCache = new Map<string, { at: number; promise: Promise<unknown> }>();

export function openGetCacheWindow(): void {
  getCacheWindowOpen = true;
}

export function closeGetCacheWindow(): void {
  getCacheWindowOpen = false;
  getCache.clear();
}

function clearGetCache(): void {
  getCache.clear();
}

/** GET/POST/PUT/DELETE JSON against /api. Throws ApiError on failure. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET") {
    // A write anywhere invalidates every cached read — except a
    // page-layout save (see the window's contract above).
    if (!path.startsWith("/core/layouts/")) {
      clearGetCache();
    }
    return apiUncached<T>(path, init);
  }
  if (getCacheWindowOpen && init.body === undefined) {
    const hit = getCache.get(path);
    if (hit && Date.now() - hit.at <= GET_CACHE_TTL_MS) {
      return hit.promise as Promise<T>;
    }
    const promise = apiUncached<T>(path, init);
    const entry = { at: Date.now(), promise: promise as Promise<unknown> };
    getCache.set(path, entry);
    // A failed read is not an answer — never serve it twice.
    promise.catch(() => {
      if (getCache.get(path) === entry) getCache.delete(path);
    });
    return promise;
  }
  return apiUncached<T>(path, init);
}

async function apiUncached<T>(path: string, init: RequestInit = {}): Promise<T> {
  const sentAccess = localStorage.getItem(TOKEN_KEY);
  let res: Response;
  try {
    res = await rawFetch(path, init);
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (res.status === 401 && !NO_REFRESH_PATHS.includes(path)) {
    // Access token expired mid-session: renew once, retry once.
    if (await attemptRefresh(sentAccess)) {
      try {
        res = await rawFetch(path, init);
      } catch {
        throw new ApiError(0, UNREACHABLE);
      }
    }
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const code =
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as { code?: unknown }).code
        : undefined;
    throw new ApiError(
      res.status,
      plainMessage(res.status, detail),
      typeof code === "string" ? code : undefined,
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as Record<string, unknown>)
        : undefined,
    );
  }
  return data as T;
}

/** api() for paged list endpoints: returns the page plus the
 *  X-Total-Count header the server sends with it (null when the
 *  endpoint didn't send one). Same auth + one-refresh behavior. */
export async function apiPage<T>(
  path: string,
  init: RequestInit = {},
): Promise<{ data: T; total: number | null; headers: Headers }> {
  const sentAccess = localStorage.getItem(TOKEN_KEY);
  let res: Response;
  try {
    res = await rawFetch(path, init);
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (res.status === 401 && !NO_REFRESH_PATHS.includes(path)) {
    if (await attemptRefresh(sentAccess)) {
      try {
        res = await rawFetch(path, init);
      } catch {
        throw new ApiError(0, UNREACHABLE);
      }
    }
  }
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const code =
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as { code?: unknown }).code
        : undefined;
    throw new ApiError(
      res.status,
      plainMessage(res.status, detail),
      typeof code === "string" ? code : undefined,
      detail && typeof detail === "object" && !Array.isArray(detail)
        ? (detail as Record<string, unknown>)
        : undefined,
    );
  }
  const rawTotal = res.headers.get("X-Total-Count");
  const total = rawTotal === null ? null : Number(rawTotal);
  return {
    data: data as T,
    total: Number.isNaN(total) ? null : total,
    headers: res.headers,
  };
}

/** GET a binary download (the data-export ZIP) with the same auth
 *  and one-refresh behavior as api(). */
export async function apiBlob(path: string): Promise<Blob> {
  const sentAccess = localStorage.getItem(TOKEN_KEY);
  let res: Response;
  try {
    res = await rawFetch(path, {});
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (res.status === 401 && !NO_REFRESH_PATHS.includes(path)) {
    if (await attemptRefresh(sentAccess)) {
      try {
        res = await rawFetch(path, {});
      } catch {
        throw new ApiError(0, UNREACHABLE);
      }
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, plainMessage(res.status, null));
  }
  return res.blob();
}

/** Save a Blob as a file download (the anchor-click pattern the
 *  data export uses, shared so every download behaves alike). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
