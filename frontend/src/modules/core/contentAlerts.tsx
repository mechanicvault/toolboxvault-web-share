/**
 * New-content alert boxes (sweep E4, busy-work #6): the
 * opt-in toggles for "new file downloads" and "new 3D print
 * files" inbox notifications.
 *
 * One component, three seats: the Downloads page (documents
 * box), the 3D Print Files shelf (prints box), and Settings ->
 * Notifications (both, rendered by the settings section with
 * its own row markup over these same API helpers). Every box
 * defaults OFF on the server; the toggle states the choice in
 * words beside the switch. Signed-out visitors never see the
 * component — an inbox opt-in needs an account, and a dead
 * control is worse than none.
 */

import { useEffect, useState } from "react";

import { Toggle } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import { api } from "../../lib/api";
import { useAuth } from "./AuthContext";

export interface ContentAlertPrefs {
  downloads: boolean;
  prints: boolean;
}

export type ContentAlertKind = keyof ContentAlertPrefs;

export function getContentAlerts(): Promise<ContentAlertPrefs> {
  return api<ContentAlertPrefs>("/core/me/content-alerts");
}

export function putContentAlert(
  kind: ContentAlertKind,
  enabled: boolean,
): Promise<ContentAlertPrefs> {
  return api<ContentAlertPrefs>("/core/me/content-alerts", {
    method: "PUT",
    body: JSON.stringify({ kind, enabled }),
  });
}

const LABELS: Record<ContentAlertKind, { name: DictKey; help: DictKey }> = {
  downloads: { name: "alerts.downloads", help: "alerts.downloadsHelp" },
  prints: { name: "alerts.prints", help: "alerts.printsHelp" },
};

export function ContentAlertToggle({ kind }: { kind: ContentAlertKind }) {
  const t = useT();
  const { user } = useAuth();
  const [value, setValue] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    let live = true;
    getContentAlerts()
      .then((prefs) => {
        if (live) setValue(prefs[kind]);
      })
      .catch(() => {
        if (live) setValue(null);
      });
    return () => {
      live = false;
    };
  }, [user, kind]);

  if (!user || value === null) return null;

  async function flip(next: boolean) {
    setSaving(true);
    try {
      const saved = await putContentAlert(kind, next);
      setValue(saved[kind]);
    } catch {
      /* The switch keeps its old state; the next page load
       * re-reads the server's answer. */
    } finally {
      setSaving(false);
    }
  }

  const labels = LABELS[kind];
  return (
    <div className="ca-alert-row">
      <div className="ca-alert-text">
        <p className="ca-alert-name">{t(labels.name)}</p>
        <p className="ca-alert-help">{t(labels.help)}</p>
      </div>
      <Toggle
        checked={value}
        disabled={saving}
        onChange={(v) => void flip(v)}
        ariaLabel={t(labels.name)}
      />
    </div>
  );
}
