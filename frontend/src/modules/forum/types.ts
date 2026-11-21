/** Community Forum types — mirroring the API schemas in
 *  backend/app/modules/forum/schemas.py.
 *
 *  The reading shapes are PINNED contracts (exact keys, on the
 *  signed-in routes and the anonymous /public twins alike): an
 *  author shows only the public profile fields — display name,
 *  account number, member since, role, reputation. Never an
 *  email. */

import type { ReputationSummary } from "../marketplace/types";

export type { ReputationSummary };

export interface ForumAuthor {
  user_id: string;
  display_name: string;
  account_number: string;
  member_since: string | null;
  role: string;
  reputation: ReputationSummary;
}

export interface ForumCategory {
  id: string;
  name: string;
  description: string;
  sort_order: number;
  is_active: boolean;
  /** Built-in rooms carry a system key ("site_help" |
   *  "bug_reports" | "feature_requests" — the last two are the
   *  PERMANENT boards); operator rooms carry null. */
  system_key: string | null;
  thread_count: number;
  post_count: number;
  last_thread_id: string | null;
  last_thread_title: string | null;
  last_activity_at: string | null;
}

export interface ForumLinkCard {
  type: "part" | "listing";
  id: string;
  title: string;
  /** Decimal string; null on a part reads as "Make offer". */
  price: string | null;
  /** The SELLER's currency the price is in (wave 3); null on a
   *  dead card. The card renders via SellerPrice, like the
   *  board / pool the target lives on. */
  seller_currency: string | null;
  photo_url: string | null;
  available: boolean;
}

export interface ForumQuote {
  author_name: string;
  excerpt: string;
}

export interface ForumPost {
  id: string;
  thread_id: string;
  author: ForumAuthor;
  body: string;
  status: "visible" | "held" | "removed";
  removed_by: "author" | "moderator" | null;
  is_opener: boolean;
  quote: ForumQuote | null;
  link: ForumLinkCard | null;
  flags: string[];
  edited_at: string | null;
  created_at: string;
  mine: boolean;
}

export interface ForumThread {
  id: string;
  category_id: string;
  title: string;
  author: ForumAuthor;
  pinned: boolean;
  locked: boolean;
  held: boolean;
  reply_count: number;
  post_count: number;
  excerpt: string;
  created_at: string;
  last_post_at: string;
}

export interface ForumThreadDetail extends ForumThread {
  posts: ForumPost[];
}

/** A favorite's target kind: a forum thread, or a permanent
 *  board's post (the boards' posts are feedback rows — the
 *  favorites list holds both). */
export type ForumFavoriteKind = "thread" | "post";

/** One resolved favorite (GET /forum/favorites): the target's
 *  live face — never a snapshot. Targets the member can no
 *  longer see are absent from the list entirely. */
export interface ForumFavorite {
  kind: ForumFavoriteKind;
  target_id: string;
  title: string;
  board_name: string;
  reply_count: number;
  last_activity_at: string;
  starred_at: string;
}

export interface ForumReport {
  id: string;
  post_id: string;
  thread_id: string;
  thread_title: string;
  post_status: string;
  post_excerpt: string;
  post_author_id: string | null;
  post_author_name: string;
  reporter_id: string;
  reporter_name: string;
  reason: string;
  status: string;
  resolution: string;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
}

/** A community block (admin lane, 2026-11-07): one member's
 *  block from ONE community feature, imposed/lifted by god +
 *  moderator_admin seats only. Lifted rows stay readable —
 *  active=false once lifted_at is set. */
export interface CommunityBlock {
  id: string;
  user_id: string;
  user_name: string;
  account_number: string;
  feature: string;
  feature_label: string;
  reason: string;
  blocked_by_id: string;
  blocked_by_name: string;
  lifted_by_id: string | null;
  lifted_by_name: string;
  lifted_at: string | null;
  active: boolean;
  created_at: string;
}

export interface ForumHeld {
  id: string;
  thread_id: string;
  thread_title: string;
  author_id: string;
  author_name: string;
  body: string;
  flags: string[];
  is_opener: boolean;
  created_at: string;
}
