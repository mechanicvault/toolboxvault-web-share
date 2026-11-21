import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, useToast } from "../../components";
import { useLocale, useT } from "../../i18n/LocaleContext";
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

export default function SessionsSettings() {
  const { toast } = useToast();
  const t = useT();
  const { locale } = useLocale();
  const [sessions, setSessions] = useState<SessionView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  // Session dates render in the ACCOUNT's locale (owner rule:
  // single language everywhere) — never the browser's default.
  function fmtWhen(iso: string): string {
    return new Date(iso).toLocaleString(locale, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

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
        err instanceof ApiError ? err.message : t("settings.sessions.loadFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function signOut(session: SessionView) {
    setBusyId(session.id);
    try {
      await api(`/core/sessions/${session.id}`, { method: "DELETE" });
      toast(t("settings.sessions.signedOutToast"), { tone: "success" });
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("settings.sessions.signOutFailed"),
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
          ? t(
              res.ended === 1
                ? "settings.sessions.signedOutOne"
                : "settings.sessions.signedOutMany",
            ).replace("{count}", String(res.ended))
          : t("settings.sessions.noneToSignOut"),
        { tone: "success" },
      );
      await load();
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.sessions.signOutOthersFailed"),
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
      <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
        {t("settings.sessions.title")}
      </p>
      {sessions && sessions.length > 0 && (
        <p style={{ color: "var(--text-muted)", margin: "0 0 var(--space-2)" }}>
          {t(
            sessions.length === 1
              ? "settings.sessions.activeOne"
              : "settings.sessions.activeMany",
          ).replace("{count}", String(sessions.length))}
          {others.length === 0
            ? t("settings.sessions.onlyThisDevice")
            : others.length < sessions.length
              ? t(
                  others.length === 1
                    ? "settings.sessions.thisDeviceAndOne"
                    : "settings.sessions.thisDeviceAndMany",
                ).replace("{count}", String(others.length))
              : t("settings.sessions.allOtherDevices")}
        </p>
      )}
      {others.length > 0 && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          <Button
            variant="secondary"
            loading={busyId === "others"}
            onClick={() => void signOutOthers()}
          >
            {t("settings.sessions.signOutEverywhereElse")}
          </Button>
        </div>
      )}
      {error && <Alert tone="danger">{error}</Alert>}
      {sessions === null && !error && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.sessions.loading")}
        </p>
      )}
      {sessions && sessions.length === 0 && (
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {t("settings.sessions.noneFound")}
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
                  <span style={{ fontWeight: 700 }}>
                    {session.user_agent ?? t("settings.sessions.unknownDevice")}
                  </span>
                  {session.is_current && (
                    <Badge tone="success">{t("settings.sessions.thisDevice")}</Badge>
                  )}
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: "var(--font-size-sm)" }}>
                  {t("settings.sessions.signedIn").replace(
                    "{date}",
                    fmtWhen(session.created_at),
                  )}{" "}
                  ·{" "}
                  {t("settings.sessions.lastActive").replace(
                    "{date}",
                    fmtWhen(session.last_used_at),
                  )}
                </div>
              </div>
              {!session.is_current && (
                <Button
                  variant="secondary"
                  loading={busyId === session.id}
                  onClick={() => void signOut(session)}
                >
                  {t("settings.sessions.signOut")}
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
              ? t("settings.sessions.showFewer")
              : t("settings.sessions.showAll").replace(
                  "{count}",
                  String(sessions.length),
                )}
          </Button>
        </div>
      )}
    </div>
  );
}
