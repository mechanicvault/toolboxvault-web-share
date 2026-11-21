import { useEffect, useState } from "react";
import { Alert, Panel, Spinner, Toggle, useToast } from "../../../components";
import { type DictKey } from "../../../i18n/dictionaries";
import { api, ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { isDealerOnlyAccount } from "../settingsMeta";
import { useAuth, type User } from "../AuthContext";
import { useMyModules } from "../MyModules";
import {
  getAlerts as getFlyerAlerts,
  putAlerts as putFlyerAlerts,
} from "../../flyers/api";
import {
  getContentAlerts,
  putContentAlert,
  type ContentAlertKind,
  type ContentAlertPrefs,
} from "../contentAlerts";

interface NotifChannelPref {
  category: string;
  email_enabled: boolean;
}

export function NotificationsSection() {
  const { user, refreshUser } = useAuth();
  const { toast } = useToast();
  const t = useT();
  const { loading: modulesLoading, has } = useMyModules();
  // Parked-module signs (owner directive, 2026-10-31): the
  // messaging clauses in the intro and the Messages email row
  // render only while messaging is effective for this viewer —
  // and return on their own when the module is unparked. The
  // stored preference itself is never touched.
  const messagingOn = !modulesLoading && has("messaging");
  const [saving, setSaving] = useState(false);
  const silenced = user?.silence_claim_readiness_nudges ?? false;

  /* New-flyer alerts (flyer module, 2026-11-06): the flyer
   * notification carries its OWN per-user switch in the flyers
   * module (default on) — this row is its settings home, shown
   * only while flyers is effective for this viewer. */
  /* Dealer-only accounts (owner sheet rows 27 + 28, 2026-11-15)
   * never see the new-flyer alerts row — the dealer is the one
   * who uploads the flyers — nor the flyer / shop-crew email
   * categories below: a dealer's account has no crew and takes
   * no flyer alerts. Multi-group accounts keep everything. */
  const dealerOnly = isDealerOnlyAccount(user?.account_types ?? []);
  const flyersOn = !modulesLoading && has("flyers") && !dealerOnly;
  const [flyerAlerts, setFlyerAlerts] = useState<boolean | null>(null);
  const [savingFlyerAlerts, setSavingFlyerAlerts] = useState(false);

  useEffect(() => {
    if (!flyersOn) return;
    let live = true;
    getFlyerAlerts()
      .then((d) => {
        if (live) setFlyerAlerts(d.enabled);
      })
      .catch(() => {
        if (live) setFlyerAlerts(null);
      });
    return () => {
      live = false;
    };
  }, [flyersOn]);

  async function flipFlyerAlerts(next: boolean) {
    setSavingFlyerAlerts(true);
    try {
      const saved = await putFlyerAlerts(next);
      setFlyerAlerts(saved.enabled);
    } catch {
      toast(t("settings.notifications.saveFailed"), { tone: "danger" });
    } finally {
      setSavingFlyerAlerts(false);
    }
  }

  /* New-content alerts (sweep E4, busy-work #6): the Downloads
   * and 3D Print Files inbox opt-ins (default OFF) mirror here
   * over the same core prefs the section pages carry. The
   * downloads box always renders (Downloads is always-on —
   * it is the downloads rung's own shelf); the prints box
   * renders only while prints is effective for this viewer. */
  const printsOn = !modulesLoading && has("prints");
  const [contentAlerts, setContentAlerts] = useState<ContentAlertPrefs | null>(null);
  const [savingContentAlert, setSavingContentAlert] = useState<ContentAlertKind | null>(null);

  useEffect(() => {
    let live = true;
    getContentAlerts()
      .then((d) => {
        if (live) setContentAlerts(d);
      })
      .catch(() => {
        if (live) setContentAlerts(null);
      });
    return () => {
      live = false;
    };
  }, []);

  async function flipContentAlert(kind: ContentAlertKind, next: boolean) {
    setSavingContentAlert(kind);
    try {
      const saved = await putContentAlert(kind, next);
      setContentAlerts(saved);
    } catch {
      toast(t("settings.notifications.saveFailed"), { tone: "danger" });
    } finally {
      setSavingContentAlert(null);
    }
  }

  /* Email channel preferences (owner item 12, 2026-10-24): the
   * bell always shows every notification; email is per-category
   * and the user's choice. Rows come from the API in display
   * order with effective values (stored flip or the category
   * default). */
  const [prefs, setPrefs] = useState<NotifChannelPref[] | null>(null);
  const [prefsError, setPrefsError] = useState(false);
  const [savingCat, setSavingCat] = useState<string | null>(null);
  /* Reach gates (wizard reach filter, 2026-11-09 — settings
   * follow reach one level down, the messaging pattern above
   * extended): the claim-readiness row and each email category
   * render only while the module that owns their events is
   * effective for this viewer. A downloads-level account's
   * Notifications step otherwise enumerated claims, borrowing,
   * truck accounts and dealer updates it can never reach.
   * Categories with no module owner (crew, announcements,
   * account & system) always render. Stored preferences are
   * never touched — a hidden row's flip survives as-is. */
  const inventoryOn = !modulesLoading && has("inventory");
  const claimsOn = !modulesLoading && has("claims");
  const supportOn = !modulesLoading && has("support");
  const communityOn =
    !modulesLoading && (has("forum") || has("feedback"));
  const CATEGORY_MODULES: Record<string, string[]> = {
    support: ["support"],
    claims: ["claims"],
    borrowing: ["borrowing"],
    sharing: ["inventory"],
    maintenance: ["maintenance"],
    community: ["forum", "feedback"],
    truck_accounts: ["truck"],
    dealers: ["dealers"],
    flyers: ["flyers"],
    prints: ["prints"],
  };
  const visiblePrefs =
    prefs?.filter((pref) => {
      if (dealerOnly && (pref.category === "flyers" || pref.category === "crew"))
        return false;
      if (pref.category === "messages") return messagingOn;
      const owners = CATEGORY_MODULES[pref.category];
      if (!owners) return true;
      return !modulesLoading && owners.some((m) => has(m));
    }) ?? null;
  // The intro's activity clause names only what this account
  // can actually be notified about (the inventory wording below
  // is the historical sentence, kept verbatim for accounts
  // that reach inventory).
  const activityParts: string[] = [];
  if (supportOn) activityParts.push(t("settings.notifications.activitySupport"));
  if (communityOn)
    activityParts.push(t("settings.notifications.activityCommunity"));
  if (messagingOn)
    activityParts.push(t("settings.notifications.activityMessages"));
  const activityClause = activityParts.join(", ");

  useEffect(() => {
    let live = true;
    api<NotifChannelPref[]>("/core/me/notification-preferences")
      .then((d) => {
        if (live) setPrefs(Array.isArray(d) ? d : []);
      })
      .catch(() => {
        if (live) setPrefsError(true);
      });
    return () => {
      live = false;
    };
  }, []);

  async function flipEmail(category: string, next: boolean) {
    setSavingCat(category);
    try {
      const saved = await api<NotifChannelPref>(
        "/core/me/notification-preferences",
        {
          method: "PUT",
          body: JSON.stringify({
            category,
            channel: "email",
            enabled: next,
          }),
        },
      );
      setPrefs((p) =>
        (p ?? []).map((x) => (x.category === category ? saved : x)),
      );
    } catch {
      toast(t("settings.notifications.saveFailed"), { tone: "danger" });
    } finally {
      setSavingCat(null);
    }
  }

  async function flipSilence(next: boolean) {
    setSaving(true);
    try {
      await api<User>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ silence_claim_readiness_nudges: next }),
      });
      await refreshUser();
      toast(
        next
          ? t("settings.notifications.claimSilencedToast")
          : t("settings.notifications.claimOnToast"),
        { tone: "success" },
      );
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.notifications.saveFailed"),
        { tone: "danger" },
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title={t("settings.notifications.title")} variant="plate">
      <div className="tv-settings-stack">
        <p className="tv-settings-intro">
          {inventoryOn ? (
            <>
              {t("settings.notifications.introInventoryLead")}
              {messagingOn && (
                <>{t("settings.notifications.introMessagingClause")}</>
              )}
              {" "}
              {t("settings.notifications.introInventoryTail")}
            </>
          ) : (
            <>
              {t("settings.notifications.introLead")}
              {activityClause ? ` — ${activityClause} — ` : " "}
              {t("settings.notifications.introAppearTicker")}
            </>
          )}
          {messagingOn && (
            <>
              {" "}
              {t("settings.notifications.introRequests")}
            </>
          )}
        </p>
        {(inventoryOn || claimsOn) && (
        <div
          className="tv-setting-row is-clickable"
          onClick={(e) => {
            /* Whole row drives its switch (same pattern as the
             * Modules rows): forward to the switch itself so the
             * saving state behaves exactly as a direct click. */
            if (
              (e.target as HTMLElement).closest(
                "button, a, input, select, textarea",
              )
            ) {
              return;
            }
            e.currentTarget
              .querySelector<HTMLButtonElement>('[role="switch"]')
              ?.click();
          }}
        >
          <div className="tv-setting-row-main">
            <p className="tv-setting-row-name">
              {t("settings.notifications.claimReadiness")}
            </p>
            <p className="tv-setting-row-desc">
              {t("settings.notifications.claimReadinessDesc")}
            </p>
          </div>
          <span className="tv-setting-row-state">
            <span className="tv-setting-row-state-word">
              {!silenced ? t("settings.stateOn") : t("settings.stateOff")}
            </span>
            <Toggle
              checked={!silenced}
              onChange={(v) => void flipSilence(!v)}
              disabled={saving}
              ariaLabel={t("settings.notifications.claimReadinessAria")}
            />
          </span>
        </div>
        )}
        {flyersOn && flyerAlerts !== null ? (
          <div
            className="tv-setting-row is-clickable"
            onClick={(e) => {
              if (
                (e.target as HTMLElement).closest(
                  "button, a, input, select, textarea",
                )
              ) {
                return;
              }
              e.currentTarget
                .querySelector<HTMLButtonElement>('[role="switch"]')
                ?.click();
            }}
          >
            <div className="tv-setting-row-main">
              <p className="tv-setting-row-name">{t("flyers.alerts")}</p>
              <p className="tv-setting-row-desc">{t("flyers.alertsHelp")}</p>
            </div>
            <span className="tv-setting-row-state">
              <span className="tv-setting-row-state-word">
                {flyerAlerts ? t("settings.stateOn") : t("settings.stateOff")}
              </span>
              <Toggle
                checked={flyerAlerts}
                disabled={savingFlyerAlerts}
                onChange={(v) => void flipFlyerAlerts(v)}
                ariaLabel={t("flyers.alerts")}
              />
            </span>
          </div>
        ) : null}
        {contentAlerts !== null
          ? (["downloads", ...(printsOn ? ["prints"] : [])] as ContentAlertKind[]).map(
              (kind) => (
                <div
                  key={kind}
                  className="tv-setting-row is-clickable"
                  onClick={(e) => {
                    if (
                      (e.target as HTMLElement).closest(
                        "button, a, input, select, textarea",
                      )
                    ) {
                      return;
                    }
                    e.currentTarget
                      .querySelector<HTMLButtonElement>('[role="switch"]')
                      ?.click();
                  }}
                >
                  <div className="tv-setting-row-main">
                    <p className="tv-setting-row-name">{t(`alerts.${kind}` as DictKey)}</p>
                    <p className="tv-setting-row-desc">{t(`alerts.${kind}Help` as DictKey)}</p>
                  </div>
                  <span className="tv-setting-row-state">
                    <span className="tv-setting-row-state-word">
                      {contentAlerts[kind] ? t("settings.stateOn") : t("settings.stateOff")}
                    </span>
                    <Toggle
                      checked={contentAlerts[kind]}
                      disabled={savingContentAlert === kind}
                      onChange={(v) => void flipContentAlert(kind, v)}
                      ariaLabel={t(`alerts.${kind}` as DictKey)}
                    />
                  </span>
                </div>
              ),
            )
          : null}
        <div>
          {/* Flag header (owner, sheet row 191, 2026-11-19 —
              replaces the row 153 full-width banner): the Email
              alerts category opens with its title on the widget
              title flag, the intro back to plain section text
              under it — here in the wizard step and everywhere
              this section renders. */}
          <div className="tv-email-head">
            <p className="tv-flag-title">
              {t("settings.notifications.emailTitle")}
            </p>
            <p className="tv-settings-intro">
              {t("settings.notifications.emailIntro")}
            </p>
          </div>
          {prefsError ? (
            <Alert tone="danger">
              {t("settings.notifications.loadFailed")}
            </Alert>
          ) : prefs === null ? (
            <Spinner />
          ) : (
            <div>
              {(visiblePrefs ?? []).map((pref) => (
                <div
                  key={pref.category}
                  className="tv-setting-row is-clickable"
                  onClick={(e) => {
                    /* Whole row drives its switch: forward to
                     * the switch itself so the saving state
                     * behaves exactly as a direct click. */
                    if (
                      (e.target as HTMLElement).closest(
                        "button, a, input, select, textarea",
                      )
                    ) {
                      return;
                    }
                    e.currentTarget
                      .querySelector<HTMLButtonElement>('[role="switch"]')
                      ?.click();
                  }}
                >
                  <div className="tv-setting-row-main">
                    <p className="tv-setting-row-name">
                      {t(
                        `settings.notifications.cat.${pref.category}` as DictKey,
                      )}
                    </p>
                    <p className="tv-setting-row-desc">
                      {t(
                        `settings.notifications.catDesc.${pref.category}` as DictKey,
                      )}
                    </p>
                  </div>
                  <span className="tv-setting-row-state">
                    <span className="tv-setting-row-state-word">
                      {pref.email_enabled
                        ? t("settings.stateOn")
                        : t("settings.stateOff")}
                    </span>
                    <Toggle
                      checked={pref.email_enabled}
                      disabled={savingCat !== null}
                      onChange={(v) => void flipEmail(pref.category, v)}
                      ariaLabel={t(
                        `settings.notifications.cat.${pref.category}` as DictKey,
                      )}
                    />
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}

