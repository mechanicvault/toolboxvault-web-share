/**
 * The converter (owner order 2026-11-08): "a form that can
 * convert normal reading to other readings — like inH2O to psi,
 * liters to pints, gallons to pints, pressures, volumes, volts,
 * amps, etc." Client-side and instant; no account, no server
 * round-trip. Five unit families convert through a base unit;
 * temperature is affine and handled on its own path; the
 * electrical section is an Ohm's-law solver — fill in any two
 * of volts / amps / ohms / watts and the other two are worked
 * out.
 *
 * Factors are written as the physical constants they are, so
 * the spot checks read off the definitions: 1 gal = 8 pt
 * (3.78541 / 0.473176), 1 L = 2.11338 pt, 1 psi = 27.6799 inH2O,
 * 100 °C = 212 °F, 12 V x 2 A = 24 W.
 *
 * ONE IMPLEMENTATION, TWO HOSTS (converter widget lane, owner
 * 2026-11-08): the interactive body is `ConverterBody`, shared
 * by the Downloads → Documents panel below and the Home
 * dashboard widget (homeWidgets' `converter` def) — same
 * component, same math, no forked copy to drift. The variant
 * only changes the density class on the root; the panel adds
 * its own section chrome (title + sub) around the body.
 */

import { useMemo, useState } from "react";

import { useT } from "../../i18n/LocaleContext";
import type { DictKey } from "../../i18n/dictionaries";
import type { BlockSize } from "../../lib/usePageLayout";
import "./converter.css";

interface Unit {
  id: string;
  nameKey: DictKey;
  symbol: string;
  /** Multiply a value in this unit by `toBase` to get the base unit. */
  toBase: number;
}

interface Family {
  id: string;
  labelKey: DictKey;
  base: string;
  units: Unit[];
}

const FAMILIES: Family[] = [
  {
    id: "pressure",
    labelKey: "downloads.conv.kind.pressure",
    base: "psi",
    units: [
      { id: "psi", nameKey: "downloads.conv.unit.psi", symbol: "psi", toBase: 1 },
      { id: "inh2o", nameKey: "downloads.conv.unit.inh2o", symbol: "inH₂O", toBase: 1 / 27.6799 },
      { id: "inhg", nameKey: "downloads.conv.unit.inhg", symbol: "inHg", toBase: 1 / 2.03602 },
      { id: "kpa", nameKey: "downloads.conv.unit.kpa", symbol: "kPa", toBase: 1 / 6.89476 },
      { id: "bar", nameKey: "downloads.conv.unit.bar", symbol: "bar", toBase: 1 / 0.0689476 },
    ],
  },
  {
    id: "volume",
    labelKey: "downloads.conv.kind.volume",
    base: "l",
    units: [
      { id: "l", nameKey: "downloads.conv.unit.l", symbol: "L", toBase: 1 },
      { id: "pt", nameKey: "downloads.conv.unit.pt", symbol: "pt", toBase: 0.473176 },
      { id: "qt", nameKey: "downloads.conv.unit.qt", symbol: "qt", toBase: 0.946353 },
      { id: "gal", nameKey: "downloads.conv.unit.gal", symbol: "gal", toBase: 3.78541 },
      { id: "ml", nameKey: "downloads.conv.unit.ml", symbol: "mL", toBase: 0.001 },
      { id: "floz", nameKey: "downloads.conv.unit.floz", symbol: "fl oz", toBase: 0.0295735 },
    ],
  },
  {
    id: "length",
    labelKey: "downloads.conv.kind.length",
    base: "m",
    units: [
      { id: "in", nameKey: "downloads.conv.unit.in", symbol: "in", toBase: 0.0254 },
      { id: "mm", nameKey: "downloads.conv.unit.mm", symbol: "mm", toBase: 0.001 },
      { id: "ft", nameKey: "downloads.conv.unit.ft", symbol: "ft", toBase: 0.3048 },
      { id: "m", nameKey: "downloads.conv.unit.m", symbol: "m", toBase: 1 },
    ],
  },
  {
    id: "torque",
    labelKey: "downloads.conv.kind.torque",
    base: "nm",
    units: [
      { id: "ftlb", nameKey: "downloads.conv.unit.ftlb", symbol: "ft-lb", toBase: 1.35582 },
      { id: "inlb", nameKey: "downloads.conv.unit.inlb", symbol: "in-lb", toBase: 0.112985 },
      { id: "nm", nameKey: "downloads.conv.unit.nm", symbol: "Nm", toBase: 1 },
    ],
  },
];

