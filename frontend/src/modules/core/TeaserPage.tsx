import { useEffect, useRef, useState } from "react";
import {
  FACEBOOK_URL,
  FacebookGlyph,
  LinkButton,
  SpinningEmblem,
} from "../../components";
import { LocaleSwitcher } from "../../i18n/LocaleSwitcher";
import { useLocale, useT } from "../../i18n/LocaleContext";
import { api } from "../../lib/api";
import { useTeaser } from "./teaser";
import "./teaser.css";

/**
 * TEASER PAGE (owner order, 2026-10-26; doomsday refinement the
 * same day; owner correction the same evening) — the public
 * front door until launch. Content discipline is the whole
 * point: the ORIGINAL center lockup — the logo coin (the
 * spinning octagon emblem) at hero scale with the wordmark and
 * the slogan, no corner plates — one headline, the identity
 * line, a DOOMSDAY countdown staged like a launch sequence on
 * a full-bleed brushed band, the current teaser trailer when
 * the operator has set one, and exactly two doors (Log in /
 * Create account). No feature names, no module cards, no tour,
 * no directory links — the drama is all presentation; the page
 * gives away NOTHING of what sits behind it.
 *
 * App links (owner, 2026-10-31): the doors now carry ONE
 * deliberate exception — a slim row of direct app-store links
 * under them, so a visitor on a phone can tap straight to the
 * (already live) apps. The links are the merged landing's own:
 * the same operator-set URLs, the same secondary-button dress,
 * the same labels, hidden when the settings carry no URL. The
 * row sits BELOW the doors in flow, so the countdown band and
 * the doors keep their proven first-viewport seats exactly.
 *
 * Downloads door (owner, 2026-11-08): a SECOND deliberate
 * exception, ordered the night the Downloads section went
 * public — a "Free Downloads" door at door scale in the
 * secondary dress, in its own row directly under the two
 * doors, so a visitor who lands on the teaser can reach the
 * free Downloads page without an account (that page has been
 * an open path behind the wall since 2026-10-29; this is
 * simply its door on the front page). Like the app links it
 * rides BELOW the doors in flow — the countdown band and the
 * two doors keep their proven seats, and nothing else on the
 * page changes.
 *
 * Facebook invitation (owner, 2026-11-09): a THIRD deliberate
 * exception — a quiet line directly under the Downloads door
 * inviting the visitor to check the Facebook page for more
 * updates, the Facebook name carrying the link. The footer's
 * social icons already point there; the owner wants the
 * explicit invitation read in the flow, not just the icon
 * row. The address is the SocialLinks constant, so the site
 * spells it once.
 *
 * Layout refinement (owner, 2026-10-26 evening): the language
 * picker moved from its floated top-right row to the BOTTOM of
 * the page — the last element — and the whole composition was
 * raised into the reclaimed space, so the countdown band sits
 * fully inside the landing viewport at common sizes (proven at
 * 390×740, 402×860, 1440×800, 1440×900; see teaser.css).
 *
 * The evening's redesign briefly floated the header's brand
 * plate at the top-left instead; the owner struck it the same
 * night ("the same as it was, but a spinning logo where the
 * stagnant logo was"). The lockup below is the original build's
 * composition restored, and teaser.css carries the fix that
 * makes the coin's spin unmistakable (see the spin note there).
 */

/** The release instant: Tuesday, December 1, 2026, 12:00 noon
 *  Central, written as an absolute UTC instant so the countdown
 *  reads correctly for a visitor in any timezone. At zero the
 *  numbers rest at zero and the line flips to its launch-day
 *  state — nothing opens by itself; the owner retires the teaser
 *  from Admin → Settings when he is ready. */
const RELEASE_UTC_MS = Date.parse("2026-12-01T18:00:00Z");

