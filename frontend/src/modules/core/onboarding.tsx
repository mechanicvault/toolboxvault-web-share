import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";

import { Button, ProgressBar } from "../../components";
import { api } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { groupLayerWaived } from "./accountTypes";
import { useAuth, type User } from "./AuthContext";
import { useMyModules } from "./MyModules";
import { sectionVisibleFor, SETTINGS_SECTIONS } from "./settingsMeta";
import "./onboarding.css";

/**
 * Onboarding wizard system — client half (owner design
 * 2026-10-31, built 2026-11-07).
 *
 * The server plan (GET /core/onboarding) owns the probe steps
 * (account type, basics — read off the account itself) and the
 * module steps (the module-control registry's own read). This
 * module assembles the full pass by merging the settings steps
 * from the frontend settings registry (SETTINGS_SECTIONS — the
 * same registry Settings renders), so the wizard's step list is
 * derived from the site's registries on both sides, never a
 * hard-coded script. Progress rows are the only state; every
 * step writes through the real settings machinery.
 */

export interface OnboardingServerStep {
  key: string;
  kind: string;
  module_id?: string | null;
  status: string;
  new?: boolean;
}

export interface OnboardingPlan {
  flow: "wizard" | "existing" | "legacy";
  dismissed: boolean;
  steps: OnboardingServerStep[];
  progress: Record<string, string>;
  new_feature_modules: string[];
  resolved: number;
  total: number;
}

export type WizardStepKind =
  | "account_type"
  | "basics"
  | "modules"
  | "module"
  | "setting";

export interface WizardStep {
  key: string;
  kind: WizardStepKind;
  status: "done" | "skipped" | "pending" | "notified";
  moduleId?: string;
  sectionId?: string;
  isNew?: boolean;
}

const RESOLVED = new Set(["done", "skipped"]);

export function stepResolved(step: WizardStep): boolean {
  return RESOLVED.has(step.status);
}

/* The group-waived predicate lives in accountTypes (a leaf
 * module) so every surface — wizard, settings sections, home
 * blocks — reads the one definition without import cycles;
 * re-exported here for this module's existing consumers. */
export { groupLayerWaived };

/**
 * Assemble the pass for this account, in the design's order:
 * account type → basics → the settings walk (registry order,
 * group-gated) → modules → sharing defaults last.
 *
 * `modules` is the caller's effective module set (the nav's own
 * authority) when the caller has it: the settings walk follows
 * reach (owner ruling, 2026-11-09) — a module's settings are
 * not a step for an account that can't reach the module, the
 * same filtering the Settings page applies. Callers without
 * the read pass nothing and get the group gates alone.
 *
 * A group-waived account (groupLayerWaived) assembles the
 * bare-minimum pass instead: no account-type step (it has no
 * type to pick, and the step's copy enumerates the hidden
 * site) and no aggregate modules step (its module world is
 * operator-set, not a pick — the switches live in Settings →
 * Modules). Basics, the reach-filtered walk, and any NEW
 * module steps a release flip lit for it assemble exactly as
 * for anyone — that per-module step is the one sanctioned way
 * its wizard grows.
 */
export function assembleWizardSteps(
  user: User,
  plan: OnboardingPlan,
  modules?: ReadonlySet<string>,
): WizardStep[] {
  const serverByKey = new Map(plan.steps.map((s) => [s.key, s]));
  const steps: WizardStep[] = [];
  const probe = (key: "account_type" | "basics"): WizardStep => ({
    key,
    kind: key,
    status:
      serverByKey.get(key)?.status === "done" ? "done" : "pending",
  });

  if (plan.flow === "existing") {
    // A settled account's hub lists only what is genuinely new
    // (the server also returns its baseline modules as plain
    // steps — those are its settled state, not prompts).
    for (const s of plan.steps) {
      if (s.kind === "module" && s.new) {
        steps.push({
          key: s.key,
          kind: "module",
          moduleId: s.module_id ?? undefined,
          status: "notified",
          isNew: true,
        });
      }
    }
    return steps;
  }
  if (plan.flow !== "wizard") return steps;

  const waived = groupLayerWaived(user);
  if (!waived) steps.push(probe("account_type"));
  steps.push(probe("basics"));

  const siteSections = SETTINGS_SECTIONS.filter(
    (s) =>
      s.group === "site" &&
      sectionVisibleFor(s, user.account_types, modules, waived),
  );
  for (const section of siteSections) {
    if (section.id === "modules" || section.id === "sharing") continue;
    steps.push({
      key: `setting:${section.id}`,
      kind: "setting",
      sectionId: section.id,
      status:
        (plan.progress[`setting:${section.id}`] as WizardStep["status"]) ??
        "pending",
    });
  }

  const moduleSteps = plan.steps.filter((s) => s.kind === "module");
  // A step the release machinery marked "notified" (a tier flip
  // wrote the pending row — module_release.py) is a NEW feature
  // for this account even inside the first pass: it stands as
  // its own step, never folded into the aggregate below.
  const isNewStep = (s: OnboardingServerStep): boolean =>
    !!s.new || s.status === "notified";
  const firstPass = moduleSteps.filter((s) => !isNewStep(s));
  // A group-waived account gets no aggregate modules step: the
  // step is a pick among group-entitled modules, and its world
  // is lit by the operator instead. (Its entitled module rows
  // stay server-side only; a release flip's NEW steps below
  // still assemble individually.)
  if (!waived && firstPass.length > 0) {
    const doneCount = firstPass.filter((s) => s.status === "done").length;
    const resolvedCount = firstPass.filter((s) =>
      RESOLVED.has(s.status),
    ).length;
    steps.push({
      key: "modules",
      kind: "modules",
      status:
        resolvedCount === firstPass.length
          ? doneCount > 0
            ? "done"
            : "skipped"
          : "pending",
    });
  }
  for (const s of moduleSteps) {
    if (!isNewStep(s)) continue;
    steps.push({
      key: s.key,
      kind: "module",
      moduleId: s.module_id ?? undefined,
      status: "notified",
      isNew: true,
    });
  }

  const sharing = siteSections.find((s) => s.id === "sharing");
  if (sharing) {
    steps.push({
      key: "setting:sharing",
      kind: "setting",
      sectionId: "sharing",
      status:
        (plan.progress["setting:sharing"] as WizardStep["status"]) ??
        "pending",
    });
  }
  return steps;
}

