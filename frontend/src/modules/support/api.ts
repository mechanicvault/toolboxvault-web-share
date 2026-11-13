import { api } from "../../lib/api";

/**
 * Support module client (Home + Header program, 2026-10-24):
 * thin wrappers over the support module's own endpoints — the
 * module owns its data; the help page and the admin desk both
 * read through here.
 */
export type TicketStatus = "open" | "under_review" | "closed";

export interface TicketSummary {
  id: string;
  subject: string;
  status: TicketStatus;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string;
  /** Whose message is newest: "user" | "operator" | "" — the
   *  help page's status strip reads a ticket whose newest
   *  message is the team's as waiting on the member. */
  last_message_author_kind: "user" | "operator" | "";
}

export interface TicketMessage {
  id: string;
  author_kind: "user" | "operator";
  body: string;
  created_at: string;
}

export interface TicketDetail extends TicketSummary {
  messages: TicketMessage[];
}

export interface AdminTicketSummary extends TicketSummary {
  user_name: string;
  user_email: string;
  user_account_number: string;
}

export interface AdminTicketDetail extends TicketDetail {
  user_name: string;
  user_email: string;
  user_account_number: string;
}

export function listMyTickets(): Promise<TicketSummary[]> {
  return api<TicketSummary[]>("/support/tickets");
}

export function getMyTicket(id: string): Promise<TicketDetail> {
  return api<TicketDetail>(`/support/tickets/${id}`);
}

export function createTicket(subject: string, body: string): Promise<TicketDetail> {
  return api<TicketDetail>("/support/tickets", {
    method: "POST",
    body: JSON.stringify({ subject, body }),
  });
}

export function replyToMyTicket(id: string, body: string): Promise<TicketDetail> {
  return api<TicketDetail>(`/support/tickets/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function adminListTickets(status?: TicketStatus): Promise<AdminTicketSummary[]> {
  const q = status ? `?status=${status}` : "";
  return api<AdminTicketSummary[]>(`/admin/support/tickets${q}`);
}

export function adminGetTicket(id: string): Promise<AdminTicketDetail> {
  return api<AdminTicketDetail>(`/admin/support/tickets/${id}`);
}

export function adminReply(id: string, body: string): Promise<AdminTicketDetail> {
  return api<AdminTicketDetail>(`/admin/support/tickets/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function adminSetStatus(id: string, status: TicketStatus): Promise<AdminTicketDetail> {
  return api<AdminTicketDetail>(`/admin/support/tickets/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

/* -- how-to videos (Help & Support build, 2026-11-02) --------- */

export type HelpVideoSection = "website" | "app";

export interface HelpVideo {
  id: string;
  title: string;
  summary: string;
  youtube_id: string;
  section: HelpVideoSection;
  sort_order: number;
}

export interface AdminHelpVideo extends HelpVideo {
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

export interface HelpVideoWrite {
  title: string;
  summary: string;
  /** A YouTube watch/short/embed URL or the bare video id —
   *  the server normalizes it to the id. */
  youtube: string;
  section: HelpVideoSection;
  sort_order: number;
  is_published: boolean;
}

export function listPublishedVideos(): Promise<HelpVideo[]> {
  return api<HelpVideo[]>("/support/videos");
}

export function adminListVideos(): Promise<AdminHelpVideo[]> {
  return api<AdminHelpVideo[]>("/admin/support/videos");
}

export function adminCreateVideo(body: HelpVideoWrite): Promise<AdminHelpVideo> {
  return api<AdminHelpVideo>("/admin/support/videos", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function adminUpdateVideo(
  id: string,
  body: HelpVideoWrite,
): Promise<AdminHelpVideo> {
  return api<AdminHelpVideo>(`/admin/support/videos/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function adminDeleteVideo(id: string): Promise<void> {
  return api<void>(`/admin/support/videos/${id}`, { method: "DELETE" });
}
