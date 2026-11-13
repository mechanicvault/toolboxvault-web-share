import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./reports.css";
import {
  Alert,
  AttachmentViewer,
  Button,
  FileTypeArt,
  FormField,
  Modal,
  Panel,
  Select,
  Spinner,
  Tabs,
  type FileArtKind,
  type TabItem,
  type ViewableAttachment,
} from "../../components";
import { ArtIcon } from "../../components/ArtIcon";
import { ApiError } from "../../lib/api";
import { useT } from "../../i18n/LocaleContext";
import { RequireAuth } from "../core";
import { SettingsActionsMenu } from "../core/SettingsActionsMenu";
import { downloadHistory, generateReport, getCatalog, historyView, listHistory, listTemplates } from "./api";
import { HistoryList } from "./HistoryList";
import { ReportWizard } from "./ReportWizard";
import { yearOptions } from "./YearPrompt";
import { TemplateList } from "./TemplateList";
import type {
  CatalogType,
  HistoryEntry,
  ReportTemplateView,
} from "./types";

/**
 * Reports (redesign, Ryan 2026-11-06): a main tab layout page
 * whose whole job is "needlessly simple to find, create, and
 * export any report you want."
 *
 *   New report — the Generate button opens the wizard (type →
 *     options → preview of the actual document → generate);
 *     below it, the QUICK REPORTS box: saved templates whose
 *     format icons run them fresh from today's data. Every
 *     finished generation — wizard or saved row — opens in the
 *     documents viewer popup (Ryan, 2026-11-07).
 *   Accounting — the same list for the accounting-area
 *     templates (taxes, the accountant, the business books).
 *   History — every generated file, kept: open it in the
 *     viewer, download it again, or delete it.
 *   Request a report type — a short explainer and a button
 *     that opens the Help & Support ticket form halfway filled
 *     out.
 *
 * The old builder UI retired with this redesign; the saved
 * report CONFIGS it used still exist server-side (the downloads
 * page and other direct routes keep their own behavior), they
 * simply have no surface here anymore. Deep links: #new ·
 * #accounting · #history · #request.
 */

type TabId = "new" | "accounting" | "history" | "request" | "admin";

const HASH_TO_TAB: Record<string, TabId> = {
  "#new": "new",
  "#accounting": "accounting",
  "#history": "history",
  "#request": "request",
  "#admin": "admin",
};

const FORMAT_ART: Record<string, FileArtKind> = {
  pdf: "pdf",
  csv: "sheet",
  xlsx: "sheet",
};

/**
 * The Admin tab's predefined rows (admin lane, 2026-11-07):
 * the admin catalog types themselves, run fresh in any format
 * — the same inert-row + format-chip shape as the saved lists.
 * Year types ask their year first (the fiscal rule: the year
 * is picked when a report runs). Generation rides the shared
 * generate route, so the file lands in the viewer + History
 * like every other report.
 */
function AdminPredefined({
  types,
  onGenerated,
}: {
  types: CatalogType[];
  onGenerated: (entry: HistoryEntry) => void;
}) {
  const t = useT();
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [yearFor, setYearFor] = useState<CatalogType | null>(null);
  const [yearFormat, setYearFormat] = useState("pdf");
  const [year, setYear] = useState<string>(String(new Date().getFullYear()));

  const run = async (type: CatalogType, format: string, yr?: number) => {
    setBusyKey(type.key);
    setError("");
    try {
      const entry = await generateReport({
        report_type: type.key,
        settings: yr ? { year: yr } : {},
        format,
      });
      onGenerated(entry);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That report couldn't be generated.",
      );
    } finally {
      setBusyKey(null);
    }
  };

  const startRun = (type: CatalogType, format: string) => {
    if (busyKey !== null) return;
    if (type.settings === "year" || type.settings === "year_or_all") {
      setYearFormat(format);
      setYear(String(new Date().getFullYear()));
      setYearFor(type);
      return;
    }
    void run(type, format);
  };

  return (
    <div>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="tv-reports-tpl-list">
        {types.map((type) => (
          <div key={type.key} className="tv-reports-tpl-row">
            <div className="tv-reports-tpl-main">
              <span className="tv-reports-tpl-name">{type.name}</span>
              {type.description && (
                <span className="tv-reports-tpl-desc">{type.description}</span>
              )}
            </div>
            <span className="tv-reports-tpl-side">
              {type.formats.map((format) => {
                const label = t("reports.template.runAs")
                  .replace("{name}", type.name)
                  .replace("{format}", format.toUpperCase());
                return (
                  <button
                    key={format}
                    type="button"
                    className="tv-reports-fmt-btn"
                    aria-label={label}
                    title={label}
                    disabled={busyKey === type.key}
                    onClick={() => startRun(type, format)}
                  >
                    <FileTypeArt kind={FORMAT_ART[format] ?? "doc"} height={30} />
                    <span className="tv-reports-fmt-label">
                      {format.toUpperCase()}
                    </span>
                  </button>
                );
              })}
            </span>
          </div>
        ))}
      </div>
      <Modal
        open={yearFor !== null}
        onClose={() => setYearFor(null)}
        title={t("reports.year.title")}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setYearFor(null)}>
              {t("reports.wizard.cancel")}
            </Button>
            <span className="tv-reports-spacer" />
            <Button
              onClick={() => {
                const type = yearFor;
                const format = yearFormat;
                setYearFor(null);
                if (type) void run(type, format, Number(year));
              }}
            >
              {t("reports.year.run")}
            </Button>
          </>
        }
      >
        <div className="tv-wizard">
          <p className="tv-reports-hint">{t("reports.year.body")}</p>
          <FormField label={t("reports.year.label")} htmlFor="admin-year">
            <Select
              id="admin-year"
              value={year}
              onChange={(e) => setYear(e.target.value)}
            >
              {yearOptions().map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </Select>
          </FormField>
        </div>
      </Modal>
    </div>
  );
}

