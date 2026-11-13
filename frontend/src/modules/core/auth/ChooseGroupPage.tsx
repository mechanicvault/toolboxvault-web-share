import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Alert, Button, FormField, Select, Spinner } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import type { AccountType } from "../accountTypes";
import { useAuth } from "../AuthContext";
import { groupLayerWaived } from "../onboarding";
import { useT } from "../../../i18n/LocaleContext";
import { AccentSwatches } from "../../../theme/AccentDots";
import { AuthLayout } from "./AuthLayout";
import { GroupPicker } from "./GroupPicker";

/**
 * The one-time completion page. A signed-in account missing any of
 * its bare bones — an EMPTY group set (every social-login account:
 * the provider redirect can't ask, plus every pre-group legacy
 * account) or the signup BASICS (country unset: social logins and
 * pre-basics legacy accounts, owner directive 2026-10-22) — is
 * routed here by the app gate before any app page, and can't
 * continue until the missing pieces are picked. The page asks ONLY
 * what's missing: groups and/or country + currency + language +
 * platform color, at the same owner-set defaults as signup
 * (United States, USD, English, orange). Accounts that have
 * everything never see this: they're bounced straight into the app.
 */
export default function ChooseGroupPage() {
  const { user, loading, refreshUser } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const [accountTypes, setAccountTypes] = useState<AccountType[]>([]);
  // The basics, at their owner-set defaults (an account that has a
  // country never sees this part; its currency/locale ride along).
  const [country, setCountry] = useState("US");
  const [currency, setCurrency] = useState("USD");
  const [currencyTouched, setCurrencyTouched] = useState(false);
  const [locale, setLocale] = useState("en");
  const [countries, setCountries] = useState<{ code: string; label: string }[]>([]);
  const [currencies, setCurrencies] = useState<string[]>([]);
  const [countryCurrencies, setCountryCurrencies] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Adopt anything the account already carries (a legacy account
  // may have set a language or a non-default currency in Settings
  // while its country was unset) — the defaults only fill gaps.
  useEffect(() => {
    if (!user || user.country) return;
    if (user.locale === "en" || user.locale === "es") setLocale(user.locale);
    if (user.currency && user.currency !== "USD") {
      setCurrency(user.currency);
      setCurrencyTouched(true);
    }
  }, [user]);

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

  if (loading) {
    return (
      <AuthLayout title="One moment" wide>
        <p className="tv-auth-inline-row">
          <Spinner size="sm" /> Loading…
        </p>
      </AuthLayout>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  // A group-waived account (the downloads level) holds no group
  // set by design — the picker is not a door it has, so this
  // page asks it only for missing basics and bounces it home
  // when those are present (never a picker it can't submit).
  const needsGroups =
    !groupLayerWaived(user) && user.account_types.length === 0;
  const needsBasics = !user.country;
  if (!needsGroups && !needsBasics) return <Navigate to="/" replace />;

  /** Country pick: the currency auto-follows until touched. */
  function onCountryChange(next: string) {
    setCountry(next);
    if (!currencyTouched) {
      const suggested = countryCurrencies[next];
      if (suggested) setCurrency(suggested);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (needsGroups && accountTypes.length === 0) {
      setError("Pick at least one group to continue.");
      return;
    }
    if (needsBasics && (!country || !currency)) {
      setError(t("auth.signup.pickBasics"));
      return;
    }
    setBusy(true);
    try {
      if (needsGroups) {
        await api("/core/account-type", {
          method: "POST",
          body: JSON.stringify({ account_types: accountTypes }),
        });
      }
      if (needsBasics) {
        await api("/core/me", {
          method: "PATCH",
          body: JSON.stringify({ country, currency, locale }),
        });
      }
      // Pull the updated /me (new set, the stored basics) into
      // state, then enter the app — the gate now lets us through.
      // The account number does not move: it is final at signup.
      await refreshUser();
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save your picks. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={needsGroups ? "What describes you?" : "A few basics"} wide>
      <p className="tv-auth-intro">
        {needsGroups
          ? "One quick pick so your vault shows the right tools for the work you do. Choose one or more — a lot of people wear more than one hat."
          : "A few bare-bones picks every account starts with."}{" "}
        You can change all of this later in Settings.
      </p>
      <form onSubmit={onSubmit} className="tv-auth-stack">
        {needsGroups && (
          <GroupPicker value={accountTypes} onChange={setAccountTypes} />
        )}
        {needsBasics && (
          <>
            {countries.length > 0 && (
              <FormField
                label={t("auth.signup.country")}
                htmlFor="cg-country"
                required
                hint={t("auth.signup.countryHint")}
              >
                <Select
                  id="cg-country"
                  value={country}
                  onChange={(e) => onCountryChange(e.target.value)}
                >
                  <option value="">{t("auth.signup.selectCountry")}</option>
                  {countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </FormField>
            )}
            {currencies.length > 0 && (
              <FormField
                label={t("auth.signup.currency")}
                htmlFor="cg-currency"
                required
                hint={t("auth.signup.currencyHint")}
              >
                <Select
                  id="cg-currency"
                  value={currency}
                  onChange={(e) => {
                    setCurrencyTouched(true);
                    setCurrency(e.target.value);
                  }}
                >
                  <option value="">{t("auth.signup.selectCurrency")}</option>
                  {currencies.map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </Select>
              </FormField>
            )}
            <FormField label={t("auth.signup.language")} htmlFor="cg-language" required>
              <Select
                id="cg-language"
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
              >
                <option value="en">English</option>
                <option value="es">Español</option>
              </Select>
            </FormField>
            <FormField
              label={t("auth.signup.color")}
              required
              hint={t("auth.signup.colorHint")}
            >
              <AccentSwatches />
            </FormField>
          </>
        )}
        {error && <Alert tone="danger">{error}</Alert>}
        <Button type="submit" loading={busy}>
          {busy ? "Saving…" : "Continue to my vault"}
        </Button>
      </form>
    </AuthLayout>
  );
}
