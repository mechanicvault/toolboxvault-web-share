import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import {
  Alert,
  AttachmentViewer,
  Button,
  Panel,
  QuietSkeleton,
  buttonClasses,
  type ViewableAttachment,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import type { BlockSettingValue } from "../../lib/usePageLayout";
import {
  downloadHistory,
  getCatalog,
  historyView,
  listTemplates,
  runTemplate,
} from "../reports/api";
import type {
  CatalogType,
  HistoryEntry,
  ReportTemplateView,
} from "../reports/types";
import { YearPrompt } from "../reports/YearPrompt";
import { optNum } from "./widgetOptions";

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
  const quick = (templates ?? []).filter((row) => row.area === "quick");
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
          {quick.length === 0 ? (
            <p className="tv-muted">{t("home.widget.qrEmpty")}</p>
          ) : (
            <div className="tv-qr-rows">
              {shown.map((template) => (
                <div key={template.id} className="tv-qr-row">
                  <span className="tv-qr-main">
                    <span className="tv-qr-name">{template.name}</span>
                    <span className="tv-qr-format">
                      {runFormat(template).toUpperCase()}
                    </span>
                  </span>
                  {!editing && (
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={busyId !== null}
                      onClick={() => startRun(template)}
                    >
                      {t("home.widget.qrRun")}
                    </Button>
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
            <div className="tv-widget-actions">
              <Link to="/reports" className={buttonClasses("ghost", "sm")}>
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
        <h3 className="tv-widget-title">{t("reports.page.quickTitle")}</h3>
      </div>
      {inner}
    </Panel>
  );
}
