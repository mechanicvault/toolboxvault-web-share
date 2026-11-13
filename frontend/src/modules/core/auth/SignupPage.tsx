import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { Alert, Button, FormField, TextInput, LinkButton } from "../../../components";
import { ApiError } from "../../../lib/api";
import { useAuth, type User } from "../AuthContext";
import { AuthLayout } from "./AuthLayout";
import { useT } from "../../../i18n/LocaleContext";
import {
  fetchLandingConfig,
  fetchSignupGate,
  unlockSignup,
  LANDING_FALLBACK,
  type SignupGate,
} from "../landing";
import { SocialButtons } from "./SocialButtons";

/** Signup (owner design 2026-10-31, built 2026-11-07): creating
 *  an account asks for LOGIN CREDENTIALS ONLY — name, email,
 *  password, an optional referral code. No account type, no
 *  country/currency/language, no module picks: the account is
 *  born bare and the onboarding wizard (Home banner → /setup)
 *  walks the new user through all of it afterwards, each step
 *  explained and skippable. Until the wizard sets them, the
 *  account runs on the standing defaults (US / USD / English).
 *  Success shows the new account number, exactly as before.
 *
 *  OPEN SIGNUP (owner order, 2026-11-09): the form is no longer
 *  walled by the teaser gate. While the teaser is on and this
 *  browser holds no unlock, one extra OPTIONAL field asks for
 *  the full-access code: with a valid code the account is born
 *  on the normal level with the full site, exactly as before;
 *  with no code it is born on the downloads level (Downloads +
 *  3D Print Files) and the created screen says so plainly. A
 *  typed code that is wrong is an honest error at the field
 *  and no account is created — never a silent downgrade. The
 *  server decides the level from the same posture
 *  (teaser.signup_tier); this form is its honest face. */
