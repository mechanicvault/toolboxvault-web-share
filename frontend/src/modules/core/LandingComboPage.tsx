/**
 * THE OFFICIAL LANDING PAGE — the Combination (promoted
 * 2026-11-08, owner orders 15:12 + 15:18 CST).
 *
 * This page began as Testing Option 1: the combination Ryan
 * built his verdict around — the old page 1's theme styling
 * and its top part with the logo, old page 2's square bar
 * links to the public areas, old page 3's side slider of user
 * types — then his changes round (four audiences, the sixth
 * door, the highlighted no-ads pill, the shorter lane boxes,
 * price boxes centered with feature lists, social links at
 * the bottom, app-store links + a Light/Dark dress toggle on
 * the top row), the feature-lists round (a list per tier, the
 * full master list, a section per account type), and the
 * feature-list audit that verified the list against the whole
 * product. On 2026-11-08 he made it the official landing page:
 * it takes the retired merged landing's place at "/" (behind
 * the teaser — the teaser is still the signed-out door), both
 * test pages came down, and the header's Testing item now
 * links straight here (the page also sits at "/landing" so a
 * signed-in user can open it — at "/", a signed-in user gets
 * their home instead).
 *
 * Promotion terms honored: the design, content, and order are
 * the test page's, unchanged; every string now routes through
 * the i18n dictionary with full Spanish (landing.combo.* —
 * the winner gets full EN/ES). The dress toggle stays: it
 * swaps THIS page between its Steel (dark) and Navy (light)
 * dresses in place; the page OPENS in Steel, as Option 1 did.
 *
 * Two seats differ from the test page, both recorded:
 *  - the hero's free line composes the operator's real free
 *    item limit from the landing config (the same composition
 *    the old landings used) instead of the test page's fixed
 *    "20" — identical words at today's limit of 20, and the
 *    line stays true if the operator changes the limit;
 *  - the close carries the Terms/Privacy links + the
 *    development disclaimer the old landing's own footer
 *    strip carried, under the social row — the old landing
 *    resolved its footer exactly that way (its own closing
 *    strip, then the shell's shared footer below), and a
 *    public landing must not lose its legal links.
 *
 * The store targets come from the SAME landing config the
 * teaser reads (operator-set URLs), so the page never
 * invents a store address.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ArtIcon, type ArtName } from "../../components/ArtIcon";
import { SocialLinks } from "../../components/SocialLinks";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import {
  fetchLandingConfigShared,
  LANDING_FALLBACK,
  type LandingConfig,
} from "./landing";
import { DoorTiles, Lanes, PriceCards } from "./landingComboBlocks";
import { DOORS, LOGIN, PHOTOS, SIGNUP, TRUST_FACT_KEYS } from "./landingComboData";
import "./landing-combo.css";

const ABILITIES: { icon: ArtName; titleKey: DictKey; bodyKey: DictKey }[] = [
  { icon: "inventory", titleKey: "landing.combo.ability.catalog.title", bodyKey: "landing.combo.ability.catalog.body" },
  { icon: "claims", titleKey: "landing.combo.ability.claims.title", bodyKey: "landing.combo.ability.claims.body" },
  { icon: "borrowing", titleKey: "landing.combo.ability.borrowing.title", bodyKey: "landing.combo.ability.borrowing.body" },
  { icon: "dealers", titleKey: "landing.combo.ability.dealers.title", bodyKey: "landing.combo.ability.dealers.body" },
  { icon: "reports", titleKey: "landing.combo.ability.reports.title", bodyKey: "landing.combo.ability.reports.body" },
  { icon: "backup", titleKey: "landing.combo.ability.backup.title", bodyKey: "landing.combo.ability.backup.body" },
];

/** The EXTENSIVE master feature list under the price boxes
 *  (owner order, 2026-11-08: "Your missing a ton of features.
 *  I want the full list there."), then verified against the
 *  whole product by the feature-list audit (same day) — 41
 *  items. Swept from the real module registry + feature set
 *  and written as plain user-facing features; Ryan's six
 *  named items are in, in his substance (direct customer
 *  payment, shop-paid crew access, the onboarding wizard,
 *  dashboard widgets, the insurance inventory-access request,
 *  the flyer showcase). The built-vs-designed split for every
 *  item is recorded in the feature-lists lane INDEX — the
 *  page copy carries no asterisks. Two per row, centered,
 *  small icon each (his geometry). */
