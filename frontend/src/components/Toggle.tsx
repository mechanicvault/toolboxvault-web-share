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

/** On/off switch (role="switch") — THE in-page switch: every
 * switch on the site except the header theme switch renders
 * through this component and no other (owner, 2026-11-13:
 * "all other toggle switches on the entire website need to be
 * calling the same file to display the other toggles"). The
 * header theme switch is its own component on purpose
 * (theme/HeaderThemeSwitch.tsx — wide seat, glyphs, flipped
 * mapping) and is the only other switch implementation.
 *
 * One design: "Ember" (owner-settled, 2026-11-13 — the header
 * theme switch's design made the site toggle; #4 "Midnight
 * Ring" retired) — see .tv-switch in theme/components.css.
 * The inner span is the red OFF dash the design carries in
 * the end of the track opposite the knob. There is no
 * variant: every in-page switch is this switch. */
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
    >
      <span className="tv-switch-dash" aria-hidden="true" />
    </button>
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
