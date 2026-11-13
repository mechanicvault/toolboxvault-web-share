/** The shelf's two write modals — flag and remove — shared by
 * the record page (file + comments) and My Files (remove). */

import { useState } from "react";

import { Alert, Button, FormField, Modal, TextArea, useToast } from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  modRemovePrintFile,
  removePrintFile,
  reportPrintComment,
  reportPrintFile,
} from "./api";

export function FlagModal({
  open,
  onClose,
  fileId,
  commentId,
}: {
  open: boolean;
  onClose: () => void;
  fileId?: string;
  commentId?: string;
}) {
  const t = useT();
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (commentId) await reportPrintComment(commentId, reason.trim());
      else if (fileId) await reportPrintFile(fileId, reason.trim());
      toast(t("prints.flag.sent"));
      setReason("");
      onClose();
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={commentId ? t("prints.flag.commentTitle") : t("prints.flag.fileTitle")}
    >
      <p className="pr-modal-hint">{t("prints.flag.hint")}</p>
      <FormField label={t("prints.flag.reason")}>
        <TextArea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          maxLength={1000}
        />
      </FormField>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="pr-modal-actions">
        <Button variant="secondary" onClick={onClose}>
          {t("prints.flag.cancel")}
        </Button>
        <Button onClick={() => void submit()} loading={busy}>
          {t("prints.flag.submit")}
        </Button>
      </div>
    </Modal>
  );
}

export function RemoveFileModal({
  open,
  onClose,
  fileId,
  onRemoved,
  moderator,
}: {
  open: boolean;
  onClose: () => void;
  fileId: string;
  onRemoved: () => void;
  /** A moderator_admin/god/operator removing SOMEONE ELSE'S
   * file rides the moderation door, not the owner door. */
  moderator?: boolean;
}) {
  const t = useT();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (moderator) await modRemovePrintFile(fileId, "");
      else await removePrintFile(fileId);
      toast(t("prints.remove.done"));
      onRemoved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("prints.upload.errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("prints.remove.title")}>
      <p className="pr-modal-hint">{t("prints.remove.body")}</p>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="pr-modal-actions">
        <Button variant="secondary" onClick={onClose}>
          {t("prints.flag.cancel")}
        </Button>
        <Button variant="danger" onClick={() => void submit()} loading={busy}>
          {t("prints.remove.confirm")}
        </Button>
      </div>
    </Modal>
  );
}
