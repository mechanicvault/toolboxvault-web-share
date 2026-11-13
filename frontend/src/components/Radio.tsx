import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
}

/** Labeled radio button; group with a shared `name` as usual. */
export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { label, id, value, ...rest },
  ref,
) {
  const inputId = id ?? `rb-${rest.name ?? "r"}-${String(value ?? "")}`;
  return (
    <label className="tv-check" htmlFor={inputId}>
      <input ref={ref} id={inputId} type="radio" value={value} {...rest} />
      <span>{label}</span>
    </label>
  );
});
