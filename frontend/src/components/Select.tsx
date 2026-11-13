import { forwardRef, type SelectHTMLAttributes } from "react";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean;
  inputSize?: "sm" | "md";
}

/** The only dropdown in the system (native select, token-styled). */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { invalid, inputSize = "md", className, children, ...rest },
  ref,
) {
  const classes = [
    "tv-input",
    invalid ? "tv-input--invalid" : "",
    inputSize === "sm" ? "tv-input--sm" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <select ref={ref} className={classes} aria-invalid={invalid || undefined} {...rest}>
      {children}
    </select>
  );
});
