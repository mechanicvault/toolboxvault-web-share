import { useT } from "../i18n/LocaleContext";

/**
 * The footer's social row (owner order, 2026-11-07): one icon
 * link per social place the brand actually has — the five live
 * accounts from the registrations ledger, all @toolboxvault.
 * No Reddit (the brand name there was never verified and the
 * owner suspended Reddit outright, 2026-11-02) and no X (no
 * account exists): five links, no more, and a platform joins
 * this list only when a real account stands behind it.
 *
 * The marks are the platforms' own recognizable glyphs, drawn
 * as inline SVG in this file — the teaser player's inline-glyph
 * precedent. They deliberately do NOT live in ArtIcon: that
 * library's charter is the site's own hand-drawn artwork for
 * things the site depicts ("nothing here is a copied brand
 * asset"), and a platform's mark is that platform's asset, not
 * a site concept. They ride the ONE shared shell footer
 * (AppShell), so the row stands at the bottom of every page
 * the shell closes — signed in and signed out alike, the
 * teaser front door and /downloads included since the
 * footer-unification order (owner, 2026-11-07) put that same
 * footer on the bare doors too. Each link opens its platform
 * in a new tab.
 *
 * COLOUR (owner order, 2026-11-08): each mark wears its own
 * brand colours instead of the footer's one-colour ink —
 * Facebook's blue, Instagram's gradient sweep, YouTube's red
 * with the white play triangle, TikTok's cyan/magenta channel
 * split around a theme-ink note. Threads is the exception
 * that proves the rule: its brand IS monochrome, so its glyph
 * keeps riding currentColor — the seat's ink token, dark on
 * light surfaces and light on dark ones, which is exactly
 * Threads' own black-on-light / white-on-dark treatment.
 * Shapes, sizes, seats, links and labels are untouched.
 */

function FacebookGlyph() {
  return (
    <svg viewBox="0 0 320 512" aria-hidden="true" focusable="false">
      <path
        fill="#1877F2"
        d="M279.14 288l14.22-92.66h-88.91v-60.13c0-25.35 12.42-50.06 52.24-50.06h30.42V6.26S260.43 0 225.36 0c-73.22 0-121.08 44.38-121.08 124.72v70.62H22.89V288h81.39v224h100.17V288z"
      />
    </svg>
  );
}

/** The one Facebook address, exported for the surfaces that
 *  point at the page outside this row — the teaser's
 *  "check our Facebook page for more updates" invitation
 *  (owner order, 2026-11-09) reads it from here so the site
 *  carries exactly one spelling of the link. */
export const FACEBOOK_URL = "https://facebook.com/toolboxvault";
export { FacebookGlyph };

function InstagramGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="url(#tv-ig-gradient)"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id="tv-ig-gradient"
          x1="0"
          y1="1"
          x2="1"
          y2="0"
        >
          <stop offset="0" stopColor="#FFD600" />
          <stop offset="0.3" stopColor="#FF7A00" />
          <stop offset="0.55" stopColor="#FF0069" />
          <stop offset="0.8" stopColor="#D300C5" />
          <stop offset="1" stopColor="#7638FA" />
        </linearGradient>
      </defs>
      <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" />
      <circle cx="12" cy="12" r="4.25" />
      <circle cx="17.35" cy="6.65" r="1.1" fill="url(#tv-ig-gradient)" stroke="none" />
    </svg>
  );
}

/* Threads stays on currentColor on purpose: the brand mark
 * is monochrome — black on light surfaces, white on dark —
 * and the seat's ink token already resolves exactly that
 * way per theme (see the COLOUR note at the top). */
function ThreadsGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M17.43 18.47A8.45 8.45 0 1 1 18.92 7.15" />
      <circle cx="11.4" cy="12.1" r="2.85" />
      <path d="M14.25 9.25v5.35c0 2.3 1.35 3.7 3.35 3.7 1.4 0 2.5-.6 3.15-1.6" />
    </svg>
  );
}

function TikTokGlyph() {
  /* The duotone channel split: the note drawn three times —
   * cyan shifted one way, magenta-red the other, and the
   * note itself on top in the seat's ink (currentColor), so
   * the mark reads on dark and light footers alike (a pure
   * black note would vanish on the dark one). */
  const note =
    "M16.55 3.1c.42 2.05 1.83 3.52 3.85 3.83v3.03c-1.55 0-3.02-.5-4.24-1.34v6.68c0 3.36-2.62 5.86-5.94 5.86A5.82 5.82 0 0 1 4.4 17.3c0-3.3 2.68-5.9 6-5.9.35 0 .7.03 1.04.09v3.13a2.86 2.86 0 0 0-1.04-.19 2.72 2.72 0 0 0-2.72 2.72c0 1.5 1.22 2.72 2.73 2.72 1.54 0 2.75-1.2 2.75-2.78V3.1h3.39z";
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path fill="#25F4EE" transform="translate(-0.65 0.45)" d={note} />
      <path fill="#FE2C55" transform="translate(0.65 -0.45)" d={note} />
      <path fill="currentColor" d={note} />
    </svg>
  );
}

function YouTubeGlyph() {
  /* One path split in two along its own seams: the rounded
   * body in YouTube red, the play triangle (the even-odd
   * cut-out of the single-path drawing) in white on top. */
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        fill="#FF0000"
        d="M5.75 4.9h12.5a3.6 3.6 0 0 1 3.6 3.6v7a3.6 3.6 0 0 1-3.6 3.6H5.75a3.6 3.6 0 0 1-3.6-3.6v-7a3.6 3.6 0 0 1 3.6-3.6z"
      />
      <path
        fill="#FFFFFF"
        d="M10 9.3v5.4c0 .45.5.73.88.48l4.3-2.7a.58.58 0 0 0 0-.96l-4.3-2.7A.58.58 0 0 0 10 9.3z"
      />
    </svg>
  );
}

const SOCIALS = [
  {
    id: "facebook",
    href: FACEBOOK_URL,
    labelKey: "shell.social.facebook",
    Glyph: FacebookGlyph,
  },
  {
    id: "instagram",
    href: "https://instagram.com/toolboxvault",
    labelKey: "shell.social.instagram",
    Glyph: InstagramGlyph,
  },
  {
    id: "threads",
    href: "https://threads.com/@toolboxvault",
    labelKey: "shell.social.threads",
    Glyph: ThreadsGlyph,
  },
  {
    id: "tiktok",
    href: "https://tiktok.com/@toolboxvault",
    labelKey: "shell.social.tiktok",
    Glyph: TikTokGlyph,
  },
  {
    id: "youtube",
    href: "https://youtube.com/@toolboxvault",
    labelKey: "shell.social.youtube",
    Glyph: YouTubeGlyph,
  },
] as const;

/** The social icon row: five uniform seats, platform order
 *  Facebook · Instagram · Threads · TikTok · YouTube. Rendered
 *  by the AppShell footer — the shared component is the whole
 *  point (see the header note). */
export function SocialLinks() {
  const t = useT();
  return (
    <nav className="tv-footer-social" aria-label={t("shell.social.label")}>
      {SOCIALS.map(({ id, href, labelKey, Glyph }) => (
        <a
          key={id}
          className="tv-social-link"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t(labelKey as never)}
        >
          <Glyph />
        </a>
      ))}
    </nav>
  );
}
