import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, clearTokens, REFRESH_TOKEN_KEY, storeTokens, TOKEN_KEY } from "../../lib/api";
import { clearEditViewRequest } from "../../lib/editView";
import { setViewerCurrency } from "../../lib/money";
import { useTheme } from "../../theme/ThemeContext";
import type { AccountType } from "./accountTypes";

export interface User {
  id: string;
  account_number: string;
  /** The account's group set; [] = not chosen yet (the app gates the
   *  user onto the one-time pick before anything else). */
  account_types: AccountType[];
  email: string;
  name: string;
  email_verified: boolean;
  /** False for OAuth-only accounts (no usable password set yet). */
  password_login_enabled: boolean;
  /** Operator flag (module doctrine, owner 2026-10-18): drives the
   *  Admin nav item. The admin API re-checks it server-side. */
  is_operator: boolean;
  /** Community role ladder (user | moderator | community_admin) —
   *  separate from groups and from is_operator; drives the
   *  moderation-queue link. The API re-checks it server-side. */
  role: string;
  /** Account tier (2026-10-31): the account's rung
   *  (normal | moderator | moderator_admin | god) — drives the
   *  Admin entry for moderator admins (user management only).
   *  The API re-checks it server-side. */
  tier: string;
  /** Beta tester flag (2026-10-31): stackable early-access flag
   *  on the rung; modules lit for the beta tier reach this
   *  account before normal accounts. */
  beta_tester: boolean;
  /** Community contact preferences (2026-10-19): the coarse area
   *  label shown on the public profile, the contact phone, and
   *  whether the phone may be shown at all (default off). */
  public_area_label: string;
  contact_phone: string;
  show_phone: boolean;
  silence_claim_readiness_nudges: boolean;
  /** Report contact details (reports alignment, 2026-10-19): the
   * private phone + postal address heading the Prepared-For block
   * on the owner's generated reports. "" = unset. */
  phone: string;
  postal_address: string;
  /** Currency chooser (wave 3): the optional country (ISO alpha-2,
   * "" = unset) and the account's currency (ISO 4217). Amounts on
   * the account are IN this currency — v1 semantics, no stored
   * conversion anywhere. */
  country: string;
  /** Interface language (audit A17): "en" | "es" | "" (unset =
   * automatic: country default, then browser, then English). */
  locale: string;
  currency: string;
  /** Community catalog contribution (wave 4): whether this
   *  account's items' spec data (brand/model/category/size/list
   *  price) feeds the derived community catalog. Default ON;
   *  Settings → Sharing carries the switch. */
  catalog_contribute: boolean;
  /** Appearance (owner ruling, 2026-10-25): the account-held
   *  look — mode (dark|light), per-mode accent (hex), theme.
   *  Each is null until the account first saves an appearance;
   *  all null = never saved. AuthProvider applies these over
   *  the browser-local values at sign-in. */
  appearance_mode: string | null;
  appearance_accent: string | null;
  /** Per-mode accent (owner order, 2026-11-08): the account's
   *  LIGHT-mode pick; null = no light pick (the silver default
   *  shows). appearance_accent above is the dark-mode pick. */
  appearance_accent_light: string | null;
  appearance_theme: string | null;
  /** Wizard defaults (Wizard Phase 1, 2026-10-25): the
   *  account-held Add-wizard setup document (pre-checked
   *  include sections + usual location/dealer). Null until
   *  the account first saves wizard defaults in Settings;
   *  the shape is owned by modules/inventory/wizardDefaults. */
  wizard_defaults: Record<string, unknown> | null;
  /** Rail pin (widget options Wave 1, 2026-11-02): the
   *  account-held choice to keep the left menu rail open.
   *  Null until the account first sets it (null reads as
   *  unpinned — the rail's hover behavior, unchanged); false
   *  is an explicit unpin. */
  rail_pinned: boolean | null;
  created_at: string;
}

