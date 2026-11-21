import { useState, type FormEvent } from "react";
import { Alert, Button, FormField, Panel, TextInput, useToast } from "../../../components";
import { api, ApiError, REFRESH_TOKEN_KEY } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { useAuth, type User } from "../AuthContext";
import SessionsSettings from "../SessionsSettings";
import { PASSWORD_MIN_LENGTH } from "./shared";

function PasswordForm({ user }: { user: User }) {
  const { toast } = useToast();
  const t = useT();
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
      setError(
        t("settings.security.passwordTooShort").replace(
          "{min}",
          String(PASSWORD_MIN_LENGTH),
        ),
      );
      return;
    }
    if (next !== confirm) {
      setError(t("settings.security.passwordMismatch"));
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
          ? t("settings.security.passwordChangedToast")
          : t("settings.security.passwordSetToast"),
        { tone: "success" },
      );
      await refreshUser();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("settings.security.genericError"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: "var(--space-3)" }}>
      {!hasPassword && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.security.googleNote")}
        </p>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {hasPassword && (
        <FormField label={t("settings.security.currentPassword")} htmlFor="settings-current-password" required>
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
        label={t("settings.security.newPassword")}
        htmlFor="settings-new-password"
        required
        hint={t("settings.security.passwordHint").replace(
          "{min}",
          String(PASSWORD_MIN_LENGTH),
        )}
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
      <FormField label={t("settings.security.confirmPassword")} htmlFor="settings-confirm-password" required>
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
          {hasPassword ? t("settings.security.changePassword") : t("settings.security.setPassword")}
        </Button>
      </div>
      {hasPassword && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.security.signOutNote")}
        </p>
      )}
    </form>
  );
}

export function SecuritySection({ user }: { user: User }) {
  const t = useT();
  return (
    <Panel title={t("settings.security.title")} variant="plate">
      <div style={{ display: "grid", gap: "var(--space-5)" }}>
        <PasswordForm user={user} />
        <SessionsSettings />
      </div>
    </Panel>
  );
}

/* ----------------------- Public profile & contact --------------------- */