const TICKET_PREFILL_KEY = "tv.ticketPrefill";

function ReportsHome() {
  const t = useT();
  const navigate = useNavigate();
  const [picked, setPicked] = useState<TabId | null>(null);
  const [hashTab] = useState<TabId | null>(
    () => HASH_TO_TAB[window.location.hash] ?? null,
  );
  const [catalog, setCatalog] = useState<CatalogType[] | null>(null);
  const [adminCatalog, setAdminCatalog] = useState<CatalogType[]>([]);
  const [adminWizardOpen, setAdminWizardOpen] = useState(false);
  const [templates, setTemplates] = useState<ReportTemplateView[] | null>(null);
  const [historyCount, setHistoryCount] = useState<number | null>(null);
  const [historyReload, setHistoryReload] = useState(0);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [viewerFile, setViewerFile] = useState<ViewableAttachment | null>(null);
  const [viewerEntryId, setViewerEntryId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const active: TabId = picked ?? hashTab ?? "new";

  const loadTemplates = useCallback(() => {
    listTemplates()
      .then((data) => setTemplates(data.templates))
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError ? err.message : "Saved reports couldn't be loaded.",
        );
      });
  }, []);

  useEffect(() => {
    let live = true;
    getCatalog()
      .then((data) => {
        if (live) {
          setCatalog(data.types);
          setAdminCatalog(data.admin_types ?? []);
        }
      })
      .catch((err: unknown) => {
        if (live) {
          setError(
            err instanceof ApiError ? err.message : "The report list couldn't be loaded.",
          );
        }
      });
    loadTemplates();
    listHistory({})
      .then((data) => {
        if (live) setHistoryCount(data.entries.length);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [loadTemplates]);

  const catalogByKey = useMemo(
    () =>
      new Map(
        [...(catalog ?? []), ...adminCatalog].map((row) => [row.key, row]),
      ),
    [catalog, adminCatalog],
  );

  const onGenerated = useCallback((entry: HistoryEntry) => {
    setHistoryCount((count) => (count === null ? count : count + 1));
    setHistoryReload((token) => token + 1);
    // A finished generation lands in the viewer popup — the
    // same documents viewer a History row opens (Ryan,
    // 2026-11-07). If the view can't be fetched, the file
    // still reaches the user the old way: a plain download,
    // with its History copy untouched either way.
    historyView(entry.id)
      .then(({ attachment }) => {
        setViewerEntryId(entry.id);
        setViewerFile(attachment);
      })
      .catch(() => {
        downloadHistory(entry).catch(() => undefined);
      });
  }, []);

  const requestReportType = () => {
    // The smallest prefill seam: the ticket desk reads this
    // once on mount and seeds its (otherwise untouched) form.
    sessionStorage.setItem(
      TICKET_PREFILL_KEY,
      JSON.stringify({
        subject: t("reports.request.subject"),
        message: t("reports.request.message"),
      }),
    );
    navigate("/help#tickets");
  };

  const tabs: TabItem[] = [
    {
      id: "new",
      label: t("reports.page.tabNew"),
      content: (
        <div className="tv-reports-tab">
          <div className="tv-reports-generate-row">
            <Button onClick={() => setWizardOpen(true)}>
              {t("reports.page.generate")}
            </Button>
          </div>
          <Panel>
            <TemplateList
              area="quick"
              title={t("reports.page.quickTitle")}
              templates={templates}
              catalogByKey={catalogByKey}
              onChanged={loadTemplates}
              onGenerated={onGenerated}
            />
          </Panel>
        </div>
      ),
    },
    {
      id: "accounting",
      label: t("reports.page.tabAccounting"),
      content: (
        <Panel>
          <TemplateList
            area="accounting"
            title={t("reports.page.accountingTitle")}
            body={t("reports.page.accountingBody")}
            templates={templates}
            catalogByKey={catalogByKey}
            onChanged={loadTemplates}
            onGenerated={onGenerated}
          />
        </Panel>
      ),
    },
    {
      id: "history",
      label: t("reports.page.tabHistory"),
      content: (
        <Panel>
          <HistoryList
            reloadToken={historyReload}
            onCountChange={setHistoryCount}
          />
        </Panel>
      ),
    },
    {
      id: "request",
      label: t("reports.page.tabRequest"),
      content: (
        <Panel>
          <div className="tv-reports-request">
            <h2 className="tv-reports-box-title">{t("reports.request.title")}</h2>
            <p>{t("reports.request.body")}</p>
            <Button onClick={requestReportType}>
              {t("reports.request.button")}
            </Button>
          </div>
        </Panel>
      ),
    },
    // Admin Reports (admin lane, 2026-11-07): the tab exists
    // ONLY when the catalog answered with admin types — which
    // the server sends solely to god + moderator_admin seats.
    // For everyone else this array never grows the tab.
    ...(adminCatalog.length > 0
      ? [
          {
            id: "admin",
            label: t("reports.page.tabAdmin"),
            content: (
              <div className="tv-reports-tab">
                <div className="tv-reports-generate-row">
                  <Button onClick={() => setAdminWizardOpen(true)}>
                    {t("reports.page.generate")}
                  </Button>
                </div>
                <Panel>
                  <div className="tv-reports-box-head">
                    <h2 className="tv-reports-box-title">
                      {t("reports.admin.predefinedTitle")}
                    </h2>
                  </div>
                  <p className="tv-reports-box-body">
                    {t("reports.admin.predefinedBody")}
                  </p>
                  <AdminPredefined
                    types={adminCatalog}
                    onGenerated={onGenerated}
                  />
                </Panel>
                <Panel>
                  <TemplateList
                    area="admin"
                    title={t("reports.admin.savedTitle")}
                    templates={templates}
                    catalogByKey={catalogByKey}
                    onChanged={loadTemplates}
                    onGenerated={onGenerated}
                  />
                </Panel>
              </div>
            ),
          } as TabItem,
        ]
      : []),
  ];

  const title = t("reports.page.title");
  const facts: { label: string; value: number }[] = [];
  if (templates !== null)
    facts.push({ label: t("reports.page.factSaved"), value: templates.length });
  if (historyCount !== null)
    facts.push({ label: t("reports.page.factGenerated"), value: historyCount });

  return (
    <div>
      <Panel>
        <div className="tv-reports-head">
          <div className="tv-reports-thumb" aria-hidden="true">
            <ArtIcon name="reports" size={96} />
          </div>
          <div className="tv-reports-head-main">
            <h1 className="tv-reports-title">{title}</h1>
            {facts.length > 0 && (
              <dl className="tv-reports-facts">
                {facts.map((fact) => (
                  <div key={fact.label} className="tv-reports-fact">
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <div className="tv-reports-head-actions">
            <SettingsActionsMenu
              ariaLabel={title}
              buttonLabel={t("inventory.actions")}
              entries={tabs.map((tab) => ({
                key: tab.id,
                label: tab.label,
                run: () => setPicked(tab.id as TabId),
              }))}
            />
          </div>
        </div>
      </Panel>
      {error && <Alert tone="danger">{error}</Alert>}
      {catalog === null && templates === null ? (
        <Spinner label="Loading…" />
      ) : (
        <Tabs tabs={tabs} activeId={active} onChange={(id) => setPicked(id as TabId)} />
      )}
      <ReportWizard
        open={wizardOpen}
        catalog={catalog ?? []}
        onClose={() => setWizardOpen(false)}
        onGenerated={onGenerated}
        onSavedTemplate={loadTemplates}
      />
      <ReportWizard
        open={adminWizardOpen}
        catalog={adminCatalog}
        audience="admin"
        onClose={() => setAdminWizardOpen(false)}
        onGenerated={onGenerated}
        onSavedTemplate={loadTemplates}
      />
      {/* Rendered after the wizard so a generation that
          finishes while the wizard is still open lands its
          viewer on top of it (same overlay tier; DOM order
          decides). */}
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
    </div>
  );
}

export default function ReportsPage() {
  return (
    <RequireAuth>
      <ReportsHome />
    </RequireAuth>
  );
}
