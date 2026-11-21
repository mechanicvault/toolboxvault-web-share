/** Used Parts module API calls — thin typed wrappers over the
 *  shared client (auth + refresh handled there). */

import { api } from "../../lib/api";
import type {
  CommunityListing,
  ConvertResult,
  Part,
  PartLocation,
  PartsStats,
  PartWrite,
  PoolSettings,
} from "./types";

export function getPartsStats(): Promise<PartsStats> {
  return api<PartsStats>("/parts/stats");
}

export function listLocations(): Promise<PartLocation[]> {
  return api<PartLocation[]>("/parts/locations");
}

export function createLocation(body: {
  name: string;
  level: string;
  parent_id: string | null;
}): Promise<PartLocation> {
  return api<PartLocation>("/parts/locations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateLocation(
  id: string,
  body: { name?: string; level?: string; parent_id?: string | null },
): Promise<PartLocation> {
  return api<PartLocation>(`/parts/locations/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteLocation(
  id: string,
  body: { reassign_to_id?: string; detach?: boolean },
): Promise<void> {
  return api<void>(`/parts/locations/${id}`, {
    method: "DELETE",
    body: JSON.stringify(body),
  });
}

export function listParts(params: {
  q?: string;
  location_id?: string;
  condition?: string;
}): Promise<Part[]> {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.location_id) query.set("location_id", params.location_id);
  if (params.condition) query.set("condition", params.condition);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<Part[]>(`/parts/parts${suffix}`);
}

export function getPart(id: string): Promise<Part> {
  return api<Part>(`/parts/parts/${id}`);
}

export function createPart(body: PartWrite): Promise<Part> {
  return api<Part>("/parts/parts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updatePart(id: string, body: Partial<PartWrite>): Promise<Part> {
  return api<Part>(`/parts/parts/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deletePart(id: string): Promise<void> {
  return api<void>(`/parts/parts/${id}`, { method: "DELETE" });
}

export function convertToTool(id: string): Promise<ConvertResult> {
  return api<ConvertResult>(`/parts/parts/${id}/convert-to-tool`, {
    method: "POST",
  });
}

// -- community pool ---------------------------------------------------

export function getPoolSettings(): Promise<PoolSettings> {
  return api<PoolSettings>("/parts/pool/settings");
}

export function updatePoolSettings(body: Partial<PoolSettings>): Promise<PoolSettings> {
  return api<PoolSettings>("/parts/pool/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export interface CommunityFilters {
  q?: string;
  year?: string;
  make?: string;
  model?: string;
  engine?: string;
  category?: string;
  seller_id?: string;
}

function communityQuery(filters: CommunityFilters): string {
  const query = new URLSearchParams();
  if (filters.q) query.set("q", filters.q);
  if (filters.year) query.set("year", filters.year);
  if (filters.make) query.set("make", filters.make);
  if (filters.model) query.set("model", filters.model);
  if (filters.engine) query.set("engine", filters.engine);
  if (filters.category) query.set("category", filters.category);
  if (filters.seller_id) query.set("seller_id", filters.seller_id);
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

/** The pool for signed-in users. */
export function listCommunity(filters: CommunityFilters): Promise<CommunityListing[]> {
  return api<CommunityListing[]>(`/parts/community${communityQuery(filters)}`);
}

/** The pool for logged-out visitors — the public twin route
 *  (same payload; the shared client simply has no token to send). */
export function listCommunityPublic(
  filters: CommunityFilters,
): Promise<CommunityListing[]> {
  return api<CommunityListing[]>(`/parts/public/community${communityQuery(filters)}`);
}
