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
import { AttachmentList } from "../../inventory/components/AttachmentList";
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
  SCHEDULE_KIND_LABELS,
  fullDate,
  scheduleTitle,
} from "../format";
import type { ItemStanding, MaintenanceSchedule, ScheduleKind } from "../types";

/**
 * The Maintenance (schedules) section on a tool/battery detail
 * page: the item's calibration/service/inspection schedules with
 * computed due standings, a log of performed work per schedule,
 * and the add/log forms. Data rides the same standing payload as
 * the Repairs panel (ItemCarePanels fetches once).
 */

function ScheduleBlock({
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
    <div style={{ borderTop: "1px solid var(--edge)", paddingTop: "0.6rem", display: "grid", gap: "0.5rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "1rem",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <span style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <strong>{scheduleTitle(schedule)}</strong>
          <Badge tone={DUE_STATUS_TONES[schedule.due_status]} dot>
            {DUE_STATUS_LABELS[schedule.due_status]}
            {schedule.next_due ? ` · ${fullDate(schedule.next_due)}` : ""}
          </Badge>
        </span>
        <span style={{ display: "flex", gap: "0.5rem" }}>
          {!logging && (
            <Button
              type="button"
              size="sm"
              onClick={() => {
                /* Opening the log form starts the done date on
                 * today (owner's date rule, 2026-11-04). */
                setDoneDate(todayLocalIso());
                setLogging(true);
              }}
            >
              Mark done
            </Button>
          )}
          <Button type="button" size="sm" variant="secondary" loading={busy} onClick={() => void onDelete()}>
            Delete
          </Button>
        </span>
      </div>
      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "0.9rem" }}>
        {SCHEDULE_KIND_LABELS[schedule.kind]}
        {schedule.interval_days ? ` · every ${schedule.interval_days} days` : ""}
        {schedule.last_done_at ? ` · last done ${fullDate(schedule.last_done_at)}` : " · never done"}
      </p>

      {logging && (
        <form
          onSubmit={(e) => void onLog(e)}
          style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}
        >
          <DatePicker aria-label="Done date" value={doneDate} onChange={setDoneDate} clearable />
          <TextInput type="number" min="0" step="any" placeholder="Cost" value={cost} onChange={(e) => setCost(e.target.value)} />
          <TextInput placeholder="Technician / shop" value={technician} onChange={(e) => setTechnician(e.target.value)} />
          <span style={{ display: "flex", gap: "0.5rem" }}>
            <Button type="submit" size="sm" loading={busy}>
              Save
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => setLogging(false)}>
              Cancel
            </Button>
          </span>
        </form>
      )}

      {schedule.log.length > 0 && (
        <div style={{ display: "grid", gap: "0.55rem" }}>
          {schedule.log.slice(0, 5).map((entry) => (
            <LogEntryBlock key={entry.id} entry={entry} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}

/** One performed-work log entry: its facts, its documents
 *  (Package B — calibration certificates ride the entry), and an
 *  "Add document" upload (presigned flow, documents kind). */
function LogEntryBlock({
  entry,
  onChanged,
}: {
  entry: ItemStanding["schedules"][number]["log"][number];
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

  return (
    <div style={{ display: "grid", gap: "0.35rem" }}>
      <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--text-muted)" }}>
        {fullDate(entry.done_date)}
        {entry.cost ? ` · ${formatMoney(entry.cost)}` : ""}
        {entry.technician ? ` · ${entry.technician}` : ""}
        {entry.notes ? ` · “${entry.notes}”` : ""}
      </p>
      {entry.attachments && entry.attachments.length > 0 && (
        <AttachmentList
          items={entry.attachments}
          emailPath=""
          onView={(attachment) => setViewing(attachment)}
        />
      )}
      <div>
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
      </div>
      <AttachmentViewer
        attachment={viewing}
        onClose={() => setViewing(null)}
      />
    </div>
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
        {standing.schedules.map((schedule) => (
          <ScheduleBlock key={schedule.id} schedule={schedule} onChanged={onChanged} />
        ))}
        {!adding ? (
          <div>
            <Button type="button" size="sm" variant="secondary" onClick={() => setAdding(true)}>
              Add schedule
            </Button>
          </div>
        ) : (
          <form onSubmit={(e) => void onAdd(e)} style={{ display: "grid", gap: "0.5rem" }}>
            <div style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
              <Select value={kind} onChange={(e) => setKind(e.target.value as ScheduleKind)} aria-label="Kind">
                <option value="calibration">Calibration</option>
                <option value="service">Service</option>
                <option value="inspection">Inspection</option>
                <option value="other">Other</option>
              </Select>
              <TextInput placeholder="Label (e.g. Annual calibration)" value={label} onChange={(e) => setLabel(e.target.value)} />
              <TextInput type="number" min="1" step="1" placeholder="Every N days" value={interval} onChange={(e) => setInterval(e.target.value)} />
              <DatePicker aria-label="First due date" value={dueDate} onChange={setDueDate} clearable />
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <Button type="submit" size="sm" loading={busy}>
                Add schedule
              </Button>
              <Button type="button" size="sm" variant="secondary" onClick={() => setAdding(false)}>
                Cancel
              </Button>
            </div>
          </form>
        )}
      </div>
    </Panel>
  );
}
