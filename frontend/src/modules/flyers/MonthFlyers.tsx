import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Panel,
  Spinner,
} from "../../components";
import { useT } from "../../i18n/LocaleContext";
import { flyerByMonth } from "./api";
import { FlyerReader } from "./FlyerReader";
import {
  EndedBadge,
  OpenFlyerButton,
  pagesLabel,
  windowLabel,
} from "./SourcePanel";
import type { FlyerMonthRow, FlyerView } from "./types";

/**
 * Flyers BY MONTH (sheet row 55, owner 2026-11-15): the
 * Flyers page's default display — this month's flyers from
 * every connected agent in one place, grouped by the agent
 * they came from, with a stepper to walk other months. Some
 * months hold several flyers, some one, some none — an empty
 * month says so plainly. A flyer belongs to every month its
 * run window touches (the backend decides). Rows wear the
 * company tab's row shape and open the same preview window;
 * posting and managing stay in the By company view.
 */
export function MonthFlyers() {
  const t = useT();
  const now = useMemo(() => new Date(), []);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [rows, setRows] = useState<FlyerMonthRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [preview, setPreview] = useState<FlyerView | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setFailed(false);
    flyerByMonth(year, month)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  const step = (delta: number) => {
    const d = new Date(year, month - 1 + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth() + 1);
  };
  const isThisMonth =
    year === now.getFullYear() && month === now.getMonth() + 1;
  const monthName = new Date(year, month - 1, 1).toLocaleDateString(
    undefined,
    { month: "long", year: "numeric" },
  );

  const groups = useMemo(() => {
    const out: { key: string; title: string; rows: FlyerMonthRow[] }[] = [];
    const byKey = new Map<string, (typeof out)[number]>();
    for (const row of rows ?? []) {
      let group = byKey.get(row.key);
      if (!group) {
        group = {
          key: row.key,
          title: row.agent_name
            ? `${row.agent_name} · ${row.company_name}`
            : row.company_name,
          rows: [],
        };
        byKey.set(row.key, group);
        out.push(group);
      }
      group.rows.push(row);
    }
    return out;
  }, [rows]);

  return (
    <div className="tv-stack">
      <div className="flyer-month-bar">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-label={t("flyers.prevMonth")}
          onClick={() => step(-1)}
        >
          ‹
        </Button>
        <span className="flyer-month-name">{monthName}</span>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-label={t("flyers.nextMonth")}
          onClick={() => step(1)}
        >
          ›
        </Button>
        {!isThisMonth ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setYear(now.getFullYear());
              setMonth(now.getMonth() + 1);
            }}
          >
            {t("flyers.thisMonth")}
          </Button>
        ) : null}
      </div>

      {failed ? (
        <p className="flyer-error">{t("home.widgetLoadFailed")}</p>
      ) : rows === null ? (
        <Spinner label="Loading…" />
      ) : groups.length === 0 ? (
        <Panel>
          <p className="flyer-month-empty">
            {t("flyers.noFlyersInMonth").replace("{month}", monthName)}
          </p>
        </Panel>
      ) : (
        groups.map((group) => (
          <Panel key={group.key} title={group.title}>
            <div className="flyer-list">
              {group.rows.map((row) => {
                const flyer = row.flyer;
                const open = flyer.pdf_url
                  ? () => setPreview(flyer)
                  : null;
                return (
                  <div
                    key={flyer.id}
                    className="flyer-company-row flyer-month-row"
                    {...(open
                      ? {
                          role: "button" as const,
                          tabIndex: 0,
                          onClick: open,
                          onKeyDown: (e: React.KeyboardEvent) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              open();
                            }
                          },
                        }
                      : {})}
                  >
                    <span className="flyer-row-main">
                      {flyer.thumb_url ? (
                        <img
                          className="flyer-row-thumb"
                          src={flyer.thumb_url}
                          alt=""
                        />
                      ) : null}
                      <span className="flyer-row-text">
                        <span className="flyer-row-labelrow">
                          <span
                            className="flyer-row-label"
                            title={flyer.label || undefined}
                          >
                            {flyer.label || "—"}
                          </span>
                          {flyer.is_current ? (
                            <span className="flyer-current-badge">
                              {t("flyers.currentBadge")}
                            </span>
                          ) : null}
                          <EndedBadge flyer={flyer} />
                        </span>
                        <span className="flyer-row-sub">
                          {windowLabel(flyer)} · {pagesLabel(t, flyer.page_count)}
                        </span>
                      </span>
                    </span>
                    <span>{windowLabel(flyer)}</span>
                    <span>{pagesLabel(t, flyer.page_count)}</span>
                    <span
                      className="flyer-row-actions"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      {open ? <OpenFlyerButton onOpen={open} /> : null}
                    </span>
                  </div>
                );
              })}
            </div>
          </Panel>
        ))
      )}

      <FlyerReader flyer={preview} onClose={() => setPreview(null)} />
    </div>
  );
}
