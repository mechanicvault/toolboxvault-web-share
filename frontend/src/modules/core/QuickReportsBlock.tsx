import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import {
  Alert,
  AttachmentViewer,
  Panel,
  QuietSkeleton,
  buttonClasses,
  type ViewableAttachment,
} from "../../components";
import { FileTypeArt } from "../../components/FileTypeArt";
import { ArtIcon } from "../../components/ArtIcon";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { formatDate } from "../../lib/format";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import {
  downloadHistory,
  getCatalog,
  historyView,
  listHistory,
  listTemplates,
  runTemplate,
} from "../reports/api";
import type {
  CatalogType,
  HistoryEntry,
  ReportTemplateView,
} from "../reports/types";
import { YearPrompt } from "../reports/YearPrompt";
import { optBool, optNum } from "./widgetOptions";

/**
 * QUICK REPORTS ON HOME (dashboard-flare lane, owner order
 * 2026-11-09): the Reports page's QUICK REPORTS set as a
 * dashboard widget that DOES the thing — every quick report
 * carries a Run button that generates it right here, with the
 * exact flow the Reports page runs (the shared runTemplate
 * call, the shared YearPrompt for year-set reports, and the
 * finished file landing in the same preview popup —
 * AttachmentViewer with Full screen / Print / Download /
 * Email — falling back to a plain download when the view
 * can't be fetched, byte-for-byte the Reports page's own
 * behavior). The user never leaves the dashboard.
 *
 * One Run button per report (Ryan's shape, not the page's
 * per-format chips): it produces the report in the format the
 * template itself saved; a template with no saved format runs
 * as PDF when the type offers it, else the type's first
 * format. Seated as its own block in CorePage (the
 * howto_videos pattern — a stateful component, not a load()
 * def, because the viewer lives here), gated on the reports
 * module exactly like the data behind it. In Edit view the
 * rows stand inert — a box never acts while customizing.
 */
