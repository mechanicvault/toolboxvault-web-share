interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  /** Accessible label; the spinner is decorative without one. */
  label?: string;
}

/** The only loading indicator in the system. Accent-tinted by tokens. */
export function Spinner({ size = "md", label }: SpinnerProps) {
  return (
    <span
      className={`tv-spinner tv-spinner--${size}`}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}
