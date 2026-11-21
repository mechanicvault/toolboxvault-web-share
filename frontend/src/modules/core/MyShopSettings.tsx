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
import { useT } from "../../i18n/LocaleContext";
import { ApiError, api } from "../../lib/api";
import { activeLocale } from "../../lib/format";

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
  const t = useT();
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
      setError(err instanceof ApiError ? err.message : t("settings.myShop.loadFailed"));
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
      toast(
        accept ? t("settings.myShop.joinedToast") : t("settings.myShop.declinedToast"),
        { tone: "success" },
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.myShop.respondFailed"));
    }
  }

  async function leave(row: CrewMembership) {
    setError(null);
    try {
      await api(`/core/crew/my-shops/${row.id}/leave`, { method: "POST" });
      toast(t("settings.myShop.leftToast"), { tone: "success" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.myShop.leaveFailed"));
    }
  }

  const active = (shops ?? []).filter((s) => s.status === "active");
  const left = (shops ?? []).filter((s) => s.status === "left");

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      {error && <Alert tone="danger">{error}</Alert>}

      <Panel title={t("settings.myShop.invitesTitle")} variant="plate">
        {!invites && !error && <Spinner />}
        {invites && invites.length === 0 && (
          <EmptyState
            title={t("settings.myShop.noInvitesTitle")}
            description={t("settings.myShop.noInvitesDesc")}
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
                <strong>{row.shop_name || t("settings.myShop.aShop")}</strong>
                {row.role_label && ` · ${row.role_label}`}
                <span style={{ color: "var(--text-muted)" }}>
                  {t("settings.myShop.invitedPart").replace(
                    "{date}",
                    new Date(row.invited_at).toLocaleDateString(activeLocale()),
                  )}
                </span>
              </span>
              <span style={{ display: "flex", gap: "var(--space-2)" }}>
                <Button type="button" onClick={() => void respond(row, true)}>
                  {t("settings.myShop.accept")}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => void respond(row, false)}
                >
                  {t("settings.myShop.decline")}
                </Button>
              </span>
            </div>
          ))}
      </Panel>

      <Panel title={t("settings.myShop.myShopsTitle")}>
        {!shops && !error && <Spinner />}
        {shops && shops.length === 0 && (
          <EmptyState
            title={t("settings.myShop.noCrewTitle")}
            description={t("settings.myShop.noCrewDesc")}
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
              <strong>{row.shop_name || t("settings.myShop.shopFallback")}</strong>
              {row.role_label && ` · ${row.role_label}`}
              <span style={{ color: "var(--text-muted)" }}>
                {t("settings.myShop.sincePart").replace(
                  "{date}",
                  row.accepted_at
                    ? new Date(row.accepted_at).toLocaleDateString(activeLocale())
                    : "—",
                )}
              </span>{" "}
              <Badge tone="success">{t("settings.crew.statusActive")}</Badge>
            </span>
            <Button type="button" variant="ghost" onClick={() => void leave(row)}>
              {t("settings.myShop.leaveCrew")}
            </Button>
          </div>
        ))}
        {left.map((row) => (
          <div key={row.id} style={{ padding: "var(--space-2) 0" }}>
            <span>
              <strong>{row.shop_name || t("settings.myShop.shopFallback")}</strong>
              {row.role_label && ` · ${row.role_label}`}{" "}
              <Badge tone="neutral">{t("settings.crew.statusLeft")}</Badge>
            </span>
            {row.grace_days_left !== null && (
              <Alert tone="warning">
                {t("settings.myShop.leftLead")
                  .replace(
                    "{date}",
                    row.left_at
                      ? new Date(row.left_at).toLocaleDateString(activeLocale())
                      : "—",
                  )
                  .replace("{count}", String(row.grace_days_left))}
                {row.grace_days_left === 1
                  ? t("settings.myShop.leftDayOne")
                  : t("settings.myShop.leftDayMany")}
                {t("settings.myShop.leftTail")}
              </Alert>
            )}
          </div>
        ))}
      </Panel>
    </div>
  );
}
