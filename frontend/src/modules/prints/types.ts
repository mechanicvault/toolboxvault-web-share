/** 3D Print Files wire types — the service views in
 * backend/app/modules/prints/service.py, mirrored. */

export interface PrintPublisher {
  user_id: string;
  display_name: string;
  account_number: string;
}

export interface PrintRatingView {
  average: number | null;
  count: number;
}

export interface PrintFileRow {
  id: string;
  title: string;
  description: string;
  category: string;
  publisher: PrintPublisher;
  status: string;
  current_version: number;
  download_count: number;
  step_download_count: number;
  rating: PrintRatingView;
  my_rating: number | null;
  /** My per-file update opt-in (sweep E4): true only for a
   * signed-in viewer who follows this file. */
  following: boolean;
  has_preview: boolean;
  mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface PrintVersion {
  version_number: number;
  note: string;
  print_filename: string;
  print_size: number;
  has_step: boolean;
  step_filename: string;
  downloads: number;
  step_downloads: number;
  created_at: string;
}

export interface MakerLink {
  id: string;
  label: string;
  url: string;
}

/** One showcase media item on a listing (0095): a photo
 * (up to five) or the listing's one video. One order across
 * both kinds — the Photos / Video tab's tiles and the
 * preview viewer's walk. The first PHOTO is the cover. */
export interface PrintMedia {
  id: string;
  kind: "photo" | "video";
  content_type: string;
  filename: string;
  size_bytes: number;
  duration_seconds: number | null;
  sort_order: number;
}

export interface PrintDetail extends PrintFileRow {
  media: PrintMedia[];
  versions: PrintVersion[];
  maker_links: MakerLink[];
  comment_count: number;
}

export interface PrintComment {
  id: string;
  file_id: string;
  author: PrintPublisher;
  body: string;
  status: string;
  mine: boolean;
  edited_at: string | null;
  created_at: string;
}

export interface PrintReport {
  id: string;
  target_kind: string;
  file_id: string;
  file_title: string;
  file_status: string;
  comment_id: string | null;
  comment_status: string;
  comment_excerpt: string;
  comment_author_id: string | null;
  reporter_id: string;
  reporter_name: string;
  reason: string;
  status: string;
  resolution: string;
  created_at: string;
}

/** The shelf's own category set (backend categories.py order);
 * display names live in the dictionary as prints.category.*. */
export const PRINT_CATEGORIES = [
  "tool-holders",
  "toolbox-drawer",
  "socket-wrench",
  "diagnostic-aids",
  "shop-fixtures",
  "battery-mounts",
  "air-tool",
  "vehicle-specific",
  "parts-trays",
  "other-shop",
] as const;
