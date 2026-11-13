import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, FormField, TextInput } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { AuthLayout } from "./AuthLayout";
import { useT } from "../../../i18n/LocaleContext";

/** Forgot password: ask for the account's email, and the server
 *  mails a one-hour, single-use reset link — IF an account exists
 *  for the address. The page says the same thing either way (the
 *  endpoint is deliberately not an existence oracle), so the
 *  honest copy here is conditional: "if an account exists…". */
export default function ForgotPasswordPage() {
  const t = useT();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!email.trim()) {
      setError(t("auth.forgot.enterEmail"));
      return;
    }
    setBusy(true);
    try {
      await api("/core/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t("auth.forgot.failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.forgot.title")}
      footer={
        <>
          {t("auth.forgot.remembered")}{" "}
          <Link to="/login" className="tv-auth-link">
            {t("auth.forgot.loginLink")}
          </Link>
        </>
      }
    >
      {sent ? (
        <div className="tv-auth-stack">
          <Alert tone="success">
            {t("auth.forgot.sentBefore")} {email.trim()}
            {t("auth.forgot.sentAfter")}
          </Alert>
          <p className="tv-auth-muted0">
            {t("auth.forgot.notReceived")}{" "}
            <button
              type="button"
              className="tv-auth-text-btn"
              onClick={() => setSent(false)}
            >
              {t("auth.forgot.tryAgain")}
            </button>
            .
          </p>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="tv-auth-stack">
          <p className="tv-auth-muted0">
            {t("auth.forgot.body")}
          </p>
          <FormField label={t("auth.forgot.email")} htmlFor="fp-email" required>
            <TextInput
              id="fp-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </FormField>
          {error && <Alert tone="danger">{error}</Alert>}
          <Button type="submit" loading={busy}>
            {busy ? t("auth.forgot.busy") : t("auth.forgot.submit")}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
