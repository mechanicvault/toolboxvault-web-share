/** Community Forum API calls — thin typed wrappers over the
 *  shared client. Reading has the suite's two faces (signed-in
 *  and the anonymous /public twins, same payloads); writing
 *  rides the forum module gate + the paid-contribution gate,
 *  both enforced server-side. */

import { api } from "../../lib/api";
import type {
  CommunityBlock,
  ForumCategory,
  ForumFavorite,
  ForumFavoriteKind,
  ForumHeld,
  ForumPost,
  ForumReport,
  ForumThread,
  ForumThreadDetail,
} from "./types";

/* -- reads ------------------------------------------------------------------ */

export function getCategories(signedIn: boolean): Promise<ForumCategory[]> {
  return api<ForumCategory[]>(
    signedIn ? "/forum/categories" : "/forum/public/categories",
  );
}

export function getThreads(
  categoryId: string,
  signedIn: boolean,
): Promise<ForumThread[]> {
  return api<ForumThread[]>(
    signedIn
      ? `/forum/categories/${categoryId}/threads`
      : `/forum/public/categories/${categoryId}/threads`,
  );
}

export function getThread(
  threadId: string,
  signedIn: boolean,
): Promise<ForumThreadDetail> {
  return api<ForumThreadDetail>(
    signedIn ? `/forum/threads/${threadId}` : `/forum/public/threads/${threadId}`,
  );
}

export function searchThreads(q: string, signedIn: boolean): Promise<ForumThread[]> {
  const suffix = `?q=${encodeURIComponent(q)}`;
  return api<ForumThread[]>(
    signedIn ? `/forum/search${suffix}` : `/forum/public/search${suffix}`,
  );
}

/* -- writes ----------------------------------------------------------------- */

export interface LinkRef {
  link_type: "" | "part" | "listing";
  link_id: string | null;
}

export function createThread(body: {
  category_id: string;
  title: string;
  body: string;
} & LinkRef): Promise<ForumThreadDetail> {
  return api<ForumThreadDetail>("/forum/threads", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createReply(
  threadId: string,
  body: { body: string; quote_post_id: string | null } & LinkRef,
): Promise<ForumPost> {
  return api<ForumPost>(`/forum/threads/${threadId}/replies`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function editPost(postId: string, body: string): Promise<ForumPost> {
  return api<ForumPost>(`/forum/posts/${postId}`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
}

export function deletePost(postId: string): Promise<ForumPost> {
  return api<ForumPost>(`/forum/posts/${postId}`, { method: "DELETE" });
}

export function reportPost(postId: string, reason: string): Promise<ForumReport> {
  return api<ForumReport>(`/forum/posts/${postId}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

/* -- favorites (widget options Wave 3) ------------------------------------------
 * The member's own starred conversations, resolved live by the
 * server (invisible targets silently absent). One list is the
 * whole surface: the star toggles read it to learn their state,
 * the Home widget features one entry from it, and the widget's
 * options picker chooses from it. */

export function listFavorites(): Promise<ForumFavorite[]> {
  return api<ForumFavorite[]>("/forum/favorites");
}

export function starFavorite(
  kind: ForumFavoriteKind,
  targetId: string,
): Promise<ForumFavorite> {
  return api<ForumFavorite>("/forum/favorites", {
    method: "POST",
    body: JSON.stringify({ kind, target_id: targetId }),
  });
}

export function unstarFavorite(
  kind: ForumFavoriteKind,
  targetId: string,
): Promise<void> {
  return api<void>(`/forum/favorites/${kind}/${targetId}`, {
    method: "DELETE",
  });
}

export function getMyThreads(): Promise<ForumThread[]> {
  return api<ForumThread[]>("/forum/mine/threads");
}


/* -- moderation queue ---------------------------------------------------------- */

export function getForumReports(status = "open"): Promise<ForumReport[]> {
  return api<ForumReport[]>(`/forum/mod/reports?status_filter=${status}`);
}

export function getForumHeld(): Promise<ForumHeld[]> {
  return api<ForumHeld[]>("/forum/mod/held");
}

/* -- community blocks (admin lane, 2026-11-07) ------------------ */

export function listBlocks(activeOnly = true): Promise<CommunityBlock[]> {
  return api<CommunityBlock[]>(`/forum/mod/blocks?active_only=${activeOnly}`);
}

export function createBlock(body: {
  user_id?: string;
  account_number?: string;
  feature: string;
  reason?: string;
}): Promise<CommunityBlock> {
  return api<CommunityBlock>("/forum/mod/blocks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function liftBlock(blockId: string): Promise<CommunityBlock> {
  return api<CommunityBlock>(`/forum/mod/blocks/${blockId}/lift`, {
    method: "POST",
  });
}

export function getMyBlocks(): Promise<CommunityBlock[]> {
  return api<CommunityBlock[]>("/forum/mod/my-blocks");
}

export function dismissForumReport(
  reportId: string,
  resolution: string,
): Promise<ForumReport> {
  return api<ForumReport>(`/forum/mod/reports/${reportId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function releaseForumPost(postId: string): Promise<ForumHeld> {
  return api<ForumHeld>(`/forum/mod/posts/${postId}/release`, { method: "POST" });
}

export function discardForumPost(postId: string): Promise<ForumHeld> {
  return api<ForumHeld>(`/forum/mod/posts/${postId}/discard`, { method: "POST" });
}

export function removeForumPost(
  postId: string,
  resolution: string,
): Promise<ForumPost> {
  return api<ForumPost>(`/forum/mod/posts/${postId}/remove`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function setForumThreadPin(threadId: string, pinned: boolean): Promise<ForumThread> {
  return api<ForumThread>(`/forum/mod/threads/${threadId}/${pinned ? "pin" : "unpin"}`, {
    method: "POST",
  });
}

export function setForumThreadLock(threadId: string, locked: boolean): Promise<ForumThread> {
  return api<ForumThread>(`/forum/mod/threads/${threadId}/${locked ? "lock" : "unlock"}`, {
    method: "POST",
  });
}

/** Admin tier only (operator or community_admin — the server
 *  refuses moderators): HARD-delete the thread, all its posts
 *  and every report on them. Resolves with nothing on the 204. */
export function deleteForumThread(threadId: string): Promise<void> {
  return api<void>(`/forum/mod/threads/${threadId}`, { method: "DELETE" });
}

export function wipeForumPosts(
  userId: string,
): Promise<{ user_id: string; posts_removed: number }> {
  return api<{ user_id: string; posts_removed: number }>(
    `/forum/mod/users/${userId}/wipe-posts`,
    { method: "POST" },
  );
}

/* -- operator category furniture ----------------------------------------------- */

export function getAdminCategories(): Promise<ForumCategory[]> {
  return api<ForumCategory[]>("/forum/admin/categories");
}

export function createCategory(body: {
  name: string;
  description: string;
  sort_order: number;
}): Promise<ForumCategory> {
  return api<ForumCategory>("/forum/admin/categories", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateCategory(
  categoryId: string,
  body: Partial<{
    name: string;
    description: string;
    sort_order: number;
    is_active: boolean;
  }>,
): Promise<ForumCategory> {
  return api<ForumCategory>(`/forum/admin/categories/${categoryId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
