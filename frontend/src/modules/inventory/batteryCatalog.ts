/**
 * The battery pick list (Wizard Phase 1, 2026-10-25 — Ryan's
 * battery fork: "batteries are very easy to just have an auto
 * populated list to choose from instead of having to input each
 * and everything — just pick your battery from a list").
 *
 * A code-held seed of the common cordless-tool battery packs
 * across the major US platforms. Picking an entry pre-fills the
 * battery's brand, platform, model number, voltage, capacity
 * and chemistry, and composes its name; every value stays
 * editable before saving, and the wizard's manual path covers
 * anything not listed. Model numbers are the manufacturers'
 * stamped pack numbers as published in their catalogs at seed
 * time (2026-10-25); where a pack is sold under several numbers
 * the most common one is used.
 *
 * This list is deliberately NOT the community catalog: it is a
 * fixed starter vocabulary, identical for every account. (A
 * future Ryan decision may grow a shared list from user-entered
 * batteries; v1 keeps manual entries the user's own.)
 */

export interface BatteryCatalogEntry {
  brand: string;
  platform: string;
  /** The stamped model number ("" when the pack is commonly
   *  sold under several numbers — the user can type theirs). */
  model: string;
  /** The pack's shelf name, e.g. "REDLITHIUM XC5.0". */
  label: string;
  voltage: number;
  capacityAh: number;
  chemistry: string;
}

const LI = "Li-ion";

function pack(
  brand: string,
  platform: string,
  model: string,
  label: string,
  voltage: number,
  capacityAh: number,
): BatteryCatalogEntry {
  return { brand, platform, model, label, voltage, capacityAh, chemistry: LI };
}

