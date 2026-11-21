import { useState } from "react";
import { Navigate } from "react-router-dom";
import { formatDate } from "../../../lib/format";
import { Avatar, Badge, Button, Panel, Spinner, useToast } from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { useAuth } from "../AuthContext";

function detail(label: string, value: string) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "0.5rem" }}>
      <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
      <dd style={{ margin: 0, fontWeight: 600 }}>{value}</dd>
    </div>
  );
}

/** "Me" page: profile, account number, sign out. */
export default function AccountPage() {
  const { user, loading, logout } = useAuth();
  const { toast } = useToast();
  const t = useT();
  const [resending, setResending] = useState(false);

  /* Sheet row 105 (2026-11-18): an unverified email showed its
   * "Not yet" badge here with no way to act on it — the resend
   * lived only in Settings. The same resend (same endpoint,
   * same words as Settings) now sits beside the badge. */
  async function onResendVerification() {
    setResending(true);
    try {
      await api("/core/me/resend-verification", { method: "POST" });
      toast(t("settings.email.verificationSentToast"), {
        tone: "success",
        duration: 8000,
      });
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.email.verificationSendFailed"),
        { tone: "danger" },
      );
    } finally {
      setResending(false);
    }
  }
  if (loading) {
    return (
      <p
        style={{
          color: "var(--text-muted)",
          display: "flex",
          gap: "var(--space-2)",
          alignItems: "center",
        }}
      >
        <Spinner size="sm" /> Loading…
      </p>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div style={{ maxWidth: "640px", margin: "0 auto", display: "grid", gap: "var(--spacing)" }}>
        <Panel title="Your account" variant="accent-edge">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-3)",
              margin: "0 0 1rem",
            }}
          >
            <Avatar name={user.name} size="lg" />
            <p
              style={{
                fontSize: "1.5rem",
                fontWeight: 700,
                color: "var(--accent)",
                letterSpacing: "0.05em",
                margin: 0,
              }}
            >
              {user.account_number}
            </p>
          </div>
          <dl style={{ display: "grid", gap: "0.6rem", margin: "0 0 1.25rem" }}>
            {detail("Name", user.name)}
            {detail("Email", user.email)}
            <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "0.5rem" }}>
              <dt style={{ color: "var(--text-muted)" }}>Email verified</dt>
              <dd style={{ margin: 0, display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
                <Badge tone={user.email_verified ? "success" : "warning"} dot>
                  {user.email_verified ? "Verified" : "Not yet"}
                </Badge>
                {!user.email_verified && (
                  <Button
                    type="button"
                    variant="secondary"
                    loading={resending}
                    onClick={() => void onResendVerification()}
                  >
                    {resending
                      ? t("settings.email.sending")
                      : t("settings.email.resendVerification")}
                  </Button>
                )}
              </dd>
            </div>
            {detail(
              "Member since",
              formatDate(user.created_at),
            )}
          </dl>
          <Button variant="secondary" onClick={logout}>
            Log out
          </Button>
        </Panel>
      </div>
  );
}
