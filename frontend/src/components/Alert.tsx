import { useState, type ReactNode } from "react";

export type AlertTone = "info" | "success" | "warning" | "danger";

interface AlertProps {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
  /** Show a dismiss (×) control. */
  dismissible?: boolean;
  onDismiss?: () => void;
}

/** Inline message block for form errors, notices, and confirmations. */
export function Alert({ tone = "info", title, children, dismissible, onDismiss }: AlertProps) {
  const [gone, setGone] = useState(false);
  if (gone) return null;
  return (
    <div className={`tv-alert tv-alert--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <div className="tv-alert-body">
        {title && <div className="tv-alert-title">{title}</div>}
        {children}
      </div>
      {dismissible && (
        <button
          type="button"
          className="tv-alert-close"
          aria-label="Dismiss"
          onClick={() => {
            setGone(true);
            onDismiss?.();
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}
