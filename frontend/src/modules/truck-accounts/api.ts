/** Truck Accounts API calls — thin typed wrappers over the
 *  shared client. */

import { api, apiBlob } from "../../lib/api";
import type {
  IssuableCompany,
  SelfOpenInput,
  SelfOpenTarget,
  TruckAccount,
  TruckAccountDetail,
  TruckDashboard,
  TruckEntry,
  TruckPaymentRequest,
  TruckStatusSummary,
} from "./types";

export function listAccounts(): Promise<TruckAccount[]> {
  return api<TruckAccount[]>("/truck-accounts/accounts");
}

export function createAccount(body: {
  customer_account_number: string;
  customer_email: string;
  payment_cadence: string;
  payment_amount: string | null;
  next_due_date: string | null;
  dealer_company_id: string | null;
  credit_limit: string | null;
}): Promise<TruckAccount> {
  return api<TruckAccount>("/truck-accounts/accounts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getIssuableCompanies(): Promise<IssuableCompany[]> {
  return api<IssuableCompany[]>("/truck-accounts/issuable-companies");
}

export function getStatusSummary(): Promise<TruckStatusSummary> {
  return api<TruckStatusSummary>("/truck-accounts/status-summary");
}

export function transferAccount(
  id: string,
  body: {
    to_agent_user_id: string | null;
    to_private_agent_id: string | null;
  },
): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/transfer`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getAccount(id: string): Promise<TruckAccountDetail> {
  return api<TruckAccountDetail>(`/truck-accounts/accounts/${id}`);
}

export function acceptAccount(
  id: string,
  agreementVersion: string,
): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ agreement_version: agreementVersion }),
  });
}

export function declineAccount(id: string): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/decline`, {
    method: "POST",
  });
}

export function closeAccount(id: string): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/close`, {
    method: "POST",
  });
}

export function updateSchedule(
  id: string,
  body: {
    payment_cadence?: string;
    payment_amount?: string;
    next_due_date?: string;
  },
): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/schedule`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function addEntry(
  id: string,
  body: {
    kind: string;
    amount: string;
    note: string;
    item_link_id: string | null;
    entry_date: string | null;
  },
): Promise<TruckEntry> {
  return api<TruckEntry>(`/truck-accounts/accounts/${id}/entries`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getDealerDashboard(): Promise<TruckDashboard> {
  return api<TruckDashboard>("/truck-accounts/dealer/dashboard");
}

// -- Stage 2: the mechanic's seat ---------------------------------------------

export function openSelfAccount(body: SelfOpenInput): Promise<TruckAccount> {
  return api<TruckAccount>("/truck-accounts/accounts/self", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getSelfCompanies(): Promise<IssuableCompany[]> {
  return api<IssuableCompany[]>("/truck-accounts/accounts/self/companies");
}

export function getSelfTargets(companyId: string): Promise<SelfOpenTarget[]> {
  return api<SelfOpenTarget[]>(
    `/truck-accounts/accounts/self/targets?company_id=${encodeURIComponent(companyId)}`,
  );
}

export function setPaymentMode(
  id: string,
  paymentMode: "manual" | "automatic",
): Promise<TruckAccount> {
  return api<TruckAccount>(`/truck-accounts/accounts/${id}/payment-mode`, {
    method: "POST",
    body: JSON.stringify({ payment_mode: paymentMode }),
  });
}

export function requestPayment(
  id: string,
  body: { amount: string; note?: string },
): Promise<TruckPaymentRequest> {
  return api<TruckPaymentRequest>(
    `/truck-accounts/accounts/${id}/payment-requests`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function decidePaymentRequest(
  id: string,
  requestId: string,
  decision: "approve" | "decline",
  note: string,
): Promise<TruckPaymentRequest> {
  return api<TruckPaymentRequest>(
    `/truck-accounts/accounts/${id}/payment-requests/${requestId}/${decision}`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

/** The per-account statement (the reports document machinery
 *  renders it): PDF for print, CSV for the books. */
export function downloadStatement(
  id: string,
  fmt: "pdf" | "csv",
): Promise<Blob> {
  return apiBlob(`/truck-accounts/accounts/${id}/statement?fmt=${fmt}`);
}
