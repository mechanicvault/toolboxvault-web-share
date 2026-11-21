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
import {
  loadDictionary,
  type DictKey,
  type LocaleDict,
} from "./dictionaries";

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
  /** The dictionaries loaded so far (rows 111/112: each
   *  language arrives as its own chunk). Consumers that read
   *  the dictionary directly take the active locale's, falling
   *  back to English — the same rule t() follows. */
  dicts: Partial<Record<Locale, LocaleDict>>;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "en",
  preference: "",
  setPreference: async () => {},
  t: (key) => key,
  dicts: {},
});

/** The boot shell, mirrored from index.html's static one: while
 *  the active language's chunk is in flight the app shows the
 *  same skeleton the first paint showed, so there is no flash
 *  of untranslated content and no layout jump. */
function BootShell() {
  return (
    <div className="tv-boot" aria-hidden="true">
      <div className="tv-boot-header">Toolbox Vault</div>
      <div className="tv-boot-body">
        <div className="tv-boot-side">
          <div className="tv-boot-skel tv-boot-line"></div>
          <div className="tv-boot-skel tv-boot-line"></div>
          <div className="tv-boot-skel tv-boot-line"></div>
          <div className="tv-boot-skel tv-boot-line"></div>
          <div className="tv-boot-skel tv-boot-line"></div>
          <div className="tv-boot-skel tv-boot-line"></div>
        </div>
        <div className="tv-boot-main">
          <div className="tv-boot-stats">
            <div className="tv-boot-skel tv-boot-stat"></div>
            <div className="tv-boot-skel tv-boot-stat"></div>
            <div className="tv-boot-skel tv-boot-stat"></div>
            <div className="tv-boot-skel tv-boot-stat"></div>
            <div className="tv-boot-skel tv-boot-stat"></div>
            <div className="tv-boot-skel tv-boot-stat"></div>
          </div>
          <div className="tv-boot-skel tv-boot-panel"></div>
          <div className="tv-boot-skel tv-boot-panel"></div>
        </div>
      </div>
    </div>
  );
}

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

  // Rows 111/112: dictionaries load per language. The active
  // locale's chunk gates first render (the boot shell covers
  // the wait); when the active locale isn't English, English
  // loads alongside as t()'s fallback. A failed fetch retries
  // once, then gives up gating — the app renders with whatever
  // is loaded rather than bricking on a network hiccup.
  const [dicts, setDicts] = useState<
    Partial<Record<Locale, LocaleDict>>
  >({});
  const [gaveUp, setGaveUp] = useState(false);
  useEffect(() => {
    let live = true;
    const wanted: Locale[] = locale === "en" ? ["en"] : [locale, "en"];
    for (const target of wanted) {
      if (dicts[target]) continue;
      loadDictionary(target)
        .catch(() => loadDictionary(target))
        .then((dict) => {
          if (live) {
            setDicts((prev) =>
              prev[target] ? prev : { ...prev, [target]: dict },
            );
          }
        })
        .catch(() => {
          if (live && target === locale) setGaveUp(true);
        });
    }
    return () => {
      live = false;
    };
    // dicts is read for the already-loaded shortcut only; the
    // effect re-runs on locale change, not on every load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    (key: DictKey): string =>
      dicts[locale]?.[key] ?? dicts.en?.[key] ?? key,
    [dicts, locale],
  );

  const value = useMemo(
    () => ({ locale, preference, setPreference, t, dicts }),
    [locale, preference, setPreference, t, dicts],
  );
  const ready = Boolean(dicts[locale] ?? dicts.en) || gaveUp;
  return (
    <LocaleContext.Provider value={value}>
      {ready ? children : <BootShell />}
    </LocaleContext.Provider>
  );
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
  const { locale, dicts } = useLocale();
  return useCallback(
    (routeName: string, fallback: string) => {
      const key = `nav.${routeName}` as DictKey;
      const dict = dicts[locale] ?? dicts.en ?? {};
      return (dict as Record<string, string>)[key] ?? fallback;
    },
    [locale, dicts],
  );
}
