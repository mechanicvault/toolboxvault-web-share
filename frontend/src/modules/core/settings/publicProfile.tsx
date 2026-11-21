import { useState, type FormEvent } from "react";
import { Alert, Button, FormField, Panel, TextInput, Toggle, useToast } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { useAuth, type User } from "../AuthContext";
import { useMyModules } from "../MyModules";

function PublicProfileForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
  const { refreshUser } = useAuth();
  const { loading: modulesLoading, has } = useMyModules();
  // Parked-module signs (owner directive, 2026-10-31): the
  // messaging promise in the intro renders only while messaging
  // is effective for this viewer — and returns on its own when
  // the module is unparked. While modules load, no promise is
  // made (the same never-guess rule the nav follows).
  const messagingOn = !modulesLoading && has("messaging");
  const [area, setArea] = useState(user.public_area_label ?? "");
  const [phone, setPhone] = useState(user.contact_phone ?? "");
  const [showPhone, setShowPhone] = useState(user.show_phone ?? false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const dirty =
    area !== (user.public_area_label ?? "") ||
    phone !== (user.contact_phone ?? "") ||
    showPhone !== (user.show_phone ?? false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api<User>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({
          public_area_label: area.trim(),
          contact_phone: phone.trim(),
          show_phone: showPhone,
        }),
      });
      await refreshUser();
      toast(t("settings.publicProfile.savedToast"), {
        title: t("settings.publicProfile.savedTitle"),
        tone: "success",
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.publicProfile.saveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {t("settings.publicProfile.introLead")}
        {messagingOn ? (
          <>
            {" "}
            {t("settings.publicProfile.introMessaging")}
          </>
        ) : (
          <> {t("settings.publicProfile.introPhoneOnly")}</>
        )}
      </p>
      <FormField label={t("settings.publicProfile.area")} htmlFor="settings-area">
        <TextInput
          id="settings-area"
          value={area}
          onChange={(e) => setArea(e.target.value)}
          placeholder={t("settings.publicProfile.areaPlaceholder")}
          maxLength={120}
        />
      </FormField>
      <FormField label={t("settings.publicProfile.phone")} htmlFor="settings-contact-phone">
        <TextInput
          id="settings-contact-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder={t("settings.publicProfile.phonePlaceholder")}
          maxLength={40}
          autoComplete="tel"
        />
      </FormField>
      {/* The phone switch rides the standard setting-row anatomy
          (settings uniformity, 2026-11-13): name + description +
          state word + switch, like every other settings switch —
          its label text becomes the row name/description pair and
          stays whole as the switch's aria-label. */}
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
          <p className="tv-setting-row-name">{t("settings.publicProfile.showPhone")}</p>
          <p className="tv-setting-row-desc">
            {t("settings.publicProfile.showPhoneDesc")}
          </p>
        </div>
        <span className="tv-setting-row-state">
          <span className="tv-setting-row-state-word">
            {showPhone ? t("settings.stateOn") : t("settings.stateOff")}
          </span>
          <Toggle
            id="settings-show-phone"
            checked={showPhone}
            onChange={setShowPhone}
            ariaLabel={t("settings.publicProfile.showPhoneAria")}
          />
        </span>
      </div>
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          {t("settings.publicProfile.save")}
        </Button>
      </div>
    </form>
  );
}

export function PublicProfileSection({ user }: { user: User }) {
  const t = useT();
  return (
    <Panel title={t("settings.publicProfile.title")} variant="plate">
      <PublicProfileForm user={user} />
    </Panel>
  );
}

/* ------------------------------ Appearance ---------------------------- */

