import { type ReactNode } from "react";

export const PASSWORD_MIN_LENGTH = 6; // mirrors the backend policy (schemas)

export function detail(label: string, value: ReactNode) {
  return (
    <div
      style={{
        display: "grid",
        // minmax(0, …): the value column must be allowed to shrink
        // below its content's min-content — an unbroken email is
        // ~190px of min-content, which at phone widths otherwise
        // forces the row (and in Steel Light the whole panel, and
        // with it the document) wider than the screen (measured
        // 412px at a 402px viewport, 2026-10-18). The dd's
        // overflow-wrap then breaks the value inside its column.
        gridTemplateColumns: "150px minmax(0, 1fr)",
        gap: "0.5rem",
      }}
    >
      <dt style={{ color: "var(--text-muted)" }}>{label}</dt>
      <dd style={{ margin: 0, fontWeight: 600, minWidth: 0, overflowWrap: "anywhere" }}>
        {value}
      </dd>
    </div>
  );
}

/* ------------------------------ Profile ------------------------------ */