function countdownParts(remainingMs: number) {
  const totalSeconds = Math.floor(remainingMs / 1000);
  return {
    days: Math.floor(totalSeconds / 86_400),
    hours: Math.floor((totalSeconds % 86_400) / 3_600),
    minutes: Math.floor((totalSeconds % 3_600) / 60),
    seconds: totalSeconds % 60,
  };
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/* -- The player's one icon: a Lucide-style fullscreen glyph
 *    (2px stroke, light gray), drawn inline so it needs no icon
 *    font and no extra requests. */
function FullscreenGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
      <path d="M3 16v3a2 2 0 0 0 2 2h3" />
      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
    </svg>
  );
}

/* Fullscreen capability helpers (2026-10-31 iPhone repair).
 * fsElement reads the standard property, falling back to
 * desktop Safari's prefixed one. enterVideoFullscreen is the
 * iPhone door: the video element's own native fullscreen —
 * the only fullscreen iPhone Safari has. */
type FsDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => void;
};
type WebkitVideo = HTMLVideoElement & {
  webkitEnterFullscreen?: () => void;
};

function fsElement(): Element | null {
  return (
    document.fullscreenElement ??
    (document as FsDocument).webkitFullscreenElement ??
    null
  );
}

function enterVideoFullscreen(v: HTMLVideoElement | null): void {
  (v as WebkitVideo | null)?.webkitEnterFullscreen?.();
}

/**
 * The teaser-trailer player (owner reversal, 2026-10-26
 * 23:13): NO visible controls but ONE — a fullscreen button
 * seated bottom-right of the frame. The full custom bar
 * (play/pause, seek, volume) and the big center toggle built
 * earlier the same evening are gone at the owner's word: the
 * trailer is an attract loop, not a deck.
 *
 * Behavior law: the video runs muted on autoplay-loop, poster
 * first, and nothing on it pauses, scrubs or adjusts — there
 * is no affordance to. The one button toggles fullscreen on
 * the whole player element. Sound rides that state: ENTERING
 * fullscreen unmutes (it is the only way a visitor hears the
 * trailer's audio); LEAVING it — by the button or by Esc —
 * returns the video to the muted attract. The button lives
 * inside the player, so it stays visible while fullscreen.
 *
 * iPhone repair (2026-10-31, owner's phone): iPhone Safari
 * has NO element Fullscreen API — requestFullscreen on the
 * player silently did nothing there, and its fullscreen is
 * announced on the video element (webkitbeginfullscreen /
 * webkitendfullscreen), never as document fullscreenchange,
 * so the sound wiring never fired either: dead button, no
 * sound, ever. The button now falls back to the video's own
 * native fullscreen (webkitEnterFullscreen) where the
 * standard API is missing or refuses, and the sound law
 * listens to both event families. Design unchanged.
 */
