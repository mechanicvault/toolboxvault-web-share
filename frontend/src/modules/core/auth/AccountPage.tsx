import { Navigate } from "react-router-dom";
import { formatDate } from "../../../lib/format";
import { Avatar, Badge, Button, Panel, Spinner } from "../../../components";
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
              <dd style={{ margin: 0 }}>
                <Badge tone={user.email_verified ? "success" : "warning"} dot>
                  {user.email_verified ? "Verified" : "Not yet"}
                </Badge>
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
