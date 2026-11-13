import { useEffect, useMemo, useRef, useState } from "react";

import {
  Alert,
  Button,
  DatePicker,
  FileTypeArt,
  FormField,
  Modal,
  ProgressBar,
  Radio,
  Select,
  TextArea,
  TextInput,
} from "../../components";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import {
  createTemplate,
  describeReport,
  generateReport,
  getReportsMeta,
  previewReport,
} from "./api";
import type {
  CatalogType,
  HistoryEntry,
  ReportArea,
  ReportsMeta,
} from "./types";
import { yearOptions } from "./YearPrompt";

/**
 * The report wizard (Ryan's spec): pick the type, pick that
 * type's options, PREVIEW the actual document ("need to change
 * anything?"), then generate — the finished file opens in the
 * page's viewer popup and a copy lands in History — with an
 * optional save-as-template step
 * (system-prefilled name + description, editable; the area ask
 * pre-answered by the type's home). Types are permanent: the
 * catalog lists every kind even when no template exists.
 */

const STEP_KEYS = [
  "reports.wizard.stepType",
  "reports.wizard.stepOptions",
  "reports.wizard.stepPreview",
  "reports.wizard.stepSave",
] as const;

interface PreviewState {
  kind: "pdf" | "csv" | "sheet";
  url?: string;
  text?: string;
}