export function stepTitle(step: WizardStep, t: (key: never) => string): string {
  switch (step.kind) {
    case "account_type":
      return t("setup.accountType.title" as never);
    case "basics":
      return t("setup.basics.title" as never);
    case "modules":
      return t("setup.modules.title" as never);
    case "module":
      return t(`modules.name.${step.moduleId}` as never);
    case "setting":
      return t(`settings.section.${step.sectionId}` as never);
  }
}

// -- context -----------------------------------------------------

interface OnboardingContextValue {
  plan: OnboardingPlan | null;
  /** True until the first plan read for the current account settles. */
  loading: boolean;
  refresh: () => Promise<OnboardingPlan | null>;
  setProgress: (stepKey: string, status: "done" | "skipped") => Promise<void>;
  dismiss: () => Promise<void>;
  reopen: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [plan, setPlan] = useState<OnboardingPlan | null>(null);
  // Which account the settled state belongs to. "Loading" is
  // DERIVED from it (a signed-in account whose plan hasn't
  // settled yet) — a bare boolean gets consumed by the
  // signed-out read and then reads "settled" for the split
  // second between login and the account's own fetch, which
  // once let the classic gate fire on a wizard account.
  const [planFor, setPlanFor] = useState<string | null>(null);
  const userId = user?.id ?? null;
  const loading = userId !== null && planFor !== userId;

