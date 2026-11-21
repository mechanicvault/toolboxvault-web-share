/** Wishlist types — mirroring backend/app/modules/wishlist/schemas.py. */

export type WishlistPriority = "low" | "normal" | "high";
export type WishlistStatus = "wanted" | "purchased";

export interface WishlistAttachment {
  key: string;
  filename: string;
  kind: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string | null;
  url: string;
}

export interface WishlistItem {
  id: string;
  title: string;
  link_url: string;
  /** Decimal string; null = no target set. */
  target_price: string | null;
  priority: WishlistPriority;
  dealer_company_id: string | null;
  dealer_name: string | null;
  notes: string;
  attachments: WishlistAttachment[];
  status: WishlistStatus;
  purchased_price: string | null;
  purchased_on: string | null;
  converted_tool_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WishlistWrite {
  title: string;
  link_url: string;
  target_price: string | null;
  priority: WishlistPriority;
  dealer_company_id: string | null;
  notes: string;
}
