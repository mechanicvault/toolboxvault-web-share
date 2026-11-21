/** Messaging module shapes — mirror backend/app/modules/messaging/schemas.py. */

export interface MessageItem {
  id: string;
  thread_id: string;
  sender_id: string;
  mine: boolean;
  body: string;
  /** "sent" | "held" | "removed" (own shadow sends read "sent" —
   *  the block is silent by design). */
  status: string;
  /** True while MY message sits in the moderation hold. */
  held: boolean;
  removed: boolean;
  flags: string[];
  has_links: boolean;
  /** True while the thread is at request stage: render links
   *  inert behind the quarantine warning. */
  links_disabled: boolean;
  created_at: string;
  seq: number;
}

export interface ThreadSummary {
  id: string;
  other_user_id: string;
  other_name: string;
  anchor_type: string;
  anchor_id: string | null;
  anchor_title: string;
  /** "request" | "accepted" */
  status: string;
  /** "incoming" | "outgoing" | "accepted" */
  direction: string;
  unread_count: number;
  other_last_read_seq: number | null;
  last_message_at: string | null;
  last_message_preview: string;
  last_message_sender_id: string | null;
  last_message_mine: boolean;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ThreadDetail extends ThreadSummary {
  messages: MessageItem[];
}

export interface UnreadSummary {
  inbox_unread: number;
  requests_count: number;
}

export interface BlockItem {
  user_id: string;
  name: string;
  created_at: string;
}

export interface ReputationSummary {
  average: number | null;
  count: number;
  completed_deals: number;
}

export interface PublicProfile {
  user_id: string;
  display_name: string;
  member_since: string;
  area_label: string | null;
  show_phone: boolean;
  /** Present ONLY while the owner opted in. */
  phone: string | null;
  reputation: ReputationSummary;
}

export interface ReportItem {
  id: string;
  thread_id: string;
  reporter_id: string;
  reporter_name: string;
  reason: string;
  status: string;
  resolution: string;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
  anchor_title: string;
  participant_names: string[];
}

export interface HeldItem {
  id: string;
  thread_id: string;
  sender_id: string;
  sender_name: string;
  recipient_id: string | null;
  recipient_name: string;
  body: string;
  status: string;
  flags: string[];
  anchor_title: string;
  created_at: string;
}

export interface ModMessage {
  id: string;
  sender_id: string;
  sender_name: string;
  body: string;
  status: string;
  flags: string[];
  created_at: string;
  seq: number;
}

export interface ModThread {
  id: string;
  participant_low_id: string;
  participant_high_id: string;
  participant_names: string[];
  anchor_type: string;
  anchor_id: string | null;
  anchor_title: string;
  status: string;
  created_at: string;
  messages: ModMessage[];
}
