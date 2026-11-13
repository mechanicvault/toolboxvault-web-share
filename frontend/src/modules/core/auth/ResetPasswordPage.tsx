import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Alert, Button, FormField, TextInput } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { AuthLayout } from "./AuthLayout";
import { useT } from "../../../i18n/LocaleContext";

const PASSWORD_MIN_LENGTH = 6; // mirrors the backend policy (schemas)

/** Reset password: the landing page of the emailed reset link
 *  (/reset-password?token=…). Submitting sets the new password,
 *  consumes the link, and signs out every session — the page
 *  says so, because landing back at login afterwards is the
 *  expected outcome, not a glitch. */
export default function ResetPasswordPage() {
  const t = useT();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < PASSWORD_MIN_LENGTH) {
      setError(`${t("auth.reset.tooShort")} ${PASSWORD_MIN_LENGTH} ${t("auth.reset.characters")}`);
      return;
    }
    if (password !== confirm) {
      setError(t("auth.reset.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await api("/core/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("auth.reset.failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.reset.title")}
      footer={
        <>
          {t("auth.reset.backTo")}{" "}
          <Link to="/login" className="tv-auth-link">
            {t("auth.reset.loginLink")}
          </Link>
        </>
      }
    >
      {done ? (
        <div className="tv-auth-stack">
          <Alert tone="success">{t("auth.reset.done")}</Alert>
          <Link to="/login" className="tv-auth-link tv-auth-link-strong">
            {t("auth.reset.goLogin")}
          </Link>
        </div>
      ) : !token ? (
        <div className="tv-auth-stack">
          <Alert tone="danger">{t("auth.reset.missingCode")}</Alert>
          <p className="tv-auth-muted0">
            <Link to="/forgot-password" className="tv-auth-link">
              {t("auth.reset.requestNew")}
            </Link>
          </p>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="tv-auth-stack">
          <FormField
            label={t("auth.reset.newPassword")}
            htmlFor="rp-password"
            required
            hint={`${t("auth.reset.atLeast")} ${PASSWORD_MIN_LENGTH} ${t("auth.reset.characters")}`}
          >
            <TextInput
              id="rp-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          <FormField label={t("auth.reset.confirmPassword")} htmlFor="rp-confirm" required>
            <TextInput
              id="rp-confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />
          </FormField>
          {error && <Alert tone="danger">{error}</Alert>}
          <Button type="submit" loading={busy}>
            {busy ? t("auth.reset.busy") : t("auth.reset.submit")}
          </Button>
          <p className="tv-auth-note-sm">
            {t("auth.reset.signsOut")}
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
