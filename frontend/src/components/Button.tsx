import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { Spinner } from "./Spinner";

export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  block = false,
  className?: string,
): string {
  return [
    "tv-btn",
    `tv-btn--${variant}`,
    size !== "md" ? `tv-btn--${size}` : "",
    block ? "tv-btn--block" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and disables the button while keeping its label. */
  loading?: boolean;
  /** Stretch to the width of the container. */
  block?: boolean;
  children: ReactNode;
}

/**
 * The only button in the system. Variants and sizes are explicit;
 * all colors come from tokens via the theme layer (.tv-btn classes).
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  block = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  return (
    <button className={buttonClasses(variant, size, block, className)} disabled={disabled || loading} {...rest}>
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  );
}

interface LinkButtonProps extends Omit<LinkProps, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * A navigation action styled as a button — ONE focusable element
 * (F2-06). This replaces the `<Link><Button/></Link>` nesting that
 * gave every major CTA two Tab stops and invalid interactive-
 * inside-interactive HTML.
 */
export function LinkButton({
  variant = "primary",
  size = "md",
  block = false,
  className,
  children,
  ...rest
}: LinkButtonProps) {
  return (
    <Link className={buttonClasses(variant, size, block, className)} {...rest}>
      {children}
    </Link>
  );
}

interface HrefButtonProps extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
  className?: string;
  children: ReactNode;
}

/** The external/plain-href twin of LinkButton (tel:, mailto:,
 *  full-page OAuth starts, file opens): one `<a class="tv-btn">`. */
export function HrefButton({
  variant = "primary",
  size = "md",
  block = false,
  className,
  children,
  ...rest
}: HrefButtonProps) {
  return (
    <a className={buttonClasses(variant, size, block, className)} {...rest}>
      {children}
    </a>
  );
}
