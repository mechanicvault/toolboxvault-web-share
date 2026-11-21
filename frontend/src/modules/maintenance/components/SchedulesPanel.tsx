import { useRef, useState, type FormEvent } from "react";
import {
  AttachmentViewer,
  Badge,
  Button,
  DatePicker,
  Panel,
  Select,
  TextInput,
  useToast,
} from "../../../components";
import { ApiError } from "../../../lib/api";
import { todayLocalIso } from "../../../lib/format";
import { formatMoney } from "../../../lib/money";
import {
  acceptForKind,
  attachmentFileError,
  fileContentType,
} from "../../inventory/components/photoTransfer";
import type { Attachment } from "../../inventory/types";
import { createSchedule, deleteSchedule, logDone, uploadLogEntryDocument } from "../api";
import {
  DUE_STATUS_LABELS,
  DUE_STATUS_TONES,
  fullDate,
  scheduleTitle,
} from "../format";
import type { ItemStanding, MaintenanceSchedule, ScheduleKind } from "../types";
/* The service-book styles live with the module; importing
 * them here (not only via boards.tsx) is what guarantees the
 * item page carries them — the Repairs page chunk is not
 * loaded on a detail page. */
import "../maintenance.css";

/**
 * The Maintenance tab on a tool/battery detail page — the
 * SERVICE BOOK (owner's pick M3, 2026-11-16, replacing the
 * stacked schedule blocks he called "ugly, not user friendly,
 * no flow"):
 *
 * 1. COMING DUE — one card per schedule: its name, a status
 *    pill (an overdue pill carries the day count and the card
 *    itself burns red), one line of facts (due date, interval,
 *    last done), and a Mark done button that opens the labeled
 *    log form right in the card (Date done / Cost / Who did
 *    it). Delete rides the card too, as before.
 * 2. SERVICE RECORD — ONE table of every work log entry on
 *    the item across all schedules, newest first: DATE DONE ·
 *    SCHEDULE · DONE BY · COST · DOCUMENT. A document cell
 *    opens the entry's files in the viewer and still takes an
 *    upload, like the old per-entry block did.
 * 3. The schedules strip — the item's schedule names in one
 *    line, with Add schedule beside them; the add form opens
 *    in place under the strip, every field labeled.
 *
 * Data rides the same standing payload as the Repairs panel
 * (ItemCarePanels fetches once); every write calls onChanged
 * and the whole book re-reads.
 */

type LogRow = {
  entry: MaintenanceSchedule["log"][number];
  schedule: MaintenanceSchedule;
};

const STATUS_RANK: Record<MaintenanceSchedule["due_status"], number> = {
  overdue: 0,
  due_soon: 1,
  ok: 2,
  unknown: 3,
};

function overdueDays(nextDue: string | null): number {
  if (!nextDue) return 0;
  const due = new Date(`${nextDue.slice(0, 10)}T00:00:00`);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(0, Math.round((today.getTime() - due.getTime()) / 86_400_000));
}

function statusPill(schedule: MaintenanceSchedule): string {
  const label = DUE_STATUS_LABELS[schedule.due_status];
  if (schedule.due_status === "overdue") {
    const days = overdueDays(schedule.next_due);
    return days > 0 ? `${label} · ${days} ${days === 1 ? "day" : "days"}` : label;
  }
  if (schedule.due_status === "due_soon" && schedule.next_due) {
    return `${label} · ${fullDate(schedule.next_due)}`;
  }
  return label;
}

function dueLine(schedule: MaintenanceSchedule): string {
  const parts: string[] = [];
  if (schedule.next_due) {
    parts.push(
      schedule.due_status === "overdue"
        ? `Was due ${fullDate(schedule.next_due)}`
        : `Due ${fullDate(schedule.next_due)}`,
    );
  }
  if (schedule.interval_days) parts.push(`every ${schedule.interval_days} days`);
  parts.push(
    schedule.last_done_at
      ? `last done ${fullDate(schedule.last_done_at)}`
      : "never done",
  );
  return parts.join(" · ");
}

