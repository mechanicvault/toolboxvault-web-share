import { Badge, type BadgeTone } from "../../../components";
import { STANDING_LABELS, type Standing } from "../types";

export const STANDING_TONES: Record<Exclude<Standing, "in_service">, BadgeTone> = {
  broken: "danger",
  in_repair: "warning",
  lost: "neutral",
  stolen: "danger",
  sold: "success",
  replaced: "neutral",
};

/** The standing badge (Package B): renders for any standing other
 *  than in_service — in service is the quiet default and gets no
 *  badge. One look on cards, list rows, and detail pages. */
export function StandingBadge({ standing }: { standing: Standing }) {
  if (!standing || standing === "in_service") return null;
  return (
    <Badge tone={STANDING_TONES[standing]} dot>
      {STANDING_LABELS[standing]}
    </Badge>
  );
}
