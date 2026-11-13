import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Panel,
  Select,
  Spinner,
  TextArea,
  TextInput,
  Toggle,
  useToast,
} from "../../components";
import type { DictKey } from "../../i18n/dictionaries";
import { api, ApiError, REFRESH_TOKEN_KEY } from "../../lib/api";
import { AccentSwatches } from "../../theme/AccentDots";
import { useTheme } from "../../theme/ThemeContext";
import { ThemeModePlate, ThemeSwitcher } from "../../theme/ThemeSwitcher";
import { LocaleSwitcher } from "../../i18n/LocaleSwitcher";
import { useLocale, useT } from "../../i18n/LocaleContext";
import {
  accountTypeSummary,
  type AccountType,
} from "./accountTypes";
import { useAuth, type User } from "./AuthContext";
import { GroupPicker } from "./auth/GroupPicker";
import SessionsSettings from "./SessionsSettings";
import { AccessCodeSettingsPanel } from "./TierConversion";
import { useMyModules } from "./MyModules";
import {
  getAlerts as getFlyerAlerts,
  putAlerts as putFlyerAlerts,
} from "../flyers/api";
import {
  getContentAlerts,
  putContentAlert,
  type ContentAlertKind,
  type ContentAlertPrefs,
} from "./contentAlerts";

/**
 * The settings SECTION components (settings restructure, owner
 * review round 1, 2026-10-19). These used to be stacked in one
 * long SettingsPage scroll; now each is a registry section (see
 * settingsRegistry.tsx) rendered one at a time by the shell.
 * Profile data is REAL (the /me payload behind useAuth); sections
 * whose systems don't exist yet say so plainly instead of faking
 * controls.
 */

const PASSWORD_MIN_LENGTH = 6; // mirrors the backend policy (schemas)

function detail(label: string, value: ReactNode) {
  return (
    <div
      style={{
        display: "grid",
        // minmax(0, …): the value column must be allowed to shrink
        // below its content's min-content — an unbroken email is
        // ~190px of min-content, which at phone widths otherwise
        // forces the row (and in Steel Light the whole panel, and
        // with it the document) wider than the screen (measured
        // 412px at a 402px viewport, 2026-10-18). The dd's
        // overflow-wrap then breaks the value inside its column.
        gridTemplateColumns: "150px minmax(0, 1fr)",
        gap: "0.5rem",
      }}
    >
      <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
      <dd style={{ margin: 0, fontWeight: 600, minWidth: 0, overflowWrap: "anywhere" }}>
        {value}
      </dd>
    </div>
  );
}

/* ------------------------------ Profile ------------------------------ */

function GroupForm({ user }: { user: User }) {
  const { toast } = useToast();
  const { refreshUser } = useAuth();
  const [selection, setSelection] = useState<AccountType[]>(user.account_types);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dirty =
    selection.length !== user.account_types.length ||
    selection.some((t) => !user.account_types.includes(t));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (selection.length === 0) {
      setError("Your account has to belong to at least one group.");
      return;
    }
    setSubmitting(true);
    try {
      await api<User>("/core/account-type", {
        method: "POST",
        body: JSON.stringify({ account_types: selection }),
      });
      await refreshUser();
      toast(`Groups updated.`, { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't update your groups. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        Your groups set what you see — overviews, modules, and access.
        Add or remove them here; your account number never changes.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <GroupPicker value={selection} onChange={setSelection} name="settings-groups" />
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          Save groups
        </Button>
      </div>
    </form>
  );
}

function NameForm({ user }: { user: User }) {
  const { toast } = useToast();
  const { refreshUser } = useAuth();
  const [name, setName] = useState(user.name);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldError(null);
    /* F2-14: the error ties to the field and focus moves to it —
     * not a form-top bucket alert. */
    if (!name.trim()) {
      setFieldError("Your name can't be empty.");
      document.getElementById("settings-name")?.focus();
      return;
    }
    setSubmitting(true);
    try {
      await api<User>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ name: name.trim() }),
      });
      await refreshUser();
      toast("Your name was updated.", { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save your name. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label="Name" htmlFor="settings-name" required error={fieldError ?? undefined}>
        <TextInput
          id="settings-name"
          value={name}
          invalid={Boolean(fieldError)}
          onChange={(e) => { setName(e.target.value); setFieldError(null); }}
          autoComplete="name"
        />
      </FormField>
      <div>
        <Button type="submit" loading={submitting} disabled={name.trim() === user.name}>
          Save name
        </Button>
      </div>
    </form>
  );
}