function TeaserVideoPlayer({
  src,
  poster,
  label,
}: {
  src: string;
  poster: string;
  label: string;
}) {
  const t = useT();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [muted, setMuted] = useState(true);

  /* React's muted attribute alone doesn't reliably set the
   * property, and the property is what autoplay + sound read —
   * keep both in sync from state. Unmuting also raises the
   * volume property, so the loud state is fully loud. */
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = muted;
    if (!muted) v.volume = 1;
  }, [muted]);

  /* Fullscreen is the loud state (see the behavior law above):
   * the change events — not the click — drive the sound, so an
   * Esc exit lands in the same muted state as a button exit.
   * Two event families, because iPhone Safari never fires the
   * standard one: its fullscreen is announced on the VIDEO
   * element as webkitbeginfullscreen / webkitendfullscreen
   * (desktop Safari's prefixed document event is covered too). */
  useEffect(() => {
    const v = videoRef.current;
    const onFsChange = () => {
      setMuted(fsElement() !== wrapRef.current);
    };
    const onVideoBegin = () => setMuted(false);
    const onVideoEnd = () => setMuted(true);
    document.addEventListener("fullscreenchange", onFsChange);
    document.addEventListener("webkitfullscreenchange", onFsChange);
    v?.addEventListener("webkitbeginfullscreen", onVideoBegin);
    v?.addEventListener("webkitendfullscreen", onVideoEnd);
    return () => {
      document.removeEventListener("fullscreenchange", onFsChange);
      document.removeEventListener("webkitfullscreenchange", onFsChange);
      v?.removeEventListener("webkitbeginfullscreen", onVideoBegin);
      v?.removeEventListener("webkitendfullscreen", onVideoEnd);
    };
  }, []);

  const toggleFullscreen = () => {
    const w = wrapRef.current;
    if (!w) return;
    if (fsElement()) {
      if (typeof document.exitFullscreen === "function") {
        void document.exitFullscreen();
      } else {
        (document as FsDocument).webkitExitFullscreen?.();
      }
      return;
    }
    if (typeof w.requestFullscreen === "function") {
      /* Standard path (desktop/Android): fullscreen the whole
       * player, so the button stays visible inside it. A
       * browser that offers the API but refuses the call falls
       * back to the video's own fullscreen. */
      try {
        const p = w.requestFullscreen();
        if (p && typeof p.catch === "function") {
          p.catch(() => enterVideoFullscreen(videoRef.current));
        }
      } catch {
        enterVideoFullscreen(videoRef.current);
      }
    } else {
      /* iPhone Safari: no element fullscreen — the video's own
       * native fullscreen is the only door, called
       * synchronously from the click as iOS expects. */
      enterVideoFullscreen(videoRef.current);
    }
  };

  return (
    <div className="tv-teaser-player" ref={wrapRef}>
      <div className="tv-teaser-videowrap">
        <video
          ref={videoRef}
          className="tv-teaser-video"
          src={src}
          poster={poster || undefined}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          aria-label={label}
        />
        <button
          type="button"
          className="tv-teaser-fsbtn"
          onClick={toggleFullscreen}
          aria-label={t("teaser.fullscreen")}
        >
          <FullscreenGlyph />
        </button>
      </div>
    </div>
  );
}

/** The poster frame the trailer wears before it plays (sweep
 *  fix 10-F14): a CLEAN in-repo frame — the teaser's own stage
 *  art — instead of the operator poster's captured frame. The
 *  admin upload flow captures the poster FROM the trailer in
 *  the browser, and the current trailer's captured frame shows
 *  an in-scene countdown reading "30 DAYS" — a stale promise
 *  that contradicted the live countdown directly above it
 *  (20 days when the sweep caught it, shrinking daily). The
 *  baked-in figure lives inside the trailer's own artwork and
 *  cannot be corrected in code, so the page no longer presents
 *  that frame as its poster; the trailer itself still plays
 *  exactly as set. If a future trailer's poster carries no
 *  baked countdown, restoring the operator poster is the
 *  one-line change back to `poster={posterUrl}` below. */
const TEASER_CLEAN_POSTER = "/landing/hero-workbench.webp";

/** The brand-only hold shown on the signed-out root while the
 *  public posture is still being read: the spinning emblem on
 *  the steel ground, nothing else — neither the landing's
 *  features nor the teaser itself may flash in wrong. */
export function TeaserSplash() {
  return (
    <div className="tv-teaser tv-teaser--splash">
      <span className="tv-teaser-emblem tv-teaser-emblem--splash" aria-hidden="true">
        <SpinningEmblem />
      </span>
    </div>
  );
}

