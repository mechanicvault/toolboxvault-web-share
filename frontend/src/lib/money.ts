import { useEffect, useState } from "react";

import { api, TOKEN_KEY } from "./api";

/**
 * THE money formatter (wave 3, 2026-10-20) — the frontend mirror
 * of the backend's ONE formatter (core/money.py). Every money
 * string the client renders goes through here:
 *
 * - symbol currencies: "$1,234.56" / "€1,234.56" (symbol first);
 * - other currencies: "1,234.56 CAD" (code after, one space);
 * - zero-decimal currencies render whole: "¥12,345";
 * - negatives lead with "-": "-$5.00".
 *
 * V1 SEMANTICS: an account's amounts are IN its currency; stored
 * amounts never convert. Your own surfaces render in YOUR
 * currency (the viewer currency below, set by the auth provider
 * from /core/me). Cross-user surfaces (marketplace, parts pool,
 * public profiles) render in the SELLER's currency — the payload
 * carries `seller_currency` — and may add an approximate hint
 * (MoneyHint) when the viewer's currency differs.
 */

const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CNY: "¥",
  INR: "₹",
  KRW: "₩",
  BRL: "R$",
  PLN: "zł",
  ILS: "₪",
  TRY: "₺",
  ZAR: "R",
};

const ZERO_DECIMAL = new Set(["JPY", "KRW", "HUF"]);

export function normalizeCurrency(code: string | null | undefined): string {
  const candidate = (code ?? "").trim().toUpperCase();
  return candidate.length === 3 ? candidate : "USD";
}

export function formatMoney(
  value: string | number | null | undefined,
  currency?: string | null,
  whole = false,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  const code = normalizeCurrency(currency ?? viewerCurrency);
  const places = whole || ZERO_DECIMAL.has(code) ? 0 : 2;
  const rounded =
    places === 0 ? Math.round(n) : Math.round(n * 100) / 100;
  const sign = rounded < 0 ? "-" : "";
  const digits = Math.abs(rounded).toLocaleString("en-US", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
  const symbol = SYMBOLS[code];
  return symbol ? `${sign}${symbol}${digits}` : `${sign}${digits} ${code}`;
}

// -- the viewer currency -------------------------------------------------------
//
// A tiny module store: the auth provider sets it from /core/me
// (and after profile edits); formatters default to it, so the
// existing call sites keep their one-argument shape while their
// output becomes currency-aware.

let viewerCurrency = "USD";
const listeners = new Set<(code: string) => void>();

export function setViewerCurrency(code: string | null | undefined): void {
  const next = normalizeCurrency(code);
  if (next === viewerCurrency) return;
  viewerCurrency = next;
  listeners.forEach((fn) => fn(next));
}


/** Subscribe a component to the viewer's currency. */
export function useViewerCurrency(): string {
  const [code, setCode] = useState(viewerCurrency);
  useEffect(() => {
    const fn = (next: string) => setCode(next);
    listeners.add(fn);
    setCode(viewerCurrency);
    return () => {
      listeners.delete(fn);
    };
  }, []);
  return code;
}

// -- approximate hints -----------------------------------------------------------

interface HintResponse {
  hint: string | null;
  viewer_currency: string;
}

const hintCache = new Map<string, string | null>();

/**
 * The approximate converted hint for a cross-user amount ("≈
 * $108.70"), or null — when the currencies match, when no rates
 * are cached, or signed out. DISPLAY ONLY, always approximate;
 * the stored amount never changes. Fetched lazily per
 * (amount, from) pair and cached for the page's lifetime.
 */
export function useMoneyHint(
  amount: string | number | null | undefined,
  fromCurrency: string | null | undefined,
): string | null {
  const viewer = useViewerCurrency();
  const from = normalizeCurrency(fromCurrency);
  const [hint, setHint] = useState<string | null>(null);
  useEffect(() => {
    if (
      amount === null ||
      amount === undefined ||
      amount === "" ||
      from === viewer ||
      !localStorage.getItem(TOKEN_KEY)
    ) {
      setHint(null);
      return;
    }
    const key = `${amount}|${from}|${viewer}`;
    if (hintCache.has(key)) {
      setHint(hintCache.get(key) ?? null);
      return;
    }
    let alive = true;
    api<HintResponse>(
      `/core/money/hint?amount=${encodeURIComponent(String(amount))}&from_currency=${from}`,
    )
      .then((res) => {
        hintCache.set(key, res.hint);
        if (alive) setHint(res.hint);
      })
      .catch(() => {
        hintCache.set(key, null);
        if (alive) setHint(null);
      });
    return () => {
      alive = false;
    };
  }, [amount, from, viewer]);
  return hint;
}
