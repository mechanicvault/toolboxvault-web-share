import { useEffect, useState } from "react";

import {
  AttachmentViewer,
  Button,
  DataTable,
  DatePicker,
  EmptyState,
  FileTypeArt,
  FormField,
  Select,
  TextInput,
  formatBytes,
  type Column,
  type FileArtKind,
  type ViewableAttachment,
} from "../../components";
import { useToast } from "../../components/Toast";
import { useT } from "../../i18n/LocaleContext";
import { ApiError } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { deleteHistory, historyView, listHistory } from "./api";
import type { HistoryEntry } from "./types";

/**
 * History (Ryan's spec): every report this page generated is
 * KEPT — a true list (file-type artwork · generated date ·
 * report name · file size) whose rows open the documents-style
 * viewer popup (preview / download / delete). Filters: a date
 * range, the file type, and a name/type search.
 */

const FORMAT_ART: Record<string, FileArtKind> = {
  pdf: "pdf",
  csv: "sheet",
  xlsx: "sheet",
};

function DeleteReportButton({
  entry,
  onDeleted,
}: {
  entry: HistoryEntry;
  onDeleted: (entry: HistoryEntry) => void;
}) {
  const t = useT();
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(timer);
  }, [armed]);

  const click = async () => {
    if (!armed) {
      setArmed(true);
      return;
    }
    setBusy(true);
    try {
      await deleteHistory(entry.id);
      onDeleted(entry);
    } catch {
      setBusy(false);
      setArmed(false);
    }
  };

  return (
    <Button variant="danger" onClick={() => void click()} disabled={busy}>
      {armed ? t("reports.history.deleteArm") : t("reports.history.delete")}
    </Button>
  );
}

export function HistoryList({
  reloadToken,
  onCountChange,
}: {
  /** Bumped by the page whenever a report is generated. */
  reloadToken: number;
  onCountChange?: (count: number) => void;
}) {
  const t = useT();
  const { toast } = useToast();
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [format, setFormat] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [viewerEntry, setViewerEntry] = useState<HistoryEntry | null>(null);
  const [viewerFile, setViewerFile] = useState<ViewableAttachment | null>(null);

  const filtered = from !== "" || to !== "" || format !== "" || q.trim() !== "";

  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      listHistory({
        from: from || undefined,
        to: to || undefined,
        format: format || undefined,
        q: q.trim() || undefined,
      })
        .then((data) => {
          if (!live) return;
          setEntries(data.entries);
          setError("");
          if (!filtered) onCountChange?.(data.entries.length);
        })
        .catch((err: unknown) => {
          if (!live) return;
          setError(
            err instanceof ApiError ? err.message : "History couldn't be loaded.",
          );
        });
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // onCountChange is a stable page callback; filters + the
    // reload token are the real triggers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to, format, q, reloadToken]);

  const openEntry = async (entry: HistoryEntry) => {
    try {
      const { attachment } = await historyView(entry.id);
      setViewerEntry(entry);
      setViewerFile(attachment);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That report couldn't be opened.",
      );
    }
  };

  const columns: Column<HistoryEntry>[] = [
    {
      key: "file",
      header: t("reports.history.colFile"),
      render: (entry) => (
        <span className="tv-reports-history-file">
          <FileTypeArt kind={FORMAT_ART[entry.format] ?? "doc"} height={34} />
          {entry.format.toUpperCase()}
        </span>
      ),
    },
    {
      key: "date",
      header: t("reports.history.colDate"),
      render: (entry) => formatDateTime(entry.created_at),
      sortValue: (entry) => entry.created_at ?? "",
      sortable: true,
    },
    {
      key: "name",
      header: t("reports.history.colName"),
      render: (entry) => (
        <span className="tv-reports-history-name">{entry.name}</span>
      ),
      sortValue: (entry) => entry.name,
      sortable: true,
    },
    {
      key: "size",
      header: t("reports.history.colSize"),
      align: "right",
      render: (entry) => formatBytes(entry.size_bytes),
      sortValue: (entry) => entry.size_bytes,
      sortable: true,
    },
  ];

  return (
    <div>
      <div className="tv-reports-filters">
        <div className="tv-reports-filter">
          <FormField label={t("reports.history.filterFrom")} htmlFor="hist-from">
            <DatePicker id="hist-from" value={from} onChange={setFrom} clearable />
          </FormField>
        </div>
        <div className="tv-reports-filter">
          <FormField label={t("reports.history.filterTo")} htmlFor="hist-to">
            <DatePicker id="hist-to" value={to} onChange={setTo} clearable />
          </FormField>
        </div>
        <div className="tv-reports-filter">
          <FormField label={t("reports.history.filterFormat")} htmlFor="hist-format">
            <Select
              id="hist-format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="">{t("reports.history.filterAll")}</option>
              <option value="pdf">PDF</option>
              <option value="csv">CSV</option>
              <option value="xlsx">XLSX</option>
            </Select>
          </FormField>
        </div>
        <div className="tv-reports-filter tv-reports-filter--search">
          <FormField label={t("reports.history.colName")} htmlFor="hist-q">
            <TextInput
              id="hist-q"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("reports.history.searchPlaceholder")}
            />
          </FormField>
        </div>
      </div>

      {error && <p className="tv-reports-hint">{error}</p>}
      {entries !== null && entries.length === 0 && !filtered ? (
        <EmptyState
          title={t("reports.history.emptyTitle")}
          description={t("reports.history.emptyBody")}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={entries ?? []}
          rowKey={(entry) => entry.id}
          onRowClick={(entry) => void openEntry(entry)}
          emptyState={t("reports.history.noMatch")}
        />
      )}

      <AttachmentViewer
        attachment={viewerFile}
        onClose={() => {
          setViewerFile(null);
          setViewerEntry(null);
        }}
        emailPath={
          viewerEntry ? `/reports/history/${viewerEntry.id}/email` : undefined
        }
        deleteControl={
          viewerEntry ? (
            <DeleteReportButton
              entry={viewerEntry}
              onDeleted={(entry) => {
                setViewerFile(null);
                setViewerEntry(null);
                setEntries((rows) =>
                  (rows ?? []).filter((row) => row.id !== entry.id),
                );
                toast(t("reports.history.deleted"));
              }}
            />
          ) : undefined
        }
      />
    </div>
  );
}
