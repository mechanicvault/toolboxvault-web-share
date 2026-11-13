import { useRef, useState, type ChangeEvent } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Modal,
  Spinner,
  useToast,
} from "../../components";
import { ApiError, downloadBlob } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  exportBorrowerFile,
  exportBorrowersFile,
  importBorrowers,
  previewBorrowerImport,
  type BorrowerImportPreview,
} from "./api";
import type { BorrowerContact } from "./types";

/**
 * Contact cards for the borrower address book (contact cards
 * lane, 2026-11-07): export one borrower or the whole book as
 * .vcf files a phone can open, and import a .vcf through a
 * preview the owner confirms row by row — likely duplicates
 * flagged and left unchecked, unreadable cards reported as
 * soft skips. Nothing is created until the owner confirms.
 */

function slug(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "contact"
  );
}

/** The per-row "Card" button in the address book list. */
export function BorrowerCardButton({ contact }: { contact: BorrowerContact }) {
  const t = useT();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);

  async function onExport() {
    setBusy(true);
    try {
      const blob = await exportBorrowerFile(contact.id);
      downloadBlob(blob, `${slug(contact.name)}.vcf`);
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("borrowing.cards.exportError"),
        { tone: "danger" },
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      loading={busy}
      onClick={() => void onExport()}
    >
      {t("borrowing.cards.exportOne")}
    </Button>
  );
}

type ImportStage = "pick" | "reading" | "preview" | "adding";

/** The address book's card toolbar: Import + Export all, and
 *  the import modal (pick -> preview -> confirm). The sheet
 *  rides the large modal seat (sweep B4, F8): its preview list
 *  is a 620px-minimum true list, which the default md seat
 *  (600px) forced into a sideways scroll inside its own sheet;
 *  lg is the seat the other list-carrying sheets use. */
