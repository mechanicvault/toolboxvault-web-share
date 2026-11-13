/**
 * Teaser mode state + the signed-out wall (owner order,
 * 2026-10-26). While the operator's teaser switch is on, the
 * public front door is the teaser page and a signed-out visitor
 * can reach nothing but the teaser, the two doors (log in /
 * create account), and the login door's own machinery. A deep
 * link to anything else meets the sign-in door with its
 * destination kept (sweep C2, 2026-11-12 — TeaserWall below);
 * it is never dumped on the teaser. Signed-in sessions are
 * never touched by any of this.
 *
 * The posture comes from the ONE public boolean on the landing
 * config (`teaser_mode`) — fetched once per document through the
 * shared landing fetch. The gate CODE never appears on the
 * client at all; the API is the gate (see core/teaser.py).
 */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import { TOKEN_KEY } from "../../lib/api";
import { useAuth } from "./AuthContext";
import { fetchLandingConfigShared } from "./landing";

interface TeaserState {
  /** Has the public posture been read at least once? Until it
   *  has, the signed-out root shows the brand splash — the full
   *  landing must never flash its features to a teaser-world
   *  visitor while the answer is still loading. */
  known: boolean;
  teaserMode: boolean;
  /** The current teaser trailer (site-hosted MP4 + poster).
   *  Empty videoUrl = no slot renders at all. */
  videoUrl: string;
  posterUrl: string;
  /** The app-store URLs (owner, 2026-10-31): the SAME
   *  operator-set values the merged landing's store block and
   *  the phone app bar use — one source, so the doors on the
   *  teaser can carry direct links to the apps. Empty = the
   *  links row renders nothing (settings-gated, no invented
   *  links — the landing's own rule). */
  appStoreUrl: string;
  playStoreUrl: string;
}

const TeaserContext = createContext<TeaserState>({
  known: false,
  teaserMode: false,
  videoUrl: "",
  posterUrl: "",
  appStoreUrl: "",
  playStoreUrl: "",
});

export function TeaserProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<TeaserState>({
    known: false,
    teaserMode: false,
    videoUrl: "",
    posterUrl: "",
    appStoreUrl: "",
    playStoreUrl: "",
  });
  useEffect(() => {
    let live = true;
    void fetchLandingConfigShared().then((config) => {
      if (live) {
        setState({
          known: true,
          teaserMode: config.teaser_mode,
          videoUrl: config.teaser_video_url,
          posterUrl: config.teaser_poster_url,
          appStoreUrl: config.app_store_url,
          playStoreUrl: config.play_store_url,
        });
      }
    });
    return () => {
      live = false;
    };
  }, []);
  return (
    <TeaserContext.Provider value={state}>{children}</TeaserContext.Provider>
  );
}

export function useTeaser(): TeaserState {
  return useContext(TeaserContext);
}

/** Paths a signed-out visitor may still reach while the teaser
 *  is the front door: the two doors themselves, the flows the
 *  login door depends on (password reset and verification links
 *  arrive by email and are useless without an account), and the
 *  legal pages the signup form links to. Everything else — the
 *  dealer directory, marketplace, forum, help, public
 *  storefronts — returns to the teaser. */
const TEASER_OPEN_PATHS: ReadonlySet<string> = new Set([
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/confirm-email-change",
  "/auth/callback",
  "/terms",
  "/privacy",
  // The /downloads lead magnet (2026-10-29): public by design — a
  // stranger following a flyer/QR link must land on the page, not
  // the teaser. Exact path only, like every other entry here.
  "/downloads",
]);

/** The 3D print files shelf (owner, 2026-11-08 21:03): public by
 *  design on the same footing as /downloads — a stranger following
 *  a shared link must land on the shelf or the file itself, never
 *  the teaser. The family rides a prefix rule, not the exact-path
 *  set above, because record pages live under the seat
 *  (/3dprints/<id>). The legacy /downloads/prints doors are
 *  exempt on the same reasoning: they only redirect here, and a
 *  bounced stranger would never reach the redirect. */
const TEASER_OPEN_PREFIXES = ["/3dprints", "/downloads/prints"];

/** The FEEDBACK BOARDS family (sweep C2, 2026-11-12): the one
 *  members-only family whose designed sign-in door lives IN the
 *  page itself — BoardsSignInDoor renders inside the app shell
 *  with the return path, and the API refuses anonymous reads
 *  server-side. The wall stands down for these routes so a
 *  deep link reaches that door; every other members-only
 *  destination takes the wall's own door below. */
const TEASER_DOOR_IN_APP_PREFIXES = ["/feedback"];

/** The wall: rendered inside the router by the shell. A
 *  definitively signed-out visitor (no user, auth settled, no
 *  stored session still resolving) on any non-open path meets
 *  the SIGN-IN DOOR, never a dump on the marketing teaser
 *  (sweep 08-F1, remade 2026-11-12): the wall sends them to
 *  /login carrying the FULL destination (pathname + search +
 *  hash) as the redirect-back state LoginPage already honors,
 *  so signing in lands them on what they clicked. The one
 *  exception is the door-in-app family above, whose pages
 *  render their own door. Any hint of a session — a signed-in
 *  user, auth still loading, a token in storage — stands the
 *  wall down, so a returning member is never bounced. The
 *  teaser keeps its job at the root path alone. */
export function TeaserWall() {
  const { known, teaserMode } = useTeaser();
  const { user, loading } = useAuth();
  const location = useLocation();
  if (!known || !teaserMode || user || loading) return null;
  if (localStorage.getItem(TOKEN_KEY)) return null;
  const path = location.pathname;
  if (path === "/" || TEASER_OPEN_PATHS.has(path)) return null;
  if (
    TEASER_OPEN_PREFIXES.some(
      (p) => path === p || path.startsWith(`${p}/`),
    )
  )
    return null;
  if (
    TEASER_DOOR_IN_APP_PREFIXES.some(
      (p) => path === p || path.startsWith(`${p}/`),
    )
  )
    return null;
  return (
    <Navigate
      to="/login"
      replace
      state={{
        from: location.pathname + location.search + location.hash,
      }}
    />
  );
}

/** Is the bare front door showing (teaser on + signed out + at
 *  "/")? The shell uses this to strip its chrome — brand strip,
 *  app-store bar, construction banner — so the teaser page is
 *  the whole front door, exactly as ordered. One closing piece
 *  remains: the page ends with the shared site footer, like
 *  every other surface (footer unification, owner 2026-11-07). */
export function useTeaserBareChrome(): boolean {
  const { known, teaserMode } = useTeaser();
  const { user, loading } = useAuth();
  const location = useLocation();
  if (!known || !teaserMode || user || loading) return false;
  if (localStorage.getItem(TOKEN_KEY)) return false;
  return location.pathname === "/";
}
