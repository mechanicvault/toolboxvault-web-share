/** Wishlist API calls — thin typed wrappers over the shared client. */

import { api } from "../../lib/api";
import type { WishlistItem, WishlistWrite } from "./types";

export function listWishlist(q?: string): Promise<WishlistItem[]> {
  const suffix = q ? `?q=${encodeURIComponent(q)}` : "";
  return api<WishlistItem[]>(`/wishlist/items${suffix}`);
}

export function createWishlistItem(body: WishlistWrite): Promise<WishlistItem> {
  return api<WishlistItem>("/wishlist/items", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateWishlistItem(
  id: string,
  body: Partial<WishlistWrite>,
): Promise<WishlistItem> {
  return api<WishlistItem>(`/wishlist/items/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteWishlistItem(id: string): Promise<void> {
  return api<void>(`/wishlist/items/${id}`, { method: "DELETE" });
}

export function markPurchased(
  id: string,
  body: { purchased_price: string; purchased_on: string | null },
): Promise<WishlistItem> {
  return api<WishlistItem>(`/wishlist/items/${id}/mark-purchased`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function convertToTool(
  id: string,
): Promise<{ item: WishlistItem }> {
  return api<{ item: WishlistItem }>(`/wishlist/items/${id}/convert`, {
    method: "POST",
  });
}
