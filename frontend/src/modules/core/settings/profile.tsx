import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  FormField,
  Panel,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../../components";
import { peekDictionary, type DictKey } from "../../../i18n/dictionaries";
import { api, ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import {
  accountTypeSummary,
  type AccountType,
} from "../accountTypes";
import { useAuth, type User } from "../AuthContext";
import { GroupPicker } from "../auth/GroupPicker";
import {
  probeUsername,
  usernameReasonKey,
  type UsernameCheck,
} from "../usernames";
import { AccessCodeSettingsPanel } from "../TierConversion";
import { detail } from "./shared";

function GroupForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
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
      setError(t("settings.groups.emptyError"));
      return;
    }
    setSubmitting(true);
    try {
      await api<User>("/core/account-type", {
        method: "POST",
        body: JSON.stringify({ account_types: selection }),
      });
      await refreshUser();
      toast(t("settings.groups.updatedToast"), { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.groups.saveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {t("settings.groups.intro")}
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <GroupPicker value={selection} onChange={setSelection} name="settings-groups" />
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          {t("settings.groups.save")}
        </Button>
      </div>
    </form>
  );
}

function NameForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
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
      setFieldError(t("settings.profile.nameEmpty"));
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
      toast(t("settings.profile.nameSavedToast"), { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.profile.nameSaveFailed"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label={t("settings.profile.name")} htmlFor="settings-name" required error={fieldError ?? undefined}>
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
          {t("settings.profile.saveName")}
        </Button>
      </div>
    </form>
  );
}

/** Username editor (sheet row 144, owner directive 2026-11-18):
 *  the account's public identity — shown instead of the real
 *  name everywhere public. Changeable once every 6 months; the
 *  server enforces it and reports the unlock moment on /me
 *  (username_next_change_at), which this form shows as a date
 *  while a change is locked. Admins are never locked (their
 *  /me carries no unlock date). */
function UsernameForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
  const { refreshUser } = useAuth();
  const [value, setValue] = useState(user.username ?? "");
  const [verdict, setVerdict] = useState<UsernameCheck | "checking" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(
    () => probeUsername(value, user.username, setVerdict),
    [value, user.username],
  );

  const unlockAt = user.username_next_change_at
    ? new Date(user.username_next_change_at)
    : null;
  const locked = unlockAt !== null && unlockAt.getTime() > Date.now();
  const unlockDate = unlockAt ? unlockAt.toLocaleDateString() : "";

  const verdictError =
    verdict && verdict !== "checking" && !verdict.available
      ? t(usernameReasonKey(verdict.reason ?? ""))
      : undefined;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldError(null);
    if (!value.trim()) {
      setFieldError(t("auth.signup.usernameRequired"));
      document.getElementById("settings-username")?.focus();
      return;
    }
    if (verdictError) {
      setFieldError(verdictError);
      document.getElementById("settings-username")?.focus();
      return;
    }
    setSubmitting(true);
    try {
      await api<User>("/core/me/username", {
        method: "POST",
        body: JSON.stringify({ username: value.trim() }),
      });
      await refreshUser();
      toast(t("settings.profile.usernameSavedToast"), { tone: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.message.startsWith("username_")) {
        setFieldError(
          err.message === "username_cooldown"
            ? t("auth.username.cooldown").replace("{date}", unlockDate)
            : t(usernameReasonKey(err.message)),
        );
        document.getElementById("settings-username")?.focus();
      } else {
        setError(
          err instanceof ApiError ? err.message : t("settings.profile.nameSaveFailed"),
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField
        label={t("settings.profile.username")}
        htmlFor="settings-username"
        required
        hint={
          locked
            ? t("settings.profile.usernameLocked").replace("{date}", unlockDate)
            : verdict === "checking"
              ? t("auth.username.checking")
              : verdict?.available
                ? t("auth.username.available")
                : t("settings.profile.usernameHint")
        }
        error={fieldError ?? verdictError}
      >
        <TextInput
          id="settings-username"
          value={value}
          disabled={locked}
          invalid={Boolean(fieldError ?? verdictError)}
          onChange={(e) => { setValue(e.target.value); setFieldError(null); }}
          autoComplete="username"
        />
      </FormField>
      <div>
        <Button
          type="submit"
          loading={submitting}
          disabled={locked || value.trim() === (user.username ?? "")}
        >
          {t("settings.profile.saveUsername")}
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
        tt("settings.email.confirmSentToast").replace(
          "{email}",
          state.pending_email ?? "",
        ),
        { tone: "success", duration: 8000 },
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : tt("settings.email.startFailed"),
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
      toast(tt("settings.email.cancelledToast"), {
        tone: "success",
      });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : tt("settings.email.cancelFailed"),
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
        tt("settings.email.verificationSentToast"),
        { tone: "success", duration: 8000 },
      );
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : tt("settings.email.verificationSendFailed"),
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
            {tt("settings.email.notVerifiedNote")}
          </p>
          <Button
            type="button"
            variant="secondary"
            loading={resending}
            onClick={() => void onResendVerification()}
          >
            {resending ? tt("settings.email.sending") : tt("settings.email.resendVerification")}
          </Button>
        </div>
      )}
      {pending?.pending_email ? (
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <Alert tone="warning">
            {tt("settings.email.pendingLead").replace("{email}", pending.pending_email)}
            {pending.expires_at
              ? ` ${tt("settings.email.pendingExpires").replace("{date}", new Date(pending.expires_at).toLocaleString())}`
              : ""}
            . {tt("settings.email.pendingTail").replace("{email}", user.email)}
          </Alert>
          <div>
            <Button
              type="button"
              variant="secondary"
              loading={cancelling}
              onClick={() => void onCancel()}
            >
              {cancelling ? tt("settings.email.cancelling") : tt("settings.email.cancelChange")}
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate style={{ display: "grid", gap: "var(--space-3)" }}>
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {tt("settings.email.intro")}
          </p>
          {error && <Alert tone="danger">{error}</Alert>}
          <FormField label={tt("settings.email.newEmailLabel")} htmlFor="settings-new-email" required error={emailFieldError ?? undefined}>
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
              label={tt("settings.security.currentPassword")}
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
              {submitting ? tt("settings.email.sending") : tt("settings.email.sendConfirmation")}
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
  const t = useT();
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
      toast(t("settings.reportContact.savedToast"), { tone: "success" });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("settings.profile.couldntSaveRetry"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {t("settings.reportContact.intro")}
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label={t("settings.reportContact.phone")} htmlFor="settings-report-phone">
        <TextInput
          id="settings-report-phone"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          autoComplete="tel"
          placeholder={t("settings.reportContact.phonePlaceholder")}
        />
      </FormField>
      <FormField label={t("settings.reportContact.address")} htmlFor="settings-report-address">
        <TextArea
          id="settings-report-address"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          autoComplete="street-address"
          rows={3}
          placeholder={t("settings.reportContact.addressPlaceholder")}
        />
      </FormField>
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          {t("settings.reportContact.save")}
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

/** Country / currency option labels: the /core/money/meta values
 * arrive in English, so a KNOWN code renders through the
 * dictionary (settings.country.* / settings.currency.* — the EN
 * values are the API label / the code itself, so EN seats render
 * byte-identically). A code with no key falls back to the API
 * value, per the i18n-final lane's recorded rule. */
function moneyCountryLabel(
  t: (key: DictKey) => string,
  code: string,
  apiLabel: string,
): string {
  const key = `settings.country.${code}` as DictKey;
  return key in (peekDictionary("en") ?? {}) ? t(key) : apiLabel;
}

function moneyCurrencyLabel(
  t: (key: DictKey) => string,
  code: string,
): string {
  const key = `settings.currency.${code}` as DictKey;
  return key in (peekDictionary("en") ?? {}) ? t(key) : code;
}

/** Country & currency (wave 3): the account's amounts are IN its
 * currency — picking a country suggests its currency; the
 * currency itself stays independently changeable afterwards. */
function CountryCurrencyForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
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
      toast(t("settings.countryCurrency.savedToast"), { tone: "success" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.profile.couldntSaveRetry"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {t("settings.countryCurrency.intro")}
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <FormField label={t("settings.countryCurrency.country")} htmlFor="settings-country">
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
              {moneyCountryLabel(t, c.code, c.label)}
            </option>
          ))}
        </Select>
      </FormField>
      <FormField label={t("settings.countryCurrency.currency")} htmlFor="settings-currency">
        <Select
          id="settings-currency"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          {(meta?.currencies ?? [currency]).map((code) => (
            <option key={code} value={code}>
              {moneyCurrencyLabel(t, code)}
            </option>
          ))}
        </Select>
      </FormField>
      <div>
        <Button type="submit" loading={submitting} disabled={!dirty}>
          {t("settings.countryCurrency.save")}
        </Button>
      </div>
    </form>
  );
}

export function ProfileSection({ user }: { user: User }) {
  const t = useT();
  return (
    <Panel title={t("settings.profile.title")} variant="plate">
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
        <UsernameForm user={user} />
      </div>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginBottom: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
          {t("settings.profile.countryCurrencyHeading")}
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
          {t("settings.profile.reportContactHeading")}
        </p>
        <ReportContactForm user={user} />
      </div>
      <dl style={{ display: "grid", gap: "0.6rem", margin: 0 }}>
        {detail(t("settings.profile.email"), user.email)}
        {detail(t("settings.accountNumber"), user.account_number)}
        {detail(
          t("settings.profile.accountGroups"),
          user.account_types.length > 0
            ? accountTypeSummary(user.account_types, t)
            : t("settings.profile.groupsNotChosen"),
        )}
        {detail(
          t("settings.profile.emailVerified"),
          user.email_verified ? (
            <Badge tone="success">{t("settings.profile.verified")}</Badge>
          ) : (
            <Badge tone="warning">{t("settings.profile.notVerified")}</Badge>
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
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>{t("settings.profile.emailAddressHeading")}</p>
        <EmailForm user={user} />
      </div>
      <div
        style={{
          borderTop: "1px solid var(--edge)",
          marginTop: "1rem",
          paddingTop: "1rem",
        }}
      >
        <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>{t("settings.profile.yourGroups")}</p>
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

