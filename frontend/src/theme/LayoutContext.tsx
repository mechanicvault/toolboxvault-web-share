import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

/**
 * Site LAYOUT — PINNED to the sidebar (owner review round 1,
 * 2026-10-19). The owner walked the site, chose the left menu bar,
 * and ordered the other layouts removed: "lets keep the site with
 * the menu bar on the left … and remove the other layout options."
 *
 * The Top Bar and Rail presentations are retired. This provider now
 * exists only to keep the shell's contract stable (AppShell still
 * receives a `layout` value) while guaranteeing the one layout:
 * any stored `tv-layout` preference from the multi-layout era is
 * ignored and cleaned, `data-layout` on <html> is forced to
 * "sidebar", and setLayout is a no-op that keeps the pin. The
 * topbar/rail CSS stays on disk dormant (keyed off data-layout
 * values nothing sets any more) in case a layout is ever revived.
 */
export type LayoutName = "sidebar" | "topbar" | "rail";

interface LayoutContextValue {
  layout: LayoutName;
  setLayout: (l: LayoutName) => void;
}

const LayoutContext = createContext<LayoutContextValue | null>(null);

const STORAGE_KEY = "tv-layout";

export function LayoutProvider({ children }: { children: ReactNode }) {
  // One-time cleanup + immediate application: the shell's geometry
  // depends on the attribute, so it is set during the first render
  // pass, not in an effect.
  localStorage.removeItem(STORAGE_KEY);
  document.documentElement.dataset.layout = "sidebar";

  const setLayout = useCallback((_l: LayoutName) => {
    // Pinned: there is no other layout to switch to.
    document.documentElement.dataset.layout = "sidebar";
  }, []);

  const value = useMemo(() => ({ layout: "sidebar" as LayoutName, setLayout }), [setLayout]);
  return <LayoutContext.Provider value={value}>{children}</LayoutContext.Provider>;
}

export function useLayout(): LayoutContextValue {
  const ctx = useContext(LayoutContext);
  if (!ctx) throw new Error("useLayout must be used inside <LayoutProvider>");
  return ctx;
}