  const refresh = useCallback(async (): Promise<OnboardingPlan | null> => {
    if (!userId) {
      setPlan(null);
      return null;
    }
    try {
      const next = await api<OnboardingPlan>("/core/onboarding");
      setPlan(next);
      return next;
    } catch {
      // A failed read must never wedge the shell: no plan reads
      // as "not the wizard flow" and the legacy gate applies.
      setPlan(null);
      return null;
    } finally {
      setPlanFor(userId);
    }
  }, [userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const post = useCallback(
    async (path: string, body?: unknown) => {
      const next = await api<OnboardingPlan>(path, {
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      setPlan(next);
      if (userId) setPlanFor(userId);
    },
    [userId],
  );

  const value = useMemo<OnboardingContextValue>(
    () => ({
      plan,
      loading,
      refresh,
      setProgress: (stepKey, status) =>
        post("/core/onboarding/progress", { step_key: stepKey, status }),
      dismiss: () => post("/core/onboarding/dismiss"),
      reopen: () => post("/core/onboarding/reopen"),
    }),
    [plan, loading, refresh, post],
  );
  return (
    <OnboardingContext.Provider value={value}>
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboarding(): OnboardingContextValue {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used inside OnboardingProvider");
  return ctx;
}

// -- banner --------------------------------------------------------

/**
 * The Home banner (design §3/§6): noticeable, across the top of
 * Home, until the pass is finished or waived. For settled
 * accounts it speaks only when a new feature lands. Renders
 * nothing while the plan is unknown.
 */
export function SetupBanner() {
  const t = useT();
  const { user } = useAuth();
  const { plan, dismiss } = useOnboarding();
  const { modules: effectiveModules } = useMyModules();
  const [waiving, setWaiving] = useState(false);
  if (!user || !plan || plan.dismissed) return null;

  const steps = assembleWizardSteps(
    user,
    plan,
    effectiveModules
      ? new Set(effectiveModules.map((m) => m.id))
      : undefined,
  );
  const remaining = steps.filter((s) => !stepResolved(s));
  const newFeature = plan.new_feature_modules.length > 0;

  if (plan.flow === "wizard" && remaining.length > 0) {
    const doneCount = steps.length - remaining.length;
    // A group-waived account never picks a type, so its
    // "started" reads off the pass itself — and its banner
    // body names only the bare-minimum pass it actually gets,
    // never the types/modules/sharing it can't reach.
    const waived = groupLayerWaived(user);
    const started = waived
      ? doneCount > 0
      : user.account_types.length > 0;
    const ctaKey = (
      started ? "setup.banner.resume" : "setup.banner.cta"
    ) as never;
    return (
      <div className="tv-setup-banner" role="region" aria-label={t("setup.banner.title" as never)}>
        <div className="tv-setup-banner-main">
          <strong>{t("setup.banner.title" as never)}</strong>
          <p>{t((waived ? "setup.banner.bodyBare" : "setup.banner.body") as never)}</p>
          {doneCount > 0 && (
            <p className="tv-setup-banner-progress">
              {t("setup.progress.of" as never)
                .replace("{done}", String(doneCount))
                .replace("{total}", String(steps.length))}
            </p>
          )}
        </div>
        <div className="tv-setup-banner-actions">
          <Link className="tv-setup-banner-cta" to="/setup">
            {t(ctaKey)}
          </Link>
          <Button
            variant="ghost"
            size="sm"
            loading={waiving}
            onClick={() => {
              if (!window.confirm(t("setup.dismissConfirm" as never))) return;
              setWaiving(true);
              void dismiss().finally(() => setWaiving(false));
            }}
          >
            {t("setup.banner.dismiss" as never)}
          </Button>
        </div>
      </div>
    );
  }

  if (newFeature) {
    return (
      <div className="tv-setup-banner" role="region" aria-label={t("setup.banner.newFeature" as never)}>
        <div className="tv-setup-banner-main">
          <strong>{t("setup.banner.newFeature" as never)}</strong>
          <p>{t("setup.banner.newFeatureBody" as never)}</p>
        </div>
        <div className="tv-setup-banner-actions">
          <Link className="tv-setup-banner-cta" to="/setup">
            {t("setup.banner.newFeatureCta" as never)}
          </Link>
          <Button
            variant="ghost"
            size="sm"
            loading={waiving}
            onClick={() => {
              setWaiving(true);
              void dismiss().finally(() => setWaiving(false));
            }}
          >
            {t("setup.banner.dismiss" as never)}
          </Button>
        </div>
      </div>
    );
  }
  return null;
}

// -- progress panel -------------------------------------------------

/**
 * The setup control panel (design §6): what's done, how far
 * along, what remains. Shared by the wizard page and the
 * Settings → Account setup section.
 */
export function SetupProgressPanel({
  steps,
  activeKey,
  onSelect,
}: {
  steps: WizardStep[];
  activeKey?: string;
  onSelect?: (step: WizardStep) => void;
}) {
  const t = useT();
  const done = steps.filter((s) => stepResolved(s)).length;
  const chip = (step: WizardStep): string =>
    step.isNew
      ? t("setup.step.new" as never)
      : step.status === "done"
        ? t("setup.step.done" as never)
        : step.status === "skipped"
          ? t("setup.step.skipped" as never)
          : t("setup.step.todo" as never);
  return (
    <div className="tv-setup-progress">
      <h2 className="tv-setup-progress-title">
        {t("setup.progress.title" as never)}
      </h2>
      <ProgressBar
        value={steps.length ? (done / steps.length) * 100 : 100}
        label={
          steps.length === 0
            ? t("setup.progress.allDone" as never)
            : t("setup.progress.of" as never)
                .replace("{done}", String(done))
                .replace("{total}", String(steps.length))
        }
      />
      <p className="tv-setup-progress-count">
        {steps.length === 0 || done === steps.length
          ? t("setup.progress.allDone" as never)
          : t("setup.progress.of" as never)
              .replace("{done}", String(done))
              .replace("{total}", String(steps.length))}
      </p>
      <ol className="tv-setup-progress-list">
        {steps.map((step) => {
          const row = (
            <>
              <span className="tv-setup-progress-name">
                {stepTitle(step, t)}
              </span>
              <span
                className={`tv-setup-chip tv-setup-chip--${step.isNew ? "new" : step.status}`}
              >
                {chip(step)}
              </span>
            </>
          );
          return (
            <li key={step.key}>
              {onSelect ? (
                <button
                  type="button"
                  className={`tv-setup-progress-row${step.key === activeKey ? " is-active" : ""}`}
                  onClick={() => onSelect(step)}
                >
                  {row}
                </button>
              ) : (
                <div className="tv-setup-progress-row">{row}</div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