interface EmailChangeState {
  pending_email: string | null;
  expires_at: string | null;
}

function EmailForm({ user }: { user: User }) {
  const { toast } = useToast();
  const tt = useT();
  const [emailFieldError, setEmailFieldError] = useState<string | null>(null);
  const [passwordFieldError, setPasswordFieldError] = useState<string | null>(null);
  const [pending, setPending] = useState<EmailChangeState | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [resending, setResending] = useState(false);

  const loadPending = useCallback(async () => {
    try {
      setPending(await api<EmailChangeState>("/core/email-change"));
    } catch {
      setPending({ pending_email: null, expires_at: null });
    }
  }, []);

  useEffect(() => {
    void loadPending();
  }, [loadPending]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEmailFieldError(null);
    setPasswordFieldError(null);
    /* F2-23: an EMPTY current password says the field is empty —
     * it must never round-trip to the server and come back as
     * "Current password is incorrect." */
    if (!newEmail.trim()) {
      setEmailFieldError(tt("settings.email.newEmailRequired"));
      document.getElementById("settings-new-email")?.focus();
      return;
    }
    if (user.password_login_enabled && !currentPassword) {
      setPasswordFieldError(tt("settings.email.passwordRequired"));
      document.getElementById("settings-email-change-password")?.focus();
      return;
    }
    setSubmitting(true);
    try {
      const state = await api<EmailChangeState>("/core/email-change/request", {
        method: "POST",
        body: JSON.stringify({
          new_email: newEmail.trim(),
          current_password: user.password_login_enabled
            ? currentPassword
            : undefined,
        }),
      });
      setPending(state);
      setNewEmail("");
      setCurrentPassword("");
      toast(
        `Confirmation link sent to ${state.pending_email}. Open it within the hour to finish the change.`,
        { tone: "success", duration: 8000 },
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't start the email change.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancel() {
    setCancelling(true);
    try {
      await api("/core/email-change", { method: "DELETE" });
      setPending({ pending_email: null, expires_at: null });
      toast("Email change cancelled. The link that was sent no longer works.", {
        tone: "success",
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't cancel the change.",
      );
    } finally {
      setCancelling(false);
    }
  }

  async function onResendVerification() {
    setResending(true);
    try {
      await api("/core/me/resend-verification", { method: "POST" });
      toast(
        "Verification email sent — open the link in it to verify this address.",
        { tone: "success", duration: 8000 },
      );
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't send the verification email.",
        { tone: "danger" },
      );
    } finally {
      setResending(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-3)" }}>
      {!user.email_verified && (
        <div
          style={{
            display: "flex",
            gap: "var(--space-3)",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            This address isn't verified yet. The verification link
            proves the inbox is yours.
          </p>
          <Button
            type="button"
            variant="secondary"
            loading={resending}
            onClick={() => void onResendVerification()}
          >
            {resending ? "Sending…" : "Resend verification email"}
          </Button>
        </div>
      )}
      {pending?.pending_email ? (
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <Alert tone="warning">
            A confirmation link was sent to {pending.pending_email}.
            Your email changes only when that link is opened
            {pending.expires_at
              ? ` (it expires ${new Date(pending.expires_at).toLocaleString()})`
              : ""}
            . Until then you keep signing in with {user.email}.
          </Alert>
          <div>
            <Button
              type="button"
              variant="secondary"
              loading={cancelling}
              onClick={() => void onCancel()}
            >
              {cancelling ? "Cancelling…" : "Cancel the change"}
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            Your email address is how you sign in, so a change has
            to be confirmed at the new address first: we send that
            inbox a link, and the change lands when it's opened. A
            notice also goes to your current address.
          </p>
          {error && <Alert tone="danger">{error}</Alert>}
          <FormField label="New email address" htmlFor="settings-new-email" required error={emailFieldError ?? undefined}>
            <TextInput
              id="settings-new-email"
              type="email"
              value={newEmail}
              invalid={Boolean(emailFieldError)}
              onChange={(e) => { setNewEmail(e.target.value); setEmailFieldError(null); }}
              autoComplete="email"
            />
          </FormField>
          {user.password_login_enabled && (
            <FormField
              label="Current password"
              htmlFor="settings-email-change-password"
              required
              error={passwordFieldError ?? undefined}
            >
              <TextInput
                id="settings-email-change-password"
                type="password"
                value={currentPassword}
                invalid={Boolean(passwordFieldError)}
                onChange={(e) => { setCurrentPassword(e.target.value); setPasswordFieldError(null); }}
                autoComplete="current-password"
              />
            </FormField>
          )}
          <div>
            <Button type="submit" loading={submitting}>
              {submitting ? "Sending…" : "Send confirmation link"}
            </Button>
          </div>
        </form>
      )}
      {pending?.pending_email && error && <Alert tone="danger">{error}</Alert>}
    </div>
  );
}

/**
 * Report contact details (reports alignment, 2026-10-19): the
 * optional phone + postal address that head the "Prepared for"
 * block on generated reports — Ryan's app report carries them, so
 * the profile does too. Private paperwork data, never published;
 * leaving them blank simply leaves them off the document.
 */
function ReportContactForm({ user }: { user: User }) {
  const { toast } = useToast();
  const { refreshUser } = useAuth();
  const [phone, setPhone] = useState(user.phone);
  const [address, setAddress] = useState(user.postal_address);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dirty = phone !== user.phone || address !== user.postal_address;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api<User>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ phone: phone.trim(), postal_address: address.trim() }),
      });
      await refreshUser();
      toast("Report contact details saved.", { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        Optional — when set, these appear in the “Prepared for” block on
        reports you generate (and on claims paperwork later). Leave them
        blank and they simply don't appear.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label="Phone" htmlFor="settings-report-phone">
        <TextInput
          id="settings-report-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          autoComplete="tel"
          placeholder="e.g. (555) 010-1234"
        />
      </FormField>
      <FormField label="Postal address" htmlFor="settings-report-address">
        <TextArea
          id="settings-report-address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          autoComplete="street-address"
          rows={3}
          placeholder={"Street\nCity, ST ZIP"}
        />
      </FormField>
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          Save report contact details
        </Button>
      </div>
    </form>
  );
}

interface MoneyMeta {
  countries: { code: string; label: string }[];
  currencies: string[];
  country_currencies: Record<string, string>;
}

/** Country & currency (wave 3): the account's amounts are IN its
 * currency — picking a country suggests its currency; the
 * currency itself stays independently changeable afterwards. */
function CountryCurrencyForm({ user }: { user: User }) {
  const { toast } = useToast();
  const { refreshUser } = useAuth();
  const [meta, setMeta] = useState<MoneyMeta | null>(null);
  // Country is required account basics (owner, 2026-10-22): an
  // unset country opens on the USA default, and the select no
  // longer offers a "Not set" clearing option.
  const [country, setCountry] = useState(user.country || "US");
  const [currency, setCurrency] = useState(user.currency || "USD");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dirty = country !== user.country || currency !== (user.currency || "USD");

  useEffect(() => {
    let cancelled = false;
    api<MoneyMeta>("/core/money/meta")
      .then((m) => {
        if (!cancelled) setMeta(m);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api<User>("/core/me", {
        method: "PATCH",
        body: JSON.stringify({ country, currency }),
      });
      await refreshUser();
      toast("Country & currency saved.", { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        Your amounts — prices, totals, reports — are shown in your
        currency. Other people's prices show in THEIR currency,
        with an approximate conversion next to them when yours
        differs.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label="Country" htmlFor="settings-country">
        <Select
          id="settings-country"
          value={country}
          onChange={(e) => {
            const next = e.target.value;
            setCountry(next);
            // Picking a country suggests its currency (the
            // server applies the same default); the currency
            // below stays free to change afterwards.
            const suggested = meta?.country_currencies[next];
            if (suggested) setCurrency(suggested);
          }}
        >
          {(meta?.countries ?? []).map((c) => (
            <option key={c.code} value={c.code}>
              {c.label}
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label="Currency" htmlFor="settings-currency">
        <Select
          id="settings-currency"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {(meta?.currencies ?? [currency]).map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </Select>
      </FormField>
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          Save country & currency
        </Button>
      </div>
    </form>
  );
}

export function ProfileSection({ user }: { user: User }) {
  return (
    <Panel title="Profile" variant="plate">
      <div style={{ marginBottom: "1rem" }}>
        <NameForm user={user} />
      </div>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginBottom: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
          Country & currency
        </p>
        <CountryCurrencyForm user={user} />
      </div>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginBottom: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
          Report contact details
        </p>
        <ReportContactForm user={user} />
      </div>
      <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
        {detail("Email", user.email)}
        {detail("Account number", user.account_number)}
        {detail(
          "Account groups",
          user.account_types.length > 0
            ? accountTypeSummary(user.account_types)
            : "Not chosen yet",
        )}
        {detail(
          "Email verified",
          user.email_verified ? (
            <Badge tone="success">Verified</Badge>
          ) : (
            <Badge tone="warning">Not verified</Badge>
          ),
        )}
      </dl>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginTop: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>Email address</p>
        <EmailForm user={user} />
      </div>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginTop: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>Your groups</p>
        <GroupForm user={user} />
      </div>
      {/* Tier conversion (2026-11-10): the second door out of
          the downloads level — renders ONLY for that tier (the
          component gates on the payload's tier), so no other
          seat ever sees it. */}
      <AccessCodeSettingsPanel tier={user.tier} />
    </Panel>
  );
}

/* ------------------------- Security & sessions ------------------------ */

function PasswordForm({ user }: { user: User }) {
  const { toast } = useToast();
  const { refreshUser } = useAuth();
  const hasPassword = user.password_login_enabled;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < PASSWORD_MIN_LENGTH) {
      setError(`New password must be at least ${PASSWORD_MIN_LENGTH} characters.`);
      return;
    }
    if (next !== confirm) {
      setError("New password and confirmation don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await api("/core/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: hasPassword ? current : undefined,
          new_password: next,
          // The session that survives the change (all others are revoked).
          refresh_token: localStorage.getItem(REFRESH_TOKEN_KEY) ?? undefined,
        }),
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      toast(
        hasPassword
          ? "Password changed. Other devices were signed out."
          : "Password set. You can now sign in with your email too.",
        { tone: "success" },
      );
      await refreshUser();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {!hasPassword && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          You sign in with Google. Set a password if you also want to
          sign in with your email.
        </p>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {hasPassword && (
        <FormField label="Current password" htmlFor="settings-current-password" required>
          <TextInput
            id="settings-current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </FormField>
      )}
      <FormField
        label="New password"
        htmlFor="settings-new-password"
        required
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
      >
        <TextInput
          id="settings-new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          required
        />
      </FormField>
      <FormField label="Confirm new password" htmlFor="settings-confirm-password" required>
        <TextInput
          id="settings-confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
        />
      </FormField>
      <div>
        <Button type="submit" loading={submitting}>
          {hasPassword ? "Change password" : "Set password"}
        </Button>
      </div>
      {hasPassword && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          Changing your password signs out every other device and session.
          This one stays signed in.
        </p>
      )}
    </form>
  );
}

export function SecuritySection({ user }: { user: User }) {
  return (
    <Panel title="Security & sessions" variant="plate">
      <div style={{ display: "grid", gap: "var(--space-5)" }}>
        <PasswordForm user={user} />
        <SessionsSettings />
      </div>
    </Panel>
  );
}

/* ----------------------- Public profile & contact --------------------- */

function PublicProfileForm({ user }: { user: User }) {
  const { toast } = useToast();
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
      toast("Your public profile contact settings were saved.", {
        title: "Saved",
        tone: "success",
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't save those settings.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        What the community sees on your public profile. Your area is
        coarse on purpose — a region or city, never your address.
        {messagingOn ? (
          <>
            {" "}
            In-site messaging is always available; a phone number is
            your choice alone.
          </>
        ) : (
          <>{" "}A phone number is your choice alone.</>
        )}
      </p>
      <FormField label="Public area" htmlFor="settings-area">
        <TextInput
          id="settings-area"
          value={area}
          onChange={(e) => setArea(e.target.value)}
          placeholder="e.g. Central Minnesota"
          maxLength={120}
        />
      </FormField>
      <FormField label="Contact phone" htmlFor="settings-contact-phone">
        <TextInput
          id="settings-contact-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="Only shown if you turn it on below"
          maxLength={40}
          autoComplete="tel"
        />
      </FormField>
      <Toggle
        id="settings-show-phone"
        label="Show my phone number on my public profile and listings"
        checked={showPhone}
        onChange={setShowPhone}
      />
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          Save public profile
        </Button>
      </div>
    </form>
  );
}

export function PublicProfileSection({ user }: { user: User }) {
  return (
    <Panel title="Public profile & contact" variant="plate">
      <PublicProfileForm user={user} />
    </Panel>
  );
}

/* ------------------------------ Appearance ---------------------------- */

export function AppearanceSection() {
  const t = useT();
  const { locale } = useLocale();
  const { mode } = useTheme();
  return (
    <Panel title={t("settings.appearance.title")} variant="plate">
      {/* F1-28: the section composes like its siblings — controls
          on the left, a LIVE preview on the right (it re-renders
          in the current theme/accent because it uses the same
          tokens), instead of one short panel in a sea of grey. */}
      <div
        style={{
          display: "grid",
          gap: "var(--space-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
        }}
      >
      <div style={{ display: "grid", gap: "var(--space-4)", alignContent: "start" }}>
        <div>
          <p className="tv-settings-block-label">
            {t("settings.appearance.theme")}
          </p>
          {/* Rail Steel Phase 3: ThemeSwitcher is the whole theme
              control — a single current-design plate. There is NO
              Layout picker and NO Header-variant picker here:
              both contexts are pinned and the rail shell ignores
              them, so offering them would be a silent lie. The
              providers stay mounted for their importers. */}
          <ThemeSwitcher />
        </div>
        <div>
          <p className="tv-settings-block-label">
            {t("settings.appearance.mode")}
          </p>
          {/* Light-mode seam (owner steer, 2026-10-24): the mode
              row sits beside the design plate from today, bound
              to ThemeContext's mode. When the light palette
              lands, this plate becomes the Light/Dark toggle —
              no section restructuring. It is a plate, not a
              switch, until there is a second palette to switch
              to. */}
          <ThemeModePlate
            label={t(
              mode === "dark"
                ? "settings.appearance.modeDark"
                : "settings.appearance.modeLight",
            )}
          />
        </div>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.appearance.accent")}
          </p>
          <AccentSwatches />
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }}>
{t("settings.appearance.accentHelper")}
          </p>
        </div>
        <div>
          <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
            {t("settings.appearance.language")}
          </p>
          <LocaleSwitcher id="locale-switcher-settings" />
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }}>
            {t("settings.appearance.languageBody")}
          </p>
          <p style={{ color: "var(--text-muted)", margin: "var(--space-2) 0 0" }} lang={locale}>
            {locale === "es"
              ? "La traducción cubre la interfaz principal; algunas pantallas especializadas aún se muestran en inglés."
              : "Translation covers the main interface; some specialized screens still show in English."}
          </p>
        </div>
      </div>
      <div aria-hidden="true" style={{ alignContent: "start", display: "grid", gap: "var(--space-3)" }}>
        <p style={{ fontWeight: 700, margin: 0 }}>{locale === "es" ? "Vista previa" : "Live preview"}</p>
        <Panel title={locale === "es" ? "Panel de ejemplo" : "Sample panel"}>
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <span style={{ fontSize: "var(--font-size-2xl)", fontWeight: 800 }}>$19,004</span>
            <span style={{ color: "var(--text-muted)", fontSize: "var(--font-size-xs)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
              {locale === "es" ? "Costo de reemplazo" : "Replacement cost"}
            </span>
            <div>
              <Button size="sm">{locale === "es" ? "Botón principal" : "Primary button"}</Button>
            </div>
          </div>
        </Panel>
      </div>
      </div>
    </Panel>
  );
}

/* ----------------------------- Notifications -------------------------- */

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
  const flyersOn = !modulesLoading && has("flyers");
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
  if (supportOn) activityParts.push("answers on your support tickets");
  if (communityOn) activityParts.push("activity on the community boards");
  if (messagingOn)
    activityParts.push("new messages in conversations you've accepted");
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
          ? "Claim-readiness checks are silenced — no more nudges."
          : "Claim-readiness checks are on — a nudge at most once a week, and only when records are missing.",
        { tone: "success" },
      );
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save that preference.",
        { tone: "danger" },
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Notifications" variant="plate">
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {inventoryOn ? (
            <>
              Your notifications — tool-list invites and their answers,
              borrowing activity
              {messagingOn && (
                <>, and new messages in conversations you've accepted</>
              )}
              {" "}— appear in the header ticker and in the Notifications
              block on your home page.
            </>
          ) : (
            <>
              Your notifications
              {activityClause ? ` — ${activityClause} — ` : " "}
              appear in the header ticker.
            </>
          )}
          {messagingOn && (
            <>
              {" "}
              Message requests never notify: a first contact waits
              quietly in Messages → Requests until you answer it.
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
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "var(--space-3)",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <div>
            <p style={{ fontWeight: 700, margin: 0 }}>Claim-readiness checks</p>
            <p style={{ color: "var(--text-muted)", margin: "0.2rem 0 0" }}>
              At most once a week, and only when items are missing a
              photo, serial number, or purchase price — the records
              an insurer asks for first. Turn this off to silence
              them for good.
            </p>
          </div>
          <Toggle
            checked={!silenced}
            onChange={(v) => void flipSilence(!v)}
            disabled={saving}
            ariaLabel="Claim-readiness checks enabled"
          />
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
              <p className="tv-settings-intro">{t("flyers.alertsHelp")}</p>
            </div>
            <Toggle
              checked={flyerAlerts}
              disabled={savingFlyerAlerts}
              onChange={(v) => void flipFlyerAlerts(v)}
              ariaLabel={t("flyers.alerts")}
            />
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
                    <p className="tv-settings-intro">{t(`alerts.${kind}Help` as DictKey)}</p>
                  </div>
                  <Toggle
                    checked={contentAlerts[kind]}
                    disabled={savingContentAlert === kind}
                    onChange={(v) => void flipContentAlert(kind, v)}
                    ariaLabel={t(`alerts.${kind}` as DictKey)}
                  />
                </div>
              ),
            )
          : null}
        <div>
          <p className="tv-setting-row-name">
            {t("settings.notifications.emailTitle")}
          </p>
          <p className="tv-settings-intro">
            {t("settings.notifications.emailIntro")}
          </p>
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
                  </div>
                  <Toggle
                    checked={pref.email_enabled}
                    disabled={savingCat !== null}
                    onChange={(v) => void flipEmail(pref.category, v)}
                    ariaLabel={t(
                      `settings.notifications.cat.${pref.category}` as DictKey,
                    )}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}

