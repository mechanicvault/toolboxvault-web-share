import { forwardRef, type TextareaHTMLAttributes } from "react";

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

/** The only multi-line input in the system. */
export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(
  function TextArea({ invalid, className, ...rest }, ref) {
    const classes = ["tv-input", invalid ? "tv-input--invalid" : "", className ?? ""]
      .filter(Boolean)
      .join(" ");
    return (
      <textarea ref={ref} className={classes} aria-invalid={invalid || undefined} {...rest} />
    );
  },
);
