import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  SectionHeader,
  Spinner,
  useToast,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import {
  claimWarrantyRequest,
  listIncomingWarrantyRequests,
  listMyWarrantyRequests,
  setWarrantyStatus,
} from "../api";
import type { WarrantyRequest } from "../types";
import { WARRANTY_STATUS_KEYS } from "./DealerWarrantyBox";
import WarrantyMessageButton from "./WarrantyMessageButton";

/**
 * Warranty requests (dealer build) on the Dealers page: the
 * dealer's incoming queue (claim + work the status) and the
 * requests the signed-in user sent themselves, one list each.
 * The dealer HOME dashboard shows the summary; this is the full
 * working list.
 */
export default function WarrantyRequestsPanel({
  dealerGroup,
}: {
  dealerGroup: boolean;
}) {
  const t = useT();
  const { toast } = useToast();
  const [incoming, setIncoming] = useState<WarrantyRequest[] | null>(null);
  const [mine, setMine] = useState<WarrantyRequest[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");

  const refresh = useCallback(async () => {
    const [inc, sent] = await Promise.all([
      listIncomingWarrantyRequests(),
      listMyWarrantyRequests(),
    ]);
    setIncoming(inc);
    setMine(sent);
  }, []);

  useEffect(() => {
    refresh().catch((err) =>
      setError(
        err instanceof ApiError ? err.message : t("dealers.warranty.loadError"),
      ),
    );
  }, [refresh, t]);

  async function act(id: string, action: "claim" | string) {
    setBusyId(id);
    try {
      if (action === "claim") {
        await claimWarrantyRequest(id);
        toast(t("dealers.warranty.claimedToast"), { tone: "success" });
      } else {
        await setWarrantyStatus(id, action);
        toast(t("dealers.warranty.statusToast"), {
          tone: "success",
        });
      }
      await refresh();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.warranty.failedToast"),
        { tone: "danger" },
      );
    } finally {
      setBusyId("");
    }
  }

  if (incoming === null && !error) {
    return (
      <section>
        <SectionHeader title={t("dealers.warranty.title")} />
        <p style={{ color: "var(--text-muted)" }}>
          <Spinner size="sm" /> {t("dealers.warranty.loading")}
        </p>
      </section>
    );
  }

  const queue = (incoming ?? []).filter((r) => !r.mine);

  return (
    <section>
      <SectionHeader title={t("dealers.warranty.title")} />
      {error && <Alert tone="danger">{error}</Alert>}
      {dealerGroup && (
        <div style={{ display: "grid", gap: "var(--spacing)", marginBottom: "var(--spacing)" }}>
          {queue.length === 0 ? (
            <EmptyState title={t("dealers.warranty.queueEmpty")} />
          ) : (
            queue.map((request) => (
              <RequestCard
                key={request.id}
                request={request}
                busy={busyId === request.id}
                onAct={(action) => void act(request.id, action)}
              />
            ))
          )}
        </div>
      )}
      <p style={{ margin: "0 0 var(--space-2)", fontWeight: 600 }}>
        {t("dealers.warranty.sentTitle")}
      </p>
      {mine.length === 0 ? (
        <EmptyState title={t("dealers.warranty.sentEmpty")} />
      ) : (
        <div style={{ display: "grid", gap: "var(--spacing)" }}>
          {mine.map((request) => (
            <RequestCard
              key={request.id}
              request={request}
              busy={busyId === request.id}
              onAct={(action) => void act(request.id, action)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RequestCard({
  request,
  busy,
  onAct,
}: {
  request: WarrantyRequest;
  busy: boolean;
  onAct: (action: "claim" | string) => void;
}) {
  const t = useT();
  const warrantyStatus = WARRANTY_STATUS_KEYS[request.warranty_status]
    ? t(WARRANTY_STATUS_KEYS[request.warranty_status] as never)
    : request.warranty_status.replace("_", " ");
  const statusTone =
    request.status === "resolved"
      ? "success"
      : request.status === "unclaimed"
        ? "accent"
        : "neutral";
  const counterpart = request.mine
    ? request.claimed_by?.user_id
    : request.requester_deleted
      ? undefined
      : request.requester_id;
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        padding: "var(--space-3)",
        display: "grid",
        gap: "0.45rem",
      }}
    >
      <p style={{ margin: 0 }}>
        <strong>{request.item_name}</strong>{" "}
        <Badge tone={statusTone}>
          {t(`dealers.warranty.status.${request.status}` as never)}
        </Badge>{" "}
        <span style={{ color: "var(--text-muted)" }}>
          {request.company_name}
          {request.brand ? ` · ${request.brand}` : ""}
          {request.model ? ` ${request.model}` : ""}
        </span>
      </p>
      <p style={{ margin: 0, color: "var(--text-muted)" }}>
        {request.mine
          ? request.claimed_by
            ? t("dealers.warranty.claimedBy").replace(
                "{name}",
                request.claimed_by.display_name,
              )
            : request.routed_agents.length > 0
              ? t("dealers.warranty.offeredTo").replace(
                  "{names}",
                  request.routed_agents.map((a) => a.display_name).join(", "),
                )
              : t("dealers.warranty.status.unclaimed")
          : `${t("dealers.warranty.from").replace("{name}", request.requester_name)}${
              request.requester_area ? ` · ${request.requester_area}` : ""
            }`}
      </p>
      {request.problem && <p style={{ margin: 0 }}>{request.problem}</p>}
      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
        {request.serials.length > 0 &&
          `${t("dealers.warranty.serial").replace("{serials}", request.serials.join(", "))} · `}
        {t("dealers.warranty.warrantyLabel").replace("{status}", warrantyStatus)}
        {request.purchase_date
          ? ` · ${t("dealers.warranty.purchased").replace("{date}", request.purchase_date)}`
          : ""}
        {!request.mine &&
          request.requester_phone &&
          ` · ${request.requester_phone}`}
        {!request.mine &&
          request.requester_email &&
          ` · ${request.requester_email}`}
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {!request.mine && request.status === "unclaimed" && (
          <Button size="sm" loading={busy} onClick={() => onAct("claim")}>
            {t("dealers.warranty.claimJob")}
          </Button>
        )}
        {!request.mine &&
          request.claimed_by_me &&
          request.status === "received" && (
            <Button
              size="sm"
              loading={busy}
              onClick={() => onAct("in_process")}
            >
              {t("dealers.warranty.startWork")}
            </Button>
          )}
        {!request.mine &&
          request.claimed_by_me &&
          (request.status === "received" ||
            request.status === "in_process") && (
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={() => onAct("resolved")}
            >
              {t("dealers.warranty.markResolved")}
            </Button>
          )}
        {counterpart && (
          <WarrantyMessageButton
            request={request}
            recipientId={counterpart}
            label={t("dealers.warranty.message")}
          />
        )}
      </div>
    </div>
  );
}
