import { useEffect, useState } from "react";
import { Badge, type BadgeTone } from "../../../components";
import { useT } from "../../../i18n/LocaleContext";
import { listMine } from "../../marketplace/api";
import type { Standing } from "../types";
import type { ItemStatusData } from "./ItemStatusStrip";
import { STANDING_TONES } from "./StandingBadge";
import "../itemPage.css";

/**
 * The item header's ONE status pill (owner ruling 2026-11-03):
 * it sits in the facts row, immediately right of the purchase
 * date, and names the item's current primary status in the
 * owner's vocabulary — Available (the status formerly labeled
 * "In service"), Checked out, Broken, Lost, Stolen, For sale,
 * Sent out (sent out for repair). Sold / Replaced keep their
 * standing names — they are not in the owner's list, and calling
 * a sold item "Available" would be a lie.
 *
 * The state comes from the SAME live-state seam the header
 * status strip reads (the page's useItemStatus data: standing +
 * the open loss report + the current checkout + the item's
 * claims) — no second state model. Broken / Sent out derive
 * from the standing plus the item's OPEN CLAIM (repairs ∪
 * claims merge, 2026-11-04): the claim lifecycle drives the
 * standing, and a broken-standing item whose open claim is
 * already in repair reads Sent out — it is physically out,
 * whatever the standing's last write says. The one extra read
 * is the owner's own listings (the For sale state):
 * best-effort, exactly like the strip's reads — when Tools For
 * Sale isn't effective for the viewer the read fails quietly
 * and the state simply never shows.
 *
 * Precedence when several states coincide (safety/asset-risk
 * first, then the standing's terminal states, then routine):
 *   Lost > Stolen > Broken > Sent out > Sold > Replaced
 *   > Checked out > For sale > Available.
 * A checked-out item PAST its return date renders the pill RED
 * (the danger tone) — the overdue treatment.
 */
export function ItemStatusPill({
  standing,
  data,
  itemKind,
  itemId,
}: {
  standing: Standing;
  data: ItemStatusData;
  itemKind: "tool" | "battery";
  itemId: string;
}) {
  const t = useT();
  const [forSale, setForSale] = useState(false);

  useEffect(() => {
    let live = true;
    setForSale(false);
    listMine()
      .then((rows) => {
        if (!live) return;
        setForSale(
          rows.some(
            (row) =>
              row.status === "active" &&
              row.source_kind === itemKind &&
              row.source_id === itemId,
          ),
        );
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [itemKind, itemId]);

  let tone: BadgeTone = "success";
  let label = t("inventory.status.available");

  // Sent out via the claim (merge, 2026-11-04): an open warranty
  // claim in repair means the item is out being fixed.
  const claimSentOut = Boolean(
    data.claims?.current.some(
      (c) => c.kind === "warranty_repair" && c.status === "in_repair",
    ),
  );

  if (standing === "lost") {
    tone = STANDING_TONES.lost;
    label = t("inventory.status.lost");
  } else if (standing === "stolen") {
    tone = STANDING_TONES.stolen;
    label = t("inventory.status.stolen");
  } else if (standing === "broken" && claimSentOut) {
    tone = STANDING_TONES.in_repair;
    label = t("inventory.status.sentOut");
  } else if (standing === "broken") {
    tone = "danger";
    label = t("inventory.status.broken");
  } else if (standing === "in_repair") {
    tone = STANDING_TONES.in_repair;
    label = t("inventory.status.sentOut");
  } else if (standing === "sold") {
    tone = STANDING_TONES.sold;
    label = t("inventory.status.sold");
  } else if (standing === "replaced") {
    tone = STANDING_TONES.replaced;
    label = t("inventory.status.replaced");
  } else if (data.checkout?.state === "checked_out") {
    tone = data.checkout.overdue ? "danger" : "accent";
    label = t("inventory.status.checkedOut");
  } else if (forSale) {
    tone = "success";
    label = t("inventory.status.forSale");
  }

  return (
    <span className="tv-item-statuspill">
      <Badge tone={tone} dot>
        {label}
      </Badge>
    </span>
  );
}
