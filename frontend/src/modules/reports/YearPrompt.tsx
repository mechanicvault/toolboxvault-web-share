import { useEffect, useState } from "react";

import { Button, FormField, Modal, Select } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { ReportTemplateView } from "./types";

/**
 * The run-time year ask (Ryan's spec: fiscal templates pick
 * their year when they run, never when they're saved). Shared
 * by both template lists. For year_or_all types (repair costs)
 * the prompt also offers All time — the run then carries no
 * year at all.
 */

export function yearOptions(): number[] {
  const now = new Date().getFullYear();
  const years: number[] = [];
  for (let y = now + 1; y >= now - 7; y -= 1) years.push(y);
  return years;
}

export function YearPrompt({
  template,
  allowAllTime,
  onCancel,
  onRun,
}: {
  template: ReportTemplateView | null;
  allowAllTime: boolean;
  onCancel: () => void;
  onRun: (year: number | null) => void;
}) {
  const t = useT();
  const [value, setValue] = useState<string>("");

  useEffect(() => {
    if (template) {
      const stored = template.settings?.year;
      // A stored year wins; otherwise an all-time type starts
      // on All time and a year type on the current year.
      setValue(
        typeof stored === "number"
          ? String(stored)
          : allowAllTime
            ? ""
            : String(new Date().getFullYear()),
      );
    }
  }, [template, allowAllTime]);

  return (
    <Modal
      open={template !== null}
      onClose={onCancel}
      title={t("reports.year.title")}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onCancel}>
            {t("reports.wizard.cancel")}
          </Button>
          <span className="tv-reports-spacer" />
          <Button
            onClick={() => onRun(value === "" ? null : Number(value))}
          >
            {t("reports.year.run")}
          </Button>
        </>
      }
    >
      <div className="tv-wizard">
        <p className="tv-reports-hint">{t("reports.year.body")}</p>
        <FormField label={t("reports.year.label")} htmlFor="reports-year-prompt">
          <Select
            id="reports-year-prompt"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            {allowAllTime && (
              <option value="">{t("reports.year.allTime")}</option>
            )}
            {yearOptions().map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Modal>
  );
}