export default function SignupPage() {
  const t = useT();
  const { user, signup } = useAuth();
  const location = useLocation();
  /* Sweep C2 completion: the sign-in door's "Create an account"
   * link carries the kept destination in the same router state
   * the door itself received (state.from). It is handed back to
   * /login on both exits from this page (the footer's Log in link
   * and the created screen's button), so the post-signup sign-in
   * lands on what the visitor originally clicked — through the
   * EXISTING sign-in return, gate and all, not a second mechanism.
   * It also feeds this page's social buttons. Only a same-site
   * path is honoured; no state (a plain /signup arrival) leaves
   * every behaviour below exactly as before. */
  const rawFrom = (location.state as { from?: unknown } | null)?.from;
  const keptFrom =
    typeof rawFrom === "string" &&
    rawFrom.startsWith("/") &&
    !rawFrom.startsWith("//") &&
    !rawFrom.includes("\\")
      ? rawFrom
      : null;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [created, setCreated] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  /* F2-14: ONE validation model — per-field errors tied to their
   * fields (FormField error + aria via htmlFor), and focus moves
   * to the first problem. The page-level Alert now carries only
   * server failures, never a bucket of field problems, so a stale
   * alert can never contradict the field that is actually wrong. */
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const clearField = (key: string) =>
    setFieldErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  // The free tier's item limit, from the plan catalog via the
  // public landing config (assessment catch, 2026-10-20: this
  // page never said what free means). Falls back to the seeded
  // default if the fetch fails — the same number either way.
  const [freeLimit, setFreeLimit] = useState(LANDING_FALLBACK.free_item_limit);
  /* The signup gate posture (teaser mode): null while this
   * browser's posture is being read. It no longer walls the
   * form (open signup, 2026-11-09) — it only decides whether
   * the optional full-access code field shows. A failed read
   * renders the plain form, and the server still decides the
   * new account's level from its own posture. */
  const [gate, setGate] = useState<SignupGate | null>(null);
  const [gateCode, setGateCode] = useState("");
  const [gateError, setGateError] = useState("");

  useEffect(() => {
    let live = true;
    void fetchSignupGate()
      .then((posture) => {
        if (live) setGate(posture);
      })
      .catch(() => {
        if (live) setGate({ teaser_mode: false, unlocked: true });
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    let live = true;
    void fetchLandingConfig().then((config) => {
      if (live) setFreeLimit(config.free_item_limit);
    });
    return () => {
      live = false;
    };
  }, []);

  if (user) return <Navigate to={keptFrom ?? "/"} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = t("auth.signup.nameRequired");
    if (!email.trim()) errs.email = t("auth.signup.emailRequired");
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
      errs.email = t("auth.signup.emailInvalid");
    if (!password) errs.password = t("auth.signup.passwordRequired");
    else if (password.length < 6) errs.password = t("auth.signup.shortPassword");
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) {
      const ids: Record<string, string> = {
        name: "su-name",
        email: "su-email",
        password: "su-password",
      };
      for (const key of ["name", "email", "password"]) {
        if (!(key in errs)) continue;
        document.getElementById(ids[key]!)?.focus();
        break;
      }
      return;
    }
    setBusy(true);
    setGateError("");
    try {
      // A typed full-access code unlocks THIS browser first:
      // the signup that follows is then born on the normal
      // level. A wrong code stops here with the honest error —
      // no account is created on a guess.
      if (gate?.teaser_mode && !gate.unlocked && gateCode.trim()) {
        try {
          setGate(await unlockSignup(gateCode.trim()));
        } catch (err) {
          setGateError(
            err instanceof ApiError ? err.message : t("auth.gate.wrong"),
          );
          return;
        }
      }
      // Credentials only: no account types, no basics — the
      // wizard collects them after the account exists.
      setCreated(
        await signup(name.trim(), email.trim(), password, [], referralCode),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("auth.signup.failed"));
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <AuthLayout title={t("auth.signup.createdTitle")}>
        <p>
          {t("auth.signup.welcome")} <strong>{created.name}</strong>! {t("auth.signup.yourNumber")}
        </p>
        <p className="tv-auth-acct-number">
          {created.account_number}
        </p>
        {created.tier === "downloads" && (
          <p className="tv-auth-muted">{t("auth.signup.createdLimited")}</p>
        )}
        <p className="tv-auth-muted">
          {t("auth.signup.keepHandy")}
        </p>
        <LinkButton
          to="/login"
          state={keptFrom ? { from: keptFrom } : undefined}
          className="tv-auth-mt"
        >
          {t("auth.signup.loginToVault")}
        </LinkButton>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={t("auth.signup.title")}
      footer={
        <>
          {t("auth.signup.haveAccount")}{" "}
          <Link
            to="/login"
            state={keptFrom ? { from: keptFrom } : undefined}
            className="tv-auth-link"
          >
            {t("auth.signup.loginLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="tv-auth-form">
        {/* First paint (sweep 10-F7): the form renders IMMEDIATELY —
         * a visitor never meets a bare "Loading…". While the gate
         * posture is still being read, the optional code field's
         * seat is held by a labelled skeleton in the field's own
         * register, so the real field (when this browser needs
         * one) takes a reserved seat instead of flashing in. The
         * rest of the form is live at once; if a submit somehow
         * beats the posture read, the server still decides the
         * new account's level from its own posture. */}
        {gate === null && (
          <div
            className="tv-field tv-auth-gate-skel"
            role="status"
            aria-label={t("shell.loading")}
            aria-busy="true"
          >
            <span className="tv-field-label">{t("auth.gate.optionalCode")}</span>
            <div className="tv-skel tv-auth-gate-skel-input" aria-hidden="true" />
            <p className="tv-field-hint">{t("auth.gate.codeHint")}</p>
          </div>
        )}
        {gate?.teaser_mode && !gate.unlocked && (
          <>
            <p className="tv-auth-muted">{t("auth.gate.limitedNotice")}</p>
            <FormField
              label={t("auth.gate.optionalCode")}
              htmlFor="su-gate-code"
              hint={t("auth.gate.codeHint")}
              error={gateError || undefined}
            >
              <TextInput
                id="su-gate-code"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                value={gateCode}
                invalid={Boolean(gateError)}
                onChange={(e) => {
                  setGateCode(e.target.value);
                  setGateError("");
                }}
              />
            </FormField>
          </>
        )}
        <FormField label={t("auth.signup.name")} htmlFor="su-name" required error={fieldErrors.name}>
          <TextInput
            id="su-name"
            value={name}
            invalid={Boolean(fieldErrors.name)}
            onChange={(e) => { setName(e.target.value); clearField("name"); }}
            autoComplete="name"
          />
        </FormField>
        <FormField label={t("auth.signup.email")} htmlFor="su-email" required error={fieldErrors.email}>
          <TextInput
            id="su-email"
            type="email"
            value={email}
            invalid={Boolean(fieldErrors.email)}
            onChange={(e) => { setEmail(e.target.value); clearField("email"); }}
            autoComplete="email"
          />
        </FormField>
        {/* The never-sold promise (sweep 10-F16): the standing
         * promise that lives at Downloads' email field, carried
         * VERBATIM (same dictionary keys, same bold-orange
         * "Ever." treatment) to the field where an account's
         * email is actually handed over. */}
        <p className="tv-auth-promise">
          {t("downloads.promise.never")}{" "}
          <span className="tv-auth-ever">{t("downloads.promise.ever")}</span>
        </p>
        <FormField label={t("auth.signup.password")} htmlFor="su-password" required hint={t("auth.signup.passwordHint")} error={fieldErrors.password}>
          <TextInput
            id="su-password"
            type="password"
            value={password}
            invalid={Boolean(fieldErrors.password)}
            onChange={(e) => { setPassword(e.target.value); clearField("password"); }}
            autoComplete="new-password"
          />
        </FormField>
        <FormField
          label={t("auth.signup.referral")}
          htmlFor="su-referral"
          hint={t("auth.signup.referralHint")}
        >
          {/* Referral example (sweep 10-F16): the example code is
           * a HINT, never a look-alike value — it wears the
           * dedicated example register (.tv-input--example
           * placeholder: muted, italic, reduced opacity in every
           * theme) so no visitor can mistake it for a pre-filled
           * stranger's code. The field itself starts EMPTY and
           * nothing ever injects a referral into it: the only
           * writer is the visitor's own typing (verified — the
           * state initialises "" and no effect, param, or fetch
           * sets it). */}
          <TextInput
            id="su-referral"
            className="tv-input--example"
            value={referralCode}
            onChange={(e) => setReferralCode(e.target.value)}
            autoComplete="off"
            placeholder={t("auth.signup.referralExample")}
          />
        </FormField>
        {error && <Alert tone="danger">{error}</Alert>}
        <Button type="submit" loading={busy} block>
          {busy ? t("auth.signup.busy") : t("auth.signup.submit")}
        </Button>
        <p className="tv-auth-agree">
          {t("auth.signup.agree")}{" "}
          <Link to="/terms" className="tv-auth-link">
            {t("auth.signup.terms")}
          </Link>{" "}
          {t("auth.signup.and")}{" "}
          <Link to="/privacy" className="tv-auth-link">
            {t("auth.signup.privacy")}
          </Link>
          .
        </p>
      </form>
      <p className="tv-auth-free-note">
{t("auth.signup.freeBefore")} {freeLimit} {t("auth.signup.freeAfter")}
      </p>
      <SocialButtons next={keptFrom} />
    </AuthLayout>
  );
}
