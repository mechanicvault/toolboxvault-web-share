import { useCallback, useEffect, useState, type CSSProperties } from "react";

import {
  Alert,
  Badge,
  Checkbox,
  Panel,
  Spinner,
  Toggle,
  useToast,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { ACCOUNT_TYPE_OPTIONS } from "../accountTypes";
import { RequireAuth } from "../auth/RequireAuth";
import { useT } from "../../../i18n/LocaleContext";
import { AdminShell } from "./AdminShell";

/**
 * Admin → Modules (module doctrine, owner 2026-10-18): the operator
 * control surface for feature modules. One card per module with its
 * manifest (what it provides, what it depends on), the global kill
 * switch, one checkbox per account group, and — since the account
 * tiers (2026-10-31) — one checkbox per account tier, so a module
 * can be staged: lit for staff and beta testers while normal
 * accounts don't have it yet, then released. (The God account
 * bypasses every switch and always sees all modules.) Every save
 * goes to /api/admin/modules and the card re-renders from the
 * server's answer — the matrix the operator sees is always the
 * matrix the site is enforcing.
 */

interface AdminModuleState {
  id: string;
  name: string;
  version: string;
  description: string;
  provides: string[];
  depends_on: string[];
  default_groups: string[];
  nav: { label: string; path: string; order: number } | null;
  globally_enabled: boolean;
  groups: Record<string, boolean>;
  /** Per-tier switches (2026-10-31): normal | moderator |
   *  moderator_admin | beta. */
  tiers: Record<string, boolean>;
  dependency_status: string; // "ok" | "blocked by <dep>" | graph reason
}

/** The tiers an operator can light or darken per module, in
 *  rollout order: staff first, then beta testers, then everyone. */
const MODULE_TIER_OPTIONS = [
  { value: "moderator_admin", label: "Moderator admins" },
  { value: "moderator", label: "Moderators" },
  { value: "beta", label: "Beta testers" },
  { value: "normal", label: "Normal accounts" },
  // The downloads level (2026-11-09) stands apart from the
  // ladder: it inherits nothing and nothing inherits it, so its
  // switch is its own audience — lighting a module here is a
  // RELEASE to those accounts (badge, announcement, wizard).
  { value: "downloads", label: "Downloads accounts" },
];

/** 09b-F5: manifest codes (AI_IDENTIFICATION, ai_assistant) read
 *  as plain words on the cards — the descriptions already are
 *  plain; the names now match them. Display only: the ids the API
 *  routes on are untouched. */
function humanizeCode(code: string): string {
  const words = code.split(/[_\s]+/).filter(Boolean);
  return words
    .map((w, i) => {
      if (w.toLowerCase() === "ai") return "AI";
      const lower = w.toLowerCase();
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    })
    .join(" ");
}

const SECTION_TITLE_STYLE: CSSProperties = {
  fontWeight: 700,
  margin: "0 0 var(--space-2)",
};
const SECTION_GRID_STYLE: CSSProperties = {
  display: "grid",
  gap: "var(--space-2)",
};
function ModuleCard({
  module,
  onSaved,
}: {
  module: AdminModuleState;
  onSaved: (updated: AdminModuleState) => void;
}) {
  const { toast } = useToast();
  const tt = useT();
  const [busy, setBusy] = useState(false);
  const [renderNonce, setRenderNonce] = useState(0);

  async function save(path: string, enabled: boolean, what: string) {
    setBusy(true);
    try {
      const updated = await api<AdminModuleState>(path, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      onSaved(updated);
      toast(`${module.nav?.label ?? humanizeCode(module.name)}: ${what}.`, { tone: "success", duration: 8000 });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : "Couldn't save that change.",
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  const blocked = module.dependency_status !== "ok";

  return (
    <Panel
      title={module.nav?.label ?? humanizeCode(module.name)}
      variant="plate"
      actions={<Badge tone="neutral">v{module.version}</Badge>}
    >
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {module.description}
        </p>

        <div className="tv-admin-module-badges" style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          {module.provides.map((capability) => (
            <Badge key={capability} tone="accent">
              Provides: {humanizeCode(capability)}
            </Badge>
          ))}
          {module.depends_on
            .filter((dep) => dep !== "core")
            .map((dep) => (
              <Badge key={dep} tone="neutral">
                Depends on: {humanizeCode(dep)}
              </Badge>
            ))}
        </div>

        {blocked && (
          <Alert tone="warning">
            Dependency problem — {module.dependency_status}. This module
            can't work until its dependency is usable again.
          </Alert>
        )}

        <div
          style={{
            borderTop: "1px solid var(--edge)",
            paddingTop: "var(--space-3)",
            display: "grid",
            gap: "var(--space-3)",
          }}
        >
          <Toggle
            key={`global-${renderNonce}`}
            checked={module.globally_enabled}
            disabled={busy}
            label={
              module.globally_enabled
                ? "On for the whole site"
                : "Off for the whole site (kill switch)"
            }
            onChange={(enabled) => {
              /* F2-15: the site-wide kill switch confirms before
               * it fires — a misclick must not take a module down
               * for every user. Declining remounts the switch on
               * its stored state. */
              if (!enabled && !window.confirm(tt("admin.confirm.moduleOff").replace("{name}", module.nav?.label ?? module.name))) {
                setRenderNonce((n) => n + 1);
                return;
              }
              void save(
                `/admin/modules/${module.id}/global`,
                enabled,
                enabled ? "switched on for everyone" : "switched off for everyone",
              );
            }}
          />

          <div>
            <p style={{ fontWeight: 700, margin: "0 0 var(--space-2)" }}>
              Account groups
            </p>
            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              {ACCOUNT_TYPE_OPTIONS.map((option) => (
                <Checkbox
                  key={`${option.value}-${renderNonce}`}
                  name={`${module.id}-${option.value}`}
                  label={option.label}
                  checked={!!module.groups[option.value]}
                  disabled={busy}
                  onChange={(e) => {
                    if (!e.target.checked && !window.confirm(tt("admin.confirm.moduleGroupOff").replace("{name}", module.nav?.label ?? module.name).replace("{group}", option.label))) {
                      setRenderNonce((n) => n + 1);
                      return;
                    }
                    void save(
                      `/admin/modules/${module.id}/groups/${option.value}`,
                      e.target.checked,
                      e.target.checked
                        ? `assigned to ${option.label}`
                        : `removed from ${option.label}`,
                    );
                  }}
                />
              ))}
            </div>
          </div>

          <div>
            <p style={SECTION_TITLE_STYLE}>Account tiers</p>
            <div style={SECTION_GRID_STYLE}>
              {MODULE_TIER_OPTIONS.map((option) => (
                <Checkbox
                  key={`tier-${option.value}-${renderNonce}`}
                  name={`${module.id}-tier-${option.value}`}
                  label={option.label}
                  checked={!!module.tiers[option.value]}
                  disabled={busy}
                  onChange={(e) => {
                    if (!e.target.checked && !window.confirm(tt("admin.confirm.moduleTierOff").replace("{name}", module.nav?.label ?? module.name).replace("{tier}", option.label))) {
                      setRenderNonce((n) => n + 1);
                      return;
                    }
                    void save(
                      `/admin/modules/${module.id}/tiers/${option.value}`,
                      e.target.checked,
                      e.target.checked
                        ? `lit for ${option.label}`
                        : `darkened for ${option.label}`,
                    );
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function ModulesSection() {
  const [modules, setModules] = useState<AdminModuleState[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setModules(await api<AdminModuleState[]>("/admin/modules"));
      setLoadError(null);
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Couldn't load the module matrix.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AdminShell>
      <div className="tv-admin-modules-grid" style={{ display: "grid", gap: "var(--spacing)" }}>
        {/* 09b-F5: the two explanations every card used to repeat
            verbatim (~20x) live ONCE here at the top; each card
            below keeps only what is unique to its module. */}
        <Panel title="How module access works">
          <div style={{ display: "grid", gap: "var(--space-2)" }}>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              An account gets a module when ANY of its groups is checked
              on that module's card (accounts can hold several groups) —
              and the module is switched on for the whole site.
            </p>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Tier switches stage a rollout: light Moderator admins to test a
              module while it's still dark for everyone else, then Beta
              testers, then Normal accounts. Higher tiers include the tiers
              below them — a module lit for Normal accounts reaches
              moderators and moderator admins too, and a beta tester gets
              Normal + Beta. A module only reaches an account when its tier
              AND one of its groups allow it. The God account always
              sees every module, whatever these switches say. Downloads
              accounts are the exception: they hold no groups, so their
              switch alone decides, and lighting a module for them
              announces it as a release (NEW badge, announcement, setup
              wizard on first entry).
            </p>
          </div>
        </Panel>
        {loadError && (
          <Alert tone="danger">
            {loadError} Try reloading the page — if it persists, the admin
            API may be down.
          </Alert>
        )}
        {!modules && !loadError && (
          <p
            style={{
              color: "var(--text-muted)",
              display: "flex",
              gap: "var(--space-2)",
              alignItems: "center",
              margin: 0,
            }}
          >
            <Spinner size="sm" /> Loading modules…
          </p>
        )}
        {modules?.map((module) => (
          <ModuleCard
            key={module.id}
            module={module}
            onSaved={(updated) =>
              setModules((current) =>
                (current ?? []).map((m) => (m.id === updated.id ? updated : m)),
              )
            }
          />
        ))}
      </div>
    </AdminShell>
  );
}

export default function AdminModulesPage() {
  return (
    <RequireAuth>
      <ModulesSection />
    </RequireAuth>
  );
}
