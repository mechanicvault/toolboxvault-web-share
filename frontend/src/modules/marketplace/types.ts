/** Tools For Sale + reputation types — mirroring the API
 *  schemas in backend/app/modules/marketplace/schemas.py.
 *
 *  The public listing shape is a PINNED contract (exact keys, on
 *  the signed-in board and the anonymous board alike): a listing
 *  shows only what the seller put on it — never their email,
 *  never anything from the inventory record it was copied from.
 *  The phone rides along ONLY when the seller opted in. */

export interface ReputationSummary {
  average: number | null;
  count: number;
  completed_deals: number;
}

export interface ListingPhoto {
  filename: string;
  url: string;
}

export interface PublicListing {
  id: string;
  title: string;
  description: string;
  listing_type: "for_sale" | "wanted";
  /** Decimal string; null reads as "Make offer". */
  price: string | null;
  condition: string;
  brand: string;
  model: string;
  delivery_local_pickup: boolean;
  delivery_ships: boolean;
  area_label: string | null;
  photos: ListingPhoto[];
  seller_id: string;
  seller_name: string;
  seller_member_since: string;
  seller_reputation: ReputationSummary;
  /** Wave 3: the price is in the SELLER's currency (ISO 4217). */
  seller_currency: string;
  phone: string | null;
  created_at: string;
  updated_at: string;
}

export interface OwnerListing extends PublicListing {
  status: "active" | "sold" | "removed";
  source_kind: string;
  source_id: string | null;
  buyer_id: string | null;
  buyer_name: string | null;
  sold_at: string | null;
  /** The RAW per-listing area override (null = inherit the
   *  profile's public area); the public shape resolves it into
   *  area_label. */
  area_override: string | null;
  show_phone_override: boolean | null;
}

export interface ListingFormValues {
  title: string;
  description: string;
  listing_type: "for_sale" | "wanted";
  price: string | null;
  condition: string;
  brand: string;
  model: string;
  delivery_local_pickup: boolean;
  delivery_ships: boolean;
  public_area_label: string | null;
  show_phone_override: boolean | null;
}

export interface BuyerCandidate {
  user_id: string;
  name: string;
}

export interface MyRatingView {
  /** Null when a moderator has removed the rating (gap wave 1). */
  stars: number | null;
  text: string;
  removed: boolean;
  published: boolean;
  published_at: string | null;
}

/** The other side's rating exists in this shape ONLY once
 *  published — before that the API sends null (double-blind). */
export interface TheirRatingView {
  id: string | null;
  stars: number | null;
  text: string;
  removed: boolean;
  published_at: string | null;
}

export interface Interaction {
  id: string;
  other_user_id: string;
  other_name: string;
  source: "listing" | "part" | "thread";
  listing_id: string | null;
  part_id: string | null;
  thread_id: string | null;
  context_title: string;
  completed_at: string;
  my_rating: MyRatingView | null;
  their_rating: TheirRatingView | null;
  their_rating_submitted: boolean;
}

export interface PublishedRating {
  id: string;
  /** Null on a moderator-removed review (the tombstone row). */
  stars: number | null;
  text: string;
  removed: boolean;
  rater_id: string;
  rater_name: string;
  context_title: string;
  published_at: string | null;
  created_at: string;
}

/** One rating report as the moderation queue sees it (gap wave 1). */
export interface RatingReport {
  id: string;
  rating_id: string;
  reporter_id: string;
  reporter_name: string;
  reason: string;
  status: string;
  resolution: string;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
  rating_stars: number | null;
  rating_text: string;
  rating_removed: boolean;
  rater_id: string | null;
  rater_name: string;
  ratee_id: string | null;
  ratee_name: string;
  context_title: string;
}

export interface PublicReputation {
  user_id: string;
  summary: ReputationSummary;
  ratings: PublishedRating[];
}

export interface ThreadCompletion {
  anchored: boolean;
  i_closed: boolean;
  other_closed: boolean;
  interaction_id: string | null;
}

/** The one-line rating badge used on cards suite-wide:
 *  "★ 4.8 (12)" once ratings exist; an honest "New seller"
 *  before that — never an invented number. */
export function reputationBadge(summary: ReputationSummary): string {
  if (summary.count > 0 && summary.average !== null) {
    return `★ ${summary.average.toFixed(1)} (${summary.count})`;
  }
  return "New seller";
}
