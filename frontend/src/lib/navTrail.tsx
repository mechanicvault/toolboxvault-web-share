import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  useLocation,
  useNavigate,
  useNavigationType,
} from "react-router-dom";

import type { Crumb } from "../components/Breadcrumbs";
import { MODULES } from "../modules/registry";

/**
 * Back / forward navigation + the link tree (owner directive
 * 2026-11-02 21:21 CST: "On all pages, there should be a back
 * button, or a link tree showing the user where they are at, or
 * both… a little arrow pointing left and right just to the left
 * of any page header text, that way the user can go back to the
 * previous page or forward to a page they just came back from").
 *
 * The trail is the app's OWN record of page navigations — not
 * the browser's history — so the arrows (components/PageNavBar)
 * enable and disable truthfully and can never dump the user out
 * of the site:
 *
 *  - Only real page navigations enter the trail: a pathname
 *    change. Hash/query-only changes on the same page (tab deep
 *    links, the /help?ticket= door), in-place tab switches, and
 *    modal opens never touch it.
 *  - A fresh push truncates everything ahead of the current
 *    entry (browser semantics); consecutive duplicates dedupe
 *    by pathname; a replace (login redirects, the settings
 *    arrival redirect) rewrites the current entry in place.
 *  - POP (the arrows themselves, or the browser's own back /
 *    forward) moves the pointer to the matching entry when the
 *    trail knows it; an unknown POP target restarts the trail
 *    at that page rather than guessing.
 *  - A fresh deep-link load starts a one-entry trail: back has
 *    nowhere in-app to go, so it falls back to the page's
 *    PARENT (parentPathFor below) — an item lands on its list,
 *    never out of the site. Top-level pages have no parent and
 *    their back arrow is simply disabled.
 *
 * The link tree renders from, in priority order: (1) a trail
 * the page itself registered with usePageCrumbs (record pages
 * whose current-step label is a record's name — the dealer
 * company page, the claim page, and since the owner batch
 * 2026-11-03 the item, battery, set, part and truck-account
 * pages: the owner ruled the tree belongs HERE, right of the
 * arrows, not down in the page header, so those pages register
 * theirs and carry no in-header trail), (2) a route-derived
 * trail for the settings sections, /help, and the admin pages,
 * (3) nothing — pages that still carry their own in-header
 * trail (forum, feedback, marketplace, message thread, and the
 * form/wizard pages) keep exactly that one, and plain list
 * pages show the arrows alone.
 */

interface TrailEntry {
  key: string;
  pathname: string;
}

/** Trail hygiene: a very long session keeps the newest entries. */
const TRAIL_CAP = 60;

const STATIC_PARENTS: Record<string, string> = {
  "/inventory/new": "/inventory",
  "/inventory/import": "/inventory",
  "/inventory/labels": "/inventory",
  "/inventory/health": "/inventory",
  "/inventory/categories": "/inventory",
  "/parts/new": "/parts",
  "/parts/community": "/parts",
  "/dealers/new": "/dealers",
  "/dealers/find-agent": "/dealers",
  "/marketplace/new": "/marketplace",
  "/marketplace/mine": "/marketplace",
  "/feedback/bugs": "/feedback",
  "/feedback/features": "/feedback",
};

const PATTERN_PARENTS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^\/inventory\/batteries\/([^/]+)\/edit$/, (m) => `/inventory/batteries/${m[1]}`],
  [/^\/inventory\/batteries\/([^/]+)$/, () => "/inventory"],
  [/^\/inventory\/([^/]+)\/edit$/, (m) => `/inventory/${m[1]}`],
  [/^\/inventory\/([^/]+)$/, () => "/inventory"],
  [/^\/parts\/([^/]+)\/edit$/, (m) => `/parts/${m[1]}`],
  [/^\/parts\/([^/]+)$/, () => "/parts"],
  [/^\/dealers\/([^/]+)$/, () => "/dealers"],
  [/^\/claims\/([^/]+)$/, () => "/repairs#repair-claims"],
  [/^\/truck-accounts\/([^/]+)$/, () => "/truck-accounts"],
  [/^\/settings\/([^/]+)$/, () => "/settings"],
  [/^\/admin\/([^/]+)$/, () => "/admin"],
  [/^\/forum\/category\/([^/]+)$/, () => "/forum"],
  [/^\/forum\/thread\/([^/]+)$/, () => "/forum"],
  [/^\/feedback\/post\/([^/]+)$/, () => "/feedback"],
  [/^\/messages\/([^/]+)$/, () => "/messages"],
  [/^\/marketplace\/([^/]+)\/edit$/, (m) => `/marketplace/${m[1]}`],
  [/^\/marketplace\/([^/]+)$/, () => "/marketplace"],
];

/**
 * The parent a back press falls back to when the trail holds no
 * earlier page (a fresh deep-link load). Detail pages land on
 * their list, edit pages on their record, nested single pages
 * on their desk, settings sections on Settings. Top-level pages
 * return null — nowhere honest to go.
 */
export function parentPathFor(pathname: string): string | null {
  const staticParent = STATIC_PARENTS[pathname];
  if (staticParent) return staticParent;
  for (const [pattern, build] of PATTERN_PARENTS) {
    const m = pattern.exec(pathname);
    if (m) return build(m);
  }
  return null;
}

