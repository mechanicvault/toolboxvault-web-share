import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

/**
 * Header VARIANT — PINNED to the Yoke (owner review round 1,
 * 2026-10-19). The variant era (Classic / Pendant / Yoke switchable
 * from the Appearance controls) ended with the layout lock-in: the
 * owner kept the header bar exactly as it stands — the Yoke he
 * crowned on 2026-10-19, brand plate centered through the beam —
 * and the switcher UI is gone.
 *
 * This provider keeps the shell's contract stable while
 * guaranteeing the one header: any stored `tv-header-variant`
 * preference is ignored and cleaned, `data-header-variant` on
 * <html> is forced to "yoke", and setHeaderVariant is a no-op that
 * keeps the pin. The classic/pendant markup paths and CSS stay on
 * disk dormant (AppShell only ever receives "yoke" now) in case a
 * variant is ever revived.
 */
export type HeaderVariantName = "classic" | "pendant" | "yoke";

interface HeaderVariantContextValue {
  headerVariant: HeaderVariantName;
  setHeaderVariant: (v: HeaderVariantName) => void;
}

const HeaderVariantContext = createContext<HeaderVariantContextValue | null>(null);

const STORAGE_KEY = "tv-header-variant";

export function HeaderVariantProvider({ children }: { children: ReactNode }) {
  localStorage.removeItem(STORAGE_KEY);
  document.documentElement.dataset.headerVariant = "yoke";

  const setHeaderVariant = useCallback((_v: HeaderVariantName) => {
    document.documentElement.dataset.headerVariant = "yoke";
  }, []);

  const value = useMemo(
    () => ({ headerVariant: "yoke" as HeaderVariantName, setHeaderVariant }),
    [setHeaderVariant],
  );
  return (
    <HeaderVariantContext.Provider value={value}>
      {children}
    </HeaderVariantContext.Provider>
  );
}

export function useHeaderVariant(): HeaderVariantContextValue {
  const ctx = useContext(HeaderVariantContext);
  if (!ctx) {
    throw new Error("useHeaderVariant must be used inside <HeaderVariantProvider>");
  }
  return ctx;
}
