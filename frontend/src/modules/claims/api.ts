/** Claims API calls — thin typed wrappers over the shared client
 *  (auth + refresh handled there).
 *
 *  Claims separation (2026-11-05): warranty claims live under
 *  /api/claims and DISASTER (insurance) claims under
 *  /api/disaster-claims — two sections, two modules, fully
 *  separated. The section-shared calls are built by `claimsApiFor`
 *  so both sections run the SAME client code against their own
 *  base path; the warranty-only calls (quick-create, agent
 *  routing, replace, the dealer worklist, the item panel) exist
 *  only on the claims side and stay plain exports below. */

import { api, apiBlob } from "../../lib/api";
import {
  fileContentType,
  type AttachmentKind,
} from "../inventory/components/photoTransfer";
import type {
  Claim,
  ClaimCommunication,
  ClaimEvidence,
  ClaimHeaderInput,
  ClaimLine,
  ClaimStatus,
  ClaimSummary,
  ClaimTargets,
  ClaimsStats,
  CommChannel,
  EvidenceKind,
  IncomingClaim,
  ItemClaims,
  ReplaceItemResult,
  TargetKind,
  ValueBasis,
  WarrantyCreateResult,
  WarrantyFilingOptions,
} from "./types";

export interface PackageDriveResult {
  filename: string;
  drive_file_id: string;
  drive_link: string;
  emailed: boolean;
  via: string;
}

export interface PackageEmailResult {
  filename: string;
  emailed: boolean;
  via: "attachment" | "drive_link";
  drive_file_id: string;
  drive_link: string;
}

export interface AddLineBody {
  target_kind: TargetKind;
  target_id: string;
  include_addons?: boolean;
  value_basis?: ValueBasis;
  amount?: string | null;
}

export interface CommunicationBody {
  channel: CommChannel;
  contact?: string;
  summary?: string;
  occurred_at?: string | null;
}

/** The calls both claim sections share, bound to one section's
 *  base path. */
export interface ClaimsSectionApi {
  getClaimsStats(): Promise<ClaimsStats>;
  getClaimTargets(): Promise<ClaimTargets>;
  listClaims(includeArchived?: boolean): Promise<ClaimSummary[]>;
  archiveClaim(claimId: string, archived: boolean): Promise<Claim>;
  duplicateClaim(claimId: string): Promise<Claim>;
  setLinePackage(
    claimId: string,
    lineId: string,
    includeInPackage: boolean,
  ): Promise<ClaimLine>;
  downloadClaimPackage(claimId: string, claimNumber: string): Promise<void>;
  saveClaimPackageToDrive(claimId: string): Promise<PackageDriveResult>;
  emailClaimPackage(claimId: string): Promise<PackageEmailResult>;
  getClaim(claimId: string): Promise<Claim>;
  createClaim(body: ClaimHeaderInput): Promise<Claim>;
  updateClaim(claimId: string, body: ClaimHeaderInput): Promise<Claim>;
  deleteClaim(claimId: string): Promise<void>;
  transitionClaim(
    claimId: string,
    toStatus: ClaimStatus,
    repair?: { repair_sent_to?: string; repair_cost?: string },
  ): Promise<Claim>;
  markProofOfLossSent(claimId: string, sentDate: string | null): Promise<Claim>;
  addClaimLine(claimId: string, body: AddLineBody): Promise<ClaimLine>;
  removeClaimLine(claimId: string, lineId: string): Promise<void>;
  addEvidenceReference(
    claimId: string,
    body: {
      item_kind: "tool" | "battery" | "piece";
      item_id: string;
      attachment_key: string;
    },
  ): Promise<ClaimEvidence>;
  removeEvidence(claimId: string, evidenceId: string): Promise<void>;
  uploadClaimEvidence(
    claimId: string,
    kind: EvidenceKind,
    file: File,
  ): Promise<ClaimEvidence>;
  addCommunication(
    claimId: string,
    body: CommunicationBody,
  ): Promise<ClaimCommunication>;
  updateCommunication(
    claimId: string,
    entryId: string,
    body: Partial<CommunicationBody>,
  ): Promise<ClaimCommunication>;
  deleteCommunication(claimId: string, entryId: string): Promise<void>;
}

