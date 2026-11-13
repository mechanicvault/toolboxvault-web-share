import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { BrandIcon, Panel, SectionHeader, type BrandIconName, LinkButton } from "../../components";
import { ACCOUNT_TYPE_OPTIONS } from "./accountTypes";
import { fetchLandingConfig, LANDING_FALLBACK, type LandingConfig } from "./landing";

import "./landing.css";
import { useT } from "../../i18n/LocaleContext";

/**
 * The public landing page (landing build, 2026-10-20; Ryan spec
 * 2026-10-20 08:20 + 08:21): what a signed-out visitor gets at
 * "/" — a page that SELLS the site. Signed-in users never see
 * it (HomePage routes them to CorePage untouched).
 *
 * Honesty rules (core/landing.py owns the values): every price,
 * the trial block, and the app-store block come from operator
 * settings and render ONLY while the settings say they exist —
 * no invented numbers, no fake testimonials, no store links
 * that aren't real. Backup copy says "automatic daily backups
 * with restore points" — the offsite/encrypted leg is NOT
 * claimed until it is live.
 *
 * Visual pass (2026-10-20): presentation only — a cinematic
 * hero band the lockup mounts over, glossy brand-icon
 * medallions on the ability tiles, a "See the real thing" band
 * of REAL product screens (captured from a staged demo account,
 * labeled as sample data), and a photo header on each
 * who-it's-for card. All artwork is self-hosted WebP under
 * /landing/ (provenance: mobile-repro/landing-visual/INDEX.md);
 * the landing-scoped styles live in ./landing.css — no theme
 * files, no shared component rules changed.
 *
 * Rail Steel Phase 4 (2026-10-24): the page is translated into
 * the Rail Steel design language — hero brand-plate composition
 * (logo verbatim in a recess well, wordmark on the chrome
 * nameplate, stencil display slogan), framed metal tiles, and
 * pricing as screwed plan boxes — via ./landing.css classes
 * only. Content, order, links, and the admin-driven landing
 * config are unchanged; every former inline style moved to a
 * landing.css class in the same pass (ratchet).
 */

const ABILITIES: { title: string; body: string; icon: BrandIconName }[] = [
  {
    title: "Inventory",
    icon: "layers",
    body: "Every tool with its photos, serial numbers, model numbers, and receipts. Sets stay together, locations nest like your real drawers and bins, and search finds any of it in seconds.",
  },
  {
    title: "Insurance-ready documentation",
    icon: "shield-check",
    body: "Values, serials, and photos organized the way a claim needs them — a full inventory packet for your insurer is a few clicks, not a weekend of digging.",
  },
  {
    title: "Guided claims",
    icon: "check-badge",
    body: "When something is lost, stolen, or damaged, a step-by-step claim flow walks you through it — police report details, deadlines, and evidence pulled straight from your inventory.",
  },
  {
    title: "Repair & service history",
    icon: "refresh",
    body: "A tool's life story: purchased, repaired, warranty work, lent out, claimed, replaced — dated and on the record, forever.",
  },
  {
    title: "Dealer network",
    icon: "search",
    body: "Find your tool-truck agents, keep your preferred reps a tap away, and send a broken tool straight to your dealer to get the warranty process rolling.",
  },
  {
    title: "Reports",
    icon: "chart-up",
    body: "Insurance packets, valuations, tax-year summaries, and shop reports — on screen, as a PDF, or emailed, all built from the same records.",
  },
  {
    title: "Sharing",
    icon: "share-nodes",
    body: "Share your list with your shop or your insurer — you pick exactly which fields they see — and lend or borrow with people you trust, with a paper trail.",
  },
  {
    title: "Community",
    icon: "chat-green",
    body: "A community parts pool searchable by year, make, model, and engine; a tools-for-sale board with seller reputations; and a forum of people who turn the same wrenches.",
  },
  {
    title: "Backups & restore",
    icon: "cloud-upload",
    body: "Automatic daily backups with restore points: undo a bad edit, bring back a deleted tool with its photos, or export everything you own at any time.",
  },
];

/** One-paragraph pitch per account group (the picker's one-liner
 *  in accountTypes.ts is the signup surface's; these are the
 *  landing page's longer sell, keyed by group value). */