const FEATURES: { icon: ArtName; titleKey: DictKey; subKey: DictKey }[] = [
  { icon: "inventory", titleKey: "landing.combo.feature.catalog.title", subKey: "landing.combo.feature.catalog.sub" },
  { icon: "search", titleKey: "landing.combo.feature.search.title", subKey: "landing.combo.feature.search.sub" },
  { icon: "badge", titleKey: "landing.combo.feature.aiEntry.title", subKey: "landing.combo.feature.aiEntry.sub" },
  { icon: "info", titleKey: "landing.combo.feature.manuals.title", subKey: "landing.combo.feature.manuals.sub" },
  { icon: "categories", titleKey: "landing.combo.feature.batteries.title", subKey: "landing.combo.feature.batteries.sub" },
  { icon: "repairs", titleKey: "landing.combo.feature.repairs.title", subKey: "landing.combo.feature.repairs.sub" },
  { icon: "claims", titleKey: "landing.combo.feature.claims.title", subKey: "landing.combo.feature.claims.sub" },
  { icon: "disaster", titleKey: "landing.combo.feature.disaster.title", subKey: "landing.combo.feature.disaster.sub" },
  { icon: "badge", titleKey: "landing.combo.feature.health.title", subKey: "landing.combo.feature.health.sub" },
  { icon: "tag", titleKey: "landing.combo.feature.qr.title", subKey: "landing.combo.feature.qr.sub" },
  { icon: "categories", titleKey: "landing.combo.feature.customFields.title", subKey: "landing.combo.feature.customFields.sub" },
  { icon: "borrowing", titleKey: "landing.combo.feature.borrowing.title", subKey: "landing.combo.feature.borrowing.sub" },
  { icon: "warning", titleKey: "landing.combo.feature.reminders.title", subKey: "landing.combo.feature.reminders.sub" },
  { icon: "truck", titleKey: "landing.combo.feature.truck.title", subKey: "landing.combo.feature.truck.sub" },
  { icon: "money", titleKey: "landing.combo.feature.paid.title", subKey: "landing.combo.feature.paid.sub" },
  { icon: "flyers", titleKey: "landing.combo.feature.flyers.title", subKey: "landing.combo.feature.flyers.sub" },
  { icon: "dealers", titleKey: "landing.combo.feature.findAgent.title", subKey: "landing.combo.feature.findAgent.sub" },
  { icon: "people", titleKey: "landing.combo.feature.crew.title", subKey: "landing.combo.feature.crew.sub" },
  { icon: "shared", titleKey: "landing.combo.feature.sharing.title", subKey: "landing.combo.feature.sharing.sub" },
  { icon: "reports", titleKey: "landing.combo.feature.reports.title", subKey: "landing.combo.feature.reports.sub" },
  { icon: "reports", titleKey: "landing.combo.feature.reportsSaved.title", subKey: "landing.combo.feature.reportsSaved.sub" },
  { icon: "backup", titleKey: "landing.combo.feature.backups.title", subKey: "landing.combo.feature.backups.sub" },
  { icon: "backup", titleKey: "landing.combo.feature.history.title", subKey: "landing.combo.feature.history.sub" },
  { icon: "backup", titleKey: "landing.combo.feature.drive.title", subKey: "landing.combo.feature.drive.sub" },
  { icon: "settings", titleKey: "landing.combo.feature.onboarding.title", subKey: "landing.combo.feature.onboarding.sub" },
  { icon: "support", titleKey: "landing.combo.feature.walkthroughs.title", subKey: "landing.combo.feature.walkthroughs.sub" },
  { icon: "home", titleKey: "landing.combo.feature.widgets.title", subKey: "landing.combo.feature.widgets.sub" },
  { icon: "info", titleKey: "landing.combo.feature.insuranceAccess.title", subKey: "landing.combo.feature.insuranceAccess.sub" },
  { icon: "forum", titleKey: "landing.combo.feature.forum.title", subKey: "landing.combo.feature.forum.sub" },
  { icon: "marketplace", titleKey: "landing.combo.feature.marketplace.title", subKey: "landing.combo.feature.marketplace.sub" },
  { icon: "parts", titleKey: "landing.combo.feature.parts.title", subKey: "landing.combo.feature.parts.sub" },
  { icon: "expansion", titleKey: "landing.combo.feature.expansion.title", subKey: "landing.combo.feature.expansion.sub" },
  { icon: "videos", titleKey: "landing.combo.feature.videos.title", subKey: "landing.combo.feature.videos.sub" },
  { icon: "support", titleKey: "landing.combo.feature.support.title", subKey: "landing.combo.feature.support.sub" },
  { icon: "feedback", titleKey: "landing.combo.feature.boards.title", subKey: "landing.combo.feature.boards.sub" },
  { icon: "tag", titleKey: "landing.combo.feature.importSheet.title", subKey: "landing.combo.feature.importSheet.sub" },
  { icon: "people", titleKey: "landing.combo.feature.contacts.title", subKey: "landing.combo.feature.contacts.sub" },
  { icon: "info", titleKey: "landing.combo.feature.language.title", subKey: "landing.combo.feature.language.sub" },
  { icon: "settings", titleKey: "landing.combo.feature.theme.title", subKey: "landing.combo.feature.theme.sub" },
  { icon: "money", titleKey: "landing.combo.feature.currency.title", subKey: "landing.combo.feature.currency.sub" },
  { icon: "people", titleKey: "landing.combo.feature.refer.title", subKey: "landing.combo.feature.refer.sub" },
  { icon: "backup", titleKey: "landing.combo.feature.exportData.title", subKey: "landing.combo.feature.exportData.sub" },
  { icon: "reports", titleKey: "landing.combo.feature.downloads.title", subKey: "landing.combo.feature.downloads.sub" },
  { icon: "settings", titleKey: "landing.combo.feature.converter.title", subKey: "landing.combo.feature.converter.sub" },
  { icon: "parts", titleKey: "landing.combo.feature.prints3d.title", subKey: "landing.combo.feature.prints3d.sub" },
  { icon: "search", titleKey: "landing.combo.feature.visitorPreview.title", subKey: "landing.combo.feature.visitorPreview.sub" },
  { icon: "videos", titleKey: "landing.combo.feature.wallpapers.title", subKey: "landing.combo.feature.wallpapers.sub" },
];

