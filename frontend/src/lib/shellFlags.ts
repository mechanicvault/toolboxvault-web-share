/**
 * SHELL FLAGS — shell-level rendering switches, each with an
 * owner directive behind it. One flag, one seat: a flag here is
 * read in exactly the place that renders the thing it gates, so
 * flipping it is the whole change.
 */

/**
 * SIDE PANEL (owner directive, 2026-11-01): the shell's second
 * column — the full-height panel between the rail and the page
 * content (per-route section panels from the panel registry,
 * plus the settings tree that takes the same slot over on
 * /settings routes) — is REMOVED from rendering. Ryan's words:
 * the panel "doesn't seem to offer any real reasoning on the
 * website." The removal is deliberately RENDERING-ONLY and
 * reversible:
 *
 *  - Every panel component (components/panels/*), the panel
 *    registry, the HomePanel edit bridge, and every user's
 *    SAVED panel customization (the home layout's "panel"
 *    entry: panel_hidden / panel_order / panel_stat_order in
 *    user_page_layouts) stay exactly as they are — nothing is
 *    deleted, migrated, or rewritten.
 *  - AppShell reads this flag: while it is false the aside
 *    never renders (and the phone panel toggle with it), and
 *    App.tsx turns the rail's Settings item into a plain link
 *    to /settings, since there is no panel for its in-place
 *    tree flip to land in.
 *  - The one piece of panel content Ryan wanted kept — the
 *    Home panel's account box (account number, group,
 *    location) — was RELOCATED, not removed with the panel:
 *    it lives permanently in the user menu's header (UserMenu),
 *    independent of this flag.
 *
 * RESTORE (the whole procedure): set this constant to `true`,
 * rebuild, redeploy. The panel returns on every route with
 * each user's saved sections and stat picks exactly as they
 * left them — no data step exists, because no data ever moved.
 */
export const SIDE_PANEL_ENABLED = false;