const TEMP_UNITS = [
  { id: "f", nameKey: "downloads.conv.unit.f" as DictKey, symbol: "°F" },
  { id: "c", nameKey: "downloads.conv.unit.c" as DictKey, symbol: "°C" },
];

function fmt(n: number): string {
  if (!Number.isFinite(n)) return "—";
  const rounded = Number.parseFloat(n.toPrecision(6));
  return rounded.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

type ElecField = "v" | "a" | "r" | "w";

const ELEC_KEYS: Record<ElecField, DictKey> = {
  v: "downloads.conv.volts",
  a: "downloads.conv.amps",
  r: "downloads.conv.ohms",
  w: "downloads.conv.watts",
};

/** Ohm's law: from any two knowns, the whole quartet. Returns
 * null when the pair can't solve (a zero where a divisor is
 * needed) — the panel then shows dashes, never NaNs. */
function solveElec(known: Partial<Record<ElecField, number>>): Record<ElecField, number> | null {
  const { v, a, r, w } = known;
  let V: number, I: number, R: number, P: number;
  if (v !== undefined && a !== undefined) {
    V = v; I = a; R = I === 0 ? NaN : V / I; P = V * I;
  } else if (v !== undefined && r !== undefined) {
    V = v; R = r; I = R === 0 ? NaN : V / R; P = I * V;
  } else if (v !== undefined && w !== undefined) {
    V = v; P = w; I = V === 0 ? NaN : P / V; R = I === 0 ? NaN : V / I;
  } else if (a !== undefined && r !== undefined) {
    I = a; R = r; V = I * R; P = I * I * R;
  } else if (a !== undefined && w !== undefined) {
    I = a; P = w; V = I === 0 ? NaN : P / I; R = I === 0 ? NaN : V / I;
  } else if (r !== undefined && w !== undefined) {
    R = r; P = w;
    if (R <= 0 || P < 0) return null;
    V = Math.sqrt(P * R); I = V / R;
  } else {
    return null;
  }
  const out = { v: V, a: I, r: R, w: P };
  return Object.values(out).every((n) => Number.isFinite(n) && n >= 0) ? out : null;
}

/**
 * The converter's interactive body — the kind picker, the
 * value/from pair with its live result rows, and the Ohm's-law
 * quartet. `variant` is density only ("panel" on Downloads,
 * "widget" on Home); `size` is the host widget's grid width
 * when there is one (the quartet runs 2×2 at half width).
 */
export function ConverterBody({
  variant = "panel",
  size,
}: {
  variant?: "panel" | "widget";
  size?: BlockSize;
}) {
  const t = useT();
  const [kind, setKind] = useState<string>("pressure");
  const [value, setValue] = useState<string>("");
  const [fromUnit, setFromUnit] = useState<string>("psi");
  const [elec, setElec] = useState<Record<ElecField, string>>({ v: "", a: "", r: "", w: "" });
  const [elecEdited, setElecEdited] = useState<ElecField[]>([]);

  const family = FAMILIES.find((f) => f.id === kind);
  const isTemp = kind === "temperature";
  const isElec = kind === "electrical";

  function pickKind(next: string) {
    setKind(next);
    setValue("");
    if (next === "temperature") setFromUnit("f");
    else if (next !== "electrical") {
      const fam = FAMILIES.find((f) => f.id === next);
      if (fam) setFromUnit(fam.base);
    }
  }

  const results = useMemo(() => {
    const num = Number.parseFloat(value);
    if (value.trim() === "" || Number.isNaN(num)) return null;
    if (isTemp) {
      const celsius = fromUnit === "f" ? ((num - 32) * 5) / 9 : num;
      return TEMP_UNITS.map((u) => ({
        name: t(u.nameKey),
        symbol: u.symbol,
        out: u.id === "c" ? celsius : (celsius * 9) / 5 + 32,
        isFrom: u.id === fromUnit,
      }));
    }
    if (!family) return null;
    const from = family.units.find((u) => u.id === fromUnit) ?? family.units[0]!;
    const baseValue = num * from.toBase;
    return family.units.map((u) => ({
      name: t(u.nameKey),
      symbol: u.symbol,
      out: baseValue / u.toBase,
      isFrom: u.id === from.id,
    }));
  }, [value, fromUnit, family, isTemp, t]);

  const elecResult = useMemo(() => {
    const known: Partial<Record<ElecField, number>> = {};
    const sources: ElecField[] = [];
    for (const field of elecEdited) {
      const n = Number.parseFloat(elec[field]);
      if (elec[field].trim() !== "" && !Number.isNaN(n) && n >= 0) {
        known[field] = n;
        sources.push(field);
      }
      if (sources.length === 2) break;
    }
    if (sources.length < 2) return null;
    const solved = solveElec(known);
    return solved ? { solved, sources } : null;
  }, [elec, elecEdited]);

  function editElec(field: ElecField, next: string) {
    setElec((prev) => ({ ...prev, [field]: next }));
    setElecEdited((prev) => [field, ...prev.filter((f) => f !== field)]);
  }

  const kinds: { id: string; labelKey: DictKey }[] = [
    ...FAMILIES.map((f) => ({ id: f.id, labelKey: f.labelKey })),
    { id: "temperature", labelKey: "downloads.conv.kind.temperature" as DictKey },
    { id: "electrical", labelKey: "downloads.conv.kind.electrical" as DictKey },
  ];

  return (
    <div
      className={[
        "conv-root",
        `conv-root--${variant}`,
        size ? `conv-size-${size}` : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="conv-kinds" role="group" aria-label={t("downloads.conv.title")}>
        {kinds.map((k) => (
          <button
            key={k.id}
            type="button"
            className={kind === k.id ? "conv-kind conv-selected" : "conv-kind"}
            aria-pressed={kind === k.id}
            onClick={() => pickKind(k.id)}
          >
            {t(k.labelKey)}
          </button>
        ))}
      </div>

      {!isElec && (
        <div className="conv-body">
          <div className="conv-inputs">
            <label className="conv-field">
              <span>{t("downloads.conv.value")}</span>
              <input
                type="number"
                inputMode="decimal"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="0"
              />
            </label>
            <label className="conv-field">
              <span>{t("downloads.conv.from")}</span>
              <select value={fromUnit} onChange={(e) => setFromUnit(e.target.value)}>
                {(isTemp ? TEMP_UNITS : family!.units).map((u) => (
                  <option key={u.id} value={u.id}>
                    {t(u.nameKey)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {results && (
            <ul className="conv-results">
              {results.map((r) => (
                <li key={r.symbol} className={r.isFrom ? "conv-from-row" : undefined}>
                  <span>{r.name}</span>
                  <strong>
                    {fmt(r.out)} {r.symbol}
                  </strong>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isElec && (
        <div className="conv-body">
          <p className="conv-hint">{t("downloads.conv.elecHint")}</p>
          <div className="conv-elec">
            {(Object.keys(ELEC_KEYS) as ElecField[]).map((field) => {
              const derived =
                elecResult !== null && !elecResult.sources.includes(field);
              return (
                <label key={field} className="conv-field">
                  <span>{t(ELEC_KEYS[field])}</span>
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    value={
                      derived && elecResult
                        ? fmt(elecResult.solved[field])
                        : elec[field]
                    }
                    readOnly={derived}
                    className={derived ? "conv-derived" : undefined}
                    onChange={(e) => editElec(field, e.target.value)}
                  />
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/** The Downloads → Documents panel: the shared body in its
 *  section chrome (title + sub), exactly as it has always
 *  rendered on the page. */
export function DownloadsConverter() {
  const t = useT();
  return (
    <section className="dl-panel dl-converter" aria-label={t("downloads.conv.title")}>
      <h3>{t("downloads.conv.title")}</h3>
      <p className="dl-step-note">{t("downloads.conv.sub")}</p>
      <ConverterBody variant="panel" />
    </section>
  );
}
