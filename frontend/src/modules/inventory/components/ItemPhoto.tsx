import { FramedImage, ItemThumb } from "../../../components";
import type { Attachment } from "../types";

/**
 * An item's lead photo for inventory tiles and list rows (Round B,
 * F1-04/F1-05/F3-12):
 *  - WITH a photo: the WHOLE photo (contain over a blurred fill of
 *    itself), served from the size-appropriate rendition URL —
 *    320px for tiles, 128px for rows — never the full-size original.
 *  - WITHOUT (owner directive, 2026-11-02): the shared no-photo
 *    placeholder — the rendered toolbox artwork on its
 *    theme-aware plate, one central asset via ItemThumb (artwork
 *    replaced by sweep B2-F7) — in the same slot a photo would
 *    fill.
 *    Display-only: the item remains photo-less to every count,
 *    completeness check and claim-readiness warning.
 */
export function ItemPhoto({
  photo,
  name,
  variant,
}: {
  photo: Attachment | undefined;
  name: string;
  brand: string;
  variant: "tile" | "row";
}) {
  if (photo) {
    if (variant === "row") {
      return (
        <span className="tv-thumb-cell">
          <FramedImage
            src={photo.thumb_url_sm || photo.thumb_url || photo.url}
            alt={name}
            aspectRatio="4 / 3"
            fit="contain"
          />
        </span>
      );
    }
    return (
      <FramedImage
        src={photo.thumb_url || photo.url}
        alt={name}
        aspectRatio="16 / 9"
        fit="contain"
      />
    );
  }
  if (variant === "row") {
    return (
      <span className="tv-thumb-cell">
        <ItemThumb src={null} name={name} aspectRatio="4 / 3" />
      </span>
    );
  }
  return <ItemThumb src={null} name={name} aspectRatio="16 / 9" />;
}
