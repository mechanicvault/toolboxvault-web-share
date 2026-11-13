import { forwardRef, type InputHTMLAttributes } from "react";

export interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Red border + danger focus ring; pair with FormField's error text. */
  invalid?: boolean;
  inputSize?: "sm" | "md";
}

/** The only text input in the system (email/password/number/date too). */
export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  function TextInput({ invalid, inputSize = "md", className, ...rest }, ref) {
    const classes = [
      "tv-input",
      invalid ? "tv-input--invalid" : "",
      inputSize === "sm" ? "tv-input--sm" : "",
      className ?? "",
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <input
        ref={ref}
        className={classes}
        aria-invalid={invalid || undefined}
        {...rest}
      />
    );
  },
);
