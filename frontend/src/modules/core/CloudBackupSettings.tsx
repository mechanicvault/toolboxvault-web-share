import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Alert,
  Badge,
  Button,
  Panel,
  Select,
  Spinner,
  useToast,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { activeLocale } from "../../lib/format";
import { api, ApiError } from "../../lib/api";
import { formatBytes } from "../../components";

function displayDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(activeLocale());
}

/** Settings → Cloud backup (wave 4): automatic backups of the
 *  account's own export ZIP to the user's OWN Google Drive.
 *
 *  The connection asks Google for the drive.file scope ONLY —
 *  the app can see and touch just the files it creates. Backups
 *  keep the newest 7 in a "Toolbox Vault Backups" folder; the
 *  history below is the ledger of every attempt. Restoring stays
 *  the ordinary machinery: a backup IS the Export ZIP, and its
 *  contents come back through Inventory → Import. */

interface CloudRun {
  id: string;
  trigger: string;
  status: string;
  file_name: string;
  size_bytes: number;
  error: string;
  started_at: string;
  finished_at: string | null;
  drive_url: string | null;
}

interface CloudState {
  connected: boolean;
  folder_name: string;
  schedule: string;
  connected_at: string | null;
  last_backup_at: string | null;
  history: CloudRun[];
}

