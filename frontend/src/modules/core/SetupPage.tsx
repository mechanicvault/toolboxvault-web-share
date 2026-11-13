import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Button,
  FormField,
  LinkButton,
  Panel,
  Select,
  Spinner,
  Toggle,
  useToast,
} from "../../components";
import { api, ApiError } from "../../lib/api";
import { usePageCrumbs } from "../../lib/navTrail";
import { useT } from "../../i18n/LocaleContext";
import { AccentSwatches } from "../../theme/AccentDots";
import type { AccountType } from "./accountTypes";
import { useAuth } from "./AuthContext";
import { GroupPicker } from "./auth/GroupPicker";
import { RequireAuth } from "./auth/RequireAuth";
import ModulesSettings from "./ModulesSettings";
import { useMyModules } from "./MyModules";
import {
  assembleWizardSteps,
  groupLayerWaived,
  SetupProgressPanel,
  stepResolved,
  useOnboarding,
  type WizardStep,
} from "./onboarding";
import { settingsSectionById } from "./settingsRegistry";
import "./settings.css";

/**
 * ACCOUNT SETUP — the onboarding wizard's hub (owner design
 * 2026-10-31, built 2026-11-07).
 *
 * One page in the main-tab-layout family: a header panel (brand
 * thumb, title, the account's facts), the setup control panel on
 * the left (progress + the step list — what's done, how far
 * along, what remains), and the current step on the right. The
 * step list is assembled from the site's registries (see
 * onboarding.tsx): account type and basics are probe steps over
 * the account itself; settings steps render the Settings
 * sections' OWN components; the modules step renders the
 * Settings → Modules switches. Nothing here keeps a private copy
 * of any setting — the wizard is a guided path over Settings,
 * and every write lands in the same machinery.
 *
 * Every step but one can be skipped and the pass resumed:
 * progress is server-held, so leaving and returning lands on
 * the first unfinished step. The exception is ACCOUNT TYPE,
 * which is REQUIRED (owner ruling 2026-11-07): you can't pick
 * available modules without an account type — a mechanic can't
 * pick dealer modules — so the type step carries no Skip,
 * Continue blocks until a type is picked, and the settings
 * walk and modules steps stay locked until one exists. Trying
 * to enter a locked step (panel click, deep link, advancing
 * past basics) routes back to the type step with the reason
 * shown. The server holds the same line: progress writes for
 * settings/module steps are refused while an account is
 * typeless, and the module-switch API refuses typeless writes.
 *
 * A group-waived account (onboarding.tsx's groupLayerWaived —
 * the downloads level) never meets any of this: its assembly
 * carries no account-type step and no aggregate modules step,
 * so the lock below finds no type step to derive from and
 * nothing is locked — its pass is basics, the reach-filtered
 * settings walk, and any NEW module step a release flip lit,
 * each recordable because the server's refusal keys on the
 * same waiver.
 */

function StepFooter({
  onBack,
  backDisabled,
  onSkip,
  onContinue,
  continueDisabled,
  busy,
  isLast,
}: {
  onBack?: () => void;
  backDisabled?: boolean;
  onSkip?: () => void;
  onContinue: () => void;
  continueDisabled?: boolean;
  busy?: boolean;
  isLast?: boolean;
}) {
  const t = useT();
  return (
    <div className="tv-setup-actions">
      {onBack && (
        <Button variant="ghost" onClick={onBack} disabled={backDisabled || busy}>
          {t("setup.back" as never)}
        </Button>
      )}
      <span className="tv-setup-actions-spacer" />
      {onSkip && (
        <Button variant="ghost" onClick={onSkip} disabled={busy}>
          {t("setup.skip" as never)}
        </Button>
      )}
      <Button onClick={onContinue} loading={busy} disabled={continueDisabled}>
        {t(isLast ? "setup.finish" : "setup.continue" as never)}
      </Button>
    </div>
  );
}

function ExampleBox({ text }: { text: string }) {
  const t = useT();
  return (
    <div className="tv-setup-example">
      <span className="tv-setup-example-label">
        {t("setup.example.label" as never)}
      </span>
      <p>{text}</p>
    </div>
  );
}

// -- step bodies ---------------------------------------------------

