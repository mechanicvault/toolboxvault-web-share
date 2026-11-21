import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";

import { useT } from "../i18n/LocaleContext";
import { activeLocale, formatDate, todayLocalIso } from "../lib/format";
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "./icons";

/**
 * THE date entry control (owner standing rule, 2026-11-04:
 * "Anywhere you have to enter a date into the system, that date
 * should default to todays date and be a calendar picker").
 *
 * One component for every date field in the system — the native
 * <input type="date"> is retired. The trigger wears the shared
 * .tv-input box and shows the date in the standard display
 * format (lib/format's formatDate, active locale); clicking it
 * opens a month-grid calendar in a portal at the document root
 * (the UserMenu pattern — an in-flow popup gets clipped by
 * scrolling/overflow containers, and date fields live in modals
 * and tab panels). Previous/next month buttons, today ringed,
 * the chosen day filled; clicking a day selects and closes.
 * Escape, an outside click, a page scroll, or a resize closes
 * without changing the value.
 *
 * Values in and out are plain "YYYY-MM-DD" strings — exactly
 * what every form already sends the API, so no backend change
 * rides along. "" means unset: fields the data model allows to
 * stay empty pass `clearable` and keep their empty state (the
 * today-default is applied by the FORMS, at their state init,
 * for new entries — this control never invents a value, so an
 * edit form always shows the record's saved date).
 */
export interface DatePickerProps {
  id?: string;
  name?: string;
  /** "YYYY-MM-DD", or "" when unset. */
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  inputSize?: "sm" | "md";
  className?: string;
  /** Trigger text when no date is chosen; defaults to the
   *  dictionary's "Select a date". */
  placeholder?: string;
  /** Offer a Clear action in the popup — for fields the record
   *  is allowed to leave empty. */
  clearable?: boolean;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "grammar" | "spelling";
}

interface Ymd {
  y: number;
  m: number;
  d: number;
}

/** Strict "YYYY-MM-DD" parse; null for anything else. */
function parseIso(iso: string): Ymd | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) {
    return null;
  }
  return { y, m, d };
}