const GROUP_PITCHES: Record<string, string> = {
  mechanic_technician:
    "Your tools are your livelihood — often tens of thousands of dollars riding in one box. Toolbox Vault keeps the proof: what you own, what it's worth, and everything that ever happened to it, ready for the day something walks off or breaks.",
  shop_company:
    "See the whole shop's tools in one place: who has what, what's checked out, what's broken, and what's due for service — with crew accounts that stay portable when people move on.",
  tool_dealer:
    "Your customers, your territory, and your truck accounts in one dashboard. Hear about a broken tool the moment it breaks, and let customers find you by the area you actually cover.",
  insurance:
    "When a claim lands, the documentation is already in order — itemized inventories with photos, serials, and values that your policyholders maintain themselves, shared with you only with their permission.",
};

/** The "See the real thing" band: genuine product screens,
 *  captured in the Steel theme from a staged demo account (the
 *  toolbox shown is sample data — the UI is 100% the real
 *  product). Static WebPs under /landing/. */
const SHOTS: { src: string; alt: string; title: string; body: string }[] = [
  {
    src: "/landing/shot-dashboard.webp",
    alt: "Toolbox Vault home dashboard showing shop totals, checkouts, and open claims",
    title: "The home dashboard",
    body: "Value, checkouts, repairs, and open claims — the whole shop's morning snapshot.",
  },
  {
    src: "/landing/shot-inventory.webp",
    alt: "Inventory list with tool photos, brands, and values",
    title: "Inventory",
    body: "Every tool on the record with its photo, value, and where it lives.",
  },
  {
    src: "/landing/shot-history.webp",
    alt: "A torque wrench's detail page with its History timeline of purchases, repairs, and a claim",
    title: "A tool's life story",
    body: "Purchased, repaired, warranty work, lent out, claimed — dated and on the record.",
  },
  {
    src: "/landing/shot-find-agent.webp",
    alt: "Find an Agent results for a ZIP code, listing dealer agents with drawn territories",
    title: "Find an Agent",
    body: "Agents whose hand-drawn territory covers your ZIP — every one of them, never just one.",
  },
];

/** Photo header per account group (generated imagery,
 *  self-hosted — provenance in the landing-visual INDEX). */
const GROUP_PHOTOS: Record<string, { src: string; alt: string }> = {
  mechanic_technician: {
    src: "/landing/group-mechanic.webp",
    alt: "A mechanic standing in front of his red tool cabinet",
  },
  shop_company: {
    src: "/landing/group-shop.webp",
    alt: "Three mechanics working together under a truck on a lift",
  },
  tool_dealer: {
    src: "/landing/group-dealer.webp",
    alt: "A tool truck dealer beside his open truck, shelves of tools inside",
  },
  insurance: {
    src: "/landing/insurance-record.webp",
    alt: "A documented tool record with photos and values, ready for an insurance claim",
  },
};

const PROOF_LINKS: { title: string; body: string; path: string; cta: string }[] = [
  {
    title: "Find an agent",
    body: "Search the dealer network by the area you work in — every listed agent whose territory covers you, no account needed to look.",
    path: "/dealers/find-agent",
    cta: "Find an agent",
  },
  {
    title: "Dealer directory",
    body: "The big brands' warranty lines, service addresses, and your local reps — the directory is public, copy any number in one tap.",
    path: "/dealers",
    cta: "Browse the directory",
  },
  {
    title: "Tools for sale",
    body: "The community board: tools for sale and wanted, from sellers with real reputations built on completed deals.",
    path: "/marketplace",
    cta: "See the board",
  },
  {
    title: "Community Forum",
    body: "Mechanics talking shop — repairs, finds, and hard-won lessons. Read it all free; posting is for members.",
    path: "/forum",
    cta: "Read the forum",
  },
];

function priceLine(amount: string, per: string): string {
  return amount.trim() ? `$${amount.trim()} ${per}` : "";
}

