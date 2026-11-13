import { useCallback, useEffect, useState } from "react";

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Panel,
  Spinner,
  useToast,
} from "../../components";
import { ApiError, api } from "../../lib/api";

/**
 * MY SHOP (wave 3): the employee side of crew membership — the
 * invite inbox (accept / decline) and the shops I belong to,
 * with the 30-day grace countdown after leaving: rejoin any crew
 * or hold your own paid plan inside the window and nothing about
 * your standing changes; the notices land in your inbox as the
 * deadline approaches.
 */

interface CrewMembership {
  id: string;
  shop_user_id: string;
  shop_name: string;
  role_label: string;
  status: "invited" | "active" | "left" | "declined";
  invited_at: string;
  accepted_at: string | null;
  left_at: string | null;
  grace_days_left: number | null;
}

export default function MyShopSettings() {
  const { toast } = useToast();
  const [invites, setInvites] = useState<CrewMembership[] | null>(null);
  const [shops, setShops] = useState<CrewMembership[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [inv, mine] = await Promise.all([
        api<CrewMembership[]>("/core/crew/invites"),
        api<CrewMembership[]>("/core/crew/my-shops"),
      ]);
      setInvites(inv);
      setShops(mine);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your shops.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function respond(row: CrewMembership, accept: boolean) {
    setError(null);
    try {
      await api(`/core/crew/invites/${row.id}/respond`, {
        method: "POST",
        body: JSON.stringify({ accept }),
      });
      toast(accept ? "You're on the crew." : "Invite declined.", {
        tone: "success",
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't answer that invite.");
    }
  }

  async function leave(row: CrewMembership) {
    setError(null);
    try {
      await api(`/core/crew/my-shops/${row.id}/leave`, { method: "POST" });
      toast("You've left that crew. Your 30-day grace window has started.", {
        tone: "success",
      });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't leave that crew.");
    }
  }

  const active = (shops ?? []).filter((s) => s.status === "active");
  const left = (shops ?? []).filter((s) => s.status === "left");

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      {error && <Alert tone="danger">{error}</Alert>}

      <Panel title="Crew invites" variant="plate">
        {!invites && !error && <Spinner />}
        {invites && invites.length === 0 && (
          <EmptyState
            title="No invites"
            description="When a shop invites you by email or account number, it lands here."
          />
        )}
        {invites &&
          invites.map((row) => (
            <div
              key={row.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "var(--space-3)",
                flexWrap: "wrap",
                padding: "var(--space-2) 0",
              }}
            >
              <span>
                <strong>{row.shop_name || "A shop"}</strong>
                {row.role_label && ` · ${row.role_label}`}
                <span style={{ color: "var(--text-muted)" }}>
                  {" "}
                  · invited {new Date(row.invited_at).toLocaleDateString()}
                </span>
              </span>
              <span style={{ display: "flex", gap: "var(--space-2)" }}>
                <Button type="button" onClick={() => void respond(row, true)}>
                  Accept
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => void respond(row, false)}
                >
                  Decline
                </Button>
              </span>
            </div>
          ))}
      </Panel>

      <Panel title="My shops">
        {!shops && !error && <Spinner />}
        {shops && shops.length === 0 && (
          <EmptyState
            title="Not on a crew"
            description="Accept a shop's invite and it shows up here — which shop, your role, and since when."
          />
        )}
        {active.map((row) => (
          <div
            key={row.id}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "var(--space-3)",
              flexWrap: "wrap",
              padding: "var(--space-2) 0",
            }}
          >
            <span>
              <strong>{row.shop_name || "Shop"}</strong>
              {row.role_label && ` · ${row.role_label}`}
              <span style={{ color: "var(--text-muted)" }}>
                {" "}
                · since{" "}
                {row.accepted_at
                  ? new Date(row.accepted_at).toLocaleDateString()
                  : "—"}
              </span>{" "}
              <Badge tone="success">active</Badge>
            </span>
            <Button type="button" variant="ghost" onClick={() => void leave(row)}>
              Leave crew
            </Button>
          </div>
        ))}
        {left.map((row) => (
          <div key={row.id} style={{ padding: "var(--space-2) 0" }}>
            <span>
              <strong>{row.shop_name || "Shop"}</strong>
              {row.role_label && ` · ${row.role_label}`}{" "}
              <Badge tone="neutral">left</Badge>
            </span>
            {row.grace_days_left !== null && (
              <Alert tone="warning">
                You left on{" "}
                {row.left_at
                  ? new Date(row.left_at).toLocaleDateString()
                  : "—"}
                . Your crew standing runs for {row.grace_days_left} more
                day{row.grace_days_left === 1 ? "" : "s"} — rejoin a crew
                or hold your own paid plan before then and nothing
                changes; after that you're on the Free plan.
              </Alert>
            )}
          </div>
        ))}
      </Panel>
    </div>
  );
}
