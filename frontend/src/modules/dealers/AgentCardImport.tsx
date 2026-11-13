import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Modal,
  Select,
  Spinner,
  useToast,
} from "../../components";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import {
  importAgents,
  listCompanies,
  previewAgentImport,
  type AgentImportPreview,
  type AgentImportPreviewRow,
} from "./api";
import type { DealerCompany } from "./types";

/**
 * Import agent contact cards (agent card import lane,
 * 2026-11-07): a .vcf (one card or many) becomes the owner's
 * own PRIVATE agent records — never a platform agent, which
 * only signup + the code-claim flow can create. Preview-first,
 * the borrower import's shape: one row per readable card with
 * a dealer pick (the card's ORG suggests one; the owner
 * confirms or changes it per card), likely duplicates badged
 * "Already in your book" and starting unchecked, unreadable
 * cards as soft skips. Nothing is created until the owner
 * confirms, and nothing is ever created dealerless.
 */

type ImportStage = "pick" | "reading" | "preview" | "adding";

function duplicateFor(row: AgentImportPreviewRow, companyId: string) {
  return row.duplicates.find((d) => d.company_id === companyId) ?? null;
}

export function AgentImportButton({
  defaultCompanyId,
  onImported,
}: {
  /** The dealer whose page opened the import (the Agents
   *  tab): cards with no ORG suggestion start on it. The My
   *  agents surface passes none — those cards start on their
   *  suggestion or unpicked. */
  defaultCompanyId?: string | null;
  onImported: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState<ImportStage>("pick");
  const [preview, setPreview] = useState<AgentImportPreview | null>(null);
  const [companies, setCompanies] = useState<DealerCompany[]>([]);
  const [picks, setPicks] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [readError, setReadError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  // The dealer choices (the companies the owner can see, under
  // the names he sees them by) load when the modal opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listCompanies()
      .then((rows) => {
        if (!cancelled) setCompanies(rows);
      })
      .catch(() => {
        /* the preview still names its suggestions; the owner
           just can't re-pick until a reload succeeds */
      });
    return () => {
      cancelled = true;
    };
  }, [open ]);

  function reset() {
    setStage("pick");
    setPreview(null);
    setPicks({});
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
      const result = await previewAgentImport(file);
      const nextPicks: Record<number, string> = {};
      const nextSelected = new Set<number>();
      for (const row of result.rows) {
        // The card's suggestion wins; the page's dealer is the
        // fallback for cards that suggest nothing.
        const pick =
          row.suggested_company_id ?? defaultCompanyId ?? "";
        nextPicks[row.index] = pick;
        // Duplicates and dealerless rows start UNCHECKED —
        // adding either again is the owner's deliberate act.
        if (pick && !duplicateFor(row, pick)) nextSelected.add(row.index);
      }
      setPreview(result);
      setPicks(nextPicks);
      setSelected(nextSelected);
      setStage("preview");
    } catch (err) {
      setReadError(
        err instanceof Error ? err.message : t("dealers.cards.readError"),
      );
      setStage("pick");
    }
  }

  function changePick(row: AgentImportPreviewRow, companyId: string) {
    setPicks((prev) => ({ ...prev, [row.index]: companyId }));
    // A row's checked state follows its dealer: dealerless or
    // a duplicate under the new dealer is unchecked; a clean
    // pick is checked.
    setSelected((prev) => {
      const next = new Set(prev);
      if (companyId && !duplicateFor(row, companyId)) next.add(row.index);
      else next.delete(row.index);
      return next;
    });
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
      .filter((r) => selected.has(r.index) && picks[r.index])
      .map((r) => ({
        name: r.name,
        company_id: picks[r.index],
        phone: r.phone,
        email: r.email,
        location: r.location,
        notes: r.notes,
      }));
    if (rows.length === 0) return;
    setStage("adding");
    try {
      const result = await importAgents(rows);
      toast(
        t("dealers.cards.added").replace("{count}", String(result.count)),
        { tone: "success" },
      );
      close();
      onImported();
    } catch (err) {
      toast(
        err instanceof ApiError ? err.message : t("dealers.cards.addError"),
        { tone: "danger" },
      );
      setStage("preview");
    }
  }

  const shownCount = preview ? preview.rows.length + preview.errors.length : 0;
  const chosenCount = preview
    ? preview.rows.filter((r) => selected.has(r.index) && picks[r.index])
        .length
    : 0;

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        onClick={() => setOpen(true)}
      >
        {t("dealers.cards.importButton")}
      </Button>
      <Modal
        open={open}
        onClose={close}
        title={t("dealers.cards.importTitle")}
        footer={
          <>
            <Button type="button" variant="secondary" onClick={close}>
              {t("common.cancel")}
            </Button>
            {stage === "preview" || stage === "adding" ? (
              <Button
                type="button"
                loading={stage === "adding"}
                disabled={chosenCount === 0}
                onClick={() => void onConfirm()}
              >
                {t("dealers.cards.addSelected").replace(
                  "{count}",
                  String(chosenCount),
                )}
              </Button>
            ) : null}
          </>
        }
      >
        <div className="tv-agent-import">
          {stage === "pick" || stage === "reading" ? (
            <>
              <p className="tv-agent-import-intro">
                {t("dealers.cards.importIntro")}
              </p>
              {readError && (
                <p className="tv-agent-import-error">{readError}</p>
              )}
              <div>
                <Button
                  type="button"
                  loading={stage === "reading"}
                  onClick={() => fileRef.current?.click()}
                >
                  {t("dealers.cards.pickFile")}
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".vcf,text/vcard,text/x-vcard"
                  className="tv-agent-import-file"
                  onChange={(e) => void onFile(e)}
                />
              </div>
              {stage === "reading" && (
                <p className="tv-agent-import-intro">
                  <Spinner size="sm" /> {t("dealers.cards.reading")}
                </p>
              )}
            </>
          ) : preview ? (
            <>
              <p className="tv-agent-import-intro">
                {t("dealers.cards.found").replace(
                  "{count}",
                  String(preview.rows.length),
                )}
              </p>
              {preview.total_cards > shownCount && (
                <p className="tv-agent-import-intro">
                  {t("dealers.cards.capped")
                    .replace("{total}", String(preview.total_cards))
                    .replace("{shown}", String(shownCount))}
                </p>
              )}
              <div className="tv-agent-table" role="table">
                <div className="tv-agent-thead" role="row">
                  <span aria-hidden="true" />
                  <span role="columnheader">
                    {t("dealers.cards.colName")}
                  </span>
                  <span role="columnheader">
                    {t("dealers.cards.colContact")}
                  </span>
                  <span role="columnheader">
                    {t("dealers.cards.colDealer")}
                  </span>
                </div>
                {preview.rows.map((row) => {
                  const pick = picks[row.index] ?? "";
                  const dup = pick ? duplicateFor(row, pick) : null;
                  const pickedName = companies.find(
                    (c) => c.id === pick,
                  )?.name;
                  const orgOffPick =
                    row.org &&
                    (!pickedName ||
                      pickedName.trim().toLowerCase() !==
                        row.org.trim().toLowerCase());
                  return (
                    <div key={row.index} className="tv-agent-row" role="row">
                      <div role="cell">
                        <Checkbox
                          label=""
                          aria-label={row.name}
                          checked={selected.has(row.index)}
                          disabled={!pick}
                          onChange={(e) =>
                            toggle(row.index, e.target.checked)
                          }
                        />
                      </div>
                      <div role="cell">
                        <strong>{row.name}</strong>
                        {dup && (
                          <span className="tv-agent-cell-sub">
                            <Badge tone="warning" dot>
                              {t("dealers.cards.duplicate")}
                            </Badge>
                          </span>
                        )}
                        {row.location && (
                          <span className="tv-agent-cell-sub">
                            {t("dealers.roster.locationLabel")}: {row.location}
                          </span>
                        )}
                      </div>
                      <div role="cell">
                        {[row.phone, row.email].filter(Boolean).join(" · ") ||
                          "—"}
                      </div>
                      <div role="cell">
                        <Select
                          aria-label={t("dealers.cards.colDealer")}
                          value={pick}
                          onChange={(e) =>
                            changePick(row, e.target.value)
                          }
                        >
                          <option value="">
                            {t("dealers.cards.pickDealer")}
                          </option>
                          {companies.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                            </option>
                          ))}
                        </Select>
                        {!pick && (
                          <span className="tv-agent-cell-sub">
                            {t("dealers.cards.needDealer")}
                          </span>
                        )}
                        {orgOffPick ? (
                          <span className="tv-agent-cell-sub">
                            {t("dealers.cards.onCard").replace(
                              "{org}",
                              row.org,
                            )}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
              {preview.errors.length > 0 && (
                <ul className="tv-agent-import-errors">
                  {preview.errors.map((err) => (
                    <li key={err.index}>
                      {t("dealers.cards.cardSkipped").replace(
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
