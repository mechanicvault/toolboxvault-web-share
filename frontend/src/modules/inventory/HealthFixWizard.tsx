import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  DatePicker,
  FormField,
  Modal,
  TextInput,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { api, ApiError } from "../../lib/api";
import { todayLocalIso } from "../../lib/format";
import {
  StagedFilePicker,
  uploadStagedFiles,
  type StagedFile,
} from "./components/StagedPhotoPicker";
import type { HealthCheckItem } from "./types";
import "./wizard.css";

/**
 * Fix-all wizard (sweep E3, busy-work #5): offered only after
 * the Health Check page asks (more than 10 items flagged) and
 * the user says yes. Walks the flagged queue item by item, ONE
 * STEP PER MISSING FIELD, in the brief's order — photo, model
 * number, purchase date, serial number — plus one serial step
 * per set piece missing its serial. Each step names the item
 * and shows its identifying data (brand / model / serial as
 * recorded) so the user knows what they're looking at.
 *
 * Saves ride the EXISTING paths only: item edits through the
 * item's own PUT, piece serials through the piece's own PUT,
 * photos through the shared staged-photo upload (presigned URL
 * → PUT → attach) filed onto the item. Skip on every step —
 * skipped fields simply stay flagged. Closing the wizard early
 * lands on the same summary, with everything not yet reached
 * counted as skipped. The summary is plain: fixed vs skipped.
 */

type FieldKind = "photo" | "model" | "purchase_date" | "serial" | "piece_serial";

interface WizardStep {
  item: HealthCheckItem;
  field: FieldKind;
  piece?: { id: string; name: string };
}

/** The queue: scan order (name order), one step per missing
 *  field per item. The scan's single "identifier" gap is BOTH a
 *  model and a serial number missing, so it expands to a model
 *  step and a serial step — filling either one clears the scan
 *  flag; the other is still an empty field the user may fill or
 *  skip. */
export function buildWizardSteps(items: HealthCheckItem[]): WizardStep[] {
  const steps: WizardStep[] = [];
  for (const item of items) {
    if (item.missing.includes("photo"))
      steps.push({ item, field: "photo" });
    if (item.missing.includes("identifier"))
      steps.push({ item, field: "model" });
    if (item.missing.includes("purchase_date"))
      steps.push({ item, field: "purchase_date" });
    if (item.missing.includes("identifier"))
      steps.push({ item, field: "serial" });
    for (const piece of item.pieces_missing)
      steps.push({ item, field: "piece_serial", piece });
  }
  return steps;
}

function itemBasePath(item: HealthCheckItem): string {
  return item.kind === "tool"
    ? `/inventory/${item.id}`
    : `/inventory/batteries/${item.id}`;
}

