import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
}

/** Labeled checkbox. Accent-tinted check via tokens. */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, id, ...rest },
  ref,
) {
  const inputId = id ?? `cb-${rest.name ?? Math.random().toString(36).slice(2, 8)}`;
  return (
    <label className="tv-check" htmlFor={inputId}>
      <input ref={ref} id={inputId} type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
});