export default function LandingPage() {
  const t = useT();
  const [config, setConfig] = useState<LandingConfig>(LANDING_FALLBACK);

  useEffect(() => {
    let live = true;
    void fetchLandingConfig().then((loaded) => {
      if (live) setConfig(loaded);
    });
    return () => {
      live = false;
    };
  }, []);

  const proMonthly = priceLine(config.pro_monthly_price, "/ month");
  const proYearly = priceLine(config.pro_yearly_price, "/ year");
  const bizMonthly = priceLine(config.business_monthly_price, "/ month base");
  const bizYearly = priceLine(config.business_yearly_price, "/ year base");
  const showStores = Boolean(config.app_store_url.trim() || config.play_store_url.trim());
  const showTrial = config.self_serve_trial_enabled;

  return (
    <div className="tv-landing-root">
      {/* -- Hero ------------------------------------------------ */}
      <section aria-label="Toolbox Vault" className="tv-landing-hero">
        <div className="tv-landing-hero-art" aria-hidden="true">
          <img src="/landing/hero-workbench.webp" alt="" width={1920} height={823} fetchPriority="high" />
        </div>
        <div className="tv-landing-lockup">
        <img
          className="tv-landing-logo"
          src="/brand/logo-256.webp"
          alt="Toolbox Vault logo"
          width={256}
          height={256}
        />
        <img
          className="tv-landing-wordmark"
          src="/brand/wordmark-840.webp"
          alt="Toolbox Vault"
          width={840}
          height={124}
        />
        <p className="tv-landing-slogan">
          ORGANIZE. PROTECT. RECOVER.
        </p>
        <p className="tv-landing-tagline">
          {t("landing.tagline")}
        </p>
        <p className="tv-landing-herobody">
          {t("landing.hero.body")}
        </p>
        <div className="tv-landing-ctas">
          <LinkButton to="/signup" size="lg">{t("landing.hero.cta")}</LinkButton>
          <LinkButton to="/login" size="lg" variant="secondary">{t("landing.hero.login")}</LinkButton>
        </div>
        <p className="tv-landing-free">
          {t("landing.hero.freeBefore")} {config.free_item_limit} {t("landing.hero.freeAfter")}
        </p>
        </div>
      </section>

      {/* -- App stores (settings-gated: hidden until real URLs) - */}
      {showStores && (
        <section aria-label="Get the app" className="tv-landing-stores">
          <div className="tv-landing-stores-row">
            {config.app_store_url.trim() && (
              <a
                className="tv-btn tv-btn--secondary tv-landing-store-link"
                href={config.app_store_url.trim()}
                target="_blank"
                rel="noreferrer"
              >
                {t("landing.store.appStore")}
              </a>
            )}
            {config.play_store_url.trim() && (
              <a
                className="tv-btn tv-btn--secondary tv-landing-store-link"
                href={config.play_store_url.trim()}
                target="_blank"
                rel="noreferrer"
              >
                {t("landing.store.googlePlay")}
              </a>
            )}
          </div>
        </section>
      )}

      {/* -- Abilities ------------------------------------------- */}
      <section aria-label="What Toolbox Vault does">
        <SectionHeader title="What it does" />
        <div className="tv-module-tiles tv-landing-abilities">
          {ABILITIES.map((ability) => (
            <div key={ability.title} className="tv-module-tile">
              <div className="tv-landing-tile-head">
                <span className="tv-landing-medallion">
                  <BrandIcon name={ability.icon} size={44} />
                </span>
                <p className="tv-landing-tile-title">{ability.title}</p>
              </div>
              <p className="tv-landing-muted">{ability.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* -- See the real thing ---------------------------------- */}
      <section aria-label="See the real thing">
        <SectionHeader title="See the real thing" />
        <p className="tv-landing-shots-intro">
          Actual screens from the live product, in the Steel theme.
          The toolbox shown is sample data from a demo account — the
          screens, records, and history are the real thing.
        </p>
        <div className="tv-landing-shots">
          {SHOTS.map((shot) => (
            <figure key={shot.src} className="tv-landing-shot">
              <img
                src={shot.src}
                alt={shot.alt}
                width={1160}
                height={725}
                loading="lazy"
                decoding="async"
              />
              <figcaption>
                <span className="tv-landing-shot-title">{shot.title}</span>
                <span className="tv-landing-muted">{shot.body}</span>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      {/* -- Who it's for ---------------------------------------- */}
      <section aria-label="Who it's for">
        <SectionHeader title="Who it's for" />
        <div className="tv-module-tiles">
          {ACCOUNT_TYPE_OPTIONS.map((option) => {
            const photo = GROUP_PHOTOS[option.value];
            return (
              <div key={option.value} className="tv-module-tile tv-landing-group-tile">
                {photo && (
                  <img
                    className="tv-landing-group-photo"
                    src={photo.src}
                    alt={photo.alt}
                    width={880}
                    height={660}
                    loading="lazy"
                    decoding="async"
                  />
                )}
                <div className="tv-landing-group-body">
                  <p className="tv-landing-tile-title">{option.label}</p>
                  <p className="tv-landing-muted">
                    {GROUP_PITCHES[option.value] ?? option.description}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* -- Live proof ------------------------------------------ */}
      <section aria-label="See it live">
        <SectionHeader title="See it live — no account needed" />
        <div className="tv-module-tiles">
          {PROOF_LINKS.map((proof) => (
            <div key={proof.path} className="tv-module-tile">
              <p className="tv-landing-tile-title">{proof.title}</p>
              <p className="tv-landing-muted">{proof.body}</p>
              <div>
                <LinkButton to={proof.path} size="sm" variant="secondary">{proof.cta}</LinkButton>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* -- Pricing --------------------------------------------- */}
      <section aria-label="Pricing">
        <SectionHeader title="Pricing" />
        <div className="tv-module-tiles">
          <div className="tv-module-tile tv-landing-plan">
            <p className="tv-landing-plan-name">Free</p>
            <p className="tv-landing-price">
              $0 <span className="tv-landing-price-per">forever</span>
            </p>
            <p className="tv-landing-muted">
              {config.free_item_limit} items with the core vault —
              inventory, photos, documents, sharing, and reports. No
              card required and no expiry; upgrade only when your
              vault outgrows it.
            </p>
            <div>
              <LinkButton to="/signup" size="sm">Start free</LinkButton>
            </div>
          </div>
          <div className="tv-module-tile tv-landing-plan">
            <p className="tv-landing-plan-name">Pro</p>
            {(proMonthly || proYearly) && (
              <p className="tv-landing-price">
                {proMonthly || proYearly}
                {proMonthly && proYearly && (
                  <span className="tv-landing-price-per">
                    {" "}· {proYearly}
                  </span>
                )}
              </p>
            )}
            <p className="tv-landing-muted">
              For the working mechanic: unlimited items, the full
              claims and reports toolkit, and every module the vault
              grows — your whole box, on the record.
            </p>
            <div>
              <LinkButton to="/signup" size="sm" variant="secondary">Go Pro</LinkButton>
            </div>
          </div>
          <div className="tv-module-tile tv-landing-plan">
            <p className="tv-landing-plan-name">Business</p>
            {(bizMonthly || bizYearly) && (
              <p className="tv-landing-price">
                {bizMonthly || bizYearly}
                {bizMonthly && bizYearly && (
                  <span className="tv-landing-price-per">
                    {" "}· {bizYearly}
                  </span>
                )}
              </p>
            )}
            <p className="tv-landing-muted">
              For shops and crews: everything in Pro for the whole
              crew, priced as a base plus a bracket fee for your
              crew size — set when you sign up.
            </p>
            <div>
              <LinkButton to="/signup" size="sm" variant="secondary">Bring your shop</LinkButton>
            </div>
          </div>
        </div>
      </section>

      {/* -- Trial (settings-gated: only a real offer renders) --- */}
      {showTrial && (
        <Panel title="Try it first">
          <div className="tv-landing-trial-body">
            <p className="tv-landing-plain">
              {config.trial_copy.trim() ||
                "Start a free trial of Pro — full access, no card required to start."}
            </p>
            <div>
              <LinkButton to="/signup">Start your free trial</LinkButton>
            </div>
          </div>
        </Panel>
      )}

      {/* -- Footer strip ---------------------------------------- */}
      <footer className="tv-landing-footer">
        <div className="tv-landing-footer-links">
          <Link to="/signup" className="tv-landing-footer-link">{t("landing.footer.createAccount")}</Link>
          <Link to="/login" className="tv-landing-footer-link">{t("landing.footer.login")}</Link>
          <Link to="/dealers" className="tv-landing-footer-link">{t("landing.footer.dealers")}</Link>
          <Link to="/marketplace" className="tv-landing-footer-link">{t("landing.footer.marketplace")}</Link>
          <Link to="/forum" className="tv-landing-footer-link">{t("landing.footer.forum")}</Link>
          <Link to="/terms" className="tv-landing-footer-link">{t("landing.footer.terms")}</Link>
          <Link to="/privacy" className="tv-landing-footer-link">{t("landing.footer.privacy")}</Link>
          <Link to="/roadmap" className="tv-landing-footer-link">{t("landing.footer.roadmap")}</Link>
        </div>
        <p className="tv-landing-disclaimer">
{t("landing.footer.disclaimer")}
        </p>
      </footer>
    </div>
  );
}