function toIso(y: number, m: number, d: number): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${y}-${p(m)}-${p(d)}`;
}

/** 0 = Sunday … 6 = Saturday, from the locale's week info where
 *  the browser provides it; Spanish weeks start Monday, US weeks
 *  Sunday, as the fallback. */
function firstDayOfWeek(locale: string | undefined): number {
  try {
    const info = (
      new Intl.Locale(locale ?? "en-US") as unknown as {
        weekInfo?: { firstDay?: number };
      }
    ).weekInfo;
    if (info && typeof info.firstDay === "number") return info.firstDay % 7;
  } catch {
    /* fall through to the language default */
  }
  return locale?.toLowerCase().startsWith("es") ? 1 : 0;
}

const POP_WIDTH = 272;
const POP_HEIGHT = 336;

export function DatePicker({
  id,
  name,
  value,
  onChange,
  required,
  disabled,
  invalid,
  inputSize = "md",
  className,
  placeholder,
  clearable,
  "aria-label": ariaLabel,
  "aria-describedby": ariaDescribedby,
  "aria-invalid": ariaInvalid,
}: DatePickerProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<{ y: number; m: number }>({ y: 2000, m: 1 });
  const [popStyle, setPopStyle] = useState<CSSProperties>({});
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const todayIso = todayLocalIso();
  const selected = parseIso(value);
  const firstDay = firstDayOfWeek(activeLocale());

  const close = (restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  };

  const openPicker = () => {
    const anchor = selected ?? parseIso(todayIso) ?? { y: 2000, m: 1, d: 1 };
    setView({ y: anchor.y, m: anchor.m });
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      const gap = 4;
      const margin = 8;
      const left = Math.min(
        Math.max(rect.left, margin),
        Math.max(margin, window.innerWidth - POP_WIDTH - margin),
      );
      const flipUp =
        rect.bottom + gap + POP_HEIGHT > window.innerHeight &&
        rect.top - gap - POP_HEIGHT > 0;
      const style: CSSProperties = flipUp
        ? { left, bottom: window.innerHeight - rect.top + gap }
        : { left, top: rect.bottom + gap };
      setPopStyle(style);
    }
    setOpen(true);
  };

  /* Dismissal + initial focus while the calendar is open. */
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        wrapRef.current?.contains(target) ||
        popRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onScroll = (e: Event) => {
      if (popRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    const focusTimer = window.setTimeout(() => {
      const pop = popRef.current;
      if (!pop) return;
      const target =
        pop.querySelector<HTMLButtonElement>("[data-selected='true']") ??
        pop.querySelector<HTMLButtonElement>("[data-today='true']");
      target?.focus();
    }, 0);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
      window.clearTimeout(focusTimer);
    };
  }, [open ]);

  const cells = useMemo(() => {
    const first = new Date(view.y, view.m - 1, 1);
    const startOffset = (first.getDay() - firstDay + 7) % 7;
    const start = new Date(view.y, view.m - 1, 1 - startOffset);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(
        start.getFullYear(),
        start.getMonth(),
        start.getDate() + i,
      );
      return {
        iso: toIso(d.getFullYear(), d.getMonth() + 1, d.getDate()),
        day: d.getDate(),
        inMonth: d.getMonth() === view.m - 1,
      };
    });
  }, [view, firstDay]);

  const weekdays = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        /* 2024-01-07 was a Sunday; walk the locale's week from it. */
        const d = new Date(2024, 0, 7 + ((firstDay + i) % 7));
        return d.toLocaleDateString(activeLocale(), { weekday: "narrow" });
      }),
    [firstDay],
  );

  const monthTitle = new Date(view.y, view.m - 1, 1).toLocaleDateString(
    activeLocale(),
    { month: "long", year: "numeric" },
  );

  const shiftMonth = (delta: number) => {
    setView((v) => {
      const d = new Date(v.y, v.m - 1 + delta, 1);
      return { y: d.getFullYear(), m: d.getMonth() + 1 };
    });
  };

  const pick = (iso: string) => {
    onChange(iso);
    close(true);
  };

  const triggerClasses = [
    "tv-input",
    "tv-datepicker-trigger",
    invalid ? "tv-input--invalid" : "",
    inputSize === "sm" ? "tv-input--sm" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={`tv-datepicker${className ? ` ${className}` : ""}`}
      ref={wrapRef}
    >
      <button
        ref={triggerRef}
        type="button"
        id={id}
        name={name}
        className={triggerClasses}
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedby}
        aria-invalid={invalid || ariaInvalid || undefined}
        aria-required={required || undefined}
        onClick={() => (open ? close(false) : openPicker())}
      >
        <span className={selected ? undefined : "tv-datepicker-placeholder"}>
          {selected ? formatDate(value) : (placeholder ?? t("common.selectDate"))}
        </span>
        <CalendarIcon size={16} />
      </button>
      {open &&
        createPortal(
          <div
            ref={popRef}
            className="tv-datepicker-pop"
            style={popStyle}
            role="dialog"
            aria-label={monthTitle}
          >
            <div className="tv-dp-head">
              <button
                type="button"
                className="tv-dp-nav"
                aria-label={t("common.prevMonth")}
                onClick={() => shiftMonth(-1)}
              >
                <ChevronLeftIcon size={16} />
              </button>
              <span className="tv-dp-title" aria-live="polite">
                {monthTitle}
              </span>
              <button
                type="button"
                className="tv-dp-nav"
                aria-label={t("common.nextMonth")}
                onClick={() => shiftMonth(1)}
              >
                <ChevronRightIcon size={16} />
              </button>
            </div>
            <div className="tv-dp-week" aria-hidden="true">
              {weekdays.map((w, i) => (
                <span key={i} className="tv-dp-weekday">
                  {w}
                </span>
              ))}
            </div>
            <div className="tv-dp-days">
              {cells.map((cell) => {
                const isToday = cell.iso === todayIso;
                const isSelected = cell.iso === value;
                const dayClasses = [
                  "tv-dp-day",
                  cell.inMonth ? "" : "tv-dp-day--outside",
                  isToday ? "tv-dp-day--today" : "",
                  isSelected ? "tv-dp-day--selected" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <button
                    key={cell.iso}
                    type="button"
                    className={dayClasses}
                    data-today={isToday || undefined}
                    data-selected={isSelected || undefined}
                    aria-label={formatDate(cell.iso)}
                    aria-pressed={isSelected || undefined}
                    onClick={() => pick(cell.iso)}
                  >
                    {cell.day}
                  </button>
                );
              })}
            </div>
            <div className="tv-dp-foot">
              <button
                type="button"
                className="tv-dp-foot-btn"
                onClick={() => pick(todayIso)}
              >
                {t("common.today")}
              </button>
              {clearable && value ? (
                <button
                  type="button"
                  className="tv-dp-foot-btn"
                  onClick={() => pick("")}
                >
                  {t("common.clear")}
                </button>
              ) : (
                <span />
              )}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
