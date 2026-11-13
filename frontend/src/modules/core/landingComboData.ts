import type { ArtName } from "../../components/ArtIcon";
import type { DictKey } from "../../i18n/dictionaries";

/**
 * The Combination landing page's FACTS (promoted from the
 * landing test tree 2026-11-08, owner order): the real public
 * doors, the four audiences, the photo set. Copy lives in the
 * i18n dictionary (landing.combo.*) — this file holds only
 * structure: paths, icons, photos, and the dictionary keys
 * each rendered string comes from.
 *
 * Door targets are the public surfaces the old merged landing
 * advertised (its FREE_CARDS), so a door never points anywhere
 * the product doesn't already open to the public.
 */

export const SIGNUP = "/signup";
export const LOGIN = "/login";

export interface Door {
  labelKey: DictKey;
  subKey: DictKey;
  /** Shorter label for the page's top navigation row only —
   *  the same door, the same destination; a nav row is terser
   *  than a door tile. */
  navLabelKey?: DictKey;
  path: string;
  icon: ArtName;
}

/** The six public doors (owner, 2026-11-08): the first door
 *  carries his wording ("Find local tool dealer or insurance
 *  agent"), and Downloads is in the row — he flagged its
 *  omission himself. */
export const DOORS: Door[] = [
  { labelKey: "landing.combo.door.findAgent.label", subKey: "landing.combo.door.findAgent.sub", navLabelKey: "landing.combo.navFindAgent", path: "/dealers/find-agent", icon: "search" },
  { labelKey: "landing.footer.dealers", subKey: "landing.combo.door.dealers.sub", path: "/dealers", icon: "dealers" },
  { labelKey: "landing.footer.marketplace", subKey: "landing.combo.door.tools.sub", path: "/marketplace", icon: "marketplace" },
  { labelKey: "landing.combo.door.parts.label", subKey: "landing.combo.door.parts.sub", path: "/parts/community", icon: "parts" },
  { labelKey: "landing.combo.door.forum.label", subKey: "landing.combo.door.forum.sub", navLabelKey: "landing.combo.navForum", path: "/forum", icon: "forum" },
  { labelKey: "landing.combo.door.downloads.label", subKey: "landing.combo.door.downloads.sub", path: "/downloads", icon: "reports" },
];

export interface Audience {
  key: string;
  nameKey: DictKey;
  /** One-line pitch in the site's voice. */
  pitchKey: DictKey;
  pointKeys: DictKey[];
  photo: string;
  photoAltKey: DictKey;
  icon: ArtName;
}

export const PHOTOS = {
  workbench: "/landing/hero-workbench.webp",
  mechanic: "/landing/group-mechanic.webp",
  dealer: "/landing/group-dealer.webp",
  shop: "/landing/group-shop.webp",
  dashboard: "/landing/shot-dashboard.webp",
  inventory: "/landing/shot-inventory.webp",
  history: "/landing/shot-history.webp",
  findAgent: "/landing/shot-find-agent.webp",
  record: "/landing/insurance-record.webp",
  logo: "/brand/logo-256.webp",
  wordmark: "/brand/wordmark-840.webp",
};

/** The four audiences (the parts-hunter lane is gone — owner
 *  order, 2026-11-08: parts hunters are served by the Parts
 *  for sale door). The lane slider renders the first two
 *  points per audience; the rest stay as the audience's full
 *  selling points in the record. */
export const AUDIENCES: Audience[] = [
  {
    key: "mechanic",
    nameKey: "landing.combo.lane.mechanic.name",
    pitchKey: "landing.combo.lane.mechanic.pitch",
    pointKeys: [
      "landing.combo.lane.mechanic.p1",
      "landing.combo.lane.mechanic.p2",
      "landing.combo.lane.mechanic.p3",
      "landing.combo.lane.mechanic.p4",
      "landing.combo.lane.mechanic.p5",
    ],
    photo: PHOTOS.mechanic,
    photoAltKey: "landing.combo.lane.mechanic.alt",
    icon: "inventory",
  },
  {
    key: "dealer",
    nameKey: "landing.combo.lane.dealer.name",
    pitchKey: "landing.combo.lane.dealer.pitch",
    pointKeys: [
      "landing.combo.lane.dealer.p1",
      "landing.combo.lane.dealer.p2",
      "landing.combo.lane.dealer.p3",
      "landing.combo.lane.dealer.p4",
    ],
    photo: PHOTOS.dealer,
    photoAltKey: "landing.combo.lane.dealer.alt",
    icon: "truck",
  },
  {
    key: "insurance",
    nameKey: "landing.combo.lane.insurance.name",
    pitchKey: "landing.combo.lane.insurance.pitch",
    pointKeys: [
      "landing.combo.lane.insurance.p1",
      "landing.combo.lane.insurance.p2",
      "landing.combo.lane.insurance.p3",
      "landing.combo.lane.insurance.p4",
    ],
    photo: PHOTOS.record,
    photoAltKey: "landing.combo.lane.insurance.alt",
    icon: "claims",
  },
  {
    key: "shop",
    nameKey: "landing.combo.lane.shop.name",
    pitchKey: "landing.combo.lane.shop.pitch",
    pointKeys: [
      "landing.combo.lane.shop.p1",
      "landing.combo.lane.shop.p2",
      "landing.combo.lane.shop.p3",
    ],
    photo: PHOTOS.shop,
    photoAltKey: "landing.combo.lane.shop.alt",
    icon: "people",
  },
];

/** True statements the page's close leans on (the promise is
 *  the downloads page's own line: your email is never sold). */
export const TRUST_FACT_KEYS: DictKey[] = [
  "landing.combo.trust1",
  "landing.combo.trust2",
  "landing.combo.promise",
  "landing.combo.trust4",
];