export function QuickReportsBlock({
  editing = false,
  settings,
  bare = false,
}: {
  editing?: boolean;
  settings: Record<string, BlockSettingValue>;
  /** Custom-widget composition (Lane 2): sections only —
   *  no Panel, no head; the composite box carries its own.
   *  The run dialogs still render — they are portals of the
   *  body, not of the frame. */
  bare?: boolean;
}) {
  const t = useT();
  const { toast } = useToast();
  const [templates, setTemplates] = useState<ReportTemplateView[] | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [catalogByKey, setCatalogByKey] = useState<Map<string, CatalogType>>(
    new Map(),
  );
  const [failed, setFailed] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [yearFor, setYearFor] = useState<ReportTemplateView | null>(null);
  const [yearFormat, setYearFormat] = useState("pdf");
  const [viewerFile, setViewerFile] = useState<ViewableAttachment | null>(null);
  const [viewerEntryId, setViewerEntryId] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    listHistory({})
      .then((h) => {
        if (live) setHistory(h.entries);
      })
      .catch(() => undefined);
    Promise.all([listTemplates(), getCatalog()])
      .then(([tpl, catalog]) => {
        if (!live) return;
        setTemplates(tpl.templates);
        setCatalogByKey(
          new Map(
            [...catalog.types, ...(catalog.admin_types ?? [])].map((row) => [
              row.key,
              row,
            ]),
          ),
        );
      })
      .catch(() => {
        if (live) {
          setTemplates([]);
          setFailed(true);
        }
      });
    return () => {
      live = false;
    };
  }, []);

  const rowsToShow = optNum(settings, "rowsToShow", 5, 1, 10);
  const showGenerate = optBool(settings, "showGenerate", false);
  // The pick list (owner order 2026-11-14): the widget's
  // options carry one checkbox per quick report; unchecking
  // stores the id in hiddenReports (the Flyers options'
  // pattern — absence of the key = everything shows).
  // Unchecking is how a report leaves the widget, checking
  // it again is how it comes back.
  const hiddenReports = new Set(
    Array.isArray(settings.hiddenReports) ? settings.hiddenReports : [],
  );
  const quickAll = (templates ?? []).filter((row) => row.area === "quick");
  const quick = quickAll.filter((row) => !hiddenReports.has(row.id));
  // Sheet row 110: the "saved reports" line counts only the
  // member's own templates — the seeded defaults (is_default)
  // ride the rows below as starter quick reports, but they are
  // not reports the user saved.
  const ownQuickCount = quickAll.filter((row) => !row.is_default).length;
  const shown = quick.slice(0, rowsToShow);

  const onGenerated = (entry: HistoryEntry) => {
    // The Reports page's own landing: the viewer popup, or a
    // plain download when the view can't be fetched.
    historyView(entry.id)
      .then(({ attachment }) => {
        setViewerEntryId(entry.id);
        setViewerFile(attachment);
      })
      .catch(() => {
        downloadHistory(entry).catch(() => undefined);
      });
  };

  const runNow = async (
    template: ReportTemplateView,
    format: string,
    year?: number | null,
  ) => {
    setBusyId(template.id);
    setError("");
    try {
      const entry = await runTemplate(template.id, {
        format,
        year: year === undefined ? undefined : year,
      });
      onGenerated(entry);
      toast(t("reports.template.generated"));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "That report couldn't be generated.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const runFormat = (template: ReportTemplateView): string => {
    const type = catalogByKey.get(template.report_type);
    const saved = template.settings?.format;
    const formats =
      type?.formats ?? (typeof saved === "string" ? [saved] : ["pdf"]);
    if (typeof saved === "string" && formats.includes(saved)) return saved;
    return formats.includes("pdf") ? "pdf" : formats[0];
  };

  // Open right here on Home (owner, 2026-11-15): a report
  // row's main face OPENS the report in the viewer on this
  // page — the latest run's file when one exists, a fresh
  // run (which lands in the same viewer) when none does.
  // The Run button stays the explicit regenerate.
  const openReport = (template: ReportTemplateView) => {
    if (editing || busyId !== null) return;
    const latest = history
      .filter((h) => h.template_id === template.id)
      .sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""))
      .slice(-1)[0];
    if (!latest) {
      startRun(template);
      return;
    }
    historyView(latest.id)
      .then(({ attachment }) => {
        setViewerEntryId(latest.id);
        setViewerFile(attachment);
      })
      .catch(() => startRun(template));
  };

  const startRun = (template: ReportTemplateView) => {
    if (editing || busyId !== null) return;
    const type = catalogByKey.get(template.report_type);
    if (type && !type.available) {
      toast(t("reports.template.moduleOff"));
      return;
    }
    const format = runFormat(template);
    if (type && (type.settings === "year" || type.settings === "year_or_all")) {
      setYearFormat(format);
      setYearFor(template);
      return;
    }
    void runNow(template, format);
  };

  const inner = (
    <>
      {failed ? (
        <p className="tv-muted">{t("home.widgetLoadFailed")}</p>
      ) : templates === null ? (
        <QuietSkeleton lines={3} />
      ) : (
        <>
          {error && <Alert tone="danger">{error}</Alert>}
          {quickAll.length > 0 && (
            <>
              <p className="tv-widget-line">
                {t("home.widget.qrSavedLine")
                  .replace("{count}", String(ownQuickCount))
                  .replace(
                    "{last}",
                    history.length > 0
                      ? formatDate(
                          history
                            .map((h) => h.created_at)
                            .filter((d): d is string => typeof d === "string")
                            .sort()
                            .slice(-1)[0]
                            ?.slice(0, 10) ?? null,
                        )
                      : t("home.widget.qrNever"),
                  )}
              </p>
              <p className="tv-widget-counts">
                <span className="tv-widget-count">
                  <strong>{quick.length}</strong>{" "}
                  {t("home.widget.qrQuickWord")}
                </span>
                <span className="tv-widget-count">
                  <span className="tv-widget-count-sep">·</span>
                  <strong>
                    {
                      history.filter((h) =>
                        (h.created_at ?? "").startsWith(
                          new Date().toISOString().slice(0, 7),
                        ),
                      ).length
                    }
                  </strong>{" "}
                  {t("home.widget.qrRunMonthWord")}
                </span>
              </p>
              <div className="tv-widget-group-label">
                {t("home.widget.qrGroupLabel")}
              </div>
            </>
          )}
          {quick.length === 0 ? (
            <p className="tv-muted">
              {quickAll.length > 0
                ? t("home.widget.qrPickedNone")
                : t("home.widget.qrEmpty")}
            </p>
          ) : (
            <div className="tv-qr-rows">
              {shown.map((template) => (
                <div key={template.id} className="tv-qr-row">
                  {editing ? (
                    <span className="tv-qr-main">
                      <span className="tv-qr-stack">
                        <span className="tv-qr-name">{template.name}</span>
                        {template.description && (
                          <span className="tv-qr-sub">{template.description}</span>
                        )}
                      </span>
                      <FileTypeArt
                        kind={runFormat(template) === "xlsx" ? "sheet" : "pdf"}
                        height={42}
                      />
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="tv-qr-main tv-qr-open"
                      title={t("home.widget.qrOpenReport")}
                      onClick={() => openReport(template)}
                    >
                      <span className="tv-qr-stack">
                        <span className="tv-qr-name">{template.name}</span>
                        {template.description && (
                          <span className="tv-qr-sub">{template.description}</span>
                        )}
                      </span>
                      <FileTypeArt
                        kind={runFormat(template) === "xlsx" ? "sheet" : "pdf"}
                        height={42}
                      />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {quick.length > shown.length && (
            <p className="tv-muted">
              {t("home.widget.qrMore").replace(
                "{count}",
                String(quick.length - shown.length),
              )}
            </p>
          )}
          {!editing && (
            <div className="tv-widget-actions tv-widget-actions--end">
              {showGenerate && (
                <Link
                  to="/reports#new"
                  className={buttonClasses("ghost", "sm")}
                >
                  {t("home.widget.qrGenerate")}
                </Link>
              )}
              <Link to="/reports" className={buttonClasses("primary", "sm")}>
                {t("home.widget.qrOpen")}
              </Link>
            </div>
          )}
        </>
      )}
      <YearPrompt
        template={yearFor}
        allowAllTime={
          yearFor
            ? catalogByKey.get(yearFor.report_type)?.settings === "year_or_all"
            : false
        }
        onCancel={() => setYearFor(null)}
        onRun={(year) => {
          const template = yearFor;
          const format = yearFormat;
          setYearFor(null);
          if (template) void runNow(template, format, year);
        }}
      />
      <AttachmentViewer
        attachment={viewerFile}
        onClose={() => {
          setViewerFile(null);
          setViewerEntryId(null);
        }}
        emailPath={
          viewerEntryId ? `/reports/history/${viewerEntryId}/email` : undefined
        }
      />
    </>
  );
  if (bare) return inner;
  return (
    <Panel className="tv-home-widget">
      <div className="tv-widget-head">
        <span className="tv-stat-icon" data-tone="info" aria-hidden="true">
          <ArtIcon name="reports" size={24} />
        </span>
        <h3 className="tv-widget-title">{t("home.widget.reportsTitle")}</h3>
      </div>
      {inner}
    </Panel>
  );
}
