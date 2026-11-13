import { SELF_SERVE_ACCOUNT_TYPE_OPTIONS, type AccountType } from "../accountTypes";
import { useT } from "../../../i18n/LocaleContext";

export interface GroupPickerProps {
  /** The currently picked set (may be empty while the user decides). */
  value: AccountType[];
  onChange: (next: AccountType[]) => void;
  /** Form name for the underlying checkboxes. */
  name?: string;
}

/**
 * The group picker: one selectable card per group, MULTI-select
 * (checkbox behavior — a user can be a dealer AND a technician).
 * Shared by signup, the one-time "choose your groups" gate, and the
 * Settings editor, so the pick looks and behaves identically in all
 * three. Renders the SELF-SERVE list only (accountTypes.ts): groups
 * an operator can assign but users can't pick — insurance, for now —
 * never appear here. Styling lives in the theme layer (.tv-group-picker /
 * .tv-group-card): one full-width row per group, wearing the
 * input-well family face in every theme (no plate art).
 */
export function GroupPicker({ value, onChange, name = "account_types" }: GroupPickerProps) {
  const t = useT();
  function toggle(type: AccountType, checked: boolean) {
    onChange(
      checked ? [...value, type] : value.filter((t) => t !== type),
    );
  }
  return (
    <div className="tv-group-picker" role="group" aria-label="Account groups">
      {SELF_SERVE_ACCOUNT_TYPE_OPTIONS.map((option) => {
        const selected = value.includes(option.value);
        const id = `gp-${name}-${option.value}`;
        return (
          <label
            key={option.value}
            htmlFor={id}
            className={`tv-group-card${selected ? " is-selected" : ""}`}
          >
            <input
              id={id}
              type="checkbox"
              name={name}
              value={option.value}
              checked={selected}
              onChange={(e) => toggle(option.value, e.target.checked)}
            />
            <span className="tv-group-check" aria-hidden="true" />
            <span className="tv-group-card-text">
              <span className="tv-group-card-title">{t(`group.${option.value}` as never)}</span>
              <span className="tv-group-card-desc">{t(`group.${option.value}.desc` as never)}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}
