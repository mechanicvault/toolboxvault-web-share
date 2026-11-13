/** Star displays for the print shelf. The read-only face
 * paints the average (full stars rounded to the nearest half
 * step visually by fill percentage on the last star — kept
 * simple: full stars for the rounded average, the exact
 * number beside it does the precision work). The input face
 * is five real buttons — a rating is a choice, so it takes
 * the main highlight treatment like every clickable thing. */

import { StarIcon } from "../../components/icons";

export function StarsDisplay({ average, size = 15 }: { average: number; size?: number }) {
  const full = Math.round(average);
  return (
    <span className="pr-stars" aria-label={`${average} / 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={n <= full ? "pr-star pr-star-on" : "pr-star"}>
          <StarIcon size={size} />
        </span>
      ))}
    </span>
  );
}

export function StarsInput({
  value,
  onPick,
  disabled,
}: {
  value: number;
  onPick: (stars: number) => void;
  disabled?: boolean;
}) {
  return (
    <span className="pr-stars pr-stars-input">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          className={n <= value ? "pr-star-btn pr-star-on" : "pr-star-btn"}
          onClick={() => onPick(n)}
          disabled={disabled}
          aria-label={`${n} / 5`}
          aria-pressed={n === value}
        >
          <StarIcon size={22} />
        </button>
      ))}
    </span>
  );
}