export function BorrowerBookTools({
  hasContacts,
  onImported,
}: {
  hasContacts: boolean;
  onImported: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState<ImportStage>("pick");
  const [preview, setPreview] = useState<BorrowerImportPreview | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [readError, setReadError] = useState("");
  const [exporting, setExporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function reset() {
    setStage("pick");
    setPreview(null);
    setSelected(new Set());
    setReadError("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function close() {
    setOpen(false);
    reset();
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setStage("reading");
    setReadError("");
    try {
      const result = await previewBorrowerImport(file);
      setPreview(result);
      // Duplicates start UNCHECKED — adding one again is the
      // owner's deliberate choice, never the default.
      setSelected(
        new Set(
          result.rows.filter((r) => !r.duplicate).map((r) => r.index),
        ),
      );
      setStage("preview");
    } catch (err) {
      setReadError(err instanceof Error ? err.message : t("borrowing.cards.readError"));
      setStage("pick");
    }
  }

  function toggle(index: number, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(index);
      else next.delete(index);
      return next;
    });
  }

  async function onConfirm() {
    if (!preview) return;
    const rows = preview.rows
      .filter((r) => selected.has(r.index))
      .map((r) => ({ name: r.name, contact: r.contact, notes: r.notes }));
    if (rows.length === 0) return;
    setStage("adding");
    try {
      const result = await importBorrowers(rows);
      toast(
        t("borrowing.cards.added").replace("{count}", String(result.count)),
        { tone: "success" },
      );
      close();
      onImported();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("borrowing.cards.addError"),
        { tone: "danger" },
      );
      setStage("preview");
    }
  }

  async function onExportAll() {
    setExporting(true);
    try {
      const blob = await exportBorrowersFile();
      downloadBlob(blob, "toolbox-vault-borrowers.vcf");
      toast(t("borrowing.cards.exportedAll"), { tone: "success" });
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("borrowing.cards.exportError"),
        { tone: "danger" },
      );
    } finally {
      setExporting(false);
    }
  }

  const shownCount = preview ? preview.rows.length + preview.errors.length : 0;

  return (
    <>
      <div className="tv-bw-cards-bar">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setOpen(true)}
        >
          {t("borrowing.cards.importButton")}
        </Button>
        {hasContacts && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            loading={exporting}
            onClick={() => void onExportAll()}
          >
            {t("borrowing.cards.exportAll")}
          </Button>
        )}
      </div>
      <Modal
        open={open}
        onClose={close}
        size="lg"
        title={t("borrowing.cards.importTitle")}
        footer={
          <>
            <Button type="button" variant="secondary" onClick={close}>
              {t("borrowing.checkout.cancel")}
            </Button>
            {stage === "preview" || stage === "adding" ? (
              <Button
                type="button"
                loading={stage === "adding"}
                disabled={selected.size === 0}
                onClick={() => void onConfirm()}
              >
                {t("borrowing.cards.addSelected").replace(
                  "{count}",
                  String(selected.size),
                )}
              </Button>
            ) : null}
          </>
        }
      >
        <div className="tv-bw-import">
          {stage === "pick" || stage === "reading" ? (
            <>
              <p className="tv-bw-import-intro">
                {t("borrowing.cards.importIntro")}
              </p>
              {readError && <p className="tv-bw-import-error">{readError}</p>}
              <div>
                <Button
                  type="button"
                  loading={stage === "reading"}
                  onClick={() => fileRef.current?.click()}
                >
                  {t("borrowing.cards.pickFile")}
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".vcf,text/vcard,text/x-vcard"
                  className="tv-bw-import-file"
                  onChange={(e) => void onFile(e)}
                />
              </div>
              {stage === "reading" && (
                <p className="tv-bw-import-intro">
                  <Spinner size="sm" /> {t("borrowing.cards.reading")}
                </p>
              )}
            </>
          ) : preview ? (
            <>
              <p className="tv-bw-import-intro">
                {t("borrowing.cards.found").replace(
                  "{count}",
                  String(preview.rows.length),
                )}
              </p>
              {preview.total_cards > shownCount && (
                <p className="tv-bw-import-intro">
                  {t("borrowing.cards.capped")
                    .replace("{total}", String(preview.total_cards))
                    .replace("{shown}", String(shownCount))}
                </p>
              )}
              <div className="tv-bw-table tv-bw-table--import" role="table">
                <div className="tv-bw-thead" role="row">
                  <span aria-hidden="true" />
                  <span role="columnheader">{t("borrowing.cards.colName")}</span>
                  <span role="columnheader">
                    {t("borrowing.cards.colContact")}
                  </span>
                  <span role="columnheader">{t("borrowing.cards.colNotes")}</span>
                </div>
                {preview.rows.map((row) => (
                  <div key={row.index} className="tv-bw-row" role="row">
                    <div role="cell">
                      <Checkbox
                        label=""
                        aria-label={row.name}
                        checked={selected.has(row.index)}
                        onChange={(e) => toggle(row.index, e.target.checked)}
                      />
                    </div>
                    <div role="cell">
                      <strong>{row.name}</strong>
                      {row.duplicate && (
                        <span className="tv-bw-cell-sub">
                          <Badge tone="warning" dot>
                            {t("borrowing.cards.duplicate")}
                          </Badge>
                        </span>
                      )}
                    </div>
                    <div role="cell">{row.contact || "—"}</div>
                    <div role="cell">
                      {row.notes ? (
                        <span className="tv-bw-notes" title={row.notes}>
                          {row.notes}
                        </span>
                      ) : (
                        "—"
                      )}
                    </div>
                  </div>
                ))}
              </div>
              {preview.errors.length > 0 && (
                <ul className="tv-bw-import-errors">
                  {preview.errors.map((err) => (
                    <li key={err.index}>
                      {t("borrowing.cards.cardSkipped").replace(
                        "{message}",
                        err.message,
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : null}
        </div>
      </Modal>
    </>
  );
}