function ScheduleCard({
  schedule,
  onChanged,
}: {
  schedule: MaintenanceSchedule;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [logging, setLogging] = useState(false);
  const [doneDate, setDoneDate] = useState("");
  const [cost, setCost] = useState("");
  const [technician, setTechnician] = useState("");
  const [busy, setBusy] = useState(false);
  const overdue = schedule.due_status === "overdue";

  async function onLog(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await logDone(schedule.id, {
        done_date: doneDate || null,
        cost: cost === "" ? null : cost,
        technician,
      });
      toast("Work logged — the next due date moved.", {
        tone: "success",
        title: "Maintenance",
      });
      setLogging(false);
      setDoneDate("");
      setCost("");
      setTechnician("");
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't log that.", {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!window.confirm(`Delete the “${scheduleTitle(schedule)}” schedule? Its log goes with it.`)) return;
    setBusy(true);
    try {
      await deleteSchedule(schedule.id);
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't delete that schedule.", {
        tone: "danger",
      });
      setBusy(false);
    }
  }

  return (
    <div className={`tv-svc-card${overdue ? " is-overdue" : ""}`}>
      <div className="tv-svc-card-head">
        <strong>{scheduleTitle(schedule)}</strong>
        <Badge tone={DUE_STATUS_TONES[schedule.due_status]} dot>
          {statusPill(schedule)}
        </Badge>
      </div>
      <p className="tv-svc-card-note">{dueLine(schedule)}</p>
      {!logging ? (
        <div className="tv-svc-card-actions">
          <Button
            type="button"
            size="sm"
            variant={overdue ? "primary" : "secondary"}
            onClick={() => {
              /* Opening the log form starts the done date on
               * today (owner's date rule, 2026-11-04). */
              setDoneDate(todayLocalIso());
              setLogging(true);
            }}
          >
            Mark done
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            loading={busy}
            onClick={() => void onDelete()}
          >
            Delete
          </Button>
        </div>
      ) : (
        <form onSubmit={(e) => void onLog(e)} className="tv-svc-logform">
          <label className="tv-svc-field">
            <span>Date done</span>
            <DatePicker aria-label="Date done" value={doneDate} onChange={setDoneDate} clearable />
          </label>
          <label className="tv-svc-field">
            <span>Cost</span>
            <TextInput type="number" min="0" step="any" value={cost} onChange={(e) => setCost(e.target.value)} />
          </label>
          <label className="tv-svc-field">
            <span>Who did it</span>
            <TextInput value={technician} onChange={(e) => setTechnician(e.target.value)} />
          </label>
          <span className="tv-svc-form-actions">
            <Button type="submit" size="sm" loading={busy}>
              Save
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => setLogging(false)}>
              Cancel
            </Button>
          </span>
        </form>
      )}
    </div>
  );
}

/** One service-record row's document cell: the entry's files
 *  as named buttons into the shared viewer, plus the upload
 *  the old per-entry block carried (presigned flow, documents
 *  kind). */
