import type { ReactNode } from "react";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Optional visible label rendered beside the switch. */
  label?: ReactNode;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
}

/** On/off switch (role="switch"). The knob lights up in tinted themes. */
export function Toggle({ checked, onChange, label, disabled, id, ariaLabel }: ToggleProps) {
  const button = (
    <button
      type="button"
      id={id}
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel ?? (typeof label === "string" ? label : undefined)}
      className="tv-switch"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
  if (!label) return button;
  return (
    <span
      className="tv-switch-label"
      onClick={(e) => {
        /* The label is part of the control (the class has
         * always promised cursor: pointer): a click on the
         * label text forwards to the switch itself, so the
         * disabled state and the switch's own handler behave
         * exactly as a direct click. Clicks that land on the
         * button (or any nested control) are left alone —
         * the button handles those itself. */
        if (
          (e.target as HTMLElement).closest(
            "button, a, input, select, textarea",
          )
        ) {
          return;
        }
        e.currentTarget
          .querySelector<HTMLButtonElement>("button")
          ?.click();
      }}
    >
      {button}
      <span>{label}</span>
    </span>
  );
}
