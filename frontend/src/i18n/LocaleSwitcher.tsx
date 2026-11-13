import { Select } from "../components";
import { useLocale, useT } from "./LocaleContext";
import { useAuth } from "../modules/core/AuthContext";

/**
 * The language switcher (audit A17): a compact select with
 * Automatic / English / Español. Used in the signed-out header
 * cluster and in Settings -> Appearance. Signed-in changes save
 * to the account (PATCH /me) and refresh the auth user so the
 * whole shell re-renders in the new language; signed-out
 * changes persist in this browser only.
 */
export function LocaleSwitcher({ id = "locale-switcher" }: { id?: string }) {
  const { preference, setPreference } = useLocale();
  const { refreshUser } = useAuth();
  const t = useT();

  return (
    <Select
      id={id}
      aria-label={t("shell.language")}
      value={preference}
      onChange={(e) => {
        void setPreference(e.target.value).then(() => refreshUser());
      }}
      className="tv-locale-select"
    >
      <option value="">{t("settings.language.auto")}</option>
      <option value="en">{t("settings.language.en")}</option>
      <option value="es">{t("settings.language.es")}</option>
    </Select>
  );
}
