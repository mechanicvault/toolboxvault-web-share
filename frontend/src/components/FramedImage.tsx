interface FramedImageProps {
  src: string;
  /**
   * Accessibility text for the image. Must be meaningful text
   * (e.g. the tool's name) — NEVER a storage filename: alt text is
   * not a caption and must not leak internal file names into the UI.
   */
  alt: string;
  /** Aspect ratio like "4 / 3". Kept consistent across modules by default. */
  aspectRatio?: string;
  /**
   * Caption under the frame. Renders ONLY when a caller deliberately
   * passes one — it never defaults to the alt text.
   */
  caption?: string;
  /**
   * How the photo fills its frame (F1-05). "cover" (the historic
   * default) crops to fill — right only for deliberate editorial
   * crops. "contain" shows the WHOLE photo, letterboxed over a
   * blurred fill of itself so portrait/panorama records stay
   * recognisable instead of being sliced to a ribbon.
   */
  fit?: "cover" | "contain";
}

/**
 * The ONLY way modules render images with the standard look.
 * Sizing/framing rules live here once — modules never copy image styles.
 * Module-specific differences are explicit props, never forked copies.
 */
export function FramedImage({ src, alt, aspectRatio = "4 / 3", caption, fit = "cover" }: FramedImageProps) {
  const contain = fit === "contain";
  return (
    <figure className="tv-framed">
      <div
        className={`tv-framed-frame${contain ? " tv-framed-frame--contain" : ""}`}
        style={{ aspectRatio }}
      >
        {contain && (
          <span
            className="tv-framed-backdrop"
            style={{ backgroundImage: `url("${src.replace(/"/g, "%22")}")` }}
            aria-hidden="true"
          />
        )}
        <img src={src} alt={alt} />
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}
