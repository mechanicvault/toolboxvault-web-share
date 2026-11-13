import { api, apiBlob, TOKEN_KEY } from "../../lib/api";
import type {
  AgentProfile,
  AgentProfileWrite,
  CompanyDetail,
  CompanyMyRecords,
  DealerCompany,
  DealerCompanyPersonalWrite,
  DealerCompanyWrite,
  DealerPortalStats,
  PreferredAgent,
  PreferredSummary,
  PrivateAgent,
  PrivateAgentWrite,
  Representation,
  RepresentationAdmin,
  TakeoverEnterResult,
  TakeoverMine,
  TakeoverRequest,
} from "./types";

/** Dealers module API (backend: app/modules/dealers). Every call
 *  403s with module_unavailable when the module is off or unassigned
 *  for the user — callers that embed dealer UI in other modules
 *  (the item dealer picker, the agents panel) treat that as "hide",
 *  never as an error worth surfacing. */

export function listCompanies(): Promise<DealerCompany[]> {
  return api<DealerCompany[]>("/dealers/companies");
}

export function createPrivateCompany(body: DealerCompanyWrite): Promise<DealerCompany> {
  return api<DealerCompany>("/dealers/companies", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateCompany(id: string, body: DealerCompanyWrite): Promise<DealerCompany> {
  return api<DealerCompany>(`/dealers/companies/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteCompany(id: string): Promise<void> {
  return api<void>(`/dealers/companies/${id}`, { method: "DELETE" });
}

/** Personal edits (2026-11-05): save MY details for a directory
 *  dealer (writes my personal layer only — the directory record
 *  is never touched), and clear them (Reset). */
export function savePersonalCompanyEdit(
  id: string,
  body: DealerCompanyPersonalWrite,
): Promise<DealerCompany> {
  return api<DealerCompany>(`/dealers/companies/${id}/personal-edit`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function clearPersonalCompanyEdit(id: string): Promise<void> {
  return api<void>(`/dealers/companies/${id}/personal-edit`, {
    method: "DELETE",
  });
}

export function listPrivateAgents(): Promise<PrivateAgent[]> {
  return api<PrivateAgent[]>("/dealers/agents/private");
}

export function createPrivateAgent(body: PrivateAgentWrite): Promise<PrivateAgent> {
  return api<PrivateAgent>("/dealers/agents/private", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updatePrivateAgent(id: string, body: PrivateAgentWrite): Promise<PrivateAgent> {
  return api<PrivateAgent>(`/dealers/agents/private/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deletePrivateAgent(id: string): Promise<void> {
  return api<void>(`/dealers/agents/private/${id}`, { method: "DELETE" });
}

export function listPreferred(companyId?: string): Promise<PreferredAgent[]> {
  const query = companyId ? `?company_id=${companyId}` : "";
  return api<PreferredAgent[]>(`/dealers/preferred${query}`);
}

/** The caller's preferred-agent SUMMARY for one company
 *  (owner ruling 2026-11-06): "one" with the agent when
 *  exactly one preferred agent is flagged — the item pages'
 *  agent line and the Warranty tab's agent row name him;
 *  "many" (agent null) when more than one is flagged — those
 *  displays show "Multiple Agents" instead; "none" when the
 *  caller has no agent for the company. */
export function getPreferredSummary(
  companyId: string,
): Promise<PreferredSummary> {
  return api<PreferredSummary>(
    `/dealers/preferred/on-record?company_id=${encodeURIComponent(companyId)}`,
  );
}

export function addPreferred(body: {
  company_id: string;
  private_agent_id?: string;
  agent_account_number?: string;
}): Promise<PreferredAgent> {
  return api<PreferredAgent>("/dealers/preferred", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function removePreferred(id: string): Promise<void> {
  return api<void>(`/dealers/preferred/${id}`, { method: "DELETE" });
}

/* -- The roster + the preferred star (stage 1, 2026-11-04;
 *    multi-preferred, 2026-11-05) ----------------------------------- */

import type { RosterAgentDetail, RosterEntry } from "./types";

/** The company's roster for the caller: his own agent records +
 *  the platform agents he is connected with, preferred agents
 *  starred and leading their section. */
export function getRoster(
  companyId: string,
  asVisitor = false,
): Promise<RosterEntry[]> {
  return api<RosterEntry[]>(
    asVisitor
      ? `/dealers/companies/${companyId}/roster?as_visitor=true`
      : `/dealers/companies/${companyId}/roster`,
  );
}

/** One agent's full record, opened from the roster: the record,
 *  his claims seated with the caller, and the truck slot. */
export function getRosterAgent(
  companyId: string,
  kind: "private" | "platform",
  refId: string,
): Promise<RosterAgentDetail> {
  return api<RosterAgentDetail>(
    `/dealers/companies/${companyId}/roster/agent?kind=${kind}&ref_id=${encodeURIComponent(refId)}`,
  );
}

/** One roster agent's contact card (.vcf) — the same roster
 *  authorization as the record view (contact cards lane). */
export function exportAgentCardFile(
  companyId: string,
  kind: "private" | "platform",
  refId: string,
): Promise<Blob> {
  return apiBlob(
    `/dealers/companies/${companyId}/roster/agent/export.vcf?kind=${kind}&ref_id=${encodeURIComponent(refId)}`,
  );
}

/* -- Contact cards: vCard import into PRIVATE agents (agent
 *    card import lane, 2026-11-07) ---------------------------------- */

export interface AgentImportDuplicate {
  company_id: string;
  company_name: string;
  duplicate_of: string;
}

export interface AgentImportPreviewRow {
  index: number;
  name: string;
  phone: string;
  email: string;
  org: string;
  location: string;
  notes: string;
  suggested_company_id: string | null;
  suggested_company_name: string | null;
  duplicate: boolean;
  duplicate_of: string | null;
  duplicates: AgentImportDuplicate[];
}

export interface AgentImportPreview {
  rows: AgentImportPreviewRow[];
  errors: { index: number; message: string }[];
  total_cards: number;
}

/** Upload a .vcf for the agent-import preview (multipart — the
 *  borrowing importer's fetch pattern: the shared client
 *  speaks JSON). Creates nothing. */
export async function previewAgentImport(
  file: File,
): Promise<AgentImportPreview> {
  const token = localStorage.getItem(TOKEN_KEY);
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/dealers/agents/import/preview", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!response.ok) {
    let message = `Upload failed (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(message);
  }
  return (await response.json()) as AgentImportPreview;
}

export interface AgentImportRowBody {
  name: string;
  company_id: string;
  phone: string;
  email: string;
  location: string;
  notes: string;
}

/** Create exactly the confirmed rows as PRIVATE agent records. */
export function importAgents(
  rows: AgentImportRowBody[],
): Promise<{ created: PrivateAgent[]; count: number }> {
  return api<{ created: PrivateAgent[]; count: number }>(
    "/dealers/agents/import",
    { method: "POST", body: JSON.stringify({ agents: rows }) },
  );
}

/** Star or unstar ONE roster agent as preferred
 *  (multi-preferred, 2026-11-05): per-agent and independent —
 *  starring never unstars another agent, never stamps tenure
 *  and never moves a claim. (The stage-1 switch endpoints are
 *  gone; there is nothing to switch.) */
export function setAgentPreferred(body: {
  company_id: string;
  private_agent_id?: string;
  agent_user_id?: string;
  is_preferred: boolean;
}): Promise<PreferredAgent> {
  return api<PreferredAgent>("/dealers/preferred/flag", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* -- My dealer list (owner directive, 2026-10-31) -------------------- */

import type {
  DealerListEntry,
  DealerListEntryWrite,
  DealerListRestoreResult,
  DealerListSettings,
  DealerPickList,
} from "./types";

/** The dealer-entry pick list for the signed-in user: directory
 *  minus the brands they removed, their private companies, and
 *  their unspent list entries. */
export function getPickList(): Promise<DealerPickList> {
  return api<DealerPickList>("/dealers/pick-list");
}

export function getDealerListSettings(): Promise<DealerListSettings> {
  return api<DealerListSettings>("/dealers/list-settings");
}

export function hideDirectoryCompany(companyId: string): Promise<DealerListSettings> {
  return api<DealerListSettings>("/dealers/directory-hidden", {
    method: "POST",
    body: JSON.stringify({ company_id: companyId }),
  });
}

export function unhideDirectoryCompany(companyId: string): Promise<DealerListSettings> {
  return api<DealerListSettings>(`/dealers/directory-hidden/${companyId}`, {
    method: "DELETE",
  });
}

export function createListEntry(body: DealerListEntryWrite): Promise<DealerListEntry> {
  return api<DealerListEntry>("/dealers/list-entries", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateListEntry(
  id: string,
  body: DealerListEntryWrite,
): Promise<DealerListEntry> {
  return api<DealerListEntry>(`/dealers/list-entries/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteListEntry(id: string): Promise<void> {
  return api<void>(`/dealers/list-entries/${id}`, { method: "DELETE" });
}

/** Pick an entry: mints (once) the user's private company from
 *  the entry's fields and returns it; later picks return the
 *  same company. */
export function useListEntry(id: string): Promise<DealerCompany> {
  return api<DealerCompany>(`/dealers/list-entries/${id}/use`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function restoreDealerList(): Promise<DealerListRestoreResult> {
  return api<DealerListRestoreResult>("/dealers/list-restore", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getCompanyDetail(id: string): Promise<CompanyDetail> {
  return api<CompanyDetail>(`/dealers/companies/${id}/detail`);
}

/** "View as visitor" preview fetches (Sweep D5): the
 * representative-only reads that return this company's page
 * shaped for a signed-in member with no relationship to it —
 * the server runs the same serializers with the visitor
 * stand-in, so what lands here IS the real plain-member data
 * shape (raw directory company, no preferred agents, the
 * empty records set, an empty roster). */
export function getCompanyDetailAsVisitor(id: string): Promise<CompanyDetail> {
  return api<CompanyDetail>(`/dealers/companies/${id}/detail?as_visitor=true`);
}

export function getCompanyMyRecordsAsVisitor(
  id: string,
): Promise<CompanyMyRecords> {
  return api<CompanyMyRecords>(
    `/dealers/companies/${id}/my-records?as_visitor=true`,
  );
}

/** The viewer's own records for one company (dealer
 *  intermingling): their items from it, honest stats, and their
 *  claims touching it — claims null when the claims module is
 *  off for the viewer. */
export function getCompanyMyRecords(id: string): Promise<CompanyMyRecords> {
  return api<CompanyMyRecords>(`/dealers/companies/${id}/my-records`);
}

/* -- Dealer portal: my agent profile --------------------------------- */

export function getMyProfile(): Promise<AgentProfile> {
  return api<AgentProfile>("/dealers/profile/me");
}

export function updateMyProfile(body: AgentProfileWrite): Promise<AgentProfile> {
  return api<AgentProfile>("/dealers/profile/me", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

function putFile(url: string, file: File, contentType: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error(`Upload failed (HTTP ${xhr.status})`));
    xhr.onerror = () => reject(new Error("Upload failed — check your connection."));
    xhr.send(file);
  });
}

/** Profile photo: presigned URL -> direct PUT -> attach (the shared
 *  attachment flow, photo kind — see photoTransfer for items). */
export async function uploadProfilePhoto(file: File): Promise<AgentProfile> {
  const contentType = file.type || "image/jpeg";
  const issued = await api<{ upload_url: string; key: string }>(
    "/dealers/profile/me/photo/upload-url",
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: contentType,
        size_bytes: file.size,
      }),
    },
  );
  await putFile(issued.upload_url, file, contentType);
  return api<AgentProfile>("/dealers/profile/me/photo", {
    method: "POST",
    body: JSON.stringify({ key: issued.key, filename: file.name }),
  });
}

export function removeProfilePhoto(): Promise<AgentProfile> {
  return api<AgentProfile>("/dealers/profile/me/photo", { method: "DELETE" });
}

export function listMyRepresentations(): Promise<Representation[]> {
  return api<Representation[]>("/dealers/profile/me/representations");
}

export function addRepresentation(companyId: string): Promise<Representation> {
  return api<Representation>("/dealers/profile/me/representations", {
    method: "POST",
    body: JSON.stringify({ company_id: companyId }),
  });
}

export function removeRepresentation(id: string): Promise<void> {
  return api<void>(`/dealers/profile/me/representations/${id}`, {
    method: "DELETE",
  });
}

/* -- One-tap preferred + the private -> platform switch --------------- */

export function addPreferredByAgent(body: {
  company_id: string;
  agent_user_id: string;
}): Promise<{ created: boolean; preferred: PreferredAgent }> {
  return api("/dealers/preferred/by-agent", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function linkPrivateAgent(
  id: string,
  accountNumber: string,
): Promise<PrivateAgent> {
  return api<PrivateAgent>(`/dealers/agents/private/${id}/link`, {
    method: "POST",
    body: JSON.stringify({ agent_account_number: accountNumber }),
  });
}

export function unlinkPrivateAgent(id: string): Promise<PrivateAgent> {
  return api<PrivateAgent>(`/dealers/agents/private/${id}/unlink`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

/* -- Agent-code takeover (2026-11-03) ---------------------------------- */

/** Enter a code a customer handed me: creates the takeover
 *  REQUEST (the customer still has to accept). Wrong codes come
 *  back as a generic 422; known states resolve as outcomes. */
export function enterAgentCode(code: string): Promise<TakeoverEnterResult> {
  return api<TakeoverEnterResult>("/dealers/agents/takeover/enter-code", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

/** My code-entry asks + the customer records I have taken over. */
export function getTakeoverMine(): Promise<TakeoverMine> {
  return api<TakeoverMine>("/dealers/agents/takeover/mine");
}

/** Pending takeover asks on ONE of my records (owner side). */
export function listTakeoverRequests(agentId: string): Promise<TakeoverRequest[]> {
  return api<TakeoverRequest[]>(
    `/dealers/agents/private/${agentId}/takeover-requests`,
  );
}

export function acceptTakeoverRequest(requestId: string): Promise<PrivateAgent> {
  return api<PrivateAgent>(`/dealers/agents/takeover/${requestId}/accept`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function declineTakeoverRequest(requestId: string): Promise<void> {
  return api<void>(`/dealers/agents/takeover/${requestId}/decline`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getDealerStats(): Promise<DealerPortalStats> {
  return api<DealerPortalStats>("/dealers/stats");
}

/** Operator surface: the platform directory itself. */
export function listDirectoryAdmin(): Promise<DealerCompany[]> {
  return api<DealerCompany[]>("/admin/dealer-companies");
}

export function createDirectoryCompany(body: DealerCompanyWrite): Promise<DealerCompany> {
  return api<DealerCompany>("/admin/dealer-companies", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateDirectoryCompany(
  id: string,
  body: DealerCompanyWrite,
): Promise<DealerCompany> {
  return api<DealerCompany>(`/admin/dealer-companies/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteDirectoryCompany(id: string): Promise<void> {
  return api<void>(`/admin/dealer-companies/${id}`, { method: "DELETE" });
}

/** Operator surface: representation review (verify/unverify). */
export function listRepresentationsAdmin(): Promise<RepresentationAdmin[]> {
  return api<RepresentationAdmin[]>("/admin/dealer-representations");
}

export function setRepresentationVerified(
  id: string,
  verified: boolean,
): Promise<RepresentationAdmin> {
  return api<RepresentationAdmin>(`/admin/dealer-representations/${id}/verify`, {
    method: "PUT",
    body: JSON.stringify({ verified }),
  });
}

/* -- Find an Agent + warranty requests (dealer build) ------------------ */

import type {
  FindAgentResult,
  FindLocalAgentResult,
  GeocodeResult,
  WarrantyCounts,
  WarrantyEligibility,
  WarrantyRequest,
} from "./types";

export function findAgents(
  q: string,
  companyId?: string,
): Promise<FindAgentResult> {
  const query = companyId
    ? `?q=${encodeURIComponent(q)}&company_id=${companyId}`
    : `?q=${encodeURIComponent(q)}`;
  return api<FindAgentResult>(`/dealers/find-agent${query}`);
}

/* -- Find local Agent (stage 3): the reusable ZIP + radius seam.
 * companyId scopes to agents with a verified representation of
 * that dealer; omit it for the site-wide search. */

export function findLocalAgents(
  zip: string,
  radiusMiles: number,
  companyId?: string,
): Promise<FindLocalAgentResult> {
  const params = new URLSearchParams({
    zip_code: zip,
    radius_miles: String(radiusMiles),
  });
  if (companyId) params.set("company_id", companyId);
  return api<FindLocalAgentResult>(`/dealers/find-local-agent?${params}`);
}

/* -- Dealers near you (dashboard widget, widget wave 2): the
 * viewer's own ZIP (their profile postal address, read
 * server-side) through the find-local search. Always resolves —
 * a missing/unknown ZIP is a state in the payload. */

import type { NearYouResult } from "./types";

export function getNearYou(radiusMiles: number): Promise<NearYouResult> {
  return api<NearYouResult>(
    `/dealers/near-you?radius_miles=${encodeURIComponent(String(radiusMiles))}`,
  );
}

export function connectLocalAgent(body: {
  company_id: string;
  agent_user_id: string;
}): Promise<{ created: boolean; preferred: PreferredAgent }> {
  return api("/dealers/find-local-agent/connect", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function geocodePlace(q: string): Promise<GeocodeResult> {
  return api<GeocodeResult>(`/dealers/geocode?q=${encodeURIComponent(q)}`);
}

export function warrantyEligibility(
  claimId: string,
): Promise<WarrantyEligibility> {
  return api<WarrantyEligibility>(
    `/dealers/warranty-requests/eligibility/${claimId}`,
  );
}

export function sendWarrantyRequest(
  claimId: string,
): Promise<WarrantyRequest> {
  return api<WarrantyRequest>("/dealers/warranty-requests", {
    method: "POST",
    body: JSON.stringify({ claim_id: claimId }),
  });
}

export function listMyWarrantyRequests(): Promise<WarrantyRequest[]> {
  return api<WarrantyRequest[]>("/dealers/warranty-requests/mine");
}

export function listIncomingWarrantyRequests(): Promise<WarrantyRequest[]> {
  return api<WarrantyRequest[]>("/dealers/warranty-requests/incoming");
}

export function warrantyCounts(): Promise<WarrantyCounts> {
  return api<WarrantyCounts>("/dealers/warranty-requests/counts");
}

export function claimWarrantyRequest(id: string): Promise<WarrantyRequest> {
  return api<WarrantyRequest>(`/dealers/warranty-requests/${id}/claim`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function setWarrantyStatus(
  id: string,
  status: string,
): Promise<WarrantyRequest> {
  return api<WarrantyRequest>(`/dealers/warranty-requests/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
}

/** The anonymous twin: read-only cards, no contact actions —
 *  reading is public, contacting takes an account. */
export function findAgentsPublic(
  q: string,
  companyId?: string,
): Promise<FindAgentResult> {
  const query = companyId
    ? `?q=${encodeURIComponent(q)}&company_id=${companyId}`
    : `?q=${encodeURIComponent(q)}`;
  return api<FindAgentResult>(`/dealers/public/find-agent${query}`);
}