/** The account-type sections (owner order, 2026-11-08): for
 *  EACH type — a short summary of what the type is FOR, then
 *  that type's own full feature list, so a visitor can see
 *  which type to pick. The product's types are a SET on one
 *  account (accountTypes.ts: a user belongs to a set of
 *  groups, access is the union) — the banner above the cards
 *  says so where a chooser will see it. Type features are
 *  drawn from the real group/module availability (manifest
 *  default_groups) plus Ryan's named items mapped to their
 *  types; the feature-lists INDEX records sources and the
 *  built-vs-designed split per type. */
const TYPES: { icon: ArtName; nameKey: DictKey; summaryKey: DictKey; itemKeys: DictKey[] }[] = [
  {
    icon: "inventory",
    nameKey: "landing.combo.type.mechanic.name",
    summaryKey: "landing.combo.type.mechanic.summary",
    itemKeys: [
      "landing.combo.type.mechanic.i1",
      "landing.combo.type.mechanic.i2",
      "landing.combo.type.mechanic.i3",
      "landing.combo.type.mechanic.i4",
      "landing.combo.type.mechanic.i5",
      "landing.combo.type.mechanic.i6",
      "landing.combo.type.mechanic.i7",
      "landing.combo.type.mechanic.i8",
      "landing.combo.type.mechanic.i9",
      "landing.combo.type.mechanic.i10",
      "landing.combo.type.mechanic.i11",
      "landing.combo.type.mechanic.i12",
      "landing.combo.type.mechanic.i13",
    ],
  },
  {
    icon: "people",
    nameKey: "landing.combo.type.shop.name",
    summaryKey: "landing.combo.type.shop.summary",
    itemKeys: [
      "landing.combo.type.shop.i1",
      "landing.combo.type.shop.i2",
      "landing.combo.type.shop.i3",
      "landing.combo.type.shop.i4",
      "landing.combo.type.shop.i5",
      "landing.combo.type.shop.i6",
      "landing.combo.type.shop.i7",
    ],
  },
  {
    icon: "dealers",
    nameKey: "landing.combo.type.dealer.name",
    summaryKey: "landing.combo.type.dealer.summary",
    itemKeys: [
      "landing.combo.type.dealer.i1",
      "landing.combo.type.dealer.i2",
      "landing.combo.type.dealer.i3",
      "landing.combo.type.dealer.i4",
      "landing.combo.type.dealer.i5",
      "landing.combo.type.dealer.i6",
      "landing.combo.type.dealer.i7",
    ],
  },
  {
    icon: "truck",
    nameKey: "landing.combo.type.agent.name",
    summaryKey: "landing.combo.type.agent.summary",
    itemKeys: [
      "landing.combo.type.agent.i1",
      "landing.combo.type.agent.i2",
      "landing.combo.type.agent.i3",
      "landing.combo.type.agent.i4",
      "landing.combo.type.agent.i5",
      "landing.combo.type.agent.i6",
    ],
  },
  {
    icon: "claims",
    nameKey: "landing.combo.type.insco.name",
    summaryKey: "landing.combo.type.insco.summary",
    itemKeys: [
      "landing.combo.type.insco.i1",
      "landing.combo.type.insco.i2",
      "landing.combo.type.insco.i3",
      "landing.combo.type.insco.i4",
      "landing.combo.type.insco.i5",
    ],
  },
  {
    icon: "badge",
    nameKey: "landing.combo.type.insagent.name",
    summaryKey: "landing.combo.type.insagent.summary",
    itemKeys: [
      "landing.combo.type.insagent.i1",
      "landing.combo.type.insagent.i2",
      "landing.combo.type.insagent.i3",
      "landing.combo.type.insagent.i4",
      "landing.combo.type.insagent.i5",
    ],
  },
];

