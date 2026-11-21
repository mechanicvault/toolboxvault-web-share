import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button, EmptyState, LinkButton, Panel, Spinner } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api } from "../../lib/api";
import { useAuth } from "./AuthContext";
import { fetchLandingConfigShared, type LandingConfig } from "./landing";

/**
 * My modules (module doctrine, owner 2026-10-18): the frontend half
 * of the module control system. GET /api/core/my-modules returns the
 * feature modules effective for the signed-in user RIGHT NOW — the
 * operator's global switch + per-group assignment + the dependency
 * graph, already resolved server-side. The nav, the home Modules
 * tiles, module-owned overview stats, and direct-route guards all
 * consume this one hook, so a switch flipped in /admin/modules shows
 * up everywhere on the next load.
 *
 * Per-user switches (2026-10-24): a second feed,
 * GET /api/core/my-module-prefs, carries every module the user's
 * groups entitle with the user's own on/off choice resolved on top
 * (operator layer first, user layer second). my-modules already
 * EXCLUDES anything the user turned off, so existing consumers get
 * the hiding for free; prefs exist so surfaces can tell "not
 * entitled" apart from "entitled but I turned it off" — the second
 * gets the friendly turned-off panel and the Settings → Modules
 * switches, never the operator dead-end.
 *
 * While either answer is loading, consumers render NO module items —
 * never a guess that might flash the wrong menu. Signed out, there
 * are no modules (and no fetch).
 */

export interface EffectiveModuleNav {
  label: string;
  path: string;
  order: number;
}

export interface EffectiveModule {
  id: string;
  name: string;
  description: string;
  provides: string[];
  depends_on: string[];
  nav: EffectiveModuleNav | null;
}

/** One row of GET /api/core/my-module-prefs: a module the user's
 *  groups entitle, with the user's own switch resolved on top.
 *  `visible` is the bottom line — false when the user turned the
 *  module off OR when a dependency they turned off blocks it
 *  (`blocked_by` names that dependency). */
export interface ModulePref {
  id: string;
  name: string;
  label: string;
  description: string;
  nav: EffectiveModuleNav | null;
  /** False for the always-on core (inventory, support): no switch. */
  switchable: boolean;
  user_enabled: boolean;
  visible: boolean;
  blocked_by: string | null;
}

/** One row of GET /api/core/module-options?groups=… (public): what
 *  a hypothetical account holding those groups would be entitled
 *  to — the signup module step renders these. */
export interface ModuleOption {
  id: string;
  name: string;
  label: string;
  description: string;
  nav: EffectiveModuleNav | null;
  switchable: boolean;
}

interface MyModulesValue {
  /** Null while the first fetch is in flight (or signed out). */
  modules: EffectiveModule[] | null;
  loading: boolean;
  has: (moduleId: string) => boolean;
  /** Null while the first prefs fetch is in flight (or signed out). */
  prefs: ModulePref[] | null;
  prefsLoading: boolean;
  /** True when the user is entitled to the module but it is hidden
   *  by their own switch — directly, or by cascade through a
   *  dependency they turned off. Always-on modules never count. */
  isUserOff: (moduleId: string) => boolean;
  /** Refetch BOTH feeds (after a switch flip). Existing data stays
   *  on screen while the refetch runs — no loading flash. */
  refresh: () => void;
}

const MyModulesContext = createContext<MyModulesValue>({
  modules: null,
  loading: false,
  has: () => false,
  prefs: null,
  prefsLoading: false,
  isUserOff: () => false,
  refresh: () => {},
});

