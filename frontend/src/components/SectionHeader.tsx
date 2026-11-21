export interface SectionHeaderProps {
  title: string;
}

/**
 * Section heading: stencil-caps label + a hairline rule that runs to
 * the right edge in the accent (the dashboard "SHOP OVERVIEW" pattern).
 * All color comes from tokens — Steel's accent + caps treatment is the
 * reference; other themes get the same structure in their own tokens.
 */
export function SectionHeader({ title }: SectionHeaderProps) {
  return (
    <div className="tv-section-header">
      <h2 className="tv-section-title">{title}</h2>
      <span className="tv-section-rule" aria-hidden="true" />
    </div>
  );
}
