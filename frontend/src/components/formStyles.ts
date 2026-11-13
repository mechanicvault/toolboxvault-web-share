import type { CSSProperties } from "react";

/**
 * Legacy style helpers from before the component library was completed.
 * Kept so existing imports keep working; new code should use the shared
 * components (TextInput, FormField, …) instead of raw style objects.
 * Values are token references only, as everywhere else.
 */
export const inputStyle: CSSProperties = {
  width: "100%",
  minHeight: "var(--control-height)",
  padding: "0.55rem 0.7rem",
  borderRadius: "var(--radius)",
  border: "1px solid var(--input-edge)",
  background: "var(--input-bg)",
  boxShadow: "var(--input-shadow)",
  color: "var(--text)",
  fontSize: "1rem",
  fontFamily: "var(--font)",
};

export const labelStyle: CSSProperties = {
  display: "block",
  marginBottom: "0.35rem",
  fontWeight: 600,
  fontSize: "0.9rem",
  color: "var(--text)",
};

export const formGridStyle: CSSProperties = {
  display: "grid",
  gap: "0.9rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
};

export const errorTextStyle: CSSProperties = {
  margin: "0.35rem 0 0",
  fontSize: "0.85rem",
  color: "var(--danger)",
};
