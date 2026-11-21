import { api } from "../../lib/api";
import { fetchLookupPhoto } from "../catalog/api";
import { uploadPhotoFile } from "./components/photoTransfer";
import type { Tool } from "./types";

/**
 * Row 199: bring lookup-seeded piece photos in through the
 * server fetch (the sanctioned, SSRF-guarded path) as soon
 * as they're applied — outside image hosts are blocked by
 * the site's security policy, so the page URL alone can't
 * preview in the editor, while the fetched file previews
 * locally and uploads at save like any picked photo. A
 * piece whose fetch fails keeps its page URL: the server
 * attach at save remains its fallback. Reports each success
 * as (index, file) so the caller can update its drafts.
 */
export async function fetchSeededPiecePhotos(
  drafts: { photo_url?: string }[],
  onFetched: (index: number, file: File) => void,
): Promise<void> {
  await Promise.all(
    drafts.map(async (draft, index) => {
      const url = draft.photo_url;
      if (!url) return;
      try {
        const file = await fetchLookupPhoto(url);
        onFetched(index, file);
      } catch {
        // Keep the page URL — the save's server attach is
        // this piece's fallback.
      }
    }),
  );
}

/** The slice of a piece draft the photo pass needs. */
export interface PiecePhotoDraft {
  id?: string;
  kind: "core" | "addon";
  name: string;
  photo_file?: File | null;
}

/**
 * Row 199: upload the photos users picked for individual set
 * pieces once the tool exists. Drafts for existing pieces
 * carry their piece id and upload straight to it; new drafts
 * are matched to the saved pieces by kind + order, and a
 * match is only trusted when the saved piece's name agrees —
 * a mismatch uploads nothing rather than the wrong photo to
 * the wrong piece. Best-effort throughout: a failed piece
 * photo never fails the save it rode in on.
 */
export async function uploadDraftPiecePhotos(
  toolId: string,
  drafts: PiecePhotoDraft[],
): Promise<void> {
  if (!drafts.some((d) => d.photo_file)) return;
  const pools: Record<string, { id: string; name: string }[]> = {
    core: [],
    addon: [],
  };
  if (drafts.some((d) => d.photo_file && !d.id)) {
    try {
      const tool = await api<Tool>(`/inventory/${toolId}`);
      pools.core = (tool.set?.core_pieces ?? []).map((p) => ({
        id: p.id,
        name: p.name,
      }));
      pools.addon = (tool.set?.addon_pieces ?? []).map((p) => ({
        id: p.id,
        name: p.name,
      }));
    } catch {
      return;
    }
  }
  const counters: Record<string, number> = { core: 0, addon: 0 };
  for (const draft of drafts) {
    const index = counters[draft.kind]++;
    if (!draft.photo_file) continue;
    let pieceId: string | undefined = draft.id;
    if (!pieceId) {
      const candidate = pools[draft.kind][index];
      if (
        candidate &&
        candidate.name.trim().toLowerCase() ===
          draft.name.trim().toLowerCase()
      ) {
        pieceId = candidate.id;
      }
    }
    if (!pieceId) continue;
    try {
      await uploadPhotoFile(`/inventory/pieces/${pieceId}`, draft.photo_file);
    } catch {
      // Best effort — the piece keeps whatever photo it had.
    }
  }
}