export default function TeaserPage() {
  const t = useT();
  const { locale } = useLocale();
  const { videoUrl, appStoreUrl, playStoreUrl } = useTeaser();
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  /* The visitor counter (owner order, 2026-10-26): one call on
   * load; the server decides whether THIS browser counts (its
   * rules live in core/teaser.py) and answers with the unique-
   * visitor count, rendered below as bare digits — no words, no
   * label. Until a real number arrives nothing renders, and a
   * failed call renders nothing either: the counter is a quiet
   * detail, never a broken "0" and never a blocker. */
  const [visitors, setVisitors] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    api<{ count: number }>("/core/visit", { method: "POST" })
      .then((res) => {
        if (live) setVisitors(res.count);
      })
      .catch(() => {
        /* decoration only — silence is the failure state */
      });
    return () => {
      live = false;
    };
  }, []);
  const remainingMs = Math.max(0, RELEASE_UTC_MS - nowMs);
  const launched = remainingMs <= 0;
  const parts = countdownParts(remainingMs);
  const units: Array<{ value: string; label: string; hot?: boolean }> = [
    { value: String(parts.days), label: t("teaser.days") },
    { value: pad2(parts.hours), label: t("teaser.hours") },
    { value: pad2(parts.minutes), label: t("teaser.minutes") },
    { value: pad2(parts.seconds), label: t("teaser.seconds"), hot: true },
  ];
  return (
    <div className="tv-teaser">
      {/* No top row (owner, 2026-10-26 evening): the language
          picker that floated here moved to the bottom of the
          page, and the composition starts with the stage — the
          brand lives in the center lockup below, exactly as
          the original build had it. */}
      <section className="tv-teaser-stage">
        <div className="tv-teaser-art" aria-hidden="true">
          <img src="/landing/hero-workbench.webp" alt="" />
        </div>
        <div className="tv-teaser-lockup">
          {/* The center lockup, restored (owner correction,
              2026-10-26 evening): a logo coin with text, no
              corner plates — the SPINNING emblem at hero scale,
              the wordmark under it, the slogan under that, all
              sitting directly on the stage. The evening's
              floating top-left brand plate is gone. The coin
              must VISIBLY spin: teaser.css gives this emblem
              its own brisker turn and exempts it, on this
              surface only, from the reduced-motion stand-down
              that could freeze it solid (see the spin note in
              teaser.css). */}
          <span
            className="tv-teaser-emblem"
            role="img"
            aria-label={t("landing.merged.logoAlt")}
          >
            <SpinningEmblem />
          </span>
          <img
            className="tv-teaser-wordmark"
            src="/brand/wordmark-840.webp"
            alt="Toolbox Vault"
            width={840}
            height={150}
          />
          {/* The brand slogan is a literal mark, as on the merged
              landing — it does not translate. */}
          <p className="tv-teaser-slogan">ORGANIZE. PROTECT. RECOVER.</p>
          <h1 className="tv-teaser-headline">{t("teaser.headline")}</h1>
          <p className="tv-teaser-identity">{t("landing.tagline")}</p>
        </div>
      </section>
      {/* The countdown band: full-bleed brushed steel, the
          doomsday die as the page's centerpiece. The block's
          orange under-glow (the radial accent bloom) is the
          .tv-teaser-countblock rule in teaser.css. */}
      <section className="tv-teaser-band">
        {launched ? (
          <p className="tv-teaser-launched">{t("teaser.launched")}</p>
        ) : (
          <div className="tv-teaser-countblock">
            <p className="tv-teaser-countlabel">{t("teaser.opensIn")}</p>
            <div className="tv-teaser-count" role="timer">
              {units.map((unit) => (
                <div key={unit.label} className="tv-teaser-unit">
                  <span
                    className={
                      unit.hot
                        ? "tv-teaser-num tv-teaser-num--hot"
                        : "tv-teaser-num"
                    }
                  >
                    {unit.value}
                  </span>
                  <span className="tv-teaser-unitlabel">{unit.label}</span>
                </div>
              ))}
            </div>
            <p className="tv-teaser-date">{t("teaser.date")}</p>
          </div>
        )}
      </section>
      <div className="tv-teaser-doors">
        <LinkButton to="/login" size="lg">
          {t("landing.hero.login")}
        </LinkButton>
        <LinkButton to="/signup" size="lg" variant="secondary">
          {t("teaser.create")}
        </LinkButton>
      </div>
      {/* The Downloads door (owner, 2026-11-08): one door-scale
          button in its own row directly under the two doors —
          the free Downloads page is public by design (an open
          path behind the wall since 2026-10-29), and this is
          its door on the front page. Secondary dress, like
          Create account; Log in keeps the only primary. It
          rides below the doors in flow, so the band and the
          doors keep their seats (the app-links pattern). */}
      <div className="tv-teaser-downloads">
        <LinkButton to="/downloads" size="lg" variant="secondary">
          {t("teaser.downloads")}
        </LinkButton>
      </div>
      {/* The Facebook invitation (owner, 2026-11-09): one quiet
          line in its own row directly under the Downloads door —
          the Facebook glyph in the platform's blue beside the
          invitation text, the whole line the link, opening the
          page in a new tab exactly as the footer's social links
          open. The address is the SocialLinks constant
          (FACEBOOK_URL), so the site spells it once. It rides
          below the doors in flow like the other exceptions, so
          the band and the doors keep their seats. */}
      <div className="tv-teaser-facebook">
        <a
          className="tv-teaser-facebook-link"
          href={FACEBOOK_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          <FacebookGlyph />
          <span>{t("teaser.facebookUpdates")}</span>
        </a>
      </div>
      {/* The app links (owner, 2026-10-31): a slim row directly
          under the doors — the merged landing's store block in
          miniature. Same operator-set URLs (via the teaser
          state, from the one shared landing config), same
          secondary-button dress, same bilingual labels; a store
          renders only while its URL is set, and no URLs at all
          means no row. External by design: these are the apps'
          store doors, not site doors. */}
      {(appStoreUrl.trim() || playStoreUrl.trim()) && (
        <section
          aria-label={t("landing.merged.storeLabel")}
          className="tv-teaser-stores"
        >
          <div className="tv-teaser-stores-row">
            {appStoreUrl.trim() && (
              <a
                className="tv-btn tv-btn--secondary tv-teaser-store-link"
                href={appStoreUrl.trim()}
                target="_blank"
                rel="noreferrer"
              >
                {t("landing.store.appStore")}
              </a>
            )}
            {playStoreUrl.trim() && (
              <a
                className="tv-btn tv-btn--secondary tv-teaser-store-link"
                href={playStoreUrl.trim()}
                target="_blank"
                rel="noreferrer"
              >
                {t("landing.store.googlePlay")}
              </a>
            )}
          </div>
        </section>
      )}
      {/* The current teaser trailer — ONLY when the operator
          has set one (Admin → Settings). No video set = no slot
          at all: no empty frame, no placeholder. The file is
          hosted on the site itself (never an external embed),
          poster first so the plate looks composed before a
          frame loads, and nothing here blocks the countdown or
          the doors. Playback wears NO controls but one
          fullscreen button (see TeaserVideoPlayer) — the
          owner's reversal of the full control bar, the same
          evening it was built. */}
      {videoUrl && (
        <section className="tv-teaser-videoslot">
          <h2 className="tv-teaser-trailer">{t("teaser.trailer")}</h2>
          <div className="tv-teaser-video-frame">
            <TeaserVideoPlayer
              src={videoUrl}
              poster={TEASER_CLEAN_POSTER}
              label={t("teaser.video")}
            />
          </div>
        </section>
      )}
      {/* The language picker closes the page (owner, 2026-10-26
          evening): same switcher, same job, last element on the
          page — below the doors, and below the trailer when one
          is set. Its top-right row is gone; the composition
          above was raised into that space. The visitor counter
          (owner, later the same evening) shares this row: bare
          digits at its left end, no words, no row of its own —
          and nothing at all until the count has arrived. */}
      <div className="tv-teaser-bottom">
        {visitors !== null && (
          <span className="tv-teaser-visitors" aria-hidden="true">
            {new Intl.NumberFormat(locale).format(visitors)}
          </span>
        )}
        <LocaleSwitcher id="locale-switcher-teaser" />
      </div>
    </div>
  );
}
