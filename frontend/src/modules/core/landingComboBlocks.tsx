/**
 * The Combination landing page's building blocks (promoted
 * from the landing test tree 2026-11-08, owner order) — the
 * pieces Ryan named from the retired test batches, built once
 * and dressed by the caller's class prefix (every rule lives
 * in landing-combo.css under the page's own prefix):
 *
 *  - DoorTiles — the square bar links to the public areas:
 *    the six doors as square tiles (icon, label, one line,
 *    "Open →").
 *  - Lanes — the user-type side slider: four audience photo
 *    lanes side by side that widen under the pointer, each
 *    with its pitch, two points, and its Start free door.
 *  - PriceCards — the real plan catalog (billing migration
 *    0010 + the landing settings): Free (first 20 tools),
 *    Pro ($7.99/mo · $79.99/yr), and Business (the company
 *    plan, priced base + crew-size bracket; its dollar
 *    figures are an operator setting that is empty today,
 *    so no figure is shown — the same honesty rule every
 *    landing here follows). Every tier box carries its OWN
 *    feature list, derived from the catalog + the entitlement
 *    engine (plans differ by item limit — 20 vs unlimited —
 *    and by the Business crew structure; site features
 *    themselves are not plan-gated in the resolver).
 *
 * All copy routes through the i18n dictionary (landing.combo.*)
 * — data and keys live in ./landingComboData.
 */

import { Link } from "react-router-dom";

import { ArtIcon } from "../../components/ArtIcon";
import type { DictKey } from "../../i18n/dictionaries";
import { useT } from "../../i18n/LocaleContext";
import { AUDIENCES, DOORS, SIGNUP } from "./landingComboData";

/** The square door tiles, under the caller's prefix. */
export function DoorTiles({ prefix }: { prefix: string }) {
  const t = useT();
  return (
    <div className={`${prefix}-doors`}>
      {DOORS.map((d) => (
        <Link key={d.path} className={`${prefix}-door`} to={d.path}>
          <ArtIcon name={d.icon} size={38} />
          <span className={`${prefix}-door-label`}>{t(d.labelKey)}</span>
          <span className={`${prefix}-door-sub`}>{t(d.subKey)}</span>
          <span className={`${prefix}-door-go`}>{t("landing.combo.open")} →</span>
        </Link>
      ))}
    </div>
  );
}

/** The photo-lane slider, under the caller's prefix. */
export function Lanes({ prefix }: { prefix: string }) {
  const t = useT();
  return (
    <div className={`${prefix}-lanes`}>
      {AUDIENCES.map((a) => (
        <article key={a.key} className={`${prefix}-lane`}>
          <img src={a.photo} alt={t(a.photoAltKey)} loading="lazy" />
          <div className={`${prefix}-lane-body`}>
            <h3>{t(a.nameKey)}</h3>
            <p className={`${prefix}-lane-pitch`}>{t(a.pitchKey)}</p>
            <ul>
              {a.pointKeys.slice(0, 2).map((p) => (
                <li key={p}>{t(p)}</li>
              ))}
            </ul>
            <Link className={`${prefix}-lane-cta`} to={SIGNUP}>
              {t("landing.combo.startFree")} →
            </Link>
          </div>
        </article>
      ))}
    </div>
  );
}

interface Plan {
  nameKey: DictKey;
  /** A printed amount ("$0", "$7.99") — language-neutral, so
   *  it stays a literal; a worded amount goes through the
   *  dictionary instead (amountKey). */
  amount?: string;
  amountKey?: DictKey;
  perKey: DictKey;
  bodyKey: DictKey;
  itemKeys: DictKey[];
  ctaKey: DictKey;
  pro?: boolean;
  wordAmount?: boolean;
}

/** The plan catalog as feature lists (owner order, 2026-11-08:
 *  a feature list for EACH account tier). Sources: the seeded
 *  catalog (alembic 0010_billing — free item_limit 20, pro and
 *  business unlimited), the entitlement resolver (the plans
 *  differ by item limit and the Business crew brackets — up to
 *  5 / 10 / 25 / unlimited employees — never by feature gates),
 *  and the landing price settings (Pro $7.99/$79.99; Business
 *  dollar figures unset, so none is printed). */
const PLANS: Plan[] = [
  {
    nameKey: "landing.combo.plan.free.name",
    amount: "$0",
    perKey: "landing.combo.plan.free.per",
    bodyKey: "landing.combo.plan.free.body",
    itemKeys: [
      "landing.combo.plan.free.i1",
      "landing.combo.plan.free.i2",
      "landing.combo.plan.free.i3",
      "landing.combo.plan.free.i4",
      "landing.combo.plan.free.i5",
    ],
    ctaKey: "landing.combo.startFree",
  },
  {
    nameKey: "landing.combo.plan.pro.name",
    amount: "$7.99",
    perKey: "landing.combo.plan.pro.per",
    bodyKey: "landing.combo.plan.pro.body",
    itemKeys: [
      "landing.combo.plan.pro.i1",
      "landing.combo.plan.pro.i2",
      "landing.combo.plan.pro.i3",
      "landing.combo.plan.pro.i4",
      "landing.combo.plan.pro.i5",
    ],
    ctaKey: "landing.combo.plan.pro.cta",
    pro: true,
  },
  {
    nameKey: "landing.combo.plan.biz.name",
    amountKey: "landing.combo.plan.biz.amount",
    perKey: "landing.combo.plan.biz.per",
    bodyKey: "landing.combo.plan.biz.body",
    itemKeys: [
      "landing.combo.plan.biz.i1",
      "landing.combo.plan.biz.i2",
      "landing.combo.plan.biz.i3",
      "landing.combo.plan.biz.i4",
      "landing.combo.plan.biz.i5",
    ],
    ctaKey: "landing.combo.plan.biz.cta",
    wordAmount: true,
  },
];

/** The three catalog tiers, side by side, each with its own
 *  feature list, under the caller's prefix. */
export function PriceCards({ prefix }: { prefix: string }) {
  const t = useT();
  return (
    <div className={`${prefix}-plans`}>
      {PLANS.map((plan) => (
        <div
          key={plan.nameKey}
          className={`${prefix}-plan${plan.pro ? ` ${prefix}-plan-pro` : ""}`}
        >
          <p className={`${prefix}-plan-name`}>{t(plan.nameKey)}</p>
          <p
            className={`${prefix}-plan-amount${plan.wordAmount ? ` ${prefix}-plan-amount-word` : ""}`}
          >
            {plan.amount ?? t(plan.amountKey!)} <span className={`${prefix}-plan-per`}>{t(plan.perKey)}</span>
          </p>
          <p className={`${prefix}-plan-body`}>{t(plan.bodyKey)}</p>
          <ul className={`${prefix}-plan-list`}>
            {plan.itemKeys.map((item) => (
              <li key={item}>{t(item)}</li>
            ))}
          </ul>
          <Link className={`${prefix}-plan-cta`} to={SIGNUP}>
            {t(plan.ctaKey)}
          </Link>
        </div>
      ))}
    </div>
  );
}
