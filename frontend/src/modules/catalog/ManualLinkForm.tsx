import { useState, type FormEvent } from "react";

import { Button, FormField, TextInput, useToast } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { importManualLink } from "./api";
import "../inventory/itemPage.css";

/** Add a manual by link (owner ruling 2026-11-03): paste the
 *  address of a PDF manual, hit Add, and the SERVER downloads
 *  the file into the item's Manuals — the stored file is the
 *  downloaded bytes, never a hotlink. A refusal (unreachable,
 *  not a PDF, too large, a disallowed target) comes back as the
 *  server's own message and files nothing. Lives inside the
 *  Manuals area's Add flow, under the upload dropzone. */
export function ManualLinkForm({
  segment,
  itemId,
  itemName,
  onSaved,
}: {
  segment: "tools" | "batteries";
  itemId: string;
  itemName: string;
  onSaved: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!url.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await importManualLink(segment, itemId, url.trim());
      toast(
        data.already_present
          ? t("catalog.manualLink.already")
          : t("catalog.manualLink.saved").replace("{name}", itemName),
        { tone: "success" },
      );
      setUrl("");
      onSaved();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t("catalog.manualLink.failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="tv-manual-linkform" onSubmit={(e) => void submit(e)}>
      <FormField
        label={t("catalog.manualLink.label")}
        hint={t("catalog.manualLink.hint")}
        error={error || undefined}
      >
        <TextInput
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t("catalog.manualLink.placeholder")}
          inputMode="url"
          autoComplete="off"
        />
      </FormField>
      <Button type="submit" size="sm" loading={busy} disabled={!url.trim()}>
        {t("catalog.manualLink.add")}
      </Button>
    </form>
  );
}