interface AuthContextValue {
  user: User | null;
  /** True while the stored token is being validated on load. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Returns the created user so the caller can show the account number. */
  signup: (
    name: string,
    email: string,
    password: string,
    accountTypes: AccountType[],
    referralCode?: string,
    country?: string,
    currency?: string,
    locale?: string,
    /** Per-user module switches (2026-10-24): the module ids the
     *  user unchecked on the signup module step. Omitted/empty =
     *  everything on (the default for every account). */
    disabledModules?: string[],
  ) => Promise<User>;
  logout: () => void;
  /** Re-fetch /core/me into state (e.g. after a password change flips
   *  password_login_enabled). No-op when signed out. */
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  // Appearance sync (owner ruling, 2026-10-25): AuthProvider is
  // rendered inside ThemeProvider, so it can drive the theme
  // state when a session resolves. `appearanceRef` always holds
  // the look currently on screen; `appearanceSyncedFor` makes
  // the sync run exactly once per signed-in account.
  const { theme, mode, accentDark, accentLight, hydrateFromAccount } =
    useTheme();
  const appearanceRef = useRef({ theme, mode, accentDark, accentLight });
  appearanceRef.current = { theme, mode, accentDark, accentLight };
  const appearanceSyncedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!user) {
      // Signed out: the next sign-in syncs afresh, and the
      // browser-local look simply carries on meanwhile.
      appearanceSyncedFor.current = null;
      return;
    }
    if (appearanceSyncedFor.current === user.id) return;
    appearanceSyncedFor.current = user.id;
    if (
      user.appearance_mode != null ||
      user.appearance_accent != null ||
      user.appearance_accent_light != null ||
      user.appearance_theme != null
    ) {
      // The account has a saved look: it wins over whatever
      // this browser had stored locally.
      hydrateFromAccount({
        mode: user.appearance_mode,
        accent: user.appearance_accent,
        accentLight: user.appearance_accent_light,
        theme: user.appearance_theme,
      });
    } else {
      // Nothing saved yet: adopt the look currently on screen
      // (the browser's local choice — e.g. the accent picked
      // on the signup form, or the dark + orange defaults) as
      // the account's appearance, so from now on the account
      // holds it and it follows the user to every sign-in.
      // Per-mode accent: the slots adopt as they stand — a
      // light DEFAULT on screen (silver, un-picked) is not a
      // pick, so a null light slot adopts as no field at all
      // and the account's light pick stays empty.
      const current = appearanceRef.current;
      void api("/core/me", {
        method: "PATCH",
        body: JSON.stringify({
          appearance_mode: current.mode,
          appearance_accent: current.accentDark,
          ...(current.accentLight !== null
            ? { appearance_accent_light: current.accentLight }
            : {}),
          appearance_theme: current.theme,
        }),
      }).catch(() => undefined);
    }
  }, [user, hydrateFromAccount]);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setLoading(false);
      return;
    }
    api<User>("/core/me")
      .then((me) => {
        setUser(me);
        setViewerCurrency(me.currency);
      })
      .catch(() => clearTokens())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    // A new session starts clean: a pending Edit view request
    // belongs to whoever set it, never to the account signing
    // in (owner bug report, 2026-10-24 — see lib/editView).
    clearEditViewRequest();
    const res = await api<{ access_token: string; refresh_token: string }>(
      "/core/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
    );
    storeTokens(res.access_token, res.refresh_token);
    const me = await api<User>("/core/me");
    setUser(me);
    setViewerCurrency(me.currency);
  }, []);

  const signup = useCallback(
    async (
      name: string,
      email: string,
      password: string,
      accountTypes: AccountType[],
      referralCode?: string,
      country?: string,
      currency?: string,
      locale?: string,
      disabledModules?: string[],
    ) => {
      const created = await api<User>("/core/signup", {
        method: "POST",
        body: JSON.stringify({
          name,
          email,
          password,
          account_types: accountTypes,
          // Referral capture: the referrer's account number, when
          // one was entered. The server ignores unknown codes.
          referral_code: referralCode?.trim() || undefined,
          // Signup basics: since the onboarding wizard (owner
          // design 2026-10-31, built 2026-11-07) the signup form
          // sends none of these — the server defaults them and
          // the wizard's basics step collects the real picks.
          // Sent only when a caller provides them.
          country: country || undefined,
          currency: currency || undefined,
          locale: locale || undefined,
          // Module step picks: only sent when the user actually
          // unchecked something — absent reads as all-on server-side.
          disabled_modules:
            disabledModules && disabledModules.length > 0
              ? disabledModules
              : undefined,
        }),
      });
      return created;
    },
    [],
  );

  const refreshUser = useCallback(async () => {
    if (!localStorage.getItem(TOKEN_KEY)) return;
    const me = await api<User>("/core/me");
    setUser(me);
    setViewerCurrency(me.currency);
  }, []);

  const logout = useCallback(() => {
    // Session-scoped UI intent dies with the session: nothing
    // the outgoing account asked for may greet the next one.
    clearEditViewRequest();
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (refreshToken) {
      // Best-effort server-side revocation; local cleanup is unconditional.
      void api("/core/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => undefined);
    }
    clearTokens();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, signup, logout, refreshUser }),
    [user, loading, login, signup, logout, refreshUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
