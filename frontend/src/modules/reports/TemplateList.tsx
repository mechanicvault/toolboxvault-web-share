import { useState } from "react";

import {
  Alert,
  Button,
  EmptyState,
  FileTypeArt,
  Modal,
  type FileArtKind,
} from "../../components";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { deleteTemplate, runTemplate } from "./api";
import type {
  CatalogType,
  HistoryEntry,
  ReportArea,
  ReportTemplateView,
} from "./types";
import { YearPrompt } from "./YearPrompt";

/**
 * One saved-templates box (Quick Reports on the New tab, the
 * Accounting list on its tab — the same component, Ryan's spec).
 * One report per row: name BOLD, description smaller beneath.
 * The row itself is INERT (Ryan, 2026-11-07): the right side
 * carries one format icon per format the report's type can
 * honestly make (the FileTypeArt artwork), and clicking an
 * icon runs the report in THAT format — year types ask their
 * year first — after which the page opens the generated file
 * in the viewer popup and History keeps its copy. The box's
 * Edit button arms in-place removal on the very rows on
 * screen — the site list standard.
 */

const FORMAT_ART: Record<string, FileArtKind> = {
  pdf: "pdf",
  csv: "sheet",
  xlsx: "sheet",
};

export function TemplateList({
  area,
  title,
  body,
  templates,
  catalogByKey,
  onChanged,
  onGenerated,
}: {
  area: ReportArea;
  title: string;
  body?: string;
  templates: ReportTemplateView[] | null;
  catalogByKey: Map<string, CatalogType>;
  onChanged: () => void;
  onGenerated: (entry: HistoryEntry) => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<ReportTemplateView | null>(null);
  const [yearFor, setYearFor] = useState<ReportTemplateView | null>(null);
  const [yearFormat, setYearFormat] = useState<string>("pdf");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const rows = (templates ?? []).filter((row) => row.area === area);

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
        err instanceof ApiError ? err.message : "That report couldn't be generated.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const startRun = (template: ReportTemplateView, format: string) => {
    if (editing || busyId !== null) return;
    const type = catalogByKey.get(template.report_type);
    if (type && !type.available) {
      toast(t("reports.template.moduleOff"));
      return;
    }
    if (type && (type.settings === "year" || type.settings === "year_or_all")) {
      setYearFormat(format);
      setYearFor(template);
      return;
    }
    void runNow(template, format);
  };

  const remove = async () => {
    if (!confirm) return;
    const victim = confirm;
    setConfirm(null);
    try {
      await deleteTemplate(victim.id);
      toast(t("reports.template.removed"));
      onChanged();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That saved report couldn't be removed.",
      );
    }
  };

  return (
    <div>
      <div className="tv-reports-box-head">
        <h2 className="tv-reports-box-title">{title}</h2>
        {rows.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? t("reports.template.done") : t("reports.template.edit")}
          </Button>
        )}
      </div>
      {body && <p className="tv-reports-box-body">{body}</p>}
      {error && <Alert tone="danger">{error}</Alert>}
      {templates === null ? null : rows.length === 0 ? (
        <EmptyState
          title={
            area === "quick"
              ? t("reports.template.emptyQuickTitle")
              : area === "admin"
                ? t("reports.template.emptyAdminTitle")
                : t("reports.template.emptyAccountingTitle")
          }
          description={t("reports.template.emptyBody")}
        />
      ) : (
        <div className="tv-reports-tpl-list">
          {rows.map((template) => {
            const type = catalogByKey.get(template.report_type);
            const savedFormat = template.settings?.format;
            const formats =
              type?.formats ??
              (typeof savedFormat === "string" ? [savedFormat] : ["pdf"]);
            return (
              <div
                key={template.id}
                className={`tv-reports-tpl-row${editing ? " tv-reports-tpl-row--static" : ""}`}
              >
                <div className="tv-reports-tpl-main">
                  <span className="tv-reports-tpl-name">{template.name}</span>
                  {template.description && (
                    <span className="tv-reports-tpl-desc">
                      {template.description}
                    </span>
                  )}
                </div>
                <span className="tv-reports-tpl-side">
                  {formats.map((format) => {
                    const label = t("reports.template.runAs")
                      .replace("{name}", template.name)
                      .replace("{format}", format.toUpperCase());
                    return (
                      <button
                        key={format}
                        type="button"
                        className="tv-reports-fmt-btn"
                        aria-label={label}
                        title={label}
                        disabled={editing || busyId === template.id}
                        onClick={() => startRun(template, format)}
                      >
                        <FileTypeArt
                          kind={FORMAT_ART[format] ?? "doc"}
                          height={30}
                        />
                        <span className="tv-reports-fmt-label">
                          {format.toUpperCase()}
                        </span>
                      </button>
                    );
                  })}
                  {editing && (
                    <button
                      type="button"
                      aria-label={t("reports.template.remove").replace(
                        "{name}",
                        template.name,
                      )}
                      className="tv-reports-tpl-remove"
                      onClick={() => setConfirm(template)}
                    >
                      −
                    </button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
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

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={t("reports.template.deleteTitle")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              {t("reports.wizard.cancel")}
            </Button>
            <span className="tv-reports-spacer" />
            <Button variant="danger" onClick={() => void remove()}>
              {t("reports.template.deleteConfirm")}
            </Button>
          </>
        }
      >
        <p>
          {confirm
            ? t("reports.template.deleteBody").replace("{name}", confirm.name)
            : ""}
        </p>
      </Modal>
    </div>
  );
}
