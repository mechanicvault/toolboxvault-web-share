import { useState } from "react";

import {
  Alert,
  LinkButton,
  Panel,
  Spinner,
  Toggle,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "./AuthContext";
import { useMyModules, type ModulePref } from "./MyModules";

/**
 * SETTINGS → SITE SETTINGS → MODULES (per-user module switches,
 * owner directive 2026-10-24): every feature module the user's
 * groups entitle, one switch each. The list is the prefs feed the
 * MyModules provider already fetched — this section owns no fetch
 * of its own, so a flip here and the nav/home/search surfaces all
 * read the same refreshed state the moment the PUT lands.
 *
 * Flipping is instant and touches no data: off hides the module
 * everywhere for this user; on restores it exactly as it was.
 * Always-on modules (switchable=false — inventory, support) list
 * with a caption instead of a working switch, and a module hidden
 * only because a dependency is off says so and names the blocker.
 */
export default function ModulesSettings() {
  const t = useT();
  const { toast } = useToast();
  const { user } = useAuth();
  const { prefs, prefsLoading, refresh } = useMyModules();
  const [savingId, setSavingId] = useState<string | null>(null);

  const nameOf = (id: string) => t(`modules.name.${id}` as never);

  async function flip(pref: ModulePref, enabled: boolean) {
    setSavingId(pref.id);
    try {
      await api(`/core/my-modules/${pref.id}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      refresh();
      toast(
        (enabled
          ? t("settings.modules.savedOn")
          : t("settings.modules.savedOff")
        ).replace("{name}", nameOf(pref.id)),
        { tone: "success" },
      );
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't save that change. Try again.",
        { tone: "danger" },
      );
    } finally {
      setSavingId(null);
    }
  }

  // No account type, no module list (owner ruling 2026-11-07):
  // the prefs feed is legitimately EMPTY for a typeless account
  // — entitlement is read off the account's groups — so instead
  // of the load-failure reading below, route the account to the
  // setup wizard, whose first step is the type pick. (The
  // wizard's own modules step renders this component too, but
  // it is only reachable after the pick, so this branch never
  // fires there.)
  if (user && user.account_types.length === 0) {
    return (
      <Panel title={t("settings.modules.title")} variant="plate">
        <div className="tv-settings-stack">
          <p className="tv-settings-intro">
            {t("settings.modules.needType")}
          </p>
          <div>
            <LinkButton to="/setup">
              {t("setup.settingsSection.open")}
            </LinkButton>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title={t("settings.modules.title")} variant="plate">
      <div className="tv-settings-stack">
        <p className="tv-settings-intro">{t("settings.modules.intro")}</p>
        {prefsLoading ? (
          <Spinner />
        ) : !prefs || prefs.length === 0 ? (
          /* The provider reports a failed prefs fetch as an empty
           * list, and a real entitlement list is never empty — so
           * empty here means the load failed, same as null. */
          <Alert tone="danger">{t("settings.modules.loadFailed")}</Alert>
        ) : (
          <div>
            {prefs.map((pref) => (
              <div
                key={pref.id}
                className={`tv-setting-row${pref.switchable ? " is-clickable" : ""}`}
                onClick={
                  pref.switchable
                    ? (e) => {
                        /* The whole row drives its switch (the
                         * name/description were dead area beside
                         * it): forward to the switch itself so
                         * the disabled/saving states behave
                         * exactly as a direct switch click. */
                        if (
                          (e.target as HTMLElement).closest(
                            "button, a, input, select, textarea",
                          )
                        ) {
                          return;
                        }
                        e.currentTarget
                          .querySelector<HTMLButtonElement>(
                            '[role="switch"]',
                          )
                          ?.click();
                      }
                    : undefined
                }
              >
                <div className="tv-setting-row-main">
                  <p className="tv-setting-row-name">{nameOf(pref.id)}</p>
                  <p className="tv-setting-row-desc">
                    {t(`modules.desc.${pref.id}` as never)}
                  </p>
                  {!pref.switchable && (
                    <p className="tv-setting-row-caption">
                      {t("settings.modules.alwaysOn")}
                    </p>
                  )}
                  {pref.blocked_by && (
                    <p className="tv-setting-row-caption">
                      {t("settings.modules.needsOther").replace(
                        "{name}",
                        nameOf(pref.blocked_by),
                      )}
                    </p>
                  )}
                </div>
                <span className="tv-setting-row-state">
                  {pref.switchable && (
                    <span className="tv-setting-row-state-word">
                      {pref.user_enabled
                        ? t("settings.modules.stateOn" as never)
                        : t("settings.modules.stateOff" as never)}
                    </span>
                  )}
                  <Toggle
                    checked={pref.user_enabled}
                    disabled={!pref.switchable || savingId !== null}
                    onChange={(v) => void flip(pref, v)}
                    ariaLabel={nameOf(pref.id)}
                  />
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}
