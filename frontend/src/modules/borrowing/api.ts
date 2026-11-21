/** Borrowing module API calls — thin typed wrappers over the shared
 *  client (auth + refresh handled there). */

import { api, apiBlob, TOKEN_KEY } from "../../lib/api";
import type {
  BorrowRequestCreate,
  BorrowerContact,
  BorrowerRollup,
  BorrowingOverview,
  Checkout,
  CheckoutCreateRequest,
  CheckoutItemKind,
  Counterparty,
  ItemLending,
  NudgeResult,
} from "./types";

export function getBorrowingOverview(): Promise<BorrowingOverview> {
  return api<BorrowingOverview>("/borrowing/overview");
}


export function getCounterparties(): Promise<Counterparty[]> {
  return api<Counterparty[]>("/borrowing/counterparties");
}

export function createCheckout(body: CheckoutCreateRequest): Promise<Checkout> {
  return api<Checkout>("/borrowing/checkouts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createBorrowRequest(body: BorrowRequestCreate): Promise<Checkout> {
  return api<Checkout>("/borrowing/requests", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getItemLending(
  itemKind: CheckoutItemKind,
  itemId: string,
): Promise<ItemLending> {
  return api<ItemLending>(`/borrowing/items/${itemKind}/${itemId}`);
}

function transition(id: string, action: "approve" | "decline" | "cancel" | "return") {
  return api<Checkout>(`/borrowing/${id}/${action}`, { method: "POST" });
}

export function approveCheckout(id: string): Promise<Checkout> {
  return transition(id, "approve");
}

export function declineCheckout(id: string): Promise<Checkout> {
  return transition(id, "decline");
}

export function cancelCheckout(id: string): Promise<Checkout> {
  return transition(id, "cancel");
}

export function returnCheckout(id: string): Promise<Checkout> {
  return transition(id, "return");
}

// -- borrower address book (gap wave 1) ---------------------------

export function listBorrowers(): Promise<BorrowerContact[]> {
  return api<BorrowerContact[]>("/borrowing/borrowers");
}

export function createBorrower(body: {
  name: string;
  contact?: string;
  notes?: string;
  linked_user_id?: string | null;
}): Promise<BorrowerContact> {
  return api<BorrowerContact>("/borrowing/borrowers", {
    method: "POST",
    body: JSON.stringify(body),
  });
}


export function deleteBorrower(id: string): Promise<void> {
  return api<void>(`/borrowing/borrowers/${id}`, { method: "DELETE" });
}

export function getBorrowerRollup(id: string): Promise<BorrowerRollup> {
  return api<BorrowerRollup>(`/borrowing/borrowers/${id}`);
}

export function nudgeCheckout(id: string): Promise<NudgeResult> {
  return api<NudgeResult>(`/borrowing/${id}/nudge`, { method: "POST" });
}

// -- contact cards: vCard export / import (contact cards lane) -----------

export function exportBorrowersFile(): Promise<Blob> {
  return apiBlob("/borrowing/borrowers/export.vcf");
}

export function exportBorrowerFile(id: string): Promise<Blob> {
  return apiBlob(`/borrowing/borrowers/${id}/export.vcf`);
}

export interface BorrowerImportPreviewRow {
  index: number;
  name: string;
  contact: string;
  notes: string;
  duplicate: boolean;
  duplicate_of: string | null;
}

export interface BorrowerImportPreview {
  rows: BorrowerImportPreviewRow[];
  errors: { index: number; message: string }[];
  total_cards: number;
}

/** Upload a .vcf for the preview (multipart — the inventory
 *  importer's fetch pattern: the shared client speaks JSON). */
export async function previewBorrowerImport(
  file: File,
): Promise<BorrowerImportPreview> {
  const token = localStorage.getItem(TOKEN_KEY);
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/borrowing/borrowers/import/preview", {
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
  return (await response.json()) as BorrowerImportPreview;
}

export function importBorrowers(
  rows: { name: string; contact: string; notes: string }[],
): Promise<{ created: BorrowerContact[]; count: number }> {
  return api<{ created: BorrowerContact[]; count: number }>(
    "/borrowing/borrowers/import",
    { method: "POST", body: JSON.stringify({ contacts: rows }) },
  );
}
