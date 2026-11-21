import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Alert,
  AttachmentViewer,
  Button,
  DatePicker,
  FileUpload,
  FormField,
  Panel,
  QuietSkeleton,
  Select,
  TextArea,
  TextInput,
  useToast,
} from "../../../components";
import { api, ApiError } from "../../../lib/api";
import { todayLocalIso } from "../../../lib/format";
import { useT } from "../../../i18n/LocaleContext";
import { displayDate } from "../format";
import type { Attachment, LossReport } from "../types";
import { AttachmentList } from "./AttachmentList";

const docsBlockStyle = { display: "grid", gap: "0.5rem" } as const;
const docsHintStyle = {
  margin: 0,
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;
const docsEmptyStyle = { margin: 0, color: "var(--text-muted)" } as const;
const docsSectionStyle = { marginTop: "1rem" } as const;
const historyDocsStyle = { marginTop: "0.5rem", color: "var(--text)" } as const;
import {
  acceptForKind,
  attachmentFileError,
  uploadAttachmentFile,
} from "./photoTransfer";

/**
 * Lost/Stolen report panel (gap wave 1), shown in its own modal
 * window on the tool + battery detail pages (owner correction,
 * 2026-10-31 — it no longer sits in the Details tab). The
 * standing says an item IS lost or stolen; this panel carries
 * the paper trail — police report, insurer, claim number — as
 * its own record:
 *
 *  - no open report: a "Report lost or stolen" form (marking
 *    the item and opening the record are ONE action; every
 *    detail field is optional and can be filled in later);
 *  - an open report: its fields, editable, plus Mark recovered
 *    (the item returns to service and the report CLOSES — it is
 *    kept below as history, never deleted);
 *  - past reports render read-only under History.
 */
/**
 * One report's documents (police-report uploads, 2026-10-25): the
 * files ride the item's regular document machinery (presigned
 * upload, document size/type rules) with the report's id stamped
 * on the attachment, so they live on the item's record AND belong
 * to this report — the list read hands them back grouped here.
 * Editable on the open report (upload + delete); read-only on
 * history rows. Every entry opens the shared AttachmentViewer.
 */
function ReportDocuments({
  report,
  itemKind,
  itemId,
  editable,
  onChanged,
}: {
  report: LossReport;
  itemKind: "tool" | "battery";
  itemId: string;
  editable: boolean;
  onChanged: () => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [viewing, setViewing] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState(false);
  const itemBase =
    itemKind === "battery"
      ? `/inventory/batteries/${itemId}`
      : `/inventory/${itemId}`;
  const emailPath = `${itemBase}/attachments/email`;

  async function onFiles(picked: File[]) {
    if (picked.length === 0 || uploading) return;
    setUploading(true);
    let failure = "";
    for (const file of picked) {
      const problem = attachmentFileError("document", file);
      if (problem) {
        failure = problem;
        continue;
      }
      try {
        await uploadAttachmentFile(itemBase, "document", file, undefined, {
          loss_report_id: report.id,
        });
      } catch (err) {
        failure =
          err instanceof ApiError ? err.message : "Couldn't upload that file.";
      }
    }
    setUploading(false);
    if (failure) {
      toast(failure, { title: "Something went wrong", tone: "danger" });
    }
    onChanged();
  }

  return (
    <div style={docsBlockStyle}>
      <strong>{t("lossReport.documents")}</strong>
      {editable && <p style={docsHintStyle}>{t("lossReport.documentsHint")}</p>}
      {report.documents.length > 0 ? (
        <AttachmentList
          items={report.documents}
          emailPath={emailPath}
          onView={(a) => setViewing(a)}
          deletePath={editable ? `${itemBase}/attachments` : undefined}
          onDeleted={onChanged}
        />
      ) : (
        <p style={docsEmptyStyle}>{t("lossReport.noDocuments")}</p>
      )}
      {editable && (
        <FileUpload
          onFiles={(picked) => void onFiles(picked)}
          accept={acceptForKind("document")}
          multiple
          disabled={uploading}
          hint="PDF, Word, Excel, text, or a photo of the document · up to 25 MB each"
        />
      )}
      <AttachmentViewer
        attachment={viewing}
        emailPath={emailPath}
        onClose={() => setViewing(null)}
      />
    </div>
  );
}

/** The panel's frame, dropped when the panel rides inside a
 *  Modal (the item pages' loss/stolen window, owner correction
 *  2026-10-31) — the modal supplies the title there, so the
 *  content renders bare rather than double-titled. */
function ReportFrame({
  bare,
  children,
}: {
  bare?: boolean;
  children: ReactNode;
}) {
  if (bare) return <>{children}</>;
  return <Panel title="Lost / stolen report">{children}</Panel>;
}

export function LossReportPanel({
  itemKind,
  itemId,
  onChanged,
  bare,
}: {
  itemKind: "tool" | "battery";
  itemId: string;
  onChanged?: () => void;
  /** Render without the Panel frame (inside the item page's
   *  loss/stolen modal window). */
  bare?: boolean;
}) {
  const { toast } = useToast();
  const [reports, setReports] = useState<LossReport[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Create-form state (also the "open a report" prompt).
  const [standing, setStanding] = useState<"lost" | "stolen">("lost");
  /* A new report starts on today (owner's date rule, 2026-11-04);
   * clearable back to null, as the field allowed before. */
  const [reportedDate, setReportedDate] = useState(() => todayLocalIso());
  const [policeNumber, setPoliceNumber] = useState("");
  const [policeDept, setPoliceDept] = useState("");
  const [insurer, setInsurer] = useState("");
  const [claimNumber, setClaimNumber] = useState("");
  const [notes, setNotes] = useState("");
  // Edit state for the active report (seeded when it loads).
  const [edit, setEdit] = useState<LossReport | null>(null);

  const load = useCallback(() => {
    api<LossReport[]>(`/inventory/${itemKind}/${itemId}/loss-reports`)
      .then((rows) => {
        setReports(rows);
        setEdit(rows.find((r) => r.status === "active") ?? null);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load the report record."),
      );
  }, [itemKind, itemId]);

  useEffect(() => {
    load();
  }, [load]);

  const active = reports?.find((r) => r.status === "active") ?? null;
  const history = (reports ?? []).filter((r) => r.status === "recovered");

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api(`/inventory/${itemKind}/${itemId}/loss-reports`, {
        method: "POST",
        body: JSON.stringify({
          standing,
          reported_date: reportedDate || null,
          police_report_number: policeNumber.trim(),
          police_department: policeDept.trim(),
          insurer_name: insurer.trim(),
          claim_number: claimNumber.trim(),
          notes: notes.trim(),
        }),
      });
      toast("Report opened — the item is marked " + standing + ".", {
        title: "Lost/stolen report",
        tone: "success",
      });
      setPoliceNumber("");
      setPoliceDept("");
      setInsurer("");
      setClaimNumber("");
      setNotes("");
      setReportedDate(todayLocalIso());
      load();
      onChanged?.();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't open the report.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onSaveEdit(event: FormEvent) {
    event.preventDefault();
    if (!edit) return;
    setBusy(true);
    try {
      await api(`/inventory/loss-reports/${edit.id}`, {
        method: "PUT",
        body: JSON.stringify({
          reported_date: edit.reported_date,
          police_report_number: edit.police_report_number,
          police_department: edit.police_department,
          insurer_name: edit.insurer_name,
          claim_number: edit.claim_number,
          notes: edit.notes,
        }),
      });
      toast("Report updated.", { title: "Saved", tone: "success" });
      load();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save the report.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onRecover() {
    if (!active) return;
    if (
      !window.confirm(
        "Mark this item recovered? It goes back into service and the report closes (it stays in the history below).",
      )
    )
      return;
    setBusy(true);
    try {
      await api(`/inventory/loss-reports/${active.id}/recover`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      toast("Marked recovered — welcome back.", { title: "Recovered", tone: "success" });
      load();
      onChanged?.();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't mark it recovered.", {
        title: "Something went wrong",
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  const grid = {
    display: "grid",
    gap: "0.8rem",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  } as const;

  return (
    <ReportFrame bare={bare}>
      {error && (
        <div style={{ marginBottom: "0.6rem" }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {reports === null ? (
        <QuietSkeleton lines={2} />
      ) : active && edit ? (
        <>
        <form onSubmit={(e) => void onSaveEdit(e)} style={{ display: "grid", gap: "0.8rem" }}>
          <p style={{ margin: 0 }}>
            This item is marked <strong>{active.standing}</strong> — reported{" "}
            {displayDate(active.reported_date)}. Keep the paper trail
            current; it feeds your reports and a claim.
          </p>
          <div style={grid}>
            <FormField label="Reported date" htmlFor="lr-date">
              <DatePicker
                id="lr-date"
                value={edit.reported_date ?? ""}
                onChange={(v) => setEdit({ ...edit, reported_date: v || null })}
                clearable
              />
            </FormField>
            <FormField label="Police report #" htmlFor="lr-police">
              <TextInput
                id="lr-police"
                value={edit.police_report_number}
                onChange={(e) => setEdit({ ...edit, police_report_number: e.target.value })}
              />
            </FormField>
            <FormField label="Police department" htmlFor="lr-dept">
              <TextInput
                id="lr-dept"
                value={edit.police_department}
                onChange={(e) => setEdit({ ...edit, police_department: e.target.value })}
              />
            </FormField>
            <FormField label="Insurer" htmlFor="lr-insurer">
              <TextInput
                id="lr-insurer"
                value={edit.insurer_name}
                onChange={(e) => setEdit({ ...edit, insurer_name: e.target.value })}
              />
            </FormField>
            <FormField label="Claim number" htmlFor="lr-claim">
              <TextInput
                id="lr-claim"
                value={edit.claim_number}
                onChange={(e) => setEdit({ ...edit, claim_number: e.target.value })}
              />
            </FormField>
          </div>
          <FormField label="Notes" htmlFor="lr-notes">
            <TextArea
              id="lr-notes"
              value={edit.notes}
              onChange={(e) => setEdit({ ...edit, notes: e.target.value })}
            />
          </FormField>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button type="submit" loading={busy}>
              Save report
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={busy}
              onClick={() => void onRecover()}
            >
              Mark recovered
            </Button>
          </div>
        </form>
        <div style={docsSectionStyle}>
          <ReportDocuments
            report={active}
            itemKind={itemKind}
            itemId={itemId}
            editable
            onChanged={load}
          />
        </div>
        </>
      ) : (
        <form onSubmit={(e) => void onCreate(e)} style={{ display: "grid", gap: "0.8rem" }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            If this item goes missing, open a report: the item is
            marked lost or stolen and the details below become its
            record for the police and your insurer. Every field is
            optional — you can fill them in later.
          </p>
          <div style={grid}>
            <FormField label="What happened?" htmlFor="lr-standing">
              <Select
                id="lr-standing"
                value={standing}
                onChange={(e) => setStanding(e.target.value as "lost" | "stolen")}
              >
                <option value="lost">Lost</option>
                <option value="stolen">Stolen</option>
              </Select>
            </FormField>
            <FormField label="Reported date" htmlFor="lr-c-date">
              <DatePicker
                id="lr-c-date"
                value={reportedDate}
                onChange={setReportedDate}
                clearable
              />
            </FormField>
            <FormField label="Police report #" htmlFor="lr-c-police">
              <TextInput
                id="lr-c-police"
                value={policeNumber}
                onChange={(e) => setPoliceNumber(e.target.value)}
              />
            </FormField>
            <FormField label="Police department" htmlFor="lr-c-dept">
              <TextInput
                id="lr-c-dept"
                value={policeDept}
                onChange={(e) => setPoliceDept(e.target.value)}
              />
            </FormField>
            <FormField label="Insurer" htmlFor="lr-c-insurer">
              <TextInput
                id="lr-c-insurer"
                value={insurer}
                onChange={(e) => setInsurer(e.target.value)}
              />
            </FormField>
            <FormField label="Claim number" htmlFor="lr-c-claim">
              <TextInput
                id="lr-c-claim"
                value={claimNumber}
                onChange={(e) => setClaimNumber(e.target.value)}
              />
            </FormField>
          </div>
          <FormField label="Notes" htmlFor="lr-c-notes">
            <TextArea
              id="lr-c-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </FormField>
          <div>
            <Button type="submit" loading={busy}>
              Report {standing === "lost" ? "lost" : "stolen"}
            </Button>
          </div>
        </form>
      )}
      {history.length > 0 && (
        <div style={{ marginTop: "1rem", display: "grid", gap: "0.5rem" }}>
          <strong>History</strong>
          {history.map((row) => (
            <div
              key={row.id}
              style={{
                borderTop: "1px solid var(--edge)",
                paddingTop: "0.5rem",
                color: "var(--text-muted)",
              }}
            >
              Marked {row.standing} — reported {displayDate(row.reported_date)},
              recovered {displayDate(row.recovered_date)}.
              {row.police_report_number && <> Police report {row.police_report_number}.</>}
              {row.claim_number && <> Claim {row.claim_number}.</>}
              {row.notes && <div style={{ whiteSpace: "pre-wrap" }}>{row.notes}</div>}
              {row.documents.length > 0 && (
                <div style={historyDocsStyle}>
                  <ReportDocuments
                    report={row}
                    itemKind={itemKind}
                    itemId={itemId}
                    editable={false}
                    onChanged={load}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </ReportFrame>
  );
}
