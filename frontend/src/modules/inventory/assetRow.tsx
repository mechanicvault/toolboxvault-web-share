import {type ReactNode} from "react";
import {
  Badge,
  Checkbox,
} from "../../components";
import {batterySpecChips} from "./components/BatteryCard";
import {ItemPhoto} from "./components/ItemPhoto";
import {useT} from "../../i18n/LocaleContext";
import {StandingBadge} from "./components/StandingBadge";
import {money} from "./format";
import {
  Battery,
  Tool,
} from "./types";
import {extendedPrice} from "./listUtils";

export interface RowLending {
  chip: string;
  /** The full standing text ("Checked out to … · due …"), carried
   *  as the pill's hover title (sweep B2-F6). */
  title?: string;
  tone: "accent" | "warning" | "danger";
}

/** One item in LIST layout: a TRUE list row (list standard,
 *  2026-11-02) — one record per row, each fact in its OWN column
 *  across the row on the header's grid template: thumbnail +
 *  name · dealer/brand · status badges · quantity · extended price,
 *  with the expansion badge and the item's Actions menu riding
 *  a trailing actions column. (The Model # and Location columns
 *  left the list on the owner's word, 2026-11-05 — both facts
 *  still live on the item itself and its page.) Battery spec
 *  chips (F1-16) stay as the item cell's sub-line, the way the
 *  battery page carries them. Clicking any fact cell opens the
 *  item page, as the old row-wide button did; the selection
 *  checkbox and the actions are siblings of the open control. */
export function AssetRow({
  kind,
  item,
  onOpen,
  selection,
  lending,
  actions,
  badge,
}: {
  kind: "tool" | "battery";
  item: Tool | Battery;
  onOpen: () => void;
  selection?: { selected: boolean; onToggle: () => void; label?: string };
  lending?: RowLending | null;
  /** The item's Actions menu (the item page's ItemActionsMenu) —
   *  it replaced the row's lone Check out button (owner,
   *  2026-11-05). */
  actions?: ReactNode;
  /** Tool Expansion cart badge — a sibling of the open button,
   *  like the actions menu; absent when the item has no live
   *  suggestions or the module isn't effective. */
  badge?: ReactNode;
}) {
  const t = useT();
  const photo = item.attachments.find((a) => a.kind === "photo");
  const inactive = item.active === false;
  const total = extendedPrice(item);
  // Dealer/Brand column (owner, 2026-11-12): the brand and the
  // item's dealer tag (dealer_company_name — the linked dealer
  // company's name, resolved server-side; null when the item
  // carries no tag or the dealers module is off) share ONE
  // column: both when both are present, the one when only one
  // is, the standard "—" when neither is.
  const brandText = (item.brand || "").trim();
  const dealerText = (item.dealer_company_name || "").trim();
  const dealerBrandText = [brandText, dealerText].filter(Boolean).join(" · ");
  // F1-16: battery rows carry the battery's spec facts (deduped
  // chips as one line), the same facts its page headlines.
  const specLine =
    kind === "battery" ? batterySpecChips(item as Battery).join(" · ") : "";
  return (
    /* F1-12: a true list row — the parent .tv-inv-list supplies the
       shared surface + hairline separators; the row is not a card. */
    <div className={`tv-inv-row${inactive ? " is-inactive" : ""}`} role="row">
      {selection && (
        <div className="tv-inv-cell tv-inv-cell--select" role="cell">
          <Checkbox
            label={selection.label ?? "Select"}
            checked={selection.selected}
            onChange={selection.onToggle}
          />
        </div>
      )}
      <div className="tv-inv-cell tv-inv-cell--item tv-inv-fact" role="cell">
        <button
          type="button"
          onClick={onOpen}
          className="tv-open-btn tv-inv-open"
          aria-label={`Open ${item.name}`}
        >
          <ItemPhoto photo={photo} name={item.name} brand={item.brand} variant="row" />
          <span className="tv-inv-name-stack">
            <strong className="tv-inv-name" title={item.name}>
              {item.name}
            </strong>
            {(kind === "battery" || specLine) && (
              <span className="tv-inv-sub">
                {kind === "battery" ? "Battery" : ""}
                {specLine
                  ? `${kind === "battery" ? " · " : ""}${specLine}`
                  : ""}
              </span>
            )}
          </span>
        </button>
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--brand tv-inv-fact"
        role="cell"
        onClick={onOpen}
        title={dealerBrandText || undefined}
      >
        {/* The phone fold's labelled fact: the label is styled
            in surfaces.css to exist only in the ≤640px fold,
            where the header row is hidden. */}
        <span className="tv-inv-fact-label">
          {t("inventory.col.dealerBrand")}
        </span>
        {brandText || dealerText ? (
          <>
            <span className="tv-inv-brand-main">
              {brandText || dealerText}
            </span>
            {brandText && dealerText && (
              <span className="tv-inv-brand-sub">{dealerText}</span>
            )}
          </>
        ) : (
          "—"
        )}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--status tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        {inactive ? (
          <Badge tone="warning">Inactive</Badge>
        ) : (
          <StandingBadge standing={item.standing} />
        )}
        {/* Sweep B2-F6: an in-service row with no loan says so —
            "Available", the same pill the item header wears —
            instead of a blank cell that could mean anything. */}
        {!inactive && !lending && item.standing === "in_service" && (
          <Badge tone="success" dot>
            {t("inventory.status.available")}
          </Badge>
        )}
        {item.replaced_on && <Badge tone="neutral">Replaced</Badge>}
        {lending && (
          <span title={lending.title ?? lending.chip} className="tv-inv-status-pillwrap">
            <Badge tone={lending.tone} dot>
              {lending.chip}
            </Badge>
          </span>
        )}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--num tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        {item.quantity}
      </div>
      <div
        className="tv-inv-cell tv-inv-cell--num tv-inv-fact"
        role="cell"
        onClick={onOpen}
      >
        <strong>{money(String(total ?? 0))}</strong>
      </div>
      <div className="tv-inv-cell tv-inv-cell--actions" role="cell">
        {badge}
        {actions}
      </div>
    </div>
  );
}