export default function HealthFixWizard({
  items,
  onFinish,
}: {
  items: HealthCheckItem[];
  /** Called when the wizard closes (summary Done, or early
   *  close): the page re-runs the scan. */
  onFinish: () => void;
}) {
  const t = useT();
  const steps = useMemo(() => buildWizardSteps(items), [items]);
  const [index, setIndex] = useState(0);
  const [done, setDone] = useState(false);
  const [fixed, setFixed] = useState<string[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [date, setDate] = useState(todayLocalIso());
  const [photos, setPhotos] = useState<StagedFile[]>([]);

  const step = steps[index] as WizardStep | undefined;

  function stepLabel(s: WizardStep): string {
    const fieldKey =
      s.field === "photo"
        ? "inventory.health.labelPhoto"
        : s.field === "model"
          ? "inventory.health.wiz.modelLabel"
          : s.field === "serial" || s.field === "piece_serial"
            ? "inventory.health.wiz.serialLabel"
            : "inventory.health.labelPurchase";
    const base = `${s.item.name} — ${t(fieldKey as never)}`;
    return s.piece ? `${base} (${s.piece.name})` : base;
  }

  function resetInputs() {
    setText("");
    setDate(todayLocalIso());
    setPhotos([]);
    setError("");
  }

  function advance(wasFixed: boolean, s: WizardStep) {
    if (wasFixed) setFixed((f) => [...f, stepLabel(s)]);
    else setSkipped((f) => [...f, stepLabel(s)]);
    resetInputs();
    if (index + 1 >= steps.length) setDone(true);
    else setIndex(index + 1);
  }

  /** Early close: everything not yet reached counts as skipped,
   *  then the summary shows — the fixed/skipped split stays
   *  honest however the wizard ends. */
  function closeEarly() {
    if (done) {
      onFinish();
      return;
    }
    setSkipped((prev) => [
      ...prev,
      ...steps.slice(index).map((s) => stepLabel(s)),
    ]);
    setDone(true);
  }

  async function save() {
    if (!step) return;
    setBusy(true);
    setError("");
    try {
      if (step.field === "photo") {
        if (photos.length === 0) {
          setError(t("inventory.health.wiz.photoNeed"));
          setBusy(false);
          return;
        }
        const { failed } = await uploadStagedFiles(
          itemBasePath(step.item),
          "photo",
          photos,
          setPhotos,
        );
        if (failed.length > 0) {
          setError(t("inventory.health.wiz.saveFailed"));
          setBusy(false);
          return;
        }
      } else if (step.field === "piece_serial" && step.piece) {
        await api(`/inventory/pieces/${step.piece.id}`, {
          method: "PUT",
          body: JSON.stringify({ serial_number: text.trim() }),
        });
      } else {
        const payload =
          step.field === "model"
            ? { model: text.trim() }
            : step.field === "serial"
              ? { serial_number: text.trim() }
              : { purchase_date: date };
        await api(itemBasePath(step.item), {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      }
      setBusy(false);
      advance(true, step);
    } catch (err) {
      setBusy(false);
      setError(
        err instanceof ApiError
          ? err.message
          : t("inventory.health.wiz.saveFailed"),
      );
    }
  }

  const prompt = step
    ? step.field === "photo"
      ? t("inventory.health.wiz.photoPrompt").replace("{name}", step.item.name)
      : step.field === "model"
        ? t("inventory.health.wiz.modelPrompt").replace("{name}", step.item.name)
        : step.field === "serial"
          ? t("inventory.health.wiz.serialPrompt").replace("{name}", step.item.name)
          : step.field === "piece_serial" && step.piece
            ? t("inventory.health.wiz.pieceSerialPrompt")
                .replace("{piece}", step.piece.name)
                .replace("{name}", step.item.name)
            : t("inventory.health.wiz.datePrompt").replace("{name}", step.item.name)
    : "";

  const identBits: string[] = [];
  if (step) {
    identBits.push(
      t(
        step.item.kind === "tool"
          ? "inventory.health.wiz.kindTool"
          : "inventory.health.wiz.kindBattery",
      ),
    );
    if (step.item.brand) identBits.push(step.item.brand);
    if (step.item.model)
      identBits.push(
        `${t("inventory.health.wiz.modelLabel")}: ${step.item.model}`,
      );
    if (step.item.serial_number)
      identBits.push(
        `${t("inventory.health.wiz.serialLabel")}: ${step.item.serial_number}`,
      );
  }

  return (
    <Modal
      open
      onClose={closeEarly}
      title={t("inventory.health.wiz.title")}
      footer={
        done ? (
          <Button type="button" variant="primary" onClick={onFinish}>
            {t("inventory.health.wiz.done")}
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() => step && advance(false, step)}
            >
              {t("inventory.health.wiz.skip")}
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={busy}
              onClick={save}
            >
              {t("inventory.health.wiz.saveNext")}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <div className="tv-health-wiz">
          <p className="tv-health-wiz-summary-line">
            <strong>
              {t("inventory.health.wiz.summaryLine")
                .replace("{fixed}", String(fixed.length))
                .replace("{skipped}", String(skipped.length))}
            </strong>
          </p>
          {fixed.length > 0 && (
            <div>
              <p className="tv-health-wiz-list-title">
                <strong>{t("inventory.health.wiz.summaryFixedTitle")}</strong>
              </p>
              <ul className="tv-health-wiz-list">
                {fixed.map((label, i) => (
                  <li key={i}>{label}</li>
                ))}
              </ul>
            </div>
          )}
          {skipped.length > 0 && (
            <div>
              <p className="tv-health-wiz-list-title">
                <strong>{t("inventory.health.wiz.summarySkippedTitle")}</strong>
              </p>
              <ul className="tv-health-wiz-list">
                {skipped.map((label, i) => (
                  <li key={i}>{label}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : step ? (
        <div className="tv-health-wiz">
          <p className="tv-health-wiz-step">
            {t("inventory.health.wiz.stepOf")
              .replace("{step}", String(index + 1))
              .replace("{total}", String(steps.length))}
          </p>
          <div>
            <p className="tv-health-wiz-name">
              <strong>{step.item.name}</strong>
            </p>
            <p className="tv-health-wiz-ident">
              {identBits.join(" · ")}
            </p>
          </div>
          <p className="tv-health-plain">{prompt}</p>
          {error && <Alert tone="danger">{error}</Alert>}
          {step.field === "photo" ? (
            <StagedFilePicker
              kind="photo"
              files={photos}
              onChange={setPhotos}
              disabled={busy}
            />
          ) : step.field === "purchase_date" ? (
            <FormField label={t("inventory.health.wiz.dateLabel")}>
              <DatePicker value={date} onChange={setDate} />
            </FormField>
          ) : (
            <FormField
              label={t(
                step.field === "model"
                  ? "inventory.health.wiz.modelLabel"
                  : "inventory.health.wiz.serialLabel",
              )}
            >
              <TextInput
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={busy}
              />
            </FormField>
          )}
        </div>
      ) : (
        <p className="tv-health-plain">{t("inventory.health.wiz.none")}</p>
      )}
    </Modal>
  );
}
