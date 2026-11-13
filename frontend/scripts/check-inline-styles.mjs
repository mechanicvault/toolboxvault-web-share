#!/usr/bin/env node
/**
 * Inline-style ratchet — Deep Audit F3-01.
 *
 * The design-system rule ("no inline styles for token-covered properties")
 * used to live only in docs, so the count grew to ~2,300 unchecked. This
 * script puts the rule in the build: it counts inline style attributes in
 * the frontend source and FAILS when the count exceeds the recorded
 * baseline in frontend/inline-style-baseline.txt. The baseline only ever
 * moves DOWN, in the same commit that converts styles to the token system
 * (the script prints a nudge when the count has dropped below it).
 *
 * Pattern counted: every literal occurrence of `style={{` in `.tsx` files
 * under `src` (searched recursively)
 * — i.e. a JSX style attribute whose value is an inline object literal.
 * Verified at baseline time (HEAD 20f0eab): the flexible spellings
 * (`style = {{`, whitespace/newlines between `style`, `=` and `{{`) occur
 * zero times in the tree, and the flexible regex counts exactly the same
 * total as the literal pattern, so the literal pattern misses nothing
 * today and stays trivially reproducible by hand:
 *
 *   grep -r -o 'style={{' frontend/src --include='*.tsx' | wc -l
 *
 * What the pattern deliberately does NOT catch (documented, accepted):
 *   - `style={someVariable}` — a style object defined elsewhere and passed
 *     by reference (48 occurrences at baseline). These are usually shared
 *     constants defined once, not per-element bypasses.
 *   - `React.CSSProperties` objects declared as module constants and then
 *     passed by reference (same case as above).
 * If a new bypass spelling ever appears, extend PATTERN and re-baseline
 * deliberately in the same commit.
 *
 * No dependencies: runs in the node:20-slim Docker build stage, in CI,
 * and locally via `npm run check:inline-styles` (also chained into
 * `npm run build`).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const srcRoot = join(frontendRoot, "src");
const baselinePath = join(frontendRoot, "inline-style-baseline.txt");
const PATTERN = "style={{";

function readBaseline() {
  const raw = readFileSync(baselinePath, "utf8");
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    const n = Number.parseInt(trimmed, 10);
    if (Number.isInteger(n) && String(n) === trimmed) return n;
  }
  console.error(
    `check:inline-styles — could not find a baseline number in ${baselinePath}`,
  );
  process.exit(2);
}

function* walkTsx(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* walkTsx(full);
    else if (entry.endsWith(".tsx")) yield full;
  }
}

let count = 0;
let files = 0;
for (const file of walkTsx(srcRoot)) {
  files += 1;
  const text = readFileSync(file, "utf8");
  let idx = text.indexOf(PATTERN);
  while (idx !== -1) {
    count += 1;
    idx = text.indexOf(PATTERN, idx + PATTERN.length);
  }
}

const baseline = readBaseline();

if (count > baseline) {
  console.error(
    `check:inline-styles — FAIL: inline styles increased ${baseline} → ${count} ` +
      `(baseline ${baseline}, +${count - baseline}).\n` +
      `Inline \`style={{…}}\` blocks bypass the design-token system (Deep Audit F3-01).\n` +
      `Convert the new style(s) to the token system (classes / CSS custom properties).\n` +
      `If this is a deliberate design-system change, raise the baseline in\n` +
      `frontend/inline-style-baseline.txt in the same commit and say why.`,
  );
  process.exit(1);
}

console.log(
  `check:inline-styles — OK: ${count} inline style(s) across src ` +
    `(${files} .tsx files scanned; baseline ${baseline}).`,
);
if (count < baseline) {
  console.log(
    `check:inline-styles — the count dropped by ${baseline - count}. ` +
      `Lower the baseline in frontend/inline-style-baseline.txt to ${count} ` +
      `in this commit so the ratchet tightens.`,
  );
}
