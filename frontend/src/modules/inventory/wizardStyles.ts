import "./wizard.css";

export const pageTitleStyle = { margin: "0.25rem 0 0", fontSize: "1.5rem" } as const;
export const loadingStyle = {
  color: "var(--text-muted)",
  display: "flex",
  gap: "var(--space-2)",
  alignItems: "center",
} as const;
export const pieceCardStyle = {
  display: "grid",
  gap: "0.5rem",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.7rem",
} as const;
export const pieceRowStyle = { display: "flex", gap: "0.5rem", flexWrap: "wrap" } as const;
export const pieceKindStyle = { flex: "0 1 130px" } as const;
export const pieceNameStyle = { flex: "1 1 180px" } as const;
export const pieceGridStyle = {
  display: "grid",
  gap: "0.5rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))",
} as const;
export const rebuyBoxStyle = {
  display: "grid",
  gap: "0.7rem",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  padding: "0.8rem",
} as const;
export const tagRowStyle = {
  display: "flex",
  gap: "0.4rem",
  flexWrap: "wrap",
  marginBottom: "0.7rem",
} as const;
export const tagButtonStyle = {
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
} as const;
export const tagInputWrapStyle = { flex: "1 1 180px" } as const;
export const reviewRowStyle = {
  display: "flex",
  gap: "0.75rem",
  flexWrap: "wrap",
} as const;
export const reviewLabelStyle = {
  flex: "0 0 150px",
  color: "var(--text-muted)",
  fontSize: "0.9rem",
} as const;
export const batteryListStyle = {
  display: "grid",
  gap: "0.4rem",
  maxHeight: "340px",
  overflowY: "auto",
} as const;
export const batteryRowStyle = {
  display: "grid",
  gap: "0.15rem",
  textAlign: "left",
  width: "100%",
  border: "1px solid var(--edge)",
  borderRadius: "var(--radius)",
  background: "none",
  padding: "0.55rem 0.7rem",
  cursor: "pointer",
  color: "inherit",
} as const;
export const batteryRowSelectedStyle = {
  ...batteryRowStyle,
  borderColor: "var(--accent)",
  outline: "1px solid var(--accent)",
} as const;
export const batteryNameStyle = { fontWeight: 600 } as const;
export const batterySpecStyle = { color: "var(--text-muted)", fontSize: "0.85rem" } as const;
export const ruleIndentStyle = { marginLeft: "1.6rem" } as const;
export const setCheckboxRowStyle = { marginTop: "0.9rem" } as const;
export const lockedNoteStyle = {
  color: "var(--text-muted)",
  fontSize: "0.9rem",
  marginLeft: "1.6rem",
} as const;
export const dupRowStyle = { marginTop: 0 } as const;
export const saveSelectionsStyle = {
  borderTop: "1px solid var(--edge)",
  paddingTop: "0.7rem",
} as const;