export function MyModulesProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [modules, setModules] = useState<EffectiveModule[] | null>(null);
  const [prefs, setPrefs] = useState<ModulePref[] | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  // Whose data is on screen: a DIFFERENT user signing in clears to
  // the loading state; a same-user refresh() keeps the current data
  // visible until the new answer lands.
  const dataUserRef = useRef<string | null>(null);

  const refresh = useCallback(() => setRefreshTick((n) => n + 1), []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      dataUserRef.current = null;
      setModules(null);
      setPrefs(null);
      return;
    }
    if (dataUserRef.current !== user.id) {
      dataUserRef.current = user.id;
      setModules(null);
      setPrefs(null);
    }
    let live = true;
    api<EffectiveModule[]>("/core/my-modules")
      .then((data) => {
        if (live) setModules(data);
      })
      .catch(() => {
        // A failed fetch must not invent access: no module items.
        if (live) setModules([]);
      });
    api<ModulePref[]>("/core/my-module-prefs")
      .then((data) => {
        if (live) setPrefs(data);
      })
      .catch(() => {
        // Same rule: a failed prefs fetch invents no switches —
        // an empty list reads as "nothing is user-off".
        if (live) setPrefs([]);
      });
    return () => {
      live = false;
    };
  }, [user, authLoading, refreshTick]);

  const value = useMemo<MyModulesValue>(() => {
    const list = modules;
    const prefList = prefs;
    return {
      modules: list,
      loading: !!user && list === null,
      has: (moduleId) => !!list?.some((m) => m.id === moduleId),
      prefs: prefList,
      prefsLoading: !!user && prefList === null,
      isUserOff: (moduleId) => {
        const pref = prefList?.find((p) => p.id === moduleId);
        return !!pref && pref.switchable && !pref.visible;
      },
      refresh,
    };
  }, [modules, prefs, user, refresh]);

  return (
    <MyModulesContext.Provider value={value}>{children}</MyModulesContext.Provider>
  );
}

export function useMyModules(): MyModulesValue {
  return useContext(MyModulesContext);
}

/** The clean dead-end shown when a module isn't effective for the
 *  signed-in user — a direct link, a bookmark, a stale tab. Never a
 *  crash, never a blank page, never the module's own UI. */
export function ModuleUnavailablePanel({ moduleLabel }: { moduleLabel: string }) {
  return (
    <Panel>
      <EmptyState
        title="This module isn't enabled for your account"
        description={`${moduleLabel} is switched off for your account groups right now. If that looks wrong, it can be changed by the site operator — nothing about your data has changed.`}
      />
    </Panel>
  );
}

/**
 * The friendly landing for a module the user THEMSELVES turned off
 * (per-user switches, 2026-10-24) — a direct link or a stale tab
 * lands here, not on an error. Turning it back on is one tap, right
 * here; when the module is only hidden because a dependency is off
 * (blocked_by), the button turns the BLOCKING module back on
 * instead, which restores both.
 */
export function TurnedOffPanel({
  moduleId,
  moduleLabel,
}: {
  moduleId: string;
  moduleLabel: string;
}) {
  const t = useT();
  const { prefs, refresh } = useMyModules();
  const [busy, setBusy] = useState(false);
  const pref = prefs?.find((p) => p.id === moduleId);
  // Fresh prefs end the busy state: either the gate above swaps
  // this panel for the page (unmount), or the panel re-renders
  // against the new answer and the button must be usable again.
  useEffect(() => {
    setBusy(false);
  }, [prefs]);
  const blockedBy = pref?.blocked_by ?? null;
  const blockerName = blockedBy
    ? t(`modules.name.${blockedBy}` as never)
    : moduleLabel;
  const body = blockedBy
    ? t("moduleOff.bodyBlocked").replace(/\{name\}/g, blockerName)
    : t("moduleOff.body");

  async function turnOn() {
    setBusy(true);
    try {
      await api(`/core/my-modules/${blockedBy ?? moduleId}`, {
        method: "PUT",
        body: JSON.stringify({ enabled: true }),
      });
      // The refresh swaps this panel for the page (or for the
      // still-blocked state, if anything else is off) — the busy
      // state rides along until the new prefs land.
      refresh();
    } catch {
      setBusy(false);
    }
  }

  return (
    <Panel>
      <EmptyState
        title={t("moduleOff.title")}
        description={body}
        action={
          <div className="tv-module-off-actions">
            <Button onClick={() => void turnOn()} loading={busy}>
              {blockedBy
                ? t("moduleOff.turnOnNamed").replace("{name}", blockerName)
                : t("moduleOff.turnOn")}
            </Button>
            <LinkButton to="/settings/modules" variant="secondary">
              {t("moduleOff.goSettings")}
            </LinkButton>
          </div>
        }
      />
    </Panel>
  );
}

