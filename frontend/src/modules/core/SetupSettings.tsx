import { useNavigate } from "react-router-dom";

import { Button, Panel, Spinner } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { useAuth } from "./AuthContext";
import { useMyModules } from "./MyModules";
import {
  assembleWizardSteps,
  SetupProgressPanel,
  stepResolved,
  useOnboarding,
} from "./onboarding";

/**
 * SETTINGS → ACCOUNT → ACCOUNT SETUP: the onboarding wizard's
 * permanent home. The wizard itself is a guided pass, not a
 * settings store — this section shows where the pass stands
 * (the same progress panel the wizard carries) and reopens it.
 * Reopening also un-dismisses the Home banner, so a waved-off
 * setup can be picked back up from here at any time.
 */
export default function SetupSettings() {
  const t = useT();
  const { user } = useAuth();
  const { plan, loading, reopen } = useOnboarding();
  const { modules: effectiveModules } = useMyModules();
  const navigate = useNavigate();

  if (!user) return null;
  if (loading && !plan) {
    return (
      <Panel title={t("settings.section.setup" as never)} variant="plate">
        <Spinner />
      </Panel>
    );
  }
  if (!plan) return null;

  const steps = assembleWizardSteps(
    user,
    plan,
    effectiveModules
      ? new Set(effectiveModules.map((m) => m.id))
      : undefined,
  );
  const remaining = steps.filter((s) => !stepResolved(s)).length;

  return (
    <Panel title={t("settings.section.setup" as never)} variant="plate">
      <div className="tv-settings-stack">
        {remaining === 0 ? (
          <p className="tv-settings-intro">
            {t("setup.settingsSection.done" as never)}
          </p>
        ) : (
          <p className="tv-settings-intro">
            {t("setup.settingsSection.remaining" as never).replace(
              "{count}",
              String(remaining),
            )}
          </p>
        )}
        {plan.dismissed && (
          <p className="tv-settings-intro">
            {t("setup.settingsSection.dismissed" as never)}
          </p>
        )}
        <SetupProgressPanel steps={steps} />
        <div>
          <Button
            onClick={() => {
              void reopen().then(() => navigate("/setup"));
            }}
          >
            {t("setup.settingsSection.open" as never)}
          </Button>
        </div>
      </div>
    </Panel>
  );
}
