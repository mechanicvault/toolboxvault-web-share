/**
 * Feedback boards payloads (wave 3) — the exact-key contract
 * from the API. No email exists anywhere in these shapes, by
 * construction. The signed-in and anonymous faces share them
 * (signed-out reads simply carry mine/voted_by_me = false).
 */

export type FeedbackBoard = "bug" | "feature";

export type FeedbackStatus =
  | "open"
  | "acknowledged"
  | "planned"
  | "in_progress"
  | "done"
  | "declined";

/** The filer's urgency call (boards lane, 2026-11-07): picked
 *  on the filing form's 3-position toggle, locked to the filer
 *  afterwards, editable by moderators. */
export type FeedbackUrgency = "low" | "medium" | "high";

export type FeedbackSort = "new" | "top";

export interface FeedbackAuthor {
  user_id: string;
  display_name: string;
  account_number: string;
  member_since: string | null;
  role: string;
}

export interface FeedbackPost {
  id: string;
  board: FeedbackBoard;
  title: string;
  body: string;
  author: FeedbackAuthor;
  status: FeedbackStatus;
  /** Derived closure (sweep E5): true exactly when the status
   *  is done/declined — the post is closed to new comments and
   *  reads Closed everywhere it shows. */
  closed: boolean;
  status_note: string;
  urgency: FeedbackUrgency;
  visibility: "visible" | "held" | "removed_author" | "removed_mod";
  vote_count: number;
  comment_count: number;
  voted_by_me: boolean;
  mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface FeedbackComment {
  id: string;
  post_id: string;
  author: FeedbackAuthor;
  body: string;
  visibility: "visible" | "held" | "removed_author" | "removed_mod";
  mine: boolean;
  created_at: string;
}

export interface FeedbackPostDetail extends FeedbackPost {
  comments: FeedbackComment[];
}

export interface FeedbackReport {
  id: string;
  target_kind: "post" | "comment";
  target_id: string;
  post_id: string | null;
  post_title: string;
  target_excerpt: string;
  target_author_name: string;
  target_author_id: string | null;
  reporter_name: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface FeedbackHeld {
  id: string;
  target_kind: "post" | "comment";
  post_id: string;
  post_title: string;
  author_name: string;
  author_id: string;
  body: string;
  flags: string[];
  created_at: string;
}

/** Dictionary keys for the status words (the pill, the
 *  filter and the moderator form translate through these —
 *  STATUS_LABELS below stays the English fallback vocabulary). */
export const STATUS_LABEL_KEYS: Record<FeedbackStatus, string> = {
  open: "feedback.status.open",
  acknowledged: "feedback.status.acknowledged",
  planned: "feedback.status.planned",
  in_progress: "feedback.status.in_progress",
  done: "feedback.status.done",
  declined: "feedback.status.declined",
};

export const STATUS_LABELS: Record<FeedbackStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  planned: "Planned",
  in_progress: "In progress",
  done: "Done",
  declined: "Declined",
};

export const STATUS_TONES: Record<
  FeedbackStatus,
  "neutral" | "accent" | "warning" | "success" | "danger"
> = {
  open: "neutral",
  acknowledged: "accent",
  planned: "accent",
  in_progress: "warning",
  done: "success",
  declined: "danger",
};

/** Urgency wears its level's color everywhere it shows (the
 *  pill on rows, posts and Home widgets): low stays quiet,
 *  medium asks for attention, high calls out. */
export const URGENCY_TONES: Record<
  FeedbackUrgency,
  "neutral" | "warning" | "danger"
> = {
  low: "neutral",
  medium: "warning",
  high: "danger",
};

/** Dictionary keys for the urgency words (the pill and the
 *  toggle translate; STATUS_LABELS above predate the
 *  dictionaries and stay as they are). */
export const URGENCY_LABEL_KEYS: Record<FeedbackUrgency, string> = {
  low: "feedback.urgency.low",
  medium: "feedback.urgency.medium",
  high: "feedback.urgency.high",
};

export const URGENCY_LEVELS: FeedbackUrgency[] = ["low", "medium", "high"];
