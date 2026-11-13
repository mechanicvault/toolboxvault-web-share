import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, useToast } from "../../components";
import { api, ApiError, REFRESH_TOKEN_KEY } from "../../lib/api";

/**
 * Settings → Account & security → Your sessions: every live
 * sign-in (one entry per refresh-token chain), where it started,
 * and the sign-out controls. The current session is identified by
 * sending our own refresh token in X-Current-Session — the same
 * trust as a refresh call.
 */

interface SessionView {
  id: string;
  created_at: string;
  last_used_at: string;
  user_agent: string | null;
  is_current: boolean;
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function SessionsSettings() {
  const { toast } = useToast();
  const [sessions, setSessions] = useState<SessionView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<SessionView[]>("/core/sessions", {
        headers: {
          "X-Current-Session": localStorage.getItem(REFRESH_TOKEN_KEY) ?? "",
        },
      });
      setSessions(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't load your sessions.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function signOut(session: SessionView) {
    setBusyId(session.id);
    try {
      await api(`/core/sessions/${session.id}`, { method: "DELETE" });
      toast("That session was signed out.", { tone: "success" });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't sign that session out.",
        { tone: "danger" },
      );
    } finally {
      setBusyId(null);
    }
  }

  async function signOutOthers() {
    setBusyId("others");
    try {
      const res = await api<{ ended: number }>("/core/sessions/revoke-others", {
        method: "POST",
        body: JSON.stringify({
          refresh_token: localStorage.getItem(REFRESH_TOKEN_KEY),
        }),
      });
      toast(
        res.ended > 0
          ? `Signed out ${res.ended} other session${res.ended === 1 ? "" : "s"}.`
          : "No other sessions to sign out.",
        { tone: "success" },
      );
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't sign out other sessions.",
        { tone: "danger" },
      );
    } finally {
      setBusyId(null);
    }
  }

  const others = sessions?.filter((s) => !s.is_current) ?? [];
  // Sweep B9 (09-F7): the list is BOUNDED — the recent sessions
  // show first and the rest wait behind a "show all" expander,
  // so a long-lived account's page stays a page, not a scroll
  // of thousands of rows. The one control that matters ("Sign
  // out everywhere else") sits at the TOP, above the list.
  const SESSION_PREVIEW_COUNT = 10;
  const visibleSessions =
    sessions && !showAll
      ? sessions.slice(0, SESSION_PREVIEW_COUNT)
      : sessions;

  return (
    <div>
      <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>Your sessions</p>
      {sessions && sessions.length > 0 && (
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
          {sessions.length} active session{sessions.length === 1 ? "" : "s"}
          {others.length === 0
            ? " — this device only."
            : others.length < sessions.length
              ? ` — this device and ${others.length} other${others.length === 1 ? "" : "s"}.`
              : ` — all on other devices.`}
        </p>
      )}
      {others.length > 0 && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          <Button
            variant="secondary"
            loading={busyId === "others"}
            onClick={() => void signOutOthers()}
          >
            Sign out everywhere else
          </Button>
        </div>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {sessions === null && !error && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>Loading sessions…</p>
      )}
      {sessions && sessions.length === 0 && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          No active sessions found.
        </p>
      )}
      {sessions && sessions.length > 0 && (
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "grid",
            gap: "0.6rem",
          }}
        >
          {(visibleSessions ?? []).map((session) => (
            <li
              key={session.id}
              className="tv-setting-row"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                flexWrap: "wrap",
              }}
            >
              <div>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <span style={{ fontWeight: 600 }}>
                    {session.user_agent ?? "Unknown device"}
                  </span>
                  {session.is_current && <Badge tone="success">This device</Badge>}
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: "0.88rem" }}>
                  Signed in {fmtWhen(session.created_at)} · last active{" "}
                  {fmtWhen(session.last_used_at)}
                </div>
              </div>
              {!session.is_current && (
                <Button
                  variant="secondary"
                  loading={busyId === session.id}
                  onClick={() => void signOut(session)}
                >
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {sessions && sessions.length > SESSION_PREVIEW_COUNT && (
        <div style={{ marginTop: "var(--space-3)" }}>
          <Button variant="secondary" onClick={() => setShowAll((v) => !v)}>
            {showAll
              ? "Show fewer sessions"
              : `Show all ${sessions.length} sessions`}
          </Button>
        </div>
      )}
    </div>
  );
}