export function ReportWizard({
  open,
  catalog,
  onClose,
  onGenerated,
  onSavedTemplate,
  audience = "user",
}: {
  open: boolean;
  catalog: CatalogType[];
  onClose: () => void;
  onGenerated: (entry: HistoryEntry) => void;
  onSavedTemplate: () => void;
  /** "admin" (admin lane, 2026-11-07): the same wizard fed the
   *  admin catalog — one type group, and the save area is fixed
   *  to the Admin tab (the server forces it too), so the
   *  quick/accounting radio doesn't render. */
  audience?: "user" | "admin";
}) {
  const t = useT();
  const { toast } = useToast();
  const [step, setStep] = useState(0);
  const [typeKey, setTypeKey] = useState<string | null>(null);
  const [format, setFormat] = useState("pdf");
  const [year, setYear] = useState<string>(String(new Date().getFullYear()));
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [grouping, setGrouping] = useState("category");
  const [setsMode, setSetsMode] = useState("full");
  const [meta, setMeta] = useState<ReportsMeta | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [generated, setGenerated] = useState<HistoryEntry | null>(null);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [saveArea, setSaveArea] = useState<ReportArea>("quick");
  const [saved, setSaved] = useState(false);
  const previewUrlRef = useRef<string | null>(null);

  const type = useMemo(
    () => catalog.find((row) => row.key === typeKey) ?? null,
    [catalog, typeKey],
  );

  // Fresh state every time the wizard opens.
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setTypeKey(null);
    setFormat("pdf");
    setYear(String(new Date().getFullYear()));
    setStartDate("");
    setEndDate("");
    setGrouping("category");
    setSetsMode("full");
    setPreview(null);
    setPreviewError("");
    setError("");
    setGenerated(null);
    setSaveName("");
    setSaveDescription("");
    setSaved(false);
  }, [open ]);

  // The inventory options ride the module meta (groupings).
  useEffect(() => {
    if (!open || meta !== null) return;
    let live = true;
    getReportsMeta()
      .then((data) => {
        if (live) setMeta(data);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [open, meta]);

  const revokePreview = () => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  };
  useEffect(() => revokePreview, []);

  const buildSettings = (): Record<string, unknown> => {
    const settings: Record<string, unknown> = { format };
    if (!type) return settings;
    if (type.settings === "year") {
      settings.year = Number(year);
    } else if (type.settings === "year_or_all") {
      if (year !== "") settings.year = Number(year);
    } else if (type.settings === "period") {
      if (startDate) settings.start = startDate;
      if (endDate) settings.end = endDate;
    } else if (type.settings === "inventory") {
      settings.grouping = grouping;
      settings.sets_mode = setsMode;
    }
    return settings;
  };

  const pickType = (row: CatalogType) => {
    setTypeKey(row.key);
    setFormat(row.formats[0] ?? "pdf");
    if (row.settings === "year_or_all") setYear("");
    if (row.settings === "year") setYear(String(new Date().getFullYear()));
  };

  const loadPreview = async () => {
    if (!type) return;
    revokePreview();
    setPreview(null);
    setPreviewError("");
    if (format === "xlsx") {
      setPreview({ kind: "sheet" });
      return;
    }
    setPreviewBusy(true);
    try {
      const { blob } = await previewReport({
        report_type: type.key,
        settings: buildSettings(),
        format,
      });
      if (format === "pdf") {
        const url = URL.createObjectURL(blob);
        previewUrlRef.current = url;
        setPreview({ kind: "pdf", url });
      } else {
        const text = await blob.text();
        setPreview({ kind: "csv", text: text.split("\n").slice(0, 60).join("\n") });
      }
    } catch (err) {
      setPreviewError(
        err instanceof ApiError ? err.message : t("reports.wizard.previewError"),
      );
    } finally {
      setPreviewBusy(false);
    }
  };

  const generate = async () => {
    if (!type || busy) return;
    setBusy(true);
    setError("");
    try {
      const settings = buildSettings();
      const entry = await generateReport({
        report_type: type.key,
        settings,
        format,
      });
      setGenerated(entry);
      onGenerated(entry);
      try {
        const described = await describeReport(type.key, settings);
        setSaveName(described.name);
        setSaveDescription(described.description);
      } catch {
        setSaveName(entry.name);
        setSaveDescription("");
      }
      setSaveArea(type.home_area);
      setStep(3);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That report couldn't be generated.",
      );
    } finally {
      setBusy(false);
    }
  };

  const saveTemplate = async () => {
    if (!type || busy || saved) return;
    setBusy(true);
    setError("");
    try {
      await createTemplate({
        report_type: type.key,
        name: saveName,
        description: saveDescription,
        area: saveArea,
        settings: buildSettings(),
      });
      setSaved(true);
      toast(t("reports.wizard.saved"));
      onSavedTemplate();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That template couldn't be saved.",
      );
    } finally {
      setBusy(false);
    }
  };

  const footer = (
    <>
      {step > 0 && step < 3 && (
        <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={busy}>
          {t("reports.wizard.back")}
        </Button>
      )}
      {step === 3 && <span className="tv-reports-spacer" />}
      {step < 3 && (
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          {t("reports.wizard.cancel")}
        </Button>
      )}
      <span className="tv-reports-spacer" />
      {step === 0 && (
        <Button onClick={() => setStep(1)} disabled={type === null}>
          {t("reports.wizard.continue")}
        </Button>
      )}
      {step === 1 && (
        <Button
          onClick={() => {
            setStep(2);
            void loadPreview();
          }}
        >
          {t("reports.wizard.continue")}
        </Button>
      )}
      {step === 2 && (
        <Button onClick={() => void generate()} disabled={busy || previewBusy}>
          {t("reports.wizard.generate")}
        </Button>
      )}
      {step === 3 && (
        <Button onClick={onClose}>{t("reports.wizard.close")}</Button>
      )}
    </>
  );

  const renderTypeGroup = (area: ReportArea) => {
    const rows = catalog.filter((row) => row.home_area === area);
    if (rows.length === 0) return null;
    return (
      <div key={area}>
        <p className="tv-reports-group-label">
          {area === "quick"
            ? t("reports.wizard.quickKinds")
            : area === "admin"
              ? t("reports.wizard.adminKinds")
              : t("reports.wizard.accountingKinds")}
        </p>
        <div className="tv-reports-type-list">
          {rows.map((row) => (
            <button
              key={row.key}
              type="button"
              className={`tv-reports-type-row${row.key === typeKey ? " tv-reports-type-row--selected" : ""}`}
              disabled={!row.available}
              onClick={() => pickType(row)}
            >
              <span className="tv-reports-type-main">
                <span className="tv-reports-type-name">{row.name}</span>
                <span className="tv-reports-type-desc">{row.description}</span>
                {!row.available && (
                  <span className="tv-reports-type-off">
                    {t("reports.wizard.moduleOff")}
                  </span>
                )}
              </span>
              <span className="tv-reports-chip">
                {row.formats.map((f) => f.toUpperCase()).join(" · ")}
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("reports.wizard.title")}
      size="lg"
      footer={footer}
    >
      <div className="tv-wizard">
        <div className="tv-reports-wizard-body">
          <div>
            <div className="tv-reports-wizard-steps">
              {STEP_KEYS.map((key, i) => (
                <span
                  key={key}
                  className={`tv-reports-wizard-step${i === step ? " tv-reports-wizard-step--active" : ""}`}
                >
                  {i + 1}. {t(key)}
                </span>
              ))}
            </div>
            <ProgressBar
              value={((step + 1) / STEP_KEYS.length) * 100}
              label={`${t(STEP_KEYS[step])} (${step + 1}/${STEP_KEYS.length})`}
            />
          </div>

          {error && <Alert tone="danger">{error}</Alert>}

          {step === 0 && (
            <>
              {audience === "admin" ? (
                renderTypeGroup("admin")
              ) : (
                <>
                  {renderTypeGroup("quick")}
                  {renderTypeGroup("accounting")}
                </>
              )}
            </>
          )}

          {step === 1 && type && (
            <div className="tv-reports-form">
              <FormField label={t("reports.wizard.format")} htmlFor="wiz-format">
                <Select
                  id="wiz-format"
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                >
                  {type.formats.map((f) => (
                    <option key={f} value={f}>
                      {f.toUpperCase()}
                    </option>
                  ))}
                </Select>
              </FormField>

              {(type.settings === "year" || type.settings === "year_or_all") && (
                <FormField label={t("reports.wizard.year")} htmlFor="wiz-year">
                  <Select
                    id="wiz-year"
                    value={year}
                    onChange={(e) => setYear(e.target.value)}
                  >
                    {type.settings === "year_or_all" && (
                      <option value="">{t("reports.year.allTime")}</option>
                    )}
                    {yearOptions().map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </Select>
                </FormField>
              )}

              {type.settings === "period" && (
                <>
                  <div className="tv-reports-date-pair">
                    <FormField label={t("reports.wizard.startDate")} htmlFor="wiz-start">
                      <DatePicker
                        id="wiz-start"
                        value={startDate}
                        onChange={setStartDate}
                        clearable
                      />
                    </FormField>
                    <FormField label={t("reports.wizard.endDate")} htmlFor="wiz-end">
                      <DatePicker
                        id="wiz-end"
                        value={endDate}
                        onChange={setEndDate}
                        clearable
                      />
                    </FormField>
                  </div>
                  <p className="tv-reports-hint">{t("reports.wizard.dateHint")}</p>
                </>
              )}

              {type.settings === "inventory" && (
                <>
                  <FormField label={t("reports.wizard.grouping")} htmlFor="wiz-grouping">
                    <Select
                      id="wiz-grouping"
                      value={grouping}
                      onChange={(e) => setGrouping(e.target.value)}
                    >
                      {(meta?.groupings ?? []).map((g) => (
                        <option key={g.key} value={g.key}>
                          {g.label}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <FormField label={t("reports.sets.label")} htmlFor="wiz-sets">
                    <Select
                      id="wiz-sets"
                      value={setsMode}
                      onChange={(e) => setSetsMode(e.target.value)}
                    >
                      <option value="summary">{t("reports.sets.modeSummary")}</option>
                      <option value="with_core">{t("reports.sets.modeWithCore")}</option>
                      <option value="full">{t("reports.sets.modeFull")}</option>
                    </Select>
                  </FormField>
                </>
              )}
            </div>
          )}

          {step === 2 && (
            <>
              <p className="tv-reports-hint">{t("reports.wizard.previewIntro")}</p>
              {previewBusy && (
                <p className="tv-reports-hint">{t("reports.wizard.previewLoading")}</p>
              )}
              {previewError && <Alert tone="danger">{previewError}</Alert>}
              {preview?.kind === "pdf" && preview.url && (
                <iframe
                  className="tv-reports-preview-frame"
                  src={preview.url}
                  title={type?.name ?? "Report preview"}
                />
              )}
              {preview?.kind === "csv" && (
                <pre className="tv-reports-preview-text">{preview.text}</pre>
              )}
              {preview?.kind === "sheet" && (
                <div className="tv-reports-preview-card">
                  <FileTypeArt kind="sheet" />
                  <p>{t("reports.wizard.sheetNote")}</p>
                </div>
              )}
            </>
          )}

          {step === 3 && generated && (
            <>
              <div>
                <h3>{t("reports.wizard.doneTitle")}</h3>
                <p className="tv-reports-hint">{t("reports.wizard.doneBody")}</p>
              </div>
              {!saved ? (
                <div className="tv-reports-form">
                  <p className="tv-reports-hint">{t("reports.wizard.savePrompt")}</p>
                  <FormField label={t("reports.wizard.saveName")} htmlFor="wiz-save-name">
                    <TextInput
                      id="wiz-save-name"
                      value={saveName}
                      onChange={(e) => setSaveName(e.target.value)}
                    />
                  </FormField>
                  <FormField
                    label={t("reports.wizard.saveDescription")}
                    htmlFor="wiz-save-desc"
                  >
                    <TextArea
                      id="wiz-save-desc"
                      rows={3}
                      value={saveDescription}
                      onChange={(e) => setSaveDescription(e.target.value)}
                    />
                  </FormField>
                  {audience !== "admin" && (
                  <FormField label={t("reports.wizard.saveArea")}>
                    <div className="tv-reports-radio-row">
                      <Radio
                        name="wiz-save-area"
                        value="quick"
                        checked={saveArea === "quick"}
                        onChange={() => setSaveArea("quick")}
                        label={t("reports.wizard.areaQuick")}
                      />
                      <Radio
                        name="wiz-save-area"
                        value="accounting"
                        checked={saveArea === "accounting"}
                        onChange={() => setSaveArea("accounting")}
                        label={t("reports.wizard.areaAccounting")}
                      />
                    </div>
                  </FormField>
                  )}
                  <div>
                    <Button onClick={() => void saveTemplate()} disabled={busy}>
                      {t("reports.wizard.saveButton")}
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="tv-reports-hint">{t("reports.wizard.saved")}</p>
              )}
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
