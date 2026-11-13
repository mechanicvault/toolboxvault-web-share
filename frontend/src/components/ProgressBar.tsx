interface ProgressBarProps {
  /** 0–100. */
  value: number;
  tone?: "accent" | "success" | "warning" | "danger";
  label?: string;
}

/** Slim progress track; the fill glows in tinted themes. */
export function ProgressBar({ value, tone = "accent", label }: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div
      className="tv-progress"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={`tv-progress-fill${tone !== "accent" ? ` tv-progress-fill--${tone}` : ""}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
