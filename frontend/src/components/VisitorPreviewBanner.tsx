import { useT } from "../i18n/LocaleContext";
import { ArtIcon } from "./ArtIcon";
import { Button } from "./Button";

/**
 * The "View as visitor" preview banner (Sweep D5, 2026-11-12):
 * while a page is previewed as a visitor, this slim strip
 * rides at the top of the page so the mode is unmistakable —
 * the site's own banner furniture (the construction strip's
 * family: icon, strong lead, quiet body, in normal flow) in
 * the accent tint, with the one way out labelled in words.
 * Shared by every surface that grows a visitor preview (the
 * print listing page and the dealer page today), so the mode
 * reads identically everywhere it exists.
 */
export function VisitorPreviewBanner({ onExit }: { onExit: () => void }) {
  const t = useT();
  return (
    <div className="tv-preview-banner" role="note" aria-label={t("preview.bannerTitle")}>
      <span className="tv-preview-banner-icon" aria-hidden="true">
        <ArtIcon name="search" size={20} />
      </span>
      <p className="tv-preview-banner-text">
        <strong>{t("preview.bannerTitle")}</strong>
        {` — ${t("preview.bannerBody")}`}
      </p>
      <Button size="sm" variant="secondary" onClick={onExit}>
        {t("preview.exit")}
      </Button>
    </div>
  );
}