function DocumentCell({
  entry,
  onChanged,
}: {
  entry: LogRow["entry"];
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [viewing, setViewing] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function onPick(file: File | undefined) {
    if (!file) return;
    const problem = attachmentFileError("document", file);
    if (problem) {
      toast(problem, { tone: "danger", title: "Document" });
      return;
    }
    setUploading(true);
    try {
      await uploadLogEntryDocument(entry.id, file, fileContentType(file));
      toast("Document attached to the log entry.", {
        tone: "success",
        title: "Maintenance",
      });
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't attach that document.", {
        tone: "danger",
      });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const files = entry.attachments ?? [];
  return (
    <span className="tv-svc-doccell">
      {files.map((file) => (
        <button
          key={file.key}
          type="button"
          className="tv-svc-doclink"
          onClick={() => setViewing(file)}
        >
          {file.filename}
        </button>
      ))}
      <input
        ref={fileRef}
        type="file"
        accept={acceptForKind("document")}
        style={{ display: "none" }}
        onChange={(e) => void onPick(e.target.files?.[0])}
      />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        loading={uploading}
        onClick={() => fileRef.current?.click()}
      >
        Add document
      </Button>
      <AttachmentViewer attachment={viewing} onClose={() => setViewing(null)} />
    </span>
  );
}

export function SchedulesPanel({
  standing,
  onChanged,
}: {
  standing: ItemStanding;
  onChanged: () => void;
}) {
  const { toast } = useToast();
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<ScheduleKind>("service");
  const [label, setLabel] = useState("");
  const [interval, setInterval] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [busy, setBusy] = useState(false);

  // Pieces carry no schedules (they aren't assets).
  if (standing.item_kind === "piece") return null;
  const assetKind: "tool" | "battery" = standing.item_kind;

  const cards = [...standing.schedules].sort(
    (a, b) =>
      STATUS_RANK[a.due_status] - STATUS_RANK[b.due_status] ||
      (a.next_due ?? "9999").localeCompare(b.next_due ?? "9999"),
  );
  const record: LogRow[] = standing.schedules
    .flatMap((schedule) => schedule.log.map((entry) => ({ entry, schedule })))
    .sort((a, b) => b.entry.done_date.localeCompare(a.entry.done_date));

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    if (!interval && !dueDate) {
      toast("Give the schedule an interval or a due date.", { tone: "danger" });
      return;
    }
    setBusy(true);
    try {
      await createSchedule(assetKind, standing.item_id, {
        kind,
        label: label.trim(),
        interval_days: interval ? Number(interval) : null,
        due_date: dueDate || null,
      });
      toast("Schedule added.", { tone: "success", title: "Maintenance" });
      setAdding(false);
      setLabel("");
      setInterval("");
      setDueDate("");
      onChanged();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't add that schedule.", {
        tone: "danger",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Maintenance schedules">
      <div style={{ display: "grid", gap: "var(--space-3)" }}>
        {standing.schedules.length === 0 && !adding && (
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            No schedules yet — add one for calibration, service, or inspection
            and it will show here and on the Maintenance page as it comes due.
          </p>
        )}

        {cards.length > 0 && (
          <section>
            <h3 className="tv-svc-head">Coming due</h3>
            <div className="tv-svc-cards">
              {cards.map((schedule) => (
                <ScheduleCard key={schedule.id} schedule={schedule} onChanged={onChanged} />
              ))}
            </div>
          </section>
        )}

        {standing.schedules.length > 0 && (
          <section>
            <h3 className="tv-svc-head">Service record</h3>
            {record.length === 0 ? (
              <p style={{ margin: 0, color: "var(--text-muted)" }}>
                No work logged yet — when you mark a schedule done, it lands
                here as this item's service record.
              </p>
            ) : (
              <div className="tv-maint-table tv-maint-table--service" role="table">
                <div className="tv-maint-thead" role="row">
                  <span role="columnheader">Date done</span>
                  <span role="columnheader">Schedule</span>
                  <span role="columnheader">Done by</span>
                  <span role="columnheader">Cost</span>
                  <span role="columnheader">Document</span>
                </div>
                {record.map(({ entry, schedule }) => (
                  <div key={entry.id} className="tv-maint-row" role="row">
                    <span>{fullDate(entry.done_date)}</span>
                    <span>
                      {scheduleTitle(schedule)}
                      {entry.notes ? (
                        <span className="tv-svc-note">“{entry.notes}”</span>
                      ) : null}
                    </span>
                    <span>{entry.technician || "—"}</span>
                    <span>{entry.cost ? formatMoney(entry.cost) : "—"}</span>
                    <DocumentCell entry={entry} onChanged={onChanged} />
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {standing.schedules.length > 0 && !adding && (
          <div className="tv-svc-strip">
            <span className="tv-svc-strip-names">
              Schedules on this item:{" "}
              {cards.map((schedule, i) => (
                <span key={schedule.id}>
                  {i > 0 ? " · " : ""}
                  <strong>{scheduleTitle(schedule)}</strong>
                </span>
              ))}
            </span>
            <Button type="button" size="sm" variant="secondary" onClick={() => setAdding(true)}>
              Add schedule
            </Button>
          </div>
        )}
        {standing.schedules.length === 0 && !adding && (
          <div>
            <Button type="button" size="sm" variant="secondary" onClick={() => setAdding(true)}>
              Add schedule
            </Button>
          </div>
        )}
        {adding && (
          <form onSubmit={(e) => void onAdd(e)} className="tv-svc-addform">
            <label className="tv-svc-field">
              <span>Kind</span>
              <Select value={kind} onChange={(e) => setKind(e.target.value as ScheduleKind)} aria-label="Kind">
                <option value="calibration">Calibration</option>
                <option value="service">Service</option>
                <option value="inspection">Inspection</option>
                <option value="other">Other</option>
              </Select>
            </label>
            <label className="tv-svc-field">
              <span>Label</span>
              <TextInput placeholder="e.g. Annual calibration" value={label} onChange={(e) => setLabel(e.target.value)} />
            </label>
            <label className="tv-svc-field">
              <span>Every N days</span>
              <TextInput type="number" min="1" step="1" value={interval} onChange={(e) => setInterval(e.target.value)} />
            </label>
            <label className="tv-svc-field">
              <span>First due date</span>
              <DatePicker aria-label="First due date" value={dueDate} onChange={setDueDate} clearable />
            </label>
            <span className="tv-svc-form-actions">
              <Button type="submit" size="sm" loading={busy}>
                Add schedule
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </span>
          </form>
        )}
      </div>
    </Panel>
  );
}
