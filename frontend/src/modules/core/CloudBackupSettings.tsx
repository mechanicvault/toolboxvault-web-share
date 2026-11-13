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
import { api, ApiError } from "../../lib/api";
import { formatBytes } from "../../components";

function displayDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
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
        err instanceof ApiError ? err.message : "Couldn't load backup settings.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The connect callback lands back here with ?cloud=… — toast
  // the outcome once and clean the URL.
  useEffect(() => {
    const flag = params.get("cloud");
    if (!flag) return;
    if (flag === "connected") {
      toast("Google Drive connected", { tone: "success" });
    } else if (flag === "denied") {
      toast("Drive connection was cancelled.", { tone: "danger" });
    } else {
      toast("Drive connection didn't finish — try again.", { tone: "danger" });
    }
    params.delete("cloud");
    setParams(params, { replace: true });
    void load();
  }, [params, setParams, toast, load]);

  async function connect() {
    setBusy(true);
    try {
      const data = await api<{ authorize_url: string }>("/core/cloud-backup/connect");
      window.location.href = data.authorize_url;
    } catch (err) {
      toast(
        err instanceof ApiError
          ? err.message
          : "Couldn't start the Drive connection.",
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
      toast("Backup schedule saved", { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save.", {
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
        toast("Backup saved to Google Drive", { tone: "success" });
      } else {
        toast(latest?.error || "That backup didn't complete.", {
          tone: "danger",
        });
      }
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Backup failed.", {
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
      toast("Google Drive disconnected", { tone: "success" });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't disconnect.", {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Cloud backup" variant="plate">
      <p style={{ color: "var(--text-muted)", marginTop: 0 }}>
        Send a full backup of your account — the same ZIP the Export
        button makes — to your own Google Drive, automatically. We
        ask Google for access to <strong>only the files this app
        creates</strong> (the drive.file permission); the app can't
        see anything else in your Drive. The newest 7 backups are
        kept in a folder called “Toolbox Vault Backups”.
      </p>
      {loadError && <Alert tone="danger">{loadError}</Alert>}
      {!state && !loadError && (
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> Loading…
        </p>
      )}
      {state && !state.connected && (
        <div>
          <Button onClick={() => void connect()} loading={busy}>
            Connect Google Drive
          </Button>
          <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
            You'll sign in with Google and approve the connection.
            Connecting never uploads anything by itself — backups run
            on the schedule you pick afterwards (weekly to start).
          </p>
        </div>
      )}
      {state?.connected && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <Badge tone="success">Connected</Badge>
            <span>
              Folder: <strong>{state.folder_name || "Toolbox Vault Backups"}</strong>
            </span>
            {state.last_backup_at && (
              <span style={{ color: "var(--text-muted)" }}>
                Last backup {displayDateTime(state.last_backup_at)}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
            <div>
              <label className="tv-field-label" htmlFor="cb-schedule">
                Automatic backups
              </label>
              <Select
                id="cb-schedule"
                value={state.schedule}
                disabled={busy}
                onChange={(e) => void setSchedule(e.target.value)}
              >
                <option value="off">Off</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </Select>
            </div>
            <Button onClick={() => void runNow()} loading={busy}>
              Back up now
            </Button>
            {confirmingDisconnect ? (
              <>
                <span>Disconnect? Stored access is wiped; backups already in your Drive stay there.</span>
                <Button variant="danger" onClick={() => void disconnect()} loading={busy}>
                  Yes, disconnect
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setConfirmingDisconnect(false)}
                >
                  Keep it
                </Button>
              </>
            ) : (
              <Button
                variant="secondary"
                onClick={() => setConfirmingDisconnect(true)}
              >
                Disconnect
              </Button>
            )}
          </div>
        </div>
      )}
      {state && state.history.length > 0 && (
        <div style={{ marginTop: "1.25rem" }}>
          <h3 style={{ marginTop: 0 }}>Backup history</h3>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "0.5rem" }}>
            {state.history.map((run) => (
              <li
                key={run.id}
                style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}
              >
                <Badge tone={run.status === "ok" ? "success" : run.status === "failed" ? "danger" : "neutral"}>
                  {run.status}
                </Badge>
                <span>{displayDateTime(run.started_at)}</span>
                <span style={{ color: "var(--text-muted)" }}>
                  {run.trigger === "manual" ? "Manual" : "Scheduled"}
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
                    Open in Drive
                  </a>
                )}
              </li>
            ))}
          </ul>
          <p style={{ color: "var(--text-muted)", marginBottom: 0 }}>
            To restore from a backup, download it from Drive and bring
            its contents back through Inventory → Import — a
            backup file is the exact ZIP the Export button produces.
          </p>
        </div>
      )}
    </Panel>
  );
}