function AccountTypeStep({
  step,
  advance,
  goBack,
  isLast,
  lockNotice,
}: StepNav & { lockNotice?: boolean }) {
  const t = useT();
  const { user, refreshUser } = useAuth();
  const [picked, setPicked] = useState<AccountType[]>(
    () => (user?.account_types ?? []) as AccountType[],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  void step;

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/core/account-type", {
        method: "POST",
        body: JSON.stringify({ account_types: picked }),
      });
      await refreshUser();
      advance();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("setup.accountType.needOne" as never));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tv-setup-step">
      <h2>{t("setup.accountType.title" as never)}</h2>
      <p className="tv-setup-intro">{t("setup.accountType.intro" as never)}</p>
      {lockNotice && <Alert>{t("setup.locked.body" as never)}</Alert>}
      <GroupPicker value={picked} onChange={setPicked} name="setup-groups" />
      <ExampleBox text={t("setup.accountType.example" as never)} />
      {picked.length === 0 && (
        <p className="tv-setup-hint">{t("setup.accountType.needOne" as never)}</p>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {/* No Skip on this step — the one required pick of the
          pass (owner ruling 2026-11-07). Continue stays
          disabled until at least one type is picked, and the
          needOne line above the footer says why. */}
      <StepFooter
        onBack={goBack}
        onContinue={() => void save()}
        continueDisabled={picked.length === 0}
        busy={busy}
        isLast={isLast}
      />
    </div>
  );
}

