import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/* The Downloads page's own entry document (social-share fix,
 * owner order, 2026-11-08): the app is one SPA document, so a
 * shared /downloads link used to preview with the SITE's Open
 * Graph tags. This plugin derives dist/downloads.html from the
 * built index.html with only the head's share/description meta
 * swapped for the Downloads page's own (title, description,
 * canonical URL, and its own share card) — the boot script and
 * body stay byte-identical, so the CSP hash pin on the boot
 * script is unaffected. nginx serves this file for exactly
 * /downloads (see nginx.conf.template). Every replacement is
 * asserted: if index.html's meta ever drifts, the build fails
 * loudly instead of silently shipping generic tags again. */
const DOWNLOADS_DESCRIPTION =
  "Free shop documents and worksheets, a built-in unit converter, and free 3D print files shared by members — no account, no email, just download.";

const DOWNLOADS_REPLACEMENTS: Array<[string, string]> = [
  ["<title>Toolbox Vault</title>", "<title>Free Downloads — Toolbox Vault</title>"],
  [
    '<meta property="og:title" content="Toolbox Vault — Organize. Protect. Recover." />',
    '<meta property="og:title" content="Free Downloads — Toolbox Vault" />',
  ],
  [
    'content="Toolbox Vault — the tool inventory built by a mechanic, for mechanics. Document every tool with photos, serials, and values; be ready for insurance claims, repairs, and recovery. Free to start."',
    `content="${DOWNLOADS_DESCRIPTION}"`,
  ],
  [
    'content="Every tool documented, provable, and recoverable: inventory, insurance-ready records, guided claims, dealer network, and reports. Free to start — no card required."',
    `content="${DOWNLOADS_DESCRIPTION}"`,
  ],
  [
    '<meta property="og:url" content="https://toolboxvault.com/" />',
    '<meta property="og:url" content="https://toolboxvault.com/downloads" />',
  ],
  [
    '<meta property="og:image" content="https://toolboxvault.com/brand/og-card.png" />',
    '<meta property="og:image" content="https://toolboxvault.com/brand/og-downloads.png" />',
  ],
  [
    '<meta property="og:image:alt" content="Toolbox Vault — Organize. Protect. Recover." />',
    '<meta property="og:image:alt" content="Free Downloads — Toolbox Vault" />',
  ],
  [
    '<meta name="twitter:title" content="Toolbox Vault — Organize. Protect. Recover." />',
    '<meta name="twitter:title" content="Free Downloads — Toolbox Vault" />',
  ],
  [
    'content="The tool inventory built by a mechanic, for mechanics. Free to start — no card required."',
    `content="${DOWNLOADS_DESCRIPTION}"`,
  ],
  [
    '<meta name="twitter:image" content="https://toolboxvault.com/brand/og-card.png" />',
    '<meta name="twitter:image" content="https://toolboxvault.com/brand/og-downloads.png" />',
  ],
];

function downloadsHtmlPlugin(): Plugin {
  return {
    name: "downloads-html",
    apply: "build",
    closeBundle() {
      const root = fileURLToPath(new URL(".", import.meta.url));
      const indexPath = resolve(root, "dist/index.html");
      let html = readFileSync(indexPath, "utf8");
      for (const [from, to] of DOWNLOADS_REPLACEMENTS) {
        if (!html.includes(from)) {
          throw new Error(`downloads-html: pattern not found in index.html: ${from}`);
        }
        html = html.replace(from, to);
      }
      writeFileSync(resolve(root, "dist/downloads.html"), html);
    },
  };
}

// Dev only: proxy /api to a locally-running backend.
// In production (docker), nginx handles /api -> api:8000.
export default defineConfig({
  plugins: [react(), downloadsHtmlPlugin()],
  build: {
    // Deep audit F3-04: never inline assets as base64 data-URIs.
    // The Steel theme slices were inlined into the one render-blocking
    // stylesheet (155 KB of base64 that brotli cannot shrink and that
    // can never be cached separately). As files they are hashed,
    // immutable-cached /assets/* like every other build asset.
    assetsInlineLimit: () => false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
