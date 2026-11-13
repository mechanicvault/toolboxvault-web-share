import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Alert, Button, FormField, TextInput } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useAuth } from "../AuthContext";
import { AuthLayout } from "./AuthLayout";
import { SocialButtons } from "./SocialButtons";
import { useT } from "../../../i18n/LocaleContext";

/** Login: email + password, or a configured social provider. Stores
 *  the JWT, then heads Home — the owner's dashboard (deep audit
 *  F1-11: sign-in used to dump the user into Inventory). A
 *  redirect-back target set by RequireAuth (the page a signed-out
 *  visitor was actually headed to) still wins over the default.
 *  Arriving with ?error=oauth
 *  means a social sign-in just failed — say so plainly. ?error=
 *  banned / ?error=deactivated mean an operator block stopped the
 *  social sign-in — name it, don't dress it up as a glitch. */
const ARRIVAL_ERROR_KEYS = {
  oauth: "auth.login.errOauth",
  banned: "auth.login.errBanned",
  deactivated: "auth.login.errDeactivated",
} as const;

export default function LoginPage() {
  const t = useT();
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  // The sign-in DOOR (sweep C2, 2026-11-12): a visitor who was
  // carried here by a guard — the teaser wall or a page's
  // RequireAuth — arrives with a kept destination, and the door
  // says in plain words why they're being asked to sign in and
  // that signing in lands them right there. A plain /login
  // arrival (the header's Log in, a logout) carries no kept
  // destination and shows no notice — the form exactly as before.
  const doorDestination =
    (location.state as { from?: string } | null)?.from ?? null;
  const showDoorNotice = !!doorDestination && doorDestination !== "/";
  const arrivalKey =
    ARRIVAL_ERROR_KEYS[
      (new URLSearchParams(location.search).get("error") ?? "") as keyof typeof ARRIVAL_ERROR_KEYS
    ];
  const arrivalError = arrivalKey ? t(arrivalKey) : "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(arrivalError);
  const [busy, setBusy] = useState(false);
  // The verification gate (auth.require_email_verification, a
  // launch switch) refuses an unverified account with the
  // email_unverified code — the form then offers the resend
  // instead of leaving the user at a dead end.
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);
  const [resending, setResending] = useState(false);

  if (user) return <Navigate to={from} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setUnverified(false);
    setResent(false);
    if (!email.trim() || !password) {
      setError(t("auth.login.enterBoth"));
      return;
    }
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("auth.login.failed"));
      if (err instanceof ApiError && err.code === "email_unverified") {
        setUnverified(true);
      }
    } finally {
      setBusy(false);
    }
  }

  async function onResendVerification() {
    setResending(true);
    try {
      // The endpoint answers generically; the copy below mirrors
      // that honesty ("if the account still needs it…").
      await api("/core/resend-verification", {
        method: "POST",
        body: JSON.stringify({ email: email.trim() }),
      });
      setResent(true);
    } catch {
      setResent(true); // a failed resend shows the same state — no oracle, no dead end
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.login.title")}
      footer={
        <>
          {t("auth.login.newHere")}{" "}
          {/* Sweep C2 completion: the kept destination rides along
              to signup in the same router state, so a visitor who
              creates an account instead of signing in still lands
              on what they clicked (via the post-signup return to
              this page). A plain /login arrival carries no state —
              the link behaves exactly as before. */}
          <Link
            to="/signup"
            state={showDoorNotice ? { from: doorDestination } : undefined}
            className="tv-auth-link"
          >
            {t("auth.login.createAccount")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="tv-auth-stack">
        {showDoorNotice && (
          <Alert tone="info">{t("auth.login.doorNotice")}</Alert>
        )}
        <FormField label={t("auth.login.email")} htmlFor="li-email" required>
          <TextInput
            id="li-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </FormField>
        <FormField label={t("auth.login.password")} htmlFor="li-password" required>
          <TextInput
            id="li-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </FormField>
        <p className="tv-auth-forgot-row">
          <Link to="/forgot-password" className="tv-auth-link">
            {t("auth.login.forgot")}
          </Link>
        </p>
        {error && <Alert tone="danger">{error}</Alert>}
        {unverified &&
          (resent ? (
            <Alert tone="success">{t("auth.login.resent")}</Alert>
          ) : (
            <Button
              type="button"
              variant="secondary"
              loading={resending}
              onClick={() => void onResendVerification()}
            >
              {resending ? t("auth.login.resending") : t("auth.login.resend")}
            </Button>
          ))}
        <Button type="submit" loading={busy}>
          {busy ? t("auth.login.busy") : t("auth.login.submit")}
        </Button>
      </form>
      <SocialButtons next={showDoorNotice ? doorDestination : null} />
    </AuthLayout>
  );
}