export default function LandingComboPage() {
  const t = useT();
  /** The dress on screen: the page OPENS in Steel (Option 1's
   *  own dress); the top-row Light/Dark toggle swaps it to
   *  the Navy dress in place. */
  const [active, setActive] = useState<"steel" | "navy">("steel");
  const [config, setConfig] = useState<LandingConfig>(LANDING_FALLBACK);
  useEffect(() => {
    let live = true;
    void fetchLandingConfigShared().then((loaded) => {
      if (live) setConfig(loaded);
    });
    return () => {
      live = false;
    };
  }, []);
  const appStoreUrl = config.app_store_url.trim();
  const playStoreUrl = config.play_store_url.trim();

  return (
    <div className={`lt lt-cb lt-cb-${active}`}>
      {/* — Top row: navigation links + the app stores ——————— */}
      <div className="lt-cb-topbar">
        <nav className="lt-cb-topnav" aria-label={t("landing.combo.navLabel")}>
          {DOORS.map((d) => (
            <Link key={d.path} to={d.path}>
              {t(d.navLabelKey ?? d.labelKey)}
            </Link>
          ))}
        </nav>
        <div className="lt-cb-stores">
          <a
            className="lt-cb-store"
            href={appStoreUrl || "#"}
            {...(appStoreUrl
              ? { target: "_blank", rel: "noreferrer" }
              : {})}
          >
            {t("landing.store.appStore")}
          </a>
          <a
            className="lt-cb-store"
            href={playStoreUrl || "#"}
            {...(playStoreUrl
              ? { target: "_blank", rel: "noreferrer" }
              : {})}
          >
            {t("landing.store.googlePlay")}
          </a>
          <button
            type="button"
            className="lt-cb-theme"
            aria-pressed={active === "navy"}
            aria-label={t("landing.combo.themeToggle")}
            onClick={() =>
              setActive((d) => (d === "steel" ? "navy" : "steel"))
            }
          >
            <span className={active === "navy" ? "is-on" : ""}>{t("landing.combo.themeLight")}</span>
            <span className={active === "steel" ? "is-on" : ""}>{t("landing.combo.themeDark")}</span>
          </button>
        </div>
      </div>

      {/* — Hero: the lockup riding high over the photo band — */}
      <section className="lt-cb-hero" aria-label="Toolbox Vault">
        <div className="lt-cb-hero-art" aria-hidden="true">
          <img src={PHOTOS.workbench} alt="" />
        </div>
        <div className="lt-cb-lockup">
          <img className="lt-cb-logo" src={PHOTOS.logo} alt={t("landing.combo.logoAlt")} />
          <img className="lt-cb-wordmark" src={PHOTOS.wordmark} alt="Toolbox Vault" />
          <p className="lt-cb-slogan">ORGANIZE. PROTECT. RECOVER.</p>
          <p className="lt-cb-tagline">{t("landing.tagline")}</p>
          <p className="lt-cb-herobody">{t("landing.hero.body")}</p>
          <div className="lt-cb-ctas">
            <Link className="lt-cb-btn lt-cb-btn-primary" to={SIGNUP}>
              {t("landing.hero.cta")}
            </Link>
            <Link className="lt-cb-btn lt-cb-btn-ghost" to={LOGIN}>
              {t("landing.hero.login")}
            </Link>
          </div>
          <p className="lt-cb-noads">
            {t("landing.combo.noads")} <strong>{t("landing.combo.noadsEver")}</strong>
          </p>
          <p className="lt-cb-free">
            {t("landing.hero.freeBefore")} {config.free_item_limit} {t("landing.hero.freeAfter")}
          </p>
        </div>
      </section>

      {/* — Doors: the square bar links to the public areas ——— */}
      <section className="lt-cb-section" aria-label={t("landing.combo.doorsTitle")}>
        <h2 className="lt-cb-h2">{t("landing.combo.doorsTitle")}</h2>
        <p className="lt-cb-intro">{t("landing.combo.doorsIntro")}</p>
        <DoorTiles prefix="lt-cb" />
      </section>

      {/* — Lanes: the user-type side slider ——————————————————— */}
      <section className="lt-cb-section" aria-label={t("landing.combo.lanesLabel")}>
        <p className="lt-cb-eyebrow">{t("landing.combo.lanesEyebrow")}</p>
        <h2 className="lt-cb-h2">{t("landing.combo.lanesTitle")}</h2>
        <Lanes prefix="lt-cb" />
      </section>

      {/* — Abilities ———————————————————————————————————————————— */}
      <section className="lt-cb-section" aria-label={t("landing.combo.abilitiesTitle")}>
        <h2 className="lt-cb-h2">{t("landing.combo.abilitiesTitle")}</h2>
        <div className="lt-cb-tiles">
          {ABILITIES.map((a) => (
            <div key={a.titleKey} className="lt-cb-tile">
              <span className="lt-cb-medallion">
                <ArtIcon name={a.icon} size={40} />
              </span>
              <p className="lt-cb-tile-title">{t(a.titleKey)}</p>
              <p className="lt-cb-tile-body">{t(a.bodyKey)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* — Pricing —————————————————————————————————————————————— */}
      <section className="lt-cb-section" aria-label={t("landing.combo.pricingLabel")}>
        <h2 className="lt-cb-h2">{t("landing.combo.pricingTitle")}</h2>
        <PriceCards prefix="lt-cb" />
        <p className="lt-cb-features-label">{t("landing.combo.featuresLabel")}</p>
        <div className="lt-cb-features">
          {FEATURES.map((f) => (
            <div key={f.titleKey} className="lt-cb-feature">
              <span className="lt-cb-feature-icon">
                <ArtIcon name={f.icon} size={24} />
              </span>
              <div>
                <p className="lt-cb-feature-title">{t(f.titleKey)}</p>
                <p className="lt-cb-feature-sub">{t(f.subKey)}</p>
              </div>
            </div>
          ))}
        </div>
        <p className="lt-cb-promise">{t("landing.combo.promise")}</p>
      </section>

      {/* — Account types: summary + each type's own list ————— */}
      <section className="lt-cb-section" aria-label={t("landing.combo.typesEyebrow")}>
        <p className="lt-cb-eyebrow">{t("landing.combo.typesEyebrow")}</p>
        <h2 className="lt-cb-h2">{t("landing.combo.typesTitle")}</h2>
        <div className="lt-cb-multitype">
          <p className="lt-cb-multitype-title">{t("landing.combo.multiTitle")}</p>
          <p className="lt-cb-multitype-body">{t("landing.combo.multiBody")}</p>
        </div>
        <div className="lt-cb-types">
          {TYPES.map((type) => (
            <article key={type.nameKey} className="lt-cb-type">
              <span className="lt-cb-medallion">
                <ArtIcon name={type.icon} size={40} />
              </span>
              <h3 className="lt-cb-type-name">{t(type.nameKey)}</h3>
              <p className="lt-cb-type-summary">{t(type.summaryKey)}</p>
              <ul className="lt-cb-type-list">
                {type.itemKeys.map((item) => (
                  <li key={item}>{t(item)}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      {/* — Close ———————————————————————————————————————————————— */}
      <section className="lt-cb-close">
        <h2 className="lt-cb-close-title">{t("landing.combo.closeTitle")}</h2>
        <p className="lt-cb-close-body">{t("landing.combo.closeBody")}</p>
        <Link className="lt-cb-btn lt-cb-btn-primary" to={SIGNUP}>
          {t("landing.combo.closeCta")}
        </Link>
        <ul className="lt-cb-trust">
          {TRUST_FACT_KEYS.map((f) => (
            <li key={f}>✓ {t(f)}</li>
          ))}
        </ul>
        <div className="lt-cb-social">
          <SocialLinks />
        </div>
        {/* The legal line the old landing's own closing strip
            carried (Terms/Privacy + the development
            disclaimer) — the shell's shared footer follows
            below, exactly as it closed the old landing. */}
        <p className="lt-cb-legal">
          <Link to="/terms">{t("landing.footer.terms")}</Link>
          <span aria-hidden="true">·</span>
          <Link to="/privacy">{t("landing.footer.privacy")}</Link>
        </p>
        <p className="lt-cb-disclaimer">{t("landing.footer.disclaimer")}</p>
      </section>
    </div>
  );
}
