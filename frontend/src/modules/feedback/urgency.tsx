/** Urgency UI (boards lane, 2026-11-07) — the two shapes the
 *  filer's urgency call takes:
 *
 *  - UrgencyPill: the read-only face. It rides the board list
 *    rows, the post page, and the Home board widgets — one
 *    component so the word and its color can never drift
 *    between surfaces. The filer sees the pill and nothing
 *    else: their call locked at submission.
 *
 *  - UrgencyToggle: the 3-position toggle switch the owner
 *    asked for ("give the urgency picker some flare"). One
 *    segmented steel switch, Low | Medium | High, the chosen
 *    segment lit in its level's color. It renders in exactly
 *    two places: the filing form (the filer's one pick) and
 *    the post page's moderator panel (the responders' lever).
 *    Styling lives in feedback.css — no inline styles.
 */

import { Badge } from "../../components";
import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import {
  URGENCY_LABEL_KEYS,
  URGENCY_LEVELS,
  URGENCY_TONES,
  type FeedbackUrgency,
} from "./types";

export function UrgencyPill({ urgency }: { urgency: FeedbackUrgency }) {
  const t = useT();
  return (
    <Badge tone={URGENCY_TONES[urgency]}>
      {t(URGENCY_LABEL_KEYS[urgency] as DictKey)}
    </Badge>
  );
}

export function UrgencyToggle({
  value,
  onChange,
  label,
  disabled = false,
}: {
  value: FeedbackUrgency;
  onChange: (next: FeedbackUrgency) => void;
  label: string;
  disabled?: boolean;
}) {
  const t = useT();
  return (
    <div className="tv-urgency-toggle" role="radiogroup" aria-label={label}>
      {URGENCY_LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          role="radio"
          aria-checked={value === level}
          data-level={level}
          className={
            value === level
              ? "tv-urgency-seg tv-urgency-seg--on"
              : "tv-urgency-seg"
          }
          disabled={disabled}
          onClick={() => onChange(level)}
        >
          {t(URGENCY_LABEL_KEYS[level] as DictKey)}
        </button>
      ))}
    </div>
  );
}