interface NavTrailValue {
  /** In-trail back exists. */
  canBack: boolean;
  /** In-trail forward exists. */
  canForward: boolean;
  /** Back is pressable: in-trail back, or the parent fallback. */
  backEnabled: boolean;
  goBack: () => void;
  goForward: () => void;
  /** The page-registered link tree for the current page. */
  crumbs: Crumb[] | null;
  setCrumbs: (crumbs: Crumb[] | null) => void;
}

const NavTrailContext = createContext<NavTrailValue | null>(null);

export function NavTrailProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navType = useNavigationType();
  const navigate = useNavigate();
  const [trail, setTrail] = useState<{ entries: TrailEntry[]; index: number }>({
    entries: [],
    index: -1,
  });
  const [crumbs, setCrumbsState] = useState<Crumb[] | null>(null);
  // Latest trail in a ref so the callbacks stay stable while the
  // location effect below is the trail's only writer.
  const trailRef = useRef(trail);
  trailRef.current = trail;

  useEffect(() => {
    setTrail((prev) => {
      const { entries, index } = prev;
      const current = index >= 0 ? entries[index] : undefined;
      const here: TrailEntry = { key: location.key, pathname: location.pathname };
      // Same page: a hash/query-only change, or the arrival
      // redirect settling on the path it names. Not a navigation
      // — refresh the entry's key and stay put.
      if (current && current.pathname === location.pathname) {
        if (current.key === location.key) return prev;
        const next = entries.slice();
        next[index] = here;
        return { entries: next, index };
      }
      if (entries.length === 0) {
        return { entries: [here], index: 0 };
      }
      if (navType === "POP") {
        const at = entries.findIndex((e) => e.key === location.key);
        if (at >= 0) return { entries, index: at };
        // The browser walked somewhere the trail never recorded
        // (e.g. past a replace chain): restart honestly here.
        return { entries: [here], index: 0 };
      }
      if (navType === "REPLACE") {
        const next = entries.slice();
        next[index] = here;
        return { entries: next, index };
      }
      // PUSH: drop any forward entries, then append.
      const base = entries.slice(0, index + 1);
      base.push(here);
      const overflow = base.length - TRAIL_CAP;
      const trimmed = overflow > 0 ? base.slice(overflow) : base;
      return { entries: trimmed, index: trimmed.length - 1 };
    });
  }, [location.key, location.pathname, navType]);

  const value = useMemo<NavTrailValue>(() => {
    const { entries, index } = trail;
    const canBack = index > 0;
    const canForward = index >= 0 && index < entries.length - 1;
    const parent =
      index >= 0 ? parentPathFor(entries[index]?.pathname ?? "") : null;
    return {
      canBack,
      canForward,
      backEnabled: canBack || parent != null,
      goBack: () => {
        const t = trailRef.current;
        if (t.index > 0) {
          navigate(-1);
        } else {
          const p = parentPathFor(t.entries[t.index]?.pathname ?? "");
          if (p) navigate(p);
        }
      },
      goForward: () => {
        const t = trailRef.current;
        if (t.index >= 0 && t.index < t.entries.length - 1) navigate(1);
      },
      crumbs,
      setCrumbs: setCrumbsState,
    };
  }, [trail, crumbs, navigate]);

  return (
    <NavTrailContext.Provider value={value}>{children}</NavTrailContext.Provider>
  );
}

export function useNavTrail(): NavTrailValue {
  const ctx = useContext(NavTrailContext);
  if (!ctx) throw new Error("useNavTrail outside NavTrailProvider");
  return ctx;
}

/**
 * Register the current page's link tree with the shell bar.
 * Pages call it with their trail once their record loads (null
 * until then). The registration clears when the page unmounts;
 * identity is the serialized trail, so re-renders with equal
 * items never churn the bar.
 */
export function usePageCrumbs(items: Crumb[] | null) {
  const ctx = useContext(NavTrailContext);
  const serialized = items ? JSON.stringify(items) : "";
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const appliedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!ctx) return;
    if (appliedRef.current !== serialized) {
      appliedRef.current = serialized;
      ctx.setCrumbs(serialized ? itemsRef.current : null);
    }
  }, [ctx, serialized]);
  useEffect(
    () => () => {
      appliedRef.current = null;
      ctx?.setCrumbs(null);
    },
    [ctx],
  );
}

/**
 * The route-derived link tree, for the pages whose trail the
 * route alone can name: a settings section (Settings › section),
 * /help (Home › Help & Support), and the admin pages (Admin ›
 * page). Labels come from the same dictionaries and the same
 * module registry the pages themselves read — no second list.
 */
export function derivedCrumbs(
  pathname: string,
  t: (key: never) => string,
): Crumb[] | null {
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] === "settings" && seg[1]) {
    return [
      { label: t("shell.settings" as never), to: "/settings" },
      { label: t(`settings.section.${seg[1]}` as never) },
    ];
  }
  if (pathname === "/help") {
    return [
      { label: t("nav.core" as never), to: "/" },
      { label: t("help.title" as never) },
    ];
  }
  if (seg[0] === "admin" && seg[1]) {
    const mod = MODULES.find((m) => m.path === pathname);
    if (mod) {
      return [
        { label: "Admin", to: "/admin" },
        { label: mod.label.replace(/^Admin · /, "") },
      ];
    }
  }
  return null;
}
