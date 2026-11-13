import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "../lib/api";
import { useAuth } from "../modules/core/AuthContext";
import { DICTIONARIES, type DictKey } from "./dictionaries";

/**
 * Locale framework (audit A17, blueprint §16).
 *
 * Resolution order mirrors the backend rule, with the browser
 * as the frontend-only step: the account's stored preference
 * (users.locale, set in Settings -> Appearance) -> the stored
 * country default (applied server-side to /me's locale by
 * signup country — the frontend reads the RESOLVED value the
 * same way: preference or country) -> a stored browser choice
 * (the signed-out switcher) -> the browser language -> English.
 *
 * t() ALWAYS falls back to English, so an untranslated key
 * renders English — never a key, never a blank.
 */

export type Locale = "en" | "es";

const STORAGE_KEY = "tv-locale";

const ES_COUNTRIES = new Set([
  "AR", "BO", "CL", "CO", "CR", "CU", "DO", "EC", "ES", "GQ",
  "GT", "HN", "MX", "NI", "PA", "PE", "PR", "PY", "SV", "UY", "VE",
]);

function browserLocale(): Locale {
  if (typeof navigator !== "undefined" && navigator.language) {
    return navigator.language.toLowerCase().startsWith("es") ? "es" : "en";
  }
  return "en";
}

interface LocaleContextValue {
  locale: Locale;
  /** The stored preference ("" = automatic). */
  preference: string;
  setPreference: (pref: string) => Promise<void>;
  t: (key: DictKey) => string;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "en",
  preference: "",
  setPreference: async () => {},
  t: (key) => DICTIONARIES.en[key],
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [browserChoice, setBrowserChoice] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) ?? "",
  );

  const preference = user ? (user.locale ?? "") : browserChoice;

  const locale: Locale = useMemo(() => {
    if (preference === "es" || preference === "en") return preference;
    // Automatic: stored country default, then browser language.
    if (user?.country && ES_COUNTRIES.has(user.country.toUpperCase())) {
      return "es";
    }
    return browserLocale();
  }, [preference, user?.country]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setPreference = useCallback(
    async (pref: string) => {
      if (user) {
        await api("/core/me", {
          method: "PATCH",
          body: JSON.stringify({ locale: pref }),
        });
      } else {
        localStorage.setItem(STORAGE_KEY, pref);
        setBrowserChoice(pref);
      }
    },
    [user],
  );

  const t = useCallback(
    (key: DictKey): string => DICTIONARIES[locale][key] ?? DICTIONARIES.en[key],
    [locale],
  );

  const value = useMemo(
    () => ({ locale, preference, setPreference, t }),
    [locale, preference, setPreference, t],
  );
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}

export function useT(): (key: DictKey) => string {
  return useContext(LocaleContext).t;
}

/** Nav/route label through the dictionary, falling back to the
 * registry's English label for routes without a nav.* key. */
export function useNavLabel(): (routeName: string, fallback: string) => string {
  const { locale } = useLocale();
  return useCallback(
    (routeName: string, fallback: string) => {
      const key = `nav.${routeName}` as DictKey;
      const dict = DICTIONARIES[locale];
      return (dict as Record<string, string>)[key] ?? fallback;
    },
    [locale],
  );
}
