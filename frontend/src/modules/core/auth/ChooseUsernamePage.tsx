import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Alert, Button, FormField, Spinner, TextInput } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useAuth, type User } from "../AuthContext";
import { useT } from "../../../i18n/LocaleContext";
import {
  probeUsername,
  usernameReasonKey,
  type UsernameCheck,
} from "../usernames";
import { AuthLayout } from "./AuthLayout";

/**
 * The forced username pick (sheet row 144, owner directive
 * 2026-11-18). Every account carries a unique username — the
 * only name other people ever see in the site's public areas.
 * Accounts born before usernames (and social-login accounts,
 * whose provider redirect can't ask) hold none, and the app
 * gate routes them here before any app page until they pick
 * one. The page says why in plain words: the username exists
 * for the member's safety, so their real name is never shown
 * in public. There is no skip.
 */
export default function ChooseUsernamePage() {
  const { user, loading, refreshUser } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [verdict, setVerdict] = useState<UsernameCheck | "checking" | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(
    () => probeUsername(username, user?.username ?? null, setVerdict),
    [username, user?.username],
  );

  if (loading) {
    return (
      <AuthLayout title={t("auth.username.pickTitle")}>
        <Spinner />
      </AuthLayout>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (user.username) return <Navigate to="/" replace />;

  const verdictError =
    verdict && verdict !== "checking" && !verdict.available
      ? t(usernameReasonKey(verdict.reason ?? ""))
      : undefined;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setFieldError(null);
    if (!username.trim()) {
      setFieldError(t("auth.signup.usernameRequired"));
      document.getElementById("cu-username")?.focus();
      return;
    }
    if (verdictError) {
      setFieldError(verdictError);
      document.getElementById("cu-username")?.focus();
      return;
    }
    setBusy(true);
    try {
      await api<User>("/core/me/username", {
        method: "POST",
        body: JSON.stringify({ username: username.trim() }),
      });
      await refreshUser();
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.message.startsWith("username_")) {
        setFieldError(t(usernameReasonKey(err.message)));
        document.getElementById("cu-username")?.focus();
      } else {
        setError(err instanceof ApiError ? err.message : t("auth.signup.failed"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("auth.username.pickTitle")}>
      <form onSubmit={onSubmit} noValidate className="tv-auth-form">
        <p className="tv-auth-muted">{t("auth.username.pickIntro")}</p>
        {error && <Alert tone="danger">{error}</Alert>}
        <FormField
          label={t("auth.signup.username")}
          htmlFor="cu-username"
          required
          hint={
            verdict === "checking"
              ? t("auth.username.checking")
              : verdict?.available
                ? t("auth.username.available")
                : t("auth.signup.usernameHint")
          }
          error={fieldError ?? verdictError}
        >
          <TextInput
            id="cu-username"
            value={username}
            invalid={Boolean(fieldError ?? verdictError)}
            onChange={(e) => {
              setUsername(e.target.value);
              setFieldError(null);
            }}
            autoComplete="username"
          />
        </FormField>
        <Button type="submit" loading={busy} block>
          {t("auth.username.pickSubmit")}
        </Button>
      </form>
    </AuthLayout>
  );
}
