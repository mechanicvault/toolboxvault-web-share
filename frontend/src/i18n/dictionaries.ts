/**
 * Interface dictionaries — the loader (sheet rows 111/112).
 *
 * The dictionaries themselves live one file per language
 * (dict/en.ts, dict/es.ts) and ship as separate chunks: a
 * visitor downloads only the language they use, instead of
 * both riding the main bundle for everyone (they were ~728 KB
 * of the ~1.12 MB main script). `en` stays the source of truth
 * for keys; `es` must carry the same keys (TypeScript enforces
 * it). t() falls back to the English string for any key a
 * locale hasn't translated, so the UI can never render a raw
 * key or a blank once the dictionaries are in.
 */
import type { DictKey } from "./dict/en";

export type { DictKey } from "./dict/en";

export type Locale = "en" | "es";
export type LocaleDict = Record<DictKey, string>;

const cache = new Map<Locale, LocaleDict>();
const inflight = new Map<Locale, Promise<LocaleDict>>();

/** Load a locale's dictionary chunk (cached; concurrent calls
 *  share one fetch). Rejects if the chunk can't be fetched —
 *  the caller (LocaleContext) retries once, then renders with
 *  whatever is loaded. */
export function loadDictionary(locale: Locale): Promise<LocaleDict> {
  const hit = cache.get(locale);
  if (hit) return Promise.resolve(hit);
  const pending = inflight.get(locale);
  if (pending) return pending;
  const request = (async (): Promise<LocaleDict> => {
    try {
      const dict: LocaleDict =
        locale === "es"
          ? (await import("./dict/es")).es
          : ((await import("./dict/en")).en as unknown as LocaleDict);
      cache.set(locale, dict);
      return dict;
    } finally {
      inflight.delete(locale);
    }
  })();
  inflight.set(locale, request);
  return request;
}

/** The already-loaded dictionary for a locale, if any. */
export function peekDictionary(locale: Locale): LocaleDict | undefined {
  return cache.get(locale);
}
