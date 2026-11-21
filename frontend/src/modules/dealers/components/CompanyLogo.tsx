import { useState } from "react";
import type { DealerCompany } from "../types";

/**
 * The company's logo on a neutral tile (corporate directory,
 * 2026-10-19): the brand's official logo, contained — never
 * stretched, never a substitute. When the brand has no harvested
 * logo (or the stored file fails to load), the tile falls back to
 * the brand's initial as a clean text tile. Logos that are white
 * glyphs on transparency render on the dark tile variant.
 */
export function CompanyLogo({
  company,
  width = 132,
  height = 56,
}: {
  company: Pick<DealerCompany, "name" | "logo_url" | "logo_tile">;
  width?: number;
  height?: number;
}) {
  const [failed, setFailed] = useState(false);
  const dark = company.logo_tile === "dark";
  const showImage = Boolean(company.logo_url) && !failed;
  return (
    <div
      className={`tv-logo-tile${dark ? " tv-logo-tile--dark" : ""}`}
      style={{ width, height }}
      aria-hidden={!showImage}
    >
      {showImage ? (
        <img
          src={company.logo_url as string}
          alt={`${company.name} logo`}
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          className="tv-logo-tile-initial"
          style={{ fontSize: Math.round(height * 0.44) }}
        >
          {company.name.charAt(0).toUpperCase()}
        </span>
      )}
    </div>
  );
}
