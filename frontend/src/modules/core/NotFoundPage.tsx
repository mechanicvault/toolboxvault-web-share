import { useLocation } from "react-router-dom";
import { Panel, LinkButton } from "../../components";
import { useAuth } from "./AuthContext";

/**
 * Catch-all 404 (completeness audit A4): any path no registry route
 * claims lands here. The shell around it already does the right
 * thing in both states — signed-in users keep their nav, signed-out
 * visitors get the plain header — so the page itself just explains
 * and offers the way home. Unknown API routes are unaffected (the
 * backend still answers those with JSON 404s).
 */
export function NotFoundPage() {
  const { user } = useAuth();
  const location = useLocation();
  return (
    <div className="tv-notfound" style={{ maxWidth: 560, margin: "10vh auto 0", padding: "0 var(--space-4)" }}>
      <Panel>
        <div style={{ display: "grid", gap: "var(--space-3)", textAlign: "center" }}>
          <p className="tv-notfound-code">
            404 — page not found
          </p>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            There's nothing at{" "}
            <code style={{ color: "var(--text)" }}>{location.pathname}</code> — the
            page may have moved, or the link may be mistyped.
          </p>
          <div
            style={{
              display: "flex",
              gap: "var(--space-2)",
              justifyContent: "center",
              flexWrap: "wrap",
            }}
          >
            <LinkButton to="/">{user ? "Go to my home page" : "Go to the home page"}</LinkButton>
            {user ? (
              <LinkButton to="/inventory" variant="secondary">Open my inventory</LinkButton>
            ) : (
              <LinkButton to="/login" variant="secondary">Log in</LinkButton>
            )}
          </div>
        </div>
      </Panel>
    </div>
  );
}
