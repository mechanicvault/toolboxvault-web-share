/** Feedback boards API calls — thin typed wrappers over the
 *  shared client. Reading has the suite's two faces (the plain
 *  routes and the /public twins, same payloads) — both are
 *  MEMBERS-ONLY since 2026-11-10: the server refuses anonymous
 *  callers on either face, and the pages render a sign-in door
 *  instead of ever calling signed-out. The twins stay so old
 *  links resolve to the door rather than a dead route. Writing
 *  rides the feedback module gate — but NOT a paid gate: any
 *  signed-in account may post (Ryan's ruling: open feedback). */

import { api } from "../../lib/api";
import type {
  FeedbackBoard,
  FeedbackComment,
  FeedbackHeld,
  FeedbackPost,
  FeedbackPostDetail,
  FeedbackReport,
  FeedbackSort,
  FeedbackStatus,
  FeedbackUrgency,
} from "./types";

/* -- reads ------------------------------------------------------------------ */

export function getBoard(
  board: FeedbackBoard,
  signedIn: boolean,
  statusFilter = "",
  sort: FeedbackSort = "new",
): Promise<FeedbackPost[]> {
  const params: string[] = [];
  if (statusFilter) params.push(`status_filter=${encodeURIComponent(statusFilter)}`);
  if (sort !== "new") params.push(`sort=${encodeURIComponent(sort)}`);
  const suffix = params.length ? `?${params.join("&")}` : "";
  return api<FeedbackPost[]>(
    signedIn
      ? `/feedback/boards/${board}${suffix}`
      : `/feedback/public/boards/${board}${suffix}`,
  );
}

export function getPost(
  postId: string,
  signedIn: boolean,
): Promise<FeedbackPostDetail> {
  return api<FeedbackPostDetail>(
    signedIn ? `/feedback/posts/${postId}` : `/feedback/public/posts/${postId}`,
  );
}

export function getMine(
  board: FeedbackBoard | "",
  sort: FeedbackSort = "new",
): Promise<FeedbackPost[]> {
  const params: string[] = [];
  if (board) params.push(`board=${encodeURIComponent(board)}`);
  if (sort !== "new") params.push(`sort=${encodeURIComponent(sort)}`);
  const suffix = params.length ? `?${params.join("&")}` : "";
  return api<FeedbackPost[]>(`/feedback/mine${suffix}`);
}

/* -- writes (any signed-in account) ------------------------------------------ */

export function createPost(body: {
  board: FeedbackBoard;
  title: string;
  body: string;
  urgency: FeedbackUrgency;
}): Promise<FeedbackPost> {
  return api<FeedbackPost>("/feedback/posts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function toggleVote(postId: string): Promise<FeedbackPost> {
  return api<FeedbackPost>(`/feedback/posts/${postId}/vote`, { method: "POST" });
}

export function createComment(
  postId: string,
  body: string,
): Promise<FeedbackComment> {
  return api<FeedbackComment>(`/feedback/posts/${postId}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

export function deletePost(postId: string): Promise<FeedbackPost> {
  return api<FeedbackPost>(`/feedback/posts/${postId}`, { method: "DELETE" });
}

export function deleteComment(commentId: string): Promise<FeedbackComment> {
  return api<FeedbackComment>(`/feedback/comments/${commentId}`, {
    method: "DELETE",
  });
}

export function reportTarget(body: {
  target_kind: "post" | "comment";
  target_id: string;
  reason: string;
}): Promise<FeedbackReport> {
  return api<FeedbackReport>("/feedback/reports", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* -- moderation --------------------------------------------------------------- */

export function setPostStatus(
  postId: string,
  status: FeedbackStatus,
  note: string,
): Promise<FeedbackPost> {
  return api<FeedbackPost>(`/feedback/posts/${postId}/status`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });
}

/** The moderator urgency lever — the ONLY urgency write
 *  after filing (the filer's token gets a 403 here; their
 *  picker locked at submission). */
export function setPostUrgency(
  postId: string,
  urgency: FeedbackUrgency,
): Promise<FeedbackPost> {
  return api<FeedbackPost>(`/feedback/posts/${postId}/urgency`, {
    method: "POST",
    body: JSON.stringify({ urgency }),
  });
}

export function getFeedbackReports(
  statusFilter = "open",
): Promise<FeedbackReport[]> {
  return api<FeedbackReport[]>(
    `/feedback/mod/reports?status_filter=${encodeURIComponent(statusFilter)}`,
  );
}

export function dismissFeedbackReport(
  reportId: string,
  note = "",
): Promise<FeedbackReport> {
  return api<FeedbackReport>(`/feedback/mod/reports/${reportId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function getFeedbackHeld(): Promise<FeedbackHeld[]> {
  return api<FeedbackHeld[]>("/feedback/mod/held");
}

export function releaseFeedbackTarget(
  targetKind: "post" | "comment",
  targetId: string,
): Promise<FeedbackHeld> {
  return api<FeedbackHeld>(`/feedback/mod/targets/${targetKind}/${targetId}/release`, {
    method: "POST",
  });
}

export function discardFeedbackTarget(
  targetKind: "post" | "comment",
  targetId: string,
): Promise<FeedbackHeld> {
  return api<FeedbackHeld>(`/feedback/mod/targets/${targetKind}/${targetId}/discard`, {
    method: "POST",
  });
}

export function removeFeedbackTarget(
  targetKind: "post" | "comment",
  targetId: string,
  reason = "",
): Promise<FeedbackHeld> {
  return api<FeedbackHeld>(`/feedback/mod/targets/${targetKind}/${targetId}/remove`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