export default function CloudBackupSettings() {
  const { toast } = useToast();
  const t = useT();
  const [params, setParams] = useSearchParams();
  const [state, setState] = useState<CloudState | null>(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api<CloudState>("/core/cloud-backup");
      setState(data);
      setLoadError("");
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("settings.cloudBackup.loadFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  // The connect callback lands back here with ?cloud=… — toast
  // the outcome once and clean the URL.
  useEffect(() => {
    const flag = params.get("cloud");
    if (!flag) return;
    if (flag === "connected") {
      toast(t("settings.cloudBackup.connectedToast"), { tone: "success" });
    } else if (flag === "denied") {
      toast(t("settings.cloudBackup.deniedToast"), { tone: "danger" });
    } else {
      toast(t("settings.cloudBackup.failedToast"), { tone: "danger" });
    }
    params.delete("cloud");
    setParams(params, { replace: true });
    void load();
  }, [params, setParams, toast, load, t]);

  async function connect() {
    setBusy(true);
    try {
      const data = await api<{ authorize_url: string }>("/core/cloud-backup/connect");
      window.location.href = data.authorize_url;
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : t("settings.cloudBackup.connectFailed"),
        { tone: "danger" },
      );
      setBusy(false);
    }
  }

  async function setSchedule(schedule: string) {
    setBusy(true);
    try {
      const data = await api<CloudState>("/core/cloud-backup/schedule", {
        method: "PUT",
        body: JSON.stringify({ schedule }),
      });
      setState(data);
      toast(t("settings.cloudBackup.scheduleSaved"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("settings.cloudBackup.saveFailed"), {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function runNow() {
    setBusy(true);
    try {
      const data = await api<CloudState>("/core/cloud-backup/run", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setState(data);
      const latest = data.history[0];
      if (latest?.status === "ok") {
        toast(t("settings.cloudBackup.backupSaved"), { tone: "success" });
      } else {
        toast(latest?.error || t("settings.cloudBackup.backupIncomplete"), {
          tone: "danger",
        });
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("settings.cloudBackup.backupFailed"), {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      const data = await api<CloudState>("/core/cloud-backup/disconnect", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setState(data);
      setConfirmingDisconnect(false);
      toast(t("settings.cloudBackup.disconnectedToast"), { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : t("settings.cloudBackup.disconnectFailed"), {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={t("settings.cloudBackup.title")} variant="plate">
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        {t("settings.cloudBackup.introLead")}
        <strong>{t("settings.cloudBackup.introStrong")}</strong>
        {t("settings.cloudBackup.introTail")}
      </p>
      {loadError && <Alert tone="danger">{loadError}</Alert>}
      {!state && !loadError && (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> {t("shell.loading")}
        </p>
      )}
      {state && !state.connected && (
        <div>
          <Button onClick={() => void connect()} loading={busy}>
            {t("settings.cloudBackup.connectButton")}
          </Button>
          <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
            {t("settings.cloudBackup.connectNote")}
          </p>
        </div>
      )}
      {state?.connected && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <Badge tone="success">{t("settings.cloudBackup.connectedBadge")}</Badge>
            <span>
              {t("settings.cloudBackup.folderLead")}{" "}
              <strong>{state.folder_name || "Toolbox Vault Backups"}</strong>
            </span>
            {state.last_backup_at && (
              <span style={{ color: "var(--text-muted)" }}>
                {t("settings.cloudBackup.lastBackup").replace(
                  "{date}",
                  displayDateTime(state.last_backup_at),
                )}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
            <div>
              <label className="tv-field-label" htmlFor="cb-schedule">
                {t("settings.cloudBackup.scheduleLabel")}
              </label>
              <Select
                id="cb-schedule"
                value={state.schedule}
                disabled={busy}
                onChange={(e) => void setSchedule(e.target.value)}
              >
                <option value="off">{t("settings.cloudBackup.scheduleOff")}</option>
                <option value="daily">{t("settings.cloudBackup.scheduleDaily")}</option>
                <option value="weekly">{t("settings.cloudBackup.scheduleWeekly")}</option>
                <option value="monthly">{t("settings.cloudBackup.scheduleMonthly")}</option>
              </Select>
            </div>
            <Button onClick={() => void runNow()} loading={busy}>
              {t("settings.cloudBackup.backUpNow")}
            </Button>
            {confirmingDisconnect ? (
              <>
                <span>{t("settings.cloudBackup.disconnectPrompt")}</span>
                <Button variant="danger" onClick={() => void disconnect()} loading={busy}>
                  {t("settings.cloudBackup.yesDisconnect")}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setConfirmingDisconnect(false)}
                >
                  {t("settings.cloudBackup.keepIt")}
                </Button>
              </>
            ) : (
              <Button
                variant="secondary"
                onClick={() => setConfirmingDisconnect(true)}
              >
                {t("settings.cloudBackup.disconnect")}
              </Button>
            )}
          </div>
        </div>
      )}
      {state && state.history.length > 0 && (
        <div style={{ marginTop: "1.25rem" }}>
          <h3 style={{ marginTop: 0 }}>{t("settings.cloudBackup.historyTitle")}</h3>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "0.5rem" }}>
            {state.history.map((run) => (
              <li
                key={run.id}
                style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}
              >
                <Badge tone={run.status === "ok" ? "success" : run.status === "failed" ? "danger" : "neutral"}>
                  {run.status === "ok"
                    ? t("settings.cloudBackup.statusOk")
                    : run.status === "failed"
                      ? t("settings.cloudBackup.statusFailed")
                      : run.status}
                </Badge>
                <span>{displayDateTime(run.started_at)}</span>
                <span style={{ color: "var(--text-muted)" }}>
                  {run.trigger === "manual"
                    ? t("settings.cloudBackup.triggerManual")
                    : t("settings.cloudBackup.triggerScheduled")}
                </span>
                {run.status === "ok" ? (
                  <span>
                    {run.file_name} · {formatBytes(run.size_bytes)}
                  </span>
                ) : (
                  <span style={{ color: "var(--text-muted)" }}>{run.error}</span>
                )}
                {run.drive_url && (
                  <a href={run.drive_url} target="_blank" rel="noreferrer">
                    {t("settings.cloudBackup.openInDrive")}
                  </a>
                )}
              </li>
            ))}
          </ul>
          <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
            {t("settings.cloudBackup.restoreNote")}
          </p>
        </div>
      )}
    </Panel>
  );
}
