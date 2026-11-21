import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Modal, TextArea, useToast } from "../../../components";
import { ApiError } from "../../../lib/api";
import { useT } from "../../../i18n/LocaleContext";
import { openThread } from "../../messaging/api";
import type { WarrantyRequest } from "../types";

/**
 * "Message" on a warranty request (dealer build): opens the
 * EXISTING messaging with a thread anchored to the request — the
 * conversation about this exact job, between the requester and
 * the agent. Nothing about chat is rebuilt here.
 */
export default function WarrantyMessageButton({
  request,
  recipientId,
  label,
}: {
  request: WarrantyRequest;
  recipientId: string;
  label?: string;
}) {
  const t = useT();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setSending(true);
    try {
      const thread = await openThread({
        recipient_id: recipientId,
        body: draft.trim(),
        anchor_type: "warranty_request",
        anchor_id: request.id,
      });
      toast(t("dealers.warranty.messageSent"), { tone: "success" });
      setOpen(false);
      navigate(`/messages/${thread.id}`);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.warranty.messageFailed"),
        { tone: "danger" },
      );
      setSending(false);
    }
  }

  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
        {label ?? t("dealers.warranty.message")}
      </Button>
      <Modal
        open={open}
        title={t("dealers.warranty.messageAbout").replace("{item}", request.item_name)}
        onClose={() => setOpen(false)}
      >
        <form
          onSubmit={(e) => void onSend(e)}
          style={{ display: "grid", gap: "0.8rem" }}
        >
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("dealers.warranty.messageBody")
              .replace("{item}", request.item_name)
              .replace("{company}", request.company_name)}
          </p>
          <TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={4}
            placeholder={t("dealers.warranty.messagePlaceholder")}
          />
          <div>
            <Button type="submit" loading={sending} disabled={!draft.trim()}>
              {t("dealers.warranty.sendMessage")}
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
