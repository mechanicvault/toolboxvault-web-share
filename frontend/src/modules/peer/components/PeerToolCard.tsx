import { Badge, ItemThumb, Panel } from "../../../components";
import type { PeerItem } from "../types";

/**
 * One tool on someone's shared list: photo, name, brand/model,
 * category — and who owns it. Deliberately NO price: the
 * peer payload doesn't carry one. Click opens the detail view.
 *
 * Uniformity (owner rule, 2026-11-05): the shared tile skeleton
 * (surfaces.css .tv-tile-*) — reserved name / brand·model / chips
 * rows and the owner line pinned to the bottom, so a grid row of
 * shared tools aligns like a row of inventory tiles.
 */
export function PeerToolCard({
  item,
  showOwner = true,
  onOpen,
}: {
  item: PeerItem;
  showOwner?: boolean;
  onOpen: () => void;
}) {
  const photo = item.photos[0];
  return (
    <Panel className="tv-hoverable tv-peer-tile">
      <button
        onClick={onOpen}
          className="tv-open-btn tv-tile-open"
        style={{
          cursor: "pointer",
          width: "100%",
        }}
        aria-label={`View ${item.name}`}
      >
        <ItemThumb
          src={photo ?? null}
          name={item.name}
          aspectRatio="16 / 9"
          fit="cover"
        />
        <h3 className="tv-tile-name" title={item.name}>
          {item.name}
        </h3>
        <p className="tv-tile-sub" title={[item.brand, item.model].filter(Boolean).join(" · ") || undefined}>
          {[item.brand, item.model].filter(Boolean).join(" · ") || "—"}
        </p>
        <div className="tv-tile-chips" aria-hidden={item.kind !== "battery" && !item.is_set && !item.category}>
          {item.kind === "battery" && <Badge tone="accent">Battery</Badge>}
          {item.is_set && item.set && (
            <Badge tone="accent">
              Set · {item.set.core_pieces.length} core
              {item.set.include_addons &&
                ` + ${item.set.addon_pieces.length + item.set.attached_tools.length} addons`}
            </Badge>
          )}
          {item.category && <Badge tone="accent">{item.category}</Badge>}
        </div>
        {showOwner && (
          <p className="tv-tile-ownerline">
            {item.owner.name} · {item.owner.account_number}
          </p>
        )}
      </button>
    </Panel>
  );
}
