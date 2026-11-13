import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { listTemplates } from "../../modules/reports/api";
import type { ReportTemplateView } from "../../modules/reports/types";
import { PanelUtility } from "./PanelUtility";

/**
 * The Reports panel (Rail Steel conversion, Phase 2c).
 *
 * Reports redesign (2026-11-06): the page is a main tab layout
 * (New report / Accounting / History / Request a report type)
 * and its saved reports are TEMPLATES — type + settings that
 * run fresh from today's data. The panel links the page itself
 * (with the area deep links), lists the report kinds the
 * wizard offers as plain rows (the catalog's ten kinds), and
 * carries the saved-template facts from the page's own read,
 * GET /reports/templates (listTemplates). Nothing here pretends
 * to run a report.
 */

const KIND_TITLES = [
  "Full inventory report",
  "Open repair claims",
  "Open truck accounts",
  "Checked out items",
  "Lost / stolen",
  "Warranty claims",
  "Fiscal year-end spending",
  "Fiscal year repair claim costs",
  "Sales",
  "Tax 179 worksheet",
];

const NAME_CAP = 8;

export function ReportsPanel() {
  const [templates, setTemplates] = useState<ReportTemplateView[] | null>(null);

  useEffect(() => {
    let live = true;
    listTemplates()
      .then((data) => {
        if (live) setTemplates(data.templates);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const quick = (templates ?? []).filter((row) => row.area === "quick");
  const accounting = (templates ?? []).filter((row) => row.area === "accounting");

  return (
    <>
      <p className="tv-sp-kicker">Reports</p>
      <h2 className="tv-sp-title">Reports</h2>
      <PanelUtility />
      <p className="tv-sp-group">Reports</p>
      <div className="tv-sp-list">
        <NavLink
          to="/reports#new"
          className="tv-sp-item"
        >
          <span>New report</span>
        </NavLink>
        <NavLink
          to="/reports#accounting"
          className="tv-sp-item"
        >
          <span>Accounting</span>
          {templates !== null && (
            <span className="tv-sp-count">{accounting.length.toLocaleString("en-US")}</span>
          )}
        </NavLink>
        <NavLink
          to="/reports#history"
          className="tv-sp-item"
        >
          <span>History</span>
        </NavLink>
      </div>
      <p className="tv-sp-group">Report kinds</p>
      <div className="tv-sp-list">
        {KIND_TITLES.map((title) => (
          <span key={title} className="tv-sp-item tv-sp-item--text">
            <span>{title}</span>
          </span>
        ))}
      </div>
      {templates !== null && (
        <>
          <p className="tv-sp-group">Saved reports</p>
          <ul className="tv-sp-stats">
            <li>
              <span>Quick Reports</span>
              <strong>{quick.length.toLocaleString("en-US")}</strong>
            </li>
            <li>
              <span>Accounting</span>
              <strong>{accounting.length.toLocaleString("en-US")}</strong>
            </li>
          </ul>
          {templates.length > 0 && (
            <div className="tv-sp-list">
              {templates.slice(0, NAME_CAP).map((template) => (
                <span key={template.id} className="tv-sp-item tv-sp-item--text">
                  <span>{template.name}</span>
                </span>
              ))}
            </div>
          )}
          {templates.length > NAME_CAP && (
            <p className="tv-sp-hint">
              +{templates.length - NAME_CAP} more — the full lists are on the
              Reports page.
            </p>
          )}
        </>
      )}
    </>
  );
}
