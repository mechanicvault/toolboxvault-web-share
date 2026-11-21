import { cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

export interface FormFieldProps {
  label: string;
  /** Omit for group controls (checkbox/radio sets) that have no single
   *  input to label — the label then renders as a plain group caption. */
  htmlFor?: string;
  required?: boolean;
  /** Helper text shown under the control. */
  hint?: string;
  /** Error text; also rendered with role="alert". */
  error?: string;
  children: ReactNode;
}

/**
 * Labeled form field with hint + error. One look for every form.
 * (Historically exported as `Field`; both names are the same component.)
 *
 * F2-16: when `htmlFor` is set and there is exactly one child
 * control, the error/hint get stable ids and are wired onto the
 * control via aria-describedby; the error sets aria-invalid on the
 * control too (stale errors also need the wiring, not just the
 * color). F2-22: `required` is passed through to the actual
 * control (required + aria-required), so the star is never the
 * only signal.
 */
export function FormField({ label, htmlFor, required, hint, error, children }: FormFieldProps) {
  const caption = (
    <>
      {label}
      {required && (
        <span className="tv-field-required" aria-hidden="true">
          {" "}
          *
        </span>
      )}
    </>
  );
  const errorId = htmlFor && error ? `${htmlFor}-error` : undefined;
  const hintId = htmlFor && hint ? `${htmlFor}-hint` : undefined;
  let child = children;
  if (htmlFor && isValidElement(children)) {
    const el = children as ReactElement<any>;
    const describedby = [errorId, hintId].filter(Boolean).join(" ") || undefined;
    const prevDescribed = (el.props as any)?.["aria-describedby"] as string | undefined;
    const merged = [prevDescribed, describedby].filter(Boolean).join(" ") || undefined;
    const prevRequired = (el.props as any)?.required as boolean | undefined;
    child = cloneElement(el, {
      ...(merged ? { "aria-describedby": merged } : {}),
      ...(error ? { "aria-invalid": true } : {}),
      ...(required && prevRequired !== false ? { required: true, "aria-required": true } : {}),
    } as any);
  }
  return (
    <div className="tv-field">
      {htmlFor ? (
        <label htmlFor={htmlFor} className="tv-field-label">
          {caption}
        </label>
      ) : (
        <span className="tv-field-label">{caption}</span>
      )}
      {child}
      {error ? (
        <p role="alert" id={errorId} className="tv-field-error">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="tv-field-hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** Back-compat alias — existing modules import `Field`. */
export const Field = FormField;
