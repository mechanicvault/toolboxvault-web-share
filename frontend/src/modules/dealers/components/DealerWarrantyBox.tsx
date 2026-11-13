import { useEffect, useState } from "react";
import { Badge, Button, Checkbox, useToast } from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { sendWarrantyRequest, warrantyEligibility } from "../api";
import type { WarrantyEligibility } from "../types";
import WarrantyMessageButton from "./WarrantyMessageButton";

/** The item's warranty standing through the inventory
 *  dictionary family (shared with the Agents tab's Warranty
 *  Requests panel, sweep B5); an unmapped value keeps the
 *  plain de-snaked reading. */
export const WARRANTY_STATUS_KEYS: Record<string, string> = {
  in_warranty: "inventory.warranty.in_warranty",
  expiring_soon: "inventory.warranty.expiring_soon",
  expired: "inventory.warranty.expired",
  unknown: "inventory.warranty.unknown",
};

/**
 * "Send to my dealer" (dealer build) inside the claim's Repair panel:
 * when a broken item's company has REGISTERED agents, the break
 * can go straight to them as a warranty service request. The box
 * shows the EXACT payload before anything sends — the requester's
 * name/contact as it will arrive, the item identity, the problem,
 * purchase date, computed warranty status — and the send checkbox
 * starts CHECKED when the user has a preferred agent for the
 * company, unchecked otherwise.
 *
 * Hidden entirely when the dealers module is off (403), when the
 * item has no dealer company, or when the record is someone
 * else's — a private dealer never gets a send, and the note says
 * why when a company exists but has no registered agents yet.
 */
export default function DealerWarrantyBox({
  claimId,
}: {
  claimId: string;
}) {
  const t = useT();
  const { toast } = useToast();
  const [elig, setElig] = useState<WarrantyEligibility | null>(null);
  const [hidden, setHidden] = useState(false);
  const [sendChecked, setSendChecked] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let alive = true;
    warrantyEligibility(claimId)
      .then((next) => {
        if (!alive) return;
        setElig(next);
        setSendChecked(next.has_preferred_agent);
        if (!next.available && !next.existing_request && next.reason !== "no_agents") {
          setHidden(true);
        }
      })
      .catch(() => {
        if (alive) setHidden(true);
      });
    return () => {
      alive = false;
    };
  }, [claimId]);

  if (hidden || elig === null) return null;

  const existing = elig.existing_request;
  if (existing) {
    return (
      <div
        style={{
          borderTop: "1px solid var(--border)",
          paddingTop: "0.7rem",
          display: "grid",
          gap: "0.4rem",
        }}
      >
        <p style={{ margin: 0 }}>
          <strong>{t("dealers.warranty.boxTitle")}</strong>{" "}
          <Badge
            tone={existing.status === "resolved" ? "success" : "accent"}
          >
            {t(`dealers.warranty.status.${existing.status}` as never)}
          </Badge>
        </p>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {existing.claimed_by
            ? t("dealers.warranty.boxSentClaimed")
                .replace("{company}", existing.company_name)
                .replace("{name}", existing.claimed_by.display_name)
            : existing.routed_agents.length > 0
              ? t("dealers.warranty.boxSentOffered")
                  .replace("{company}", existing.company_name)
                  .replace(
                    "{names}",
                    existing.routed_agents.map((a) => a.display_name).join(", "),
                  )
              : t("dealers.warranty.boxSentPlain").replace(
                  "{company}",
                  existing.company_name,
                )}
        </p>
        {existing.claimed_by && (
          <div>
            <WarrantyMessageButton
              request={existing}
              recipientId={existing.claimed_by.user_id}
              label={t("dealers.warranty.messageName").replace(
                "{name}",
                existing.claimed_by.display_name,
              )}
            />
          </div>
        )}
      </div>
    );
  }

  if (!elig.available) {
    // no_agents is the only visible dead end (the others hide):
    // there IS a company, it just has nobody registered yet.
    return (
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {t("dealers.warranty.noAgents").replace("{company}", elig.company_name)}
      </p>
    );
  }

  const payload = elig.payload;
  if (!payload) return null;

  async function send() {
    setSending(true);
    try {
      const created = await sendWarrantyRequest(claimId);
      setElig({ ...elig!, existing_request: created, available: false, reason: "already_sent" });
      toast(t("dealers.warranty.sentToast"), { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.warranty.sendFailed"),
        { tone: "danger" },
      );
      setSending(false);
    }
  }

  return (
    <div
      style={{
        borderTop: "1px solid var(--border)",
        paddingTop: "0.7rem",
        display: "grid",
        gap: "0.5rem",
      }}
    >
      <p style={{ margin: 0 }}>
        <strong>{t("dealers.warranty.sendToDealer")}</strong>{" "}
        <span style={{ color: "var(--text-muted)" }}>
          ({(elig.registered_agent_count === 1
            ? t("dealers.warranty.agentCountOne")
            : t("dealers.warranty.agentCountMany").replace(
                "{count}",
                String(elig.registered_agent_count),
              )
          ).replace("{company}", elig.company_name)})
        </span>
      </p>
      <p style={{ color: "var(--text-muted)", margin: 0 }}>
        {elig.has_preferred_agent
          ? t("dealers.warranty.goesPreferred").replace(
              "{names}",
              elig.preferred_agent_names.join(", "),
            )
          : t("dealers.warranty.goesArea")}{" "}
        {t("dealers.warranty.exactlyThis")}
      </p>
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "0.6rem 0.8rem",
          display: "grid",
          gap: "0.2rem",
          fontSize: "0.92rem",
        }}
      >
        <span>
          <strong>{payload.requester_name}</strong>
          {payload.requester_phone ? ` · ${payload.requester_phone}` : ""}
          {` · ${payload.requester_email}`}
          {payload.requester_area ? ` · ${payload.requester_area}` : ""}
        </span>
        <span>
          {payload.item_name}
          {payload.brand ? ` · ${payload.brand}` : ""}
          {payload.model ? ` ${payload.model}` : ""}
          {payload.serials.length > 0
            ? ` · ${t("dealers.warranty.serial").replace("{serials}", payload.serials.join(", "))}`
            : ""}
        </span>
        <span>
          {t("dealers.warranty.problemLabel").replace("{problem}", payload.problem || "—")}
        </span>
        <span>
          {t("dealers.warranty.purchasedLine")
            .replace("{date}", payload.purchase_date ?? t("dealers.warranty.notRecorded"))
            .replace(
              "{status}",
              WARRANTY_STATUS_KEYS[payload.warranty_status]
                ? t(WARRANTY_STATUS_KEYS[payload.warranty_status] as never)
                : payload.warranty_status.replace("_", " "),
            )}
        </span>
      </div>
      <Checkbox
        checked={sendChecked}
        onChange={(e) => setSendChecked(e.target.checked)}
        label={t("dealers.warranty.sendCheckbox").replace("{company}", elig.company_name)}
      />
      <div>
        <Button
          size="sm"
          loading={sending}
          disabled={!sendChecked}
          onClick={() => void send()}
        >
          {t("dealers.warranty.sendButton")}
        </Button>
      </div>
    </div>
  );
}
