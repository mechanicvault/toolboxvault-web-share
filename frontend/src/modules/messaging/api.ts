/** Messaging module API calls — thin typed wrappers over the
 *  shared client (auth + refresh handled there). */

import { api } from "../../lib/api";
import type {
  BlockItem,
  HeldItem,
  ModThread,
  PublicProfile,
  ReportItem,
  ThreadDetail,
  ThreadSummary,
  UnreadSummary,
} from "./types";

export function listThreads(folder: "inbox" | "requests"): Promise<ThreadSummary[]> {
  return api<ThreadSummary[]>(`/messaging/threads?folder=${folder}`);
}

export function getUnread(): Promise<UnreadSummary> {
  return api<UnreadSummary>("/messaging/unread");
}

export function getThread(id: string): Promise<ThreadDetail> {
  return api<ThreadDetail>(`/messaging/threads/${id}`);
}

export function openThread(body: {
  recipient_id: string;
  body: string;
  anchor_type?: string;
  anchor_id?: string | null;
}): Promise<ThreadDetail> {
  return api<ThreadDetail>("/messaging/threads", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function postMessage(threadId: string, body: string) {
  return api(`/messaging/threads/${threadId}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function markRead(threadId: string): Promise<ThreadSummary> {
  return api<ThreadSummary>(`/messaging/threads/${threadId}/read`, {
    method: "POST",
  });
}

export function acceptRequest(threadId: string): Promise<ThreadSummary> {
  return api<ThreadSummary>(`/messaging/threads/${threadId}/accept`, {
    method: "POST",
  });
}

export function declineRequest(threadId: string): Promise<void> {
  return api<void>(`/messaging/threads/${threadId}/decline`, { method: "POST" });
}

export function reportThread(threadId: string, reason: string): Promise<void> {
  return api<void>(`/messaging/threads/${threadId}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function listBlocks(): Promise<BlockItem[]> {
  return api<BlockItem[]>("/messaging/blocks");
}

export function blockUser(userId: string): Promise<BlockItem> {
  return api<BlockItem>("/messaging/blocks", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function unblockUser(userId: string): Promise<void> {
  return api<void>(`/messaging/blocks/${userId}`, { method: "DELETE" });
}

export function lookupRecipient(
  accountNumber: string,
): Promise<{ user_id: string; display_name: string }> {
  return api(`/messaging/lookup?account_number=${encodeURIComponent(accountNumber)}`);
}

export function getPublicProfile(userId: string): Promise<PublicProfile> {
  return api<PublicProfile>(`/messaging/profiles/${userId}`);
}

// -- moderation queue (role ladder: moderator / community_admin /
// operator; the API enforces it) --------------------------------

export function listReports(status = "open"): Promise<ReportItem[]> {
  return api<ReportItem[]>(`/messaging/mod/reports?status_filter=${status}`);
}

export function listHeld(): Promise<HeldItem[]> {
  return api<HeldItem[]>("/messaging/mod/held");
}

export function getModThread(threadId: string): Promise<ModThread> {
  return api<ModThread>(`/messaging/mod/threads/${threadId}`);
}

export function dismissReport(reportId: string, resolution: string): Promise<ReportItem> {
  return api<ReportItem>(`/messaging/mod/reports/${reportId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function releaseMessage(messageId: string): Promise<HeldItem> {
  return api<HeldItem>(`/messaging/mod/messages/${messageId}/release`, {
    method: "POST",
  });
}

export function discardMessage(messageId: string): Promise<HeldItem> {
  return api<HeldItem>(`/messaging/mod/messages/${messageId}/discard`, {
    method: "POST",
  });
}

export function wipeMessage(messageId: string): Promise<HeldItem> {
  return api<HeldItem>(`/messaging/mod/messages/${messageId}/wipe`, {
    method: "POST",
  });
}

export function wipeAllFromUser(userId: string) {
  return api(`/messaging/mod/users/${userId}/wipe-messages`, { method: "POST" });
}

export function banUser(userId: string) {
  return api(`/messaging/mod/users/${userId}/ban`, { method: "POST" });
}