export const BATTERY_CATALOG: BatteryCatalogEntry[] = [
  // -- Milwaukee M18 (18V) --------------------------------------
  pack("Milwaukee", "M18", "48-11-1815", "REDLITHIUM CP1.5", 18, 1.5),
  pack("Milwaukee", "M18", "48-11-1820", "REDLITHIUM CP2.0", 18, 2.0),
  pack("Milwaukee", "M18", "48-11-1830", "REDLITHIUM CP3.0", 18, 3.0),
  pack("Milwaukee", "M18", "48-11-1828", "REDLITHIUM XC3.0", 18, 3.0),
  pack("Milwaukee", "M18", "48-11-1850", "REDLITHIUM XC5.0", 18, 5.0),
  pack("Milwaukee", "M18", "48-11-1835", "REDLITHIUM HIGH OUTPUT CP3.0", 18, 3.0),
  pack("Milwaukee", "M18", "48-11-1865", "REDLITHIUM HIGH OUTPUT XC6.0", 18, 6.0),
  pack("Milwaukee", "M18", "48-11-1880", "REDLITHIUM HIGH OUTPUT XC8.0", 18, 8.0),
  pack("Milwaukee", "M18", "48-11-1812", "REDLITHIUM HIGH DEMAND HD12.0", 18, 12.0),
  pack("Milwaukee", "M18", "48-11-1861", "REDLITHIUM FORGE XC6.0", 18, 6.0),
  pack("Milwaukee", "M18", "48-11-1881", "REDLITHIUM FORGE XC8.0", 18, 8.0),
  // -- Milwaukee M12 (12V) --------------------------------------
  pack("Milwaukee", "M12", "48-11-2401", "REDLITHIUM CP1.5", 12, 1.5),
  pack("Milwaukee", "M12", "48-11-2420", "REDLITHIUM CP2.0", 12, 2.0),
  pack("Milwaukee", "M12", "48-11-2425", "REDLITHIUM HIGH OUTPUT CP2.5", 12, 2.5),
  pack("Milwaukee", "M12", "48-11-2402", "REDLITHIUM XC3.0", 12, 3.0),
  pack("Milwaukee", "M12", "48-11-2440", "REDLITHIUM XC4.0", 12, 4.0),
  pack("Milwaukee", "M12", "48-11-2450", "REDLITHIUM HIGH OUTPUT XC5.0", 12, 5.0),
  pack("Milwaukee", "M12", "48-11-2460", "REDLITHIUM XC6.0", 12, 6.0),
  // -- DeWalt 20V MAX (20V) -------------------------------------
  pack("DeWalt", "20V MAX", "DCB201", "20V MAX 1.3Ah", 20, 1.3),
  pack("DeWalt", "20V MAX", "DCB203", "20V MAX Compact 2.0Ah", 20, 2.0),
  pack("DeWalt", "20V MAX", "DCB230", "20V MAX Compact 3.0Ah", 20, 3.0),
  pack("DeWalt", "20V MAX", "DCB204", "20V MAX XR 4.0Ah", 20, 4.0),
  pack("DeWalt", "20V MAX", "DCB205", "20V MAX XR 5.0Ah", 20, 5.0),
  pack("DeWalt", "20V MAX", "DCB206", "20V MAX XR 6.0Ah", 20, 6.0),
  pack("DeWalt", "20V MAX", "DCB208", "20V MAX XR 8.0Ah", 20, 8.0),
  pack("DeWalt", "20V MAX", "DCBP034", "POWERSTACK 1.7Ah", 20, 1.7),
  pack("DeWalt", "20V MAX", "DCBP520", "POWERSTACK 5.0Ah", 20, 5.0),
  // -- DeWalt FLEXVOLT (20V/60V; filed at 20V, its tool voltage
  //    on 20V MAX tools) ----------------------------------------
  pack("DeWalt", "FLEXVOLT", "DCB546", "FLEXVOLT 6.0Ah", 20, 6.0),
  pack("DeWalt", "FLEXVOLT", "DCB609", "FLEXVOLT 9.0Ah", 20, 9.0),
  pack("DeWalt", "FLEXVOLT", "DCB612", "FLEXVOLT 12.0Ah", 20, 12.0),
  pack("DeWalt", "FLEXVOLT", "DCB615", "FLEXVOLT 15.0Ah", 20, 15.0),
  // -- DeWalt 12V MAX (12V) -------------------------------------
  pack("DeWalt", "12V MAX", "DCB122", "12V MAX 2.0Ah", 12, 2.0),
  pack("DeWalt", "12V MAX", "DCB124", "12V MAX 3.0Ah", 12, 3.0),
  pack("DeWalt", "12V MAX", "DCB126", "12V MAX 5.0Ah", 12, 5.0),
  // -- Makita LXT (18V) ------------------------------------------
  pack("Makita", "LXT 18V", "BL1815N", "LXT 1.5Ah", 18, 1.5),
  pack("Makita", "LXT 18V", "BL1820B", "LXT 2.0Ah", 18, 2.0),
  pack("Makita", "LXT 18V", "BL1830B", "LXT 3.0Ah", 18, 3.0),
  pack("Makita", "LXT 18V", "BL1840B", "LXT 4.0Ah", 18, 4.0),
  pack("Makita", "LXT 18V", "BL1850B", "LXT 5.0Ah", 18, 5.0),
  pack("Makita", "LXT 18V", "BL1860B", "LXT 6.0Ah", 18, 6.0),
  // -- Makita XGT (40V) ------------------------------------------
  pack("Makita", "XGT 40V", "BL4020", "XGT 2.0Ah", 40, 2.0),
  pack("Makita", "XGT 40V", "BL4025", "XGT 2.5Ah", 40, 2.5),
  pack("Makita", "XGT 40V", "BL4040", "XGT 4.0Ah", 40, 4.0),
  pack("Makita", "XGT 40V", "BL4050F", "XGT 5.0Ah", 40, 5.0),
  pack("Makita", "XGT 40V", "BL4080F", "XGT 8.0Ah", 40, 8.0),
  // -- Makita CXT (12V) ------------------------------------------
  pack("Makita", "CXT 12V", "BL1021B", "CXT 2.0Ah", 12, 2.0),
  pack("Makita", "CXT 12V", "BL1041B", "CXT 4.0Ah", 12, 4.0),
  // -- Ryobi ONE+ (18V) ------------------------------------------
  pack("Ryobi", "ONE+ 18V", "PBP001", "ONE+ 1.5Ah", 18, 1.5),
  pack("Ryobi", "ONE+ 18V", "PBP002", "ONE+ 2.0Ah", 18, 2.0),
  pack("Ryobi", "ONE+ 18V", "PBP004", "ONE+ 4.0Ah", 18, 4.0),
  pack("Ryobi", "ONE+ 18V", "PBP005", "ONE+ HIGH PERFORMANCE 4.0Ah", 18, 4.0),
  pack("Ryobi", "ONE+ 18V", "PBP006", "ONE+ HIGH PERFORMANCE 6.0Ah", 18, 6.0),
  pack("Ryobi", "ONE+ 18V", "PBP007", "ONE+ HIGH PERFORMANCE 8.0Ah", 18, 8.0),
  // -- Bosch (18V + 12V) ------------------------------------------
  pack("Bosch", "18V", "GBA18V20", "18V 2.0Ah", 18, 2.0),
  pack("Bosch", "18V", "GBA18V40", "CORE18V 4.0Ah", 18, 4.0),
  pack("Bosch", "18V", "GBA18V80", "CORE18V 8.0Ah", 18, 8.0),
  pack("Bosch", "18V", "GBA18V120", "CORE18V 12.0Ah", 18, 12.0),
  pack("Bosch", "12V", "BAT414", "12V Max 2.0Ah", 12, 2.0),
  pack("Bosch", "12V", "GBA12V30", "12V Max 3.0Ah", 12, 3.0),
  pack("Bosch", "12V", "GBA12V60", "12V Max 6.0Ah", 12, 6.0),
  // -- Hilti Nuron (22V) ------------------------------------------
  pack("Hilti", "Nuron", "B 22-55", "Nuron B 22-55 (2.6Ah)", 22, 2.6),
  pack("Hilti", "Nuron", "B 22-85", "Nuron B 22-85 (4.0Ah)", 22, 4.0),
  pack("Hilti", "Nuron", "B 22-170", "Nuron B 22-170 (8.0Ah)", 22, 8.0),
  pack("Hilti", "Nuron", "B 22-255", "Nuron B 22-255 (12.0Ah)", 22, 12.0),
  // -- Craftsman V20 (20V) ----------------------------------------
  pack("Craftsman", "V20", "CMCB201", "V20 1.3Ah", 20, 1.3),
  pack("Craftsman", "V20", "CMCB202", "V20 2.0Ah", 20, 2.0),
  pack("Craftsman", "V20", "CMCB204", "V20 4.0Ah", 20, 4.0),
  pack("Craftsman", "V20", "CMCB205", "V20 5.0Ah", 20, 5.0),
  pack("Craftsman", "V20", "CMCB206", "V20 6.0Ah", 20, 6.0),
  // -- Kobalt (24V) -----------------------------------------------
  pack("Kobalt", "24V", "KB 224-03", "24V Max 2.0Ah", 24, 2.0),
  pack("Kobalt", "24V", "KB 424-03", "24V Max 4.0Ah", 24, 4.0),
  // -- EGO POWER+ (56V) -------------------------------------------
  pack("EGO", "POWER+ 56V", "BA1400T", "POWER+ 2.5Ah", 56, 2.5),
  pack("EGO", "POWER+ 56V", "BA2800T", "POWER+ 5.0Ah", 56, 5.0),
  pack("EGO", "POWER+ 56V", "BA4200T", "POWER+ 7.5Ah", 56, 7.5),
  pack("EGO", "POWER+ 56V", "BA5600T", "POWER+ 10.0Ah", 56, 10.0),
  pack("EGO", "POWER+ 56V", "BA6720T", "POWER+ 12.0Ah", 56, 12.0),
  // -- FLEX (24V) ---------------------------------------------------
  pack("FLEX", "24V", "FX0111", "24V Stacked Lithium 2.5Ah", 24, 2.5),
  pack("FLEX", "24V", "FX0121", "24V Stacked Lithium 5.0Ah", 24, 5.0),
  // -- Ridgid (18V) -------------------------------------------------
  pack("Ridgid", "18V", "AC8400802", "18V 2.0Ah", 18, 2.0),
  pack("Ridgid", "18V", "AC840040", "18V MAX Output 4.0Ah", 18, 4.0),
  pack("Ridgid", "18V", "AC840060", "18V MAX Output 6.0Ah", 18, 6.0),
  pack("Ridgid", "18V", "AC840080", "18V MAX Output 8.0Ah", 18, 8.0),
  // -- Metabo HPT MultiVolt -----------------------------------------
  pack("Metabo HPT", "MultiVolt", "BSL36A18", "MultiVolt 36V/18V 4.0Ah (8.0Ah at 18V)", 18, 8.0),
  pack("Metabo HPT", "18V", "BSL1820", "18V 2.0Ah", 18, 2.0),
  // -- Skil PWRCore (20V) -------------------------------------------
  pack("Skil", "PWRCore 20", "BY519702", "PWRCore 20 2.0Ah", 20, 2.0),
  pack("Skil", "PWRCore 20", "BY519703", "PWRCore 20 4.0Ah", 20, 4.0),
  pack("Skil", "PWRCore 20", "BY519705", "PWRCore 20 5.0Ah", 20, 5.0),
  // -- Greenworks (40V) ---------------------------------------------
  pack("Greenworks", "40V", "29472", "40V G-MAX 2.0Ah", 40, 2.0),
  pack("Greenworks", "40V", "29462", "40V G-MAX 4.0Ah", 40, 4.0),
  // -- Porter-Cable (20V) -------------------------------------------
  pack("Porter-Cable", "20V MAX", "PCC680L", "20V MAX 1.3Ah", 20, 1.3),
  pack("Porter-Cable", "20V MAX", "PCC685L", "20V MAX 4.0Ah", 20, 4.0),
  // -- Black+Decker (20V) -------------------------------------------
  pack("Black+Decker", "20V MAX", "LBXR20", "20V MAX 1.5Ah", 20, 1.5),
  pack("Black+Decker", "20V MAX", "LBXR4020", "20V MAX 4.0Ah", 20, 4.0),
];

/** The display name a pick composes into the battery's name
 *  field: brand + platform + pack label, e.g. "Milwaukee M18
 *  REDLITHIUM XC5.0". */
export function batteryCatalogName(entry: BatteryCatalogEntry): string {
  return `${entry.brand} ${entry.platform} ${entry.label}`;
}

/** Case-insensitive substring search over everything a user
 *  might type: brand, platform, model number, pack label. */
export function searchBatteryCatalog(query: string): BatteryCatalogEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return BATTERY_CATALOG;
  return BATTERY_CATALOG.filter((entry) =>
    [entry.brand, entry.platform, entry.model, entry.label]
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}