export function claimsApiFor(base: string): ClaimsSectionApi {
  return {
    getClaimsStats: () => api<ClaimsStats>(`${base}/stats`),

    getClaimTargets: () => api<ClaimTargets>(`${base}/targets`),

    listClaims: (includeArchived = false) =>
      api<ClaimSummary[]>(
        includeArchived ? `${base}?include_archived=true` : base,
      ),

    archiveClaim: (claimId, archived) =>
      api<Claim>(`${base}/${claimId}/archive`, {
        method: "POST",
        body: JSON.stringify({ archived }),
      }),

    duplicateClaim: (claimId) =>
      api<Claim>(`${base}/${claimId}/duplicate`, { method: "POST" }),

    setLinePackage: (claimId, lineId, includeInPackage) =>
      api<ClaimLine>(`${base}/${claimId}/lines/${lineId}/package`, {
        method: "PATCH",
        body: JSON.stringify({ include_in_package: includeInPackage }),
      }),

    /** The claim package PDF: summary + included items (values +
     * photos), the evidence list, the police block, the comms log. */
    downloadClaimPackage: async (claimId, claimNumber) => {
      const blob = await apiBlob(`${base}/${claimId}/package`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `claim-package-${claimNumber}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    },

    /** Audit A10: save the package PDF to the owner's Drive. */
    saveClaimPackageToDrive: (claimId) =>
      api<PackageDriveResult>(`${base}/${claimId}/package/drive`, {
        method: "POST",
      }),

    /** Audit A10: email the package (attachment, or Drive link
     *  when the package is too large to attach). */
    emailClaimPackage: (claimId) =>
      api<PackageEmailResult>(`${base}/${claimId}/package/email`, {
        method: "POST",
      }),

    getClaim: (claimId) => api<Claim>(`${base}/${claimId}`),

    createClaim: (body) =>
      api<Claim>(base, { method: "POST", body: JSON.stringify(body) }),

    updateClaim: (claimId, body) =>
      api<Claim>(`${base}/${claimId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),

    deleteClaim: (claimId) =>
      api<void>(`${base}/${claimId}`, { method: "DELETE" }),

    transitionClaim: (claimId, toStatus, repair) =>
      api<Claim>(`${base}/${claimId}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: toStatus, ...(repair ?? {}) }),
      }),

    markProofOfLossSent: (claimId, sentDate) =>
      api<Claim>(`${base}/${claimId}/proof-of-loss-sent`, {
        method: "POST",
        body: JSON.stringify({ sent_date: sentDate }),
      }),

    addClaimLine: (claimId, body) =>
      api<ClaimLine>(`${base}/${claimId}/lines`, {
        method: "POST",
        body: JSON.stringify(body),
      }),

    removeClaimLine: (claimId, lineId) =>
      api<void>(`${base}/${claimId}/lines/${lineId}`, { method: "DELETE" }),

    addEvidenceReference: (claimId, body) =>
      api<ClaimEvidence>(`${base}/${claimId}/evidence`, {
        method: "POST",
        body: JSON.stringify(body),
      }),

    removeEvidence: (claimId, evidenceId) =>
      api<void>(`${base}/${claimId}/evidence/${evidenceId}`, {
        method: "DELETE",
      }),

    /**
     * Upload one file as claim-specific evidence: presigned URL →
     * direct PUT → attach (the same two-step as item attachments,
     * at the section's endpoints). Throws on failure; the caller
     * surfaces it.
     */
    uploadClaimEvidence: async (claimId, kind, file) => {
      const contentType = fileContentType(file);
      const { upload_url, key } = await api<{
        upload_url: string;
        key: string;
        expires_in: number;
      }>(`${base}/${claimId}/evidence/upload-url`, {
        method: "POST",
        body: JSON.stringify({
          kind: kind as AttachmentKind,
          filename: file.name,
          content_type: contentType,
          size_bytes: file.size,
        }),
      });
      const put = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": contentType },
        body: file,
      });
      if (!put.ok) throw new Error(`Upload failed (HTTP ${put.status})`);
      return api<ClaimEvidence>(`${base}/${claimId}/evidence/attach`, {
        method: "POST",
        body: JSON.stringify({ key, filename: file.name }),
      });
    },

    addCommunication: (claimId, body) =>
      api<ClaimCommunication>(`${base}/${claimId}/communications`, {
        method: "POST",
        body: JSON.stringify(body),
      }),

    updateCommunication: (claimId, entryId, body) =>
      api<ClaimCommunication>(`${base}/${claimId}/communications/${entryId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),

    deleteCommunication: (claimId, entryId) =>
      api<void>(`${base}/${claimId}/communications/${entryId}`, {
        method: "DELETE",
      }),
  };
}

/** The warranty Claims section's API (base /claims). */
export const claimsApi = claimsApiFor("/claims");

/** The Disaster Claims section's API (base /disaster-claims). */
export const disasterClaimsApi = claimsApiFor("/disaster-claims");

/* -- the warranty section's named exports (existing callers) --------------- */

export const getClaimsStats = claimsApi.getClaimsStats;
export const getClaimTargets = claimsApi.getClaimTargets;
export const listClaims = claimsApi.listClaims;
export const archiveClaim = claimsApi.archiveClaim;
export const duplicateClaim = claimsApi.duplicateClaim;
export const setLinePackage = claimsApi.setLinePackage;
export const downloadClaimPackage = claimsApi.downloadClaimPackage;
export const saveClaimPackageToDrive = claimsApi.saveClaimPackageToDrive;
export const emailClaimPackage = claimsApi.emailClaimPackage;
export const getClaim = claimsApi.getClaim;
export const createClaim = claimsApi.createClaim;
export const updateClaim = claimsApi.updateClaim;
export const deleteClaim = claimsApi.deleteClaim;
export const transitionClaim = claimsApi.transitionClaim;
export const markProofOfLossSent = claimsApi.markProofOfLossSent;
export const addClaimLine = claimsApi.addClaimLine;
export const removeClaimLine = claimsApi.removeClaimLine;
export const addEvidenceReference = claimsApi.addEvidenceReference;
export const removeEvidence = claimsApi.removeEvidence;
export const uploadClaimEvidence = claimsApi.uploadClaimEvidence;
export const addCommunication = claimsApi.addCommunication;
export const updateCommunication = claimsApi.updateCommunication;
export const deleteCommunication = claimsApi.deleteCommunication;

/* -- warranty-only calls (no disaster twin) --------------------------------- */

/** One item's claims, current + history (dealer intermingling —
 *  the block on the tool/battery pages). Warranty only: the item
 *  Claims / Replace tab never carries insurance claims. Rejects
 *  with module_unavailable when the claims module is off for the
 *  user; the panel hides on any error, like its siblings. */
export function getItemClaims(
  itemKind: "tool" | "battery",
  itemId: string,
): Promise<ItemClaims> {
  return api<ItemClaims>(`/claims/for-item/${itemKind}/${itemId}`);
}

/** Start a warranty claim from a broken item (or one set piece).
 *  The claim is born live with its item on it; the answer says
 *  whether the agent has been told and through what. Agent scope
 *  (2026-10-31): the claim runs through ONE of the owner's
 *  agents for the dealer — the ids below pick one explicitly,
 *  no_agent says "I'll handle it myself"; omit all three and the
 *  claim takes the owner's agent on record. */
export function createWarrantyClaim(body: {
  target_kind: TargetKind;
  target_id: string;
  include_addons?: boolean;
  dealer_notified: boolean;
  problem?: string;
  agent_user_id?: string | null;
  private_agent_id?: string | null;
  no_agent?: boolean;
  /** Ryan's filing routes (2026-11-05 #6): "agent" | "self" |
   *  "corporate" — when sent it decides the claim's counterparty
   *  seat outright (the agent ids / no_agent still serve the
   *  agent and self routes' details). */
  filed_with?: "agent" | "self" | "corporate";
}): Promise<WarrantyCreateResult> {
  return api<WarrantyCreateResult>("/claims/warranty", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** The filing form's agent step for one target: the dealer the
 *  claim will name and the owner's agents on record for it. */
export function getWarrantyFilingOptions(
  targetKind: TargetKind,
  targetId: string,
): Promise<WarrantyFilingOptions> {
  return api<WarrantyFilingOptions>(
    `/claims/warranty/agent-options?target_kind=${targetKind}` +
      `&target_id=${encodeURIComponent(targetId)}`,
  );
}

/** Re-point a warranty claim at a different agent (or none).
 *  Owner-only; the backend refuses insurance claims and closed
 *  warranty claims. */
export function setClaimAgent(
  claimId: string,
  body: { agent_user_id?: string | null; private_agent_id?: string | null },
): Promise<Claim> {
  return api<Claim>(`/claims/${claimId}/agent`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/** The broken prompt's Replace: retire the old item, and (mode
 *  "same") create its exact replacement at the amount spent. */
export function replaceItem(body: {
  item_kind: "tool" | "battery";
  item_id: string;
  mode: "same" | "different";
  amount_spent?: number | null;
}): Promise<ReplaceItemResult> {
  return api<ReplaceItemResult>("/claims/replace-item", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** The agent side's worklist: warranty claims currently routed
 *  to the signed-in user as an agent (agent scope, 2026-10-31 —
 *  claims addressed to their company but routed to a different
 *  agent never appear). Gated server-side on the dealers module;
 *  callers hide the section on any error. */
export function listIncomingClaims(): Promise<IncomingClaim[]> {
  return api<IncomingClaim[]>("/claims/incoming");
}
