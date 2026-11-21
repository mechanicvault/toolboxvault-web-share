/** Tools For Sale module API calls — thin typed wrappers over
 *  the shared client (auth + refresh handled there). The board
 *  has the suite's two faces: signed-in (module-gated owner
 *  surfaces alongside) and the anonymous public board. */

import { api } from "../../lib/api";
import type {
  BuyerCandidate,
  Interaction,
  ListingFormValues,
  OwnerListing,
  PublicListing,
  PublicReputation,
  RatingReport,
  ThreadCompletion,
} from "./types";

export interface BoardQuery {
  q?: string;
  listing_type?: string;
  price_min?: string;
  price_max?: string;
  area?: string;
  seller_id?: string;
  sort?: "newest" | "price_asc" | "price_desc" | "rating";
}

function queryString(query: BoardQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value);
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function getBoard(query: BoardQuery = {}): Promise<PublicListing[]> {
  return api<PublicListing[]>(`/marketplace/board${queryString(query)}`);
}

export function getPublicBoard(query: BoardQuery = {}): Promise<PublicListing[]> {
  return api<PublicListing[]>(`/marketplace/public/board${queryString(query)}`);
}

export function getPublicListing(id: string): Promise<PublicListing> {
  return api<PublicListing>(`/marketplace/public/board/${id}`);
}

export function listMine(): Promise<OwnerListing[]> {
  return api<OwnerListing[]>("/marketplace/mine");
}

export function createListing(body: Record<string, unknown>): Promise<OwnerListing> {
  return api<OwnerListing>("/marketplace/listings", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateListing(
  id: string,
  values: Partial<ListingFormValues>,
): Promise<OwnerListing> {
  return api<OwnerListing>(`/marketplace/listings/${id}`, {
    method: "PUT",
    body: JSON.stringify(values),
  });
}

export function deleteListing(id: string): Promise<void> {
  return api<void>(`/marketplace/listings/${id}`, { method: "DELETE" });
}

export function markSold(
  id: string,
  body: { buyer_user_id?: string; buyer_account_number?: string },
): Promise<OwnerListing> {
  return api<OwnerListing>(`/marketplace/listings/${id}/sold`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function removeListing(id: string): Promise<OwnerListing> {
  return api<OwnerListing>(`/marketplace/listings/${id}/remove`, { method: "POST" });
}

export function reactivateListing(id: string): Promise<OwnerListing> {
  return api<OwnerListing>(`/marketplace/listings/${id}/reactivate`, {
    method: "POST",
  });
}

export function getBuyerCandidates(id: string): Promise<BuyerCandidate[]> {
  return api<BuyerCandidate[]>(`/marketplace/listings/${id}/buyer-candidates`);
}

// -- reputation ----------------------------------------------------

export function listMyInteractions(): Promise<Interaction[]> {
  return api<Interaction[]>("/marketplace/interactions/mine");
}

export function submitRating(
  interactionId: string,
  stars: number,
  text: string,
): Promise<Interaction> {
  return api<Interaction>(`/marketplace/interactions/${interactionId}/rating`, {
    method: "POST",
    body: JSON.stringify({ stars, text }),
  });
}

export function getPublicReputation(userId: string): Promise<PublicReputation> {
  return api<PublicReputation>(`/marketplace/reputation/${userId}`);
}

// -- rating moderation (gap wave 1) --------------------------------

export function reportRating(ratingId: string, reason: string): Promise<RatingReport> {
  return api<RatingReport>(`/marketplace/ratings/${ratingId}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function listRatingReports(status = "open"): Promise<RatingReport[]> {
  return api<RatingReport[]>(`/marketplace/mod/rating-reports?status_filter=${status}`);
}

export function dismissRatingReport(id: string, resolution = ""): Promise<RatingReport> {
  return api<RatingReport>(`/marketplace/mod/rating-reports/${id}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function removeRatingReport(id: string, resolution = ""): Promise<RatingReport> {
  return api<RatingReport>(`/marketplace/mod/rating-reports/${id}/remove`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function getThreadCompletion(threadId: string): Promise<ThreadCompletion> {
  return api<ThreadCompletion>(`/marketplace/threads/${threadId}/completion`);
}

export function completeThread(threadId: string): Promise<ThreadCompletion> {
  return api<ThreadCompletion>(`/marketplace/threads/${threadId}/complete`, {
    method: "POST",
  });
}