function BasicsStep({ advance, goBack, isLast }: StepNav) {
  const t = useT();
  const { user, refreshUser } = useAuth();
  const [country, setCountry] = useState(user?.country || "US");
  const [currency, setCurrency] = useState(user?.currency || "USD");
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [locale, setLocale] = useState(
    user?.locale === "es" ? "es" : "en",
  );
  const [countries, setCountries] = useState<{ code: string; label: string }[]>([]);
  const [currencies, setCurrencies] = useState<string[]>([]);
  const [countryCurrencies, setCountryCurrencies] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    void api<{
      countries: { code: string; label: string }[];
      currencies: string[];
      country_currencies: Record<string, string>;
    }>("/core/money/meta")
      .then((meta) => {
        if (!live) return;
        setCountries(meta.countries);
        setCurrencies(meta.currencies);
        setCountryCurrencies(meta.country_currencies);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  function onCountryChange(next: string) {
    setCountry(next);
    if (!currencyTouched) {
      const suggested = countryCurrencies[next];
      if (suggested) setCurrency(suggested);
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ country, currency, locale }),
      });
      await refreshUser();
      advance();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("auth.signup.pickBasics" as never));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tv-setup-step">
      <h2>{t("setup.basics.title" as never)}</h2>
      <p className="tv-setup-intro">{t("setup.basics.intro" as never)}</p>
      <div className="tv-setup-form">
        {countries.length > 0 && (
          <FormField label={t("auth.signup.country" as never)} htmlFor="setup-country" required>
            <Select
              id="setup-country"
              value={country}
              onChange={(e) => onCountryChange(e.target.value)}
            >
              <option value="">{t("auth.signup.selectCountry" as never)}</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {currencies.length > 0 && (
          <FormField label={t("auth.signup.currency" as never)} htmlFor="setup-currency" required>
            <Select
              id="setup-currency"
              value={currency}
              onChange={(e) => {
                setCurrencyTouched(true);
                setCurrency(e.target.value);
              }}
            >
              <option value="">{t("auth.signup.selectCurrency" as never)}</option>
              {currencies.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        <FormField label={t("auth.signup.language" as never)} htmlFor="setup-language" required>
          <Select
            id="setup-language"
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
          >
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </FormField>
        <FormField label={t("auth.signup.color" as never)} hint={t("auth.signup.colorHint" as never)}>
          <AccentSwatches />
        </FormField>
      </div>
      <ExampleBox text={t("setup.basics.example" as never)} />
      {error && <Alert tone="danger">{error}</Alert>}
      <StepFooter
        onBack={goBack}
        onSkip={() => advance()}
        onContinue={() => void save()}
        busy={busy}
        isLast={isLast}
      />
    </div>
  );
}

function SettingStep({ step, advance, goBack, isLast }: StepNav) {
  const t = useT();
  const { user } = useAuth();
  const { setProgress } = useOnboarding();
  const [busy, setBusy] = useState(false);
  const sectionId = step.sectionId!;
  const section = user
    ? settingsSectionById(user, sectionId, undefined, groupLayerWaived(user))
    : undefined;
  const sectionLabel = t(`settings.section.${sectionId}` as never);

  async function mark(status: "done" | "skipped") {
    setBusy(true);
    try {
      await setProgress(step.key, status);
      advance();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tv-setup-step">
      <h2>{sectionLabel}</h2>
      <p className="tv-setup-intro">
        {t("setup.settings.intro" as never).replace("{section}", sectionLabel)}
      </p>
      {user && section ? (
        <div className="tv-settings-content" data-settings-section={sectionId}>
          {section.render(user)}
        </div>
      ) : (
        <Spinner />
      )}
      <ExampleBox
        text={t(
          /* Group-waived accounts (wizard reach filter,
           * 2026-11-09) read the bare variants where a step's
           * example names features outside their reach — the
           * my-shop claims clause, the notifications claim /
           * ledger lines. Sections without a bare variant read
           * the same example as everyone. */
          (user &&
          groupLayerWaived(user) &&
          (sectionId === "my-shop" || sectionId === "notifications")
            ? `setup.example.${sectionId}-bare`
            : `setup.example.${sectionId}`) as never,
        )}
      />
      <StepFooter
        onBack={goBack}
        onSkip={() => void mark("skipped")}
        onContinue={() => void mark("done")}
        busy={busy}
        isLast={isLast}
      />
    </div>
  );
}

function ModulesStep({ advance, goBack, isLast }: StepNav) {
  const t = useT();
  const { plan, setProgress } = useOnboarding();
  const [busy, setBusy] = useState(false);

  async function mark(status: "done" | "skipped") {
    setBusy(true);
    try {
      const pending = (plan?.steps ?? []).filter(
        (s) => s.kind === "module" && !s.new && s.status !== "done" && s.status !== "skipped",
      );
      for (const s of pending) {
        await setProgress(s.key, status);
      }
      advance();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tv-setup-step">
      <h2>{t("setup.modules.title" as never)}</h2>
      <p className="tv-setup-intro">{t("setup.modules.intro" as never)}</p>
      <ModulesSettings />
      <ExampleBox text={t("setup.modules.example" as never)} />
      <StepFooter
        onBack={goBack}
        onSkip={() => void mark("skipped")}
        onContinue={() => void mark("done")}
        busy={busy}
        isLast={isLast}
      />
    </div>
  );
}

function NewModuleStep({ step, advance, goBack, isLast }: StepNav) {
  const t = useT();
  const { toast } = useToast();
  const { prefs, refresh } = useMyModules();
  const { setProgress } = useOnboarding();
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const pref = (prefs ?? []).find((p) => p.id === step.moduleId);
  const name = t(`modules.name.${step.moduleId}` as never);

  async function flip(enabled: boolean) {
    if (!pref) return;
    setSaving(true);
    try {
      await api(`/core/my-modules/${pref.id}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("shell.loading" as never), {
        tone: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function mark(status: "done" | "skipped") {
    setBusy(true);
    try {
      await setProgress(step.key, status);
      advance();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tv-setup-step">
      <h2>{t("setup.newFeature.title" as never).replace("{name}", name)}</h2>
      <p className="tv-setup-intro">{t("setup.newFeature.body" as never)}</p>
      {pref ? (
        <div className="tv-setting-row">
          <div className="tv-setting-row-main">
            <p className="tv-setting-row-name">{name}</p>
            <p className="tv-setting-row-desc">
              {t(`modules.desc.${pref.id}` as never)}
            </p>
          </div>
          <Toggle
            checked={pref.user_enabled}
            disabled={!pref.switchable || saving}
            onChange={(v) => void flip(v)}
            ariaLabel={name}
          />
        </div>
      ) : (
        <Spinner />
      )}
      <StepFooter
        onBack={goBack}
        onSkip={() => void mark("skipped")}
        onContinue={() => void mark("done")}
        busy={busy}
        isLast={isLast}
      />
    </div>
  );
}

interface StepNav {
  step: WizardStep;
  advance: () => void;
  goBack?: () => void;
  isLast?: boolean;
}

// -- the hub ---------------------------------------------------------

function SetupShell() {
  const t = useT();
  const { user } = useAuth();
  const { plan, loading, dismiss, refresh } = useOnboarding();
  const { modules: effectiveModules } = useMyModules();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [dismissing, setDismissing] = useState(false);
  const [lockNotice, setLockNotice] = useState(false);

  // The settings walk follows reach (2026-11-09): the wizard
  // never offers settings for a module this account can't use.
  const moduleIds = useMemo(
    () =>
      effectiveModules
        ? new Set(effectiveModules.map((m) => m.id))
        : undefined,
    [effectiveModules],
  );
  const steps = useMemo(
    () =>
      user && plan ? assembleWizardSteps(user, plan, moduleIds) : [],
    [user, plan, moduleIds],
  );
  const stepsRef = useRef(steps);
  stepsRef.current = steps;

  usePageCrumbs(
    user
      ? [
          { label: t("nav.core" as never), to: "/" },
          { label: t("setup.title" as never) },
        ]
      : null,
  );

  // The type lock (owner ruling 2026-11-07): while the account
  // has no types, the settings walk and the module steps are
  // locked — their contents are filtered by the account's
  // groups (sections gate on them; module entitlement is read
  // off them), so there is no honest list to show a typeless
  // account. Basics and the type step itself are never locked.
  const typePending =
    plan?.flow === "wizard" &&
    steps.some((s) => s.kind === "account_type" && s.status !== "done");
  const lockedKind = (kind: WizardStep["kind"]) =>
    kind === "setting" || kind === "modules" || kind === "module";
  const typeStepKey = steps.find((s) => s.kind === "account_type")?.key;

  // Arrival: the deep-linked step when given, else the first
  // unfinished step — the resume rule. Once the user picks a
  // step themselves, plan refreshes don't move them. A locked
  // arrival target bounces to the type step with the reason.
  useEffect(() => {
    if (currentKey && steps.some((s) => s.key === currentKey)) return;
    const wanted = searchParams.get("step");
    const found = steps.find((s) => s.key === wanted);
    const target =
      found ?? steps.find((s) => !stepResolved(s)) ?? steps[0];
    if (!target) return;
    // A downstream deep link can also name a step that doesn't
    // EXIST yet for a typeless account (the module steps are
    // built from the account's groups, so pre-pick there are
    // none): the resume rule below would land on the type step
    // silently. It is the same locked door — bounce with the
    // reason, exactly like a locked step that does exist.
    const wantedLocked =
      wanted !== null &&
      !found &&
      (wanted === "modules" ||
        wanted.startsWith("setting:") ||
        wanted.startsWith("module:"));
    if (typePending && typeStepKey && (lockedKind(target.kind) || wantedLocked)) {
      setLockNotice(true);
      setCurrentKey(typeStepKey);
      return;
    }
    setCurrentKey(target.key);
  }, [steps, currentKey, searchParams, typePending, typeStepKey]);

  if (!user) return null;
  if (loading && !plan) {
    return (
      <p className="tv-auth-inline-row">
        <Spinner size="sm" /> {t("shell.loading" as never)}
      </p>
    );
  }
  if (!plan) {
    return (
      <Alert tone="danger">{t("settings.modules.loadFailed" as never)}</Alert>
    );
  }

  if (plan.flow === "legacy") {
    // A pre-wizard account missing its bare bones keeps the
    // classic one-time completion door — untouched by design.
    return (
      <div className="tv-stack">
        <Panel>
          <h1 className="tv-settings-title">{t("setup.title" as never)}</h1>
          <p className="tv-setup-intro">{t("setup.legacy.body" as never)}</p>
          <LinkButton to="/choose-group">
            {t("setup.legacy.cta" as never)}
          </LinkButton>
        </Panel>
      </div>
    );
  }

  const index = steps.findIndex((s) => s.key === currentKey);
  const step = index >= 0 ? steps[index] : undefined;
  const resolved = steps.filter((s) => stepResolved(s)).length;

  async function advanceFrom(key: string) {
    if (key === "account_type") setLockNotice(false);
    // Re-read the plan BEFORE choosing the next step: the probe
    // steps (account type, basics) resolve on the server from
    // the account itself, and picking a type can ADD steps
    // (the module steps exist only once groups do). Advancing
    // on the pre-save step list could skip the modules step
    // entirely and leave the header's done-count stale.
    await refresh();
    // Let the refreshed plan render into stepsRef.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const list = stepsRef.current;
    const at = list.findIndex((s) => s.key === key);
    const next = list[at + 1];
    // Read the lock off the FRESH list: basics can be finished
    // before the type pick (deep link, panel click) and its
    // Continue must not walk a still-typeless account into the
    // locked settings walk — route back to the type step with
    // the reason instead. (Owner ruling 2026-11-07.)
    const stillTypeless = list.some(
      (s) => s.kind === "account_type" && s.status !== "done",
    );
    if (next && stillTypeless && lockedKind(next.kind)) {
      const type = list.find((s) => s.kind === "account_type");
      if (type) {
        setLockNotice(true);
        setCurrentKey(type.key);
        window.scrollTo({ top: 0 });
        return;
      }
    }
    if (next) {
      setCurrentKey(next.key);
      window.scrollTo({ top: 0 });
    } else {
      navigate("/", { replace: true });
    }
  }

  function goBackFrom(key: string) {
    const list = stepsRef.current;
    const at = list.findIndex((s) => s.key === key);
    const prev = list[at - 1];
    if (prev) {
      setCurrentKey(prev.key);
      window.scrollTo({ top: 0 });
    }
  }

  async function onDismiss() {
    if (!window.confirm(t("setup.dismissConfirm" as never))) return;
    setDismissing(true);
    try {
      await dismiss();
      navigate("/", { replace: true });
    } finally {
      setDismissing(false);
    }
  }

  const body = !step ? (
    <Panel>
      <p className="tv-setup-intro">
        {t("setup.progress.allDone" as never)}
      </p>
      <LinkButton to="/">{t("nav.core" as never)}</LinkButton>
    </Panel>
  ) : step.kind === "account_type" ? (
    <AccountTypeStep
      step={step}
      advance={() => advanceFrom(step.key)}
      goBack={index > 0 ? () => goBackFrom(step.key) : undefined}
      isLast={index === steps.length - 1}
      lockNotice={lockNotice}
    />
  ) : step.kind === "basics" ? (
    <BasicsStep
      step={step}
      advance={() => advanceFrom(step.key)}
      goBack={index > 0 ? () => goBackFrom(step.key) : undefined}
      isLast={index === steps.length - 1}
    />
  ) : step.kind === "modules" ? (
    <ModulesStep
      step={step}
      advance={() => advanceFrom(step.key)}
      goBack={index > 0 ? () => goBackFrom(step.key) : undefined}
      isLast={index === steps.length - 1}
    />
  ) : step.kind === "module" ? (
    <NewModuleStep
      step={step}
      advance={() => advanceFrom(step.key)}
      goBack={index > 0 ? () => goBackFrom(step.key) : undefined}
      isLast={index === steps.length - 1}
    />
  ) : (
    <SettingStep
      step={step}
      advance={() => advanceFrom(step.key)}
      goBack={index > 0 ? () => goBackFrom(step.key) : undefined}
      isLast={index === steps.length - 1}
    />
  );

  return (
    <div className="tv-stack">
      <Panel>
        <div className="tv-settings-head">
          <div className="tv-settings-thumb">
            <img src="/brand/logo-256.webp" alt="" className="tv-setup-thumb" />
          </div>
          <div className="tv-settings-head-main">
            <h1 className="tv-settings-title">{t("setup.title" as never)}</h1>
            <p className="tv-settings-subtitle">{user.name}</p>
            <dl className="tv-settings-facts">
              <div className="tv-settings-fact">
                <dt>{t("settings.accountNumber" as never)}</dt>
                <dd>{user.account_number}</dd>
              </div>
              <div className="tv-settings-fact">
                <dt>{t("setup.progress.title" as never)}</dt>
                <dd>
                  {t("setup.progress.of" as never)
                    .replace("{done}", String(resolved))
                    .replace("{total}", String(steps.length))}
                </dd>
              </div>
            </dl>
          </div>
        </div>
        <p className="tv-setup-subtitle">{t("setup.subtitle" as never)}</p>
      </Panel>

      <div className="tv-setup-layout">
        <Panel className="tv-setup-side">
          <SetupProgressPanel
            steps={steps}
            activeKey={step?.key}
            onSelect={(s) => {
              // A locked step's row routes to the type step
              // with the reason — the panel never opens a list
              // the account's types haven't shaped yet.
              if (typePending && lockedKind(s.kind) && typeStepKey) {
                setLockNotice(true);
                setCurrentKey(typeStepKey);
              } else {
                setCurrentKey(s.key);
              }
              window.scrollTo({ top: 0 });
            }}
          />
          <div className="tv-setup-side-actions">
            <Button
              variant="ghost"
              size="sm"
              loading={dismissing}
              onClick={() => void onDismiss()}
            >
              {t("setup.dismissSetup" as never)}
            </Button>
          </div>
        </Panel>
        <Panel className="tv-setup-main">{body}</Panel>
      </div>
      <p className="tv-setup-foot">
        <Link to="/help">{t("shell.help" as never)}</Link>
      </p>
    </div>
  );
}

export default function SetupPage() {
  return (
    <RequireAuth>
      <SetupShell />
    </RequireAuth>
  );
}