/** The shared loading line both gates render — one look, so a page
 *  never flashes two different spinners back to back. */
function GateSpinner() {
  return (
    <p
      style={{
        color: "var(--text-muted)",
        display: "flex",
        gap: "var(--space-2)",
        alignItems: "center",
      }}
    >
      <Spinner size="sm" /> Loading…
    </p>
  );
}

/**
 * Route guard for feature-module pages. Signed-out visitors pass
 * straight through (the page's own RequireAuth handles the login
 * redirect, exactly as before); signed-in users see a spinner while
 * their modules load, the page when the module is effective, and a
 * dead-end panel when it isn't — the friendly turned-off panel when
 * the user is entitled but switched it off themselves, the operator
 * panel when their groups never entitled them at all.
 */
export function ModuleGate({
  module,
  modules,
  moduleLabel,
  children,
}: {
  module: string;
  /** Two-seat routes: render while ANY listed module is effective. */
  modules?: string[];
  moduleLabel: string;
  children: ReactNode;
}) {
  const { user, loading: authLoading } = useAuth();
  const { loading, prefsLoading, has, prefs } = useMyModules();

  if (!user && !authLoading) return <>{children}</>;
  if (authLoading || loading || prefsLoading) {
    return <GateSpinner />;
  }
  const seatModules = modules && modules.length > 0 ? modules : [module];
  if (!seatModules.some((m) => has(m))) {
    const offSeat = seatModules.find((m) =>
      prefs?.some((p) => p.id === m),
    );
    if (offSeat) {
      return <TurnedOffPanel moduleId={offSeat} moduleLabel={moduleLabel} />;
    }
    return <ModuleUnavailablePanel moduleLabel={moduleLabel} />;
  }
  return <>{children}</>;
}

/** Public-family modules whose OPERATOR-park state the anonymous
 *  landing payload already publishes (usable-anywhere flags —
 *  core/landing.py): while the flag reads false the module is
 *  parked site-wide, and its public routes land on the standard
 *  not-enabled panel for signed-in users too (hidden-modules
 *  directive, 2026-10-31). Family modules without a flag keep the
 *  original posture below — extend this map when one is parked. */
const PARK_FLAGS: Record<string, (config: LandingConfig) => boolean> = {
  parts: (config) => config.community_parts_enabled,
  marketplace: (config) => config.marketplace_enabled,
};

/**
 * Route guard for the PUBLIC module family (parts pool, marketplace
 * board, forum, feedback, dealer find-an-agent): those routes carry
 * no featureModule, so signed-out visitors and entitled users pass
 * straight through this gate, and only a signed-in user who turned
 * the module off themselves gets the turned-off panel. (Feedback
 * stays in this family for the gate's purposes; its PAGES carry
 * their own members-only door for signed-out visitors since
 * 2026-11-10.) An operator-parked family module (PARK_FLAGS) lands
 * on the not-enabled panel instead: parked means parked, for
 * every seat.
 */
export function UserOffGate({
  module,
  moduleLabel,
  children,
}: {
  module: string;
  moduleLabel: string;
  children: ReactNode;
}) {
  const { user, loading: authLoading } = useAuth();
  const { loading, prefsLoading, isUserOff } = useMyModules();
  const parkFlag = PARK_FLAGS[module];
  const [landing, setLanding] = useState<LandingConfig | null>(null);
  useEffect(() => {
    if (!parkFlag) return;
    let live = true;
    void fetchLandingConfigShared().then((config) => {
      if (live) setLanding(config);
    });
    return () => {
      live = false;
    };
  }, [parkFlag]);

  if (!user && !authLoading) return <>{children}</>;
  if (authLoading || loading || prefsLoading) {
    return <GateSpinner />;
  }
  if (parkFlag) {
    if (landing === null) return <GateSpinner />;
    if (!parkFlag(landing)) {
      return <ModuleUnavailablePanel moduleLabel={moduleLabel} />;
    }
  }
  if (isUserOff(module)) {
    return <TurnedOffPanel moduleId={module} moduleLabel={moduleLabel} />;
  }
  return <>{children}</>;
}
